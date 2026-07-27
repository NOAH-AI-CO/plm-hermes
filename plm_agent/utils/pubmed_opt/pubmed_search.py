# -*- coding: utf-8 -*-
import time
import asyncio
import logging

from typing import List, Dict, Any, Optional

from utils.pubmed_opt.pubmed_elastic_search import PubMedElasticSearch
from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch

logger = logging.getLogger(__name__)


class PubMedSearch:

    def __init__(self):
        self._es_search: Optional[PubMedElasticSearch] = None
        self._vector_search: Optional[PubMedVectorSearch] = None
    
    @property
    def es_search(self) -> PubMedElasticSearch:
        if self._es_search is None:
            self._es_search = PubMedElasticSearch()
        return self._es_search
    
    @property
    def vector_search(self) -> PubMedVectorSearch:
        if self._vector_search is None:
            self._vector_search = PubMedVectorSearch()
        return self._vector_search

    def _formatter(
        self,
        response: List[Dict],
    ) -> List[Dict]:
        r"""
        Convert local elasticsearch result to PubMed Entrex XML result.
        1. Merge uid, pmcid, pmc, pii, DOI into article_ids, i.e. { "idtype": "pubmed", "idtypen": 1, "value": "35612571" }
        2. Convert abstract to summary.
        3. Convert authors array, i.e. { "name": "Liang J", "authtype": "Author", "clusterid": ""}
        4. Other fields, fulljournalname, issn, essn, nlmuniqueid, 
        """
        def _safe_str(value: Any) -> str:
            """Return empty string when value is None; otherwise cast to str."""
            return '' if value is None else str(value)

        final_results = []
        for item in response:
            articleid_key = [('pmc_id', 'pmcid'), ('doi', 'DOI')]
            articleids = []
            for key in articleid_key:
                articleids.append({
                   "idtype": key[1],
                   "value": _safe_str(item.get(key[0]))
                })
            authors = [
                { "name": _safe_str(author) }
                for author in item.get('author', []) if author is not None
            ]

            final_results.append({
                'title': _safe_str(item.get('title')),
                'summary': _safe_str(item.get('abstract')),
                'uid': _safe_str(item.get('pmid')),
                'pmid': _safe_str(item.get('pmid')),
                'articleids': articleids,
                'authors': authors,
                'issn': _safe_str(item.get('issn')),
                'essn': _safe_str(item.get('essn')),
                'fulljournalname': _safe_str(item.get('journal')),
                'nlmuniqueid': _safe_str(item.get('nlmuniqueid')),
                'pubdate': _safe_str(item.get('pubmed_pub_date')),
                'journal_abbr': _safe_str(item.get('journal_abbr')),
                'year_of_publication': _safe_str(item.get('year_of_publication')),
                'volume': _safe_str(item.get('volume')),
                'issue': _safe_str(item.get('issue')),
                'pagination': _safe_str(item.get('pagination')),
            })

        # Sanitize invalid values recursively across the entire structure
        return final_results

    async def hybrid_search(
        self,
        query: str,
        input_type: str = "query", # query, article
        years: List[int] = [],
        size: int = 20,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        fusion_method: str = "rrf",  # "rrf" (Reciprocal Rank Fusion) or "weighted_score"
        rrf_k: int = 60,
        min_score_threshold: float = 0.0,
        **kwargs
    ) -> Dict:
        """
        混合搜索：结合BM25和向量搜索的结果

        :param query: 查询字符串
        :param article: 文章内容
        :param years: 年份过滤
        :param size: 返回结果数量
        :param bm25_weight: BM25结果权重 (当fusion_method="weighted_score"时使用)
        :param vector_weight: 向量搜索结果权重 (当fusion_method="weighted_score"时使用)
        :param fusion_method: 融合方法 ("rrf" 或 "weighted_score")
        :param rrf_k: RRF参数，用于调节排名融合的平滑程度
        :param min_score_threshold: 最小分数阈值
        :return: 混合搜索结果
        """

        start_time = time.time()

        search_size = min(size * 3, self.vector_search.recall_top_k)

        try:
            bm25_docs = await self.es_search.bm25_search(
                query=query,
                years=years,
                size=search_size,
            )
        except Exception as e:
            logger.warning(f"Fetch Elasticsearch result failed {e}")
            bm25_docs = []

        # 提取结果
        try:
            vector_results = self.vector_search.vector_search(
                queries=[query],
                years=years,
                input_type=input_type,
                size=search_size,
            )
            vector_docs = vector_results[0]
        except Exception as e:
            logger.warning(f"Fetch Milvus result failed {e}")
            vector_docs = []

        if not bm25_docs and not vector_docs:
            return []

        # 创建PMID到文档的映射
        all_docs: Dict[str, Dict[str, Any]] = {}

        # 收集BM25结果
        for i, doc in enumerate(bm25_docs):
            pmid = str(doc.get('pmid', ''))
            if pmid:
                doc_copy = dict(doc)
                doc_copy['bm25_rank'] = i + 1
                doc_copy['bm25_score'] = doc.get('_score', 0.0)
                doc_copy['from_bm25'] = True
                all_docs[pmid] = doc_copy

        # 收集向量搜索结果
        vector_result_pmids = [str(doc.get('pmid', '')) for doc in vector_docs if 'pmid' in doc]
        if vector_result_pmids:
            vector_pmid_results = await self.es_search.fetch(vector_result_pmids)
            vector_pmid2item: Dict[str, Any] = {p['pmid']: p for p in vector_pmid_results.get('results', []) if 'pmid' in p}
            for i, doc in enumerate(vector_docs):
                pmid = str(doc.get('pmid', ''))
                # 合并向量搜索结果中的元数据
                if pmid in vector_pmid2item:
                    for key, value in vector_pmid2item[pmid].items():
                        if key not in doc:
                            doc[key] = value
                if pmid:
                    if pmid in all_docs:
                        # 合并信息
                        all_docs[pmid]['vector_rank'] = i + 1
                        all_docs[pmid]['vector_score'] = doc.get('score', 0.0)
                        all_docs[pmid]['from_vector'] = True
                        # 保留向量搜索中可能有的额外字段
                        for key, value in doc.items():
                            if key not in all_docs[pmid]:
                                all_docs[pmid][key] = value
                    else:
                        # 新文档
                        doc_copy = dict(doc)
                        doc_copy['vector_rank'] = i + 1
                        doc_copy['vector_score'] = doc.get('score', 0.0)
                        doc_copy['from_vector'] = True
                        doc_copy['from_bm25'] = False
                        all_docs[pmid] = doc_copy

        # 为没有在某个搜索中出现的文档设置默认值
        for pmid, doc in all_docs.items():
            if 'bm25_rank' not in doc:
                doc['bm25_rank'] = len(bm25_docs) + 100  # 给一个较大的排名
                doc['bm25_score'] = 0.0
                doc['from_bm25'] = False

            if 'vector_rank' not in doc:
                doc['vector_rank'] = len(vector_docs) + 100  # 给一个较大的排名
                doc['vector_score'] = 0.0
                doc['from_vector'] = False

        # 根据融合方法计算最终分数
        docs_list = list(all_docs.values())

        if fusion_method == "rrf":
            # Reciprocal Rank Fusion
            for doc in docs_list:
                bm25_rrf = 1.0 / (rrf_k + doc['bm25_rank'])
                vector_rrf = 1.0 / (rrf_k + doc['vector_rank'])
                doc['hybrid_score'] = bm25_rrf + vector_rrf
                doc['fusion_method'] = 'rrf'

        elif fusion_method == "weighted_score":
            # 加权分数融合
            # 首先对分数进行归一化
            bm25_scores = [doc['bm25_score'] for doc in docs_list if doc['from_bm25']]
            vector_scores = [doc['vector_score'] for doc in docs_list if doc['from_vector']]

            # 计算分数范围用于归一化
            bm25_max = max(bm25_scores) if bm25_scores else 1.0
            bm25_min = min(bm25_scores) if bm25_scores else 0.0
            vector_max = max(vector_scores) if vector_scores else 1.0
            vector_min = min(vector_scores) if vector_scores else 0.0

            # 避免除零
            bm25_range = bm25_max - bm25_min if bm25_max > bm25_min else 1.0
            vector_range = vector_max - vector_min if vector_max > vector_min else 1.0

            for doc in docs_list:
                # 归一化分数到[0,1]
                norm_bm25 = (doc['bm25_score'] - bm25_min) / bm25_range if doc['from_bm25'] else 0.0
                norm_vector = (doc['vector_score'] - vector_min) / vector_range if doc['from_vector'] else 0.0

                doc['hybrid_score'] = bm25_weight * norm_bm25 + vector_weight * norm_vector
                doc['fusion_method'] = 'weighted_score'
                doc['norm_bm25_score'] = norm_bm25
                doc['norm_vector_score'] = norm_vector

        else:
            raise ValueError(f"不支持的融合方法: {fusion_method}")

        # 过滤低分结果
        if min_score_threshold > 0:
            docs_list = [doc for doc in docs_list if doc['hybrid_score'] >= min_score_threshold]

        # 按混合分数排序
        docs_list.sort(key=lambda x: x['hybrid_score'], reverse=True)

        # 添加混合搜索的排名
        for i, doc in enumerate(docs_list):
            doc['hybrid_rank'] = i + 1

        # 限制返回数量
        final_results = docs_list[:size]

        # 记录融合统计信息
        fusion_stats = {
            'fusion_method': fusion_method,
            'bm25_results_count': len(bm25_docs),
            'vector_results_count': len(vector_docs),
            'total_unique_docs': len(docs_list),
            'both_methods_count': len([d for d in docs_list if d['from_bm25'] and d['from_vector']]),
            'bm25_only_count': len([d for d in docs_list if d['from_bm25'] and not d['from_vector']]),
            'vector_only_count': len([d for d in docs_list if d['from_vector'] and not d['from_bm25']]),
        }

        if fusion_method == "weighted_score":
            fusion_stats.update({
                'bm25_weight': bm25_weight,
                'vector_weight': vector_weight,
            })
        elif fusion_method == "rrf":
            fusion_stats['rrf_k'] = rrf_k

        logger.info(f"hybrid search: {fusion_stats} cost time: {time.time() - start_time}")

        return self._formatter(final_results)


