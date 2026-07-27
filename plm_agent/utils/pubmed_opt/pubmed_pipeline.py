# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional, Iterable, Tuple
import time, random, logging, requests, socket, os
from dataclasses import dataclass, field

from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch
from utils.pubmed_opt.pubmed_encoder import MedCPTEncoder
from utils.pubmed_opt.pubmed_reranker import PubMedReranker

log = logging.getLogger(__name__)

# ===============================
# 配置
# ===============================
@dataclass
class FetchConfig:
    base_url: str = "http://10.1.0.7:7000/api/v1/items/pubmed/"
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 20.0
    max_ids_per_call: int = 10            # 小批量更稳
    max_retries: int = 2
    backoff_base_s: float = 0.5
    degrade_to_single_on_fail: bool = True
    use_post_json: bool = False           # 若后端支持，强烈建议 True（POST {"ids":[...]})
    trust_env: bool = False               # 禁用系统代理干扰
    disable_proxy: bool = True

@dataclass
class SearchConfig:
    years: Iterable[int] = field(default_factory=lambda: [])
    recall_top_k: int = 100
    final_top_k: int = 20
    input_type: str = "query"  # "query" | "article"
    search_params_hot: Optional[Dict[str, Any]] = None
    search_params_cold: Optional[Dict[str, Any]] = None

@dataclass
class RerankConfig:
    pubtype_yaml: Optional[str] = None
    pubtype_boost: Optional[Dict[str, float]] = None
    alias_file: Optional[str] = None
    pubtype_alias: Optional[Dict[str, str]] = None
    type_agg: str = "max"
    default_boost: float = 1.0
    year_tau: float = 9.0
    year_clip: Tuple[float, float] = (0.6, 1.6)
    use_ce: bool = True
    ce_gamma: float = 0.35
    mix_mode: str = "mul"
    add_alpha: float = 1.0
    add_beta: float = 0.15
    filter_retracted: bool = True
    tie_break_by: Tuple[str, ...] = ("final_score","is_high_evidence","year","rel_vec")
    enable_veterinary_penalty: bool = True
    year_floor: float = 0.9
    sum_clip_cap: Optional[float] = None

