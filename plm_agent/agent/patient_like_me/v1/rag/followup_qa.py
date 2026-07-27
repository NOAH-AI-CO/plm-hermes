"""
PLM follow-up QA. Streaming, model-agnostic.

After the user receives a full evidence-based report from ``run_plm_workflow``,
they can ask follow-up questions. This module exposes a single async generator
that yields SSE-style ``(event_name, payload)`` tuples for the HTTP layer to
forward to the frontend.

Design (v2 — adds router & retrieval):

  Phase A (rewrite & route, ~1-2s):
    一次轻量 LLM 调用，完成两件事：
      • 把"那他要怎么用药/剂量呢"等指代型短问重写为完整可理解问题
      • 判定 intent：report_grounded / need_retrieval / out_of_scope

  Phase B (answer):
    根据 intent 走三条路径之一：
      • report_grounded → 用 report_text 流式回答（保留 v1 行为）
      • need_retrieval  → 调 retrieve_guideline_evidence_pack 拉新证据，
                          然后用 FOLLOWUP_QA_WITH_EVIDENCE_* prompt 流式回答
      • out_of_scope    → 跳过 LLM，直接返回标记 + 礼貌兜底文案

  Phase C (post-process):
    Empty-response guard、history 截断、SSE complete 事件统一收尾。

Stateless: 前端每次重传 ``report_text + history + question``。

NOTE: 与 ``agent/sahzu/rag/followup_qa.py`` 必须保持完全对齐（除 docstring 与 import 路径）。
"""
from __future__ import annotations

import json as _json
import logging
import time
from typing import Any, AsyncIterator

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


# ─── Config ───
# 历史 token 预算（中文按 ~4 字符/token 估算，30K chars ≈ 7.5K tokens）。
# Gemini Flash / Claude Sonnet 都至少有 200K context，30K 历史 + 30K 报告 + 8K 证据 还有充足余量。
_MAX_HISTORY_CHARS = 30_000
_MAX_HISTORY_TURNS_HARD_CAP = 20    # 即使每轮很短，最多保留 20 个 user/assistant 对
_REPORT_SUMMARY_MAX_CHARS = 4_000   # router 看到的报告"摘要"——取前 N 字即可（标题+开头一般含核心信息）

_DEFAULT_MODEL = "gemini-3.5-flash"
_OUT_OF_SCOPE_TAG = "[OUT_OF_SCOPE]"
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"

# 当 need_retrieval 时拉证据的预算（避免追问场景拉过多 chunks 撑爆 context）
_FOLLOWUP_RETRIEVAL_MAX_DOCS = 3
_FOLLOWUP_RETRIEVAL_MAX_CHUNKS = 12


# ────────────────────── model registry / adapters ──────────────────────

class _ModelSpec:
    __slots__ = ("loader", "kind", "supports_thinking")

    def __init__(self, loader, kind: str, supports_thinking: bool):
        self.loader = loader
        self.kind = kind  # "gemini" | "claude_thinking" | "claude_plain"
        self.supports_thinking = supports_thinking


def _load_glm52_flash():
    from llm.ali_models import Glm52Flash
    return Glm52Flash()


def _load_claude_sonnet_46_thinking():
    from llm.gcp_models import ClaudeSonnet46Thinking
    return ClaudeSonnet46Thinking()


def _load_claude_sonnet_46():
    from llm.gcp_models import ClaudeSonnet46
    return ClaudeSonnet46()


# 注: kind="gemini" 仅用于走 _stream_chunks 的 stream_call 分支; GLM-5.2 流式协议同形.
_MODEL_REGISTRY: dict[str, _ModelSpec] = {
    "glm-5.2-flash": _ModelSpec(_load_glm52_flash, "gemini", supports_thinking=False),
    "gemini-3.5-flash": _ModelSpec(_load_glm52_flash, "gemini", supports_thinking=False),  # 兼容旧 caller
    "claude-sonnet-4.6": _ModelSpec(_load_claude_sonnet_46, "claude_plain", supports_thinking=True),
}

_CLAUDE_THINKING_LOADER = {
    "claude-sonnet-4.6": _load_claude_sonnet_46_thinking,
}


