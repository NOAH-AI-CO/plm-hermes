#!/usr/bin/env python3
"""
图片翻译：Paddle 版面检测 + VLM 提取并翻译，回填为 JPG。
不落盘 middle，不兼容 MinerU middle；内部用 layout（bbox+译文）仅作回填。
"""
import asyncio
import ctypes
import datetime
import gc
import json
import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Callable, List, Optional

import cv2
import numpy as np
from paddleocr import LayoutDetection, TableCellsDetection

from agent.translation.glossary.es_search import search_glossary_batch
from agent.translation.llm_translate import (
    qwen_vl_extract_and_translate_batch,
    qwen_vl_extract_batch,
    qwen_translate_texts_batch,
)
from agent.translation.ocr_translate import (
    image_to_pdf,
    pdf_to_jpg,
    draw_single_page_from_middle_on_original,
)

# 与 layout_rec_merge 一致：image/chart/seal 不送 VLM 翻译，只对文本类区域做提取+翻译
LABELS_SKIP_REC = ("image", "chart", "seal")
# qwen-vl 要求图片宽高均 > 10，过小区域不送 VLM 避免 400
MIN_CROP_SIZE = 15
TABLE_CELL_DET_THRESHOLD = float(os.environ.get("TABLE_CELL_DET_THRESHOLD", "0.3"))

# PP-DocLayout-L 按类别设置置信度阈值（cls_id -> threshold），未列出的类别用模型默认（约 0.5）。
# 阈值越低越容易检出该类别，但可能增加误检。建议对易漏检的类别适当放低。
# 常见 cls_id（以官方输出为准）：0=paragraph_title, 1=document_title, 2=text, 6=figure_title,
# 8=table, 9=table_title/table_caption；其余见 PaddleOCR 文档 23 类说明。
LAYOUT_THRESHOLD_BY_CLASS: dict[int, float] = {
    0: 0.12,   # paragraph_title，易漏检
    1: 0.12,   # document_title
    2: 0.08,   # text（正文），同事验证用 0.08
    6: 0.12,   # figure_title
    8: 0.15,   # table
    9: 0.15,   # table_title / table_caption
}

_PADDLE_POOL_SIZE = int(os.environ.get("PADDLE_MODEL_POOL_SIZE", "8"))


class _PaddleModelPool:
    """
    Fixed-size pool of Paddle model instances.
    Allows up to `size` concurrent predictions while capping total model copies in memory.
    Each instance is used by at most one thread at a time (Paddle is not thread-safe for
    concurrent calls on the same object), but different instances run independently.
    """

    def __init__(self, factory: Callable, size: int):
        self._factory = factory
        self._sem = asyncio.Semaphore(size)
        self._available: list = []
        self._list_lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self):
        async with self._sem:  # blocks once `size` instances are in use
            async with self._list_lock:
                model = self._available.pop() if self._available else None
            if model is None:
                # First-time creation is slow; run in thread to avoid blocking event loop.
                model = await asyncio.to_thread(self._factory)
            try:
                yield model
            finally:
                async with self._list_lock:
                    self._available.append(model)


_TABLE_CELL_POOL = _PaddleModelPool(
    lambda: TableCellsDetection(model_name="RT-DETR-L_wireless_table_cell_det"),
    size=_PADDLE_POOL_SIZE,
)
_LAYOUT_POOL = _PaddleModelPool(
    lambda: LayoutDetection(model_name="PP-DocLayout-L", enable_mkldnn=False),
    size=_PADDLE_POOL_SIZE,
)

logger = logging.getLogger(__name__)

# glibc holds freed memory in its internal free-list and does not return pages to the OS
# even after del + gc.collect(). malloc_trim(0) forces it to release free pages immediately.
try:
    _libc = ctypes.CDLL("libc.so.6", use_errno=True)
except Exception:
    _libc = None


def _malloc_trim() -> None:
    if _libc is not None:
        _libc.malloc_trim(0)


_NO_TEXT_PATTERNS = (
    "无文字可提取",
    "未检测到文字",
    "没有文字",
    "no text",
    "no readable text",
    "no visible text",
    "no extractable text",
)


def _box_area(coord: list) -> float:
    """计算 bbox [x1, y1, x2, y2] 面积。"""
    x1, y1, x2, y2 = coord
    return max(0, x2 - x1) * max(0, y2 - y1)


