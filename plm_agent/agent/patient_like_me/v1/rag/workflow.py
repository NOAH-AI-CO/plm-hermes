"""
PLM v1 workflow — generic guideline evidence-pack RAG.

DAG overview:
  1. Extract structured patient info (gemini-3.1-pro)
  2. If has_clear_diagnosis → parallel guide + PubMed searches
     Else → search CSCO guide → check diagnosis clarity → update diagnosis if clear → parallel
    3. Guide branch: 诊断/检查/治疗 三路并行证据包检索 → 各自LLM总结 → 整合为指南总结
  4. PubMed branch: 搜索 → 文献精炼(iteration) → 汇总 → 幻觉审查 → 清洗 → 最终重写
    5. Final merge: 指南总结 + PubMed证据 → 诊疗总结 → End
"""
import asyncio
import contextvars
import functools
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable

from tenacity import retry, stop_after_attempt, wait_exponential

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


class WorkflowEmptyOutput(RuntimeError):
    """所有分支都没有产出实际内容时抛出，告知调用方应当重试。

    Why: 之前 _assemble_final_output 在 4 个分支全空时只输出标题
    "# 循证诊疗建议汇总"，用户感知是"模型回答了但什么都没说"。
    现在改成: 一律抛错让调用方/客户端决定重试或上报，绝不返回半空报告。
    """


class GuideBranchFailed(RuntimeError):
    """某个 org 分支内部 LLM 调用失败/返回空时抛出，携带原始 cause。

    Why: 之前 _run_org_branch 把所有异常 silently 吞成 result=""，
    多 org 并发时一个失败会让该 org 静默缺位，再加上其他分支也空就触发
    WorkflowEmptyOutput。现在改成把根因冒泡，方便定位是哪一步死的。
    """


# Per-request list of (step_name, elapsed_seconds), collected so we can emit
# a single sorted summary block at workflow end (easier to grep/diff between
# local and test-env runs than scattered [timing] lines).
_timing_log: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "plm_timing_log", default=None
)


def _log_timing(func):
    """Log wall-clock duration of an async step. Used to compare per-step
    timing between local and test environments."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return await func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            logger.info("[timing] %s=%.2fs", func.__name__, elapsed)
            records = _timing_log.get()
            if records is not None:
                records.append((func.__name__, elapsed))
    return wrapper


def _format_timing_summary(records: list[tuple[str, float]], total: float) -> str:
    lines = ["[timing summary] PLM workflow breakdown (execution-finish order):"]
    for name, dur in records:
        lines.append(f"  {dur:>7.2f}s  {name}")
    lines.append(f"  {'-' * 7}")
    lines.append(f"  {total:>7.2f}s  TOTAL (run_plm_workflow)")
    return "\n".join(lines)

def _parse_usage_log_tokens(task_id: str) -> dict:
    """Parse token usage from the shared usage log file, filtering by task_id."""
    import datetime, os, re
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    path = f"logs/open_api_usage_{date}.log"
    if not os.path.exists(path):
        return {"prompt": 0, "output": 0, "total": 0, "calls": 0}
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    prompt_total, output_total, total_total, calls = 0, 0, 0, 0
    tag = f"[{task_id}]"
    for line in lines:
        if tag not in line:
            continue
        m = re.search(r'Prompt:\s*(\d+)', line)
        if m:
            prompt_total += int(m.group(1))
        m = re.search(r'Output:\s*(\d+)', line)
        if m:
            output_total += int(m.group(1))
        m = re.search(r'Total:\s*(\d+)', line)
        if m:
            total_total += int(m.group(1))
        calls += 1
    return {"prompt": prompt_total, "output": output_total, "total": total_total, "calls": calls}

# ────────────────────── Model factories ──────────────────────

def _gemini_pro():
    from llm.ali_models import Glm52Pro
    return Glm52Pro()

def _gemini_flash():
    from llm.ali_models import Glm52Flash
    return Glm52Flash()

def _gpt52():
    from llm.azure_models import GPT52
    return GPT52()


# ────────────────────── Retry helper ──────────────────────

def _with_retry(func):
    # 指数退避 1s → 3s → 8s (第 1 次重试等 1s, 第 2 次 3s, 第 3 次 8s)
    # tenacity multiplier * 2^(n-1), cap 8s
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )(func)

# ────────────────────── Tool wrappers ──────────────────────

def _loads_first_json_object(raw: str) -> dict:
    """解析 LLM 输出的首个 JSON 对象, 容忍 reasoning 模型在其后多吐的
    尾部字符 (常见: 多一个 `}` 或说明文字), 避免严格 json.loads 因 "Extra data" 整体失败。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        if start < 0:
            raise
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
        return obj


@_with_retry
async def _select_document_ids(diagnosis: str, query: str, candidates: list[dict], lite: bool = False) -> list[str]:
    # lite=True: 只给病名(去 summary), Flash 不带思考 → ~1s, 用于交互式 select_guideline 重排;
    # 默认(报告流程)保留 summary, 判定更充分。
    select_prompt = prompts.SEARCH_DOC_SELECT_PROMPT.format(
        diagnosis=diagnosis or "未明确",
        query=query,
    )
    for i, candidate in enumerate(candidates, 1):
        if lite:
            select_prompt += (
                f"{i}. id={candidate['id']}\n"
                f"   name={candidate.get('name', '')}\n"
                f"   guideline_key={candidate.get('guideline_key', '')}\n"
            )
        else:
            select_prompt += (
                f"{i}. id={candidate['id']}\n"
                f"   name={candidate.get('name', '')}\n"
                f"   guideline_key={candidate.get('guideline_key', '')}\n"
                f"   language={'CN' if candidate.get('is_cn_content') else 'EN/original'}\n"
                f"   summary={candidate.get('summary', '')}\n"
            )

    llm = _gemini_flash()
    raw = await _call_llm(llm, "你是一个严谨的检索筛选助手。", select_prompt, json_mode=True)
    try:
        data = _loads_first_json_object(raw)
        candidate_ids = {str(item.get("id")) for item in candidates}
        return [str(x) for x in data.get("ids", []) if str(x) in candidate_ids][:5]
    except Exception:
        logger.exception("Failed to parse document selection output: %s", raw)
        return []


async def _flash_json_caller(sys_prompt: str, user_prompt: str) -> str:
    llm = _gemini_flash()
    return await _call_llm(llm, sys_prompt, user_prompt, json_mode=True)


@_with_retry
async def _search_docs(
    user_query: str,
    diagnosis: str = "",
    key_features: str = "",
    patient_text: str = "",
    intent: str = "treatment",
    multi_org: bool = False,
    filter_doc_ids: list[int] | None = None,
    allowed_publishers: list[str] | None = None,
    product_scope: str | None = None,
    accessible_paid_doc_ids: list[str] | None = None,
    boost_doc_ids: list[int] | None = None,
) -> tuple[str, list[int]]:
    from agent.patient_like_me.v1.rag.evidence import retrieve_guideline_evidence_pack

    return await retrieve_guideline_evidence_pack(
        user_query=user_query,
        diagnosis=diagnosis,
        key_features=key_features,
        patient_text=patient_text,
        intent=intent,
        selector=_select_document_ids,
        llm_caller=_flash_json_caller,
        multi_org=multi_org,
        filter_doc_ids=filter_doc_ids,
        allowed_publishers=allowed_publishers,
        product_scope=product_scope,
        accessible_paid_doc_ids=accessible_paid_doc_ids,
        boost_doc_ids=boost_doc_ids,
    )


_pubmed_fetcher = None
_pubmed_probed = False
_pubmed_probe_lock = asyncio.Lock()


async def _get_pubmed_fetcher():
    """Probe PubMed availability once per process; cache result to avoid repeated 75s DB timeouts."""
    global _pubmed_fetcher, _pubmed_probed
    if _pubmed_probed:
        return _pubmed_fetcher
    async with _pubmed_probe_lock:
        if _pubmed_probed:
            return _pubmed_fetcher

        def _do_import():
            from agent.explore.mindsearch_agent_v3_pubmed import fetch_pubmed_articles_by_existing_logic
            return fetch_pubmed_articles_by_existing_logic

        try:
            _pubmed_fetcher = await asyncio.to_thread(_do_import)
            logger.info("[pubmed_branch] module available, enabled for this process")
        except Exception as e:
            logger.warning("[pubmed_branch] module unavailable, disabling for this process: %s", e)
            _pubmed_fetcher = None
        _pubmed_probed = True
        return _pubmed_fetcher


@_with_retry
async def _search_pubmed(query: str) -> list[dict]:
    if os.getenv("PLM_DISABLE_PUBMED", "").lower() in {"1", "true", "yes"}:
        logger.info("[pubmed_branch] disabled by PLM_DISABLE_PUBMED")
        return []
    fetcher = await _get_pubmed_fetcher()
    if fetcher is None:
        return []
    result = await fetcher(query=query)
    return result.get("articles", [])

# ────────────────────── LLM call helpers ──────────────────────

async def _call_llm(llm, sys_prompt: str, user_prompt: str, temperature: float = 0.0, json_mode: bool = False) -> str:
    result = await llm(sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=temperature, json_mode=json_mode)
    # None 或纯空白都视为失败 — reasoning 模型有时会烧完 token 直接产 ""
    if result is None or not str(result).strip():
        logger.warning("[call_llm] LLM returned empty/None (possibly safety-filtered or truncated), retrying once")
        result = await llm(sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=temperature, json_mode=json_mode)
    if result is None or not str(result).strip():
        raise RuntimeError(
            f"LLM returned empty after retry — likely safety-filtered, reasoning-truncated or token-exhausted. "
            f"sys_prompt[:80]={sys_prompt[:80]!r}, user_prompt[:80]={user_prompt[:80]!r}"
        )
    return result


async def _call_llm_stream(
    llm, sys_prompt: str, user_prompt: str,
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
    temperature: float = 0.0,
) -> str:
    """流式调用 LLM。每收到一个 chunk 调用 on_chunk(chunk),返回完整 text。

    on_chunk=None 时退化为非流式 _call_llm,作为不支持 stream_call 的模型 / 测试用兜底。
    """
    if on_chunk is None:
        return await _call_llm(llm, sys_prompt, user_prompt, temperature=temperature)

    # 没有 stream_call 的 lineup (GLM/DeepSeek/Kimi/Qwen): 走非流式 __call__,
    # 拿到完整 text 后用一次 on_chunk 推送, 让上层至少能拿到 section_done 时间戳
    if not hasattr(llm, "stream_call"):
        text = await _call_llm(llm, sys_prompt, user_prompt, temperature=temperature)
        try:
            await on_chunk(text)
        except Exception:
            logger.exception("[call_llm_stream] on_chunk callback failed (non-stream fallback)")
        return text

    buf: list[str] = []
    async for chunk in llm.stream_call(
        sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=temperature
    ):
        if not chunk:
            continue
        buf.append(chunk)
        try:
            await on_chunk(chunk)
        except Exception:
            logger.exception("[call_llm_stream] on_chunk callback failed")
    text = "".join(buf).strip()
    if not text:
        raise RuntimeError(
            f"LLM stream returned empty. sys_prompt[:80]={sys_prompt[:80]!r}, user_prompt[:80]={user_prompt[:80]!r}"
        )
    return text


async def _call_gemini_structured(sys_prompt: str, user_prompt: str, schema: dict, temperature: float = 0.0, use_flash: bool = False) -> dict:
    llm = _gemini_flash() if use_flash else _gemini_pro()
    content = await llm(
        user_prompt=f"{sys_prompt}\n\n{user_prompt}",
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=_convert_schema_to_gemini(schema),
    )
    # GLM/Kimi 等不理 response_mime_type, 会带 markdown 包裹
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned or "{}")
    except Exception:
        logger.warning("Failed to parse structured output: %s", content[:200] if content else "empty")
        return {}


def _convert_schema_to_gemini(json_schema: dict) -> dict:
    type_map = {"string": "STRING", "boolean": "BOOLEAN", "number": "NUMBER", "integer": "INTEGER", "array": "ARRAY", "object": "OBJECT"}
    result = {}
    if "type" in json_schema:
        result["type"] = type_map.get(json_schema["type"], json_schema["type"].upper())
    if "properties" in json_schema:
        result["properties"] = {k: _convert_schema_to_gemini(v) for k, v in json_schema["properties"].items()}
    if "required" in json_schema:
        result["required"] = json_schema["required"]
    if "items" in json_schema:
        result["items"] = _convert_schema_to_gemini(json_schema["items"])
    return result

# ────────────────────── Code nodes (from Dify) ──────────────────────

def _parse_pubmed_response(raw_articles: list[dict]) -> list[dict]:
    if not raw_articles:
        return []
    res_list = raw_articles
    if isinstance(raw_articles, list) and raw_articles and isinstance(raw_articles[0], dict):
        if "articles" in raw_articles[0]:
            res_list = raw_articles[0]["articles"]
        elif "json" in raw_articles[0] and isinstance(raw_articles[0]["json"], list):
            res_list = raw_articles[0]["json"][0].get("articles", []) if raw_articles[0]["json"] else []
    return res_list[:29]


def _build_truth_table(articles: list[dict]) -> str:
    table = "| PMID | 年份 | 摘要事实 (前400字) |\n| :--- | :--- | :--- |\n"
    for a in articles:
        pmid = a.get("pubmed_id", "未知")
        year = a.get("year_of_publication", "未知")
        summary = (a.get("summary", "无摘要内容") or "")[:400].replace("\n", " ")
        table += f"| {pmid} | {year} | {summary} |\n"
    return table

# ────────────────────── Workflow steps ──────────────────────

@_log_timing
async def step_extract_patient_info(patient_input: str, fast: bool = False) -> tuple[dict, str]:
    # fast=True: 用 Flash(不带思考, 本就是为结构化抽取设计)—— 交互式 select_guideline 只要主诊断, 求快;
    # 默认 Pro(带思考): 报告/澄清流程要更稳的抽取。
    llm = _gemini_flash() if fast else _gemini_pro()
    raw_text = await llm(
        user_prompt=f"{prompts.EXTRACT_PATIENT_INFO_SYSTEM}\n\n{prompts.EXTRACT_PATIENT_INFO_USER.format(input=patient_input)}",
        temperature=0.0,
        response_mime_type="application/json",
        response_schema=_convert_schema_to_gemini(prompts.EXTRACT_PATIENT_INFO_SCHEMA),
    )
    logger.info("[extract_patient_info] raw_text: %s", raw_text)
    # GLM/Kimi 等 OpenAI 兼容模型不理 response_mime_type, 会带 markdown 包裹
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        structured = json.loads(cleaned or "{}")
    except Exception:
        logger.warning("Failed to parse patient info: %s", raw_text[:200] if raw_text else "empty")
        structured = {}
    return structured, raw_text or ""


