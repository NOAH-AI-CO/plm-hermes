from elasticsearch import Elasticsearch
import math

from agent.translation.glossary.embedding import get_embedding
from config import api_config

client = Elasticsearch(
    hosts=api_config.ES_HOST,
    basic_auth=(api_config.ES_USERNAME, api_config.ES_PASSWORD),
)

index_name = "glossary"


_RRF_K = 60  # standard RRF constant — larger values reduce the impact of high ranks
_MSEARCH_TEXTS_PER_REQUEST = 200  # larger payload to reduce request count while avoiding giant bodies
_CONTAINS_TERM_BOOST = 100.0  # large boost so explicit term containment wins over fuzzy BM25


def _rrf_score(rank: int) -> float:
    return 1.0 / (_RRF_K + rank)


def _to_output_dict(src: dict, score: float) -> dict:
    return {
        "en_term": src.get("en_term", ""),
        "cn_term": src.get("cn_term", ""),
        "category": src.get("category", ""),
        "source": src.get("source"),
        "score": score,
    }


def _bm25_query(text: str) -> dict:
    q = (text or "").strip()
    return {
        "dis_max": {
            "tie_breaker": 0.1,
            "queries": [
                # Schema note: en_term/cn_term are text fields (no .keyword subfields).
                # Use phrase + AND-match to prioritize exact/near-exact matches.
                {"match_phrase": {"en_term": {"query": q, "boost": 20.0}}},
                {"match_phrase": {"cn_term": {"query": q, "boost": 20.0}}},
                {"match": {"en_term": {"query": q, "operator": "and", "boost": 6.0}}},
                {"match": {"cn_term": {"query": q, "operator": "and", "boost": 6.0}}},
                # Fallback: standard BM25 full-text matching.
                {"match": {"en_term": {"query": q, "boost": 1.0}}},
                {"match": {"cn_term": {"query": q, "boost": 1.0}}},
            ],
        }
    }


def _keyword_hits_to_rows(hits: list[dict], top_k: int) -> list[tuple[str, dict, float]]:
    rows: list[tuple[str, dict, float]] = []
    selected_ids: set[str] = set()
    for hit in hits:
        if len(rows) >= top_k:
            break
        doc_id = hit["_id"]
        if doc_id in selected_ids:
            continue
        selected_ids.add(doc_id)
        rows.append((doc_id, hit["_source"], float(hit.get("_score", 0.0))))
    return rows


def _keyword_hits_to_rows_keep_exact(
    query_text: str,
    hits: list[dict],
    top_k: int,
) -> list[tuple[str, dict, float]]:
    """Keep all exact contains matches, then fill up with highest-score remaining hits."""
    exact_rows: list[tuple[str, dict, float]] = []
    non_exact_rows: list[tuple[str, dict, float]] = []
    selected_ids: set[str] = set()

    for hit in hits:
        doc_id = hit["_id"]
        if doc_id in selected_ids:
            continue

        src = hit.get("_source", {})
        is_exact = (
            _contains_exact_term(query_text, src.get("cn_term", "")) or
            _contains_exact_term(query_text, src.get("en_term", ""))
        )

        row = (doc_id, src, float(hit.get("_score", 0.0)))
        selected_ids.add(doc_id)
        if is_exact:
            exact_rows.append(row)
        else:
            non_exact_rows.append(row)

    remaining_slots = max(0, top_k - len(exact_rows))
    return exact_rows + non_exact_rows[:remaining_slots]