def _intersection_area(a: list, b: list) -> float:
    """计算两个 bbox 的交集面积。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    return max(0, ix2 - ix1) * max(0, iy2 - iy1)


def _filter_large_boxes_overlapping_small(
    boxes: List[dict],
    *,
    large_overlap_threshold: float = 0.8,
    large_count_threshold: int = 1,
    small_overlap_threshold: float = 0.9,
) -> List[dict]:
    """
    两轮重叠框过滤：

    Pass 1 – 移除「大框」：若某框面积严格大于多个「小框」，且与超过 large_count_threshold
    个小框的重叠（占小框面积）> large_overlap_threshold，则移除该大框。

    Pass 2 – 移除「小框」：若某框被面积严格更大的剩余框覆盖超过 small_overlap_threshold
    （占自身面积），则移除该小框。
    """
    if not boxes:
        return boxes
    areas = [_box_area(b.get("coordinate", [0, 0, 0, 0])) for b in boxes]
    to_remove = set()

    for i in range(len(boxes)):
        if areas[i] == 0:
            continue
        coord_i = boxes[i].get("coordinate")
        if not coord_i or len(coord_i) != 4:
            continue
        overlap_count = 0
        for j in range(len(boxes)):
            if i == j or areas[i] <= areas[j]:
                continue
            small_area = areas[j]
            if small_area == 0:
                continue
            coord_j = boxes[j].get("coordinate")
            if not coord_j or len(coord_j) != 4:
                continue
            overlap = _intersection_area(coord_i, coord_j) / small_area
            if overlap > large_overlap_threshold:
                overlap_count += 1
        if overlap_count > large_count_threshold:
            to_remove.add(i)

    remaining = [idx for idx in range(len(boxes)) if idx not in to_remove]
    pass2_remove = set()
    for i in remaining:
        small_area = areas[i]
        if small_area == 0:
            continue
        coord_i = boxes[i].get("coordinate")
        if not coord_i or len(coord_i) != 4:
            continue
        for j in remaining:
            if i == j or j in pass2_remove or areas[j] <= areas[i]:
                continue
            coord_j = boxes[j].get("coordinate")
            if not coord_j or len(coord_j) != 4:
                continue
            overlap = _intersection_area(coord_i, coord_j) / small_area
            if overlap > small_overlap_threshold:
                pass2_remove.add(i)
                break

    to_remove |= pass2_remove
    return [b for idx, b in enumerate(boxes) if idx not in to_remove]


async def _run_table_cell_predict(table_path: str) -> list:
    """Run TableCellsDetection.predict() off the event loop using the model pool."""
    async with _TABLE_CELL_POOL.acquire() as model:
        return await asyncio.to_thread(
            model.predict, table_path,
            threshold=TABLE_CELL_DET_THRESHOLD, batch_size=1,
        )


async def _run_layout_predict(image_path: str) -> list:
    """Run LayoutDetection.predict() off the event loop using the model pool."""
    async with _LAYOUT_POOL.acquire() as model:
        return await asyncio.to_thread(
            model.predict, [image_path],
            batch_size=1, layout_nms=True,
            threshold=LAYOUT_THRESHOLD_BY_CLASS,
            layout_merge_bboxes_mode="small",
        )


def _extract_boxes_from_result(result_obj: Any) -> list[dict]:
    """兼容 Paddle result 的不同结构，提取 boxes 列表。"""
    try:
        d = dict(result_obj) if not hasattr(result_obj, "get") else result_obj
    except Exception:
        d = {}
    inner = d.get("res", d) if isinstance(d, dict) else {}
    boxes = inner.get("boxes", []) if isinstance(inner, dict) else []
    return boxes if isinstance(boxes, list) else []


async def _detect_table_cells(table_crop_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    对 table 区域做 cell 检测，返回相对 table 左上角的 cell bbox 列表。
    """
    if table_crop_bgr is None or table_crop_bgr.size == 0:
        return []
    h, w = table_crop_bgr.shape[:2]
    if h < MIN_CROP_SIZE or w < MIN_CROP_SIZE:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        table_path = os.path.join(tmp, "table.png")
        cv2.imwrite(table_path, table_crop_bgr)
        outputs = await _run_table_cell_predict(table_path)

    cells: list[tuple[int, int, int, int]] = []
    for out in outputs or []:
        for b in _extract_boxes_from_result(out):
            if (b.get("label") or "") != "cell":
                continue
            coord = b.get("coordinate")
            if not coord or len(coord) != 4:
                continue
            x1, y1, x2, y2 = map(int, coord)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if (x2 - x1) < MIN_CROP_SIZE or (y2 - y1) < MIN_CROP_SIZE:
                continue
            if x2 > x1 and y2 > y1:
                cells.append((x1, y1, x2, y2))
    return cells


