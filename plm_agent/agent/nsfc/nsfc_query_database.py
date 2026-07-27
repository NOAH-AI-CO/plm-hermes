import logging
import re
from typing import Any, Dict, Optional, List
from collections import Counter

from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch
from utils.pubmed_opt.pubmed_search import PubMedSearch
from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.core.milvus_client import MilvusClientSingleton
from utils.scholar.citation_formatter_v2 import vancouver_format_list, bibtex_export, ris_export, csljson_export
from agent.journal_recommendation.journal_query_pubmed import _normalize_issn, search_journals


logger = logging.getLogger(__name__)
    
def vector_search_pubmed(inputs: list, search_years: list = [2024, 2025], top_k: int = 50) -> list:
    if not inputs:
        return []
    
    ElasticsearchClientSingleton.initialize()
    MilvusClientSingleton.initialize()
    
    searcher = PubMedVectorSearch()
    vector_records = searcher.search_years(inputs=inputs, years=search_years, size=top_k, force_load_partitions=True)
    
    pmid_list = []
    for hits in vector_records:   # results 是每个 query 的 hit 列表
        for h in hits:
            pmid = h.get("pmid")
            if pmid:
                pmid_list.append(str(pmid))
                    
    records = searcher.fetch(pmid_list, source_fields=None) if pmid_list else []
    return records

def vector_search_nsfc(user_input: str, top_k: int = 50) -> list:
    pass  # TODO: 实现 NSFC 的向量搜索


