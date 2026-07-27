import json
import logging
import requests
import re

from elasticsearch import Elasticsearch
from config import settings
from typing import Dict, Any, List, Optional, Union
from collections import Counter

from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.pubmed_opt.pubmed_search import PubMedSearch
from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch

ALLOWED_FIELDS = {
    "issn", "e_issn",
    "journal_title", "publisher", "publisher_region", "open_access_status",
    "latest_impact_factor", "latest_citescore",
    "latest_citable_items", "latest_china_authorship", "latest_document_types",
    "jif_quartile", "self_citation_rate",
    "zky_quartile_major", "zky_quartile_minor",
    "risk_info",
    "journal_description", "wos_research_areas", "citation_topics_meso",
    "publisher_scopes", "publisher_article_types",
    "review_speed_weeks",  # 审稿周期（周）
}
logger = logging.getLogger(__name__)

def _parse_issn_value(issn_value: str) -> List[str]:
    """
    解析可能包含多个 ISSN 的字符串（分号/逗号/空格分隔）
    :param issn_value: ISSN 字符串，可能包含多个值
    :return: 规范化的 ISSN 列表
    """
    if not issn_value:
        return []
    
    # 使用多种分隔符拆分：分号、逗号、空格
    parts = re.split(r'[;,\s]+', str(issn_value))
    normalized = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 规范化 ISSN 格式
        m = re.match(r"^\s*(\d{4})-?(\d{3}[\dxX])\s*$", part)
        if m:
            issn_normalized = f"{m.group(1)}-{m.group(2).upper()}"
            normalized.append(issn_normalized)
    
    return normalized


def fetch_issns_from_es(pmids: List[int], batch_size: int = 500, return_mapping: bool = False):
    """
    直接从 Elasticsearch PubMed 索引中获取 ISSN（支持多个 ISSN 字段和分隔值）
    :param pmids: List of PMIDs
    :param batch_size: 每批查询的数量
    :param return_mapping: 如果为True，返回Dict[str, List[str]]（PMID->ISSN列表映射）；否则返回List[str]（ISSN列表）
    :return: List of ISSN or Dict of PMID->ISSN list mapping
    """
    if not pmids:
        return {} if return_mapping else []
    
    es_client = ElasticsearchClientSingleton.get_client()
    issns = []
    pmid_to_issns = {}

    for i in range(0, len(pmids), batch_size):
        batch_pmids = pmids[i:i+batch_size]
        logger.info(f"Fetching ISSNs from ES for batch {i//batch_size + 1}/{(len(pmids)-1)//batch_size + 1} ({len(batch_pmids)} PMIDs)")
        
        try:
            # 尝试两种索引：先尝试 pubmed_simplified，再尝试 pubmed
            for index_name in ["pubmed_simplified", "pubmed"]:
                # 将 pmid 转为字符串，因为 ES 中可能存储为字符串
                pmid_strings = [str(p) for p in batch_pmids]
                
                query = {
                    "query": {
                        "terms": {
                            "pmid": pmid_strings
                        }
                    },
                    "_source": ["issn", "electronic_issn", "e_issn", "pmid", "journal"],  # 包含所有可能的 ISSN 字段
                    "size": batch_size
                }
                
                response = es_client.search(index=index_name, body=query)
                hits = response.get("hits", {}).get("hits", [])
                
                if hits:
                    logger.info(f"ES returned {len(hits)} documents from index '{index_name}' for {len(batch_pmids)} PMIDs")
                    
                    for hit in hits:
                        source = hit.get("_source", {})
                        pmid = str(source.get("pmid", ""))
                        
                        # 从多个可能的字段中提取 ISSN
                        issn_fields = []
                        for field_name in ["issn", "electronic_issn", "e_issn"]:
                            if field_name in source:
                                issn_fields.append(source[field_name])
                        
                        # 调试：输出前3个文档的结构
                        if len(issns) < 3:
                            logger.info(f"Sample document from {index_name}: pmid={pmid}, issn_fields={issn_fields}, source_keys={list(source.keys())}")
                        
                        # 解析所有 ISSN 字段（可能包含多个值）
                        article_issns = []
                        for issn_value in issn_fields:
                            parsed = _parse_issn_value(issn_value)
                            article_issns.extend(parsed)
                        
                        # 去重
                        article_issns = list(dict.fromkeys(article_issns))  # 保持顺序的去重
                        
                        if article_issns:
                            issns.extend(article_issns)
                            if return_mapping and pmid:
                                pmid_to_issns[pmid] = article_issns
                        else:
                            # 如果没有提取到任何 ISSN，记录一下
                            if len(issns) < 3:
                                logger.debug(f"No ISSN extracted from document: {source}")
                    
                    break  # 成功获取数据，退出索引尝试循环
                else:
                    logger.warning(f"No documents found in index '{index_name}' for {len(batch_pmids)} PMIDs")
                    
        except Exception as e:
            logger.error(f"Error fetching ISSNs from ES for batch {i//batch_size + 1}: {str(e)}")
            continue
    
    if return_mapping:
        total_issn_count = sum(len(v) for v in pmid_to_issns.values())
        logger.info(f"Extracted {len(pmid_to_issns)} PMID->ISSN mappings with {total_issn_count} total ISSNs from {len(pmids)} PMIDs")
        return pmid_to_issns
    else:
        unique_issns = list(set([i for i in issns if i]))
        logger.info(f"Extracted {len(unique_issns)} unique ISSNs from {len(pmids)} PMIDs")
        return unique_issns

