# -*- coding: utf-8 -*-
import re
import time
import numpy as np
import logging
import elasticsearch

from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterable, Set, Deque
from pymilvus import Collection, utility
from pymilvus import exceptions as MilvusExceptions
from pymilvus.client.types import LoadState

from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from utils.core.milvus_client import MilvusClientSingleton
from utils.pubmed_opt.pubmed_encoder import MedCPTEncoder
from utils.pubmed_opt.pubmed_reranker import PubMedReranker

logger = logging.getLogger(__name__)

_hot_lru: Deque[str] = deque(maxlen=5)
_cold_lru: Deque[str] = deque(maxlen=5)


class PubMedVectorSearch:
    """
    Load encoders, connect to Milvus, encode, search, (optionally) merge.

    So far we have two PubMed Milvus databases: Pubmed_hot, Pubmed_code.
    Pubmed_hot use graph index and only contains the latest five years articles, the partitions like y_2021, y_2022, y_2023, y_2024, ...
    Pubmed_cold use common index and contains the other years artilces, the partitions like, y_2010_2015, y_2001_2005, y_2006_2010, y_2011_2015, ...
    """
    score_higher_better: bool = True
    METRIC_TYPE: str = 'COSINE'
    PUBMED_HOT: str = 'pubmed_hot'
    PUBMED_COLD: str = 'pubmed_cold'
    milvus_alias: str = r'Pubmed'
    recall_top_k: int = 100
    es_index: str = "pubmed_simplified"

    def __init__(self) -> None:
        
        self.encoder = MedCPTEncoder()
        self._es_client: Optional[elasticsearch.AsyncElasticsearch] = None

        # Get the directory of this file
        current_dir = Path(__file__).parent
        self.reranker = PubMedReranker(
            pubtype_yaml=str(current_dir / "config" / "pubtype_boost.yaml"),
            alias_file=str(current_dir / "config" / "pubtype_alias.yaml"),
        )
        
        self.pubmed_hot_collection = MilvusClientSingleton.get_collection(self.PUBMED_HOT)
        self.pubmed_cold_collection = MilvusClientSingleton.get_collection(self.PUBMED_COLD)
        logger.info(f"Current valid collection {self.pubmed_hot_collection}, {self.pubmed_cold_collection}")

        self._default_hot_search_params  = {"metric_type": self.METRIC_TYPE, "params": {"ef": 128}}
        self._default_cold_search_params = {"metric_type": self.METRIC_TYPE, "params": {"nprobe": 32}}
    
    @property
    def es_client(self) -> elasticsearch.AsyncElasticsearch:
        if self._es_client is None:
            ElasticsearchClientSingleton.initialize()
            self._es_client = ElasticsearchClientSingleton.get_client()
        return self._es_client

    def search_years(
        self,
        inputs: List[str],
        years: List[int],
        size: int = 20,
        input_type: str = "query", # Current only surpport query, article
        search_params_hot: Optional[Dict[str, Any]] = None,
        search_params_cold: Optional[Dict[str, Any]] = None,
        force_load_partitions: bool = False
    ) -> List:
        
        # Embedding
        if input_type == "query":
            emb = self.encoder.query_encode(inputs)
        elif input_type == "article":
            emb = self.encoder.article_encode(inputs)
        else:
            raise ValueError(f"Invalid input_type: {input_type}")

        if emb is None or emb.size == 0:
            return []

        hot = self._search_by_years(
            self.PUBMED_HOT,
            emb,
            years,
            size,
            search_params=search_params_hot or self._default_hot_search_params,
            force_load_partitions=force_load_partitions,
        )

        cold = self._search_by_years(
            self.PUBMED_COLD,
            emb,
            years,
            size,
            search_params=search_params_cold or self._default_cold_search_params,
            force_load_partitions=force_load_partitions,
        )

        return self.merge(hot, cold, size)      
    
    def _search_by_years(
        self,
        coll_name: str,
        emb: np.ndarray,
        years: Iterable[int],
        size: int,
        search_params: Optional[Dict[str, Any]] = None,
        force_load_partitions: bool = False,
    ) -> List[List[Dict[str, Any]]]:

        collection = self.pubmed_hot_collection if coll_name == self.PUBMED_HOT else self.pubmed_cold_collection

        parts = self._resolve_partitions_by_years(collection, years)

        if not parts:
            return []

        loaded = self._ensure_loaded(collection, parts, force_load_partitions)
       
        return self.search_collection(
            coll=collection,
            emb=emb,
            size=size,
            partitions=loaded,
            search_params=search_params,
            coll_name=coll_name,
        )

    def _resolve_partitions_by_years(
        self,
        coll: Collection,
        years: Iterable[int],
        include_unknown: bool = False
    ) -> List[str]:
        r"""
        Reslove years and return partition list.
        Collation partitions are _default, y_unknown, y_2021, y_2022, y_2023, y_2021_2025, y_le_1983 ...
        Map years to the target partitons, i.e. 2024 -> y_2024, 2003 -> y_2000_2004
        Return is the partition names.
        """
        try:
            names = [p.name for p in coll.partitions]
        except Exception:
            names = []
        
        # Intervals are [(partion, start year, end year)], i.e [(y_2025, 2025, 2025)]
        intervals = [] 
        for n in names:
            m = re.fullmatch(r"y_(\d{4})_(\d{4})", n)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo > hi: 
                    lo, hi = hi, lo
                intervals.append((n, lo, hi))
                continue
            m = re.fullmatch(r"y_(\d{4})", n)
            if m:
                y = int(m.group(1))
                intervals.append((n, y, y))
                continue
            m = re.fullmatch(r"y_le_(\d{4})", n)
            if m:
                hi = int(m.group(1))
                intervals.append((n, -10**9, hi))
                continue
            if n == "y_unknown" and include_unknown:
                intervals.append((n, None, None))

        want: Set[str] = set()
        for y in years:
            try:
                yi = int(y)
            except Exception:
                continue
            for name, lo, hi in intervals:
                if lo is None and hi is None:
                    continue  # unknown 只在 include_unknown=True 时处理，上面已筛
                if lo <= yi <= hi:
                    want.add(name)
        return sorted(want)

    def _ensure_loaded(
        self,
        coll: Collection,
        partitions: Optional[List[str]],
        force_load_partitions: bool,
        timeout_s: int = 30,
    ) -> List[str]:
        r"""
        Make sure the required partitions should be loaded.
        """

        if force_load_partitions:
            coll.load(partition_names=partitions)
            self._wait_loaded(coll, timeout_s)
            self._record_lru(coll.name, coll, partitions)
            return partitions

        loaded = []
        unloaded = []
        for partition_name in partitions:
            try:
                state = utility.load_state(coll.name, [partition_name], using=self.milvus_alias, timeout=2)
                if state == LoadState.Loaded:
                    loaded.append(partition_name)
            except Exception as e:
                unloaded.append(partition_name)
        
        logger.info(f"Current loaded partitions: {loaded}, unloaded: {unloaded}")

        return loaded
        
    def _wait_loaded(
        self,
        coll: Collection,
        timeout_s: int
    ) -> None:
        deadline = time.time() + max(1, timeout_s)
        while time.time() < deadline:
            try:
                state = utility.load_state(coll.name, using=self.milvus_alias, timeout=2)
                if state == LoadState.Loaded:
                    break
                elif state == LoadState.Loading:
                    time.sleep(1)
                else:
                    logger.warning(f"Invalid state {state} of {coll.name}")
                    break
            except Exception as e:
                logger.warning(f"Get Milvus collection {coll.name} loading results: {e}")
                break

    def _record_lru(
        self,
        coll_name: str,
        coll: Collection,
        new_parts: List[str],
    ) -> None:
        global _hot_lru, _cold_lru
        lru = _hot_lru if coll_name == self.PUBMED_HOT else _cold_lru

        if not new_parts:
            return

        # Insert new partitions; move duplicates to the end to mark as most recent
        for p in new_parts:
            if p in lru:
                lru.remove(p)
            lru.append(p)

        # Compute which partitions exceed capacity to release from Milvus
        overflow = len(lru) - lru.maxlen
        if overflow > 0:
            drop = list(lru)[:-lru.maxlen]  # all older ones beyond the last maxlen
            try:
                coll.release(partition_names=drop)
            except Exception:
                pass
            # Trim deque to capacity (remove from the left = oldest)
            while len(lru) > lru.maxlen:
                lru.popleft()

    def search_collection(
        self,
        coll: Collection,
        emb: np.ndarray,
        size: int,
        partitions: Optional[List[str]] = None,
        search_params: Optional[Dict[str, Any]] = None,
        coll_name: Optional[str] = None
    ) -> List[List[Dict[str, Any]]]:

        try:
            res = coll.search(
                data=emb,
                anns_field="embedding",
                param=search_params or {},
                limit=max(1, size),
                expr=None,
                partition_names=partitions,
                output_fields=["pmid", "year"],
                consistency_level="Eventually",
            )
        except MilvusExceptions.MilvusException as e:
            logger.warning(f"Query Milvus failed: {e}")
            return []

        name = coll_name or getattr(coll, "name", "unknown")

        out: List[List[Dict[str, Any]]] = []
        for hits in res:
            cur: List[Dict[str, Any]] = []
            for h in hits:
                d = float(h.distance)
                # 统一把分数转为“越大越好”
                if self.METRIC_TYPE.upper() == "COSINE":
                    score = 1.0 - d  # similarity
                elif self.METRIC_TYPE.upper() == "L2":
                    score = -d       # 距离越小越好 -> 取负
                else:  # IP 通常已经是越大越好
                    score = d
                cur.append({
                    "pmid": str(h.entity.get("pmid")),
                    "year": int(h.entity.get("year")),
                    "score": score,
                    "collection": name,
                    # "partition": getattr(h, "partition_name", None),
                })
            out.append(cur)
        return out

    def merge(
        self,
        A: List[List[Dict[str, Any]]],
        B: List[List[Dict[str, Any]]],
        size: int
    ) -> List[List[Dict[str, Any]]]:
        r"""
        Merge results from hot and cold collections; when reverse=True, higher scores come first.
        """
        reverse = self.score_higher_better
        out: List[List[Dict[str, Any]]] = []
        for i in range(max(len(A), len(B))):
            merged = (A[i] if i < len(A) else []) + (B[i] if i < len(B) else [])
            merged.sort(key=lambda x: x["score"], reverse=reverse)
            out.append(merged[:size])
        return out
    
    def fetch(
        self,
        pmids: List[str],
        source_fields: Optional[List[str]] = ['title', 'abstract', 'pmid', 
        'pmc_id', 'doi', 'author', 'issn', 'essn', 'journal', 
        'nlmuniqueid', 'pubmed_pub_date'],
    ) -> List[Dict[str, Any]]:
        # Build mget request parameters
        mget_params = {
            'index': self.es_index,
            'ids': pmids
        }
        
        if source_fields is not None:
            mget_params['_source'] = source_fields
        
        result = self.es_client.mget(**mget_params)
        doc_list = [doc['_source'] for doc in result['docs'] if doc['found']]
        return doc_list

    def vector_search(
        self,
        queries: List[str],
        years: List[int],
        input_type: str = "query",
        size: int = 20,
        use_ce: bool = False,
        force_load_partitions: bool = False,
    ) -> List[List[Dict[str, Any]]]:

        # 1. retrieve
        # Init PubMed Vector search
        if not years:    
            current_year = datetime.now().year
            years = list(range(current_year - 1, current_year + 1))

        hits_per_q = self.search_years(
            inputs=queries,
            years=years,
            input_type=input_type,
            force_load_partitions=force_load_partitions,
            size=size,
        )

        # 2. Rerank
        all_results: List[List[Dict[str, Any]]] = []
        for qi, hits in enumerate(hits_per_q):
            if not hits:
                all_results.append([])
                continue

            # 2.1 Remove duplicate pmid
            best: Dict[str, Dict[str, Any]] = {}
            for h in hits:
                p = str(h["pmid"])
                if p not in best or h["score"] > best[p]["score"]:
                    best[p] = h
            dedup_hits = list(best.values())

            # 2.2 Fetch pubmed article detail by pmid
            pmids = [h["pmid"] for h in dedup_hits]
            datalist = self.fetch(pmids)
            pmid2item: Dict[str, Any] = {p['pmid']: p for p in datalist if 'pmid' in p}
            pmid2types: Dict[str, List[str]] = {p['pmid']: p.get('pub_types',[]) for p in datalist if 'pmid' in p}

            # 2.3 Fetch pub_types
            pmid2types: Dict[str, List[str]] = {p: pmid2item.get(p, {}).get("pub_types", []) for p in pmids}

            # 2.4 Use cross encoding
            ce_scores: Optional[Dict[str, float]] = None
            if use_ce:
                query_text = queries[qi]
                texts, ce_pmids = [], []
                for p in pmids:
                    meta = pmid2item.get(p, {})
                    title = meta.get("title") or ""
                    abstract = meta.get("abstract") or ""
                    texts.append(f"{title}\n\n{abstract}".strip())
                    ce_pmids.append(p)
                if texts:
                    scores = self.encoder.cross_encode([query_text]*len(texts), texts, batch_size=32)
                    ce_scores = {pm: float(s) for pm, s in zip(ce_pmids, scores)}

             # 6) rerank
            reranked = self.reranker.rerank(dedup_hits, pmid2types=pmid2types, ce_scores=ce_scores)

            # 7) formater
            enriched: List[Dict[str, Any]] = []
            for r in reranked[:size]:
                p = r["pmid"]
                meta = pmid2item.get(p, {})
                enriched.append(meta)

            all_results.append(enriched)
        
        return all_results

