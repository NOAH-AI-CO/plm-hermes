"""
Clinical guidelines search on Noah ES. Used by the mindsearch ClinicalGuidelineSearch tool.
Does not modify or depend on IIT flow; reuses es_guideline_fetch.fetch_guideline_by_ids for full doc fetch.
"""
import asyncio
import logging
from typing import Any, List

import tiktoken
from utils.core.elasticsearch_client import ElasticsearchClientSingleton

logger = logging.getLogger(__name__)

INDEX_NAME = "guidelines"
SOURCE_FIELDS_SEARCH = ["id", "title_cn", "toc"]
PIPELINE_MAX_TOKENS = 80_000
SECTION_CONTENT_TRUNCATE_CHARS = 0


def _count_tokens(text) -> int:
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.encoding_for_model("gpt-4o")
    if isinstance(text, str):
        return len(enc.encode(text))
    if isinstance(text, list):
        n = 0
        for doc in text:
            n += len(enc.encode(doc))
        return n
    return 0


async def search_guidelines(query: str, size: int = 10) -> List[dict]:
    """
    Search guidelines index on Noah ES by text and optional vector (title_cn_vector).
    Returns list of {id, title_cn, toc} without pages.
    """
    if not query or not query.strip():
        logger.warning("[search_guidelines] Empty query provided")
        return []

    get_embedding = None
    try:
        from agent.iit.utils.guidelines.embedding import get_embedding
    except Exception as e:
        logger.warning("[search_guidelines] get_embedding import failed, will use text search only: %s", e)

    vector = None
    if get_embedding is not None:
        try:
            vector = await asyncio.to_thread(get_embedding, query.strip())
            logger.info(f"[search_guidelines] Got embedding vector, length: {len(vector) if vector else 0}")
        except Exception as e:
            logger.warning("[search_guidelines] get_embedding failed, will use text search only: %s", e)
            vector = None

    body: dict[str, Any] = {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"cn_file_flg.keyword": "Y"}},
                    {"exists": {"field": "pages"}},
                    {"exists": {"field": "toc"}},
                ],
                "should": [
                    {"match": {"title_cn": {"query": query.strip(), "boost": 2}}},
                    {"match": {"title_en": {"query": query.strip(), "boost": 2}}},
                    {"match": {"toc": {"query": query.strip(), "boost": 1}}},
                    {"match": {"title_cn": {"query": "CSCO", "boost": 100}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "_source": SOURCE_FIELDS_SEARCH,
        "size": size,
    }

    if vector is not None:
        body["knn"] = {
            "field": "title_cn_vector",
            "query_vector": vector,
            "k": size,
            "num_candidates": min(80, size * 2),
            "filter": [
                {"term": {"cn_file_flg.keyword": "Y"}},
                {"exists": {"field": "pages"}},
                {"exists": {"field": "toc"}},
            ],
        }

    client = ElasticsearchClientSingleton.get_asyncclient()
    try:
        resp = await client.search(index=INDEX_NAME, **body)
    except Exception as e:
        if "vector" in str(e).lower() or "knn" in str(e).lower():
            # KNN 搜索失败时，回退到纯文本搜索
            body.pop("knn", None)
            logger.warning("[search_guidelines] KNN search failed, falling back to text search: %s", e)
            resp = await client.search(index=INDEX_NAME, **body)
        else:
            logger.warning("guidelines search failed: %s", e)
            return []

    hits = resp.get("hits", {}).get("hits", [])
    logger.info(f"[search_guidelines] ES returned {len(hits)} hits for query: {query[:50]}")
    seen: set = set()
    results: List[dict] = []
    for h in hits:
        src = h.get("_source", {})
        gid = src.get("id") or h.get("_id")
        if gid in seen:
            continue
        seen.add(gid)
        results.append({
            "id": src.get("id"),
            "title_cn": src.get("title_cn"),
            "toc": src.get("toc"),
        })

    return results


async def _resolve_sections_to_content(
    guideline: dict,
    section_specs: list,
    total_tokens_so_far: int,
) -> tuple[list, int]:
    """
    Given guideline with 'pages', and list of {section, page_range}, resolve content.
    Returns (list of {section, content}, total_tokens_so_far after adding).
    Content is truncated per section to SECTION_CONTENT_TRUNCATE_CHARS; skips section if would exceed PIPELINE_MAX_TOKENS.
    """
    pages = guideline.get("pages") or []
    out = []
    total = total_tokens_so_far
    for spec in section_specs:
        if total >= PIPELINE_MAX_TOKENS:
            break
        pr = spec.get("page_range") or ""
        section_title = spec.get("section") or ""
        try:
            if "-" in pr:
                parts = pr.split("-", 1)
                start_p, end_p = int(parts[0].strip()), int(parts[1].strip())
                content_pages = pages[start_p - 1 : end_p] if start_p <= len(pages) else []
            else:
                p = int(pr.strip())
                content_pages = [pages[p - 1]] if 1 <= p <= len(pages) else []
            if not content_pages:
                continue
            content_str = "\n".join(content_pages) if isinstance(content_pages[0], str) else "\n".join(str(x) for x in content_pages)
            if SECTION_CONTENT_TRUNCATE_CHARS > 0 and len(content_str) > SECTION_CONTENT_TRUNCATE_CHARS:
                content_str = content_str[:SECTION_CONTENT_TRUNCATE_CHARS] + "...[truncated]"
            tokens = _count_tokens(content_str)
            if total + tokens > PIPELINE_MAX_TOKENS:
                continue
            total += tokens
            out.append({"section": section_title, "content": content_str})
        except Exception as e:
            logger.debug("resolve section %s: %s", spec, e)
            continue
    return out, total


async def pipeline_guideline_search_with_content(query: str) -> list:
    """
    Full pipeline: search -> select top 3 ids -> fetch full docs -> select sections by query -> resolve content.
    Returns list of { "title_cn": str, "sections": [ {"section": str, "content": str} ] }.
    """
    logger.info(f"[ClinicalGuideline] Starting pipeline for query: {query[:100]}")

    candidates = await search_guidelines(query, size=10)
    if not candidates:
        logger.warning(f"[ClinicalGuideline] No candidates found from ES search for query: {query[:50]}")
        return []
    logger.info(f"[ClinicalGuideline] Found {len(candidates)} candidates from ES")

    from agent.iit.v3.guidelines.selection import (
        select_guideline_ids_by_query,
        select_sections_by_query_batch,
    )
    from agent.iit.v3.guidelines.es_guideline_fetch import fetch_guideline_by_ids

    guideline_titles = [{"id": g["id"], "title": g.get("title_cn") or ""} for g in candidates]
    ids = await select_guideline_ids_by_query(query, guideline_titles)
    if not ids:
        logger.warning(f"[ClinicalGuideline] LLM selection returned no IDs for query: {query[:50]}")
        return []
    logger.info(f"[ClinicalGuideline] LLM selected {len(ids)} guideline IDs: {ids}")

    full_docs = await fetch_guideline_by_ids(ids)
    if not full_docs:
        logger.warning(f"[ClinicalGuideline] Failed to fetch full docs for IDs: {ids}")
        return []
    logger.info(f"[ClinicalGuideline] Fetched {len(full_docs)} full documents")

    order_by_id = {str(g.get("id")): g for g in full_docs}
    ordered = [order_by_id[i] for i in ids if i in order_by_id]

    # One batch LLM call for section selection (top 3 guidelines)
    guidelines_to_process = ordered[:3]
    all_section_specs = await select_sections_by_query_batch(query, guidelines_to_process)

    # Resolve content sequentially (token budget is shared across guidelines)
    result = []
    total_tokens = 0
    for guideline, section_specs in zip(guidelines_to_process, all_section_specs):
        title = guideline.get("title_cn") or ""
        if isinstance(section_specs, Exception):
            logger.warning("select_sections_by_query failed for %s: %s", title, section_specs)
            result.append({"title_cn": title, "sections": []})
            continue
        if not section_specs:
            result.append({"title_cn": title, "sections": []})
            continue
        sections_with_content, total_tokens = await _resolve_sections_to_content(
            guideline, section_specs, total_tokens
        )
        result.append({
            "title_cn": title,
            "sections": sections_with_content,
        })
    return result