def _normalize_issn(s: str) -> Optional[str]:
    import re
    m = re.match(r"^\s*(\d{4})-?(\d{3}[\dxX])\s*$", s or "")
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2).upper()}"

def query_journal_id(spec: Optional[Union[str, List[str]]]):
    if not spec:
        return None
    if isinstance(spec, list):
        vals = [s for s in spec if s]
        return {"terms": {"journal_id": vals}} if vals else None
    return {"term": {"journal_id": spec}}

def query_impact_factor(spec):
    if not spec:
        return None
    rng = {}
    if "min" in spec and spec["min"] is not None:
        rng["gte"] = float(spec["min"])
    if "max" in spec and spec["max"] is not None:
        rng["lte"] = float(spec["max"])
    return {"range": {"latest_impact_factor": rng}} if rng else None

def query_citescore(spec):
    if not spec:
        return None
    rng = {}
    if "min" in spec and spec["min"] is not None:
        rng["gte"] = float(spec["min"])
    if "max" in spec and spec["max"] is not None:
        rng["lte"] = float(spec["max"])
    return {"range": {"latest_citescore": rng}} if rng else None

def query_self_citation_rate(spec):
    if not spec:
        return None
    rng = {}
    if "min" in spec and spec["min"] is not None:
        rng["gte"] = float(spec["min"])
    if "max" in spec and spec["max"] is not None:
        rng["lte"] = float(spec["max"])
    return {"range": {"self_citation_rate": rng}} if rng else None

def query_jif_quartile(spec):
    if spec in (None, "", [], {}):
        return None

    vals = spec if isinstance(spec, list) else [spec]

    normed = []
    for v in vals:
        if v is None:
            continue
        s = str(v).strip().lower()
        if s.startswith("q"):
            s = s  
            if s not in {"q1","q2","q3","q4"}:
                continue
        else:
            if s in {"1","2","3","4"}:
                s = "q" + s
            else:
                continue
        normed.append(s)

    if not normed:
        return None

    normed = list(dict.fromkeys(normed))
    return {"terms": {"jif_quartile": normed}}

def query_zky_major_quartile(spec) -> Optional[Dict[str, Any]]:
    if not spec:
        return None
    if isinstance(spec, list):
        return {"terms": {"zky_quartile.major.quartile": [int(x) for x in spec]}}
    else:
        return {"term": {"zky_quartile.major.quartile": int(spec)}}
    
def query_zky_minor_quartile(spec) -> Optional[Dict[str, Any]]:
    if not spec:
        return None
    if isinstance(spec, list):
        return {"terms": {"zky_quartile.minor.quartile": [int(x) for x in spec]}}
    else:
        return {"term": {"zky_quartile.minor.quartile": int(spec)}}