# 注: step_search_csco_guide / step_check_diagnosis_clarity / step_structure_diagnosis
# 三个函数已删除。它们是历史"诊断明确度兜底"链路, 当 patient_info 抽取出
# has_clear_diagnosis=False 时跑, 用 CSCO 指南反推诊断。
# 现在诊断明确度全部交给澄清接口 (stream_clarification + 图谱探索) 处理。


@_log_timing
async def step_short_diagnosis_summary(diagnosis_text: str) -> str:
    llm = _gemini_flash()
    return await _call_llm(
        llm,
        sys_prompt=prompts.SHORT_DIAGNOSIS_SUMMARY_SYSTEM,
        user_prompt=prompts.SHORT_DIAGNOSIS_SUMMARY_USER.format(diagnosis_text=diagnosis_text),
    )


@_log_timing
async def step_structure_patient_text(raw_input: str) -> str:
    llm = _gemini_flash()
    result = await _call_llm(
        llm,
        sys_prompt=prompts.STRUCTURE_PATIENT_TEXT_SYSTEM,
        user_prompt=prompts.STRUCTURE_PATIENT_TEXT_USER.format(raw_input=raw_input),
    )
    return result.strip() if result else raw_input


# ── Parallel guide searches ──

@_log_timing
async def step_search_diagnosis_guide(diagnosis: str, key_features: str, patient_text: str = "", filter_doc_ids: list[int] | None = None, boost_doc_ids: list[int] | None = None) -> tuple[str, list[int]]:
    query = prompts.SEARCH_DIAGNOSIS_QUERY.format(diagnosis=diagnosis, key_features=key_features)
    return await _search_docs(query, diagnosis=diagnosis, key_features=key_features, patient_text=patient_text or key_features, intent="diagnosis", filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids)


@_log_timing
async def step_search_examination_guide(diagnosis: str, key_features: str, patient_text: str = "", filter_doc_ids: list[int] | None = None, boost_doc_ids: list[int] | None = None) -> tuple[str, list[int]]:
    query = prompts.SEARCH_EXAMINATION_QUERY.format(diagnosis=diagnosis, key_features=key_features)
    return await _search_docs(query, diagnosis=diagnosis, key_features=key_features, patient_text=patient_text or key_features, intent="examination", filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids)


@_log_timing
async def step_search_treatment_guide(diagnosis: str, key_features: str, patient_text: str = "", filter_doc_ids: list[int] | None = None, boost_doc_ids: list[int] | None = None) -> tuple[str, list[int]]:
    query = prompts.SEARCH_TREATMENT_QUERY.format(diagnosis=diagnosis, key_features=key_features)
    return await _search_docs(query, diagnosis=diagnosis, key_features=key_features, patient_text=patient_text or key_features, intent="treatment", filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids)


@_log_timing
async def step_search_pubmed(diagnosis: str, key_features: str) -> list[dict]:
    query = prompts.PUBMED_TREATMENT_QUERY.format(diagnosis=diagnosis, key_features=key_features)
    return await _search_pubmed(query)


# ── Guide summary nodes ──

def _dump_prompt(section: str, sys_prompt: str, user_prompt: str):
    """PLM_DUMP_PROMPTS=1 时把渲染好的 prompt 写到 /tmp 供调试。"""
    if not os.environ.get("PLM_DUMP_PROMPTS"):
        return
    try:
        path = f"/tmp/plm_prompt_{section}.md"
        with open(path, "w") as f:
            f.write(f"# {section} prompt (rendered)\n\n")
            f.write(f"## SYSTEM ({len(sys_prompt)} chars)\n```\n{sys_prompt}\n```\n\n")
            f.write(f"## USER ({len(user_prompt)} chars)\n```\n{user_prompt}\n```\n")
        logger.info(f"[dump_prompt] {section} → {path} (sys={len(sys_prompt)} user={len(user_prompt)})")
    except Exception:
        pass


@_log_timing
@_with_retry
async def step_diagnosis_report(
    guide_content: str, patient_info_text: str, graph_evidence: str = "",
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    llm = _gemini_pro()
    sys_p = prompts.DIAGNOSIS_REPORT_SYSTEM
    user_p = prompts.DIAGNOSIS_REPORT_USER.format(
        guide_content=guide_content,
        patient_info=patient_info_text,
        graph_evidence=graph_evidence or "(本次未触发图谱命中,仅基于上文证据片段输出。)",
    )
    _dump_prompt("diagnosis", sys_p, user_p)
    return await _call_llm_stream(llm, sys_prompt=sys_p, user_prompt=user_p, on_chunk=on_chunk)


@_log_timing
@_with_retry
async def step_examination_report(
    guide_content: str, patient_info_text: str, graph_evidence: str = "",
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    llm = _gemini_pro()
    sys_p = prompts.EXAMINATION_REPORT_SYSTEM
    user_p = prompts.EXAMINATION_REPORT_USER.format(
        guide_content=guide_content,
        patient_info=patient_info_text,
        graph_evidence=graph_evidence or "(本次未触发图谱命中,仅基于上文证据片段输出。)",
    )
    _dump_prompt("examination", sys_p, user_p)
    return await _call_llm_stream(llm, sys_prompt=sys_p, user_prompt=user_p, on_chunk=on_chunk)


@_log_timing
@_with_retry
async def step_treatment_report(
    guide_content: str, patient_info_text: str, graph_evidence: str = "",
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    llm = _gemini_pro()
    sys_p = prompts.TREATMENT_REPORT_SYSTEM
    user_p = prompts.TREATMENT_REPORT_USER.format(
        guide_content=guide_content,
        patient_info=patient_info_text,
        graph_evidence=graph_evidence or "(本次未触发图谱命中,仅基于上文证据片段输出。)",
    )
    _dump_prompt("treatment", sys_p, user_p)
    return await _call_llm_stream(llm, sys_prompt=sys_p, user_prompt=user_p, on_chunk=on_chunk)


def _strip_self_title(text: str) -> str:
    """分区报告首行现在自带 '## 标题'(供独立分栏展示时有标题)。拼进综合报告时改用下方
    的编号标题(## 1. 诊断建议 等), 去掉自带首行, 避免"## 1. 诊断建议"紧跟"## 诊断建议及依据"双标题。"""
    t = (text or "").lstrip()
    if t.startswith("## "):
        nl = t.find("\n")
        return t[nl + 1:].lstrip("\n") if nl >= 0 else ""
    return t


def _assemble_three_reports(diagnosis_summary: str, examination_summary: str, treatment_summary: str) -> str:
    """beta-v1: 三路报告代码层直接拼接,不调 LLM。"""
    parts = []
    diagnosis_summary = _strip_self_title(diagnosis_summary)
    examination_summary = _strip_self_title(examination_summary)
    treatment_summary = _strip_self_title(treatment_summary)
    if diagnosis_summary:
        parts.append("## 1. 诊断建议\n\n" + diagnosis_summary)
    if examination_summary:
        parts.append("## 2. 进一步检查\n\n" + examination_summary)
    if treatment_summary:
        parts.append("## 3. 治疗方案\n\n" + treatment_summary)
    return "\n\n".join(parts)


def _split_summary_block(summary_block: str) -> tuple[str, str]:
    """v1: 把 LLM 产出的"摘要 + 风险 + 沟通"拆成顶部(摘要)和底部(风险+沟通)。"""
    import re as _re
    text = (summary_block or "").strip()
    if not text:
        return "", ""
    # 找第一个 ## 二、 或 ## 三、 标题作为分割点
    m = _re.search(r"^##\s*二[、.\s]", text, _re.MULTILINE)
    if not m:
        # 整段都是摘要,或格式不对 → 全部放顶部
        return text, ""
    top = text[:m.start()].strip()
    bottom = text[m.start():].strip()
    return top, bottom


def _assemble_v1_guideline_text(*, summary_block: str, three_reports_text: str) -> str:
    """v1 报告正文拼接:
       摘要(顶) → 1.诊断 / 2.检查 / 3.治疗 → 二.风险 / 三.沟通(底)
    """
    top, bottom = _split_summary_block(summary_block)
    parts = []
    if top:
        parts.append(top)
    if three_reports_text:
        parts.append(three_reports_text)
    if bottom:
        parts.append(bottom)
    return "\n\n".join(parts)


@_log_timing
@_with_retry
async def step_summary_risk_communication(
    diagnosis_summary: str, examination_summary: str, treatment_summary: str,
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    """beta-v1: 基于三路报告产出"病例核心摘要 + 临床关键风险 + 医患沟通"3 块。"""
    llm = _gemini_pro()
    return await _call_llm_stream(
        llm,
        sys_prompt=prompts.REPORT_SUMMARY_RISK_COMM_SYSTEM,
        user_prompt=prompts.REPORT_SUMMARY_RISK_COMM_USER.format(
            diagnosis_summary=diagnosis_summary,
            examination_summary=examination_summary,
            treatment_summary=treatment_summary,
        ),
        on_chunk=on_chunk,
    )


@_log_timing
async def step_guideline_integration(diagnosis_summary: str, examination_summary: str, treatment_summary: str) -> str:
    """Integrate the 3 guide evidence summaries."""
    llm = _gemini_pro()
    return await _call_llm(
        llm,
        sys_prompt=prompts.GUIDELINE_INTEGRATION_SYSTEM,
        user_prompt=prompts.GUIDELINE_INTEGRATION_USER.format(
            diagnosis_summary=diagnosis_summary,
            examination_summary=examination_summary,
            treatment_summary=treatment_summary,
        ),
    )


def _assemble_secondary_block(secondary_evidence: list[dict]) -> str:
    """把各次要机构的检索证据拼成带来源标注的块, 供对比 prompt 用。

    各机构 / 各检索桶的证据都各自从 [E1] 起编号, 直接拼接会 E-id 冲突;
    这里按出现顺序全局重编号成 [E1..EK], 保证对比模型能唯一对应到每条来源标签,
    产出的"参考文献"才不会串号。
    """
    import re as _re

    blocks = []
    for item in secondary_evidence or []:
        org = str(item.get("organization") or "其他").strip()
        text = str(item.get("evidence_text") or "").strip()
        if text:
            blocks.append(f"### 来源机构: {org}\n{text}")
    combined = "\n\n".join(blocks)

    idx = 0
    def _renum(_m):
        nonlocal idx
        idx += 1
        return f"[E{idx}]"
    return _re.sub(r"\[E\d+\]", _renum, combined)


@_log_timing
@_with_retry
async def step_secondary_comparison(
    main_report: str, secondary_block: str,
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    """主报告 + 各次要机构检索证据 → GLM-5.2(think) 流式产出"与主报告的重大区别"单份正文。"""
    llm = _gemini_pro()
    sys_p = prompts.SECONDARY_COMPARISON_SYS
    user_p = prompts.SECONDARY_COMPARISON_USER.format(
        main_report=main_report,
        secondary_block=secondary_block,
    )
    _dump_prompt("secondary_comparison", sys_p, user_p)
    return await _call_llm_stream(llm, sys_prompt=sys_p, user_prompt=user_p, on_chunk=on_chunk)


# ── PubMed branch ──

@_with_retry
async def step_refine_single_article(article: dict, patient_info_text: str, index: int) -> str:
    authors = article.get("authors", [])
    first_author = authors[0].get("name", "Unknown") if authors else "Unknown"
    llm = _gemini_flash()
    return await _call_llm(
        llm,
        sys_prompt=prompts.ARTICLE_REFINER_SYSTEM,
        user_prompt=prompts.ARTICLE_REFINER_USER.format(
            patient_info=patient_info_text,
            title=article.get("title", ""),
            summary=article.get("summary", ""),
            journal=article.get("fulljournalname", ""),
            year=article.get("year_of_publication", ""),
            volume=article.get("volume", ""),
            issue=article.get("issue", ""),
            pagination=article.get("pagination", ""),
            doi=article.get("doi", ""),
            index=index,
            first_author=first_author,
        ),
    )


@_log_timing
async def step_refine_articles(articles: list[dict], patient_info_text: str) -> list[str]:
    semaphore = asyncio.Semaphore(10)

    async def _refine(article: dict, idx: int) -> str:
        async with semaphore:
            try:
                return await step_refine_single_article(article, patient_info_text, idx)
            except Exception as e:
                logger.warning("Article refinement failed for index %d: %s", idx, e)
                return "SKIP"

    tasks = [_refine(a, i) for i, a in enumerate(articles)]
    return await asyncio.gather(*tasks)


@_log_timing
async def step_pubmed_aggregation(evidence_fragments: str) -> str:
    llm = _gemini_pro()
    return await llm(
        sys_prompt=prompts.PUBMED_AGGREGATION_SYSTEM,
        user_prompt=prompts.PUBMED_AGGREGATION_USER.format(evidence_fragments=evidence_fragments),
        temperature=0.0,
        top_p=0.41,
    )


@_log_timing
async def step_hallucination_audit(truth_table: str, draft_text: str) -> str:
    llm = _gemini_flash()
    return await _call_llm(
        llm,
        sys_prompt=prompts.HALLUCINATION_AUDIT_SYSTEM,
        user_prompt=prompts.HALLUCINATION_AUDIT_USER.format(
            truth_table=truth_table,
            draft_text=draft_text,
        ),
        temperature=0.7,
    )


@_log_timing
async def step_clean_evidence(audit_report: str, truth_table: str) -> str:
    llm = _gemini_flash()
    return await _call_llm(
        llm,
        sys_prompt=prompts.CLEAN_EVIDENCE_SYSTEM,
        user_prompt=prompts.CLEAN_EVIDENCE_USER.format(
            audit_report=audit_report,
            truth_table=truth_table,
        ),
        temperature=0.7,
    )


@_log_timing
async def step_final_rewrite(audit_report: str, draft_text: str, clean_evidence: str) -> str:
    llm = _gemini_pro()
    return await _call_llm(
        llm,
        sys_prompt=prompts.FINAL_REWRITE_SYSTEM,
        user_prompt=prompts.FINAL_REWRITE_USER.format(
            audit_report=audit_report,
            draft_text=draft_text,
            clean_evidence=clean_evidence,
        ),
    )


# ── Final assembly (code-driven, no LLM merge) ──
#
# 大标题完全由代码注入，每段内容由对应分支独立产出。
# 任何关闭/失败/为空的分支，其标题和内容都不会出现在最终 markdown 里。
# 这样可以做到："关闭就完全没有，不会留下半空的占位标题"。

def _assemble_final_output(
    *,
    guideline_text: str,
    pubmed_rewrite: str,
    kb_summary: str,
    drug_manual_text: str,
    primary_org: str | None = None,
    primary_status: str = "auto",
    secondary_comparison: str = "",
) -> str:
    """Stitch the final markdown report from independent sections.

    Sections appear only when their content is non-empty, so disabling a
    branch (PubMed/KB/drug) cleanly removes the corresponding heading.
    Each section's body is already self-contained and self-numbered by
    its producing branch.
    """
    # 防御性 str 转换 — reasoning 模型偶尔会让上游返回 list/dict 而不是 str
    guideline_text = str(guideline_text or "")
    pubmed_rewrite = str(pubmed_rewrite or "")
    kb_summary = str(kb_summary or "")
    drug_manual_text = str(drug_manual_text or "")
    secondary_comparison = str(secondary_comparison or "")

    parts: list[str] = ["# 循证诊疗建议汇总"]

    # 主指南：始终插入"## 一、权威指南共识"标题，正文按状态决定
    # （只要 primary_status 是 user_specified_empty 也要给出明示，避免用户感知不到）
    if guideline_text and guideline_text.strip():
        parts.append(f"## 一、权威指南共识（主指南：{primary_org or '系统默认'}）")
        parts.append(guideline_text.strip())
    elif primary_status == "user_specified_empty" and primary_org:
        parts.append(f"## 一、权威指南共识（主指南：{primary_org}）")
        parts.append(
            f"> 用户指定的主指南 **{primary_org}** 本次未在指南库中召回到与本病例相关的内容。"
            f"以下"
            f"{'次要指南对比' if secondary_comparison.strip() else '其他证据'}"
            f"供参考。"
        )

    # 次要指南对比：独立分区(像药物说明书那样), 不进"一/二/三"权威指南编号序列
    if secondary_comparison and secondary_comparison.strip():
        parts.append("## 次要指南对比")
        parts.append(secondary_comparison.strip())

    if pubmed_rewrite and pubmed_rewrite.strip():
        parts.append("## 三、PubMed 前沿论文证据")
        parts.append(pubmed_rewrite.strip())

    if kb_summary and kb_summary.strip():
        parts.append("## 用户知识库补充")
        parts.append(kb_summary.strip())

    # 药物说明书: 前端已作为独立 tab 渲染(drug_manual_text 字段), 不再并进综合报告避免重复。

    # 只剩硬编码标题说明 4 个分支全空 — 不能给用户假兜底，直接抛错让上层重试
    if len(parts) == 1:
        empty_branches = []
        if not (guideline_text or "").strip():
            empty_branches.append("guideline_text(主指南)")
        if not secondary_comparison.strip():
            empty_branches.append("secondary_comparison(次要指南对比)")
        if not (pubmed_rewrite or "").strip():
            empty_branches.append("pubmed_rewrite(PubMed)")
        if not (kb_summary or "").strip():
            empty_branches.append("kb_summary(用户知识库)")
        if not (drug_manual_text or "").strip():
            empty_branches.append("drug_manual_text(药物说明书)")
        raise WorkflowEmptyOutput(
            f"PLM workflow 4 个分支全部产出空内容，无法生成报告。空分支: "
            f"{', '.join(empty_branches)}。primary_org={primary_org}, "
            f"primary_status={primary_status}。请检查上游 LLM 是否返回 None / 截断 / 安全拦截。"
        )

    return "\n\n".join(parts)


# ────────────────────── Orchestrator ──────────────────────

@_log_timing
async def _run_guide_branch(
    patient_info_text: str, diagnosis: str = "", key_features: str = "",
    retrieval_log: dict | None = None, filter_doc_ids: list[int] | None = None,
    return_reports: bool = False,
    clarify_session_id: str = "",
    emit=None,
    treatment_ready_future: "asyncio.Future | None" = None,
    boost_doc_ids: list[int] | None = None,
) -> str | dict:
    """主指南分支：诊断 + 检查 + 治疗三路并行检索 + 报告。

    次要指南不再走本函数(改走 _retrieve_secondary_evidence 仅检索预取 + 统一对比)。

    return_reports=True — v1 流程:返回 dict
        {"diagnosis_report", "examination_report", "treatment_report"}
        而不是经过 LLM integration 后的字符串。上层 orchestrator 负责拼接 + 调用
        摘要/风险/医患沟通 + 药物分支(三者可并行)。
    """
    # graph_path 在已知 doc_ids 时与三路 search 并行启动;
    # 命中后会作为图谱证据(优先级最高)塞进三路 report prompt。
    graph_task = None
    if filter_doc_ids:
        graph_task = asyncio.create_task(
            _run_graph_path_for_docs(patient_info_text, filter_doc_ids,
                                     emit=emit, clarify_session_id=clarify_session_id)
        )

    (diag_guide, diag_ids), (exam_guide, exam_ids), (treat_guide, treat_ids) = await asyncio.gather(
        step_search_diagnosis_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids),
        step_search_examination_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids),
        step_search_treatment_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids, boost_doc_ids=boost_doc_ids),
    )
    logger.info("[guide_branch:full] search done — diag=%d/%dd exam=%d/%dd treat=%d/%dd",
                len(diag_guide), len(diag_ids), len(exam_guide), len(exam_ids), len(treat_guide), len(treat_ids))

    if retrieval_log is not None:
        retrieval_log["diagnosis"] = {"chars": len(diag_guide), "doc_ids": diag_ids, "evidence_pack": diag_guide}
        retrieval_log["examination"] = {"chars": len(exam_guide), "doc_ids": exam_ids, "evidence_pack": exam_guide}
        retrieval_log["treatment"] = {"chars": len(treat_guide), "doc_ids": treat_ids, "evidence_pack": treat_guide}

    # 把三路 search 真正用到的 doc_ids 合并起来,补一次图谱(若一开始没传 filter_doc_ids)
    if graph_task is None:
        merged_ids = list({int(x) for x in (diag_ids + exam_ids + treat_ids)})
        graph_task = asyncio.create_task(
            _run_graph_path_for_docs(patient_info_text, merged_ids,
                                     emit=emit, clarify_session_id=clarify_session_id)
        )

    graph_results = await graph_task
    graph_evidence = _format_graph_evidence(graph_results)
    if retrieval_log is not None:
        retrieval_log["graph"] = {
            "doc_ids": [r.get("doc_id") for r in graph_results if not r.get("error")],
            "hit_count": sum(1 for r in graph_results if not r.get("error") and r.get("matched_nodes")),
            "evidence": graph_evidence,
            # 完整结果(含 matched_nodes / pruned_tree_mermaid)留给 orchestrator
            # 拼到 result.graph_path 给前端做"决策树"渲染。
            "results": graph_results,
        }
    logger.info("[guide_branch:full] graph_evidence chars=%d (results=%d)",
                len(graph_evidence), len(graph_results))

    # 三段并发 stream:
    # - 每段产 token 实时 emit("section_chunk")
    # - 段完成时 emit("section_done")
    # - 治疗段完成时立刻 set treatment_ready_future,让上层 fire 药物分支
    _emit = emit or (lambda *_a, **_k: None)

    def _make_section_cb(section: str):
        if emit is None:
            return None
        async def _cb(chunk: str):
            _emit("section_chunk", {"section": section, "text": chunk})
        return _cb

    async def _run_one_report(section: str, fn, guide):
        _emit("section_started", {"section": section})
        t0 = time.perf_counter()
        try:
            text = await fn(guide, patient_info_text, graph_evidence=graph_evidence,
                            on_chunk=_make_section_cb(section))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.error("[section=%s] failed after retries in %.2fs: %s", section, elapsed, exc)
            _emit("section_failed", {
                "section": section,
                "elapsed_seconds": round(elapsed, 2),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "retryable": True,
            })
            # 治疗段挂了要立即通知 drug branch, 否则 drug_task 永久 await
            if section == "treatment" and treatment_ready_future is not None and not treatment_ready_future.done():
                treatment_ready_future.set_exception(exc)
            raise
        elapsed = time.perf_counter() - t0
        _emit("section_done", {"section": section, "elapsed_seconds": round(elapsed, 2)})
        if section == "treatment" and treatment_ready_future is not None and not treatment_ready_future.done():
            treatment_ready_future.set_result(text)
        return text

    diag_task = asyncio.create_task(_run_one_report("diagnosis", step_diagnosis_report, diag_guide))
    exam_task = asyncio.create_task(_run_one_report("examination", step_examination_report, exam_guide))
    treat_task = asyncio.create_task(_run_one_report("treatment", step_treatment_report, treat_guide))

    # return_exceptions=True: 让每段独立成/败, 上层根据 failed_sections 决定去留
    results = await asyncio.gather(diag_task, exam_task, treat_task, return_exceptions=True)
    section_names = ["diagnosis", "examination", "treatment"]
    section_texts: dict[str, str] = {}
    failed_sections: list[dict] = []
    for name, res in zip(section_names, results):
        if isinstance(res, Exception):
            failed_sections.append({
                "section": name,
                "error": f"{type(res).__name__}: {str(res)[:300]}",
            })
            section_texts[f"{name}_report"] = ""
        else:
            section_texts[f"{name}_report"] = res
    # 兜底: 若 treatment 挂了但 future 还没 done (理论上不会, 保底)
    if failed_sections and treatment_ready_future is not None and not treatment_ready_future.done():
        treatment_ready_future.set_exception(RuntimeError("treatment_report failed"))

    if return_reports:
        return {
            **section_texts,
            "failed_sections": failed_sections,
        }
    # legacy 分支: 有任一段挂就整体抛, 因为要走 integration LLM
    if failed_sections:
        raise RuntimeError(f"guide_branch sections failed: {[f['section'] for f in failed_sections]}")
    return await step_guideline_integration(
        section_texts["diagnosis_report"],
        section_texts["examination_report"],
        section_texts["treatment_report"],
    )


async def _retrieve_secondary_evidence(
    org: str, patient_info_text: str, diagnosis: str, key_features: str,
    filter_doc_ids: list[int],
) -> dict:
    """次要机构：诊断 + 检查 + 治疗三路检索, 返回该机构的证据文本(不成文、不 integration)。

    证据供统一"次要指南对比"prompt 用, 三路都覆盖以便与主报告逐段对比。
    """
    (diag_guide, diag_ids), (exam_guide, exam_ids), (treat_guide, treat_ids) = await asyncio.gather(
        step_search_diagnosis_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids),
        step_search_examination_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids),
        step_search_treatment_guide(diagnosis, key_features, patient_text=patient_info_text, filter_doc_ids=filter_doc_ids),
    )
    parts = []
    if diag_guide and diag_guide.strip():
        parts.append(f"[诊断相关]\n{diag_guide.strip()}")
    if exam_guide and exam_guide.strip():
        parts.append(f"[检查相关]\n{exam_guide.strip()}")
    if treat_guide and treat_guide.strip():
        parts.append(f"[治疗相关]\n{treat_guide.strip()}")
    evidence_text = "\n\n".join(parts)
    logger.info("[secondary_retrieve] org=%s diag=%d/%dd exam=%d/%dd treat=%d/%dd",
                org, len(diag_guide), len(diag_ids), len(exam_guide), len(exam_ids), len(treat_guide), len(treat_ids))
    return {"organization": org, "evidence_text": evidence_text}


