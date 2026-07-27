# -*- coding: utf-8 -*-
"""
仅使用 Elasticsearch BM25（bm25_search_simple）的 PubMed 检索，不调用向量/Milvus，不做 rerank。
"""
import logging
import time
from typing import Any, Dict, List, Optional

from utils.pubmed_opt.pubmed_elastic_search import PubMedElasticSearch

logger = logging.getLogger(__name__)


def _format_pubmed_hits(response: List[Dict]) -> List[Dict]:
    """与 PubMedSearch._formatter 一致：将 ES 文档转为 Entrez 风格结构。"""

    def _safe_str(value: Any) -> str:
        return "" if value is None else str(value)

    final_results = []
    for item in response:
        articleid_key = [("pmc_id", "pmcid"), ("doi", "DOI")]
        articleids = []
        for key in articleid_key:
            articleids.append({"idtype": key[1], "value": _safe_str(item.get(key[0]))})
        authors = [
            {"name": _safe_str(author)}
            for author in item.get("author", [])
            if author is not None
        ]

        final_results.append(
            {
                "title": _safe_str(item.get("title")),
                "summary": _safe_str(item.get("abstract")),
                "uid": _safe_str(item.get("pmid")),
                "pmid": _safe_str(item.get("pmid")),
                "articleids": articleids,
                "authors": authors,
                "issn": _safe_str(item.get("issn")),
                "essn": _safe_str(item.get("essn")),
                "fulljournalname": _safe_str(item.get("journal")),
                "nlmuniqueid": _safe_str(item.get("nlmuniqueid")),
                "pubdate": _safe_str(item.get("pubmed_pub_date")),
                "journal_abbr": _safe_str(item.get("journal_abbr")),
                "year_of_publication": _safe_str(item.get("year_of_publication")),
                "volume": _safe_str(item.get("volume")),
                "issue": _safe_str(item.get("issue")),
                "pagination": _safe_str(item.get("pagination")),
            }
        )

    return final_results


def _resolve_from_index(
    size: int,
    page: Optional[int],
    offset: Optional[int],
    from_kw: Optional[Any],
) -> int:
    """分页偏移：page（1 起）> offset > ES from > 0。"""
    if page is not None:
        p = max(1, int(page))
        return max(0, (p - 1) * size)
    if offset is not None:
        return max(0, int(offset))
    if from_kw is not None:
        return max(0, int(from_kw))
    return 0


class PubMedEsOnlySearch:
    """PubMed 检索：底层仅使用 Elasticsearch bm25_search_simple（无 rerank）。"""

    def __init__(self) -> None:
        self._es_search: Optional[PubMedElasticSearch] = None

    @property
    def es_search(self) -> PubMedElasticSearch:
        if self._es_search is None:
            self._es_search = PubMedElasticSearch()
        return self._es_search

    async def search(
        self,
        query: str,
        input_type: str = "query",
        years: Optional[List[int]] = None,
        size: int = 20,
        page: Optional[int] = None,
        offset: Optional[int] = None,
        is_sort_by_date: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        纯 ES 检索（bm25_search_simple，无 rerank）。

        :param query: 查询字符串
        :param input_type: 与 hybrid 对齐；本路径不使用
        :param years: 出版年份过滤（默认不过滤）
        :param size: 每页条数
        :param page: 1 起始页码；与 offset / kwargs['from'] 互斥，优先级：page > offset > from
        :param offset: 跳过前多少条（与 page 二选一优先用 page）
        :param kwargs: 其余透传 bm25_search_simple；可用 ``**{'from': n}`` 传 ES 偏移（keyword 名 from）
        :return: ``results``, ``total``, ``from``, ``size``, ``page``（当前页，1 起）
        """
        if years is None:
            years = []

        es_extra = dict(kwargs)
        from_kw = es_extra.pop("from", None)
        from_index = _resolve_from_index(size, page, offset, from_kw)

        start_time = time.time()
        try:
            datalist, total_count, _ = await self.es_search.bm25_search_simple(
                query=query,
                years=years,
                size=size,
                is_sort_by_date=is_sort_by_date,
                **es_extra,
                **{"from": from_index},
            )
        except Exception as e:
            logger.warning("ES-only search failed: %s", e)
            datalist, total_count = [], 0

        current_page = (from_index // size + 1) if size > 0 else 1
        logger.info(
            "es_only search: hits=%d total=%d from=%d cost=%.3fs",
            len(datalist),
            total_count,
            from_index,
            time.time() - start_time,
        )

        return {
            "results": _format_pubmed_hits(datalist),
            "total": total_count,
            "from": from_index,
            "size": size,
            "page": current_page,
        }


async def es_only_search(
    query: str,
    input_type: str = "query",
    years: Optional[List[int]] = None,
    size: int = 20,
    page: Optional[int] = None,
    offset: Optional[int] = None,
    is_sort_by_date: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    便捷函数：``bm25_search_simple`` + 格式化 + 分页元数据。

    返回字段：``results``, ``total``, ``from``, ``size``, ``page``。
    """
    searcher = PubMedEsOnlySearch()
    return await searcher.search(
        query=query,
        input_type=input_type,
        years=years if years is not None else [],
        size=size,
        page=page,
        offset=offset,
        is_sort_by_date=is_sort_by_date,
        **kwargs,
    )


if __name__ == "__main__":
    import asyncio

    async def _demo() -> None:
        s = PubMedEsOnlySearch()
        out = await s.search("headache", years=[2024], size=5, page=1)
        print(out["total"], len(out["results"]), out["page"])

    asyncio.run(_demo())