def query_indexing(spec):
    if not spec:
        return None

    vals = spec if isinstance(spec, list) else [spec]

    normed = [str(v).lower() for v in vals if v]

    return {"terms": {"indexing_databases": normed}}

def query_issns(issns):
    norm = []
    seen = set()
    for raw in issns or []:
        n = _normalize_issn(raw)
        if n and n not in seen:
            seen.add(n)
            norm.append(n)

    if not norm:
        return None

    return {
        "bool": {
            "should": [
                {"terms": {"issn": norm}},
                {"terms": {"e_issn": norm}},
            ],
            "minimum_should_match": 1
        }
    }

def _add_filter(qb: Dict[str, Any], clause: Optional[Dict[str, Any]]) -> None:
    if clause:
        qb.setdefault("bool", {}).setdefault("filter", []).append(clause)

def make_query_body(issn: Optional[Union[str, List[str]]] = None,
                    issns: Optional[List[str]] = None,
                    journal_id: Optional[Union[str, List[str]]] = None,
                    impact_factor: Optional[Dict[str, Any]] = None,
                    citescore: Optional[Dict[str, Any]] = None,
                    self_citation_rate: Optional[Dict[str, Any]] = None,
                    jif_quartile: Optional[Union[str, int, List[Union[str, int]]]] = None,
                    zky_major_quartile: Optional[Union[int, List[int]]] = None,
                    zky_minor_quartile: Optional[Union[int, List[int]]] = None,
                    indexing_databases: Optional[Union[str, List[str]]] = None,
                    size: int = 100) -> Dict[str, Any]:
    bool_q: Dict[str, Any] = {}
    
    issn_list: List[str] = issns or ([] if issn is None else (issn if isinstance(issn, list) else [issn]))
    if issn_list:
        _add_filter(bool_q, query_issns(issn_list))

    _add_filter(bool_q, query_journal_id(journal_id))

    _add_filter(bool_q, query_impact_factor(impact_factor))
    _add_filter(bool_q, query_citescore(citescore))
    _add_filter(bool_q, query_self_citation_rate(self_citation_rate))

    _add_filter(bool_q, query_jif_quartile(jif_quartile))
    _add_filter(bool_q, query_zky_major_quartile(zky_major_quartile))
    _add_filter(bool_q, query_zky_minor_quartile(zky_minor_quartile))
    _add_filter(bool_q, query_indexing(indexing_databases))
    
    query = bool_q if bool_q else {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "size": max(int(size), 1),
    }
    return body