@_log_timing
async def _run_multi_guide_branch(
    patient_info_text: str,
    diagnosis: str = "",
    key_features: str = "",
    priority_config=None,
    show_supplements: bool = True,
    retrieval_log: dict | None = None,
    emit=None,
    allowed_publishers: list[str] | None = None,
    primary_return_reports: bool = False,
    clarify_session_id: str = "",
    treatment_ready_future: "asyncio.Future | None" = None,
    selected_doc_id=None,
) -> dict:
    """Run guideline analysis across multiple organizations in parallel.

    primary_return_reports=True (v1) — 主指南分支返回 dict
        {"diagnosis_report", "examination_report", "treatment_report"},
        primary_result 类型为 dict 而非 str。
    """
    from agent.patient_like_me.v1.rag.evidence import (
        group_docs_by_organization,
        search_guideline_documents,
        PRIMARY_PUBLISHERS,
        OTHER_PUBLISHER,
    )
    from agent.patient_like_me.v1.guideline_priority import (
        rank_organizations,
        resolve_priority,
    )

    if emit is None:
        emit = lambda n, p=None: None

    emit("guide_branch_started")

    doc_query = " ".join(x for x in [diagnosis, key_features] if x).strip() or diagnosis

    # 两路检索:
    # ① 主指南池 — 前端选的那类 (allowed_publishers) 硬过滤, KNN 只在这几份里搜
    # ② 补充指南池 — 4 大剩下的 + OTHER, 硬过滤走另一次检索
    # 分开搜的原因: ES filter 一旦限死 publisher, 就没法同一次 KNN 里既找主指南又找补充.
    primary_publishers = None
    supplement_publishers = None
    if allowed_publishers:
        primary_publishers = [p for p in allowed_publishers if p]
        # 补充池 = 4 大剩下的 + OTHER
        primary_set = {p.upper() for p in primary_publishers}
        supplement_publishers = [p for p in PRIMARY_PUBLISHERS if p not in primary_set] + [OTHER_PUBLISHER]

    # 用户显式选的主指南(guideline_priority_order[0])。宽召回 KNN 里, NCCN 这类"大类
    # 标题"文档(如"B细胞淋巴瘤")常被子类标题(如"滤泡性淋巴瘤")挤出 top-K, 导致明明
    # 库里有却被判"未召回"。因此对用户选定的主指南 publisher 单独定向硬过滤搜一次,
    # 保证其文档一定被捞进来参与排序。
    priority_primary_org = None
    if priority_config is not None and getattr(priority_config, "order", None):
        priority_primary_org = (priority_config.order[0] or "").upper() or None

    async def _sup_search():
        if show_supplements and supplement_publishers:
            return await search_guideline_documents(
                doc_query, diagnosis=diagnosis, max_docs=10, multi_org=True,
                allowed_publishers=supplement_publishers,
            )
        if show_supplements and not allowed_publishers:
            # 老流程 fallback: 前端没传 publisher 时, 全库 20 份 → 按 org 分组
            return await search_guideline_documents(
                doc_query, diagnosis=diagnosis, max_docs=20, multi_org=True,
            )
        return []

    async def _priority_search():
        if not priority_primary_org or priority_primary_org == OTHER_PUBLISHER:
            return []
        # 尊重组织白名单: 白名单存在且不含该 publisher 时不定向搜。
        if allowed_publishers and priority_primary_org not in {p.upper() for p in allowed_publishers if p}:
            return []
        return await search_guideline_documents(
            doc_query, diagnosis=diagnosis, max_docs=10, multi_org=True,
            allowed_publishers=[priority_primary_org],
        )

    async def _selected_search():
        # 用户在前端选定的具体指南 doc_id: 定向捞出放最前, 保证报告严格用这一份。
        if not selected_doc_id:
            return []
        try:
            return await search_guideline_documents(
                doc_query, diagnosis=diagnosis, max_docs=1, multi_org=True,
                filter_doc_ids=[int(selected_doc_id)],
            )
        except Exception:
            return []

    primary_docs, supplement_docs, priority_docs, selected_docs = await asyncio.gather(
        search_guideline_documents(
            doc_query, diagnosis=diagnosis, max_docs=10, multi_org=True,
            allowed_publishers=primary_publishers,
        ),
        _sup_search(),
        _priority_search(),
        _selected_search(),
    )

    # selected_docs(用户选定)/priority_docs 放最前, 去重时优先保留, 不被挤掉。
    all_docs = list(selected_docs) + list(priority_docs) + list(primary_docs) + list(supplement_docs)
    # 去重: 同一个 doc_id 可能在多次检索都出现
    seen = set()
    dedup_docs = []
    for d in all_docs:
        did = str(d.get("id") or "")
        if did and did not in seen:
            seen.add(did)
            dedup_docs.append(d)
    all_docs = dedup_docs

    org_groups = group_docs_by_organization(all_docs)
    logger.info("[multi_guide] found orgs: %s (total docs=%d, primary=%d, supplement=%d, priority[%s]=%d)",
                list(org_groups.keys()), len(all_docs), len(primary_docs), len(supplement_docs),
                priority_primary_org or "-", len(priority_docs))

    if not org_groups:
        # 严格模式且用户指定了主指南：返回"指定主指南本次未召回"语义
        # 主指南分支不会跑, 释放 treatment_ready_future 让药物分支退出, 避免死等。
        if treatment_ready_future is not None and not treatment_ready_future.done():
            treatment_ready_future.set_result("")
        user_top = (priority_config.order[0]
                    if priority_config and priority_config.order else None)
        primary_status = "user_specified_empty" if user_top else "auto"
        return {
            "primary_org": user_top,
            "primary_status": primary_status,
            "primary_result": "",
            "secondary_evidence": [],
        }

    priority = resolve_priority(priority_config)
    # 用户传了 priority_config → 自动启用严格主指南
    strict_primary = bool(priority_config is not None)

    # 先按 rank 决定主指南 + 次要机构集合。rank 已给出正确的 secondaries 划分:
    #   - matched/auto  → primary 在库, secondaries = 其余
    #   - user_specified_empty → primary(用户指定)不在库, secondaries = 全部
    placeholder = {org: True for org in org_groups.keys()}
    primary_org, primary_status, pre_secondaries = rank_organizations(
        placeholder, priority, strict_primary=strict_primary,
    )

    # 主指南 full 三路报告(流式) 与 次要机构仅检索预取, 并行跑。
    run_primary = primary_org is not None and primary_org in org_groups
    secondary_orgs = list(pre_secondaries.keys()) if show_supplements else []

    # 主指南不跑时(user_specified_empty / 全 OTHER)释放 future, 避免药物分支死等治疗段。
    if not run_primary and treatment_ready_future is not None and not treatment_ready_future.done():
        treatment_ready_future.set_result("")

    primary_result: "str | dict" = ""
    secondary_evidence: list[dict] = []

    async def _run_primary_branch(org: str, docs: list[dict]) -> None:
        nonlocal primary_result
        doc_ids = [int(d["id"]) for d in docs if str(d.get("id", "")).isdigit()]
        if not doc_ids:
            return
        # 硬锁: 用户选定的那份指南 = 主报告唯一指南, 三路检索只在它内部进行,
        # 同机构兄弟病指南(如 CLL/SLL、霍奇金)不参与检索/给分, 防证据被带偏。
        if selected_doc_id and int(selected_doc_id) in doc_ids:
            doc_ids = [int(selected_doc_id)]
        emit("org_branch_started", {"organization": org, "doc_count": len(doc_ids), "mode": "full"})
        try:
            primary_result = await _run_guide_branch(
                patient_info_text, diagnosis=diagnosis, key_features=key_features,
                retrieval_log=retrieval_log, filter_doc_ids=doc_ids,
                return_reports=primary_return_reports,
                clarify_session_id=clarify_session_id,
                emit=emit,
                treatment_ready_future=treatment_ready_future,
            )
        except Exception as e:
            # 主指南分支失败 → 直接冒泡，让 workflow 上层重试/报错
            logger.exception("[multi_guide] primary org=%s failed", org)
            raise GuideBranchFailed(
                f"主指南分支(org={org})失败: {type(e).__name__}: {e}"
            ) from e
        emit("org_branch_complete", {"organization": org, "mode": "full"})

    async def _run_secondary_branch(org: str, docs: list[dict]) -> None:
        # 次要机构只做检索预取(不流式、不成文)，失败仅记日志不阻塞主流程。
        doc_ids = [int(d["id"]) for d in docs if str(d.get("id", "")).isdigit()]
        if not doc_ids:
            return
        emit("org_branch_started", {"organization": org, "doc_count": len(doc_ids), "mode": "secondary_retrieve"})
        try:
            ev = await _retrieve_secondary_evidence(org, patient_info_text, diagnosis, key_features, doc_ids)
        except Exception:
            logger.exception("[multi_guide] secondary org=%s retrieve failed", org)
            return
        emit("org_branch_complete", {"organization": org, "mode": "secondary_retrieve"})
        if ev.get("evidence_text"):
            secondary_evidence.append(ev)

    tasks = []
    if run_primary:
        tasks.append(_run_primary_branch(primary_org, org_groups[primary_org]))
    for org in secondary_orgs:
        tasks.append(_run_secondary_branch(org, org_groups[org]))
    await asyncio.gather(*tasks)

    if primary_status == "user_specified_empty":
        primary_result = ""

    emit("guide_branch_complete", {
        "primary_org": primary_org,
        "primary_status": primary_status,
        "secondary_org_count": len(secondary_evidence),
    })
    return {
        "primary_org": primary_org,
        "primary_status": primary_status,
        "primary_result": primary_result,
        "secondary_evidence": secondary_evidence,
    }