def _normalize_for_contains(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _contains_exact_term(query_text: str, term: str) -> bool:
    q = _normalize_for_contains(query_text)
    t = _normalize_for_contains(term)
    return bool(t) and t in q


def _boost_bm25_hits_by_contains(query_text: str, hits: list[dict]) -> list[dict]:
    boosted: list[dict] = []
    for hit in hits:
        src = hit.get("_source", {})
        en_term = src.get("en_term", "")
        cn_term = src.get("cn_term", "")
        contains_boost = 0.0
        if _contains_exact_term(query_text, cn_term):
            contains_boost += _CONTAINS_TERM_BOOST
        if _contains_exact_term(query_text, en_term):
            contains_boost += _CONTAINS_TERM_BOOST

        # Keep the original ES score for output, use contains boost for ranking.
        base_score = float(hit.get("_score", 0.0))
        if contains_boost > 0:
            hit = dict(hit)
            hit["_score"] = base_score + contains_boost
        boosted.append(hit)

    boosted.sort(key=lambda h: float(h.get("_score", 0.0)), reverse=True)
    return boosted


def _run_msearch(searches: list[dict]) -> dict:
    try:
        return client.msearch(searches=searches)
    except TypeError:
        # Compatibility fallback for older ES python clients.
        return client.msearch(body=searches)


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    size = max(1, chunk_size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def _finalize_with_exact_and_half_rest(
    sorted_ids: list[str],
    exact_ids: set[str],
    max_results: int,
) -> list[str]:
    """
    Return all exact-match docs, then only half of remaining highest-score docs.

    Example: max_results=12, exact=2 -> 2 + floor((12-2)/2)=5 -> 7 total.
    """
    if max_results <= 0:
        return []

    exact_sorted = [doc_id for doc_id in sorted_ids if doc_id in exact_ids]
    non_exact_sorted = [doc_id for doc_id in sorted_ids if doc_id not in exact_ids]

    remaining_capacity = max(0, max_results - len(exact_sorted))
    keep_non_exact = remaining_capacity // 3

    return exact_sorted + non_exact_sorted[:keep_non_exact]


def _hybrid_rows_from_hits(
    knn_en_hits: list[dict],
    knn_cn_hits: list[dict],
    bm25_hits: list[dict],
    top_k: int,
) -> list[tuple[str, dict, float]]:
    keyword_slots = math.ceil((2 * top_k) / 3)
    embedding_slots = top_k - keyword_slots

    emb_rrf_scores: dict[str, float] = {}
    emb_sources: dict[str, dict] = {}
    for hits in (knn_en_hits, knn_cn_hits):
        for rank, hit in enumerate(hits, start=1):
            doc_id = hit["_id"]
            emb_rrf_scores[doc_id] = emb_rrf_scores.get(doc_id, 0.0) + _rrf_score(rank)
            if doc_id not in emb_sources:
                emb_sources[doc_id] = hit["_source"]

    embedding_sorted_ids = sorted(emb_rrf_scores, key=lambda d: emb_rrf_scores[d], reverse=True)

    selected_ids: set[str] = set()
    rows: list[tuple[str, dict, float]] = []

    def _append_result(doc_id: str, src: dict, score: float) -> None:
        selected_ids.add(doc_id)
        rows.append((doc_id, src, score))

    for hit in bm25_hits:
        if len(rows) >= keyword_slots:
            break
        doc_id = hit["_id"]
        if doc_id in selected_ids:
            continue
        _append_result(doc_id, hit["_source"], float(hit.get("_score", 0.0)))

    embedding_added = 0
    for doc_id in embedding_sorted_ids:
        if embedding_added >= embedding_slots:
            break
        if doc_id in selected_ids:
            continue
        _append_result(doc_id, emb_sources[doc_id], emb_rrf_scores[doc_id])
        embedding_added += 1

    if len(rows) < top_k:
        for hit in bm25_hits:
            if len(rows) >= top_k:
                break
            doc_id = hit["_id"]
            if doc_id in selected_ids:
                continue
            _append_result(doc_id, hit["_source"], float(hit.get("_score", 0.0)))

    if len(rows) < top_k:
        for doc_id in embedding_sorted_ids:
            if len(rows) >= top_k:
                break
            if doc_id in selected_ids:
                continue
            _append_result(doc_id, emb_sources[doc_id], emb_rrf_scores[doc_id])

    return rows[:top_k]


def _search_glossary_with_doc_ids(
    text: str,
    top_k: int = 20,
    use_embedding: bool = True,
) -> list[tuple[str, dict, float]]:
    """
    Internal glossary search for one query text.

    Default is keyword-only (BM25). Set `use_embedding=True` for hybrid mode.

    Returns:
        List of tuples: (doc_id, source_dict, score)
    """
    if top_k <= 0:
        return []


    text = (text or "").strip()
    if not text:
        return []

    if not use_embedding or True:
        bm25_resp = client.search(
            index=index_name,
            size=top_k,
            query=_bm25_query(text),
        )
        bm25_hits = _boost_bm25_hits_by_contains(text, bm25_resp["hits"]["hits"])
        return _keyword_hits_to_rows(bm25_hits, top_k)

    keyword_slots = math.ceil((2 * top_k) / 3)
    embedding_slots = top_k - keyword_slots

    # Pull deeper candidate pools to make quota filling robust after dedup.
    keyword_size = max(top_k * 3, keyword_slots)
    embedding_size = max(top_k * 3, max(embedding_slots, 1))

    query_vector = get_embedding(text)

    knn_en_resp = client.search(
        index=index_name,
        size=embedding_size,
        knn={
            "field": "en_term_vector",
            "query_vector": query_vector,
            "k": embedding_size,
            "num_candidates": embedding_size * 3,
        },
    )

    knn_cn_resp = client.search(
        index=index_name,
        size=embedding_size,
        knn={
            "field": "cn_term_vector",
            "query_vector": query_vector,
            "k": embedding_size,
            "num_candidates": embedding_size * 3,
        },
    )

    bm25_resp = client.search(
        index=index_name,
        size=keyword_size,
        query=_bm25_query(text),
    )

    # --- Embedding lane: RRF reranking across EN/CN KNN ---
    emb_rrf_scores: dict[str, float] = {}
    emb_sources: dict[str, dict] = {}

    embedding_ranked_lists = [
        knn_en_resp["hits"]["hits"],
        knn_cn_resp["hits"]["hits"],
    ]
    for hits in embedding_ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            doc_id = hit["_id"]
            emb_rrf_scores[doc_id] = emb_rrf_scores.get(doc_id, 0.0) + _rrf_score(rank)
            if doc_id not in emb_sources:
                emb_sources[doc_id] = hit["_source"]

    embedding_sorted_ids = sorted(
        emb_rrf_scores,
        key=lambda d: emb_rrf_scores[d],
        reverse=True,
    )
    bm25_hits = _boost_bm25_hits_by_contains(text, bm25_resp["hits"]["hits"])

    # --- Quota merge: 2/3 keyword, 1/3 embedding ---
    selected_ids: set[str] = set()
    results: list[tuple[str, dict, float]] = []

    def _append_result(doc_id: str, src: dict, score: float) -> None:
        selected_ids.add(doc_id)
        results.append((doc_id, src, score))

    # Fill keyword slots first
    for hit in bm25_hits:
        if len(results) >= keyword_slots:
            break
        doc_id = hit["_id"]
        if doc_id in selected_ids:
            continue
        _append_result(doc_id, hit["_source"], float(hit.get("_score", 0.0)))

    # Fill embedding slots next
    embedding_added = 0
    for doc_id in embedding_sorted_ids:
        if embedding_added >= embedding_slots:
            break
        if doc_id in selected_ids:
            continue
        _append_result(doc_id, emb_sources[doc_id], emb_rrf_scores[doc_id])
        embedding_added += 1

    # Backfill any remaining slots (due to dedup/scarcity), prioritizing keyword then embedding.
    if len(results) < top_k:
        for hit in bm25_hits:
            if len(results) >= top_k:
                break
            doc_id = hit["_id"]
            if doc_id in selected_ids:
                continue
            _append_result(doc_id, hit["_source"], float(hit.get("_score", 0.0)))

    if len(results) < top_k:
        for doc_id in embedding_sorted_ids:
            if len(results) >= top_k:
                break
            if doc_id in selected_ids:
                continue
            _append_result(doc_id, emb_sources[doc_id], emb_rrf_scores[doc_id])

    return results[:top_k]


def search_glossary(
    text: str,
    top_k: int = 20,
    use_embedding: bool = True,
) -> list[dict]:
    """
    Search glossary for one text.

    Default is keyword-only (BM25). Set `use_embedding=True` for hybrid mode.
    """
    rows = _search_glossary_with_doc_ids(text, top_k=top_k, use_embedding=use_embedding)
    return [_to_output_dict(src, score) for _, src, score in rows]


def search_glossary_batch(
    texts: list[str],
    top_k: int = 20,
    per_text_top_k: int = 20,
    use_embedding: bool = True,
) -> list[dict]:
    """
    Batch glossary search for multiple indexed blocks, then aggregate.

    Each non-empty block text is searched independently and cross-block
    aggregation is done by RRF on per-block ranks.

    Default is keyword-only (BM25). Set `use_embedding=True` for hybrid mode.
    """
    if top_k <= 0:
        return []

    query_texts = [str(t).strip() for t in (texts or []) if str(t).strip()]
    if not query_texts:
        return []

    per_query_k = max(1, per_text_top_k)
    agg_scores: dict[str, float] = {}
    sources: dict[str, dict] = {}
    contains_matched_ids: set[str] = set()

    if not use_embedding or True:
        keyword_size = max(per_query_k * 3, top_k * 2)
        for chunk in _chunked(query_texts, _MSEARCH_TEXTS_PER_REQUEST):
            searches: list[dict] = []
            for text in chunk:
                searches.append({"index": index_name})
                searches.append({"size": keyword_size, "query": _bm25_query(text)})

            msearch_resp = _run_msearch(searches)
            for i, one_resp in enumerate(msearch_resp.get("responses", [])):
                query_text = chunk[i] if i < len(chunk) else ""
                hits = _boost_bm25_hits_by_contains(
                    query_text,
                    one_resp.get("hits", {}).get("hits", []),
                )
                rows = _keyword_hits_to_rows_keep_exact(query_text, hits, per_query_k)
                for rank, (doc_id, src, _score) in enumerate(rows, start=1):
                    agg_scores[doc_id] = agg_scores.get(doc_id, 0.0) + _rrf_score(rank)
                    if doc_id not in sources:
                        sources[doc_id] = src
                    if (_contains_exact_term(query_text, src.get("cn_term", "")) or
                            _contains_exact_term(query_text, src.get("en_term", ""))):
                        contains_matched_ids.add(doc_id)

        sorted_ids = sorted(agg_scores, key=lambda d: agg_scores[d], reverse=True)
        final_ids = _finalize_with_exact_and_half_rest(
            sorted_ids,
            contains_matched_ids,
            top_k,
        )
        return [_to_output_dict(sources[doc_id], agg_scores[doc_id]) for doc_id in final_ids]

    keyword_slots = math.ceil((2 * per_query_k) / 3)
    embedding_slots = per_query_k - keyword_slots
    keyword_size = max(per_query_k * 3, keyword_slots)
    embedding_size = max(per_query_k * 3, max(embedding_slots, 1))

    for chunk in _chunked(query_texts, _MSEARCH_TEXTS_PER_REQUEST):
        searches: list[dict] = []
        for text in chunk:
            query_vector = get_embedding(text)
            searches.append({"index": index_name})
            searches.append(
                {
                    "size": embedding_size,
                    "knn": {
                        "field": "en_term_vector",
                        "query_vector": query_vector,
                        "k": embedding_size,
                        "num_candidates": embedding_size * 3,
                    },
                }
            )
            searches.append({"index": index_name})
            searches.append(
                {
                    "size": embedding_size,
                    "knn": {
                        "field": "cn_term_vector",
                        "query_vector": query_vector,
                        "k": embedding_size,
                        "num_candidates": embedding_size * 3,
                    },
                }
            )
            searches.append({"index": index_name})
            searches.append({"size": keyword_size, "query": _bm25_query(text)})

        responses = _run_msearch(searches).get("responses", [])
        for i in range(0, len(responses), 3):
            knn_en_hits = responses[i].get("hits", {}).get("hits", []) if i < len(responses) else []
            knn_cn_hits = responses[i + 1].get("hits", {}).get("hits", []) if i + 1 < len(responses) else []
            query_idx = i // 3
            query_text = chunk[query_idx] if query_idx < len(chunk) else ""
            bm25_hits = _boost_bm25_hits_by_contains(
                query_text,
                responses[i + 2].get("hits", {}).get("hits", []) if i + 2 < len(responses) else [],
            )

            rows = _hybrid_rows_from_hits(knn_en_hits, knn_cn_hits, bm25_hits, per_query_k)
            for rank, (doc_id, src, _score) in enumerate(rows, start=1):
                agg_scores[doc_id] = agg_scores.get(doc_id, 0.0) + _rrf_score(rank)
                if doc_id not in sources:
                    sources[doc_id] = src
                if (_contains_exact_term(query_text, src.get("cn_term", "")) or
                        _contains_exact_term(query_text, src.get("en_term", ""))):
                    contains_matched_ids.add(doc_id)

    sorted_ids = sorted(agg_scores, key=lambda d: agg_scores[d], reverse=True)
    final_ids = _finalize_with_exact_and_half_rest(
        sorted_ids,
        contains_matched_ids,
        top_k,
    )
    return [_to_output_dict(sources[doc_id], agg_scores[doc_id]) for doc_id in final_ids]


if __name__ == "__main__":
    sample_text = (
        "The primary endpoint is overall survival (OS). "
        "Patients with non-small cell lung cancer (NSCLC) were randomized "
        "to receive investigational drug or placebo. "
        "Adverse events were graded per CTCAE criteria."
    )
    hits = search_glossary(sample_text, top_k=10)
    for entry in hits:
        print(f"[{entry['category']}] {entry['en_term']} / {entry['cn_term']}  (score: {entry['score']:.4f})")