def execute_search(index,
                   search_body,
                   return_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    es_client = ElasticsearchClientSingleton.get_client()
    try:
        search_result = es_client.search(
            index=index,
            body=search_body,
            _source=return_fields
        )
    except Exception as e:
        logger.warning(e, 'failed retrying')
        es_client = ElasticsearchClientSingleton.get_client()
        search_result = es_client.search(
            index=index,
            body=search_body,
            _source=return_fields
        )
    return search_result


def search_journals_by_keywords(keywords: List[str],
                                impact_factor: Optional[Dict[str, Any]] = None,
                                citescore: Optional[Dict[str, Any]] = None,
                                jif_quartile: Optional[Union[str, int, List[Union[str, int]]]] = None,
                                zky_major_quartile: Optional[Union[int, List[int]]] = None,
                                zky_minor_quartile: Optional[Union[int, List[int]]] = None,
                                size: int = 100) -> Dict[str, Any]:
    if not keywords:
        return {"total": 0, "journals": []}
    
    # 构建关键词查询（搜索多个字段）
    should_queries = []
    for keyword in keywords[:10]:  # 限制最多10个关键词
        should_queries.extend([
            {"match": {"journal_description": {"query": keyword, "boost": 2}}},
            {"match": {"wos_research_areas": {"query": keyword, "boost": 3}}},
            {"match": {"citation_topics_meso": {"query": keyword, "boost": 2}}},
            {"match": {"journal_title": {"query": keyword, "boost": 1.5}}},
        ])
    
    bool_q = {
        "bool": {
            "should": should_queries,
            "minimum_should_match": 1
        }
    }
    
    # 添加筛选条件
    filters = []
    if impact_factor:
        clause = query_impact_factor(impact_factor)
        if clause:
            filters.append(clause)
    
    if citescore:
        clause = query_citescore(citescore)
        if clause:
            filters.append(clause)
    
    if jif_quartile:
        clause = query_jif_quartile(jif_quartile)
        if clause:
            filters.append(clause)
    
    if zky_major_quartile:
        clause = query_zky_major_quartile(zky_major_quartile)
        if clause:
            filters.append(clause)
    
    if zky_minor_quartile:
        clause = query_zky_minor_quartile(zky_minor_quartile)
        if clause:
            filters.append(clause)
    
    if filters:
        bool_q["bool"]["filter"] = filters
    
    search_body = {
        "query": bool_q,
        "size": size,
    }
    
    return_fields = list(ALLOWED_FIELDS)
    search_result = execute_search(index="journal_record", search_body=search_body, return_fields=return_fields)
    
    hits = search_result['hits']['hits']
    total = search_result.get("hits", {}).get("total", {}).get("value", 0)
    
    journals = []
    for h in hits:
        src = (h.get("_source") or {}).copy()
        src["keyword_match_score"] = h.get("_score", 0)  # 保存关键词匹配得分
        src["pmid_count"] = 0  # 关键词搜索的期刊初始PMID数为0
        journals.append(src)
    
    return {"total": total, "journals": journals}


def search_journals(issn: Optional[Union[str, List[str]]] = None,
                    issns: Optional[List[str]] = None,
                    journal_id: Optional[Union[str, List[str]]] = None,
                    impact_factor: Optional[Dict[str, Any]] = None,
                    citescore: Optional[Dict[str, Any]] = None,
                    self_citation_rate: Optional[Dict[str, Any]] = None,
                    jif_quartile: Optional[Union[str, int, List[Union[str, int]]]] = None,
                    zky_major_quartile: Optional[Union[int, List[int]]] = None,
                    zky_minor_quartile: Optional[Union[int, List[int]]] = None,
                    indexing_databases: Optional[Union[str, List[str]]] = None,
                    size: int = 100) -> Dict[str, Any]:
    inp = []
    if issns:
        inp.extend(issns)
    if issn:
        inp.extend(issn if isinstance(issn, list) else [issn])

    norm = [_normalize_issn(x) for x in (inp or []) if _normalize_issn(x)]
    cnt_map = dict(Counter(norm))  # {"1234-5678": 12, ...}

    if not cnt_map:
        return {"total": 0, "ids_have": [], "journals": []}
    
    search_body = make_query_body(issns=list(cnt_map.keys()),
                                  journal_id=journal_id,
                                  impact_factor=impact_factor,
                                  citescore=citescore,
                                  self_citation_rate=self_citation_rate,
                                  jif_quartile=jif_quartile,
                                  zky_major_quartile=zky_major_quartile,
                                  zky_minor_quartile=zky_minor_quartile,
                                  indexing_databases=indexing_databases,
                                  size=size)
    
    return_fields = list(ALLOWED_FIELDS)
    
    search_result = execute_search(index="journal_record", search_body=search_body, return_fields=return_fields)
    
    hits = search_result['hits']['hits']
    ids_have = [a['_id'] for a in hits]
    total = search_result.get("hits", {}).get("total", {}).get("value", 0)
    
    journals: List[Dict[str, Any]] = []
    for h in hits:
        src = (h.get("_source") or {}).copy()
        hit_norm = _normalize_issn(src.get("issn")) or _normalize_issn(src.get("e_issn"))
        src["pmid_count"] = cnt_map.get(hit_norm, 0)
        journals.append(src)

    return {"total": total, "ids_have": ids_have, "journals": journals}


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


async def keywords_search_pubmed(core_keywords: Optional[List[str]] = None,
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

async def abstract_search_pubmed(abstract: str, 
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
    
    input_type = determine_abstract_type(abstract)
    
    results = await pubmed_search.hybrid_search(
        query=abstract,
        input_type=input_type,
        years=years,
        size=size,
        fusion_method=fusion_method,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        min_score_threshold=min_score_threshold,
        **kwargs,
    )
    return results
    
def determine_abstract_type(abstract: str) -> str:
    return "query" if len(abstract.strip()) < 100 else "article"