@_log_timing
async def _run_pubmed_branch(
    patient_info_text: str,
    diagnosis: str = "",
    key_features: str = "",
    emit=None,
    enable_pubmed: bool = False,
) -> tuple[str, str]:
    if emit is None:
        emit = lambda n, p=None: None

    if not enable_pubmed:
        logger.info("[pubmed_branch] skipped — enable_pubmed=False (caller did not opt in)")
        emit("pubmed_branch_skipped", {"reason": "enable_pubmed_false"})
        return "", ""

    emit("pubmed_branch_started")
    articles = await step_search_pubmed(diagnosis, key_features)
    if not articles:
        logger.info("[pubmed_branch] no articles found")
        emit("pubmed_branch_complete", {"article_count": 0})
        return "", ""

    articles = _parse_pubmed_response(articles) if (articles and isinstance(articles[0], dict) and "articles" in articles[0]) else articles[:29]
    logger.info("[pubmed_branch] processing %d articles", len(articles))
    emit("pubmed_branch_searching_done", {"article_count": len(articles)})

    truth_table = _build_truth_table(articles)

    emit("pubmed_branch_refining", {"article_count": len(articles)})
    refined_list = await step_refine_articles(articles, patient_info_text)
    evidence_fragments = "\n\n".join(refined_list)

    emit("pubmed_branch_aggregating")
    draft_text = await step_pubmed_aggregation(evidence_fragments)
    logger.info("[pubmed_branch] aggregation done, starting audit")

    emit("pubmed_branch_auditing")
    audit_report = await step_hallucination_audit(truth_table, draft_text)
    clean_evidence = await step_clean_evidence(audit_report, truth_table)
    final_rewrite = await step_final_rewrite(audit_report, draft_text, clean_evidence)
    logger.info("[pubmed_branch] final rewrite done")
    emit("pubmed_branch_complete", {"article_count": len(articles)})
    return draft_text, final_rewrite


@_log_timing
async def _run_graph_path_for_docs(
    patient_text: str,
    doc_ids: list[int],
    emit=None,
    clarify_session_id: str = "",
) -> list[dict]:
    """Run graph search for the given doc_ids (filter to docs with graph data).

    Used when the caller already has the doc_id set ahead of time so graph
    search can run concurrently with chunk-level retrieval.

    clarify_session_id: 若非空,先从 Redis 取澄清阶段缓存的 matched_node_ids,
                       避免重复调 LLM,保证澄清和报告的决策路径一致。
    """
    if emit is None:
        emit = lambda n, p=None: None

    if not doc_ids:
        return []

    from agent.patient_like_me.v1.guideline import guidance_db
    graph_doc_ids: list[int] = []
    for did in dict.fromkeys(int(x) for x in doc_ids):
        if guidance_db.load_graph_by_doc_id(did) is not None:
            graph_doc_ids.append(did)

    if not graph_doc_ids:
        return []

    # 优先从 Redis 取澄清阶段缓存
    cached_matched_by_doc: dict[int, list[int]] = {}
    if clarify_session_id:
        try:
            from agent.common.session_store import load_session
            import json as _json
            cached = await load_session("plm", clarify_session_id)
            if cached and cached.get("report_text"):
                clarify_data = _json.loads(cached["report_text"])
                doc_id_cached = int(clarify_data.get("doc_id") or 0)
                if doc_id_cached:
                    cached_matched_by_doc[doc_id_cached] = clarify_data.get("matched_node_ids") or []
                    logger.info("[graph_path] reuse clarify session=%s doc_id=%d matched=%d",
                                clarify_session_id, doc_id_cached, len(cached_matched_by_doc[doc_id_cached]))
        except Exception as e:
            logger.warning("[graph_path] clarify session load failed: %s", e)

    emit("graph_path_searching", {"doc_ids": graph_doc_ids, "cache_hit": list(cached_matched_by_doc.keys())})
    from agent.patient_like_me.v1.guideline.search import (
        run_search_phase_by_doc_id, _build_clarify_path_mermaid, _build_reverse_graph, _load_file_graph,
    )

    async def _one(did: int) -> dict:
        try:
            if did in cached_matched_by_doc:
                cached_ids = cached_matched_by_doc[did]
                loaded = guidance_db.load_graph_by_doc_id(did)
                if loaded:
                    gid, fid = loaded
                    entry_info = guidance_db.get_entry_page_code(fid, gid)
                    entry_page_id = int(entry_info[0]) if entry_info else 0
                    graph_data = _load_file_graph(fid, gid)
                    node_by_id, rev_adj, root_nodes, out_adj = _build_reverse_graph(graph_data, entry_page_id)
                    valid_ids = [nid for nid in cached_ids if nid in node_by_id]
                    matched_nodes = [
                        {
                            "node_id": nid,
                            "title": node_by_id[nid].get("title", ""),
                            "content": node_by_id[nid].get("content", ""),
                            "page_id": node_by_id[nid].get("page_id"),
                            "care_phase_id": node_by_id[nid].get("care_phase_id"),
                        }
                        for nid in valid_ids
                    ]
                    mermaid = _build_clarify_path_mermaid(
                        matched_node_ids=valid_ids,
                        node_by_id=node_by_id, out_adj=out_adj, rev_adj=rev_adj,
                        root_nodes=root_nodes, forward_depth=3,
                    ) if valid_ids else ""
                    logger.info("[graph_path] doc_id=%d CACHE_HIT matched=%d", did, len(valid_ids))
                    return {
                        "doc_id": did,
                        "decision_type": "insufficient" if not valid_ids else "match",
                        "matched_nodes": matched_nodes,
                        "pruned_tree_mermaid": mermaid,
                        "pruned_tree_stats": {"matched": len(valid_ids), "from_cache": True},
                    }
            # Cache miss → 跑完整流程(澄清没做过 / session 过期 / 不同 doc)
            result = await run_search_phase_by_doc_id(patient_text, did, mode="clarify")
            logger.info(
                "[graph_path] doc_id=%d decision=%s matched=%d tree_stats=%s",
                did, result.get("decision_type"),
                len(result.get("matched_nodes", [])), result.get("pruned_tree_stats"),
            )
            return {
                "doc_id": did,
                "decision_type": result.get("decision_type", ""),
                "matched_nodes": result.get("matched_nodes", []),
                "pruned_tree_mermaid": result.get("pruned_tree_mermaid", ""),
                "pruned_tree_stats": result.get("pruned_tree_stats", {}),
            }
        except Exception as e:
            logger.warning("[graph_path] doc_id=%d failed: %s", did, e)
            return {"doc_id": did, "error": str(e)}

    results = await asyncio.gather(*[_one(d) for d in graph_doc_ids])
    emit("graph_path_complete", {"count": len(results)})
    return results


@_log_timing
async def _run_graph_path(
    patient_text: str,
    retrieval_log: dict,
    emit,
) -> list[dict]:
    """Back-compat wrapper: collect doc_ids from retrieval_log then run graph search.

    Kept so old callers (and orchestrator's downstream graph_path emit) still work.
    """
    all_doc_ids: set[int] = set()
    for intent_data in retrieval_log.values():
        if isinstance(intent_data, dict):
            for did in intent_data.get("doc_ids", []):
                all_doc_ids.add(int(did))
    return await _run_graph_path_for_docs(patient_text, list(all_doc_ids), emit)


def _format_graph_evidence(graph_results: list[dict]) -> str:
    """把 graph_path 的命中节点/决策树/Mermaid 格式化为可塞入 prompt 的图谱证据文本。

    设计要点:
    - 图谱在三路 report prompt 里作为"最高优先级证据",所以这里必须把决策路径完整保留。
    - 每个 doc 的命中节点单独成段,前缀 doc_id + decision_type,便于模型按段引用。
    """
    if not graph_results:
        return ""
    sections: list[str] = []
    for r in graph_results:
        if r.get("error"):
            continue
        decision_type = r.get("decision_type") or "未分类决策"
        matched = r.get("matched_nodes") or []
        mermaid = (r.get("pruned_tree_mermaid") or "").strip()
        if not matched and not mermaid:
            continue
        parts = [f"## 决策路径参考 (决策类型: {decision_type})"]
        # 决策树渲染说明:★ = 当前位置;✓ = 已走过;? = 后续候选(医生还要决定)
        # 节点定义直接在 mermaid 内,不重复列"关键节点"段。
        if mermaid:
            parts.append("### 决策路径 (★ = 患者当前位置, ✓ = 已走过, ? = 后续候选)")
            parts.append("```mermaid\n" + mermaid + "\n```")
        sections.append("\n".join(parts))
    if not sections:
        return ""
    return "\n\n".join(sections)


# ────────────────────── Structured input merging ──────────────────────