def _terms_query(field_name, terms, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass

    queries['bool'][query_type].append(
        {
            'terms': {
                '{}.keyword'.format(field_name): terms
            }
        }
    )
    return queries


# 学部学科
def code_query(codes, query_type='should'):
    queries = _terms_query(
        field_name='code',
        terms=codes,
        query_type=query_type
    )
    return queries


# 项目类型
def project_type_query(types, query_type='should'):
    queries = _terms_query(
        field_name='type',
        terms=types,
        query_type=query_type
    )
    return queries


# 关键词
def keyword_query(keywords, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass
    for keyword in keywords:
        queries['bool'][query_type].append(
            {
                'term': {
                    'keywordList.keyword': keyword
                }
            }
        )
    return queries


def _year_query(field_name, year, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass

    queries['bool'][query_type].append(
        {
            'range': {
                field_name: {
                    'gte': '{}-01-01'.format(year),
                    'lte': '{}-12-31'.format(year),
                    'format': 'yyyy-MM-dd'
                }
            }
        }
    )
    return queries


# 批准年份
def start_year_query(year, query_type='should'):
    queries = _year_query(
        field_name='researchTimeStart',
        year=year,
        query_type=query_type
    )
    return queries


# 结题年份
def end_year_query(year, query_type='should'):
    queries = _year_query(
        field_name='researchTimeEnd',
        year=year,
        query_type=query_type
    )
    return queries


def year_range_query(start_year: int=None,
                     end_year: int=None,
                     query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass

    if start_year:
        queries['bool'][query_type].append(
            {
                'range': {
                    'researchTimeStart': {
                        'gte': '{}-01-01'.format(start_year),
                        'format': 'yyyy-MM-dd'
                    }
                }
            }
        )
    else:
        pass
    if end_year:
        queries['bool'][query_type].append(
            {
                'range': {
                    'researchTimeEnd': {
                        'lte': '{}-12-31'.format(end_year),
                        'format': 'yyyy-MM-dd'
                    }
                }
            }
        )
    else:
        pass
    return queries


def _text_query(field_name, text, query_type='should'):
    queries = {'bool': {query_type: list()}}
    if 'should' in queries:
        queries['bool']['minimum_should_match'] = 1
    else:
        pass

    queries['bool'][query_type].append(
        {
            'match': {
                field_name: text
            }
        }
    )
    return queries

# 项目名称
def project_name_query(name, query_type='should'):
    queries = _text_query(
        field_name='projectName',
        text=name,
        query_type=query_type
    )
    return queries


# 摘要: 应该同时包含结论摘要
def abstract_query(text, query_type='should'):
    abstract_queries = _text_query(
        field_name='projectAbstractC',
        text=text,
        query_type=query_type
    )
    conclusion_queries = _text_query(
        field_name='conclusionAbstract',
        text=text,
        query_type=query_type
    )
    queries = abstract_queries
    queries['bool']['should'].extend(conclusion_queries['bool']['should'])

    return queries


def build_nsfc_query(keywords: List[str]) -> Dict[str, Any]:
    should_queries = []

    if not keywords:
        return {"match_all": {}}

    for idx, keyword in enumerate(keywords):
        if not keyword:
            continue

        if idx < 3:
            pos_boost = 5.0
        elif idx < 8:
            pos_boost = 1.5
        else:
            pos_boost = 1.0

        # 项目名称查询（字段本身 2.0，再乘位置系数）
        should_queries.append({
            "match": {
                "projectName": {
                    "query": keyword,
                    "boost": 2.0 * pos_boost
                }
            }
        })

        # 关键词 term 查询：term 也可以带 boost，需要用 value + boost 的结构
        should_queries.append({
            "term": {
                "keywordList.keyword": {
                    "value": keyword,
                    "boost": 1.0 * pos_boost
                }
            }
        })

        # 项目摘要
        should_queries.append({
            "match": {
                "projectAbstractC": {
                    "query": keyword,
                    "boost": 1.5 * pos_boost
                }
            }
        })

        # 结论摘要
        should_queries.append({
            "match": {
                "conclusionAbstract": {
                    "query": keyword,
                    "boost": 1.2 * pos_boost
                }
            }
        })

    return {
        "bool": {
            "should": should_queries,
            "minimum_should_match": 1
        }
    }

def build_nsfc_query_filters(start_year: Optional[int] = None,
                             end_year: Optional[int] = None,
                             project_types: Optional[List[str]] = None,
                             codes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    filters = []
    if start_year is not None:
        filters.append({
            "range": {
                "researchTimeStart": {
                    "gte": f"{start_year}-01-01",
                    "format": "yyyy-MM-dd"
                }
            }
        })

    # 结题年份上界（仅当提供 end_year 时添加）
    if end_year is not None:
        filters.append({
            "range": {
                "researchTimeEnd": {
                    "lte": f"{end_year}-12-31",
                    "format": "yyyy-MM-dd"
                }
            }
        })
    # 项目类型过滤
    if project_types:
        filters.append({"terms": {"type.keyword": project_types}})

    # 学部代码过滤
    if codes:
        filters.append({"terms": {"code.keyword": codes}})

    return filters


def keyword_search_nsfc(keywords: List[str],
                        start_year: Optional[int] = None,
                        end_year: Optional[int] = None,
                        project_types: Optional[List[str]] = None,
                        codes: Optional[List[str]] = None,
                        top_k: int = 50) -> list:
    """使用关键词搜索NSFC项目"""
    try:
        ElasticsearchClientSingleton.initialize()
        print("ElasticsearchClientSingleton initialized")
    except Exception as e:
        logger.error(f"Failed to initialize ElasticsearchClientSingleton: {e}")
        return []
    es_client = ElasticsearchClientSingleton.get_client()

    nsfc_index = 'nsfc_record'

    query = build_nsfc_query(keywords)
    filters = build_nsfc_query_filters(start_year, end_year, project_types, codes)

    if filters:
        query["bool"]["filter"] = filters

    body = {
        "query": query,
        "size": top_k,
        "track_total_hits": True
    }

    try:
        resp = es_client.search(index=nsfc_index, body=body)
    except Exception as e:
        logger.error(f"Elasticsearch search error: {e}")
        return []

    hits = resp.get("hits", {}).get("hits", [])
    records = []
    for h in hits:
        src = h.get("_source", {}) or {}
        src["_score"] = h.get("_score")
        src["_id"] = h.get("_id")
        records.append(src)
    return records

def rank_pubmed_records_with_if(records: List[Dict[str, Any]], max_papers: int = 20, score_key: str = "_score", alpha: float = 3.0, if_cap: float = 20.0,) -> List[Dict[str, Any]]:
    """
    根据期刊影响因子（JIF）对 PubMed 文章记录进行重新排序
    alpha 控制影响因子对最终排名的影响程度，alpha 越大，IF影响越显著
    if_cap 用于归一化影响因子, if_cap = 20 意味着大于。
    """
    if not records:
        return []

    issn_counter = Counter()

    def get_norm_issn(rec: Dict[str, Any]) -> Optional[str]:
        for key in ("issn", "e_issn", "eissn"):
            raw = rec.get(key)
            norm = _normalize_issn(raw)
            if norm:
                return norm
        return None

    for rec in records:
        norm = get_norm_issn(rec)
        if norm:
            issn_counter[norm] += 1

    issn2journal: Dict[str, Dict[str, Any]] = {}
    if issn_counter:
        jr = search_journals(issns=list(issn_counter.keys()), size=len(issn_counter))
        journals = jr.get("journals", []) or []
        for j in journals:
            norm = _normalize_issn(j.get("issn")) or _normalize_issn(j.get("e_issn"))
            if norm:
                j = dict(j)
                j["pmid_count"] = issn_counter.get(norm, 0)
                issn2journal[norm] = j

    enriched: List[Dict[str, Any]] = []

    for rec in records:
        norm = get_norm_issn(rec)
        journal_info = issn2journal.get(norm)

        # 取 IF
        jif_value = 0.0
        if journal_info is not None:
            jif_raw = journal_info.get("latest_impact_factor")
            if jif_raw is not None:
                try:
                    jif_value = float(jif_raw)
                except Exception:
                    logger.debug(f"invalid impact factor: {jif_raw!r}")
                    jif_value = 0.0

        # 相似度
        try:
            base_score = float(rec.get(score_key) or 0.0)
        except Exception:
            base_score = 0.0

        # IF 归一化 + 组合公式
        if if_cap <= 0:
            norm_if = 0.0
        else:
            norm_if = max(0.0, min(jif_value, if_cap)) / if_cap

        rank_score = base_score * (1.0 + alpha * norm_if)

        r2 = dict(rec)
        r2["journal_info"] = journal_info
        r2["jif_value"] = jif_value
        r2["rank_score"] = rank_score
        enriched.append(r2)

    def sort_key(x: Dict[str, Any]):
        return (
            float(x.get("rank_score") or 0.0),
        )

    enriched.sort(key=sort_key, reverse=True)
    #print(enriched)
    return enriched[:max_papers]

from typing import List, Dict, Any, Optional


def build_pubmed_query_from_keywords(core_keywords: Optional[List[str]] = None,
                                     keywords: Optional[List[str]] = None,
                                     use_boost_syntax: bool = True) -> str:
    core_keywords = core_keywords or []
    keywords = keywords or []

    if not core_keywords and not keywords:
        return ""

    core_query = ""
    extra_query = ""

    if core_keywords:
        if use_boost_syntax:
            core_or = " OR ".join(f'"{kw}"' for kw in core_keywords)
            core_query = f"({core_or})^3"
        else:
            repeated = []
            for kw in core_keywords:
                repeated.extend([kw] * 3)
            core_query = " ".join(repeated)

    if keywords:
        extra_query = " ".join(keywords)

    if core_query and extra_query:
        return f"{core_query} AND ({extra_query})"

    elif core_query:
        return core_query
    else:
        return extra_query


async def search_pubmed_by_keywords(core_keywords: Optional[List[str]] = None,
                                    keywords: Optional[List[str]] = None,
                                    years: Optional[List[int]] = None,
                                    size: int = 20,
                                    fusion_method: str = "rrf",
                                    bm25_weight: float = 0.3,
                                    vector_weight: float = 0.7,
                                    min_score_threshold: float = 0.0,
                                    use_boost_syntax: bool = True,
                                    pubmed_search: Optional[PubMedSearch] = None,
                                    **kwargs: Any,) -> List[Dict[str, Any]]:
    years = years or []

    if pubmed_search is None:
        pubmed_search = PubMedSearch()

    query = build_pubmed_query_from_keywords(
        core_keywords=core_keywords,
        keywords=keywords,
        use_boost_syntax=use_boost_syntax,
    )

    results = await pubmed_search.hybrid_search(
        query=query,
        input_type="query",
        years=years,
        size=size,
        fusion_method=fusion_method,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        min_score_threshold=min_score_threshold,
        **kwargs,
    )

    return results