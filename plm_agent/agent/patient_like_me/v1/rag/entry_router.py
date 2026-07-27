"""
PLM entry router.

Decides which medical processing path a user input should take:
  - full_case          → patient case with relatively complete clinical info
  - quick_guideline_qa → guideline-level / population-level question (no specific patient)
  - insufficient_case  → looks like individualized question but info too thin to answer safely

Plus a sub-router for full_case inputs:
  - full_report      → user wants a complete diagnostic & treatment report
  - case_question_qa → user has a complete case but asks one/several specific bounded questions

All routing decisions go through Gemini Flash with strict JSON schema output.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


def _safe_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# ───────── Deterministic heuristic rules ─────────
#
# The LLM router (even at temperature=0) occasionally misroutes population-
# level guideline questions to full_case (which then incurs ~400s of full
# pipeline cost). We pre-screen the most clearly identifiable cases with
# regex rules so the LLM only sees genuinely ambiguous input.
#
# Heuristics are intentionally conservative: they only fire on the cleanest
# signals. Anything else goes to the LLM as before.

# Strong markers that the input describes a specific patient. Each pattern
# is by itself enough to suggest "there is a patient" — multiple is even
# stronger. Note: "患者" alone is NOT a marker because population-level
# questions often contain it (e.g. "哪些患者需要..."). We only flag patient
# noun phrases that show concrete demographics or clinical state.
_PATIENT_SIGNALS = re.compile(
    r"(?:"
    r"\d+\s*岁"                               # 65岁 / 65 岁
    r"|男，|女，"                              # 男， / 女，
    r"|患者(?:男|女|，|为|是|目前|当前)"        # 患者男/患者女/患者，
    r"|主诉|查体|既往(?:史|心|肝|肾)"          # 主诉/查体/既往史
    r"|ECOG|KPS|PS\s*\d|IPI\s*评分|危险分层"   # PS评分
    r"|确诊"                                  # 确诊
    r"|cT\d|cN\d|cM\d|TNM"                    # TNM
    r"|HbA1c|LDH|WBC|PLT|Hb|ALT|AST|肌酐|血肌酐"
    r"|HBV[- ]?DNA|HBsAg|EGFR|TP53|BCR|MYC|PD-L1"
    r"|入院|门诊|住院|急诊"
    r"|×\s*10[⁹^9]"                          # ×10⁹/L
    r"|U/L|mmol/L|mg/dL|g/L|/L"               # 单位
    r")"
)

# Strong markers that the input is a population/guideline-level question.
# These are *question shapes*, not just disease names.
_GUIDELINE_QUESTION_SIGNALS = re.compile(
    r"(?:"
    r"哪些情况"                                # 哪些情况需要...
    r"|哪些患者"                              # 哪些患者...
    r"|哪些人群"
    r"|什么样的(?:患者|人群|情况|人)"
    r"|什么情况下"
    r"|什么时候(?:需要|应该|可以)"
    r"|何时(?:需要|应该|考虑)"
    r"|有什么特征"
    r"|适应证(?:是什么|有哪些)?"               # 适应证 / 适应证是什么
    r"|适应症(?:是什么|有哪些)?"
    r"|推荐人群"
    r"|预防指征"
    r"|(?:一线|二线|三线|首选)\s*(?:推荐|治疗|方案)" # 一线推荐方案 / 一线治疗
    r"|怎么(?:判断|定义|分类|筛查|诊断|做)"
    r"|如何(?:判断|定义|分类|筛查|诊断|进行)"
    r"|该怎么做"                              # 该怎么做
    r"|指南(?:推荐|指出|建议|要求)"
    r")"
)


def _heuristic_pre_route(query: str) -> dict | None:
    """Apply deterministic rules. Return a routing dict (no LLM call) if a
    rule fires; otherwise None so the LLM router runs.

    Currently only fires for the clearest ``quick_guideline_qa`` shape:
    short input + a population/guideline-question phrase + no patient signals.
    """
    if not query:
        return None
    # Keep heuristics tight: only short, guideline-shaped questions with no
    # patient markers can short-circuit. Anything > 200 chars or with a
    # patient signal falls through to the LLM.
    if len(query) > 200:
        return None
    if _PATIENT_SIGNALS.search(query):
        return None
    if not _GUIDELINE_QUESTION_SIGNALS.search(query):
        return None

    logger.info("[entry_router] heuristic→quick_guideline_qa  query=%r", query[:120])
    return {
        "route": "quick_guideline_qa",
        "retrieval_query": query,
        "missing_information": [],
        "reason": "heuristic: guideline-level question without patient context",
    }


async def _structured_call(sys_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Lightweight JSON call for the entry router. Uses Gemini 3.5 Flash
    with json_mode only (no response_schema) — bypassing the schema-bound
    path that previously caused the router to fall back to full_case
    on every Pro call. The router validates route/mode against its
    allowed enums in Python, so we lose nothing by dropping the
    schema-level enforcement.

    The schema argument is accepted for compatibility / future use but is
    not forwarded to the LLM.
    """
    import json as _json

    from agent.patient_like_me.v1.rag.workflow import _call_llm, _gemini_flash

    llm = _gemini_flash()
    try:
        raw = await _call_llm(
            llm,
            sys_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            json_mode=True,
        )
    except Exception:
        logger.exception("[entry_router] LLM call raised; returning empty dict")
        return {}

    text = (raw or "").strip()
    if text.startswith("```"):
        # strip leading ```json / ``` and trailing ```
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if not text:
        return {}
    try:
        return _json.loads(text)
    except Exception:
        logger.warning("[entry_router] JSON parse failed; raw=%r", text[:300])
        return {}


