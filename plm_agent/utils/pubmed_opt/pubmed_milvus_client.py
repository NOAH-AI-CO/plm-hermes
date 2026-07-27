# -*- coding: utf-8 -*-
import time
import re
import logging
from typing import Optional, List, Iterable, Deque, Set

from collections import deque
from pymilvus import Collection

from config import settings
from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch
from utils.core.milvus_client import MilvusClientSingleton

log = logging.getLogger(__name__)


class PubMedMilvusManager:
    """
    Connect Milvus, bind collections, load/release partitions by year or name.
    """
    def __init__(self, alias: str = "PubMed", lru_cap: Optional[int] = None) -> None:
        """
        lru_cap: Optional[int], LRU cache capacity for loaded partitions; None or 0 means no limit.
        """
        self.alias = alias
        
        # LRU 记录（仅记录“已加载过且常驻”的分区名）
        self._hot_lru: Optional[Deque[str]] = deque(maxlen=lru_cap) if lru_cap else None
        self._cold_lru: Optional[Deque[str]] = deque(maxlen=lru_cap) if lru_cap else None

        self.pubmed_hot_collection: Optional[Collection] = MilvusClientSingleton.get_collection(PubMedVectorSearch.PUBMED_HOT)
        self.pubmed_cold_collection: Optional[Collection] = MilvusClientSingleton.get_collection(PubMedVectorSearch.PUBMED_COLD)

    # ---- 工具 ----
    @staticmethod
    def _wait_loaded(coll: Collection, timeout_s: int) -> None:
        deadline = time.time() + max(1, timeout_s)
        while time.time() < deadline:
            try:
                p = coll.get_loading_progress()
                loaded = int(p.get("num_loaded_partitions", 0))
                total  = int(p.get("total_partitions", 0))
                if total == 0 or loaded >= total:
                    return
            except Exception:
                time.sleep(0.15)
                return
            time.sleep(0.15)

    @staticmethod
    def _existing_parts(coll: Collection) -> List[str]:
        try:
            return [p.name for p in coll.partitions]
        except Exception:
            return []

    @staticmethod
    def year_parts(years: Iterable[int]) -> List[str]:
        return [f"y_{int(y)}" for y in years]

    # ---- 按分区加载/释放（不做全量加载）----
    def ensure_load_parts(self, coll: Collection, parts: Iterable[str], timeout_s: int = 30) -> List[str]:
        parts = list(parts)
        exist = set(self._existing_parts(coll))
        use = [p for p in parts if p in exist]
        if not use:
            return []
        coll.load(partition_names=use)
        self._wait_loaded(coll, timeout_s)
        return use

    def ensure_load_years(self, coll: Collection, years: Iterable[int], timeout_s: int = 30) -> List[str]:
        return self.ensure_load_parts(coll, self.year_parts(years), timeout_s)

    def release_parts(self, coll: Collection, parts: Iterable[str]) -> None:
        parts = list(parts)
        if not parts:
            return
        try:
            coll.release(partition_names=parts)
        except Exception:
            # 某些版本不支持按分区释放；可退化为不处理或 coll.release()
            pass

    def release_except(self, coll: Collection, keep_parts: Iterable[str]) -> None:
        keep = set(keep_parts)
        exist = self._existing_parts(coll)
        drop = [p for p in exist if p not in keep]
        self.release_parts(coll, drop)

    # ---- 由“用户/调用方”显式选择加载什么 ----
    def load_years_hot(self, years: Iterable[int], timeout_s: int = 30) -> List[str]:
        assert self.pubmed_hot_collection is not None
        parts = self._resolve_partitions_by_years(self.pubmed_hot_collection, years)
        used = self.ensure_load_parts(self.pubmed_hot_collection, parts, timeout_s)
        self._record_lru(self._hot_lru, self.pubmed_hot_collection, used)
        return used

    def load_years_cold(self, years: Iterable[int], timeout_s: int = 30) -> List[str]:
        assert self.pubmed_cold_collection is not None
        parts = self._resolve_partitions_by_years(self.pubmed_cold_collection, years)
        used = self.ensure_load_parts(self.pubmed_cold_collection, parts, timeout_s)
        self._record_lru(self._cold_lru, self.pubmed_cold_collection, used)
        return used
    
    def load_parts_hot(self, parts: Iterable[str], timeout_s: int = 30) -> List[str]:
        assert self.pubmed_hot_collection is not None
        used = self.ensure_load_parts(self.pubmed_hot_collection, parts, timeout_s)
        self._record_lru(self._hot_lru, self.pubmed_hot_collection, used)
        return used

    def load_parts_cold(self, parts: Iterable[str], timeout_s: int = 30) -> List[str]:
        assert self.pubmed_cold_collection is not None
        used = self.ensure_load_parts(self.pubmed_cold_collection, parts, timeout_s)
        self._record_lru(self._cold_lru, self.pubmed_cold_collection, used)
        return used

    @staticmethod
    def _resolve_partitions_by_years(coll: Collection, years: Iterable[int], include_unknown: bool = False) -> List[str]:
        """
        将年份列表映射为实际存在的分区名。
        支持分区命名：
          - y_YYYY
          - y_YYYY_YYYY
          - y_le_YYYY
          - y_unknown（仅 include_unknown=True 时包含）
        """
        try:
            names = [p.name for p in coll.partitions]
        except Exception:
            names = []

        intervals = []  # [(name, lo, hi)]  lo/hi 为 int，或 (None, None) 表示 unknown
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
                    # y_unknown：仅在 include_unknown=True 时才纳入，这里已经过滤过
                    continue
                if lo <= yi <= hi:
                    want.add(name)
        return sorted(want)

    # ---- 可选 LRU：限制常驻分区个数并淘汰旧分区 ----
    def _record_lru(self, lru: Optional[Deque[str]], coll: Collection, new_parts: List[str]) -> None:
        if not lru or not new_parts:
            return
        # 先把新分区加入 LRU
        for p in new_parts:
            try:
                # 去重移动到末尾
                if p in lru:
                    lru.remove(p)
                lru.append(p)
            except ValueError:
                pass
        # 如果超过容量，淘汰超额分区
        overflow = len(lru) - lru.maxlen
        if overflow > 0:
            drop = list(lru)[:-lru.maxlen]
            try:
                coll.release(partition_names=drop)
            except Exception:
                pass
            # 保留最近的 maxlen 个
            while len(lru) > lru.maxlen:
                lru.popleft()

    # ---- 观测 ----
    @staticmethod
    def loaded_partitions(coll: Collection) -> List[str]:
        # 无官方“已加载列表”的 API，这里返回当前存在的分区名（近似）
        return PubMedMilvusManager._existing_parts(coll)

    def health(self) -> dict:
        return {
            "milvus_connected": True,
            "hot": settings.PUBMED_MILVUS_HOT_COLLECTION if self.pubmed_hot_collection else None,
            "cold": settings.PUBMED_MILVUS_COLD_COLLECTION if self.pubmed_cold_collection else None,
        }
    