# test
def test_pubmed_vector_search():

    ElasticsearchClientSingleton.initialize()

    MilvusClientSingleton.initialize()

    searcher = PubMedVectorSearch()

    q = ['Respiratory Syncytial Virus ']
    years = [2024, 2025, 1993]
    results = searcher.vector_search(queries=q, years=years, input_type="query", size=10, force_load_partitions=False)
    print(results)
    
    """
    q = ["Background: Respiratory Syncytial Virus (RSV) causes substantial morbidity in young infants and older adults. Currently licensed recombinant protein RSV vaccines for older adults are efficacious following an initial dose but exhibit suboptimal boostability upon re-vaccination after efficacy wanes. We evaluated SCB-1019T, a novel unadjuvanted bivalent RSV prefusion F (preF) protein vaccine stabilized via Trimer-Tag™ technology, head-to-head against AS01E-adjuvanted Arexvy in RSV-vaccine naïve older adults. Methods: In this ongoing phase 1, randomized, placebo-controlled, observer-blind study, 70 older adults (60–85 years) received one dose of SCB-1019T (unadjuvanted), Arexvy (AS01E-adjuvanted), or placebo. Safety, reactogenicity, and immunogenicity were assessed through 28 days post-vaccination. Results: Unadjuvanted SCB-1019T elicited significantly fewer local reactions than AS01E-adjuvanted Arexvy, while both vaccines induced comparable levels of RSV neutralizing antibody responses at 28 days post-vaccination. Exploratory immunogenicity results suggest that SCB-1019T induces higher functional antibody quality than Arexvy, which observed significant decreases in the ratio of RSV neutralizing antibodies-to-total preF binding antibodies at 28 days. Most systemic and local reactions were mild, and no safety concerns were identified for any study vaccines Conclusions: Unadjuvanted SCB-1019T demonstrated better tolerability and elicited differentiated functional humoral immune responses compared to AS01E-adjuvanted Arexvy in older adults, supporting further evaluation of unadjuvanted SCB-1019T in a RSV re-vaccination setting and as part of a respiratory combination vaccine containing multiple Trimer-TaggedTM preF antigens (such as hMPV and hPIV)."]
    years = [2024, 2025, 2003]
    results = searcher.vector_search(queries=q, years=years, input_type="article", size=10, force_load_partitions=True)

    for i, hits in enumerate(results):
        print(f"\nQuery #{i}: {q[i]}")
        for rank, h in enumerate(hits, 1):
            print(f"{rank:02d}. pmid={h['pmid']} year={h['year']} score={h['score']:.4f} "
                  f"from={h.get('collection','?')}")
    """

if __name__ == "__main__":
    test_pubmed_vector_search()
