# -*- coding: utf-8 -*-
"""
NSFC 申请书 Markdown 在导出 Word 时依赖固定的 ## / ### 等标题与模板锚点匹配。
编辑 Agent 改写时若改动这些标题会导致导出失败。本模块在送入模型前用占位符替换标题行，
选区含标题时：正文进模型、规范标题在服务端拼接，锚点不依赖模型。选区无标题时仍用占位符处理上下文。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

# 与 nsfc_docx_exporter.NSFCDocxExporter._normalize_title 保持一致，用于标题对齐
def _normalize_title(title: str) -> str:
    if not title:
        return ""
    s = str(title)
    s = re.sub(r"\s+", "", s)
    s = re.sub(
        r"[（(][^）)]*[\u4e00-\u9fa5]{2,}[^（(]*[）)]",
        "",
        s,
    )
    s = re.sub(
        r"^[（(]?[一二三四五六七八九十0-9]+[)）\.．、]",
        "",
        s,
    )
    s = s.rstrip("。；：、.;；")
    return s


def _heading_body_key(body: str) -> str:
    b = (body or "").strip()
    b = b.replace("．", ".").replace("：", ":")
    # _normalize_title 的 rstrip 不含 ASCII ':'，面上模板章节带「：」时需与用户无冒号写法对齐
    return _normalize_title(b).rstrip(":：")


def _build_canonical_heading_lines(fund_type: str) -> List[str]:
    colon = "：" if fund_type == "面上项目" else ""
    out: List[str] = []
    out.extend(
        [
            f"## （一）立项依据{colon}",
            f"## （二）研究内容{colon}",
            f"## （三）研究基础{colon}",
            f"## （四）其他需要说明的情况{colon}",
            "### 1. 项目的研究内容、研究目标，以及拟解决的关键科学问题；",
            "### 2. 拟采取的研究方案（包括研究方法、技术路线、实验手段、关键技术等说明）；",
            "### 3. 本项目的特色与创新之处；",
            "### 4. 年度研究计划及预期研究结果（包括拟组织的重要学术交流活动、国际合作与交流计划等）。",
            "### 1．研究基础与可行性分析（与本项目相关的研究工作积累和已取得的研究工作成绩，研究风险的应对措施等）；",
            "### 2．工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；",
        ]
    )
    if fund_type == "面上项目":
        out.append(
            "### 3. 正在承担的与本项目相关的科研项目情况（申请人和主要参与者正在承担与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；"
        )
    else:
        out.append(
            "### 3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；"
        )
    out.append(
        "### 4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。"
    )
    out.extend(
        [
            "### 参考文献",
        ]
    )
    return out


def _canonical_lookup(fund_type: str) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for line in _build_canonical_heading_lines(fund_type):
        m = re.match(r"^(#{2,3})\s+(.+)$", line.strip())
        if not m:
            continue
        key = _heading_body_key(m.group(2))
        if key:
            lookup[key] = line.strip()
    return lookup


# Word 导出锚点只依赖二、三级标题（## / ###）
_HEADING_LINE_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_PLACEHOLDER_FMT = "⟦NSFC_H{idx}⟧"


def mask_nsfc_markdown_headings(
    text: str,
    fund_type: str,
    canonical_by_key: Dict[str, str],
    index_by_resolved: Dict[str, int],
    preserved: List[str],
) -> str:
    if not text:
        return text

    lines = text.split("\n")
    out: List[str] = []

    for line in lines:
        stripped = line.strip()
        m = _HEADING_LINE_RE.match(stripped)
        if not m:
            out.append(line)
            continue
        hashes, body = m.group(1), m.group(2)
        key = _heading_body_key(body)
        resolved = canonical_by_key.get(key) if key else None
        if resolved is None:
            resolved = f"{hashes} {body.strip()}"

        if resolved not in index_by_resolved:
            index_by_resolved[resolved] = len(preserved)
            preserved.append(resolved)
        idx = index_by_resolved[resolved]
        placeholder = _PLACEHOLDER_FMT.format(idx=idx)
        out.append(line.replace(stripped, placeholder, 1))

    return "\n".join(out)


def apply_nsfc_heading_masks(
    paragraph: str,
    selected_words: str,
    fund_type: str,
) -> Tuple[str, str, List[str]]:
    """
    对段落与选区中 Markdown 二、三级标题（## / ###）做占位符替换。
    返回 (masked_paragraph, masked_selected, preserved_lines)。
    """
    canonical_by_key = _canonical_lookup(fund_type)
    index_by_resolved: Dict[str, int] = {}
    preserved: List[str] = []

    p_masked = mask_nsfc_markdown_headings(
        paragraph, fund_type, canonical_by_key, index_by_resolved, preserved
    )
    s_masked = mask_nsfc_markdown_headings(
        selected_words, fund_type, canonical_by_key, index_by_resolved, preserved
    )
    return p_masked, s_masked, preserved


def unmask_nsfc_placeholders(text: str, preserved: List[str]) -> str:
    if not preserved or not text:
        return text
    out = text
    for i, line in enumerate(preserved):
        out = out.replace(_PLACEHOLDER_FMT.format(idx=i), line)
    return out


SegmentKind = Literal["h", "b"]


def _resolve_heading_line(line: str, fund_type: str, canonical_by_key: Dict[str, str]) -> str:
    stripped = line.strip()
    m = _HEADING_LINE_RE.match(stripped)
    if not m:
        return stripped
    hashes, body = m.group(1), m.group(2)
    key = _heading_body_key(body)
    resolved = canonical_by_key.get(key) if key else None
    if resolved is None:
        resolved = f"{hashes} {body.strip()}"
    prefix = line[: len(line) - len(stripped)] if stripped else ""
    return prefix + resolved


def parse_nsfc_selection_segments(
    selected_words: str, fund_type: str
) -> Optional[List[Tuple[SegmentKind, str]]]:
    """
    若选区内至少有一行 ## / ### 标题，返回交替片段 [('h', 规范标题块), ('b', 正文), ...]；
    否则返回 None（选区纯正文，走占位符策略即可）。
    """
    if not (selected_words or "").strip():
        return None
    lines = selected_words.split("\n")
    has_heading = any(
        _HEADING_LINE_RE.match(ln.strip()) for ln in lines if ln.strip()
    )
    if not has_heading:
        return None

    canonical_by_key = _canonical_lookup(fund_type)
    segments: List[Tuple[SegmentKind, str]] = []
    i = 0
    n = len(lines)

    while i < n:
        stripped = lines[i].strip()
        if _HEADING_LINE_RE.match(stripped):
            h_start = i
            while i < n:
                s2 = lines[i].strip()
                if not s2 or not _HEADING_LINE_RE.match(s2):
                    break
                i += 1
            canon_h = "\n".join(
                _resolve_heading_line(lines[j], fund_type, canonical_by_key)
                for j in range(h_start, i)
            ).strip("\n")
            segments.append(("h", canon_h))
            continue

        b_start = i
        while i < n:
            s2 = lines[i].strip()
            if s2 and _HEADING_LINE_RE.match(s2):
                break
            i += 1
        raw_b = "\n".join(lines[b_start:i]).strip("\n")
        segments.append(("b", raw_b))

    return segments


def build_body_only_prompt_and_originals(
    segments: List[Tuple[SegmentKind, str]],
) -> Tuple[str, List[str]]:
    """从片段构造仅含正文的模型输入；返回 (prompt, original_bodies)。"""
    bodies = [t for k, t in segments if k == "b"]
    if not bodies:
        return "", []
    return "\n\n".join(bodies), bodies


def stitch_nsfc_segments(
    segments: List[Tuple[SegmentKind, str]],
    new_bodies: List[str],
    original_bodies: List[str],
) -> str:
    """用 new_bodies 替换各正文段；若某段缺失则用 original 兜底，**标题段始终用 segments 中的规范串**。"""
    bi = 0
    out: List[str] = []
    obi = 0
    for kind, text in segments:
        if kind == "h":
            out.append(text)
            continue
        if bi < len(new_bodies):
            chunk = new_bodies[bi]
        else:
            chunk = original_bodies[obi] if obi < len(original_bodies) else text
        out.append(chunk)
        bi += 1
        obi += 1
    return "\n\n".join(out)


def strip_markdown_heading_lines_from_body(text: str) -> str:
    """去掉正文块中误生成的 ## / ### 标题行。"""
    if not text:
        return text
    lines = text.split("\n")
    kept = [ln for ln in lines if not _HEADING_LINE_RE.match(ln.strip())]
    return "\n".join(kept).strip("\n")