def _merge_structured_input(request_data: dict) -> str:
    parts = []

    text = (request_data.get('patient_input') or request_data.get('patient_description') or '').strip()
    parts.append(text)

    structured_parts = []
    if request_data.get('age'):
        structured_parts.append(f"年龄: {request_data['age']}岁")
    if request_data.get('gender'):
        gender_map = {'male': '男', 'female': '女', 'unknown': '未知'}
        structured_parts.append(f"性别: {gender_map.get(request_data['gender'], request_data['gender'])}")
    if request_data.get('visit_stage'):
        structured_parts.append(f"就诊阶段: {request_data['visit_stage']}")
    if request_data.get('diagnosis_status'):
        structured_parts.append(f"诊断状态: {request_data['diagnosis_status']}")
    if request_data.get('completed_examinations'):
        exam_lines = []
        for exam in request_data['completed_examinations']:
            exam_lines.append(f"  - {exam['name']}: {exam['result']}")
        structured_parts.append("已完成检查:\n" + "\n".join(exam_lines))
    if request_data.get('key_conditions'):
        structured_parts.append(f"关键合并条件: {', '.join(request_data['key_conditions'])}")

    sf = request_data.get('structured_fields')
    if sf and isinstance(sf, dict):
        for k, v in sf.items():
            if v is None or v == '':
                continue
            if isinstance(v, dict):
                inner = ", ".join(f"{ik}: {iv}" for ik, iv in v.items() if iv)
                if inner:
                    structured_parts.append(f"{k}: {inner}")
            elif isinstance(v, list):
                structured_parts.append(f"{k}: {', '.join(str(x) for x in v if x)}")
            else:
                structured_parts.append(f"{k}: {v}")

    if structured_parts:
        parts.append("\n【结构化病例信息】\n" + "\n".join(structured_parts))

    if request_data.get('_file_texts'):
        for i, ft in enumerate(request_data['_file_texts'], 1):
            parts.append(f"\n【附件 {i} 内容】\n{ft}")

    return "\n\n".join(parts)


# ────────────────────── Drug manual analysis ──────────────────────


def _strip_html(html_text: str) -> str:
    """Remove HTML tags, preserving readable structure."""
    if not html_text:
        return ""
    import re as _re
    text = _re.sub(r'<figure[^>]*>.*?</figure>', '', html_text, flags=_re.DOTALL)
    text = _re.sub(r'<img[^>]*/?>', '', text)
    text = _re.sub(r'<a[^>]*>(.*?)</a>', r'\1', text)
    text = _re.sub(r'<sup>(.*?)</sup>', r'^\1', text)
    text = _re.sub(r'<sub>(.*?)</sub>', r'_\1', text)
    text = _re.sub(r'<br\s*/?>', '\n', text)
    text = _re.sub(r'</p>\s*<p>', '\n', text)
    text = _re.sub(r'</li>\s*<li>', '\n- ', text)
    text = _re.sub(r'<li[^>]*>', '\n- ', text)
    text = _re.sub(r'<[^>]+>', '', text)
    text = _re.sub(r'&nbsp;', ' ', text)
    text = _re.sub(r'&[a-z]+;', '', text)
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_manual_json(raw_text: str) -> dict | None:
    """Parse the raw JSON dict string from DXY into structured sections."""
    if not raw_text:
        return None
    import ast
    try:
        data = ast.literal_eval(raw_text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    boxed_warning = _strip_html(data.get("boxedWarning", "") or "")

    sections: dict[str, str] = {}
    for item in data.get("result", []):
        cn_name = item.get("cnName", "")
        value = item.get("value", "")
        if cn_name and value:
            sections[cn_name] = _strip_html(value)

    return {
        "boxedWarning": boxed_warning,
        "sections": sections,
        "common_name": data.get("commonName", ""),
        "show_name": data.get("showName", ""),
    }


def _merge_manual_versions(parsed_list: list[dict]) -> dict:
    """Merge multiple parsed versions, keeping the most complete value per section."""
    if not parsed_list:
        return {"boxedWarning": "", "sections": {}}
    if len(parsed_list) == 1:
        return parsed_list[0]

    best_boxed = ""
    merged_sections: dict[str, str] = {}
    section_order: list[str] = []

    for parsed in parsed_list:
        bw = parsed.get("boxedWarning", "")
        if len(bw) > len(best_boxed):
            best_boxed = bw
        for cn_name, value in parsed.get("sections", {}).items():
            if cn_name not in merged_sections:
                section_order.append(cn_name)
            if len(value) > len(merged_sections.get(cn_name, "")):
                merged_sections[cn_name] = value

    ordered = {k: merged_sections[k] for k in section_order if k in merged_sections}
    return {
        "boxedWarning": best_boxed,
        "sections": ordered,
        "common_name": parsed_list[0].get("common_name", ""),
        "show_name": parsed_list[0].get("show_name", ""),
    }


def _format_manual_text(parsed: dict) -> str:
    """Convert parsed/merged sections into clean plain text for LLM consumption."""
    parts = []
    bw = parsed.get("boxedWarning", "")
    if bw:
        parts.append(f"【警示语】\n{bw}")
    for cn_name, value in parsed.get("sections", {}).items():
        if value:
            parts.append(f"【{cn_name}】\n{value}")
    return "\n\n".join(parts)


async def _fetch_all_variants(es, common_name: str, size: int = 5) -> list[str]:
    """Fetch all manufacturer versions of a drug by exact common_name."""
    query = {
        "_source": ["text"],
        "query": {"term": {"common_name.keyword": common_name}},
        "size": size,
    }
    try:
        resp = await es.es_client.search(index=es.es_index, body=query)
        hits = resp.get("hits", {}).get("hits", [])
        return [h["_source"]["text"] for h in hits if h.get("_source", {}).get("text")]
    except Exception:
        logger.warning("[drug_manuals] fetch_all_variants failed for %s", common_name)
        return []


async def _expand_drug_name(drug_name: str) -> list[str]:
    """Expand a drug name to aliases via LLM."""
    aliases = [drug_name]
    try:
        llm = _gemini_flash()
        raw = await _call_llm(
            llm,
            sys_prompt="你是药学专家。",
            user_prompt=prompts.DRUG_ALIAS_EXPAND_PROMPT.format(drug_name=drug_name),
        )
        _text = (raw or "").strip()
        for part in _text.replace("\n", ",").split(","):
            part = part.strip().strip("·-•").strip()
            if part and part not in aliases and len(part) < 50:
                aliases.append(part)
    except Exception as e:
        logger.warning("[drug_alias] LLM expand failed for %s: %s", drug_name, e)
    return aliases


async def _expand_drug_names_batch(drug_names: list[str]) -> list[list[str]]:
    """批量扩展多个药物名 — 一次 LLM 调用搞定 N 个药, 避免 N 次 Flash 串发开销。
    返回 list[list[str]], 跟 drug_names 顺序一致, 每项是对应药的别名列表。"""
    if not drug_names:
        return []
    try:
        llm = _gemini_flash()
        numbered = "\n".join(f"{i+1}. {n}" for i, n in enumerate(drug_names))
        user_prompt = (
            "你是临床药学专家。请为下列每个药物名生成精准的别名(标准通用名、商品名、英文缩写)。\n\n"
            "## 输入药物列表\n"
            f"{numbered}\n\n"
            "## 输出要求\n"
            "1. 严格按照输入顺序, 每行一个药物的别名结果\n"
            "2. 每行格式: `N: 别名1,别名2,别名3`\n"
            "3. 别名间用英文逗号分隔; 列表中必须包含原输入的药品名\n"
            "4. 没有别名时只输出原名\n"
            "5. 不要输出额外解释\n\n"
            "## 示例\n"
            "输入:\n1. 利妥昔单抗\n2. 环磷酰胺\n\n"
            "输出:\n1: 利妥昔单抗,美罗华,Rituximab,RTX\n2: 环磷酰胺,CTX,Cyclophosphamide,癌得星\n"
        )
        raw = await _call_llm(llm, sys_prompt="你是药学专家。", user_prompt=user_prompt)
        # 解析: 每行 "N: 别名1,别名2"
        result: list[list[str]] = [[name] for name in drug_names]
        import re as _re
        for line in (raw or "").splitlines():
            m = _re.match(r"\s*(\d+)\s*[:：]\s*(.+)$", line.strip())
            if not m: continue
            idx = int(m.group(1)) - 1
            if idx < 0 or idx >= len(drug_names): continue
            aliases = [drug_names[idx]]
            for part in m.group(2).replace("\n", ",").split(","):
                part = part.strip().strip("·-•").strip()
                if part and part not in aliases and len(part) < 50:
                    aliases.append(part)
            result[idx] = aliases
        return result
    except Exception as e:
        logger.warning("[drug_alias] batch expand failed: %s — falling back to per-drug", e)
        return await asyncio.gather(*(_expand_drug_name(n) for n in drug_names))


@_log_timing
async def step_extract_drugs_from_treatment(treatment_text: str, patient_info_text: str) -> dict:
    # 药物名抽取是简单 NER 任务, Flash 完全够用, 不需要 thinking
    llm = _gemini_flash()
    raw = await llm(
        user_prompt=(
            f"{prompts.DRUG_EXTRACT_SYSTEM}\n\n"
            f"{prompts.DRUG_EXTRACT_USER.format(treatment_text=treatment_text, patient_info=patient_info_text)}\n\n"
            f"请严格按照以下JSON Schema返回，只返回JSON: {json.dumps(prompts.DRUG_EXTRACT_SCHEMA, ensure_ascii=False)}"
        ),
        temperature=0.0,
    )
    try:
        text = (raw or "").strip()
        import re as _re
        m = _re.search(r"```(?:json)?\s*\n?(.*?)```", text, _re.DOTALL)
        if m:
            text = m.group(1).strip()
        return json.loads(text)
    except Exception:
        logger.warning("[drug_extract] failed to parse: %s", (raw or "")[:200])
        return {"recommended_drugs": [], "current_medications": []}


@_log_timing
async def step_search_drug_manuals(drug_names: list[str]) -> list[dict]:
    if not drug_names:
        return []

    # 批量扩展所有药物名 (一次 LLM 调用搞定 N 个药)
    all_aliases = await _expand_drug_names_batch(drug_names)
    logger.info("[drug_manuals] batch-expanded %d drugs → aliases: %s",
                len(drug_names), [a[:3] for a in all_aliases])

    from utils.drug_manuals.drug_manuals_elastic_search import DrugManualsElasticSearch
    es = DrugManualsElasticSearch()

    async def _search_one(aliases: list[str]) -> dict | None:
        try:
            result = await es.search_single_drug_by_aliases(aliases, size=1)
            if not result or result.get("match_type") == "none":
                return None

            common_name = result.get("common_name", "")
            if common_name:
                variant_texts = await _fetch_all_variants(es, common_name)
                parsed_versions = [_parse_manual_json(t) for t in variant_texts]
                parsed_versions = [p for p in parsed_versions if p]
                if parsed_versions:
                    merged = _merge_manual_versions(parsed_versions)
                    result["text"] = _format_manual_text(merged)
                    logger.info("[drug_manuals] merged %d versions for %s",
                                len(parsed_versions), common_name)
                    return result

            parsed = _parse_manual_json(result.get("text", ""))
            if parsed:
                result["text"] = _format_manual_text(parsed)
            return result
        except Exception as e:
            logger.warning("[drug_manuals] search failed for %s: %s", aliases[0], e)
        return None

    search_tasks = [_search_one(aliases) for aliases in all_aliases]
    results = await asyncio.gather(*search_tasks)
    return [r for r in results if r]


@_log_timing
async def step_generate_drug_cards_per_drug(
    drug_manuals: list[dict], treatment_text: str, patient_info_text: str,
    on_chunk: "Callable[[str, str], Awaitable[None]] | None" = None,
) -> list[dict]:
    """Generate one card per drug, returning a list of {name, content} dicts.

    on_chunk(drug_name, chunk_text) — 流式回调,每张卡产 token 时实时推。
    """
    if not drug_manuals:
        return []

    semaphore = asyncio.Semaphore(10)

    async def _gen_card(manual: dict) -> dict | None:
        async with semaphore:
            drug_name = manual.get("common_name") or manual.get("show_name") or manual.get("matched_drug", "未知药物")
            drug_text = manual.get("text", "")
            if not drug_text:
                return None
            llm = _gemini_flash()
            # 给本张卡的 on_chunk 绑上 drug_name, 提升到顶层 callback
            inner_cb = None
            if on_chunk is not None:
                async def inner_cb(chunk: str):
                    await on_chunk(drug_name, chunk)
            content = await _call_llm_stream(
                llm,
                sys_prompt=prompts.DRUG_MANUAL_CARD_SYSTEM,
                user_prompt=prompts.DRUG_MANUAL_CARD_USER.format(
                    drug_name=drug_name,
                    drug_manual_text=drug_text,
                    treatment_text=treatment_text,
                    patient_info=patient_info_text,
                ),
                on_chunk=inner_cb,
            )
            return {"name": drug_name, "content": content or ""}

    tasks = [_gen_card(m) for m in drug_manuals]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r and r.get("content")]


@_log_timing
async def step_generate_drug_cards(
    drug_manuals: list[dict], treatment_text: str, patient_info_text: str,
    on_chunk: "Callable[[str, str], Awaitable[None]] | None" = None,
) -> str:
    cards = await step_generate_drug_cards_per_drug(
        drug_manuals, treatment_text, patient_info_text, on_chunk=on_chunk,
    )
    return "\n\n".join(f"## {c['name']}\n\n{c['content']}" for c in cards)


@_log_timing
async def _extract_interaction_sections(drug_manuals: list[dict]) -> list[str]:
    """Phase 1: extract interaction-relevant sections from each drug manual in parallel."""
    semaphore = asyncio.Semaphore(10)

    async def _extract_one(manual: dict) -> str:
        async with semaphore:
            drug_name = manual.get("common_name") or manual.get("show_name") or manual.get("matched_drug", "未知")
            drug_text = manual.get("text", "")
            if not drug_text:
                return ""
            llm = _gemini_flash()
            return await _call_llm(
                llm,
                sys_prompt=prompts.DRUG_INTERACTION_EXTRACT_SYSTEM,
                user_prompt=prompts.DRUG_INTERACTION_EXTRACT_USER.format(
                    drug_name=drug_name,
                    drug_manual_text=drug_text,
                ),
            )

    tasks = [_extract_one(m) for m in drug_manuals]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


@_log_timing
async def step_drug_interaction_analysis(
    drug_manuals: list[dict], current_medications: list[str], patient_info_text: str,
    on_chunk: "Callable[[str], Awaitable[None]] | None" = None,
) -> str:
    if len(drug_manuals) < 2 and not current_medications:
        return ""

    interaction_extracts = await _extract_interaction_sections(drug_manuals)
    if not interaction_extracts:
        return ""

    combined_extracts = "\n\n---\n\n".join(interaction_extracts)
    current_meds_text = "、".join(current_medications) if current_medications else "无"

    llm = _gemini_pro()
    return await _call_llm_stream(
        llm,
        sys_prompt=prompts.DRUG_INTERACTION_SYSTEM,
        user_prompt=prompts.DRUG_INTERACTION_USER.format(
            drug_interaction_extracts=combined_extracts,
            current_medications=current_meds_text,
            patient_info=patient_info_text,
        ),
        on_chunk=on_chunk,
    )


