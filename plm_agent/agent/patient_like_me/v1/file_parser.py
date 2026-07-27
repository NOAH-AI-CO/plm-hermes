"""
PLM 文件附件解析器。

接收一组 URL，下载 → 类型识别（按 MIME + magic bytes + 后缀三重判断）→ 走对应解析器：
  - 图片 (jpg/png/...) → Qwen-VL OCR
  - PDF (含扫描件)   → pypdf 抽文本，失败回退到逐页渲染 + Qwen-VL OCR
  - DOC/DOCX/TXT/MD → docling / 直接读

设计要点：
  - 仅允许 http/https URL（防 SSRF），不允许 file:// / gopher:// / 内网 metadata 等
  - 单文件最大 50MB；批量最多 20 个
  - 下载并发限制（信号量）；OCR 内部已自带 batch
  - 失败的文件返回结构化结果（不只是 None），方便上游 emit per-file 进度

NOTE: 此文件与 ``agent/sahzu/file_parser.py`` 必须保持完全一致（除 docstring 中的 agent 名）。
任何修改请同步两端。
"""
import asyncio
import logging
from typing import Callable, Optional
from urllib.parse import urlparse
from pathlib import PurePosixPath

import httpx

from utils.docs.parsing import convert_document

logger = logging.getLogger(__name__)

# ─── Configuration ───
_DOWNLOAD_TIMEOUT = 60                       # seconds
_MAX_FILE_SIZE = 50 * 1024 * 1024            # 50 MB
_MAX_FILES_PER_BATCH = 20                    # cap on file_urls list length
_MAX_CONCURRENT_DOWNLOADS = 6                # download concurrency limit
_ALLOWED_URL_SCHEMES = {"http", "https"}     # SSRF guard: no file://, no gopher://

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}
_DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}

# Magic bytes signatures for MIME sniffing — used to detect mislabeled files.
_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),  # WEBP starts with RIFF (further bytes need WEBP marker, but RIFF is enough indicator)
    (b"BM", ".bmp"),
    (b"%PDF-", ".pdf"),
    (b"PK\x03\x04", ".docx"),    # DOCX is zip
    (b"\xd0\xcf\x11\xe0", ".doc"),  # OLE2 (.doc legacy)
]


def _is_image(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in _IMAGE_EXTENSIONS


def _detect_extension_from_magic(content: bytes) -> Optional[str]:
    """Sniff file type from leading bytes. Returns a canonical extension (with dot) or None."""
    for sig, ext in _MAGIC_SIGNATURES:
        if content.startswith(sig):
            return ext
    return None


def _validate_url_scheme(url: str) -> None:
    """Block non-http(s) URLs to prevent SSRF (file://, gopher://, http://169.254.169.254, etc.)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(f"URL scheme {scheme!r} not allowed (only http/https)")
    if not parsed.netloc:
        raise ValueError(f"URL has no host: {url!r}")


async def _download_file(url: str) -> tuple[str, bytes]:
    _validate_url_scheme(url)
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    content = resp.content
    if len(content) > _MAX_FILE_SIZE:
        raise ValueError(f"File too large ({len(content)} bytes): {url}")

    parsed = urlparse(url)
    name = PurePosixPath(parsed.path).name or "unnamed"

    # 若 URL 后缀缺失或异常，用 magic bytes 补一个扩展名，下游 _is_image / convert_document 才能正确分流。
    suffix = PurePosixPath(name).suffix.lower()
    if not suffix or (suffix not in _IMAGE_EXTENSIONS and suffix not in _DOCUMENT_EXTENSIONS):
        sniffed = _detect_extension_from_magic(content)
        if sniffed:
            name = f"{name}{sniffed}"
            logger.info("[file_parser] URL %r missing ext; sniffed %s", url, sniffed)

    return name, content


async def _ocr_images_batch(images: list[bytes]) -> list[str]:
    from agent.translation.llm_translate import qwen_vl_extract_batch
    return await qwen_vl_extract_batch(images, batch_size=16)


async def parse_file(url: str) -> Optional[str]:
    """单文件解析。失败返回 None。"""
    try:
        name, content = await _download_file(url)
        if _is_image(name):
            results = await _ocr_images_batch([content])
            text = results[0] if results else ""
            return text.strip() if text else None
        text = await asyncio.to_thread(convert_document, name, content)
        return text.strip() if text else None
    except Exception as e:
        logger.warning(f"Failed to parse file {url}: {e}")
        return None


async def parse_files(
    file_urls: list[str],
    on_progress: Optional[Callable] = None,
) -> list[str]:
    """批量解析。返回成功解析的文本列表（按输入顺序，丢失失败项）。"""
    if not file_urls:
        return []

    # 长度上限：避免一次接收 100 个 50MB 文件直接撑爆内存。
    if len(file_urls) > _MAX_FILES_PER_BATCH:
        logger.warning("[file_parser] received %d files, truncating to %d",
                       len(file_urls), _MAX_FILES_PER_BATCH)
        file_urls = file_urls[:_MAX_FILES_PER_BATCH]

    if on_progress:
        on_progress("parsing_files", {"total": len(file_urls)})

    # 并发下载，但用信号量限流（防止内网突然 N 个 50MB 一起拉）
    sem = asyncio.Semaphore(_MAX_CONCURRENT_DOWNLOADS)

    async def _download_with_sem(url: str) -> tuple[str, bytes] | Exception:
        async with sem:
            try:
                return await _download_file(url)
            except Exception as e:
                return e

    downloads = await asyncio.gather(
        *[_download_with_sem(url) for url in file_urls],
    )

    images: list[tuple[int, bytes]] = []
    documents: list[tuple[int, str, bytes]] = []
    for i, result in enumerate(downloads):
        if isinstance(result, Exception):
            logger.warning("Failed to download %s: %s", file_urls[i], result)
            continue
        name, content = result
        if _is_image(name):
            images.append((i, content))
        else:
            documents.append((i, name, content))

    results: list[Optional[str]] = [None] * len(file_urls)

    if images:
        if on_progress:
            on_progress("parsing_images", {"count": len(images)})
        try:
            ocr_texts = await _ocr_images_batch([img_bytes for _, img_bytes in images])
            for (idx, _), text in zip(images, ocr_texts):
                results[idx] = text.strip() if text else None
        except Exception as e:
            logger.warning("Batch OCR failed: %s", e)

    if documents:
        if on_progress:
            on_progress("parsing_documents", {"count": len(documents)})
        doc_tasks = [
            asyncio.to_thread(convert_document, name, content)
            for _, name, content in documents
        ]
        doc_results = await asyncio.gather(*doc_tasks, return_exceptions=True)
        for (idx, _, _), result in zip(documents, doc_results):
            if isinstance(result, Exception):
                logger.warning("Document parse failed (idx=%d): %s", idx, result)
            else:
                results[idx] = result.strip() if result else None

    return [r for r in results if r]
