import json
import logging
import time
from typing import List, Dict, Any, Optional
from collections import Counter

from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.pubmed_opt.pubmed_search import PubMedSearch
from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch

logger = logging.getLogger(__name__)


def _normalize_issn(s: str) -> Optional[str]:
    """Normalize ISSN format"""
    import re
    m = re.match(r"^\s*(\d{4})-?(\d{3}[\dxX])\s*$", s or "")
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2).upper()}"


async def abstract_search_pubmed_with_issn_filter(abstract: str,
                                                 journal_issns: List[str],
                                                 years: Optional[List[int]] = None,
                                                 size: int = 20,
                                                 fusion_method: str = "rrf",
                                                 bm25_weight: float = 0.4,
                                                 vector_weight: float = 0.6,
                                                 min_score_threshold: float = 0.0,
                                                 **kwargs: Any,) -> List[Dict[str, Any]]:
    """
    Search PubMed articles similar to the given abstract, but only in specified journals.
    ISSN filtering is applied at the search level, not after retrieval.

    :param abstract: The abstract text to search for similar articles
    :param journal_issns: List of ISSN strings to filter by (will be normalized)
    :param years: Optional year filter
    :param size: Number of results to return
    :param fusion_method: Fusion method for hybrid search
    :param bm25_weight: BM25 weight for fusion
    :param vector_weight: Vector weight for fusion
    :param min_score_threshold: Minimum score threshold
    :return: List of similar articles from the specified journals
    """
    years = years or []
    pubmed_search = PubMedSearch()

    # Determine input type
    input_type = "query" if len(abstract.strip()) < 100 else "article"

    # Normalize ISSNs for filtering
    normalized_issns = []
    for issn in journal_issns:
        normalized = _normalize_issn(issn)
        if normalized:
            normalized_issns.append(normalized)

    if not normalized_issns:
        logger.warning("No valid ISSNs provided for filtering")
        return []

    # Create a custom BM25 search with ISSN filtering
    search_size = min(size * 3, pubmed_search.vector_search.recall_top_k)

    # 1. BM25 search with ISSN filtering
    bm25_docs = await _bm25_search_with_issn_filter(
        query=abstract,
        issns=normalized_issns,
        years=years,
        size=search_size
    )

    # 2. Vector search (we'll filter ISSN later since vector search doesn't support ISSN filtering)
    try:
        vector_results = pubmed_search.vector_search.vector_search(
            queries=[abstract],
            years=years,
            input_type=input_type,
            size=search_size,
        )
        vector_docs = vector_results[0] if vector_results else []
        logger.info(f"Vector search returned {len(vector_docs)} documents")
    except Exception as e:
        logger.warning(f"Vector search failed: {e}")
        vector_docs = []

    if not bm25_docs and not vector_docs:
        return []

    # Create PMID to document mapping
    all_docs: Dict[str, Dict[str, Any]] = {}

    # Collect BM25 results
    for i, doc in enumerate(bm25_docs):
        pmid = str(doc.get('pmid', ''))
        if pmid:
            doc_copy = dict(doc)
            doc_copy['bm25_rank'] = i + 1
            doc_copy['bm25_score'] = doc.get('_score', 0.0)
            all_docs[pmid] = doc_copy

    # Collect vector results and merge
    for i, doc in enumerate(vector_docs):
        pmid = str(doc.get('pmid', ''))
        if pmid:
            if pmid in all_docs:
                # Merge with existing BM25 result
                existing = all_docs[pmid]
                existing['vector_rank'] = i + 1
                existing['vector_score'] = doc.get('score', 0.0)
                existing['embedding'] = doc.get('embedding', [])
            else:
                # New vector-only result - check ISSN match
                doc_issns = set()
                doc_issns.add(_normalize_issn(doc.get('issn', '')) or '')
                doc_issns.add(_normalize_issn(doc.get('e_issn', '')) or '')
                doc_issns = {i for i in doc_issns if i}

                if doc_issns & set(normalized_issns):  # ISSN match
                    doc_copy = dict(doc)
                    doc_copy['vector_rank'] = i + 1
                    doc_copy['vector_score'] = doc.get('score', 0.0)
                    doc_copy['embedding'] = doc.get('embedding', [])
                    all_docs[pmid] = doc_copy

    if not all_docs:
        return []

    # Score fusion
    if fusion_method == "rrf":
        # Reciprocal Rank Fusion
        rrf_k = kwargs.get('rrf_k', 60)
        for doc in all_docs.values():
            rrf_score = 0.0
            if 'bm25_rank' in doc:
                rrf_score += 1.0 / (rrf_k + doc['bm25_rank'])
            if 'vector_rank' in doc:
                rrf_score += 1.0 / (rrf_k + doc['vector_rank'])
            doc['rrf_score'] = rrf_score
            doc['hybrid_score'] = rrf_score  # For compatibility

    elif fusion_method == "weighted_score":
        # Weighted score fusion
        for doc in all_docs.values():
            bm25_score = doc.get('bm25_score', 0.0)
            vector_score = doc.get('vector_score', 0.0)
            hybrid_score = bm25_weight * bm25_score + vector_weight * vector_score
            doc['hybrid_score'] = hybrid_score
            doc['rrf_score'] = hybrid_score  # For compatibility
    else:
        logger.warning(f"Unknown fusion method: {fusion_method}, using RRF")
        for doc in all_docs.values():
            rrf_k = kwargs.get('rrf_k', 60)
            rrf_score = 0.0
            if 'bm25_rank' in doc:
                rrf_score += 1.0 / (rrf_k + doc['bm25_rank'])
            if 'vector_rank' in doc:
                rrf_score += 1.0 / (rrf_k + doc['vector_rank'])
            doc['rrf_score'] = rrf_score
            doc['hybrid_score'] = rrf_score

    # Filter by minimum score and sort
    filtered_docs = [
        doc for doc in all_docs.values()
        if doc.get('rrf_score', doc.get('hybrid_score', 0)) >= min_score_threshold
    ]

    # Sort by score (descending)
    filtered_docs.sort(
        key=lambda x: x.get('rrf_score', x.get('hybrid_score', 0)),
        reverse=True
    )

    return filtered_docs[:size]