@_log_timing
async def _run_kb_branch(
    patient_info_text: str,
    diagnosis: str = "",
    key_features: str = "",
    emit=None,
) -> str:
    """Search user knowledge base and summarize relevant findings."""
    if emit:
        emit("kb_branch_started")

    try:
        from agent.patient_like_me.v1.custom_rag.kb_index import has_any_documents
        from agent.patient_like_me.v1.custom_rag.kb_search import search_knowledge_base

        if not await has_any_documents():
            logger.info("[kb_branch] no documents in knowledge base, skipping")
            return ""

        query = " ".join(filter(None, [diagnosis, key_features, patient_info_text[:200]]))
        results = await search_knowledge_base(query=query, top_k=8, min_score=0.15)

        if not results:
            logger.info("[kb_branch] no results found")
            return ""

        if emit:
            emit("kb_branch_summarizing", {"result_count": len(results)})

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"## 证据 {i} (来源: {r.filename}, 分块 {r.chunk_index})")
            lines.append(r.text)
            lines.append("")
        evidence_text = "\n".join(lines)

        from agent.patient_like_me.v1.custom_rag.kb_prompts import (
            KB_EVIDENCE_SUMMARY_SYSTEM,
            KB_EVIDENCE_SUMMARY_USER,
        )
        llm = _gemini_pro()
        summary = await _call_llm(
            llm,
            sys_prompt=KB_EVIDENCE_SUMMARY_SYSTEM,
            user_prompt=KB_EVIDENCE_SUMMARY_USER.format(
                evidence=evidence_text,
                patient_info=patient_info_text,
                diagnosis=diagnosis or "未明确",
            ),
        )

        if not summary or summary.strip().startswith("[NOT_RELEVANT]"):
            logger.info("[kb_branch] results not relevant to patient case")
            return ""

        if emit:
            emit("kb_branch_complete")
        return summary

    except Exception as e:
        logger.warning("[kb_branch] failed: %s", e)
        return ""


def _extract_treatment_block(guideline_text: str) -> str:
    """从整合后的 guideline_text 中精确切出"## 病例核心摘要"块。

    依赖 GUIDELINE_INTEGRATION_USER 的固定 Output Template 顺序：
        ## 病例核心摘要 → 1. 诊断建议 → 2. 进一步检查 →
        3. 治疗方案 → ## 二、临床关键风险与执行要点

    药品说明书模块按产品要求只看"病例核心摘要"——核心摘要里已经凝练了
    本病例需要使用的药物，并明确标注了"不建议/避免/禁用/暂缓/不应使用"，
    下游 DRUG_EXTRACT prompt 据此决定纳入/排除。

    切失败时回退到整文（保持原行为，不阻断）。
    """
    import re as _re
    m = _re.search(
        r"^##\s*病例核心摘要\s*\n(.*?)(?=\n\s*(?:1\.\s*诊断建议|##\s*二、)|\Z)",
        guideline_text or "",
        _re.DOTALL | _re.MULTILINE,
    )
    return m.group(1).strip() if m else (guideline_text or "")


@_log_timing
async def _run_drug_manual_branch(
    treatment_text: str,
    patient_info_text: str,
    patient_info: dict,
    emit,
    skip_summary_extraction: bool = False,
) -> str:
    # 默认行为(v0):上游传入整篇整合报告 → 切"病例核心摘要"块再抽药。
    # v1: skip_summary_extraction=True 时上游已直接传 treatment_report,不再切片。
    if not skip_summary_extraction:
        treatment_text = _extract_treatment_block(treatment_text)

    emit("drug_manual_extracting")
    drug_data = await step_extract_drugs_from_treatment(treatment_text, patient_info_text)
    recommended = drug_data.get("recommended_drugs", [])
    current_meds = drug_data.get("current_medications", [])
    if not current_meds:
        current_meds = [m.strip() for m in (patient_info.get("current_medications") or "").split("、") if m.strip()]

    all_drug_names = list(dict.fromkeys(recommended + current_meds))
    logger.info("[drug_manual] recommended=%s, current=%s", recommended, current_meds)

    if not all_drug_names:
        return ""

    emit("drug_manual_searching", {"drug_count": len(all_drug_names)})
    manuals = await step_search_drug_manuals(all_drug_names)
    if not manuals:
        logger.info("[drug_manual] no manuals found")
        return ""

    logger.info("[drug_manual] found %d manuals, generating cards + interaction", len(manuals))
    emit("drug_manual_analyzing", {"manual_count": len(manuals)})

    # 流式 emit: 药卡和互作分析的 token 一边产一边推
    async def _drug_card_chunk(drug_name: str, chunk: str):
        emit("section_chunk", {"section": "drug", "subsection": drug_name, "text": chunk})

    async def _drug_interaction_chunk(chunk: str):
        emit("section_chunk", {"section": "drug", "subsection": "interaction", "text": chunk})

    cards_text, interaction_text = await asyncio.gather(
        step_generate_drug_cards(manuals, treatment_text, patient_info_text, on_chunk=_drug_card_chunk),
        step_drug_interaction_analysis(manuals, current_meds, patient_info_text, on_chunk=_drug_interaction_chunk),
    )

    sections = []
    if cards_text:
        sections.append(f"### 推荐治疗方案用药说明书要点\n\n{cards_text}")
    if interaction_text:
        sections.append(f"### 合并用药相互作用分析\n\n{interaction_text}")

    if not sections:
        return ""

    return "## 药物说明书分析\n\n" + "\n\n".join(sections)


# ────────────────────── Orchestrator ──────────────────────

async def _clarify_is_no_graph(request_data: dict, clarify_session_id: str) -> bool:
    """判定澄清是否 no_graph(无决策图谱)。取"或":
      ① 前端直接回传 has_graph==False(兼容布尔/字符串);
      ② clarify_session_id 缓存里的 has_graph==False。
    任一为真即视为 no_graph。has_graph 缺失(None)不算 no_graph。"""
    def _is_false(v) -> bool:
        return v is False or (isinstance(v, str) and v.strip().lower() == "false")

    if _is_false(request_data.get("has_graph")):
        return True
    if clarify_session_id:
        try:
            from agent.common.session_store import load_session
            import json as _json
            cached = await load_session("plm", clarify_session_id)
            if cached and cached.get("report_text"):
                data = _json.loads(cached["report_text"])
                if data.get("has_graph") is False:
                    return True
        except Exception:
            logger.warning("[no_graph gate] load clarify session failed", exc_info=True)
    return False


async def run_plm_workflow(request_data: dict | str, on_event=None, task_id: str = "") -> dict:
    """
    Main entry point for PLM v1 workflow.

    Args:
        request_data: structured request dict or plain text string (backward compatible)
        on_event: optional callback(event_name: str, payload: dict) for progress tracking
        task_id: optional identifier for token usage tracking
    """
    timing_records: list[tuple[str, float]] = []
    _timing_log.set(timing_records)
    workflow_start = time.perf_counter()

    def emit(name: str, payload: Any = None):
        if on_event:
            try:
                on_event(name, payload or {})
            except Exception:
                pass

    if task_id:
        from logging_config import task_id_var
        task_id_var.set(task_id)

    if isinstance(request_data, str):
        patient_input_raw = request_data
        patient_input_merged = request_data
    else:
        patient_input_raw = (
            request_data.get('patient_input_raw')
            or request_data.get('patient_input')
            or request_data.get('patient_description')
            or ''
        ).strip()
        file_urls = request_data.get('file_urls') or []
        if file_urls and not request_data.get('_file_texts'):
            from agent.patient_like_me.v1.file_parser import parse_files
            request_data['_file_texts'] = await parse_files(
                file_urls, on_progress=lambda n, p: emit(n, p),
            )
        patient_input_merged = _merge_structured_input(request_data)

    priority_config = None
    show_supplements = True
    allowed_publishers = None
    enable_custom_kb = False
    enable_pubmed = False
    # workflow_mode：'complex'（默认，PLM 全功能）或 'simple'（sahzu 风格，关 PubMed/
    # 药物说明书/自定义 KB 与最终重写）。simple 模式下，即使调用方显式打开了
    # enable_pubmed / enable_custom_kb 也会被忽略。
    workflow_mode = "complex"
    pre_extracted_info = None
    pre_structured_text = None
    entry_mode = "report"  # 默认 report (完整报告)
    clarify_session_id_top = ""
    if isinstance(request_data, dict):
        clarify_session_id_top = (request_data.get("clarify_session_id") or "").strip()
        show_supplements = request_data.get("show_supplements", True)
        allowed_publishers = request_data.get("allowed_publishers")
        enable_custom_kb = request_data.get("enable_custom_kb", False)
        enable_pubmed = bool(request_data.get("enable_pubmed", False))
        workflow_mode = (request_data.get("mode") or "complex").strip().lower()
        entry_mode = (request_data.get("entry_mode") or "report").strip().lower()
        # 只接受 quick / report 两种, 老的 auto 不再支持
        if entry_mode not in {"quick", "report"}:
            logger.warning("[run_plm_workflow] unknown entry_mode=%r, fallback to 'report'", entry_mode)
            entry_mode = "report"
        if workflow_mode not in {"complex", "simple"}:
            logger.warning("[run_plm_workflow] unknown mode=%r, fallback to 'complex'", workflow_mode)
            workflow_mode = "complex"
        if workflow_mode == "simple":
            # 强制关闭，不接受调用方覆盖
            enable_custom_kb = False
            enable_pubmed = False
        # confirmed_patient_info：澄清回流。用户在确认页校对后通过主接口回传，
        # 工作流将跳过自动抽取直接采用。patient_input_structured 同理回传以避免
        # 重复结构化。
        if request_data.get("confirmed_patient_info"):
            pre_extracted_info = request_data["confirmed_patient_info"]
        pre_structured_text = request_data.get("patient_input_structured") or None
        # 用户在 NCCN/CSCO/CACA/ESMO 中四选一作为主指南；其余作为补充
        order = request_data.get("guideline_priority_order")
        if order:
            from agent.patient_like_me.v1.guideline_priority import GuidelinePriorityConfig
            priority_config = GuidelinePriorityConfig(order=list(order))

    # ── no_graph 拦截 ──: 澄清判定"无决策图谱"(库里没有对口且带图谱的指南, 含付费未解锁)
    # 时, 不进 part2(quick / report 都拦), 直接返回 no_graph 让前端弹窗/报错。
    # 判定取"或": 前端回传 has_graph==False, 或 clarify_session 缓存 has_graph==False, 任一即拦。
    if isinstance(request_data, dict) and await _clarify_is_no_graph(request_data, clarify_session_id_top):
        logger.info("[run_plm_workflow] no_graph 拦截, 不生成报告 (session=%s)", clarify_session_id_top)
        return {
            "output": "",
            "status": "no_graph",
            "error": "no_graph",
            "message": "该病例未匹配到含决策图谱的指南，暂不生成报告。请调整主指南（或解锁对应指南）后重试。",
            "route": "no_graph",
            "mode": None,
            "patient_info": pre_extracted_info or {},
            "token_usage": _parse_usage_log_tokens(task_id) if task_id else {},
            "retrieval_log": {},
            "graph_path": [],
        }

    # sahzu (mode=simple) 完全隔离到 product_scope=sahzu_only, 只搜 sahzu 专用库;
    # PLM/biz (mode=complex) 只搜 public 库。付费门禁通过 accessible_paid_doc_ids 单件解锁。
    from agent.patient_like_me.v1.rag import evidence as _ev
    # 显式 product_scope(如 yiyong/sahzu_only)优先; 否则 sahzu(simple)→sahzu_only, 其余→public
    _explicit_scope = ((request_data.get("product_scope") or "").strip().lower()
                       if isinstance(request_data, dict) else "")
    _product_scope = _explicit_scope or ("sahzu_only" if workflow_mode == "simple" else "public")
    _accessible_ids = None
    selected_doc_id = None
    if isinstance(request_data, dict):
        _accessible_ids = request_data.get("accessible_paid_doc_ids") or None
        selected_doc_id = request_data.get("selected_doc_id") or None
    _tok_scope = _ev.current_product_scope.set(_product_scope)
    _tok_paid = _ev.current_accessible_paid_doc_ids.set(_accessible_ids)

    try:
        return await _run_plm_workflow_body(
            patient_input_raw=patient_input_raw,
            patient_input_merged=patient_input_merged,
            emit=emit,
            task_id=task_id,
            priority_config=priority_config,
            show_supplements=show_supplements,
            allowed_publishers=allowed_publishers,
            enable_custom_kb=enable_custom_kb,
            enable_pubmed=enable_pubmed,
            workflow_mode=workflow_mode,
            pre_extracted_info=pre_extracted_info,
            pre_structured_text=pre_structured_text,
            entry_mode=entry_mode,
            clarify_session_id_top=clarify_session_id_top,
            selected_doc_id=selected_doc_id,
        )
    finally:
        _ev.current_product_scope.reset(_tok_scope)
        _ev.current_accessible_paid_doc_ids.reset(_tok_paid)
        total = time.perf_counter() - workflow_start
        logger.info(_format_timing_summary(timing_records, total))


