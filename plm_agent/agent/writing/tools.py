# -*- coding: utf-8 -*-
"""Function tools exposed to the writing manager Agent.

All tools receive ``RunContextWrapper[WritingContext]`` via the SDK's
``function_tool`` injection, giving them access to the sandbox manager
and the API base URL.

Five tools:

- ``run_in_sandbox``       — execute an ad-hoc shell command in the AgentRun
                             sandbox; ``$API_BASE_URL`` is exported into the
                             command so shell-side scripts can POST to
                             ``writing_data_router``.
- ``project_search``       — NSFC keyword search (ES).
- ``literature_pool``      — vector-search PubMed + IF ranking.
- ``pubmed_search``        — hybrid search PubMed.
- ``attachment_download``  — download/parse up to 10 URLs.

The four data tools call the Python functions backing ``writing_data_router``
directly (same process), avoiding an HTTP roundtrip. The sandbox path is
still available for LLM-written shell code that prefers the HTTP contract.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Optional

from agents import RunContextWrapper, function_tool

from agent.writing.context import WritingContext
from agent.writing.guardrails import (
    sandbox_output_size_guardrail,
    url_count_guardrail,
)

logger = logging.getLogger(__name__)


# ============================================================
# run_in_sandbox — shell passthrough with API_BASE_URL injected
# ============================================================

_SANDBOX_OUTPUT_LIMIT = 15000


@function_tool(tool_output_guardrails=[sandbox_output_size_guardrail])
async def run_in_sandbox(
    ctx: RunContextWrapper[WritingContext],
    command: str,
    timeout: int = 120,
) -> str:
    """Execute a bash command in the cloud sandbox and return its stdout/stderr.

    The environment variable ``API_BASE_URL`` is exported into the command so
    the shell can reach the writing data endpoints (``/api/writing/*``).
    Use this for Python scripts, file I/O, pandoc/docling conversions, etc.

    Args:
        command: Shell command string (bash).
        timeout: Max seconds before the sandbox kills the command (default 120).
    """
    sbox = ctx.context.sandbox_manager
    if sbox is None:
        return "Error: sandbox_manager is not configured for this run"

    await sbox.ensure_sandbox()

    base_url = ctx.context.api_base_url or ""
    wrapped = command
    if base_url:
        wrapped = f"export API_BASE_URL={base_url!r}; {command}"

    try:
        result = await sbox.execute_shell(command=wrapped, timeout=timeout)
    except Exception as e:
        logger.exception("[writing.run_in_sandbox] execution failed")
        return f"Error: sandbox execution failed: {e}"

    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    exit_code = result.get("exit_code", -1)

    if len(stdout) > _SANDBOX_OUTPUT_LIMIT:
        stdout = stdout[:_SANDBOX_OUTPUT_LIMIT] + f"\n...[stdout truncated from {len(stdout)} chars]"
    if len(stderr) > _SANDBOX_OUTPUT_LIMIT:
        stderr = stderr[:_SANDBOX_OUTPUT_LIMIT] + f"\n...[stderr truncated from {len(stderr)} chars]"

    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"STDERR: {stderr}")
    if exit_code != 0:
        parts.append(f"Exit code: {exit_code}")
    return "\n".join(parts) if parts else "(no output)"


# ============================================================
# Data tools — direct calls into the same functions backing
# writing_data_router (host side only; sandbox still uses HTTP).
# ============================================================


def _truncate(text: Any, limit: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s[:limit]


def _format_authors(rec: dict) -> str:
    authors = rec.get("author", "") or rec.get("authors", "")
    if isinstance(authors, list):
        names: list[str] = []
        for a in authors[:3]:
            if isinstance(a, dict):
                name = a.get("name") or a.get("full_name") or a.get("last_name") or ""
            else:
                name = str(a)
            name = name.strip()
            if name:
                names.append(name)
        joined = ", ".join(names)
        if len(authors) > 3:
            joined = f"{joined} et al" if joined else "et al"
        return joined
    return str(authors)


@function_tool
async def project_search(
    ctx: RunContextWrapper[WritingContext],
    keywords: List[str],
    start_year: Optional[int] = 2020,
    end_year: Optional[int] = None,
    project_types: Optional[List[str]] = None,
    codes: Optional[List[str]] = None,
    top_k: int = 50,
) -> dict:
    """Keyword-search NSFC funded projects (Elasticsearch).

    Returns a dict with ``success``, ``count``, ``results`` and optional ``error``.
    Each result includes project_name, pi, unit, keywords, start_date, end_date,
    ratify_no, type, code, score, abstract (≤500 chars), conclusion (≤300 chars).
    """
    from agent.nsfc.nsfc_query_database import keyword_search_nsfc

    if not keywords:
        return {"success": False, "count": 0, "results": [], "error": "'keywords' is required"}

    logger.info(
        "[writing.project_search] keywords=%s years=%s..%s top_k=%d",
        keywords, start_year, end_year, top_k,
    )
    try:
        records = keyword_search_nsfc(
            keywords=keywords,
            start_year=start_year,
            end_year=end_year,
            project_types=project_types,
            codes=codes,
            top_k=top_k,
        )
    except Exception as e:
        logger.exception("[writing.project_search] search failed")
        return {"success": False, "count": 0, "results": [], "error": f"search failed: {e}"}

    results = []
    for rec in records or []:
        results.append({
            "project_name": rec.get("projectName", ""),
            "pi": rec.get("projectAdmin", ""),
            "unit": rec.get("dependUnit", ""),
            "keywords": rec.get("keywordList", []),
            "start_date": str(rec.get("researchTimeStart", ""))[:10],
            "end_date": str(rec.get("researchTimeEnd", ""))[:10],
            "ratify_no": rec.get("ratifyNo", ""),
            "type": rec.get("type", ""),
            "code": rec.get("code", ""),
            "score": rec.get("_score"),
            "abstract": _truncate(rec.get("projectAbstractC", ""), 500),
            "conclusion": _truncate(rec.get("conclusionAbstract", ""), 300),
        })
    return {"success": True, "count": len(results), "results": results}


@function_tool
async def literature_pool(
    ctx: RunContextWrapper[WritingContext],
    keywords: List[str],
    years: Optional[List[int]] = None,
    max_papers: int = 40,
) -> dict:
    """Vector-search PubMed and rank results by journal impact factor.

    Returns a citation-ready literature pool. Each entry has title, authors,
    journal, year, pmid, doi, impact_factor, abstract (≤500 chars).
    """
    from agent.nsfc.nsfc_query_database import (
        rank_pubmed_records_with_if,
        vector_search_pubmed,
    )

    if not keywords:
        return {"success": False, "count": 0, "results": [], "error": "'keywords' is required"}

    search_years = years or [2021, 2022, 2023, 2024, 2025]
    logger.info(
        "[writing.literature_pool] keywords=%s years=%s max=%d",
        keywords, search_years, max_papers,
    )
    try:
        records = vector_search_pubmed(
            inputs=keywords,
            search_years=search_years,
            top_k=max(max_papers * 3, 120),
        )
        ranked = rank_pubmed_records_with_if(records, max_papers=max_papers) if records else []
    except Exception as e:
        logger.exception("[writing.literature_pool] search failed")
        return {"success": False, "count": 0, "results": [], "error": f"search failed: {e}"}

    results = []
    for rec in ranked or []:
        results.append({
            "title": rec.get("title", "Untitled"),
            "authors": _format_authors(rec),
            "journal": rec.get("journal", "") or rec.get("fulljournalname", ""),
            "year": str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4],
            "pmid": rec.get("pmid", ""),
            "doi": rec.get("doi", ""),
            "impact_factor": rec.get("jif_value"),
            "abstract": _truncate(rec.get("abstract", ""), 500),
        })
    return {"success": True, "count": len(results), "results": results}


@function_tool
async def pubmed_search(
    ctx: RunContextWrapper[WritingContext],
    pubmed_query: str,
    years: Optional[List[int]] = None,
    size: int = 20,
) -> dict:
    """Hybrid-search (BM25 + vector) PubMed articles by natural-language query.

    Returns a list of articles with title, authors, journal, year, pmid, doi,
    abstract (≤500 chars).
    """
    from utils.pubmed_opt.pubmed_search import PubMedSearch

    if not pubmed_query or not pubmed_query.strip():
        return {"success": False, "count": 0, "results": [], "error": "'pubmed_query' is required"}

    y = years or []
    logger.info(
        "[writing.pubmed_search] query=%r years=%s size=%d",
        pubmed_query, y, size,
    )
    try:
        searcher = PubMedSearch()
        records = await searcher.hybrid_search(query=pubmed_query, years=y, size=size)
    except Exception as e:
        logger.exception("[writing.pubmed_search] search failed")
        return {"success": False, "count": 0, "results": [], "error": f"search failed: {e}"}

    results = []
    for rec in records or []:
        results.append({
            "title": rec.get("title", "Untitled"),
            "authors": _format_authors(rec),
            "journal": rec.get("journal", "") or rec.get("fulljournalname", ""),
            "year": str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4],
            "pmid": rec.get("pmid", ""),
            "doi": rec.get("doi", ""),
            "abstract": _truncate(rec.get("abstract", ""), 500),
        })
    return {"success": True, "count": len(results), "results": results}


@function_tool(tool_input_guardrails=[url_count_guardrail])
async def attachment_download(
    ctx: RunContextWrapper[WritingContext],
    urls: List[str],
    explanation: str = "writing agent download",
) -> dict:
    """Download up to 10 attachment URLs and return parsed previews.

    Each result contains filename, success, type, blob_path (usable inside
    the sandbox), text_preview (≤500 chars), data_description, error.
    """
    from tools.explore.attachment_tools import AttachmentDownload

    if not urls:
        return {"success": False, "count": 0, "results": [], "error": "'urls' is required"}

    logger.info("[writing.attachment_download] count=%d", len(urls))

    tool = AttachmentDownload()
    inner_ctx = SimpleNamespace(id="", call_id="")
    collected: list = []
    try:
        async for chunk in tool.run(urls=urls, explanation=explanation, _context=inner_ctx):
            if hasattr(chunk, "result"):
                payload = chunk.result
                if isinstance(payload, list):
                    collected = payload
                elif payload is not None:
                    collected = [payload]
    except Exception as e:
        logger.exception("[writing.attachment_download] download failed")
        return {"success": False, "count": 0, "results": [], "error": f"download failed: {e}"}

    results = []
    for r in collected:
        if not isinstance(r, dict):
            continue
        results.append({
            "filename": r.get("filename", "unknown"),
            "success": bool(r.get("success", False)),
            "type": r.get("type", ""),
            "blob_path": r.get("blob_path", ""),
            "text_preview": _truncate(r.get("text_preview", ""), 500),
            "data_description": r.get("data_description", ""),
            "error": r.get("error", ""),
        })
    return {"success": True, "count": len(results), "results": results}


ALL_TOOLS = [
    run_in_sandbox,
    project_search,
    literature_pool,
    pubmed_search,
    attachment_download,
]