async def route_entry(query: str) -> dict:
    """Run the top-level entry router.

    Returns a dict with keys: route, retrieval_query, missing_information, reason.
    Falls back to ``full_case`` (safe default) on any failure.
    """
    query = (query or "").strip()
    fallback = {
        "route": "full_case",
        "retrieval_query": "",
        "missing_information": [],
        "reason": "router_fallback",
    }
    if not query:
        return fallback

    # ── Deterministic fast path. Skips the LLM for very clean inputs. ──
    heuristic = _heuristic_pre_route(query)
    if heuristic is not None:
        return heuristic

    try:
        result = await _structured_call(
            prompts.ENTRY_ROUTER_SYSTEM,
            prompts.ENTRY_ROUTER_USER.format(query=query),
            prompts.ENTRY_ROUTER_SCHEMA,
        )
    except Exception:
        logger.exception("[entry_router] structured call failed; using fallback")
        return fallback

    if not isinstance(result, dict) or "route" not in result:
        logger.warning("[entry_router] empty/invalid output, fallback. raw=%s", result)
        return fallback

    route = _safe_str(result.get("route"))
    if route not in {"full_case", "quick_guideline_qa", "insufficient_case"}:
        logger.warning("[entry_router] unknown route=%s; fallback to full_case", route)
        return fallback

    retrieval_query = _safe_str(result.get("retrieval_query"))
    missing_information = result.get("missing_information") or []
    if not isinstance(missing_information, list):
        missing_information = []
    missing_information = [str(x).strip() for x in missing_information if str(x).strip()]
    reason = _safe_str(result.get("reason"))

    return {
        "route": route,
        "retrieval_query": retrieval_query,
        "missing_information": missing_information,
        "reason": reason,
    }


async def route_full_case_mode(query: str) -> dict:
    """Sub-router for inputs already classified as ``full_case``.

    Returns a dict with keys: mode, reason.
    Falls back to ``full_report`` (the safe default) on any failure.
    """
    query = (query or "").strip()
    fallback = {"mode": "full_report", "reason": "router_fallback"}
    if not query:
        return fallback

    try:
        result = await _structured_call(
            prompts.FULL_CASE_SUBROUTER_SYSTEM,
            prompts.FULL_CASE_SUBROUTER_USER.format(query=query),
            prompts.FULL_CASE_SUBROUTER_SCHEMA,
        )
    except Exception:
        logger.exception("[full_case_subrouter] structured call failed; using fallback")
        return fallback

    if not isinstance(result, dict) or "mode" not in result:
        logger.warning("[full_case_subrouter] empty/invalid output, fallback. raw=%s", result)
        return fallback

    mode = _safe_str(result.get("mode"))
    if mode not in {"full_report", "case_question_qa"}:
        logger.warning("[full_case_subrouter] unknown mode=%s; fallback to full_report", mode)
        return fallback

    return {"mode": mode, "reason": _safe_str(result.get("reason"))}


def build_insufficient_response(
    missing_information: list[str],
    query: str,
    token_usage: dict | None = None,
) -> dict:
    """Build the minimal response dict for the insufficient_case path.

    Shape mirrors run_plm_workflow's normal return, so the frontend can branch on
    ``route`` / ``error`` without breaking on missing keys.
    """
    items = [str(x).strip() for x in (missing_information or []) if str(x).strip()]
    if items:
        output = "所提供的病例信息不足以给出安全的诊疗建议，请补充：" + "、".join(items)
    else:
        output = "所提供的病例信息不足以给出安全的诊疗建议，请补充必要的临床信息。"

    return {
        "output": output,
        "route": "insufficient_case",
        "mode": None,
        "error": "INSUFFICIENT_CASE",
        "missing_information": items,
        "patient_info": {},
        "diagnosis_clear": False,
        "path": "insufficient",
        "token_usage": token_usage or {},
        "retrieval_log": {},
        "graph_path": [],
        "primary_organization": None,
        "primary_status": "auto",
        "supplements": [],
        "patient_input_structured": "",
        "kb_evidence": "",
        "kb_used": False,
        "kb_enabled": False,
    }