def _normalize_qwen_text(text: Any) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    lower = s.lower()
    if any(p in s for p in _NO_TEXT_PATTERNS) or any(p in lower for p in _NO_TEXT_PATTERNS):
        return ""
    return s


def _should_skip_fillback_text(text: str) -> bool:
    s = _normalize_qwen_text(text)
    if not s:
        return True
    # 仅包含数字和符号（不含中英文字符）时跳过回填。
    return re.fullmatch(r"[\d\W_]+", s, flags=re.UNICODE) is not None


def _is_ascii_only_text(text: str) -> bool:
    """
    Returns True when the text contains only ASCII characters (digits, Latin letters,
    symbols, whitespace) with no non-ASCII letter characters (e.g. no CJK, Hiragana,
    Arabic, Cyrillic). Such cells don't need translation when the target is English.
    """
    s = (text or "").strip()
    if not s:
        return True
    for ch in s:
        if ord(ch) > 127 and unicodedata.category(ch).startswith("L"):
            return False
    return True


def _target_is_english(target_language: str) -> bool:
    """Return True if target_language refers to English in any common form."""
    t = (target_language or "").strip().lower()
    return t in ("english", "en", "en-us", "en-gb", "英语", "英文")


async def _translate_table_image_to_jpg(
    image_path: str,
    output_path: str,
    target_language: str,
    *,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    return_has_text: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> Any:
    """
    MinerU table 图片的直通翻译路径：跳过 Paddle 版面重分类，
    直接对整图做 cell 检测 → 逐 cell 送 VLM，回填后输出 JPG。
    """
    original_img = cv2.imread(image_path)
    if original_img is None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_pdf = os.path.join(tmp, "page.pdf")
            image_to_pdf(image_path, temp_pdf)
            pdf_to_jpg(temp_pdf, output_path)
        if on_progress:
            await _call_on_progress(on_progress, 1, 1)
        return (output_path, False) if return_has_text else output_path

    h, w = original_img.shape[:2]
    img_name = Path(image_path).name
    stem = Path(image_path).stem

    cell_boxes = await _detect_table_cells(original_img)
    logger.info(
        "[table_cell_det] image=%s (is_table path) cells_detected=%d",
        img_name, len(cell_boxes),
    )

    if cell_boxes:
        cropped_images = []
        region_bboxes = []
        for cx1, cy1, cx2, cy2 in cell_boxes:
            cx1, cy1 = max(0, cx1), max(0, cy1)
            cx2, cy2 = min(w, cx2), min(h, cy2)
            if (cx2 - cx1) < MIN_CROP_SIZE or (cy2 - cy1) < MIN_CROP_SIZE:
                continue
            crop = original_img[cy1:cy2, cx1:cx2]
            if crop is None or crop.size == 0:
                continue
            cropped_images.append(crop)
            region_bboxes.append((cx1, cy1, cx2, cy2))
    else:
        # No cells detected — treat the whole image as one region
        cropped_images = [original_img]
        region_bboxes = [(0, 0, w, h)]

    translated_indices: set[int] = set()
    if _target_is_english(target_language):
        extracted_texts = await qwen_vl_extract_batch(cropped_images)
        extracted_texts = [_normalize_qwen_text(t) for t in extracted_texts]
        n_crops = len(cropped_images)
        if len(extracted_texts) != n_crops:
            extracted_texts = (extracted_texts + [""] * n_crops)[:n_crops]
        glossary_hint = ""
        if use_glossary:
            try:
                glossary_texts = [t for t in extracted_texts if t]
                if glossary_texts:
                    glossary_hits = await asyncio.to_thread(
                        search_glossary_batch,
                        glossary_texts,
                        12,
                        12,
                        use_glossary_embedding,
                    )
                    glossary_hint = "\n".join(
                        f"{e['en_term']} = {e['cn_term']}"
                        for e in glossary_hits
                        if e.get("en_term") and e.get("cn_term")
                    )
            except Exception as _glossary_exc:
                logger.warning("[paddle_ocr] glossary search failed: %s", _glossary_exc)
        texts_to_translate = [
            (i, extracted_texts[i])
            for i in range(n_crops)
            if extracted_texts[i] and not _is_ascii_only_text(extracted_texts[i])
        ]
        final_texts = list(extracted_texts)
        if texts_to_translate:
            translations = await qwen_translate_texts_batch(
                [t for _, t in texts_to_translate], target_language, glossary_hint=glossary_hint
            )
            for (idx, _), translated in zip(texts_to_translate, translations):
                final_texts[idx] = translated
                translated_indices.add(idx)
    else:
        # 2-step: extract → glossary search → translate (batch)
        extracted_texts = await qwen_vl_extract_batch(cropped_images)
        extracted_texts = [_normalize_qwen_text(t) for t in extracted_texts]
        n_crops = len(cropped_images)
        if len(extracted_texts) != n_crops:
            extracted_texts = (extracted_texts + [""] * n_crops)[:n_crops]
        glossary_hint = ""
        if use_glossary:
            try:
                glossary_texts = [t for t in extracted_texts if t]
                if glossary_texts:
                    glossary_hits = await asyncio.to_thread(
                        search_glossary_batch,
                        glossary_texts,
                        12,
                        12,
                        use_glossary_embedding,
                    )
                    glossary_hint = "\n".join(
                        f"{e['en_term']} = {e['cn_term']}"
                        for e in glossary_hits
                        if e.get("en_term") and e.get("cn_term")
                    )
            except Exception as _glossary_exc:
                logger.warning("[paddle_ocr] glossary search failed: %s", _glossary_exc)
        texts_to_translate = [
            (i, extracted_texts[i])
            for i in range(n_crops)
            if extracted_texts[i]
        ]
        final_texts = ["" ] * n_crops
        if texts_to_translate:
            translations = await qwen_translate_texts_batch(
                [t for _, t in texts_to_translate], target_language, glossary_hint=glossary_hint
            )
            if len(translations) != len(texts_to_translate):
                translations = (translations + [""] * len(texts_to_translate))[:len(texts_to_translate)]
            for (idx, _), translated in zip(texts_to_translate, translations):
                final_texts[idx] = _normalize_qwen_text(translated)

    # Release large numpy arrays — all VLM calls are done.
    del cropped_images, original_img
    gc.collect()
    _malloc_trim()

    blocks = []
    for idx, (x1, y1, x2, y2) in enumerate(region_bboxes):
        text = final_texts[idx] if idx < len(final_texts) else ""
        if _should_skip_fillback_text(text):
            continue
        # English target: only paste back cells that were actually translated (had non-ASCII content)
        if _target_is_english(target_language) and idx not in translated_indices:
            continue
        # Non-English target: skip if translation result is ASCII-only (no meaningful localised text)
        if not _target_is_english(target_language) and _is_ascii_only_text(text):
            continue
        blocks.append({"bbox": [x1, y1, x2, y2], "text": text, "is_table_cell": True})

    translated_page = {"page_size": [w, h], "blocks": blocks}
    with tempfile.TemporaryDirectory() as tmp:
        temp_pdf = os.path.join(tmp, "page.pdf")
        temp_out_pdf = os.path.join(tmp, "out.pdf")
        image_to_pdf(image_path, temp_pdf)
        draw_single_page_from_middle_on_original(
            temp_pdf, 0, translated_page, temp_out_pdf
        )
        pdf_to_jpg(temp_out_pdf, output_path)

    if on_progress:
        await _call_on_progress(on_progress, 1, 1)
    has_text = bool(blocks)
    return (output_path, has_text) if return_has_text else output_path


async def translate_image_to_jpg_from_bytes(
    image_bytes: bytes,
    output_path: str,
    target_language: str = "Chinese",
    *,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    return_has_text: bool = False,
    is_table: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> Any:
    """
    单张图片（内存 bytes）：写入临时文件后走 translate_image_to_jpg，避免调用方落盘。
    返回翻译后的 JPG 路径。
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
    try:
        os.write(fd, image_bytes)
        os.close(fd)
        return await translate_image_to_jpg(
            tmp_path,
            output_path=output_path,
            target_language=target_language,
            on_progress=on_progress,
            return_has_text=return_has_text,
            is_table=is_table,
            use_glossary=use_glossary,
            use_glossary_embedding=use_glossary_embedding,
        )
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def translate_image_to_jpg(
    image_path: str,
    output_path: Optional[str] = None,
    target_language: str = "Chinese",
    *,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    return_has_text: bool = False,
    is_table: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> Any:
    """
    单张图片：Paddle 版面检测 → 裁剪区域 → VLM 提取并翻译 → 按 layout 回填 → 输出 JPG。
    不读写 middle 文件，返回翻译后的 JPG 路径。
    若 is_table=True（来自 MinerU table block），跳过 Paddle 版面重分类，
    直接对整张图做 cell 检测后送 VLM，避免 Paddle 将其误分类为非 table。
    """
    image_path = str(Path(image_path).resolve())
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"图片不存在: {image_path}")

    if output_path is None:
        output_path = str(Path(image_path).parent / f"{Path(image_path).stem}_translated.jpg")
    output_path = str(Path(output_path).resolve())

    if is_table:
        return await _translate_table_image_to_jpg(
            image_path=image_path,
            output_path=output_path,
            target_language=target_language,
            on_progress=on_progress,
            return_has_text=return_has_text,
            use_glossary=use_glossary,
            use_glossary_embedding=use_glossary_embedding,
        )

    layout_results = await _run_layout_predict(image_path)
    if not layout_results:
        # 无版面结果：原图转 PDF 再转 JPG 作为输出
        with tempfile.TemporaryDirectory() as tmp:
            temp_pdf = os.path.join(tmp, "page.pdf")
            image_to_pdf(image_path, temp_pdf)
            pdf_to_jpg(temp_pdf, output_path)
        if on_progress:
            await _call_on_progress(on_progress, 1, 1)
        return output_path

    layout_res = layout_results[0]
    # 版面图（与 boxes 坐标系一致）
    page_img = None
    try:
        d = dict(layout_res) if not hasattr(layout_res, "get") else layout_res
        page_img = d.get("input_img")
        if page_img is None and "res" in d:
            page_img = d["res"].get("input_img") if isinstance(d.get("res"), dict) else None
    except Exception:
        pass
    if page_img is None and hasattr(layout_res, "input_img"):
        page_img = layout_res.input_img
    if page_img is not None:
        original_img = np.asarray(page_img).copy()
    else:
        original_img = cv2.imread(image_path)
    if original_img is None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_pdf = os.path.join(tmp, "page.pdf")
            image_to_pdf(image_path, temp_pdf)
            pdf_to_jpg(temp_pdf, output_path)
        if on_progress:
            await _call_on_progress(on_progress, 1, 1)
        return output_path

    # 解析 boxes 并做重叠框过滤（参考同事验证方案）
    try:
        d = dict(layout_res) if not hasattr(layout_res, "get") else layout_res
        inner = d.get("res", d)
        detections = inner.get("boxes", []) if isinstance(inner, dict) else d.get("boxes", [])
    except Exception:
        detections = getattr(layout_res, "boxes", [])
    if isinstance(detections, list) and detections:
        detections = _filter_large_boxes_overlapping_small(
            detections,
            large_overlap_threshold=0.8,
            large_count_threshold=1,
            small_overlap_threshold=0.9,
        )

    # print("[image_translate] after filter: detections count =", len(detections))

    cropped_images = []
    region_bboxes = []
    is_table_cell_crop: list[bool] = []  # True for crops from per-cell table detection
    table_det_index = 0  # increments per table detection, for unique debug filenames
    h, w = original_img.shape[:2]
    _send_index = 0
    for detection in detections:
        label = detection.get("label", None) if isinstance(detection, dict) else getattr(detection, "label", None)
        if label in LABELS_SKIP_REC:
            continue
        bbox = detection.get("coordinate", detection) if isinstance(detection, dict) else getattr(detection, "coordinate", None)
        if bbox is None:
            continue
        x1, y1, x2, y2 = map(int, bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if (x2 - x1) < MIN_CROP_SIZE or (y2 - y1) < MIN_CROP_SIZE:
            continue
        if x2 > x1 and y2 > y1:
            # table 走 cell 级处理：先检 cell，再逐个 cell crop 送 qwen
            if str(label or "").lower() == "table":
                table_crop = original_img[y1:y2, x1:x2]
                stem = Path(image_path).stem
                cell_boxes = await _detect_table_cells(table_crop)
                logger.info(
                    "[table_cell_det] image=%s table_idx=%d bbox=[%d,%d,%d,%d] cells_detected=%d",
                    Path(image_path).name, table_det_index, x1, y1, x2, y2, len(cell_boxes),
                )
                table_det_index += 1
                if cell_boxes:
                    for cx1, cy1, cx2, cy2 in cell_boxes:
                        gx1, gy1 = x1 + cx1, y1 + cy1
                        gx2, gy2 = x1 + cx2, y1 + cy2
                        if (gx2 - gx1) < MIN_CROP_SIZE or (gy2 - gy1) < MIN_CROP_SIZE:
                            continue
                        crop = original_img[gy1:gy2, gx1:gx2]
                        if crop is None or crop.size == 0:
                            continue
                        cropped_images.append(crop)
                        region_bboxes.append((gx1, gy1, gx2, gy2))
                        is_table_cell_crop.append(True)
                    continue
                # table cell 检测失败时回退到原有整块策略，避免漏翻
            crop = original_img[y1:y2, x1:x2]
            cropped_images.append(crop)
            region_bboxes.append((x1, y1, x2, y2))
            is_table_cell_crop.append(False)

    if not cropped_images:
        with tempfile.TemporaryDirectory() as tmp:
            temp_pdf = os.path.join(tmp, "page.pdf")
            image_to_pdf(image_path, temp_pdf)
            pdf_to_jpg(temp_pdf, output_path)
        if on_progress:
            await _call_on_progress(on_progress, 1, 1)
        return (output_path, False) if return_has_text else output_path

    n_crops = len(cropped_images)
    # Tracks table-cell indices that were actually translated (populated in English branch)
    table_cell_translated_indices: set[int] = set()

    img_name = Path(image_path).name

    if _target_is_english(target_language):
        # ── 2-step for English target ────────────────────────────────────────
        # Step 1: OCR-extract all crops (no translation yet)
        logger.info(
            "[llm_call] extract_batch image=%s n_crops=%d bboxes=%s",
            img_name, n_crops, region_bboxes,
        )
        extracted_texts = await qwen_vl_extract_batch(cropped_images)
        extracted_texts = [_normalize_qwen_text(t) for t in extracted_texts]
        if len(extracted_texts) != n_crops:
            extracted_texts = (extracted_texts + [""] * n_crops)[:n_crops]
        for _i, (_bbox, _txt) in enumerate(zip(region_bboxes, extracted_texts)):
            logger.info(
                "[llm_call] extract_result image=%s crop=%d bbox=%s text=%r",
                img_name, _i, _bbox, _txt,
            )

        # Step 2: only translate table-cell crops whose extracted text has non-ASCII letters
        translated_texts = list(extracted_texts)  # default: keep original (no overlay)
        table_cell_indices = [
            i for i, flag in enumerate(is_table_cell_crop) if flag
            and not _is_ascii_only_text(extracted_texts[i])
            and extracted_texts[i]
        ]
        table_cell_translated_indices = set(table_cell_indices)
        if table_cell_indices:
            texts_to_translate = [extracted_texts[i] for i in table_cell_indices]
            for _i, _ci in enumerate(table_cell_indices):
                logger.info(
                    "[llm_call] translate_cell image=%s crop=%d bbox=%s src_text=%r",
                    img_name, _ci, region_bboxes[_ci], texts_to_translate[_i],
                )
            glossary_hint = ""
            if use_glossary:
                try:
                    if texts_to_translate:
                        glossary_hits = await asyncio.to_thread(
                            search_glossary_batch,
                            texts_to_translate,
                            12,
                            12,
                            use_glossary_embedding,
                        )
                        glossary_hint = "\n".join(
                            f"{e['en_term']} = {e['cn_term']}"
                            for e in glossary_hits
                            if e.get("en_term") and e.get("cn_term")
                        )
                except Exception as _glossary_exc:
                    logger.warning("[paddle_ocr] glossary search failed: %s", _glossary_exc)
            translations = await qwen_translate_texts_batch(
                texts_to_translate, target_language, glossary_hint=glossary_hint
            )
            if len(translations) != len(table_cell_indices):
                translations = (translations + [""] * len(table_cell_indices))[:len(table_cell_indices)]
            for idx, translated in zip(table_cell_indices, translations):
                translated_texts[idx] = translated
                logger.info(
                    "[llm_call] translate_result image=%s crop=%d bbox=%s translated=%r",
                    img_name, idx, region_bboxes[idx], translated,
                )

        # Build final_texts: for table cells, use translated_texts; for non-table crops,
        # translated_texts already holds the extracted text (pass-through — no overlay for those
        # either since target is already English). We rely on skip logic below to filter.
        final_texts = translated_texts
        # For non-table-cell crops, run the normal 1-step extract+translate
        non_table_indices = [i for i, flag in enumerate(is_table_cell_crop) if not flag]
        if non_table_indices:
            non_table_crops = [cropped_images[i] for i in non_table_indices]
            logger.info(
                "[llm_call] extract_translate_batch (non-table) image=%s n_crops=%d bboxes=%s",
                img_name, len(non_table_indices), [region_bboxes[i] for i in non_table_indices],
            )
            nt_translated = await qwen_vl_extract_and_translate_batch(
                non_table_crops, target_language=target_language
            )
            if len(nt_translated) != len(non_table_indices):
                nt_translated = (nt_translated + [""] * len(non_table_indices))[:len(non_table_indices)]
            for idx, t in zip(non_table_indices, nt_translated):
                final_texts[idx] = _normalize_qwen_text(t)
                logger.info(
                    "[llm_call] extract_translate_result image=%s crop=%d bbox=%s text=%r",
                    img_name, idx, region_bboxes[idx], final_texts[idx],
                )

    else:
        # ── non-English target ───────────────────────────────────────────────
        # Table cells: 2-step (extract → glossary → translate batch) for glossary support.
        # Non-table crops: original 1-step VLM extract+translate.
        table_cell_indices_ne = [i for i, f in enumerate(is_table_cell_crop) if f]
        non_table_indices_ne = [i for i, f in enumerate(is_table_cell_crop) if not f]
        final_texts = [""] * n_crops

        if non_table_indices_ne:
            logger.info(
                "[llm_call] extract_translate_batch image=%s n_crops=%d target=%s bboxes=%s",
                img_name, len(non_table_indices_ne), target_language,
                [region_bboxes[i] for i in non_table_indices_ne],
            )
            nt_batch = await qwen_vl_extract_and_translate_batch(
                [cropped_images[i] for i in non_table_indices_ne],
                target_language=target_language,
            )
            if len(nt_batch) != len(non_table_indices_ne):
                nt_batch = (nt_batch + [""] * len(non_table_indices_ne))[:len(non_table_indices_ne)]
            for idx, t in zip(non_table_indices_ne, nt_batch):
                final_texts[idx] = _normalize_qwen_text(t)
                logger.info(
                    "[llm_call] extract_translate_result image=%s crop=%d bbox=%s text=%r",
                    img_name, idx, region_bboxes[idx], final_texts[idx],
                )

        if table_cell_indices_ne:
            cell_crops = [cropped_images[i] for i in table_cell_indices_ne]
            logger.info(
                "[llm_call] extract_batch (cells) image=%s n_crops=%d bboxes=%s",
                img_name, len(table_cell_indices_ne),
                [region_bboxes[i] for i in table_cell_indices_ne],
            )
            extracted_cell_texts = await qwen_vl_extract_batch(cell_crops)
            extracted_cell_texts = [_normalize_qwen_text(t) for t in extracted_cell_texts]
            if len(extracted_cell_texts) != len(table_cell_indices_ne):
                extracted_cell_texts = (
                    extracted_cell_texts + [""] * len(table_cell_indices_ne)
                )[:len(table_cell_indices_ne)]
            glossary_hint = ""
            if use_glossary:
                try:
                    glossary_texts = [t for t in extracted_cell_texts if t]
                    if glossary_texts:
                        glossary_hits = await asyncio.to_thread(
                            search_glossary_batch,
                            glossary_texts,
                            12,
                            12,
                            use_glossary_embedding,
                        )
                        glossary_hint = "\n".join(
                            f"{e['en_term']} = {e['cn_term']}"
                            for e in glossary_hits
                            if e.get("en_term") and e.get("cn_term")
                        )
                except Exception as _glossary_exc:
                    logger.warning("[paddle_ocr] glossary search failed: %s", _glossary_exc)
            non_empty_cells = [
                (table_cell_indices_ne[j], extracted_cell_texts[j])
                for j in range(len(table_cell_indices_ne))
                if extracted_cell_texts[j]
            ]
            if non_empty_cells:
                translations = await qwen_translate_texts_batch(
                    [t for _, t in non_empty_cells], target_language, glossary_hint=glossary_hint
                )
                if len(translations) != len(non_empty_cells):
                    translations = (
                        translations + [""] * len(non_empty_cells)
                    )[:len(non_empty_cells)]
                for (idx, _), translated in zip(non_empty_cells, translations):
                    final_texts[idx] = _normalize_qwen_text(translated)
                    logger.info(
                        "[llm_call] translate_result image=%s crop=%d bbox=%s translated=%r",
                        img_name, idx, region_bboxes[idx], final_texts[idx],
                    )

    # Release large numpy arrays now — all VLM calls are done and cropped_images /
    # original_img are no longer needed. Dropping them returns C-heap memory sooner
    # since numpy/Paddle buffers are not freed by Python's cycle GC.
    del cropped_images
    layout_h, layout_w = h, w
    del original_img
    gc.collect()
    _malloc_trim()

    n_regions = len(region_bboxes)
    if len(final_texts) != n_regions:
        logging.warning(
            "[image_translate] region/text count mismatch: regions=%s texts=%s, using first min to avoid misalignment",
            n_regions, len(final_texts),
        )
    n = min(n_regions, len(final_texts))

    # 原图文件尺寸（与 image_to_pdf 后的 PDF 页一致）
    file_img = cv2.imread(image_path)
    file_h, file_w = (file_img.shape[:2] if file_img is not None else (0, 0))
    del file_img
    if file_w <= 0 or file_h <= 0:
        with tempfile.TemporaryDirectory() as tmp:
            temp_pdf = os.path.join(tmp, "page.pdf")
            image_to_pdf(image_path, temp_pdf)
            pdf_to_jpg(temp_pdf, output_path)
        if on_progress:
            await _call_on_progress(on_progress, 1, 1)
        return (output_path, False) if return_has_text else output_path

    scale_x = file_w / layout_w
    scale_y = file_h / layout_h
    blocks = []
    for crop_idx, (x1, y1, x2, y2) in enumerate(region_bboxes[:n]):
        text = final_texts[crop_idx]
        if _should_skip_fillback_text(text):
            continue
        # For English target: skip table-cell fill-back when the cell was not translated
        # (original text was ASCII-only so translation was skipped)
        if (
            _target_is_english(target_language)
            and crop_idx < len(is_table_cell_crop)
            and is_table_cell_crop[crop_idx]
            and crop_idx not in table_cell_translated_indices
        ):
            continue
        # For non-English target: skip fill-back when the translated result is ASCII-only
        # (translation produced no meaningful localised text)
        if (
            not _target_is_english(target_language)
            and crop_idx < len(is_table_cell_crop)
            and is_table_cell_crop[crop_idx]
            and _is_ascii_only_text(text)
        ):
            continue
        bx1 = round(x1 * scale_x)
        by1 = round(y1 * scale_y)
        bx2 = round(x2 * scale_x)
        by2 = round(y2 * scale_y)
        blocks.append({"bbox": [bx1, by1, bx2, by2], "text": text, "is_table_cell": crop_idx < len(is_table_cell_crop) and is_table_cell_crop[crop_idx]})

    translated_page = {"page_size": [file_w, file_h], "blocks": blocks}
    with tempfile.TemporaryDirectory() as tmp:
        temp_pdf = os.path.join(tmp, "page.pdf")
        temp_out_pdf = os.path.join(tmp, "out.pdf")
        image_to_pdf(image_path, temp_pdf)
        draw_single_page_from_middle_on_original(
            temp_pdf, 0, translated_page, temp_out_pdf
        )
        pdf_to_jpg(temp_out_pdf, output_path)

    if on_progress:
        await _call_on_progress(on_progress, 1, 1)
    has_text = bool(blocks)
    return (output_path, has_text) if return_has_text else output_path


async def _call_on_progress(
    on_progress: Callable[[int, int], Any], current: int, total: int
) -> None:
    try:
        if asyncio.iscoroutinefunction(on_progress):
            await on_progress(current, total)
        else:
            on_progress(current, total)
    except Exception:
        pass