def _resolve_model(model: str, enable_thinking: bool) -> tuple[Any, str]:
    """Return (llm_instance, kind). Raises ValueError on unknown model."""
    if model not in _MODEL_REGISTRY:
        supported = ", ".join(sorted(_MODEL_REGISTRY))
        raise ValueError(f"Unknown model '{model}'. Supported: {supported}")

    spec = _MODEL_REGISTRY[model]
    if enable_thinking and not spec.supports_thinking:
        raise ValueError(
            f"Model '{model}' does not support enable_thinking=True. "
            f"Set enable_thinking=False or pick another model."
        )

    if enable_thinking and model in _CLAUDE_THINKING_LOADER:
        return _CLAUDE_THINKING_LOADER[model](), "claude_thinking"
    return spec.loader(), spec.kind


# ────────────────────── stream adapter ──────────────────────

async def _stream_chunks(
    llm: Any,
    kind: str,
    sys_prompt: str,
    user_prompt: str,
    enable_thinking: bool,
    thinking_budget: str,
) -> AsyncIterator[tuple[str, str]]:
    """Adapt an LLM's stream_call output to (chunk_type, text) tuples.

    chunk_type is one of {"thinking", "answer"}.
    """
    if kind == "gemini":
        kwargs: dict[str, Any] = {"temperature": 0.0}
        if enable_thinking:
            kwargs["thinking_budget"] = thinking_budget
        async for text in llm.stream_call(
            sys_prompt=sys_prompt, user_prompt=user_prompt, **kwargs
        ):
            # Gemini SDK collapses thinking + answer into a single text stream.
            if text:
                yield "answer", text
        return

    if kind in ("claude_thinking", "claude_plain"):
        in_think = False
        carry = ""
        async for text in llm.stream_call(
            sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=0.0
        ):
            if not text:
                continue
            buf = carry + text
            carry = ""
            while buf:
                if in_think:
                    idx = buf.find(_THINK_CLOSE)
                    if idx < 0:
                        if len(buf) >= len(_THINK_CLOSE):
                            safe = buf[: -len(_THINK_CLOSE) + 1]
                            carry = buf[-len(_THINK_CLOSE) + 1:]
                        else:
                            safe = ""
                            carry = buf
                        if safe:
                            yield "thinking", safe
                        buf = ""
                    else:
                        if idx > 0:
                            yield "thinking", buf[:idx]
                        buf = buf[idx + len(_THINK_CLOSE):]
                        in_think = False
                else:
                    idx = buf.find(_THINK_OPEN)
                    if idx < 0:
                        if len(buf) >= len(_THINK_OPEN):
                            safe = buf[: -len(_THINK_OPEN) + 1]
                            carry = buf[-len(_THINK_OPEN) + 1:]
                        else:
                            safe = ""
                            carry = buf
                        if safe:
                            yield "answer", safe
                        buf = ""
                    else:
                        if idx > 0:
                            yield "answer", buf[:idx]
                        buf = buf[idx + len(_THINK_OPEN):]
                        in_think = True
        if carry:
            yield ("thinking" if in_think else "answer"), carry
        return

    raise ValueError(f"Unsupported adapter kind: {kind}")


# ────────────────────── history helpers ──────────────────────

def _format_history(history: list[dict]) -> str:
    """把 history 转成给 LLM 看的字符串。

    打了 hidden_from_prompt=True 的轮次会被过滤掉 (out_of_scope 的历史保留在 Redis
    供 UI 展示, 但不参与下一轮追问的 prompt, 避免污染上下文)。
    """
    if not history:
        return "（暂无历史对话）"
    lines: list[str] = []
    for turn in history:
        if turn.get("hidden_from_prompt"):
            continue
        role = "用户" if turn.get("role") == "user" else "助手"
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}：{content}")
    return "\n".join(lines) if lines else "（暂无历史对话）"