async def _run_plm_workflow_body(
    *, patient_input_raw: str, patient_input_merged: str,
    emit, task_id: str,
    priority_config=None,
    show_supplements: bool = True,
    allowed_publishers: list[str] | None = None,
    enable_custom_kb: bool = False,
    enable_pubmed: bool = False,
    workflow_mode: str = "complex",
    pre_extracted_info: dict | None = None,
    pre_structured_text: str | None = None,
    entry_mode: str = "auto",
    clarify_session_id_top: str = "",
    selected_doc_id=None,
) -> dict:
    """
    entry_mode (beta-v1):
      'auto'   — 由 entry_router 自动决定(老行为)
      'quick'  — 强制走快速模式: quick_guideline_qa / case_question_qa / 拒绝(否则按 insufficient 拒)
      'report' — 强制走完整报告: full_report / 拒绝(否则按 insufficient 拒)
    """
    # ───── Entry router: 按 entry_mode 强制分发, 不再调 route_entry LLM ─────
    from agent.patient_like_me.v1.rag.entry_router import build_insufficient_response
    from agent.patient_like_me.v1.rag.case_qa import run_case_question_qa

    if entry_mode not in {"quick", "report"}:
        entry_mode = "report"

    # router_input 用于入口路由判定：优先用原始主诉；若用户仅传附件而无主诉，
    # 用 merged（含附件正文）做兜底，但截断到 4000 字以避免 LLM 路由被几十 KB 附件淹没。
    router_input = (patient_input_raw or "").strip()
    if not router_input and patient_input_merged:
        router_input = patient_input_merged.strip()[:4000]

    # 入口路由按 entry_mode 强制分发:
    #   quick  → 一定走 case_question_qa (不调 router LLM)
    #   report → 一定走 full_report      (不调 router LLM, fall through 到下面)
    emit("entry_mode_dispatch", {"entry_mode": entry_mode})

    # 主接口约定 (2026-07-02):
    #   前端必须先调 /api/sahzu/clarify/ 走澄清, 用户确认后再调主接口, 且必须带
    #   confirmed_patient_info (即 pre_extracted_info)。缺失即视为流程错误。
    if not pre_extracted_info:
        token_usage = _parse_usage_log_tokens(task_id) if task_id else {}
        return {
            "output": "",
            "status": "error",
            "error": "clarification_required",
            "message": "请先调用 /api/sahzu/clarify/ 拉澄清并让用户确认, 再调主接口时带上 confirmed_patient_info + clarify_session_id",
            "requires_confirmation": True,
            "route": "clarification_required",
            "mode": None,
            "patient_info": {},
            "token_usage": token_usage,
            "retrieval_log": {},
            "graph_path": [],
        }

    if entry_mode == "quick":
        if not router_input:
            token_usage = _parse_usage_log_tokens(task_id) if task_id else {}
            return build_insufficient_response(["未提供问题"], "", token_usage=token_usage)

        result = await run_case_question_qa(
            query=router_input, patient_input_merged=patient_input_merged,
            emit=emit, llm_caller=_flash_json_caller,
            priority_config=priority_config, allowed_publishers=allowed_publishers,
            clarify_session_id=clarify_session_id_top,
            selected_doc_id=selected_doc_id,
        )
        result["token_usage"] = _parse_usage_log_tokens(task_id) if task_id else {}
        return result

    # entry_mode == "report" → fall through 到下方 full_report 流程

    # confirmed_patient_info (即 pre_extracted_info) 已在上方保证非空, 直接采用。
    patient_info = pre_extracted_info
    patient_input_structured = pre_structured_text or patient_input_merged
    logger.info("[workflow] using pre-extracted info: diagnosis=%s",
                patient_info.get("primary_diagnosis", ""))
    emit("patient_info_confirmed", patient_info)

    has_clear_diagnosis = patient_info.get("has_clear_diagnosis", False)
    diagnosis = patient_info.get("primary_diagnosis", "") or ""
    key_features = " ".join(filter(None, [
        str(patient_info.get("current_symptoms") or ""),
        str(patient_info.get("test_results") or ""),
    ]))[:200]
    logger.info("[workflow] diagnosis=%s, key_features=%s", diagnosis, key_features[:100])

    # ── Step 2 (已删): CSCO 诊断明确度检查 ──
    # 历史遗留: 当 has_clear_diagnosis=False 时, 走 CSCO 兜底来推断诊断。
    # 现在诊断明确度全部交给澄清接口 (stream_clarification + 图谱探索) 处理,
    # 主接口拿到的 confirmed_patient_info 应已经过澄清, 不再做兜底。

    # ── Step 3: Parallel branches — multi-org guideline + PubMed + optional KB ──
    # Each parallel branch is wrapped so we record its individual wall-clock
    # duration even though they overlap. The slowest one is the critical-path
    # bottleneck and is surfaced in the returned ``timing_breakdown`` dict.
    emit("starting_parallel_branches")
    retrieval_log = {}

    branch_timings: dict[str, float] = {}

    async def _timed(name: str, coro):
        t0 = time.perf_counter()
        try:
            return await coro
        finally:
            branch_timings[name] = time.perf_counter() - t0

    async def _noop_pubmed():
        return ("", "")

    async def _noop_kb():
        return ""

    # v1: complex 模式启用新流程 — 主指南返回三个独立 report,
    # 由 orchestrator 拼接 + 并行(摘要/风险/沟通 LLM)和(药物分支)
    v1_mode = (workflow_mode == "complex")
    # 摘要/风险/医患沟通段两种模式都要 (sahzu simple 也需要这块给医生看);
    # 药品分支仅 complex 才跑(simple 接口本来就关 PubMed/KB/药品)。
    summary_enabled = workflow_mode in {"complex", "simple"}
    use_three_reports = summary_enabled  # 决定主指南是否返回 dict 形式

    parallel_started = time.perf_counter()

    # early-drug 仅 complex 才用:
    # guide_branch 还在跑时, 治疗段一完成就 fire 药物分支(不要等检查/诊断段)
    # treatment_ready_future: 由 _run_guide_branch 在治疗段 LLM 完成时 set
    treatment_ready_future: "asyncio.Future[str] | None" = None
    drug_task: "asyncio.Task | None" = None
    if v1_mode:
        treatment_ready_future = asyncio.get_running_loop().create_future()

        async def _drug_when_treatment_ready() -> str:
            try:
                treat_text = await treatment_ready_future
            except Exception as e:
                logger.warning("[drug_manual] treatment_ready_future cancelled/failed: %s", e)
                return ""
            try:
                emit("drug_branch_started_early")
                return await _run_drug_manual_branch(
                    treatment_text=treat_text,
                    patient_info_text=patient_input_structured,
                    patient_info=patient_info,
                    emit=emit,
                    skip_summary_extraction=True,
                )
            except Exception as e:
                logger.warning("[drug_manual] branch failed: %s", e)
                return ""

        drug_task = asyncio.create_task(_timed("drug_manual_branch", _drug_when_treatment_ready()))

    branches = [
        _timed("guide_branch", _run_multi_guide_branch(
            patient_info_text=patient_input_structured,
            diagnosis=diagnosis,
            key_features=key_features,
            priority_config=priority_config,
            show_supplements=show_supplements,
            retrieval_log=retrieval_log,
            emit=emit,
            allowed_publishers=allowed_publishers,
            primary_return_reports=use_three_reports,
            clarify_session_id=clarify_session_id_top,
            treatment_ready_future=treatment_ready_future,
            selected_doc_id=selected_doc_id,
        )),
        _timed(
            "pubmed_branch",
            _run_pubmed_branch(
                patient_input_structured,
                diagnosis=diagnosis,
                key_features=key_features,
                emit=emit,
                enable_pubmed=enable_pubmed,
            ),
        ),
        _timed(
            "kb_branch",
            _run_kb_branch(patient_input_structured, diagnosis, key_features, emit) if enable_custom_kb else _noop_kb(),
        ),
    ]
    try:
        multi_result, (pubmed_draft, pubmed_rewrite), kb_summary = await asyncio.gather(*branches)
    except Exception:
        # guide_branch 挂了,确保 future 被释放, 让 drug_task 也尽快退出
        if treatment_ready_future is not None and not treatment_ready_future.done():
            treatment_ready_future.set_exception(RuntimeError("guide_branch failed"))
        raise
    parallel_wallclock = time.perf_counter() - parallel_started

    primary_result_raw = multi_result.get("primary_result", "")
    primary_org_resolved = multi_result.get("primary_org")
    primary_status_resolved = multi_result.get("primary_status", "auto")
    secondary_evidence_resolved = multi_result.get("secondary_evidence", []) or []

    # simple / complex: primary_result 是 dict {diagnosis_report, examination_report, treatment_report, failed_sections}
    # (legacy v0): integration 字符串 — 留作兜底, 实际现在 simple/complex 都走 dict 分支
    failed_sections: list[dict] = []
    if use_three_reports and isinstance(primary_result_raw, dict):
        diagnosis_report = primary_result_raw.get("diagnosis_report") or ""
        examination_report = primary_result_raw.get("examination_report") or ""
        treatment_report = primary_result_raw.get("treatment_report") or ""
        failed_sections = primary_result_raw.get("failed_sections") or []
        # 三路代码拼接为"诊断+检查+治疗"正文,供后续摘要 LLM 和最终输出共用
        three_reports_text = _assemble_three_reports(
            diagnosis_report, examination_report, treatment_report
        )
        guideline_text = three_reports_text
    else:
        diagnosis_report = examination_report = treatment_report = ""
        three_reports_text = ""
        guideline_text = primary_result_raw if isinstance(primary_result_raw, str) else ""

    # 缓存 evidence pack 到 Redis, 让 /retry_section 能捞回来重跑 (不重新 KNN + 图谱)
    if task_id and use_three_reports:
        try:
            from agent.common.session_store import save_session
            import json as _json
            evidence_cache = {
                "diagnosis": retrieval_log.get("diagnosis", {}).get("evidence_pack", ""),
                "examination": retrieval_log.get("examination", {}).get("evidence_pack", ""),
                "treatment": retrieval_log.get("treatment", {}).get("evidence_pack", ""),
                "graph_evidence": retrieval_log.get("graph", {}).get("evidence", ""),
                "patient_info_text": patient_input_structured,
                "diagnosis_report": diagnosis_report,
                "examination_report": examination_report,
                "treatment_report": treatment_report,
            }
            await save_session(
                "plm_retry", task_id,
                report_text=_json.dumps(evidence_cache, ensure_ascii=False),
                history=[],
            )
            logger.info("[retry_cache] saved task_id=%s (evidence pack + reports)", task_id)
        except Exception as e:
            logger.warning("[retry_cache] save failed task_id=%s: %s", task_id, e)
    emit("parallel_branches_complete", {
        "primary_org": primary_org_resolved,
        "primary_status": primary_status_resolved,
        "secondary_org_count": len(secondary_evidence_resolved),
        "branch_timings": branch_timings,
        "parallel_wallclock": parallel_wallclock,
    })

    # ── Step 4: Graph path —
    # 图谱搜索已经在 _run_guide_branch 内部跟三路 search 并行跑过,
    # 这里从 retrieval_log 拿结果给前端展示,不再重复跑。
    # complex 模式: 透出完整 graph_results (含 matched_nodes / pruned_tree_mermaid),
    #              让前端能渲染决策树。
    # simple  模式: 仅占位 (保留 doc_id, mermaid 留空; sahzu 简易报告不需要图谱).
    graph_t0 = time.perf_counter()
    graph_path_results = []
    graph_section = retrieval_log.get("graph") if isinstance(retrieval_log, dict) else None
    if graph_section:
        if workflow_mode == "complex":
            graph_full = graph_section.get("results") or []
            graph_path_results = [
                {
                    "doc_id": r.get("doc_id"),
                    "decision_type": r.get("decision_type", ""),
                    "matched_nodes": r.get("matched_nodes", []),
                    "pruned_tree_mermaid": r.get("pruned_tree_mermaid", ""),
                }
                for r in graph_full if not r.get("error")
            ]
        else:
            graph_path_results = [{
                "doc_id": did,
                "decision_type": "(see graph evidence)",
                "matched_nodes": [],
                "pruned_tree_mermaid": "",
            } for did in (graph_section.get("doc_ids") or [])]
    graph_elapsed = time.perf_counter() - graph_t0

    # ── Step 5: v1 收尾 LLM(摘要+风险+沟通) 与 药物说明书 并行 ──
    # v0/simple: 仅药物说明书,串行;v1(complex): 摘要 LLM 跟药物分支并行。
    drug_manual_text = ""
    summary_block = ""  # v1: 黄色 LLM 产出的"摘要 + 风险 + 沟通"
    secondary_comparison_text = ""  # 次要指南对比(独立 tab), 与 summary/drug 并行流式
    drug_t0 = time.perf_counter()

    # 有段挂了: 跳过 summary/药品/最终拼接, 直接返 partial_error, 让前端能重试单段
    if failed_sections:
        emit("workflow_partial_error", {"failed_sections": failed_sections})
        token_usage = _parse_usage_log_tokens(task_id) if task_id else {}
        return {
            "output": "",
            "status": "partial_error",
            "error": "section_failed",
            "message": "部分报告段生成失败, 请对失败段发起重试",
            "failed_sections": failed_sections,
            "diagnosis_report": diagnosis_report,
            "examination_report": examination_report,
            "treatment_report": treatment_report,
            "patient_info": patient_info,
            "task_id": task_id,
            "token_usage": token_usage,
            "retrieval_log": {},
            "graph_path": graph_path_results,
        }

    if summary_enabled:
        # complex / simple 都跑摘要段(LLM 总结: 临床关键风险 + 医患沟通 + 病例核心摘要)。
        # complex 额外跑药品分支(early-drug 在治疗段完成时已 fire), simple 仅跑摘要。
        emit("v1_summary_drug_started" if v1_mode else "summary_started")

        async def _summary_stream() -> str:
            emit("section_started", {"section": "summary"})
            t0 = time.perf_counter()

            async def _cb(chunk: str):
                emit("section_chunk", {"section": "summary", "text": chunk})

            try:
                text = await step_summary_risk_communication(
                    diagnosis_summary=diagnosis_report,
                    examination_summary=examination_report,
                    treatment_summary=treatment_report,
                    on_chunk=_cb,
                )
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                logger.error("[section=summary] failed after retries in %.2fs: %s", elapsed, exc)
                emit("section_failed", {
                    "section": "summary",
                    "elapsed_seconds": round(elapsed, 2),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "retryable": True,
                })
                raise
            emit("section_done", {"section": "summary", "elapsed_seconds": round(time.perf_counter() - t0, 2)})
            return text

        # 次要指南对比: 用主报告三段 + 各次要机构检索证据, GLM-5.2(think) 流式产出"重大区别"。
        # 与 summary/drug 并行(都只依赖三段主报告已就绪); 补充性质, 失败不阻塞主报告。
        secondary_block_for_cmp = _assemble_secondary_block(secondary_evidence_resolved)

        async def _secondary_comparison_stream() -> str:
            # 次要对比要有主报告作对照才有意义; 主报告为空(指定主指南真的无对应内容)时跳过,
            # 交由 _assemble_final_output 的 user_specified_empty 分支明确告知前端"无内容"。
            if not secondary_block_for_cmp.strip() or not three_reports_text.strip():
                return ""
            emit("section_started", {"section": "secondary_comparison"})
            t0 = time.perf_counter()

            async def _cb(chunk: str):
                emit("section_chunk", {"section": "secondary_comparison", "text": chunk})

            try:
                text = await step_secondary_comparison(
                    three_reports_text, secondary_block_for_cmp, on_chunk=_cb,
                )
            except Exception as exc:
                logger.warning("[section=secondary_comparison] failed: %s", exc)
                emit("section_failed", {
                    "section": "secondary_comparison",
                    "elapsed_seconds": round(time.perf_counter() - t0, 2),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "retryable": False,
                })
                return ""
            emit("section_done", {"section": "secondary_comparison", "elapsed_seconds": round(time.perf_counter() - t0, 2)})
            return text

        summary_result, drug_result, secondary_result = await asyncio.gather(
            _summary_stream(),
            drug_task if drug_task is not None else asyncio.sleep(0, result=""),
            _secondary_comparison_stream(),
            return_exceptions=True,
        )
        if isinstance(summary_result, Exception):
            emit("workflow_partial_error", {"failed_sections": [{"section": "summary",
                "error": f"{type(summary_result).__name__}: {str(summary_result)[:300]}"}]})
            token_usage = _parse_usage_log_tokens(task_id) if task_id else {}
            return {
                "output": "",
                "status": "partial_error",
                "error": "section_failed",
                "message": "综合摘要段生成失败, 请对该段发起重试",
                "failed_sections": [{"section": "summary",
                    "error": f"{type(summary_result).__name__}: {str(summary_result)[:300]}"}],
                "diagnosis_report": diagnosis_report,
                "examination_report": examination_report,
                "treatment_report": treatment_report,
                "patient_info": patient_info,
                "task_id": task_id,
                "token_usage": token_usage,
                "retrieval_log": {},
                "graph_path": graph_path_results,
            }
        summary_block = summary_result
        drug_manual_text = drug_result if not isinstance(drug_result, Exception) else ""
        secondary_comparison_text = secondary_result if not isinstance(secondary_result, Exception) else ""
        if not v1_mode:
            emit("drug_manual_skipped", {"reason": "workflow_mode_simple"})
        emit("v1_summary_drug_complete" if v1_mode else "summary_complete")
    drug_elapsed = time.perf_counter() - drug_t0

    # ── Step 6: Assemble final output ──
    # complex/simple 顺序 = 摘要 → 1.诊断 → 2.检查 → 3.治疗 → 二.风险 + 三.沟通
    #                       → (complex 额外:药物说明书 + pubmed/kb)
    emit("assembling_final_output")
    if summary_enabled:
        # 拼接:摘要 + 三路报告 + 摘要 LLM 产出的风险/沟通块
        guideline_text = _assemble_v1_guideline_text(
            summary_block=summary_block,
            three_reports_text=three_reports_text,
        )
        final_output = _assemble_final_output(
            guideline_text=guideline_text,
            pubmed_rewrite=pubmed_rewrite,
            kb_summary=kb_summary,
            drug_manual_text=drug_manual_text,
            primary_org=primary_org_resolved,
            primary_status=primary_status_resolved,
            secondary_comparison=secondary_comparison_text,
        )
    else:
        # legacy: 留个兜底, 实际 simple/complex 已经都走 summary_enabled 分支
        final_output = _assemble_final_output(
            guideline_text=guideline_text,
            pubmed_rewrite=pubmed_rewrite,
            kb_summary=kb_summary,
            drug_manual_text=drug_manual_text,
            primary_org=primary_org_resolved,
            primary_status=primary_status_resolved,
            secondary_comparison=secondary_comparison_text,
        )

    # ── Build timing breakdown (concurrent-aware) ──
    sequential_timing = {
        "parallel_wallclock": round(parallel_wallclock, 2),
        "graph_path": round(graph_elapsed, 2),
        "drug_manual_branch": round(drug_elapsed, 2),
    }
    parallel_branch_timing = {k: round(v, 2) for k, v in branch_timings.items()}
    slowest_parallel = max(parallel_branch_timing.items(), key=lambda kv: kv[1]) if parallel_branch_timing else None
    critical_path = max(
        ("parallel", parallel_wallclock),
        ("graph_path", graph_elapsed),
        ("drug_manual_branch", drug_elapsed),
        key=lambda kv: kv[1],
    )
    timing_breakdown = {
        "sequential_stages": sequential_timing,
        "parallel_branches": parallel_branch_timing,
        "slowest_parallel_branch": slowest_parallel[0] if slowest_parallel else None,
        "slowest_parallel_seconds": round(slowest_parallel[1], 2) if slowest_parallel else None,
        "critical_path_stage": critical_path[0],
        "critical_path_seconds": round(critical_path[1], 2),
    }

    # ── 解析 final_output 里的 [N] 引用,产出结构化 citations 数据 ──
    # 前端拿到后,把正文里的 [1] [2,3] 渲染成可点击锚点,点击弹出对应 label
    from agent.patient_like_me.v1.rag.citations import extract_citations
    try:
        citations = extract_citations(final_output)
    except Exception as e:
        logger.warning("[citations] extract failed: %s", e)
        citations = []

    # ── Build result ──
    result_path = "guideline_only" if workflow_mode == "simple" else "full"
    emit("workflow_complete", {"path": result_path, "timing_breakdown": timing_breakdown})
    token_usage = _parse_usage_log_tokens(task_id) if task_id else {}
    # 评测用文本: 把诊断/检查/治疗 三段干净拼接, 不带摘要/风险/沟通/药物。
    # AMEGA 类基准只评判这三段 (rubric 都是治疗/检查具体动作)。
    evaluation_text = three_reports_text if v1_mode else final_output

    return {
        "output": final_output,
        "evaluation_text": evaluation_text,
        "diagnosis_report": diagnosis_report,
        "examination_report": examination_report,
        "treatment_report": treatment_report,
        "citations": citations,
        "patient_info": patient_info,
        "patient_input_raw": patient_input_raw,
        "diagnosis_clear": has_clear_diagnosis,
        "path": result_path,
        "token_usage": token_usage,
        "retrieval_log": retrieval_log,
        "graph_path": graph_path_results,
        "primary_organization": primary_org_resolved,
        "primary_status": primary_status_resolved,
        "secondary_comparison": secondary_comparison_text,
        "drug_manual_text": drug_manual_text,  # 药物说明书独立 tab(不再并进综合报告)
        "supplements": [],  # 弃用: 次要指南已改为 secondary_comparison(独立 tab)
        "patient_input_structured": patient_input_structured,
        "kb_evidence": kb_summary,
        "kb_used": bool(kb_summary),
        "kb_enabled": enable_custom_kb,
        "pubmed_used": bool(pubmed_rewrite),
        "pubmed_enabled": enable_pubmed,
        "drug_manual_used": bool(drug_manual_text),
        "timing_breakdown": timing_breakdown,
        "route": "full_case",
        "mode": "full_report",
    }