# ===============================
# 详情拉取
# ===============================
class PubMedDetailFetcher:
    def __init__(self, cfg: FetchConfig):
        self.cfg = cfg

        self.session = requests.Session()
        # 关闭代理干扰
        self.session.trust_env = bool(cfg.trust_env)
        if cfg.disable_proxy:
            self.session.proxies = {"http": None, "https": None}

        log.info(f"[DetailFetcher] init base_url={self.cfg.base_url} batch={self.cfg.max_ids_per_call}")

    def _do_request(self, chunk: List[str]) -> Dict[str, Any]:
        """对单个 chunk 发起一次 HTTP 请求并返回 JSON"""
        timeout = (self.cfg.connect_timeout_s, self.cfg.read_timeout_s)
        if self.cfg.use_post_json:
            url = self.cfg.base_url.rstrip("/")
            payload = {"ids": chunk}
            log.info(f"[DetailFetcher] POST {url} json_len={len(payload['ids'])} sample={payload['ids'][:2]}")
            r = self.session.post(url, json=payload, timeout=timeout, allow_redirects=False)
        else:
            params = [("id", p) for p in chunk]
            log.info(f"[DetailFetcher] GET {self.cfg.base_url} nparams={len(params)} sample={params[:2]}")
            r = self.session.get(self.cfg.base_url, params=params, timeout=timeout, allow_redirects=False)

        log.info(f"[DetailFetcher] RESP {r.status_code} len={r.headers.get('content-length')}")
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _extract_pubtypes_from_item(item: Dict[str, Any]) -> List[str]:
        # 1) 扁平字段优先
        for key in ("publication_type", "publication_types", "pub_types", "PublicationType"):
            v = item.get(key)
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str) and v.strip():
                return [s.strip() for s in v.split(";") if s.strip()]
        # 2) PubMed 原始嵌套
        try:
            lst = item["MedlineCitation"]["Article"]["PublicationTypeList"]["PublicationType"]
            out = []
            for obj in lst:
                if isinstance(obj, dict):
                    val = obj.get("#text")
                    if isinstance(val, str) and val.strip():
                        out.append(val.strip())
            if out:
                return out
        except Exception:
            pass
        return []

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """补充常用字段（title/abstract/journal/doi/url 和 pub_types）"""
        norm = dict(item)
        # 常见大小写变体
        get = lambda *keys: next((item[k] for k in keys if isinstance(item.get(k), str) and item.get(k).strip()), None)
        norm.setdefault("title",   get("title", "Title"))
        norm.setdefault("abstract",get("abstract", "Abstract"))
        norm.setdefault("journal", get("journal", "Journal"))
        norm.setdefault("doi",     get("doi", "DOI"))
        norm.setdefault("url",     item.get("url") or item.get("URL") or item.get("link"))
        # 类型
        if "pub_types" not in norm:
            norm["pub_types"] = PubMedDetailFetcher._extract_pubtypes_from_item(item)
        return norm

    def fetch_batch(self, pmids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量拉取详情，返回 {pmid: 标准化item}
        """
        batch = int(self.cfg.max_ids_per_call or 10)
        chunks = [pmids[i:i+batch] for i in range(0, len(pmids), batch)]
        log.info(f"[fetch] plan {len(chunks)} chunks, chunk_size={batch}, total_ids={len(pmids)}, base_url={self.cfg.base_url}")

        out: Dict[str, Dict[str, Any]] = {}
        if not pmids:
            return out

        for idx, chunk in enumerate(chunks, 1):
            tries = 0
            while True:
                tries += 1
                try:
                    data = self._do_request(chunk)
                    # 解析常见返回结构
                    items: List[Dict[str, Any]] = []
                    if isinstance(data, dict) and isinstance(data.get("results"), list):
                        items = data["results"]
                    elif isinstance(data, dict) and isinstance(data.get("items"), list):
                        items = data["items"]
                    elif isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        # 极端：{ pmid: {...}, ...}
                        for k, v in data.items():
                            if isinstance(v, dict):
                                v.setdefault("pmid", k)
                                items.append(v)

                    got = 0
                    for it in items:
                        pid = str(it.get("pmid") or it.get("PMID") or it.get("id") or "").strip()
                        if not pid:
                            continue
                        out[pid] = self._normalize_item(it)
                        got += 1
                    log.info(f"[fetch] chunk {idx}/{len(chunks)} parsed={got} total_accum={len(out)}/{len(pmids)}")
                    break

                except Exception as e:
                    if tries > self.cfg.max_retries:
                        log.warning(f"[DetailFetcher] chunk {idx} failed after {tries} tries (size={len(chunk)}). err={e}")
                        # 降级：逐条请求，尽可能拿回
                        if self.cfg.degrade_to_single_on_fail and len(chunk) > 1:
                            for pid in chunk:
                                try:
                                    data1 = self._do_request([pid])
                                    if isinstance(data1, dict) and isinstance(data1.get("results"), list):
                                        items1 = data1["results"]
                                    elif isinstance(data1, dict) and isinstance(data1.get("items"), list):
                                        items1 = data1["items"]
                                    elif isinstance(data1, list):
                                        items1 = data1
                                    else:
                                        items1 = []
                                    for it in items1:
                                        p = str(it.get("pmid") or it.get("PMID") or it.get("id") or "").strip()
                                        if p:
                                            out[p] = self._normalize_item(it)
                                except Exception as e1:
                                    log.warning(f"[DetailFetcher] single {pid} failed: {e1}")
                        break
                    # 退避重试
                    sleep_s = self.cfg.backoff_base_s * (2 ** (tries-1)) + random.uniform(0, 0.2)
                    time.sleep(sleep_s)

        return out

# ===============================
# Pipeline
# ===============================
class PubMedSearchPipeline:
    def __init__(
        self,
        encoder: MedCPTEncoder,
        vector_searcher: PubMedVectorSearch,
        detail_fetcher: PubMedDetailFetcher,
        search_cfg: SearchConfig,
        rerank_cfg: RerankConfig,
    ):
        self.encoder = encoder
        self.searcher = vector_searcher
        self.fetcher = detail_fetcher
        self.search_cfg = search_cfg
        self.reranker = PubMedReranker(
            pubtype_yaml=rerank_cfg.pubtype_yaml,
            pubtype_boost=rerank_cfg.pubtype_boost,
            alias_file=rerank_cfg.alias_file,
            pubtype_alias=rerank_cfg.pubtype_alias,
            type_agg=rerank_cfg.type_agg,
            default_boost=rerank_cfg.default_boost,
            year_tau=rerank_cfg.year_tau,
            year_clip=rerank_cfg.year_clip,
            use_ce=rerank_cfg.use_ce,
            ce_gamma=rerank_cfg.ce_gamma,
            mix_mode=rerank_cfg.mix_mode,
            add_alpha=rerank_cfg.add_alpha,
            add_beta=rerank_cfg.add_beta,
            filter_retracted=rerank_cfg.filter_retracted,
            tie_break_by=rerank_cfg.tie_break_by,
            year_floor=rerank_cfg.year_floor,
            sum_clip_cap=rerank_cfg.sum_clip_cap,
            enable_veterinary_penalty=rerank_cfg.enable_veterinary_penalty,
        )

    def run(self, queries: List[str]) -> List[List[Dict[str, Any]]]:
        sc = self.search_cfg
        # 1) 召回
        hits_per_q = self.searcher.search_years(
            inputs=queries,
            years=sc.years,
            top_k=sc.recall_top_k,
            input_type=sc.input_type,
            search_params_hot=sc.search_params_hot,
            search_params_cold=sc.search_params_cold,
        )

        all_results: List[List[Dict[str, Any]]] = []
        for qi, hits in enumerate(hits_per_q):
            if not hits:
                all_results.append([])
                continue

            # 2) 合并去重（同 pmid 取最高向量分）
            best: Dict[str, Dict[str, Any]] = {}
            for h in hits:
                p = str(h["pmid"])
                if p not in best or h["score"] > best[p]["score"]:
                    best[p] = h
            dedup_hits = list(best.values())

            # 3) 拉详情
            pmids = [h["pmid"] for h in dedup_hits]
            pmid2item = self.fetcher.fetch_batch(pmids)

            # 4) 取 publication types
            pmid2types: Dict[str, List[str]] = {p: pmid2item.get(p, {}).get("pub_types", []) for p in pmids}

            # 5) 可选 CE
            ce_scores: Optional[Dict[str, float]] = None
            if self.reranker.use_ce and getattr(self.encoder, "cross_encoder", None) is not None:
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

            # 6) 重排
            reranked = self.reranker.rerank(dedup_hits, pmid2types=pmid2types, ce_scores=ce_scores)

            # 7) 富集输出
            enriched: List[Dict[str, Any]] = []
            for r in reranked[:sc.final_top_k]:
                p = r["pmid"]
                meta = pmid2item.get(p, {})
                item = dict(r)
                item.update({
                    "title":   meta.get("title"),
                    "abstract":meta.get("abstract"),
                    "journal": meta.get("journal"),
                    "authors": meta.get("authors") or meta.get("author"),
                    "doi":     meta.get("doi"),
                    "url":     meta.get("url"),
                    "pub_types": meta.get("pub_types", []),
                })
                enriched.append(item)

            all_results.append(enriched)

        return all_results

# ===============================
# 工厂
# ===============================
def build_pubmed_pipeline(
    encoder: MedCPTEncoder,
    searcher: PubMedVectorSearch,
    *,
    years: Iterable[int],
    recall_top_k: int = 100,
    final_top_k: int = 20,
    fetch_base_url: str = "http://10.1.0.7:7000/api/v1/items/pubmed/",
    use_post_json: bool = False,
    pubtype_yaml: Optional[str] = None,
    pubtype_boost: Optional[Dict[str, float]] = None,
    alias_file: Optional[str] = None,
    pubtype_alias: Optional[Dict[str, str]] = None,
    type_agg: str = "max",
    year_tau: float = 9.0,
    year_clip: Tuple[float,float] = (0.6, 1.6),
    use_ce: bool = True,
    ce_gamma: float = 0.35,
    mix_mode: str = "mul",
) -> PubMedSearchPipeline:

    fetch_cfg = FetchConfig(
        base_url=fetch_base_url,
        connect_timeout_s=5.0,
        read_timeout_s=20.0,
        max_ids_per_call=10,             # 强制小批量
        max_retries=2,
        backoff_base_s=0.5,
        degrade_to_single_on_fail=True,
        use_post_json=use_post_json,
        trust_env=False,
        disable_proxy=True,
    )
    fetcher = PubMedDetailFetcher(fetch_cfg)

    search_cfg = SearchConfig(
        years=list(years),
        recall_top_k=recall_top_k,
        final_top_k=final_top_k
    )
    rerank_cfg = RerankConfig(
        pubtype_yaml=pubtype_yaml,
        pubtype_boost=pubtype_boost,
        alias_file=alias_file,
        pubtype_alias=pubtype_alias,
        type_agg=type_agg,
        year_tau=year_tau,
        year_clip=year_clip,
        use_ce=use_ce,
        ce_gamma=ce_gamma,
        mix_mode=mix_mode,
    )
    return PubMedSearchPipeline(
        encoder=encoder,
        vector_searcher=searcher,
        detail_fetcher=fetcher,
        search_cfg=search_cfg,
        rerank_cfg=rerank_cfg,
    )

# ===============================
# 隧道辅助（可选）
# ===============================
def wait_port(host: str, port: int, timeout: float = 5.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.05)
    return False

# ===============================
# 示例
# ===============================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 1) 模型与向量检索
    enc = MedCPTEncoder(
        query_encoder_path="noah_agent/utils/pubmed_opt/models/MedCPT-Query-Encoder",
        article_encoder_path="noah_agent/utils/pubmed_opt/models/MedCPT-Article-Encoder",
        #cross_encoder_path="noah_agent/utils/pubmed_opt/models/MedCPT-Cross-Encoder",
    )
    searcher = PubMedVectorSearch(encoder=enc)

    # 2) （可选）本地已手工开好 ssh -L 127.0.0.1:7001:10.1.0.7:7000
    #    若未开，请先在另一个终端手工开隧道；这里直接用本地转发端口：
    base_url = "http://127.0.0.1:7001/api/v1/items/pubmed/"
    assert wait_port("127.0.0.1", 7001, 5.0), "Local forward 127.0.0.1:7001 not listening"

    # 最小闭环探活（两条）
    try:
        probe = requests.get(base_url, params=[("id","37477875"),("id","40156348")], timeout=10)
        log.info(f"[probe] status={probe.status_code} server={probe.headers.get('server')} len={len(probe.content)}")
        js = probe.json()
        first = (js.get("results") or [{}])[0]
        log.info(f"[probe] sample: pmid={first.get('pmid')} pub_types={first.get('publication_type') or first.get('pub_types')}")
    except Exception as e:
        log.warning(f"[probe] failed: {e}")

    # 3) 组装 pipeline
    pipe = build_pubmed_pipeline(
        encoder=enc,
        searcher=searcher,
        years=[2024, 2025],
        recall_top_k=120,
        final_top_k=20,
        fetch_base_url=base_url,               # 走本地转发
        use_post_json=False,                   # 若后端已支持 POST，改成 True
        pubtype_yaml="noah_agent/utils/pubmed_opt/config/pubtype_boost.yaml",
        alias_file="noah_agent/utils/pubmed_opt/config/pubtype_alias.yaml",
        use_ce=True,
        ce_gamma=0.35,
        type_agg="max",
    )

    # 4) 运行
    queries = ["RSV bivalent prefusion F vaccine SCB-1019T vs Arexvy safety and immunogenicity in older adults"]
    results = pipe.run(queries)

    # 5) 打印
    for i, hits in enumerate(results):
        print(f"\nQuery #{i}: {queries[i]}")
        for rank, h in enumerate(hits, 1):
            print(f"{rank:02d}. pmid={h.get('pmid')} year={h.get('year')} "
                  f"final={h.get('final_score',0):.4f} type_boost={h.get('type_boost',0):.2f} "
                  f"pub_types={h.get('pub_types')} title={h.get('title')!r}")