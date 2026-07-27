"""Hybrid search (BM25 + KNN) for user knowledge base."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .embedding import get_embedding_async
from .kb_index import _get_async_client, KB_CHUNK_INDEX

logger = logging.getLogger(__name__)


@dataclass
class KBSearchResult:
    chunk_id: str
    doc_id: str
    filename: str
    text: str
    score: float
    bm25_score: float
    knn_score: float
    chunk_index: int
    highlight: str = ""


async def search_knowledge_base(
    query: str,
    top_k: int = 5,
    search_mode: str = "hybrid",
    min_score: float = 0.1,
    doc_ids: list[str] | None = None,
) -> list[KBSearchResult]:
    es = _get_async_client()
    if not await es.indices.exists(index=KB_CHUNK_INDEX):
        return []

    if search_mode == "keyword":
        bm25_hits = await _bm25_search(query, top_k=top_k * 2, doc_ids=doc_ids)
        return _build_results(bm25_hits, {}, min_score, top_k)

    query_vector = await get_embedding_async(query)

    if search_mode == "semantic":
        knn_hits = await _knn_search(query_vector, top_k=top_k * 2, doc_ids=doc_ids)
        return _build_results({}, knn_hits, min_score, top_k)

    bm25_hits, knn_hits = await asyncio.gather(
        _bm25_search(query, top_k=top_k * 2, doc_ids=doc_ids),
        _knn_search(query_vector, top_k=top_k * 2, doc_ids=doc_ids),
    )
    return _merge_results(bm25_hits, knn_hits, min_score, top_k)


async def _bm25_search(
    query: str,
    top_k: int = 20,
    doc_ids: list[str] | None = None,
) -> dict[str, dict]:
    es = _get_async_client()

    must = [{"multi_match": {
        "query": query,
        "fields": ["text"],
        "type": "best_fields",
    }}]
    body: dict = {
        "query": {"bool": {"must": must}},
        "highlight": {"fields": {"text": {"fragment_size": 200, "number_of_fragments": 1}}},
        "size": top_k,
    }
    if doc_ids:
        body["query"]["bool"]["filter"] = [{"terms": {"doc_id": doc_ids}}]

    try:
        resp = await es.search(index=KB_CHUNK_INDEX, body=body)
    except Exception as e:
        logger.warning("[kb_search] BM25 search failed: %s", e)
        return {}

    results: dict[str, dict] = {}
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        cid = src["chunk_id"]
        hl = ""
        if "highlight" in hit:
            hl = "...".join(hit["highlight"].get("text", []))
        results[cid] = {
            "chunk_id": cid,
            "doc_id": src.get("doc_id", ""),
            "filename": src.get("filename", ""),
            "text": src.get("text", ""),
            "chunk_index": src.get("chunk_index", 0),
            "score": hit["_score"],
            "highlight": hl,
        }
    return results


async def _knn_search(
    query_vector: list[float],
    top_k: int = 20,
    doc_ids: list[str] | None = None,
) -> dict[str, dict]:
    es = _get_async_client()

    knn: dict = {
        "field": "text_vector",
        "query_vector": query_vector,
        "k": top_k,
        "num_candidates": max(top_k * 3, 30),
    }
    if doc_ids:
        knn["filter"] = {"terms": {"doc_id": doc_ids}}

    try:
        resp = await es.search(index=KB_CHUNK_INDEX, knn=knn, size=top_k)
    except Exception as e:
        logger.warning("[kb_search] KNN search failed: %s", e)
        return {}

    results: dict[str, dict] = {}
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        cid = src["chunk_id"]
        results[cid] = {
            "chunk_id": cid,
            "doc_id": src.get("doc_id", ""),
            "filename": src.get("filename", ""),
            "text": src.get("text", ""),
            "chunk_index": src.get("chunk_index", 0),
            "score": hit["_score"],
            "highlight": "",
        }
    return results


def _normalize_scores(hits: dict[str, dict]) -> dict[str, float]:
    if not hits:
        return {}
    scores = [h["score"] for h in hits.values()]
    mn, mx = min(scores), max(scores)
    rng = mx - mn if mx > mn else 1.0
    return {cid: (h["score"] - mn) / rng for cid, h in hits.items()}


def _merge_results(
    bm25_hits: dict[str, dict],
    knn_hits: dict[str, dict],
    min_score: float,
    top_k: int,
    bm25_weight: float = 0.3,
    knn_weight: float = 0.7,
) -> list[KBSearchResult]:
    bm25_norm = _normalize_scores(bm25_hits)
    knn_norm = _normalize_scores(knn_hits)

    all_ids = set(bm25_hits) | set(knn_hits)
    scored: list[tuple[str, float, float, float]] = []
    for cid in all_ids:
        b = bm25_norm.get(cid, 0.0)
        k = knn_norm.get(cid, 0.0)
        combined = b * bm25_weight + k * knn_weight
        scored.append((cid, combined, b, k))

    scored.sort(key=lambda x: x[1], reverse=True)

    results: list[KBSearchResult] = []
    for cid, combined, b_score, k_score in scored[:top_k]:
        if combined < min_score:
            continue
        info = knn_hits.get(cid) or bm25_hits.get(cid, {})
        results.append(KBSearchResult(
            chunk_id=cid,
            doc_id=info.get("doc_id", ""),
            filename=info.get("filename", ""),
            text=info.get("text", ""),
            score=combined,
            bm25_score=bm25_hits.get(cid, {}).get("score", 0.0),
            knn_score=knn_hits.get(cid, {}).get("score", 0.0),
            chunk_index=info.get("chunk_index", 0),
            highlight=bm25_hits.get(cid, {}).get("highlight", ""),
        ))
    return results


def _build_results(
    bm25_hits: dict[str, dict],
    knn_hits: dict[str, dict],
    min_score: float,
    top_k: int,
) -> list[KBSearchResult]:
    source = bm25_hits or knn_hits
    if not source:
        return []

    norm = _normalize_scores(source)
    items = sorted(norm.items(), key=lambda x: x[1], reverse=True)

    results: list[KBSearchResult] = []
    for cid, score in items[:top_k]:
        if score < min_score:
            continue
        info = source[cid]
        is_bm25 = cid in bm25_hits
        results.append(KBSearchResult(
            chunk_id=cid,
            doc_id=info.get("doc_id", ""),
            filename=info.get("filename", ""),
            text=info.get("text", ""),
            score=score,
            bm25_score=info.get("score", 0.0) if is_bm25 else 0.0,
            knn_score=info.get("score", 0.0) if not is_bm25 else 0.0,
            chunk_index=info.get("chunk_index", 0),
            highlight=info.get("highlight", ""),
        ))
    return results