async def run_plm_workflow_stream(request_data: dict | str) -> tuple[dict, list[dict]]:
    """Streaming wrapper — collects SSE events for real-time progress."""
    events: list[dict] = []

    def collect_event(name: str, payload: dict):
        events.append({"event": name, "payload": payload})

    result = await run_plm_workflow(request_data, on_event=collect_event)
    return result, events


# ────────────────────── Phase 1: Extract & Check ──────────────────────

_SF_KEY_MAP = {
    "当前治疗阶段": "visit_stage",
    "年龄": "age",
    "性别": "gender",
    "体能状态": "performance_status",
    "病理诊断状态及亚型": "pathological_diagnosis",
    "分期": "ann_arbor_stage",
    "B症状": "b_symptoms",
    "结外受累": "extranodal_involvement",
    "CNS受累": "cns_involvement",
    "骨髓受累": "bone_marrow_involvement",
    "Bulky disease": "bulky_disease",
    "LDH状态": "ldh_status",
    "肝肾功能状态": "liver_kidney_function",
    "感染筛查": "infection_screening",
    "LVEF": "lvef",
}


def _structured_fields_to_facts(sf: dict) -> list[dict]:
    facts = []
    for label, value in sf.items():
        if value is None or value == '':
            continue
        key = _SF_KEY_MAP.get(label, label.lower().replace(" ", "_"))
        if isinstance(value, dict):
            display = ", ".join(f"{k}: {v}" for k, v in value.items() if v)
            if not display:
                continue
        elif isinstance(value, list):
            display = ", ".join(str(x) for x in value if x)
            if not display:
                continue
        else:
            display = str(value)
        facts.append({
            "key": key,
            "label": label,
            "value": display,
            "source": "user_input",
            "origin": "patient",
            "required_for_graph": False,
            "reason": "用户在结构化表单中填写",
        })
    return facts


async def _generate_fact_cards(
    patient_info: dict,
    condition_hints: list[dict],
    phase_decision: dict,
    structured_fields: dict | None = None,
    patient_text: str = "",
) -> dict:
    user_facts = _structured_fields_to_facts(structured_fields) if structured_fields else []
    user_keys = {f["key"] for f in user_facts}

    if condition_hints:
        sys_prompt = prompts.CONFIRM_PATIENT_FACTS_SYSTEM
        user_prompt = prompts.CONFIRM_PATIENT_FACTS_USER.format(
            patient_info_json=json.dumps(patient_info, ensure_ascii=False),
            condition_hints_json=json.dumps(condition_hints[:50], ensure_ascii=False),
            phase_decision_json=json.dumps(phase_decision, ensure_ascii=False),
            already_filled_keys_json=json.dumps(list(user_keys), ensure_ascii=False),
            patient_text=patient_text,
        )
    else:
        sys_prompt = prompts.CONFIRM_PATIENT_FACTS_FREEFORM_SYSTEM
        user_prompt = prompts.CONFIRM_PATIENT_FACTS_FREEFORM_USER.format(
            patient_info_json=json.dumps(patient_info, ensure_ascii=False),
            already_filled_keys_json=json.dumps(list(user_keys), ensure_ascii=False),
            patient_text=patient_text,
        )

    llm_result = await _call_gemini_structured(
        sys_prompt=sys_prompt,
        user_prompt=user_prompt,
        schema=prompts.CONFIRM_PATIENT_FACTS_SCHEMA,
        use_flash=False,
    )

    llm_facts = llm_result.get("facts", [])
    llm_facts_deduped = [f for f in llm_facts if f.get("key") not in user_keys]

    merged = user_facts + llm_facts_deduped
    merged.sort(key=lambda f: (
        0 if f["source"] == "missing" and f.get("required_for_graph") else
        1 if f["source"] == "user_input" else
        2 if f["source"] == "system_extracted" else
        3 if f["source"] == "missing" else 4
    ))

    return {"facts": merged, "summary": llm_result.get("summary", "")}


async def run_plm_extract_and_check(request_data: dict | str, on_event=None, task_id: str = "") -> dict:
    """
    Phase 1: Extract patient info → find applicable guideline → detect missing fields.

    Returns structured patient facts with filled/missing status for frontend display.
    """
    def emit(name: str, payload: Any = None):
        if on_event:
            try:
                on_event(name, payload or {})
            except Exception:
                pass

    if task_id:
        from logging_config import task_id_var
        task_id_var.set(task_id)

    if isinstance(request_data, str):
        patient_input_raw = request_data
        patient_input_merged = request_data
    else:
        patient_input_raw = (
            request_data.get('patient_input')
            or request_data.get('patient_description')
            or ''
        ).strip()
        file_urls = request_data.get('file_urls') or []
        if file_urls and not request_data.get('_file_texts'):
            from agent.patient_like_me.v1.file_parser import parse_files
            request_data['_file_texts'] = await parse_files(
                file_urls, on_progress=lambda n, p: emit(n, p),
            )
        patient_input_merged = _merge_structured_input(request_data)

    emit("extracting_patient_info")
    (patient_info, _), patient_input_structured = await asyncio.gather(
        step_extract_patient_info(patient_input_merged),
        step_structure_patient_text(patient_input_merged),
    )
    # 澄清要求 LLM 返回规范结构。若关键字段类型异常(如返回 list/dict), 视为解析失败,
    # 不做兜底修复/降级, 直接返回明确错误让前端提示用户重试。
    _expect_str = ("primary_diagnosis", "current_symptoms", "test_results", "current_medications")
    if not isinstance(patient_info, dict) or any(
        not isinstance(patient_info.get(f, ""), str) for f in _expect_str
    ):
        logger.warning("[extract_and_check] 抽取结构异常, patient_info=%r", patient_info)
        emit("error", {"message": "病例信息解析异常"})
        return {
            "error": "extraction_malformed",
            "status": "error",
            "message": "病例信息解析异常，请重试或稍作调整后重新提交。",
            "patient_info": {}, "facts": [], "summary": "",
            "patient_input_raw": patient_input_raw,
        }

    diagnosis = patient_info.get("primary_diagnosis", "") or ""
    key_features = " ".join(filter(None, [
        patient_info.get("current_symptoms", ""),
        patient_info.get("test_results", ""),
    ]))[:200]
    emit("patient_info_extracted", patient_info)

    graph_doc_ids = []
    phase_decision = {}
    condition_hints = []
    allowed_publishers = None
    if isinstance(request_data, dict):
        allowed_publishers = request_data.get("allowed_publishers")

    if diagnosis:
        try:
            _, doc_ids = await _search_docs(
                user_query=f"{diagnosis} {key_features}",
                diagnosis=diagnosis,
                key_features=key_features,
                patient_text=patient_input_structured,
                intent="treatment",
                allowed_publishers=allowed_publishers,
            )
            from agent.patient_like_me.v1.guideline import guidance_db

            for did in doc_ids:
                loaded = guidance_db.load_graph_by_doc_id(did)
                if loaded is not None:
                    graph_doc_ids.append(did)
                    guideline_id, file_id = loaded

                    phases = guidance_db.list_guidance_care_phases(guideline_id)
                    if phases:
                        from agent.patient_like_me.v1.guideline.search import _ask_phase, _build_condition_hints
                        try:
                            _doc_full = guidance_db.get_guideline_doc(guideline_id)
                            _files = _doc_full.get("files", []) if _doc_full else []
                            _gname = (_files[0].get("file_name") if _files else "") or (_doc_full or {}).get("filename", "") or ""
                        except Exception:
                            _gname = ""
                        phase_decision = await _ask_phase(patient_input_structured, phases, guideline_name=_gname)
                        condition_hints = _build_condition_hints(guideline_id)
                        emit("phase_detected", {
                            "phase_decision": phase_decision,
                            "condition_count": len(condition_hints),
                        })
                    break
        except Exception:
            # 检索真的抛异常 → 不静默降级, 直接报错提示用户。
            # (注: "没找到决策图谱" 不是异常, 不会走到这里, 仍照常继续生成 fact cards)
            logger.exception("[extract_and_check] guideline search failed")
            emit("error", {"message": "指南检索异常"})
            return {
                "error": "guideline_search_failed",
                "status": "error",
                "message": "指南检索异常，请稍后重试。",
                "patient_info": patient_info, "facts": [], "summary": "",
                "patient_input_raw": patient_input_raw,
            }

    emit("generating_fact_cards")
    structured_fields = request_data.get('structured_fields') if isinstance(request_data, dict) else None
    # 用 merged 文本（含附件正文）抽事实卡，否则附件中的检验值/用药会被丢失
    fact_cards = await _generate_fact_cards(
        patient_info, condition_hints, phase_decision,
        structured_fields=structured_fields,
        patient_text=patient_input_merged or patient_input_raw,
    )
    emit("fact_cards_ready", {"count": len(fact_cards.get("facts", []))})

    return {
        "patient_info": patient_info,
        "patient_input_raw": patient_input_raw,
        "patient_input_structured": patient_input_structured,
        "diagnosis": diagnosis,
        "phase_decision": phase_decision,
        "condition_hints": condition_hints[:30],
        "facts": fact_cards.get("facts", []),
        "summary": fact_cards.get("summary", ""),
        "graph_doc_ids": graph_doc_ids,
        "has_missing_required": any(
            f.get("source") == "missing" and f.get("required_for_graph")
            for f in fact_cards.get("facts", [])
        ),
    }
