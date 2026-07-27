"""扫描件 PDF 的 OCR 工具: 逐页渲染成图片, 调 qwen3-vl-plus 转录为文本。

CACA 指南是扫描件(无文字层), PyMuPDF 抽不出文字, 需走 VLM OCR。
NCCN/CSCO/ESMO 多数有文字层, 由调用方判断后决定是否走这里。
"""
import base64
import logging
import os
import threading
import time

try:
    import pymupdf
except ModuleNotFoundError:
    import fitz as pymupdf

from openai import OpenAI
from config import api_config

logger = logging.getLogger(__name__)

_OCR_MODEL = "qwen3-vl-plus"
_OCR_DPI = 150
_SCANNED_CHARS_PER_PAGE = 20  # 平均每页文字低于此值判为扫描件

_OCR_PROMPT = (
    "这是一页医学临床指南的扫描图。请逐字转录页面中的全部文字为 Markdown, "
    "严格遵循:\n"
    "1. 保留原有标题层级、条目编号、表格(用 Markdown 表格)、流程/分支结构。\n"
    "2. 竖排文字按正常阅读顺序转成横排。\n"
    "3. 只做转录, 不要翻译、不要解读、不要总结、不要补充任何原文没有的内容。\n"
    "4. 页眉页脚/水印/页码可忽略。若整页无有效正文, 返回空。"
)

def _strip_fence(text: str) -> str:
    """剥掉 VLM 常带的 ```markdown ... ``` 代码围栏。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=api_config.ALIYUN_BAILIAN_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


# 全局限流, 避免 DashScope 触发 QPS 限制 (可用 OCR_MAX_CONCURRENCY 调)
_OCR_SEMAPHORE = threading.BoundedSemaphore(int(os.getenv("OCR_MAX_CONCURRENCY", "24")))


def is_scanned_pdf(pdf_path: str) -> bool:
    """全文平均每页文字量低于阈值即判为扫描件。"""
    doc = pymupdf.open(pdf_path)
    try:
        n = len(doc)
        if n == 0:
            return False
        total = sum(len((doc[i].get_text() or "").strip()) for i in range(n))
        return (total / n) < _SCANNED_CHARS_PER_PAGE
    finally:
        doc.close()


def _render_page_png_b64(pdf_path: str, page_index: int, dpi: int = _OCR_DPI) -> str:
    doc = pymupdf.open(pdf_path)
    try:
        pix = doc[page_index].get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
    finally:
        doc.close()
    return base64.b64encode(png).decode("utf-8")


def ocr_page(pdf_path: str, page_index: int, max_retries: int = 4) -> str:
    """OCR 单页, 返回转录文本(失败重试, 最终失败返回空串)。"""
    b64 = _render_page_png_b64(pdf_path, page_index)
    data_uri = f"data:image/png;base64,{b64}"
    client = _get_client()
    for attempt in range(max_retries):
        try:
            with _OCR_SEMAPHORE:
                resp = client.chat.completions.create(
                    model=_OCR_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {"type": "text", "text": _OCR_PROMPT},
                        ],
                    }],
                    temperature=0,
                )
            return _strip_fence((resp.choices[0].message.content or "").strip())
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.warning("OCR failed p%d of %s: %s", page_index, pdf_path, e)
                return ""
    return ""


def ocr_pdf_pages(pdf_path: str, workers: int = 6) -> list[str]:
    """并发 OCR 整本 PDF, 返回按页顺序的文本列表。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    doc = pymupdf.open(pdf_path)
    try:
        n = len(doc)
    finally:
        doc.close()
    pages: list[str] = [""] * n
    if n == 0:
        return pages
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(ocr_page, pdf_path, i): i for i in range(n)}
        done = 0
        for fut in as_completed(futs):
            pages[futs[fut]] = fut.result()
            done += 1
            if done % 10 == 0 or done == n:
                logger.info("OCR %s: %d/%d pages", pdf_path.split("/")[-1], done, n)
    return pages