async def test_hybrid_search():


    pubmed_search = PubMedSearch()

    # result = await pubmed_search.hybrid_search("Vaccine hesitancy among parents and its influencing factors: a cross-sectional study in Guangzhou, China", year='2021')
    result = await pubmed_search.es_search.bm25_search_simple("Global Vaccine Policy Updates Incorporating RWE", year='2024', size=10)
    print(type(result[0][0]))
    if result:
        if result[0]:
            pubmed_result = result[0][0]
            print(pubmed_result.get("abstract"))
            print(pubmed_result.get("title"))
            print(pubmed_result.get("pmid"))

            print(pubmed_result.get("author"))

    # print(result)

async def test_pubmed_elastic_search():
    import csv
    import json
    thesis_name = "疫苗领域真实世界研究"
    INPUT_JSON = f"/Users/shey/workspace/CodeTest/temp/{thesis_name}.json"
    OUTPUT_JSON = f"/Users/shey/workspace/CodeTest/temp/{thesis_name}-search.json"
    csv_file = f"/Users/shey/workspace/CodeTest/temp/{thesis_name}-search.csv"

    fieldnames = ["index", "title", "pmid", "abstract", "journal", "authors_full"]

    pubmed_search = PubMedSearch()
    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        items = json.load(f)

    results = []
    for item in items:
        title = item.get("title", "").strip()
        year = item.get("year")
        query_result = await pubmed_search.es_search.bm25_search_simple(
            title,
            years=[int(year)] if year else [],
            size=1
        )
        first_hit = (query_result[0] or [{}])[0]
        results.append({
            "index": item.get("index"),
            "title": first_hit.get("title"),
            "pmid": first_hit.get("pmid"),
            "abstract": first_hit.get("abstract"),
            "journal": first_hit.get("journal"),
            "authors_full": first_hit.get("author"),
        })

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    with open(csv_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)

if __name__ == "__main__":
    asyncio.run(test_hybrid_search())

    # asyncio.run(test_pubmed_elastic_search())
