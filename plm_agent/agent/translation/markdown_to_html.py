"""
Markdown → HTML 转换，供 PDF 贴块使用（insert_htmlbox 需要 HTML）。

处理：标题、粗体/斜体、链接、表格、代码块、换行；保留已有 HTML 如 <sup>/<sub>。
"""

from __future__ import annotations

import re
from html import escape


def _inline_md_to_html(s: str) -> str:
    """将单行或段落内的 Markdown 内联语法转为 HTML，保留已有 <sup>/<sub> 等。"""
    if not s:
        return s
    # 先做 ** 和 __（粗体），再做单 * 和单 _（斜体），避免把 ** 拆成两个 *
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    # 单 * 斜体：前后不能是 *
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", s)
    # 单 _ 斜体：前后不能是 _（避免破坏 __）
    s = re.sub(r"(?<!_)_(?!_)([^_]+?)(?<!_)_(?!_)", r"<i>\1</i>", s)
    # 链接 [text](url)
    s = re.sub(r"\[([^\]]+)\]\(([^\)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def _is_table_separator(line: str) -> bool:
    """是否为表格分隔行 |---|---|"""
    stripped = line.strip()
    return bool(re.match(r"^[\|\s\-:+]+$", stripped))


def _table_to_html(table_lines: list[str]) -> str:
    """将 Markdown 表格行转为 <table>...</table>。"""
    if len(table_lines) < 2:
        return _inline_md_to_html(table_lines[0] if table_lines else "") + "<br>"
    rows = []
    for line in table_lines:
        if _is_table_separator(line):
            continue
        cells = [c.strip() for c in line.split("|")]
        if cells and cells[0] == "" and cells[-1] == "":
            cells = cells[1:-1]
        if not cells:
            continue
        cell_html = "".join(f"<td>{_inline_md_to_html(c)}</td>" for c in cells)
        rows.append(f"<tr>{cell_html}</tr>")
    if not rows:
        return ""
    return "<table border=\"1\" cellpadding=\"2\" cellspacing=\"0\">" + "".join(rows) + "</table>"


def _code_block_to_html(code_lines: list[str]) -> str:
    """将代码块行列表转为 <pre><code>...</code></pre>。"""
    text = "\n".join(code_lines)
    return "<pre><code>" + escape(text) + "</code></pre>"


def markdown_to_html(md_text: str) -> str:
    """
    将 Markdown 文本转为 HTML，供 PyMuPDF insert_htmlbox 使用。

    支持：# 标题、**粗体**、*斜体*、__粗体__、_斜体_、[text](url)、
    | 表格 |、``` 代码块 ```、换行 → <br>。
    已有 HTML 如 <sup>、<sub> 保持不变。
    """
    if not md_text or not md_text.strip():
        return md_text or ""
    lines = md_text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 标题：# ~ ######
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = min(len(heading_match.group(1)), 6)
            inner = _inline_md_to_html(heading_match.group(2).strip())
            result.append(f"<h{level}>{inner}</h{level}>")
            i += 1
            continue

        # 表格：连续含 | 且含分隔行
        if "|" in line and i + 1 < len(lines) and _is_table_separator(lines[i + 1]):
            table_lines = [line, lines[i + 1]]
            j = i + 2
            while j < len(lines) and "|" in lines[j] and not _is_table_separator(lines[j]):
                table_lines.append(lines[j])
                j += 1
            result.append(_table_to_html(table_lines))
            i = j
            continue

        # 代码块：``` ... ```
        if stripped.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            result.append(_code_block_to_html(code_lines))
            continue

        # 图片：![alt](url) 转为简单占位或 <img>
        img_match = re.match(r"^!\[([^\]]*)\]\(([^\)]+)\)\s*$", stripped)
        if img_match:
            alt, url = img_match.group(1), img_match.group(2)
            result.append(f'<img src="{escape(url)}" alt="{escape(alt)}"/>')
            i += 1
            continue

        # 空行 → 一个 <br> 做段落间隔
        if not stripped:
            result.append("<br>")
            i += 1
            continue

        # 普通段落行：内联转换后加 <br>
        result.append(_inline_md_to_html(line) + "<br>")
        i += 1

    out = "".join(result)
    # 去掉末尾多余的一个 <br>
    if out.endswith("<br>"):
        out = out[:-4]
    return out
