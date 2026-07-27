#!/usr/bin/env python3
"""
Document format conversion helpers for translation flows.

Supported core conversions (6 functions):
1) convert_pdf_to_md
2) convert_word_to_md
3) convert_txt_to_md
4) convert_md_to_pdf
5) convert_md_to_word
6) convert_md_to_txt
"""

from __future__ import annotations

import re
import time
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional

import fitz
import pypandoc
from markdown_it import MarkdownIt

from config import api_config
from utils.azure.blob_client import AzureBlobStorage
from utils.docs.parsing import parse_document_with_images, pdf_to_text
from agent.translation.convert_markdown_to_word import convert_markdown_to_word


def _resolve_output_path(origin_path: str, output_path: Optional[str], suffix: str) -> Path:
    origin = Path(origin_path)
    if output_path:
        return Path(output_path)
    return origin.with_suffix(suffix)


def _upload_image_and_get_url(
    image_bytes: bytes,
    *,
    container: str,
    blob_key: str,
    connection_string: Optional[str] = None,
    read_url_expiry_days: int = 1,
) -> str:
    conn = connection_string or api_config.AZURE_STORAGE_CONNECTION_STRING
    azure = AzureBlobStorage(
        connection_string=conn,
        read_url_expiry_days=read_url_expiry_days,
    )
    blob_url = azure.upload_file(container, blob_key, BytesIO(image_bytes))
    if blob_url:
        return blob_url
    # Fallback to SAS URL if direct URL fetch fails in current storage settings.
    return azure.get_read_url(container, blob_key) or ""