@dataclass
class NSFCEditingPlan:
    """NSFC 标题保护执行计划。"""

    mode: Literal["body_split", "placeholder_mask"]
    fund_type: str
    paragraph_for_prompt: str
    selected_for_prompt: str
    # body_split 专用
    segments: Optional[List[Tuple[SegmentKind, str]]] = None
    original_bodies: Optional[List[str]] = None
    # placeholder 专用
    preserved_headings: Optional[List[str]] = None


def prepare_nsfc_editing(
    paragraph: str,
    selected_words: str,
    fund_type: str,
) -> NSFCEditingPlan:
    paragraph = paragraph or ""
    selected_words = selected_words or ""
    seg = parse_nsfc_selection_segments(selected_words, fund_type)
    if seg is not None:
        bodies = [t for k, t in seg if k == "b"]
        body_prompt, originals = build_body_only_prompt_and_originals(seg)
        p_masked, _, _ = apply_nsfc_heading_masks(paragraph, "", fund_type)
        return NSFCEditingPlan(
            mode="body_split",
            fund_type=fund_type,
            paragraph_for_prompt=p_masked,
            selected_for_prompt=body_prompt,
            segments=seg,
            original_bodies=originals,
        )
    p_masked, s_masked, preserved = apply_nsfc_heading_masks(
        paragraph, selected_words, fund_type
    )
    return NSFCEditingPlan(
        mode="placeholder_mask",
        fund_type=fund_type,
        paragraph_for_prompt=p_masked,
        selected_for_prompt=s_masked,
        preserved_headings=preserved,
    )


def should_apply_nsfc_heading_preservation(params: dict) -> Optional[str]:
    params = params or {}
    return str(
        params.get("fund_type")
        or params.get("nsfc_fund_type")
        or "青年科学基金项目"
    )
