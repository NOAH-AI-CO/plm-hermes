# -*- coding: utf-8 -*-
"""
HTTP endpoints that expose research data retrieval to the writing sandbox.

The writing agent runs LLM + shell inside a cloud sandbox. Instead of
intercepting CLI commands in the agent process, the sandbox calls these
endpoints directly via ``requests`` using the ``$API_BASE_URL`` env var.

Endpoints (all POST, under ``/api/writing/``):

- ``project-search``       — keyword search NSFC projects (ES)
- ``literature-pool``      — vector search PubMed + rank by impact factor
- ``pubmed-search``        — hybrid search PubMed articles
- ``attachment-download``  — download and parse attachments (urls <= 10)

Unified response schema::

    {"success": bool, "count": int, "results": [...], "error"?: str}

Abstract-like long fields are truncated (abstract 500 chars,
conclusion 300 chars) so the sandbox LLM can consume them without blowing
context.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent.nsfc.nsfc_query_database import (
    keyword_search_nsfc,
    rank_pubmed_records_with_if,
    vector_search_pubmed,
)
from tools.explore.attachment_tools import AttachmentDownload
from utils.pubmed_opt.pubmed_search import PubMedSearch

logger = logging.getLogger(__name__)

writing_data_router = APIRouter(prefix="/api/writing", tags=["writing-data"])


ABSTRACT_MAX = 500
CONCLUSION_MAX = 300
ATTACHMENT_URL_LIMIT = 10


def _truncate(text: Any, limit: int) -> str:
    if not text:
        return ""
    s = str(text)
    return s[:limit]


def _ok(results: list) -> dict:
    return {"success": True, "count": len(results), "results": results}


def _err(message: str) -> dict:
    return {"success": False, "count": 0, "results": [], "error": message}


# ============================================================
# project-search (NSFC keyword search, ES)
# ============================================================


class ProjectSearchRequest(BaseModel):
    keywords: List[str] = Field(..., description="Keyword list")
    start_year: Optional[int] = Field(default=2020)
    end_year: Optional[int] = Field(default=None)
    project_types: Optional[List[str]] = Field(default=None)
    codes: Optional[List[str]] = Field(default=None)
    top_k: int = Field(default=50, ge=1, le=200)


@writing_data_router.post("/project-search")
async def project_search(req: ProjectSearchRequest) -> dict:
    if not req.keywords:
        return _err("'keywords' is required")

    logger.info(
        "[writing/project-search] keywords=%s years=%s..%s top_k=%d",
        req.keywords, req.start_year, req.end_year, req.top_k,
    )

    try:
        records = keyword_search_nsfc(
            keywords=req.keywords,
            start_year=req.start_year,
            end_year=req.end_year,
            project_types=req.project_types,
            codes=req.codes,
            top_k=req.top_k,
        )
    except Exception as e:
        logger.exception("[writing/project-search] search failed")
        return _err(f"search failed: {e}")

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
            "abstract": _truncate(rec.get("projectAbstractC", ""), ABSTRACT_MAX),
            "conclusion": _truncate(rec.get("conclusionAbstract", ""), CONCLUSION_MAX),
        })

    return _ok(results)


# ============================================================
# literature-pool (vector search PubMed + IF ranking)
# ============================================================


class LiteraturePoolRequest(BaseModel):
    keywords: List[str] = Field(..., description="Keyword list")
    years: List[int] = Field(default_factory=lambda: [2021, 2022, 2023, 2024, 2025])
    max_papers: int = Field(default=40, ge=1, le=200)


@writing_data_router.post("/literature-pool")
async def literature_pool(req: LiteraturePoolRequest) -> dict:
    if not req.keywords:
        return _err("'keywords' is required")

    logger.info(
        "[writing/literature-pool] keywords=%s years=%s max=%d",
        req.keywords, req.years, req.max_papers,
    )

    try:
        records = vector_search_pubmed(
            inputs=req.keywords,
            search_years=req.years,
            top_k=max(req.max_papers * 3, 120),
        )
        if records:
            ranked = rank_pubmed_records_with_if(records, max_papers=req.max_papers)
        else:
            ranked = []
    except Exception as e:
        logger.exception("[writing/literature-pool] search failed")
        return _err(f"search failed: {e}")

    results = []
    for rec in ranked or []:
        authors_str, _author_count = _format_authors(rec)
        results.append({
            "title": rec.get("title", "Untitled"),
            "authors": authors_str,
            "journal": rec.get("journal", "") or rec.get("fulljournalname", ""),
            "year": str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4],
            "pmid": rec.get("pmid", ""),
            "doi": rec.get("doi", ""),
            "impact_factor": rec.get("jif_value"),
            "abstract": _truncate(rec.get("abstract", ""), ABSTRACT_MAX),
        })

    return _ok(results)


# ============================================================
# pubmed-search (hybrid search PubMed)
# ============================================================


class PubmedSearchRequest(BaseModel):
    pubmed_query: str = Field(..., description="Natural language query")
    years: List[int] = Field(default_factory=list)
    size: int = Field(default=20, ge=1, le=100)


@writing_data_router.post("/pubmed-search")
async def pubmed_search(req: PubmedSearchRequest) -> dict:
    if not req.pubmed_query.strip():
        return _err("'pubmed_query' is required")

    logger.info(
        "[writing/pubmed-search] query=%r years=%s size=%d",
        req.pubmed_query, req.years, req.size,
    )

    try:
        searcher = PubMedSearch()
        records = await searcher.hybrid_search(
            query=req.pubmed_query,
            years=req.years,
            size=req.size,
        )
    except Exception as e:
        logger.exception("[writing/pubmed-search] search failed")
        return _err(f"search failed: {e}")

    results = []
    for rec in records or []:
        authors_str, _ = _format_authors(rec)
        results.append({
            "title": rec.get("title", "Untitled"),
            "authors": authors_str,
            "journal": rec.get("journal", "") or rec.get("fulljournalname", ""),
            "year": str(rec.get("year_of_publication", "") or rec.get("pubdate", ""))[:4],
            "pmid": rec.get("pmid", ""),
            "doi": rec.get("doi", ""),
            "abstract": _truncate(rec.get("abstract", ""), ABSTRACT_MAX),
        })

    return _ok(results)


# ============================================================
# attachment-download
# ============================================================


class AttachmentDownloadRequest(BaseModel):
    urls: List[str] = Field(..., description=f"Up to {ATTACHMENT_URL_LIMIT} URLs")
    explanation: str = Field(default="writing agent download")


@writing_data_router.post("/attachment-download")
async def attachment_download(req: AttachmentDownloadRequest) -> dict:
    if not req.urls:
        return _err("'urls' is required")
    if len(req.urls) > ATTACHMENT_URL_LIMIT:
        return _err(f"too many urls (max {ATTACHMENT_URL_LIMIT})")

    logger.info("[writing/attachment-download] count=%d", len(req.urls))

    tool = AttachmentDownload()
    ctx = SimpleNamespace(id="", call_id="")
    collected: list = []
    try:
        async for chunk in tool.run(urls=req.urls, explanation=req.explanation, _context=ctx):
            if hasattr(chunk, "result"):
                payload = chunk.result
                if isinstance(payload, list):
                    collected = payload
                elif payload is not None:
                    collected = [payload]
    except Exception as e:
        logger.exception("[writing/attachment-download] download failed")
        return _err(f"download failed: {e}")

    results = []
    for r in collected:
        if not isinstance(r, dict):
            continue
        results.append({
            "filename": r.get("filename", "unknown"),
            "success": bool(r.get("success", False)),
            "type": r.get("type", ""),
            "blob_path": r.get("blob_path", ""),
            "text_preview": _truncate(r.get("text_preview", ""), ABSTRACT_MAX),
            "data_description": r.get("data_description", ""),
            "error": r.get("error", ""),
        })

    return _ok(results)


# ============================================================
# Shared helpers
# ============================================================


def _format_authors(rec: dict) -> tuple[str, int]:
    """Return (formatted_author_string, original_author_count)."""
    authors = rec.get("author", "") or rec.get("authors", "")
    if isinstance(authors, list):
        names: list[str] = []
        for a in authors[:3]:
            if isinstance(a, dict):
                name = (
                    a.get("name")
                    or a.get("full_name")
                    or a.get("last_name")
                    or ""
                )
            else:
                name = str(a)
            name = name.strip()
            if name:
                names.append(name)
        joined = ", ".join(names)
        if len(authors) > 3:
            joined = f"{joined} et al" if joined else "et al"
        return joined, len(authors)
    return str(authors), 1 if authors else 0
