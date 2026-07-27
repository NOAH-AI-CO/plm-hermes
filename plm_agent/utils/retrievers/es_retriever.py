from typing import Any, Dict, List

from elasticsearch import Elasticsearch

from config import settings
from utils.open_api import Ada


class ESRetriever:
    """Document retriever based on Elastic Search"""

    def __init__(self, es: Elasticsearch, index_name: str, similarity_top_k: int = 20):
        """
        Args:
            es: Elastic Search instance
            index_name: Index name of ES
            similarity_top_k: Number of results to return
        """
        self.es = es
        self.index_name = index_name
        self.similarity_top_k = similarity_top_k

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve documents based on the query. Using full text search (BM25) to retrieve documents.

        Args:
            query: Query string

        Returns:
            List of documents with their IDs, scores and text
        """
        try:
            res = self.es.search(
                index=self.index_name, 
                body={
                    "query": {"match": {"content": query}},
                    "size": self.similarity_top_k
                }
            )
            return [{'id': hit['_id'], 'score': hit['_score'], 'text': hit['_source']['content']} for hit in res['hits']['hits']]
        except Exception as e:
            return None
    
    def keyword_search(self, field, keyword):
        query = {
            "query": {
                "term": {
                    field: keyword 
                }
            },
            "size": self.similarity_top_k
        }
        
        response = self.es.search(index=self.index_name, body=query)
            
        return [hit['_source'] for hit in response['hits']['hits']]

class ESVectorRetriever:
    """Document retriever based on Elastic Search vector similarity search"""

    def __init__(self, es: Elasticsearch, index_name: str, similarity_top_k: int = 20):
        """
        Args:
            es: Elastic Search instance
            index_name: Index name of ES
            similarity_top_k: Number of results to return
        """
        self.es = es
        self.index_name = index_name
        self.similarity_top_k = similarity_top_k
        self.model = Ada()

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """
        Retrieve documents based on the query. Using vector similarity search to retrieve documents from ES.

        Args:
            query: Query string

        Returns:
            List of documents with their IDs, scores and text
        """
        try:
            query_embedding = self.model.get_embedding(query)
            res = self.es.search(
                index=self.index_name,
                body={
                    "query": {
                        "script_score": {
                            "query": {"match_all": {}},
                            "script": {
                                "source": "cosineSimilarity(params.query_vector, 'embedding') + 1.0",
                                "params": {"query_vector": query_embedding}
                            }
                        }
                    },
                    "size": self.similarity_top_k
                }
            )
            return [{'id': hit['_id'], 'score': hit['_score'], 'text': hit['_source']['content']} for hit in res['hits']['hits']]
        except Exception as e:
            print(e)
            return None

class ESHybridRetriever:
    """Hybrid Retriever that combines the results from ES full text search (BM25) and vector retrievers"""

    def __init__(self,
                 es_url: str=settings.ES_URL,
                 es_username: str=settings.ES_USERNAME,
                 es_password: str=settings.ES_PASSWORD,
                 index_name: str=settings.ES_INDEX_NAME,
                 similarity_top_k: int = 10):
        self.es = Elasticsearch(hosts=es_url, basic_auth=(es_username, es_password))
        if self.es.ping():
            print("Connection successful")
        else:
            print("Connection failed")
        self.es_retriever = ESRetriever(self.es, index_name, similarity_top_k)
        self.vdb_retriever = ESVectorRetriever(self.es, index_name, similarity_top_k)
        self.similarity_top_k = similarity_top_k

    def _retrieve(self, query: str):
        es_res = self.es_retriever.retrieve(query)
        vdb_res = self.vdb_retriever.retrieve(query)
        return es_res, vdb_res

    def _calculate_rrf(self, scores: List[List[str]], k: int = 60) -> List[str]:
        """
        Calculate Reciprocal Rank Fusion scores.
        
        Args:
            scores: A list of lists, where each sublist contains ranked document IDs.
            k: The RRF parameter, controlling fusion behavior.
        Returns:
            A sorted list of documents based on RRF scores.
        """
        rrf_scores = {}
        for score_list in scores:
            for rank, doc_id in enumerate(score_list, start=1):
                rrf_score = 1 / (k + rank)
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + rrf_score
        
        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_id for doc_id, _ in sorted_docs]

    def retrieve(self, query: str) -> List[str]:
        """
        Retrieve documents based on the query. Combining the results from ES and vector retrievers. Then calculate RRF scores to fuse the results.
        """
        es_res, vdb_res = self._retrieve(query)
        es_ids = [hit['id'] for hit in es_res]
        vdb_ids = [hit['id'] for hit in vdb_res]
        fused_ids = self._calculate_rrf([es_ids, vdb_ids])

        searched_results = []
        for doc_id in fused_ids:
            if doc_id in es_ids:
                searched_results.append([x['text'] for x in es_res if x['id'] == doc_id][0])
            else:
                searched_results.append([x['text'] for x in vdb_res if x['id'] == doc_id][0])
        return searched_results[:self.similarity_top_k]