def _trim_history(history: list[dict]) -> list[dict]:
    """按字符预算从最新一轮往前累加，超过 _MAX_HISTORY_CHARS 截断。

    旧的固定轮数截断不可靠：10 轮短问 vs 1 轮长问 token 差几个数量级。
    """
    if not isinstance(history, list):
        return []

    clean = [
        {
            "role": t.get("role"),
            "content": str(t.get("content") or ""),
            "hidden_from_prompt": bool(t.get("hidden_from_prompt")),
        }
        for t in history
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
    ]
    # 硬上限：再防御性多一道，避免极端情况下输入巨长
    if len(clean) > _MAX_HISTORY_TURNS_HARD_CAP * 2:
        clean = clean[-_MAX_HISTORY_TURNS_HARD_CAP * 2:]

    # 从最新一轮往前累加字符; hidden_from_prompt 的轮次不算预算 (它们不会进 prompt)
    total_chars = 0
    keep_from_idx = 0
    for i in range(len(clean) - 1, -1, -1):
        if clean[i].get("hidden_from_prompt"):
            continue
        total_chars += len(clean[i].get("content", ""))
        if total_chars > _MAX_HISTORY_CHARS:
            keep_from_idx = i + 1
            break

    return clean[keep_from_idx:] if keep_from_idx else clean


def _summarize_report_for_router(report_text: str) -> str:
    """给 router 看的报告摘要：取前 N 字即可（报告标题与开头通常含主题/患者基本信息）。"""
    if not report_text:
        return "（未提供报告）"
    s = report_text.strip()
    if len(s) <= _REPORT_SUMMARY_MAX_CHARS:
        return s
    return s[:_REPORT_SUMMARY_MAX_CHARS] + "\n...（报告后续内容已省略）"


def _strip_out_of_scope(text: str) -> tuple[bool, str]:
    """Returns (in_scope, cleaned_text)."""
    stripped = text.lstrip()
    if stripped.startswith(_OUT_OF_SCOPE_TAG):
        return False, stripped[len(_OUT_OF_SCOPE_TAG):].lstrip()
    return True, text


# ────────────────────── router (Phase A) ──────────────────────

