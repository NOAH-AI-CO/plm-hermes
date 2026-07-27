import asyncio
import re
import base64
from io import BytesIO
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import logging

from agent.bp.pp import get_text, normalize_pages_content
from agent.bp import vlm as vlm_module

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PptImageAsset:
    """A source image extracted during PDF parsing (MinerU), with a VLM-generated description."""
    filename: str  # e.g. "a1b2c3.jpg"
    data_uri: str  # e.g. "data:image/jpeg;base64,..."
    description: str  # VLM extracted text/summary for the image
    page_index: Optional[int] = None  # 0-based page index if known
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    aspect_ratio: Optional[float] = None  # width_px / height_px
    ocr_line_count: Optional[int] = None
    ocr_p10_text_h_px: Optional[float] = None
    ocr_median_text_h_px: Optional[float] = None
    readability_level: Optional[str] = None  # low | medium | high


_IMAGE_TOKEN_PREFIX = "Image["
_OCR_ENGINE = None
ENABLE_IMAGE_READABILITY = False


def _get_ocr_engine():
    """Lazily initialize PaddleOCR engine for readability analysis."""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    try:
        from paddleocr import PaddleOCR  # type: ignore
        _OCR_ENGINE = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    except Exception as e:
        logger.warning("PaddleOCR unavailable, skip readability metrics: %s", e)
        _OCR_ENGINE = False
    return _OCR_ENGINE


def _extract_text_heights_from_ocr_result(result: object) -> List[float]:
    """Extract line text heights in pixels from PaddleOCR outputs (multi-format compatible)."""
    heights: List[float] = []

    def _from_poly(poly: object) -> Optional[float]:
        try:
            pts = poly.tolist() if hasattr(poly, "tolist") else poly
            if not isinstance(pts, list) or len(pts) < 2:
                return None
            ys = []
            for p in pts:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    ys.append(float(p[1]))
            if len(ys) < 2:
                return None
            h = max(ys) - min(ys)
            return h if h > 0 else None
        except Exception:
            return None

    pages = result if isinstance(result, list) else [result]
    for page in pages:
        if not isinstance(page, dict):
            continue
        poly_candidates = []
        for key in ("rec_polys", "dt_polys", "polys", "text_polys"):
            value = page.get(key)
            if isinstance(value, list):
                poly_candidates.extend(value)
        for poly in poly_candidates:
            h = _from_poly(poly)
            if h is not None:
                heights.append(h)
    return heights


