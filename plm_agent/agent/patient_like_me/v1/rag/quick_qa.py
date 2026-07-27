"""
PLM quick guideline QA path.

Used when the entry router classifies the user input as ``quick_guideline_qa``:
the user is asking a guideline-level / population-level question without a
specific patient case. We retrieve a small evidence pack from the guideline
ES index and let Gemini Flash answer concisely.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


FALLBACK_OUTPUT = "当前检索到的指南证据不足以回答该问题。"


async def run_quick_guideline_qa(
    query: str,
    retrieval_query: str,
    emit: Callable[[str, Any], None] | None = None,
    llm_caller: Callable[[str, str], Awaitable[str]] | None = None,
    token_usage: dict | None = None,
    priority_config=None,
    allowed_publishers: list[str] | None = None,
) -> dict:
    """Answer a guideline-level question grounded in retrieved evidence.

    Returns the standard PLM response dict shape with ``route='quick_guideline_qa'``.
    """
    from agent.patient_like_me.v1.rag.evidence import retrieve_guideline_evidence_pack
    from agent.patient_like_me.v1.rag.workflow import (
        _flash_json_caller,
        _gemini_flash,
        _select_document_ids,
    )

    if emit is None:
        emit = lambda n, p=None: None

    query = (query or "").strip()
    retrieval_query = (retrieval_query or "").strip() or query

    retrieval_log: dict[str, Any] = {}

    # ── Step 1: retrieve evidence pack ──
    emit("quick_qa_searching", {"retrieval_query": retrieval_query})
    evidence_pack = ""
    doc_ids: list[int] = []
    try:
        evidence_pack, doc_ids = await retrieve_guideline_evidence_pack(
            user_query=retrieval_query,
            diagnosis="",
            key_features="",
            patient_text=retrieval_query,
            intent="treatment",
            selector=_select_document_ids,
            llm_caller=llm_caller or _flash_json_caller,
            max_docs=3,
            max_chunks=6,
            allowed_publishers=allowed_publishers,
        )
    except Exception:
        logger.exception("[quick_qa] evidence retrieval failed")

    retrieval_log["quick_qa"] = {
        "retrieval_query": retrieval_query,
        "doc_ids": doc_ids,
        "chars": len(evidence_pack or ""),
        "evidence_pack": evidence_pack or "",
    }

    # ── Step 2: answer with Gemini Flash ──
    # WHY: 同 case_qa 的修正 — 不再用 fallback 字符串掩盖失败，让错误冒泡。
    emit("quick_qa_answering")
    if not (evidence_pack or "").strip():
        raise RuntimeError(
            f"[quick_qa] 检索到的 evidence_pack 为空 (doc_ids={doc_ids}, "
            f"retrieval_query[:80]={retrieval_query[:80]!r})，无法生成回答"
        )
    llm = _gemini_flash()
    sys_prompt = prompts.QUICK_GUIDELINE_QA_SYSTEM
    user_prompt = prompts.QUICK_GUIDELINE_QA_USER.format(
        query=query, guideline_evidence=evidence_pack,
    )
    # 走 _call_llm 让 step_dump 能拦截到
    from agent.patient_like_me.v1.rag.workflow import _call_llm
    raw = await _call_llm(llm, sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=0.0)
    if not (raw and raw.strip()):
        raise RuntimeError(
            f"[quick_qa] LLM 返回空字符串 (evidence_pack chars={len(evidence_pack)}, "
            f"query[:80]={query[:80]!r})，可能 reasoning 截断或安全拦截"
        )
    output = raw.strip()

    # 主/次指南标注（仅响应字段）
    from agent.patient_like_me.v1.rag.evidence import fetch_orgs_for_doc_ids
    from agent.patient_like_me.v1.rag.case_qa import _resolve_primary_for_single_pack
    hit_orgs = fetch_orgs_for_doc_ids(doc_ids)
    primary_org, primary_status, supplements = _resolve_primary_for_single_pack(
        hit_orgs=hit_orgs, priority_config=priority_config,
    )

    emit("quick_qa_complete")

    return {
        "output": output,
        "route": "quick_guideline_qa",
        "mode": None,
        "retrieval_query": retrieval_query,
        "patient_info": {},
        "diagnosis_clear": None,
        "path": "quick_qa",
        "token_usage": token_usage or {},
        "retrieval_log": retrieval_log,
        "graph_path": [],
        "primary_organization": primary_org,
        "primary_status": primary_status,
        "supplements": supplements,
        "patient_input_structured": "",
        "kb_evidence": "",
        "kb_used": False,
        "kb_enabled": False,
    }