async def _bm25_search_with_issn_filter(query: str, issns: List[str], years: List[int] = [], size: int = 20):
    """
    Perform BM25 search with ISSN filtering applied at query level.
    """
    start_time = time.time()

    # Construct BM25 query body with ISSN filtering
    query_body = {
        "query": {
            "bool": {
                "must": [],
                "filter": []
            }
        },
        "size": size,
        "sort": [
            "_score",
            {"pubmed_pub_date": {"order": "desc"}}
        ],
        "timeout": "10s",
    }

    # Add text query on title and abstract
    if query and query.strip():
        query_body["query"]["bool"]["must"].append({
            "match": {"title_abstract_bm25": query}
        })

    # Add ISSN filter
    if issns:
        issn_filter = {
            "bool": {
                "should": [
                    {"terms": {"issn": issns}},
                    {"terms": {"e_issn": issns}},
                ],
                "minimum_should_match": 1
            }
        }
        query_body["query"]["bool"]["filter"].append(issn_filter)

    # Add year filter
    if years:
        year_strings = [str(year) for year in years]
        if len(year_strings) == 1:
            year_filter = {"term": {"year_of_publication": year_strings[0]}}
        else:
            year_filter = {"terms": {"year_of_publication": year_strings}}
        query_body["query"]["bool"]["filter"].append(year_filter)

    try:
        es_client = ElasticsearchClientSingleton.get_client()
        result = es_client.search(index="pubmed_simplified", body=query_body)
        total_count = result['hits']['total']['value']

        # Format results
        datalist = []
        for hit in result['hits']['hits']:
            doc = hit['_source']
            doc['_score'] = hit['_score']  # keep bm25 score
            datalist.append(doc)

        logger.info(f"BM25 search with ISSN filter completed in {time.time() - start_time:.2f} seconds, found {len(datalist)} results from {total_count} total hits")

        # Debug: show some ISSN info
        if datalist:
            sample_issns = [(doc.get('issn'), doc.get('e_issn')) for doc in datalist[:3]]
            logger.info(f"Sample ISSNs from BM25 results: {sample_issns}")

        return datalist

    except Exception as e:
        logger.error(f"Elasticsearch query with ISSN filter failed: {e}")
        return []