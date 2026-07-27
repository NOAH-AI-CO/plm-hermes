"""
PLM case-question QA path.

Used when the entry router classifies the input as ``full_case`` and the
sub-router classifies the internal mode as ``case_question_qa``: the user
provides a complete case AND asks one or several specific bounded questions.

We:
  1. Extract {patient_summary, user_questions} from the raw input (Gemini Flash, JSON).
  2. Retrieve a guideline evidence pack focused on the combined questions.
  3. Generate the structured answer (# 病例问题摘要 / ## 问题 N / ## 参考文献).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


FALLBACK_OUTPUT = "当前检索到的指南证据不足以回答该问题。"


def _format_questions_for_prompt(user_questions: list[str]) -> str:
    return "\n".join(f"{i}. {q}" for i, q in enumerate(user_questions, 1))


def _build_retrieval_query(patient_summary: str, user_questions: list[str]) -> str:
    parts: list[str] = []
    if patient_summary:
        parts.append(patient_summary.strip())
    parts.extend(q for q in user_questions if q)
    return "\n".join(parts).strip()


async def _extract_summary_and_questions(query: str) -> tuple[str, list[str]]:
    from agent.patient_like_me.v1.rag.workflow import _call_gemini_structured

    try:
        result = await _call_gemini_structured(
            sys_prompt=prompts.CASE_QA_EXTRACT_QUESTIONS_SYSTEM,
            user_prompt=prompts.CASE_QA_EXTRACT_QUESTIONS_USER.format(query=query),
            schema=prompts.CASE_QA_EXTRACT_QUESTIONS_SCHEMA,
            use_flash=True,
        )
    except Exception:
        logger.exception("[case_qa] question extraction failed")
        result = {}

    if not isinstance(result, dict):
        result = {}

    patient_summary = result.get("patient_summary") or ""
    if not isinstance(patient_summary, str):
        patient_summary = ""
    patient_summary = patient_summary.strip()

    raw_questions = result.get("user_questions") or []
    if not isinstance(raw_questions, list):
        raw_questions = []
    user_questions = [str(q).strip() for q in raw_questions if str(q).strip()]
    if not user_questions:
        user_questions = [query.strip()]

    return patient_summary, user_questions


async def run_case_question_qa(
    query: str,
    patient_input_merged: str,
    emit: Callable[[str, Any], None] | None = None,
    llm_caller: Callable[[str, str], Awaitable[str]] | None = None,
    token_usage: dict | None = None,
    priority_config=None,
    allowed_publishers: list[str] | None = None,
    clarify_session_id: str = "",
    selected_doc_id=None,
) -> dict:
    """Answer a complete-case-with-specific-questions input.

    Returns the standard PLM response dict shape with
    ``route='full_case'``, ``mode='case_question_qa'``.
    """
    from agent.patient_like_me.v1.rag.evidence import retrieve_guideline_evidence_pack
    from agent.patient_like_me.v1.rag.workflow import (
        _call_llm,
        _call_llm_stream,
        _flash_json_caller,
        _gemini_flash,
        _gemini_pro,
        _select_document_ids,
    )

    if emit is None:
        emit = lambda n, p=None: None

    query = (query or "").strip()
    patient_input_merged = (patient_input_merged or "").strip()
    retrieval_log: dict[str, Any] = {}

    # ── Step 1: extract patient summary + user questions ──
    emit("case_qa_extracting")
    patient_summary, user_questions = await _extract_summary_and_questions(query)
    emit(
        "case_qa_extracted",
        {"user_question_count": len(user_questions), "has_patient_summary": bool(patient_summary)},
    )

    # ── Step 2: retrieve evidence pack ──
    retrieval_query = _build_retrieval_query(patient_summary, user_questions)
    emit("case_qa_searching", {"retrieval_query_chars": len(retrieval_query)})

    evidence_pack = ""
    doc_ids: list[int] = []
    # 用 guideline_priority_order(用户选的主指南)锚定 quick 的检索范围，与主报告(report)
    # 一致；再受组织权限白名单(allowed_publishers)约束。否则 quick 会在权限内全部机构里乱选
    # 文档：如"皮肤DLBCL腿型"被选到 CACA 泛淋巴瘤共识、漏掉用户选定的 NCCN 决策 → 误判
    # "证据不足"。注意后端通常会把 allowed_publishers 注入成"组织已解锁的全部机构"(较宽)，
    # 所以必须用 priority 在其内再收紧，而不能只在 allowed_publishers 为空时才用 priority。
    priority_order = [p for p in (getattr(priority_config, "order", None) or []) if p] if priority_config else []
    if priority_order:
        if allowed_publishers:
            allowed_set = {p.upper() for p in allowed_publishers if p}
            narrowed = [p for p in priority_order if p.upper() in allowed_set]
            effective_allowed = narrowed or list(allowed_publishers)
        else:
            effective_allowed = priority_order
    else:
        effective_allowed = list(allowed_publishers) if allowed_publishers else None
    # 追问/快速模式若带来了用户已选定的指南 doc_id, 硬锁到该指南(与主报告同源), 保证追问依据一致
    _filter_ids = None
    try:
        if selected_doc_id:
            _filter_ids = [int(selected_doc_id)]
    except Exception:
        _filter_ids = None
    try:
        evidence_pack, doc_ids = await retrieve_guideline_evidence_pack(
            user_query=retrieval_query or query,
            diagnosis="",
            key_features="",
            patient_text=patient_summary or query,
            intent="treatment",
            selector=_select_document_ids,
            llm_caller=llm_caller or _flash_json_caller,
            max_docs=8,
            max_chunks=22,
            allowed_publishers=effective_allowed,
            filter_doc_ids=_filter_ids,
        )
    except Exception:
        logger.exception("[case_qa] evidence retrieval failed")

    retrieval_log["case_qa"] = {
        "retrieval_query": retrieval_query,
        "doc_ids": doc_ids,
        "chars": len(evidence_pack or ""),
        "evidence_pack": evidence_pack or "",
    }

    # ── Step 3: answer with Gemini Flash ──
    # WHY: 之前空 evidence_pack / LLM 抛错 / LLM 返回空都会降级到 FALLBACK_OUTPUT
    # ("当前检索到的指南证据不足以回答该问题。") 让用户拿到假兜底无法判断真因。
    # 现在: 任何失败一律向上抛，让调用方决定是否重试。
    emit("case_qa_answering")
    if not (evidence_pack or "").strip():
        raise RuntimeError(
            f"[case_qa] 检索到的 evidence_pack 为空 (doc_ids={doc_ids}, "
            f"retrieval_query[:80]={retrieval_query[:80]!r})，无法生成回答"
        )

    # 图谱证据: quick 也走图谱(与澄清/主报告一致)。复用澄清阶段缓存的命中节点(clarify_session_id)
    # 或就地跑图谱定位, 命中则把决策路径作为**最高优先级证据**并进 evidence, 让应答按图谱分支作答。
    graph_evidence = ""
    if doc_ids:
        try:
            from agent.patient_like_me.v1.rag.workflow import _run_graph_path_for_docs, _format_graph_evidence
            graph_results = await _run_graph_path_for_docs(
                patient_summary or query, doc_ids, emit=emit, clarify_session_id=clarify_session_id,
            )
            graph_evidence = _format_graph_evidence(graph_results)
        except Exception:
            logger.warning("[case_qa] graph path failed", exc_info=True)
    if graph_evidence:
        evidence_for_answer = (
            "# 决策图谱证据（最高优先级，优先据此回答）\n" + graph_evidence
            + "\n\n# 指南检索证据\n" + evidence_pack
        )
        retrieval_log["case_qa"]["graph_evidence"] = graph_evidence
    else:
        evidence_for_answer = evidence_pack
    # 用 Pro/thinking 模型回答 — 这是用户面前的医学问答核心环节，
    # 之前用 Flash 是历史遗漏。Flash 留给 case_qa 内部的 query 改写/筛选用。
    llm = _gemini_pro()
    sys_prompt = prompts.CASE_QA_SYSTEM
    user_prompt = prompts.CASE_QA_USER.format(
        query=query,
        patient_summary=patient_summary or "（未自动抽取到结构化病例摘要，请基于用户原始输入推断）",
        user_questions=_format_questions_for_prompt(user_questions),
        guideline_evidence=evidence_for_answer,
    )
    # token 级流式: 跟 report 模式 emit 同一套 section_* 事件 (section="answer"),
    # payload 形状跟 report 严格对齐, 前端用一份 section_chunk handler 即可
    emit("section_started", {"section": "answer"})
    _t0 = time.perf_counter()

    async def _on_chunk(chunk: str):
        emit("section_chunk", {"section": "answer", "text": chunk})

    raw = await _call_llm_stream(
        llm, sys_prompt=sys_prompt, user_prompt=user_prompt,
        on_chunk=_on_chunk, temperature=0.0,
    )
    if not (raw and raw.strip()):
        raise RuntimeError(
            f"[case_qa] LLM 返回空字符串 (evidence_pack chars={len(evidence_pack)}, "
            f"questions={user_questions})，可能 reasoning 截断或安全拦截"
        )
    output = raw.strip()
    emit("section_done", {"section": "answer", "elapsed_seconds": round(time.perf_counter() - _t0, 2)})

    # ── Step 4: 主/次指南标注（仅响应字段，不再发起额外 LLM 调用）──
    from agent.patient_like_me.v1.rag.evidence import fetch_orgs_for_doc_ids
    from agent.patient_like_me.v1.guideline_priority import resolve_priority
    hit_orgs = fetch_orgs_for_doc_ids(doc_ids)
    primary_org, primary_status, supplements = _resolve_primary_for_single_pack(
        hit_orgs=hit_orgs, priority_config=priority_config,
    )

    # 跟 report 模式一致, 把 output 里的 [N] / "参考文献:" 段解析成结构化数组
    # 给前端做 [N] 点击弹出引用 label 的交互。失败也不阻断主流程。
    from agent.patient_like_me.v1.rag.citations import extract_citations
    try:
        citations = extract_citations(output)
    except Exception:
        logger.warning("[case_qa] citations extract failed", exc_info=True)
        citations = []

    emit("case_qa_complete")

    return {
        "output": output,
        "route": "full_case",
        "mode": "case_question_qa",
        "patient_summary": patient_summary,
        "user_questions": user_questions,
        "citations": citations,
        "patient_info": {},
        "diagnosis_clear": None,
        "path": "case_qa",
        "token_usage": token_usage or {},
        "retrieval_log": retrieval_log,
        "graph_path": [],
        "primary_organization": primary_org,
        "primary_status": primary_status,
        "supplements": supplements,
        "patient_input_structured": patient_input_merged,
        "kb_evidence": "",
        "kb_used": False,
        "kb_enabled": False,
    }


def _resolve_primary_for_single_pack(
    hit_orgs: dict[str, list[str]],
    priority_config,
) -> tuple[str | None, str, list[dict]]:
    """Single-pack retrieval paths (case_qa / quick_qa) don't run multi-org branches.
    We only label which org the retrieval actually hit, against user priority if any.

    Returns (primary_org, primary_status, supplements[]).
    supplements only carry {organization, doc_count} — no LLM-generated content,
    because single-pack paths must stay fast.
    """
    from agent.patient_like_me.v1.guideline_priority import resolve_priority
    if priority_config is None:
        # 用户未指定 → 按默认优先级在命中里挑一个
        priority = resolve_priority(None)
        primary = next((o for o in priority if o in hit_orgs), None) or (
            next(iter(hit_orgs)) if hit_orgs else None
        )
        secondaries = [
            {"organization": o, "doc_count": len(fnames), "supplement_content": "", "diff_with_primary": ""}
            for o, fnames in hit_orgs.items() if o != primary
        ]
        return primary, "auto", secondaries

    # 用户指定了优先级
    priority = resolve_priority(priority_config)
    user_top = priority[0] if priority else None
    if user_top and user_top in hit_orgs:
        secondaries = [
            {"organization": o, "doc_count": len(fnames), "supplement_content": "", "diff_with_primary": ""}
            for o, fnames in hit_orgs.items() if o != user_top
        ]
        return user_top, "matched", secondaries
    # 用户指定的最高优先级 org 没召回到 → 严格主指南为空，其他全归次要
    secondaries = [
        {"organization": o, "doc_count": len(fnames), "supplement_content": "", "diff_with_primary": ""}
        for o, fnames in hit_orgs.items()
    ]
    return user_top, "user_specified_empty", secondaries
