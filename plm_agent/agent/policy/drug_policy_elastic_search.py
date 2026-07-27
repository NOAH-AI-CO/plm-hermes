import os
import time
import asyncio
import logging

os.environ["TOKENIZERS_PARALLELISM"] = "false"

from typing import List
from fastembed import TextEmbedding
from utils.core.elasticsearch_client import ElasticsearchClientSingleton

logger = logging.getLogger(__name__)

class DrugPolicyElasticSearch:

    def __init__(self):
        self.es_client = ElasticsearchClientSingleton.get_asyncclient()
        self.model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

    def _encode_query(self, query: str) -> List[float]:
        embeddings = list(self.model.embed([query]))
        if not embeddings:
            raise ValueError("fastembed returned empty embeddings for query")
        return embeddings[0].tolist()

    async def search_drug_policy(
        self,
        index: str,
        query: str,
        size: int = 10,
        vector_top_n: int = 50,
        bm25_top_n: int = 50,
    ):
        if index not in ["drug_policy_china", "drug_policy_global"]:
            logger.error("index not in drug_policy_china drug_policy_global")
            return None
        query_embedding = self._encode_query(query)

        vector_query = {
            "knn": {
                "field": "embedding",
                "query_vector": query_embedding,
                "k": vector_top_n,
                "num_candidates": vector_top_n,
            }
        }

        vector_res = await self.es_client.search(
            index=index,
            body=vector_query
        )

        vector_docs = vector_res["hits"]["hits"]

        # 存储向量分数
        for d in vector_docs:
            d["score_vector"] = float(d["_score"])
            d["score_bm25"] = 0.0

        bm25_query = {
            "size": bm25_top_n,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["title", "text"]
                }
            }
        }

        bm25_res = await self.es_client.search(
            index=index,
            body=bm25_query
        )

        bm25_docs = bm25_res["hits"]["hits"]
        for d in bm25_docs:
            d["score_bm25"] = float(d["_score"])
            d["score_vector"] = 0.0

        # 合并去重
        merged = {}
        for d in vector_docs + bm25_docs:
            doc_id = d["_id"]
            if doc_id not in merged:
                merged[doc_id] = d
            else:
                # 合并向量分数和 bm25 分数
                merged[doc_id]["score_vector"] = max(
                    merged[doc_id]["score_vector"],
                    d.get("score_vector", 0.0),
                )
                merged[doc_id]["score_bm25"] = max(
                    merged[doc_id]["score_bm25"],
                    d.get("score_bm25", 0.0),
                )

        merged_docs = list(merged.values())

        def final_score(d):
            return d["score_vector"] * 0.85 + d["score_bm25"] * 0.15

        merged_docs.sort(key=final_score, reverse=True)

        final_docs = merged_docs[:size]

        results = [
            {
                "id": d["_id"],
                "title": d["_source"]["title"],
                "text": d["_source"]["text"],
                "score_vector": d["score_vector"],
                "score_bm25": d["score_bm25"]
            }
            for d in final_docs
        ]

        return results

async def test_drug_manuals_elastic_search():
    searcher = DrugPolicyElasticSearch()
    
    # 执行 BM25 查询，查询内容为"aspirin"的药品
    result = await searcher.search_by_drugname("aspirin", size=10)
    print(result)

if __name__ == "__main__":
    asyncio.run(test_drug_manuals_elastic_search())
