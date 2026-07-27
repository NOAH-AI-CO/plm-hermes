from __future__ import annotations

import re
from typing import Literal

import requests
from docx import Document
from docx.shared import Pt

from agent.ethics.prompt.util_prompt import ethics_html_template

_MD_TO_WORD_URL = "https://test.noahai.co/markdown-to-word/convert"
_IIT_GOTENBERG_MARKDOWN_URL = "https://test.noahai.co/iit-gotenberg/forms/chromium/convert/markdown"

# 仅去掉成对的 <think>…</think>（可跨行；多块时 sub 会逐段替换）
_REDACTED_THINKING_BLOCK = re.compile(
    r"<think>.*?</think>",
    re.DOTALL,
)


def strip_llm_reasoning_from_ethics_markdown(markdown: str) -> str:
    """导出前移除模型输出的显式思维链块（仅此一对标签，其余不动）。"""
    text = (markdown or "").lstrip("\ufeff").strip()
    text = _REDACTED_THINKING_BLOCK.sub("", text)
    return text.strip()


def md_to_word_ethics(
    input_file_path: str,
    output_file_path: str,
    *,
    format_type: Literal["english", "chinese"] = "chinese",
) -> None:
    """
    Markdown -> Word。仅调用转换服务并落盘；不做页眉页脚与 logo 注入。
    format_type 与远端服务约定一致：english / chinese。
    """
    with open(input_file_path, "r", encoding="utf-8") as handle:
        cleaned_md = strip_llm_reasoning_from_ethics_markdown(handle.read())
    files = {
        "file": (
            "document.md",
            cleaned_md.encode("utf-8"),
            "text/markdown",
        )
    }
    data = {"format_type": format_type}
    response = requests.post(_MD_TO_WORD_URL, files=files, data=data, timeout=120)

    if response.status_code != 200:
        raise ValueError(
            f"md_to_word_ethics failed: HTTP {response.status_code}: {(response.text or '')[:500]}"
        )

    with open(output_file_path, "wb") as out:
        out.write(response.content)

    if format_type == "english":
        document = Document(str(output_file_path))
        for paragraph in document.paragraphs:
            for run in paragraph.runs:
                is_heading = paragraph.style.name.startswith("Heading")
                if is_heading:
                    run.font.name = "Arial"
                    run.font.bold = True
                else:
                    run.font.name = "Arial"
                    run.font.size = Pt(11)
        document.save(str(output_file_path))


def convert_md_to_pdf_ethics(md_path: str, pdf_path: str) -> None:
    """
    Markdown -> PDF（Gotenberg + ethics_html_template）。不叠加 logo 与 IIT 页眉页脚。
    """
    with open(md_path, "r", encoding="utf-8") as handle:
        markdown_content = strip_llm_reasoning_from_ethics_markdown(handle.read())

    files = [
        ("files", ("index.html", ethics_html_template.encode("utf-8"), "text/html")),
        ("files", ("document.md", markdown_content.encode("utf-8"), "text/markdown")),
    ]
    form_data = {
        "paperWidth": 8.27,
        "paperHeight": 11.69,
        "marginTop": 1.0,
        "marginBottom": 0.8,
        "waitDelay": "1s",
    }

    response = requests.post(
        _IIT_GOTENBERG_MARKDOWN_URL,
        files=files,
        data=form_data,
        timeout=300,
    )
    if response.status_code != 200:
        raise ValueError(
            f"convert_md_to_pdf_ethics failed: HTTP {response.status_code}: {(response.text or '')[:500]}"
        )

    with open(pdf_path, "wb") as out:
        out.write(response.content)


__all__ = [
    "convert_md_to_pdf_ethics",
    "md_to_word_ethics",
    "strip_llm_reasoning_from_ethics_markdown",
]