def _assess_image_readability(img_bytes: bytes) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[str]]:
    """
    Estimate image readability using OCR line heights.
    Returns (line_count, p10_text_height_px, median_text_height_px, readability_level).
    """
    engine = _get_ocr_engine()
    if not engine:
        return None, None, None, None
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore

        with Image.open(BytesIO(img_bytes)) as im:
            rgb = im.convert("RGB")
            arr = np.array(rgb)
        result = engine.predict(input=arr)
        heights = _extract_text_heights_from_ocr_result(result)
        if not heights:
            return 0, None, None, "low"
        heights_sorted = sorted(float(h) for h in heights)
        n = len(heights_sorted)
        p10_idx = int(max(0, min(n - 1, round((n - 1) * 0.1))))
        p10 = heights_sorted[p10_idx]
        median = heights_sorted[n // 2]
        # p10 越小代表图片内文字越密越小，阅读难度越高
        if p10 < 11:
            level = "high"
        elif p10 < 16:
            level = "medium"
        else:
            level = "low"
        return n, p10, median, level
    except Exception as e:
        logger.debug("Readability assessment failed: %s", e)
        return None, None, None, None


def _extract_image_refs_in_order(pages: List[str]) -> List[Tuple[int, str, str]]:
    """
    Returns list of (page_index, markdown_ref, filename) in scan order.
    markdown_ref looks like "![](images/<filename>)".
    """
    refs: List[Tuple[int, str, str]] = []
    for page_idx, page in enumerate(pages):
        for markdown_ref, filename, _start, _end in vlm_module.find_image_references(page):
            refs.append((page_idx, markdown_ref, filename))
    return refs


def _lookup_image_uri(images_dict: Dict[str, str], filename: str) -> str | None:
    """从 images_dict 查找图片 URI，支持 filename、images/filename 及模糊匹配"""
    uri = images_dict.get(filename)
    if uri:
        return uri
    uri = images_dict.get(f"images/{filename}")
    if uri:
        return uri
    for k, v in images_dict.items():
        if k.endswith(filename) or filename in k:
            return v
    return None


def _make_image_token(filename: str, description: str) -> str:
    """
    Token format is intentionally different from vlm.py's `Image[desc]` to preserve filename.
    We keep it plain-text so it can flow through downstream LLM prompts.
    """
    safe_desc = (description or "").replace("\n", " ").strip()
    return f"Image[{filename}|{safe_desc}]"


async def _describe_images(
    refs: List[Tuple[int, str, str]],
    images_dict: Dict[str, str],
    *,
    detailed: int = 2,
    max_concurrency: int = 30,
) -> Dict[str, str]:
    """
    Returns {filename -> description}. Uses existing vlm.py `send_to_vlm` without modifying it.
    """
    sem = asyncio.Semaphore(max_concurrency)
    out: Dict[str, str] = {}

    # Deduplicate by filename (same image might be referenced multiple times).
    filenames = []
    seen = set()
    for _page_idx, _markdown_ref, filename in refs:
        if filename in seen:
            continue
        seen.add(filename)
        filenames.append(filename)

    async def _one(filename: str):
        data_uri = _lookup_image_uri(images_dict, filename)
        if not data_uri:
            logger.warning("Image filename referenced but missing from images dict: %s", filename)
            return
        async with sem:
            try:
                desc = await vlm_module.send_to_vlm(data_uri, detailed=detailed)
            except Exception as e:
                logger.exception("VLM description failed for %s: %s", filename, e)
                return
        if desc:
            out[filename] = str(desc).strip()

    await asyncio.gather(*[_one(fn) for fn in filenames])
    return out


async def parse_pdf_for_ppt(
    path: str,
    *,
    remote_path: bool = False,
    detailed: int = 2,
    max_concurrency: int = 30,
) -> Tuple[List[str], Dict[str, str], List[PptImageAsset]]:
    """
    PPT-friendly PDF parsing wrapper:
    - Calls existing `agent.bp.pp.get_text()` (so no behavior changes elsewhere).
    - If MinerU returned images + markdown refs, we VLM-describe each image and replace markdown refs with tokens
      that preserve the filename: `Image[<filename>|<description>]`.
    - Returns (processed_pages, images_dict, image_assets).
    """
    parsed_dict = await get_text(path, stream=remote_path)
    if not isinstance(parsed_dict, dict):
        raise TypeError(f"Parsed result is not a dict: {type(parsed_dict).__name__}")

    results = parsed_dict.get("results", {})
    if not isinstance(results, dict) or not results:
        return [], {}, []

    # pp.parse_and_select breaks after first result; we mirror that behavior.
    _file_name, result = next(iter(results.items()))
    if not isinstance(result, dict):
        result = {"md_content": result, "images": {}}

    images_dict = result.get("images", {}) or {}
    pages = normalize_pages_content(result.get("md_content", []), file_name=_file_name)

    # No images to preserve -> return as-is.
    if not images_dict:
        return pages, {}, []

    refs = _extract_image_refs_in_order(pages)
    if not refs:
        # MinerU returned images dict but no markdown refs; still return the images dict for callers that want it.
        return pages, images_dict, []

    filename_to_desc = await _describe_images(
        refs,
        images_dict,
        detailed=detailed,
        max_concurrency=max_concurrency,
    )

    # Replace markdown refs with filename-preserving tokens
    processed_pages: List[str] = []
    for page in pages:
        new_page = page
        # Replace *all* refs on this page; use regex from vlm.py for consistency.
        for markdown_ref, filename, _start, _end in vlm_module.find_image_references(page):
            desc = filename_to_desc.get(filename, "")
            new_page = new_page.replace(markdown_ref, _make_image_token(filename, desc))
        processed_pages.append(new_page)

    assets: List[PptImageAsset] = []
    for page_idx, _markdown_ref, filename in refs:
        data_uri = _lookup_image_uri(images_dict, filename)
        if not data_uri:
            continue
        desc = filename_to_desc.get(filename, "")

        width_px = height_px = None
        aspect_ratio = None
        ocr_line_count = None
        ocr_p10_text_h_px = None
        ocr_median_text_h_px = None
        readability_level = None
        try:
            # data_uri expected: "data:image/jpeg;base64,...."
            b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
            img_bytes = base64.b64decode(b64)
            # Pillow is commonly available in this repo; import lazily to avoid hard dependency at import time.
            from PIL import Image  # type: ignore
            with Image.open(BytesIO(img_bytes)) as im:
                width_px, height_px = im.size
                if height_px:
                    aspect_ratio = float(width_px) / float(height_px)
            if ENABLE_IMAGE_READABILITY:
                (
                    ocr_line_count,
                    ocr_p10_text_h_px,
                    ocr_median_text_h_px,
                    readability_level,
                ) = _assess_image_readability(img_bytes)
        except Exception as e:
            logger.debug("Failed to extract image dimensions for %s: %s", filename, e)

        assets.append(
            PptImageAsset(
                filename=filename,
                data_uri=data_uri,
                description=desc,
                page_index=page_idx,
                width_px=width_px,
                height_px=height_px,
                aspect_ratio=aspect_ratio,
                ocr_line_count=ocr_line_count,
                ocr_p10_text_h_px=ocr_p10_text_h_px,
                ocr_median_text_h_px=ocr_median_text_h_px,
                readability_level=readability_level,
            )
        )

    return processed_pages, images_dict, assets


_TOKEN_RE = re.compile(r"Image\[([a-f0-9]+\.jpg)\|([^\]]*)\]")


def extract_image_tokens(text: str) -> List[Tuple[str, str]]:
    """Extracts [(filename, description)] from `Image[filename|desc]` tokens."""
    if not text:
        return []
    return [(m.group(1), m.group(2).strip()) for m in _TOKEN_RE.finditer(text)]

