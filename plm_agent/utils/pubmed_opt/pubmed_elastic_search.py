# -*- coding: utf-8 -*-
import time
import asyncio
import logging
from pathlib import Path

from typing import List, Dict, Any, Optional

from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.pubmed_opt.pubmed_encoder import MedCPTEncoder
from utils.pubmed_opt.pubmed_reranker import PubMedReranker

logger = logging.getLogger(__name__)


class PubMedElasticSearch:

    es_index: str = "pubmed_simplified"

    def __init__(self):
        
        self.es_client = ElasticsearchClientSingleton.get_asyncclient()
        self.pubmed_encoder = MedCPTEncoder()

        # Get the directory of this file
        current_dir = Path(__file__).parent
        self.reranker = PubMedReranker(
            pubtype_yaml=str(current_dir / "config" / "pubtype_boost.yaml"),
            alias_file=str(current_dir / "config" / "pubtype_alias.yaml"),
        )

    async def fetch(
        self,
        pmids: List[str],
        source_fields: Optional[List[str]] = ['title', 'abstract', 'pmid', 
        'pmc_id', 'doi', 'author', 'issn', 'essn', 'journal', 
        'nlmuniqueid', 'pubmed_pub_date'],
    ) -> Dict[str, Any]:
        # Build mget request parameters
        mget_params = {
            'index': self.es_index,
            'ids': pmids
        }
        
        if source_fields is not None:
            mget_params['_source'] = source_fields
        
        result = await self.es_client.mget(**mget_params)
        doc_list = [doc['_source'] for doc in result['docs'] if doc['found']]
        return {'results': doc_list, 'total_count': len(doc_list)}

    async def query_by_pmid(self, pmid: str) -> Dict[str, Any]:
        """
        查询指定 pmid 对应的文献（term 精准匹配）
        """
        query_body = {
            "query": {
                "term": {
                    "pmid": {
                        "value": str(pmid)
                    }
                }
            },
            "size": 1,
            "from": 0,
            "sort": []
        }

        result = await self.es_client.search(index=self.es_index, body=query_body)
        hits = result["hits"]["hits"]
        docs = [hit["_source"] for hit in hits]
        return {"results": docs, "total_count": result["hits"]["total"]["value"]}

    async def query_by_title(self, title: str) -> Dict[str, Any]:
        """
        查询指定 pmid 对应的文献（term 精准匹配）
        """
        query_body = {
            "query": {
                "term": {
                    "title.keyword": title, 
                }
            },
            "size": 1,
            "from": 0,
            "sort": []
        }

        result = await self.es_client.search(index=self.es_index, body=query_body)
        hits = result["hits"]["hits"]
        docs = [hit["_source"] for hit in hits]
        return {"results": docs, "total_count": result["hits"]["total"]["value"]}
        
    async def bm25_search_simple(
        self,
        query: str = "",
        years: List[int] = [],
        size: int = 20,
        **kwargs
    ) -> (List[Dict[str, Any]], int, str):
        start_time = time.time()
        # Construct BM25 query body
        from_index = kwargs.get('from', 0)
        is_sort_by_date = kwargs.get('is_sort_by_date', False)

        query_body = {
            "query": {
                "bool": {
                    "must": [],
                    "filter": []
                }
            },
            "size": size,
            "from": from_index,
            "sort": [
                "_score",
                {"pubmed_pub_date": {"order": "desc"}}
            ],
            "timeout": "10s",
        }
        if is_sort_by_date:
            query_body["sort"] = [
                {"pubmed_pub_date": {"order": "desc"}},
                "_score"
            ]

        # Add text query on title and abstract if query is provided
        if query and query.strip():
            query_body["query"]["bool"]["must"].append({
                "match": {"title_abstract_bm25": query}
            })

        # Add year filter using year_of_publication field (keyword type)
        if years:
            # Convert years to strings since year_of_publication is keyword type
            year_strings = [str(year) for year in years]
            
            if len(year_strings) == 1:
                # Single year - use term query
                year_filter = {
                    "term": {
                        "year_of_publication": year_strings[0]
                    }
                }
            else:
                # Multiple years - use terms query
                year_filter = {
                    "terms": {
                        "year_of_publication": year_strings
                    }
                }
            
            query_body["query"]["bool"]["filter"].append(year_filter)
        
        try:
             # Search in Elasticsearch
            logger.debug('BM25 query_body: {}'.format(query_body))
            result = await self.es_client.search(index=self.es_index, body=query_body)
            total_count = result['hits']['total']['value']
            
            # Formating results
            datalist = []
            for hit in result['hits']['hits']:
                doc = hit['_source']
                doc['_score'] = hit['_score']  # keep bm25 score
                datalist.append(doc)

            logger.info(f"BM25 search completed in {time.time() - start_time:.2f} seconds, ")
            return datalist, total_count, query
        
        except Exception as e:
            logger.error(f"Elasticsearch query failed: {e}")
            return [], 0, query

    async def bm25_search(
        self,
        query: str = "",
        years: List[int] = [],
        size: int = 20,
        **kwargs        
    ) -> List:
        if not query.strip():
            logger.info(f"Query and article are both empty.")
            return []

        # Initial BM25 search
        datalist, total_count, query_text = await self.bm25_search_simple(
            query=query,
            years=years,
            size=size,
            **kwargs
        )

        # Reranking
        # 1. Fetch publication types
        pmids: List[str] = [str(d['pmid']) for d in datalist if 'pmid' in d]
        pmid2item: Dict[str, Any] = {p['pmid']: p for p in datalist if 'pmid' in p}
        pmid2types: Dict[str, List[str]] = {p['pmid']: p.get('pub_types',[]) for p in datalist if 'pmid' in p}

        # 2. Compute cross-encoder scores if enabled
        ce_scores: Optional[Dict[str, float]] = None
        if self.reranker.use_ce and getattr(self.pubmed_encoder, "cross_encoder", None) is not None:
            texts, ce_pmids = [], []
            for p in pmids:
                meta = pmid2item.get(p, {})
                title = meta.get("title") or ""
                abstract = meta.get("abstract") or ""
                texts.append(f"{title}\n\n{abstract}".strip())
                ce_pmids.append(p)
            if texts:
                scores = self.pubmed_encoder.cross_encode([query_text] * len(texts), texts, batch_size=32)
                ce_scores = {pm: float(s) for pm, s in zip(ce_pmids, scores)}

        # 4. Rerank
        reranked = self.reranker.rerank(datalist, pmid2types=pmid2types, ce_scores=ce_scores)

        return reranked[:size]

# test
async def test_pubmed_elastic_search():
    
    searcher = PubMedElasticSearch()
    #result = await searcher.bm25_search_simple("headache", years=[2024, 2025])
    #print(result)

    result = await searcher.bm25_search("headache", years=[2024, 2025])
    print(result)

if __name__ == "__main__":
    asyncio.run(test_pubmed_elastic_search())