def _parse_json_lenient(raw: str | None) -> dict | None:
    """Tolerant JSON extractor — strips ``` fences before parsing."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if not text:
        return None
    try:
        result = _json.loads(text)
    except Exception:
        logger.warning("[followup_router] JSON parse failed; raw=%r", text[:300])
        return None
    return result if isinstance(result, dict) else None


async def _rewrite_question(history: list[dict], question: str) -> str:
    """Phase A step 1: 把指代型/口语化问题改写为完整临床问题。失败时返回原 question。"""
    try:
        from agent.patient_like_me.v1.rag.workflow import _call_llm, _gemini_flash
        llm = _gemini_flash()
        raw = await _call_llm(
            llm,
            sys_prompt=prompts.FOLLOWUP_REWRITE_SYSTEM,
            user_prompt=prompts.FOLLOWUP_REWRITE_USER.format(
                history=_format_history(history),
                question=question,
            ),
            temperature=0.0,
            json_mode=True,
        )
    except Exception:
        logger.exception("[followup_rewrite] LLM call failed; returning original question")
        return question

    result = _parse_json_lenient(raw)
    if not result:
        return question
    rewritten = (result.get("rewritten_question") or "").strip()
    return rewritten or question


async def _classify_intent(report_text: str, rewritten_question: str) -> dict:
    """Phase A step 2: 用 rewritten_question + report 摘要 判定意图。

    Returns ``{intent, retrieval_query, reason}``. 失败时降级为 report_grounded。
    """
    fallback = {"intent": "report_grounded", "retrieval_query": "", "reason": "intent_fallback"}
    try:
        from agent.patient_like_me.v1.rag.workflow import _call_llm, _gemini_flash
        llm = _gemini_flash()
        raw = await _call_llm(
            llm,
            sys_prompt=prompts.FOLLOWUP_INTENT_SYSTEM,
            user_prompt=prompts.FOLLOWUP_INTENT_USER.format(
                report_summary=_summarize_report_for_router(report_text),
                rewritten_question=rewritten_question,
            ),
            temperature=0.0,
            json_mode=True,
        )
    except Exception:
        logger.exception("[followup_intent] LLM call failed; using fallback")
        return fallback

    result = _parse_json_lenient(raw)
    if not result:
        return fallback

    intent = (result.get("intent") or "").strip()
    if intent not in {"report_grounded", "need_retrieval", "out_of_scope"}:
        logger.warning("[followup_intent] invalid intent=%r; fallback", intent)
        return fallback

    return {
        "intent": intent,
        "retrieval_query": (result.get("retrieval_query") or "").strip(),
        "reason": (result.get("reason") or "").strip(),
    }


# ────────────────────── retrieval (Phase B - need_retrieval branch) ──────────────────────

async def _retrieve_for_followup(
    retrieval_query: str,
    rewritten_question: str,
    report_text: str,
) -> str:
    """Pull a small evidence pack for the rewritten question. Returns evidence text or "".

    Errors are swallowed (logged) — the caller will fall back to report-grounded answer
    if retrieval returns empty.
    """
    if not retrieval_query and not rewritten_question:
        return ""

    try:
        from agent.patient_like_me.v1.rag.evidence import retrieve_guideline_evidence_pack
        # 简易 selector + llm_caller：复用 workflow 里的实现细节会引入循环，
        # 这里用 retrieve_guideline_evidence_pack 的默认行为（无 selector / 无 query rewrite LLM）。
        evidence_text, _doc_ids = await retrieve_guideline_evidence_pack(
            user_query=retrieval_query or rewritten_question,
            diagnosis="",          # follow-up 阶段不强求重新解析诊断
            key_features="",
            patient_text=report_text[:2000],  # 报告前 2K 作为患者上下文
            intent="treatment",     # follow-up 多为治疗 / 用药 / 监测，treatment 是合理默认
            selector=None,
            llm_caller=None,
            max_docs=_FOLLOWUP_RETRIEVAL_MAX_DOCS,
            max_chunks=_FOLLOWUP_RETRIEVAL_MAX_CHUNKS,
        )
        return evidence_text or ""
    except Exception:
        logger.exception("[followup_retrieval] failed; returning empty evidence")
        return ""


# ────────────────────── public entry ──────────────────────

async def stream_followup_qa(
    report_text: str,
    question: str,
    history: list[dict] | None = None,
    model: str | None = None,
    enable_thinking: bool = False,
    thinking_budget: str = "medium",
) -> AsyncIterator[tuple[str, dict]]:
    """Yield (event_name, payload) tuples for SSE forwarding.

    Event protocol:
      - ``route_decided``    {intent, rewritten_question, retrieval_query, reason}
            ↑ 新增：客户端可据此显示"正在为您查询新证据..."等状态
      - ``retrieval_started``{retrieval_query}                  — only when intent=need_retrieval
      - ``retrieval_done``   {evidence_chars}                   — only when intent=need_retrieval
      - ``thinking_started`` {budget}                           — only when enable_thinking=True
      - ``thinking_chunk``   {text}                             — only if model exposes thinking
      - ``thinking_done``    {}                                 — only when at least one thinking_chunk fired
      - ``answer_chunk``     {text}                             — always (one or more)
      - ``complete``         {model, intent, in_scope, full_answer, history, elapsed_seconds, ...}
      - ``error``            {code, message[, fallback_text]}
    """
    t0 = time.perf_counter()
    model = (model or _DEFAULT_MODEL).strip()
    question = (question or "").strip()
    report_text = (report_text or "").strip()
    history = _trim_history(history or [])

    if not report_text:
        yield "error", {"code": "MISSING_REPORT", "message": "report_text is required (or pass task_id via Backend)."}
        return
    if not question:
        yield "error", {"code": "MISSING_QUESTION", "message": "question is required."}
        return

    try:
        llm, kind = _resolve_model(model, enable_thinking)
    except ValueError as exc:
        code = "THINKING_NOT_SUPPORTED" if "enable_thinking" in str(exc) else "UNKNOWN_MODEL"
        yield "error", {"code": code, "message": str(exc)}
        return

    # ── Phase A1: rewrite (history + question → rewritten_question) ──
    rewritten_question = await _rewrite_question(history, question)
    yield "rewrite_done", {"rewritten_question": rewritten_question}

    # ── Phase A2: classify intent (report_summary + rewritten_question → intent) ──
    intent_result = await _classify_intent(report_text, rewritten_question)
    intent = intent_result["intent"]
    retrieval_query = intent_result["retrieval_query"]
    yield "route_decided", {
        "intent": intent,
        "rewritten_question": rewritten_question,
        "retrieval_query": retrieval_query,
        "reason": intent_result.get("reason", ""),
    }

    # ── Phase B: build sys/user prompts based on intent ──
    # 三个分支统一走流式 LLM，下方只决定用哪个 prompt + 是否拉证据。
    evidence_text = ""

    if intent == "out_of_scope":
        # 不写 history（防止下一轮被无关问题指代污染），用专用拒答 prompt。
        sys_prompt = prompts.FOLLOWUP_OUT_OF_SCOPE_SYSTEM
        user_prompt = prompts.FOLLOWUP_OUT_OF_SCOPE_USER.format(
            report_summary=_summarize_report_for_router(report_text),
            question=rewritten_question,
        )
        # 也不开启 thinking — 拒答场景不需要思考
        enable_thinking = False
    else:
        if intent == "need_retrieval":
            yield "retrieval_started", {"retrieval_query": retrieval_query or rewritten_question}
            evidence_text = await _retrieve_for_followup(retrieval_query, rewritten_question, report_text)
            yield "retrieval_done", {"evidence_chars": len(evidence_text)}
            # 如果检索为空，降级为 report_grounded（仍能基于报告作答），不让用户白等
            if not evidence_text:
                logger.info("[followup_qa] retrieval empty; falling back to report_grounded")
                intent = "report_grounded"

        if intent == "need_retrieval" and evidence_text:
            sys_prompt = prompts.FOLLOWUP_QA_WITH_EVIDENCE_SYSTEM
            user_prompt = prompts.FOLLOWUP_QA_WITH_EVIDENCE_USER.format(
                report=report_text,
                evidence=evidence_text,
                history=_format_history(history),
                question=rewritten_question,
            )
        else:
            sys_prompt = prompts.FOLLOWUP_QA_SYSTEM
            user_prompt = prompts.FOLLOWUP_QA_USER.format(
                report=report_text,
                history=_format_history(history),
                question=rewritten_question,
            )

    if enable_thinking:
        yield "thinking_started", {"budget": thinking_budget}

    answer_buf: list[str] = []
    thinking_emitted = False
    thinking_done_emitted = False

    try:
        async for chunk_kind, chunk_text in _stream_chunks(
            llm=llm,
            kind=kind,
            sys_prompt=sys_prompt,
            user_prompt=user_prompt,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
        ):
            if chunk_kind == "thinking":
                thinking_emitted = True
                yield "thinking_chunk", {"text": chunk_text}
            else:  # answer
                if thinking_emitted and not thinking_done_emitted:
                    yield "thinking_done", {}
                    thinking_done_emitted = True
                answer_buf.append(chunk_text)
                yield "answer_chunk", {"text": chunk_text}
    except Exception as exc:
        logger.exception("[followup_qa] streaming failed")
        yield "error", {"code": "STREAM_FAILED", "message": str(exc)[:300]}
        return

    full_answer_raw = "".join(answer_buf)

    # Empty-response guard
    if not full_answer_raw.strip():
        fallback_msg = "抱歉，模型暂未生成有效内容，可能因安全过滤或临时故障。请稍后重试，或换一种表述。"
        yield "error", {
            "code": "EMPTY_RESPONSE",
            "message": "模型返回为空（可能被安全策略过滤或调用异常）",
            "fallback_text": fallback_msg,
        }
        return

    in_scope, full_answer = _strip_out_of_scope(full_answer_raw)

    # out_of_scope 也入 history 供 UI 展示, 但打上 hidden_from_prompt 标记,
    # 下一轮 _format_history / _trim_history 会跳过这些轮次, 不污染上下文。
    is_out_of_scope = (intent == "out_of_scope")
    turn_hidden = is_out_of_scope
    new_history = history + [
        {"role": "user", "content": question, "hidden_from_prompt": turn_hidden},
        {"role": "assistant", "content": full_answer_raw, "hidden_from_prompt": turn_hidden},
    ]

    yield "complete", {
        "model": model,
        "intent": intent,
        "thinking_enabled": enable_thinking,
        "in_scope": in_scope,
        "full_answer": full_answer,
        "history": new_history,
        # 语义调整: persist_in_history 始终 true (存 Redis), 前端仍可用 intent
        # 或 history[i].hidden_from_prompt 判断是否是 out_of_scope 轮次并加提示。
        "persist_in_history": True,
        "hidden_from_prompt": turn_hidden,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
        "rewritten_question": rewritten_question,
        "evidence_used": bool(evidence_text),
    }
