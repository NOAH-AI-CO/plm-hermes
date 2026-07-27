# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import math, time, yaml
from pathlib import Path

class PubMedReranker:
    """
    重排：融合 召回分(向量/CE) + PublicationType 权重 + 年份半衰权重
    关键可调：gamma(CE占比)、year_tau、年份权重上下限、类型聚合策略、并列打破键
    用法：
        reranker = PubMedReranker(
            pubtype_yaml="pubtype_boost.yaml",      # 或传入 pubtype_boost=dict(...)
            alias_file="pubtype_alias.yaml",        # 或传入 pubtype_alias=dict(...)
            type_agg="max",                         # "max" | "mean" | "sum_clip"
            year_tau=9.0, year_clip=(0.6, 1.6),
            use_ce=True, ce_gamma=0.35,
            mix_mode="mul",                         # "mul" or "add"
            filter_retracted=True,
        )
        results = reranker.rerank(hits, pmid2types, ce_scores)
    """

    def __init__(
        self,
        pubtype_boost: Optional[Dict[str, float]] = None,
        pubtype_yaml: Optional[str] = None,              # 从 yaml 载入权重
        pubtype_alias: Optional[Dict[str, str]] = None,  # 别名字典（左原始->右标准）
        type_agg: str = "max",                           # "max" | "mean" | "sum_clip"
        default_boost: float = 1.0,

        # 年份权重（半衰：越旧越小）
        year_tau: float = 9.0,                           # 年份“半衰尺度”
        year_clip: Tuple[float, float] = (0.6, 1.6),     # 年份权重上下限

        # 相关性融合
        use_ce: bool = True,
        ce_gamma: float = 0.35,                          # CE 分数占比 [0,1]

        # 打分融合模式
        mix_mode: str = "mul",                           # "mul" 或 "add"
        add_alpha: float = 1.0,
        add_beta: float = 0.15,

        # 过滤控制
        filter_retracted: bool = True,

        # 并列打破顺序
        tie_break_by: Tuple[str, ...] = ("final_score", "is_high_evidence", "year", "rel_vec"),

        # 配置文件路径（可选）
        alias_file: Optional[str] = None,

        # 可选策略开关
        enable_veterinary_penalty: bool = True,
        veterinary_types: Optional[set] = None,          # 自定义兽医标签集合
        year_exempt_types: Optional[set] = None,         # 年份豁免类型（指南/共识）
        year_floor: float = 0.9,                         # 豁免时年份权重下限
        sum_clip_cap: Optional[float] = None,            # sum_clip 上限（默认取权重表最大值或2.4）
    ):
        # ---- 基础参数
        self.default_boost = float(default_boost)
        self.year_tau = float(year_tau)
        self.year_clip = tuple(year_clip)
        self.use_ce = bool(use_ce)
        self.ce_gamma = max(0.0, min(1.0, float(ce_gamma)))  # clamp [0,1]
        self.mix_mode = str(mix_mode)
        self.add_alpha = float(add_alpha)
        self.add_beta = float(add_beta)
        self.filter_retracted = bool(filter_retracted)
        self.type_agg = type_agg
        self.tie_break_by = tuple(tie_break_by)
        self.year_floor = float(year_floor)
        self.enable_veterinary_penalty = bool(enable_veterinary_penalty)
        self.sum_clip_cap = sum_clip_cap

        # ---- 加载权重（dict 覆盖 yaml）
        weights: Dict[str, float] = {}
        if pubtype_yaml:
            weights.update(self._load_yaml_as_float_map(pubtype_yaml))
        if pubtype_boost:
            weights.update({str(k): float(v) for k, v in pubtype_boost.items()})
        self.pubtype_boost: Dict[str, float] = weights or {}

        # ---- 加载/合并 alias（file + dict），并规范 key 大小写
        alias_from_file: Dict[str, str] = {}
        if alias_file:
            with open(alias_file, "r", encoding="utf-8") as f:
                alias_from_file = yaml.safe_load(f) or {}
        alias_from_arg = pubtype_alias or {}
        self.pubtype_alias: Dict[str, str] = self._prepare_alias({**alias_from_file, **alias_from_arg})

        # ---- 高证据集合（用于 is_high_evidence）
        self.high_evidence = {
            "Systematic Review", "Meta-Analysis", "Network Meta-Analysis",
            "Randomized Controlled Trial", "Clinical Trial, Phase III"
        }

        # ---- 撤稿强过滤集合
        self.hard_exclude = {"Retracted Publication", "Retraction Notice"}

        # ---- 年份豁免集合
        self.year_exempt = year_exempt_types or {"Practice Guideline", "Guideline"}

        # ---- 兽医集合
        self.veterinary = veterinary_types or {
            "Randomized Controlled Trial, Veterinary",
            "Clinical Trial, Veterinary",
            "Observational Study, Veterinary",
        }

    # ====================== 主流程 ======================
    def rerank(
        self,
        hits: List[Dict[str, Any]],
        pmid2types: Dict[str, List[str]],
        ce_scores: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        if not hits:
            return []

        # 1) 归一化相关性：向量分 与 CE 分
        vec_scores = [float(h.get("score", 0.0)) for h in hits]
        rel_vec = self._minmax(vec_scores)
        if self.use_ce and ce_scores:
            ce_vec = [float(ce_scores.get(str(h.get("pmid","")), 0.0)) for h in hits]
            rel_ce = self._minmax(ce_vec)
        else:
            rel_ce = [0.5]*len(hits)

        rel = [(1.0 - self.ce_gamma)*v + self.ce_gamma*c for v, c in zip(rel_vec, rel_ce)]

        # 2) 规则权重
        now_year = time.gmtime().tm_year
        out: List[Dict[str, Any]] = []
        for h, r in zip(hits, rel):
            p = str(h.get("pmid", ""))
            y = self._safe_int(h.get("year"))
            types_raw = pmid2types.get(p, []) or []
            types = self._normalize_types(types_raw)

            # 撤稿强过滤
            if self.filter_retracted and any(t in self.hard_exclude for t in types):
                continue

            # 年份权重（指南等可豁免/抬低下限）
            w_year = self._year_weight(y, now_year, types)

            # 类型权重（含多标签聚合与兽医降权）
            w_type = self._type_weight(types)

            # 融合
            final = self._mix(r, w_type, w_year)

            hh = dict(h)
            hh.update({
                "pub_types": types,
                "type_boost": w_type,
                "year_boost": w_year,
                "rel_vec": r,
                "final_score": final,
                "is_high_evidence": 1 if self._is_high_evidence(types) else 0,
            })
            out.append(hh)

        # 3) 排序 + 并列打破（tie-break）
        out.sort(key=self._sort_key)
        return out

    # ====================== 细节函数 ======================
    def _type_weight(self, types: List[str]) -> float:
        if not types:
            return self.default_boost

        # 兽医强降权（如果开启）
        if self.enable_veterinary_penalty and any(t in self.veterinary for t in types):
            # 直接返回兽医标签中的最低权，或固定低权
            vet_vals = [self.pubtype_boost.get(t, 0.6) for t in types if t in self.veterinary]
            return min(vet_vals) if vet_vals else 0.6

        vals = [self.pubtype_boost.get(t, self.default_boost) for t in types]
        if self.type_agg == "max":
            return max(vals)
        if self.type_agg == "mean":
            return sum(vals) / len(vals)

        # sum_clip
        s = sum(vals)
        cap = self.sum_clip_cap
        if cap is None:
            cap = max(2.4, max(self.pubtype_boost.values() or [2.4]))
        return min(s, cap)

    def _year_weight(self, year: Optional[int], now_year: int, types: Optional[List[str]] = None) -> float:
        if not year or year < 1800 or year > now_year + 1:
            return 1.0
        raw = math.exp(-(now_year - year) / max(1e-6, self.year_tau))
        lo, hi = self.year_clip
        # 指南/共识等：抬高年份下限，避免因年份过旧而被过度打压
        if types and any(t in self.year_exempt for t in types):
            lo = max(lo, self.year_floor)
        return max(lo, min(hi, raw))

    def _mix(self, rel: float, w_type: float, w_year: float) -> float:
        if self.mix_mode == "mul":
            return rel * w_type * w_year
        rule = 0.5 * (w_type + w_year)
        return self.add_alpha * rel + self.add_beta * rule

    # -------- 排序键（并列打破） --------
    def _sort_key(self, x: Dict[str, Any]) -> tuple:
        key = []
        for k in self.tie_break_by:
            if k == "final_score":
                key.append(-x.get("final_score", 0.0))
            elif k == "is_high_evidence":
                key.append(-x.get("is_high_evidence", 0))
            elif k == "year":
                y = x.get("year", 0)
                key.append(-(y if isinstance(y, int) else 0))
            elif k == "rel_vec":
                key.append(-x.get("rel_vec", 0.0))
            else:
                key.append(0)
        # 最后加 pmid 作为稳定兜底
        key.append(str(x.get("pmid", "")))
        return tuple(key)

    # -------- 别名标准化 --------
    def _norm_key(self, s: str) -> str:
        return " ".join(str(s).strip().lower().split())

    def _prepare_alias(self, alias: Dict[str, str]) -> Dict[str, str]:
        # 左键标准化，小写+规范空白；右值（标准key）保持原样
        return { self._norm_key(k): v for k, v in (alias or {}).items() }

    def _normalize_types(self, types: List[str]) -> List[str]:
        out = []
        for t in types or []:
            if not isinstance(t, str):
                continue
            raw = t.strip()
            if not raw:
                continue
            out.append(self.pubtype_alias.get(self._norm_key(raw), raw))
        return out

    # -------- 其他工具 --------
    def _is_high_evidence(self, types: List[str]) -> bool:
        return any(t in self.high_evidence for t in types or [])

    @staticmethod
    def _minmax(xs: List[float], eps=1e-8) -> List[float]:
        lo, hi = min(xs), max(xs)
        if hi - lo < eps:
            return [0.5]*len(xs)
        k = 1.0 / (hi - lo)
        return [(x - lo)*k for x in xs]

    @staticmethod
    def _safe_int(x) -> Optional[int]:
        try:
            return int(x)
        except Exception:
            return None

    @staticmethod
    def _load_yaml_as_float_map(path: str) -> Dict[str, float]:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"pubtype_weights.yaml not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        out: Dict[str, float] = {}
        for k, v in data.items():
            try:
                out[str(k)] = float(v)
            except Exception:
                # 非数值（比如注释或错误项）跳过
                continue
        return out

    # ============ 审计/调参辅助 ============
    def audit_boost_coverage(self, all_types_from_es: List[str]) -> List[Tuple[str, str, float]]:
        """
        检查：别名映射后的标准类型是否都在权重表中有配置。
        返回 [(原始类型, 标准类型, 使用权重)]，其中使用权重为 default 或命中权重。
        """
        misses: List[Tuple[str, str, float]] = []
        for raw in sorted(set(t for t in all_types_from_es if isinstance(t, str))):
            canon = self.pubtype_alias.get(self._norm_key(raw), raw.strip())
            w = self.pubtype_boost.get(canon, self.default_boost)
            if canon not in self.pubtype_boost:
                misses.append((raw, canon, w))
        return misses