def convert_pdf_to_md(pdf_path: str, output_path: Optional[str] = None) -> str:
    """
    PDF -> Markdown (ignore images, text only).
    """
    p = Path(pdf_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {pdf_path}")

    with p.open("rb") as f:
        text = pdf_to_text(f) or ""
    out = _resolve_output_path(pdf_path, output_path, ".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return str(out)


def convert_word_to_md(
    word_path: str,
    output_path: Optional[str] = None,
    *,
    container: str = "nudata",
    blob_prefix: Optional[str] = None,
    connection_string: Optional[str] = None,
    upload_images: bool = True,
) -> str:
    """
    Word (.doc/.docx) -> Markdown.
    - Keep text/image relative order.
    - upload_images=True: upload every image to blob and embed as ![image](url).
    - upload_images=False: write images to output_dir/images/image_N.png, embed as ![image](images/image_N.png).
    """
    p = Path(word_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {word_path}")
    if p.suffix.lower() not in {".doc", ".docx"}:
        raise ValueError("only .doc/.docx is supported for word conversion")

    out = _resolve_output_path(word_path, output_path, ".md")
    out.parent.mkdir(parents=True, exist_ok=True)

    segments = parse_document_with_images(p.name, p.read_bytes())
    prefix = blob_prefix or f"attachments/format_convert/{int(time.time())}/{p.stem}"
    images_dir = out.parent / "images"

    md_parts = []
    image_index = 0
    for seg in segments:
        seg_type = seg.get("type")
        if seg_type == "text":
            text = (seg.get("content") or "").strip()
            if text:
                md_parts.append(text)
            continue

        if seg_type == "image":
            raw = seg.get("content")
            if not raw:
                md_parts.append("[image]")
                image_index += 1
                continue
            if upload_images:
                blob_key = f"{prefix}/image_{image_index}.png"
                image_url = _upload_image_and_get_url(
                    raw,
                    container=container,
                    blob_key=blob_key,
                    connection_string=connection_string,
                    read_url_expiry_days=365,
                )
                if image_url:
                    md_parts.append(f"![image]({image_url})")
                else:
                    md_parts.append("[image]")
            else:
                images_dir.mkdir(parents=True, exist_ok=True)
                local_path = images_dir / f"image_{image_index}.png"
                local_path.write_bytes(raw)
                rel = f"images/image_{image_index}.png"
                md_parts.append(f"![image]({rel})")
            image_index += 1
            continue

    out.write_text("\n\n".join(md_parts).strip() + "\n", encoding="utf-8")
    return str(out)


def convert_txt_to_md(txt_path: str, output_path: Optional[str] = None) -> str:
    """
    TXT -> Markdown (plain text passthrough).
    """
    p = Path(txt_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {txt_path}")
    if p.suffix.lower() != ".txt":
        raise ValueError("only .txt is supported for txt conversion")

    out = _resolve_output_path(txt_path, output_path, ".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(p.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return str(out)


def convert_md_to_pdf(
    md_path: str,
    output_path: Optional[str] = None,
    *,
    image_url_to_path: Optional[Dict[str, str]] = None,
) -> str:
    """
    Markdown -> PDF.
    Uses markdown-it-py + PyMuPDF (fitz).
    image_url_to_path: url -> 本地路径，渲染时用本地文件不下载。
    """
    p = Path(md_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {md_path}")

    out = _resolve_output_path(md_path, output_path, ".pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    md_text = p.read_text(encoding="utf-8", errors="ignore")
    html_body = MarkdownIt("commonmark", {"html": True}).enable("table").render(md_text)
    # fitz.Archive 只解析相对路径，用「相对 md 所在目录」的路径才能正确加载图片
    if image_url_to_path:
        for url, local_path in image_url_to_path.items():
            if not local_path or not Path(local_path).is_file():
                continue
            try:
                rel = Path(local_path).resolve().relative_to(Path(md_path).resolve().parent)
                html_body = html_body.replace(url, str(rel).replace("\\", "/"))
            except ValueError:
                continue
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; line-height: 1.6; font-size: 12pt; }}
    h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.5em; }}
    p, ul, ol, pre, blockquote, table {{ margin: 0.5em 0; }}
    img {{ max-width: 100%; height: auto; }}
    pre {{ white-space: pre-wrap; word-break: break-word; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 6px; }}
  </style>
</head>
<body>
{html_body}
</body>
</html>"""
    page_rect = fitz.paper_rect("a4")
    # A4 page margins: roughly 20mm top/bottom, 16mm left/right.
    content_rect = fitz.Rect(45, 57, page_rect.width - 45, page_rect.height - 57)
    archive = fitz.Archive(str(p.parent))
    story = fitz.Story(html=html_doc, archive=archive)
    writer = fitz.DocumentWriter(str(out))
    try:
        more = 1
        while more:
            dev = writer.begin_page(page_rect)
            more, _ = story.place(content_rect)
            story.draw(dev)
            writer.end_page()
    finally:
        writer.close()
    return str(out)


def convert_md_to_word(md_path: str, output_path: Optional[str] = None) -> str:
    """
    Markdown -> Word (.docx).
    """
    p = Path(md_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {md_path}")

    out = _resolve_output_path(md_path, output_path, ".docx")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Use translation-specific markdown->docx converter for better document styling.
    convert_markdown_to_word(str(p), str(out))
    if not out.is_file():
        raise RuntimeError("md2docx failed to generate output")
    return str(out)


def convert_md_to_txt(md_path: str, output_path: Optional[str] = None) -> str:
    """
    Markdown -> TXT.
    (Images are not preserved in txt；先去掉图片语法再转 plain，避免出现 [image] 或 alt 占位。)
    """
    p = Path(md_path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {md_path}")

    md_text = p.read_text(encoding="utf-8", errors="ignore")
    # 先移除图片语法，避免 pandoc 输出 alt 或占位符
    md_text_no_images = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", md_text)
    try:
        txt = pypandoc.convert_text(md_text_no_images, "plain", format="md")
    except Exception:
        txt = md_text_no_images
    out = _resolve_output_path(md_path, output_path, ".txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(txt, encoding="utf-8")
    return str(out)

