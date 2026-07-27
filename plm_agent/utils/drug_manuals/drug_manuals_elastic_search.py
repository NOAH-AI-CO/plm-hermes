import re
import time
import asyncio
import logging
from typing import List, Dict, Any, Optional

from utils.core.elasticsearch_client import ElasticsearchClientSingleton

logger = logging.getLogger(__name__)

class DrugManualsElasticSearch:

    es_index: str = "drug_manuals"

    def __init__(self):
        self.es_client = ElasticsearchClientSingleton.get_asyncclient()

    async def fetch(
        self,
        drug_ids: List[int],
        source_fields: Optional[List[str]] = ['drug_id', 'common_name', 'show_name', 'company_name'],
    ) -> Dict[str, Any]:
        """
        从Elasticsearch中批量获取药品信息（通过 drug_id）。
        """
        mget_params = {
            'index': self.es_index,
            'ids': [str(id) for id in drug_ids]
        }
        
        if source_fields is not None:
            mget_params['_source'] = source_fields
        
        result = await self.es_client.mget(**mget_params)
        doc_list = [doc['_source'] for doc in result['docs'] if doc['found']]
        return {'results': doc_list, 'total_count': len(doc_list)}
    
    def _split_drug_query(self, raw_query: str) -> List[str]:
        if not raw_query:
            return []
        for sep in [',', '，', ';', '；', '\n', '|']:
            raw_query = raw_query.replace(sep, ',')
        parts = [p.strip() for p in raw_query.split(',') if p.strip()]
        seen = set()
        unique = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique

    async def search_by_drugnames(
        self,
        raw_query: str,
        size: int = 1
    ) -> (List[Dict[str, Any]], int, str):
        """
        两阶段查询：
        1. 精确搜索：尝试高精度的 Tier 匹配，只取 Top 1。
        2. 兜底搜索：对未命中的药品，使用宽泛匹配，取 Top 1。

        返回格式固定为三元组 (results, count, raw_query)：
        - results: List[Dict]，长度等于解析出的药品名个数，顺序与查询名一致
        - count: int，等于 len(results)
        - raw_query: str，原始查询字符串

        每个 result 元素为字典，结构由 match_type 决定：

        - match_type == "strict"（精确命中）:
          必有: drug_id, common_name, show_name, company_name, text, _score, matched_drug, match_type
          无: candidates

        - match_type == "fallback"（兜底命中）:
          必有: 同上，且多一个 candidates: List[Dict]（命中列表，每项含 _source + _score）

        - match_type == "none"（未命中或空名）:
          必有: drug_id(None), matched_drug, match_type
          若有兜底阶段则还有: common_name(None), show_name(None), candidates([])
          空名时可能无 common_name/show_name/candidates
        """
        start = time.time()

        names = self._split_drug_query(raw_query)
        if not names:
            return [], 0, raw_query

        # 初始化结果列表，用 None 占位，保证顺序与 names 一致
        # 结构: [ResultDict, ResultDict, ...]
        final_results = [None] * len(names)

        # -------------------------------------------------------
        # Phase 1: 精确搜索 (Strict Search)
        # -------------------------------------------------------
        msearch_body_strict = []
        valid_indices_strict = [] # 记录 names 中参与 strict 搜索的索引

        for i, name in enumerate(names):
            clean_name = name.strip()
            if not clean_name:
                # 已经是 None，后续会被处理为空结果
                continue
            
            valid_indices_strict.append(i)
            use_wildcard = len(clean_name) > 1

            # 构建原有的高精度 Query
            msearch_body_strict.append({"index": self.es_index})
            q_body = {
                "_source": ["drug_id", "common_name", "show_name", "company_name", "text"],
                "query": {
                    "bool": {
                        "should": [
                            # Tier 1: 绝对精确匹配
                            {
                                "term": {
                                    "common_name.keyword": {
                                        "value": clean_name,
                                        "boost": 1000.0
                                    }
                                }
                            },
                            {
                                "term": {
                                    "show_name.keyword": {
                                        "value": clean_name,
                                        "boost": 1000.0
                                    }
                                }
                            },
                            # Tier 2: 短语前缀匹配
                            {
                                "multi_match": {
                                    "query": clean_name,
                                    "fields": ["common_name^5", "show_name^5"],
                                    "type": "phrase_prefix", 
                                    "boost": 100.0
                                }
                            },
                            # Tier 3: 包含匹配 (Wildcard)
                            *(
                                [
                                    {
                                        "wildcard": {
                                            "common_name": {
                                                "value": f"*{clean_name}*",
                                                "boost": 10.0
                                            }
                                        }
                                    },
                                    {
                                        "wildcard": {
                                            "show_name": {
                                                "value": f"*{clean_name}*",
                                                "case_insensitive": True,
                                                "boost": 10.0
                                            }
                                        }
                                    }
                                ] if use_wildcard else []
                            )
                        ],
                        "minimum_should_match": 1
                    }
                },
                "size": size
            }
            msearch_body_strict.append(q_body)

        # 执行第一轮搜索
        try:
            if msearch_body_strict:
                resp_strict = await self.es_client.msearch(body=msearch_body_strict)
                responses_strict = resp_strict.get("responses", [])
            else:
                responses_strict = []
        except Exception:
            logger.exception("Strict msearch failed: %s", names)
            return [], 0, raw_query

        # 处理第一轮结果，找出未命中的索引
        missing_indices = [] # 需要进行兜底搜索的 names 索引

        for idx_in_resp, original_idx in enumerate(valid_indices_strict):
            resp = responses_strict[idx_in_resp]
            hits = resp.get("hits", {}).get("hits", [])
            
            if hits:
                # 命中！填入结果
                hit = hits[0]
                doc = dict(hit["_source"])  # 创建副本，避免修改原始数据
                doc["_score"] = hit.get("_score", 0)
                doc["matched_drug"] = names[original_idx]
                doc["match_type"] = "strict"  # 标记为精确匹配
                final_results[original_idx] = doc
            else:
                # 未命中，加入待重试列表
                missing_indices.append(original_idx)

        # -------------------------------------------------------
        # Phase 2: 兜底搜索 (Fallback Search)
        # -------------------------------------------------------
        if missing_indices:
            msearch_body_fallback = []
            fallback_size = 1

            for i in missing_indices:
                name = names[i]
                clean_name = name.strip()
                
                msearch_body_fallback.append({"index": self.es_index})
                
                # 模糊搜索
                q_body_fallback = {
                    "_source": [
                        "drug_id", "common_name", "show_name", "company_name", "text",
                    ],
                    "query": {
                        "bool": {
                            "should": [
                                {
                                    "multi_match": {
                                        "query": clean_name,
                                        "fields": ["common_name^2", "show_name^2"],
                                        "type": "best_fields"
                                    }
                                },
                                {
                                    "multi_match": {
                                        "query": clean_name,
                                        "fields": ["common_name", "show_name"],
                                        "type": "phrase"
                                    }
                                },
                                {
                                    "term": {
                                        "common_name.keyword": {
                                            "value": clean_name,
                                            "boost": 5.0
                                        }
                                    }
                                },
                                {
                                    "term": {
                                        "show_name.keyword": {
                                            "value": clean_name,
                                            "boost": 5.0
                                        }
                                    }
                                },
                                {
                                    "wildcard": {
                                        "common_name": {
                                            "value": f"*{clean_name}*"
                                        }
                                    }
                                },
                                {
                                    "wildcard": {
                                        "show_name": {
                                            "value": f"*{clean_name.lower()}*",
                                            "case_insensitive": True
                                        }
                                    }
                                }
                            ]
                        }
                    },
                    "size": fallback_size
                }
                msearch_body_fallback.append(q_body_fallback)

            # 执行第二轮搜索
            try:
                if msearch_body_fallback:
                    resp_fallback = await self.es_client.msearch(body=msearch_body_fallback)
                    responses_fallback = resp_fallback.get("responses", [])
                else:
                    responses_fallback = []
            except Exception:
                logger.exception("Fallback msearch failed for indices: %s", missing_indices)
                # 如果兜底失败，保持 None
            
            # 填入兜底结果
            for idx_in_resp, original_idx in enumerate(missing_indices):
                if idx_in_resp < len(responses_fallback):
                    resp = responses_fallback[idx_in_resp]
                    hits = resp.get("hits", {}).get("hits", [])
                    
                    if hits:
                        best_hit = hits[0]
                        doc = dict(best_hit["_source"])  # 创建副本，避免循环引用
                        doc["_score"] = best_hit.get("_score", 0)
                        doc["matched_drug"] = names[original_idx]
                        doc["match_type"] = "fallback"

                        candidates = []
                        for h in hits:
                            cand_doc = dict(h["_source"])  # 创建副本，避免循环引用
                            cand_doc["_score"] = h.get("_score", 0)
                            candidates.append(cand_doc)
                        doc["candidates"] = candidates

                        final_results[original_idx] = doc
                    else:
                        # 彻底没找到
                        final_results[original_idx] = {
                            "drug_id": None,
                            "common_name": None,
                            "show_name": None,
                            "matched_drug": names[original_idx],
                            "match_type": "none",
                            "candidates": []
                        }

        # -------------------------------------------------------
        # Finalize: 清理 None 值（理论上都已填充）
        # -------------------------------------------------------
        clean_results = []
        for i, res in enumerate(final_results):
            if res is None:
                # 这种情况通常是输入为空字符串
                clean_results.append({
                    "drug_id": None,
                    "matched_drug": names[i],
                    "match_type": "none"
                })
            else:
                clean_results.append(res)

        logger.info(
            "search_by_drugnames completed: %d drugs, %.2fs",
            len(names), time.time() - start
        )

        return clean_results, len(clean_results), raw_query

    async def search_single_drug_by_aliases(
        self,
        aliases: List[str],
        size: int = 1
    ) -> Dict[str, Any]:
        start = time.time()
        
        # 获取用于标识的基准药物名
        primary_name = aliases[0] if aliases else "Unknown"
        
        # 1. 基础清理
        clean_aliases = list(set([a.strip() for a in aliases if a.strip()]))
        if not clean_aliases:
            return {"drug_id": None, "matched_drug": primary_name, "match_type": "none", "candidates": []}

        if not primary_name.strip():
            primary_name = clean_aliases[0]

        # -------------------------------------------------------
        # Phase 1: 绝对精准层 (Strict Phase)
        # 目标：秒杀全称匹配、缩写精准匹配，对齐 search_by_drugnames 逻辑
        # -------------------------------------------------------
        strict_should_clauses = [
            # 1. Keyword 绝对精准命中
            {"terms": {"common_name.keyword": clean_aliases, "boost": 1000.0}},
            {"terms": {"show_name.keyword": clean_aliases, "boost": 1000.0}}
        ]
        
        for alias in clean_aliases:
            # 2. 短语前缀匹配 (对齐 search_by_drugnames)
            strict_should_clauses.append({
                "multi_match": {
                    "query": alias,
                    "fields": ["common_name^5", "show_name^5"],
                    "type": "phrase_prefix", 
                    "boost": 100.0
                }
            })

            # 3. 包含匹配 (Wildcard) 提前到 Strict 阶段 (解决原版直接漏检的核心问题)
            if len(alias) > 1:
                strict_should_clauses.extend([
                    {"wildcard": {"common_name": {"value": f"*{alias}*", "boost": 10.0}}},
                    {"wildcard": {"show_name": {"value": f"*{alias.lower()}*", "case_insensitive": True, "boost": 10.0}}}
                ])

        query_body_strict = {
            "_source": ["drug_id", "common_name", "show_name", "company_name", "text"],
            "query": {"bool": {"should": strict_should_clauses, "minimum_should_match": 1}},
            "size": size
        }

        try:
            resp_strict = await self.es_client.search(index=self.es_index, body=query_body_strict)
            hits = resp_strict.get("hits", {}).get("hits", [])
            if hits:
                best_hit = hits[0]
                doc = dict(best_hit["_source"])
                doc.update({"_score": best_hit.get("_score", 0), "matched_drug": primary_name, "match_type": "strict"})
                return doc
        except Exception:
            logger.exception("Strict search failed for aliases: %s", clean_aliases)

        # -------------------------------------------------------
        # Phase 2: 智能兜底层 (Fallback Phase)
        # 目标：应对错别字、漏字，坚决防止短英文泛滥匹配
        # -------------------------------------------------------
        fallback_should_clauses = []
        
        for alias in clean_aliases:
            # 嗅探词汇特征
            is_pure_english = bool(re.match(r'^[a-zA-Z\s\-]+$', alias))
            is_short_acronym = is_pure_english and len(alias) <= 4  # 如 ADM, DOX
            
            # 1. 使用 best_fields 进行高容错匹配，对齐 search_by_drugnames
            fallback_should_clauses.append({
                "multi_match": {
                    "query": alias,
                    "fields": ["common_name^2", "show_name^2"],
                    "type": "best_fields",
                    "minimum_should_match": "75%",
                    "boost": 5.0
                }
            })

            # 2. 受控的通配符模糊匹配
            if not is_short_acronym and len(alias) >= 4:
                # 策略调整：先用【原词】过一遍 Wildcard (防止带括号的词被误杀)
                fallback_should_clauses.extend([
                    {"wildcard": {"common_name": {"value": f"*{alias}*"}}},
                    {"wildcard": {"show_name": {"value": f"*{alias.lower()}*", "case_insensitive": True}}}
                ])
                
                # 双重保险：再用【去括号版】过一遍 (应对用户搜带括号，库里没括号的情况)
                safe_alias = re.sub(r'[()（）\[\]]', '', alias)
                if safe_alias and safe_alias != alias:
                    fallback_should_clauses.extend([
                        {"wildcard": {"common_name": {"value": f"*{safe_alias}*"}}},
                        {"wildcard": {"show_name": {"value": f"*{safe_alias.lower()}*", "case_insensitive": True}}}
                    ])

        # 如果所有的条件都被过滤掉了（比如全是3个字母以内的英文缩写），直接返回没搜到
        if not fallback_should_clauses:
            return {"drug_id": None, "matched_drug": primary_name, "match_type": "none", "candidates": []}

        query_body_fallback = {
            "_source": ["drug_id", "common_name", "show_name", "company_name", "text"],
            "query": {"bool": {"should": fallback_should_clauses, "minimum_should_match": 1}},
            "size": size
        }

        try:
            resp_fallback = await self.es_client.search(index=self.es_index, body=query_body_fallback)
            hits = resp_fallback.get("hits", {}).get("hits", [])
            if hits:
                best_hit = hits[0]
                doc = dict(best_hit["_source"])
                doc.update({
                    "_score": best_hit.get("_score", 0), 
                    "matched_drug": primary_name, 
                    "match_type": "fallback", 
                    "candidates": [dict(h["_source"], _score=h.get("_score", 0)) for h in hits]
                })
                return doc
        except Exception:
            logger.exception("Fallback search failed for aliases: %s", clean_aliases)

        return {"drug_id": None, "matched_drug": primary_name, "match_type": "none", "candidates": []}

if __name__ == "__main__":
    async def main():
        searcher = DrugManualsElasticSearch()
        try:
            results, count, query = await searcher.search_by_drugnames("阿司匹林, 布洛芬, 非存在药物XYZ")
            print(count)
            print(query)
            for res in results:
                print(res)
                
        finally:
            # 清理 Elasticsearch 客户端
            from utils.core.elasticsearch_client import ElasticsearchClientSingleton
            await ElasticsearchClientSingleton.cleanup()
    
    asyncio.run(main())