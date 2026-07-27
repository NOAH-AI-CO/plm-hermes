"""
Parse `[N]` citations + 文末"参考文献"块,产出结构化 citations 数据
供前端做"点击 [1] 弹出参考文献"绑定。

算法
====

不预先定义"什么是 section",而是反过来:
- 以每个"参考文献:"块为锚,自动产生一组 citations
- 该组的 section 名 = 该引用块**之前**最近的一个"标题样式"行;没有就空串

标题识别采用**分层信任**, 避免把正文小节误识别成 section:
  Tier 1 (强信号): ## / ### markdown 标题, "问题 N：xxx" (quick 模式必用)
  Tier 2 (中信号): 中文编号 "一、xxx" / "二、xxx"
  Tier 3 (弱信号): 数字编号 "1. xxx" / "2. xxx"

抽取规则: 优先用 Tier 1; 文档里完全没 Tier 1 才退回 Tier 1+2; 都没有才用全部三层。
这样 report 模式 (有 ## 标题) 不会被正文 "4. 体能状态评估" 抢标题,
quick 模式 (只有 "问题 N：") 走 Tier 1 同样能识别。

支持的标题样式
==============
- markdown ##/### 标题:           ## 一、权威指南共识
- "问题 N: xxx" (quick 模式):      问题 1：请问下一步应该做什么?
- 中文编号:                        一、xxx  二、xxx
- 裸数字编号:                       1. xxx  2. xxx

输出结构
========
    [
      {"section": "一、权威指南共识", "items": [{"id": 1, "label": "..."}, ...]},
      {"section": "问题 1：xxx",     "items": [{"id": 1, "label": "..."}, ...]},
    ]

加新 prompt 输出格式时只需要往 _TITLE_TIERS 里多加一行正则, 不用改算法。
citations 解析失败时返回 [] 而不是 raise (向后兼容)。
"""
from __future__ import annotations

import re
from typing import Any

# "参考文献:" / "参考文献：" / "**参考文献**:" / 单独一行"参考文献"
# DeepSeek / GLM 等常输出加粗 ** 包裹, 要兼容
_REF_HEADER_RE = re.compile(r"^\*{0,2}参考文献\*{0,2}\s*[:：]?\s*$", re.MULTILINE)
# 单条引用: 行首 [N] 后跟若干字符直到行尾 (或下一个 [N] / 双空行 / 下一个 ## 标题)
_REF_ITEM_RE = re.compile(r"^\[(\d+)\]\s+(.+?)(?=\n\[\d+\]|\n\n|\n##|\Z)", re.MULTILINE | re.DOTALL)


# 标题样式分层。每个 tier 是一组 (pattern, group_idx_for_title)。
# Tier 越靠前优先级越高 — 文档里有强信号时不用弱信号 (避免把正文"1. xxx"误识别)。
_TIER_1: list[re.Pattern[str]] = [
    # markdown ##/### 标题 (#一级标题在医学报告里几乎不用, 不识别避免误吃)
    re.compile(r"^#{2,3}\s+(?P<t>[^\n]{1,80})$", re.MULTILINE),
    # "问题 N：xxx" — quick 模式硬约定的标题
    re.compile(r"^(?P<t>问题\s*\d+\s*[：:]\s*[^\n]{1,80})$", re.MULTILINE),
]
_TIER_2: list[re.Pattern[str]] = [
    # 中文编号 "一、xxx" / "二、xxx"
    re.compile(r"^(?P<t>[一二三四五六七八九十]+、[^\n]{1,40})$", re.MULTILINE),
]
_TIER_3: list[re.Pattern[str]] = [
    # 裸数字编号 "1. xxx" / "2. xxx" 仅当上面都没有时才用
    re.compile(r"^(?P<t>\d+\.\s+[^\n]{1,40})$", re.MULTILINE),
]


def _find_titles_in_tier(markdown: str, patterns: list[re.Pattern[str]]) -> list[tuple[int, str]]:
    marks: list[tuple[int, str]] = []
    seen: set[int] = set()
    for pat in patterns:
        for m in pat.finditer(markdown):
            pos = m.start()
            if pos in seen:
                continue
            title = m.group("t").strip()
            if not title or title.startswith("参考文献"):
                continue
            seen.add(pos)
            marks.append((pos, title))
    return sorted(marks)


def _find_title_marks(markdown: str) -> list[tuple[int, str]]:
    """按分层信任找标题 — 高 tier 命中就不用低 tier。"""
    for tier in (_TIER_1, _TIER_1 + _TIER_2, _TIER_1 + _TIER_2 + _TIER_3):
        marks = _find_titles_in_tier(markdown, tier)
        if marks:
            return marks
    return []


def _find_ref_blocks(markdown: str) -> list[tuple[int, list[dict]]]:
    """找所有"参考文献:"块, 返回 [(header_pos, items), ...] 按位置升序。

    每块的 items = 该 header 之后到下一个 ref header (或 EOF) 之间的 `[N] xxx` 行。
    """
    headers = list(_REF_HEADER_RE.finditer(markdown))
    if not headers:
        return []
    result: list[tuple[int, list[dict]]] = []
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
        body = markdown[h.end():end]
        items: list[dict] = []
        seen: set[int] = set()
        for m in _REF_ITEM_RE.finditer(body):
            try:
                cid = int(m.group(1))
            except ValueError:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            label = m.group(2).strip().replace("\n", " ")
            items.append({"id": cid, "label": label})
        items.sort(key=lambda x: x["id"])
        if items:
            result.append((h.start(), items))
    return result


# 决策图谱类"伪引用"特征: 决策图谱本身不是可引用来源, 不应出现在参考文献里。
_GRAPH_REF_RE = re.compile(r"决策图谱|图谱命中|决策路径参考|doc_id")


def _is_graph_ref(label: str) -> bool:
    return bool(_GRAPH_REF_RE.search(label or ""))


def extract_citations(markdown: str) -> list[dict[str, Any]]:
    """markdown -> 结构化 citations。

    返回 [{section: str, items: [{id: int, label: str}]}, ...] 按出现顺序。
    没有任何 "参考文献:" 块 → 返回 []。
    某引用块上方没找到已知标题样式 → section = ""。
    """
    if not markdown or not isinstance(markdown, str):
        return []
    titles = _find_title_marks(markdown)
    blocks = _find_ref_blocks(markdown)
    if not blocks:
        return []
    result: list[dict[str, Any]] = []
    for ref_pos, items in blocks:
        section_title = ""
        for tpos, ttitle in reversed(titles):
            if tpos < ref_pos:
                section_title = ttitle
                break
        # 决策图谱不是可引用来源, 即使模型误把它写进参考文献也在此剔除,
        # 保证前端拿到的引用只有真实指南条目。
        items = [it for it in items if not _is_graph_ref(it.get("label", ""))]
        if items:
            result.append({"section": section_title, "items": items})
    return result
