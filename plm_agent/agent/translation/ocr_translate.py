#!/usr/bin/env python3
"""
PDF/图片翻译：支持「仅输入原文件 + 输入/输出语言」一键输出 xxx_translated，不落盘中间文件。

- translate_file(origin_path, target_language, output_path=None, input_language=None):
  一键入口。input_language 为源文档语言（用于 MinerU OCR 模式），target_language 为译文目标语言；
  支持规范名（如 Chinese, English, Japanese）或短码（cn, en, jp）。内部调用 MinerU OCR 再执行翻译。
- translate_pdf: 需已有 middle 数据（文件路径或内存 dict），适合已有 OCR 结果的场景。
- translate_image: 仅做图片翻译（Paddle 版面 + VLM），不依赖 middle。
- [暂时禁用] PDF 内图片描述及注释功能：提取 PDF 内图片、做 BP/DD 描述、在译文 PDF 上添加注释的代码已注释，仅保留原文 PDF 文本翻译。
"""
import sys
from pathlib import Path as _Path

# 直接运行本脚本时，将 noah_agent 加入 path，使 from agent.xxx 可解析
if __name__ == "__main__":
    _root = _Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import asyncio
import base64
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
import inspect
from typing import Any, Callable, Optional

import cv2
import fitz  # PyMuPDF
import numpy as np

# PyMuPDF is not thread-safe: concurrent fitz.open() from asyncio.to_thread
# causes SIGSEGV in MuPDF's internal allocator. Serialize all fitz access.
_fitz_lock = threading.Lock()

# 图片扩展名，用于区分 PDF 与图片输入
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

from agent.translation.llm_translate import (
    llm_detect_language,
    llm_translate_page_blocks,
    llm_translate_page_full_text,
    llm_translate_single_text,
)
from agent.translation.markdown_to_html import markdown_to_html
from agent.translation.glossary.es_search import search_glossary_batch


def clean_text(text):
    # Remove control characters, keep \n, \r, \t
    if not text:
        return text
    return re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', text)


def extract_text_from_block(block, preserve_html=True):
    block_type = block.get("type", "")
    content = block.get("content", {})
    text_parts = []

    if block_type == "title":
        title_content = content.get("title_content", [])
        for item in title_content:
            if item.get("type") == "text":
                text = item.get("content", "")
                if not preserve_html:
                    text = re.sub(r"<[^>]+>", "", text)
                text_parts.append(text)
    elif block_type == "paragraph":
        paragraph_content = content.get("paragraph_content", [])
        for item in paragraph_content:
            item_type = item.get("type")
            if item_type in {"text", "equation_inline"}:
                text = item.get("content", "")
                if not preserve_html:
                    text = re.sub(r"<[^>]+>", "", text)
                text_parts.append(text)
    elif block_type == "list":
        list_items = content.get("list_items", [])
        for item in list_items:
            item_content = item.get("item_content", [])
            for sub_item in item_content:
                sub_item_type = sub_item.get("type")
                if sub_item_type in {"text", "equation_inline"}:
                    text = sub_item.get("content", "")
                    if not preserve_html:
                        text = re.sub(r"<[^>]+>", "", text)
                    text_parts.append(text)

    return " ".join(text_parts).strip()


def extract_text_from_middle_block(block):
    text_parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if span.get("type") == "text":
                text_parts.append(span.get("content", ""))
    return " ".join(part.strip() for part in text_parts if part).strip()

def extract_html_or_text_from_middle_block(block):
    # 1) block 自身带 html（例如部分 table_body / caption）
    html = block.get("html")
    if html:
        return html

    # 2) 有些 middle.json 把表格 HTML 挂在 span 上（span.type == "table"）
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            if span.get("type") == "table" and span.get("html"):
                return span.get("html")

    # 3) 回退到纯文本抽取
    return extract_text_from_middle_block(block)


def convert_relative_to_pdf_rect(bbox_relative, page_width_pixel, page_height_pixel, page_rect):
    x0_rel, y0_rel, x1_rel, y1_rel = bbox_relative

    return fitz.Rect(
        page_rect.x0 + (x0_rel / 1000.0) * page_rect.width,
        page_rect.y0 + (y0_rel / 1000.0) * page_rect.height,
        page_rect.x0 + (x1_rel / 1000.0) * page_rect.width,
        page_rect.y0 + (y1_rel / 1000.0) * page_rect.height,
    )


def convert_normalized_to_pdf_rect(bbox_normalized, page_rect):
    x0_rel, y0_rel, x1_rel, y1_rel = bbox_normalized
    return fitz.Rect(
        page_rect.x0 + x0_rel * page_rect.width,
        page_rect.y0 + y0_rel * page_rect.height,
        page_rect.x0 + x1_rel * page_rect.width,
        page_rect.y0 + y1_rel * page_rect.height,
    )


def convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect):
    page_width_pixel = page_size[0]
    page_height_pixel = page_size[1]
    return fitz.Rect(
        page_rect.x0 + (bbox[0] / page_width_pixel) * page_rect.width,
        page_rect.y0 + (bbox[1] / page_height_pixel) * page_rect.height,
        page_rect.x0 + (bbox[2] / page_width_pixel) * page_rect.width,
        page_rect.y0 + (bbox[3] / page_height_pixel) * page_rect.height,
    )


# 短码 -> 规范语言名（向后兼容）
language_mapping = {
    "cn": "Chinese",
    "kr": "Korean",
    "jp": "Japanese",
    "en": "English",
}

# 语言名/短码 -> MinerU OCR 模式（一语言一模式）
# 参考 MinerU OCR 可选语言：ch, ch_lite, ch_server, en, korean, japan, chinese_cht, ta, te, ka, th, el, latin, arabic, east_slavic, cyrillic, devanagari
LANGUAGE_NAME_TO_OCR_CODE = {
    "Chinese": "ch",
    "English": "en",
    "Chinese Traditional": "chinese_cht",
    "Japanese": "japan",
    "Korean": "korean",
    "Tamil": "ta",
    "Telugu": "te",
    "Kannada": "ka",
    "Thai": "th",
    "Greek": "el",
    "French": "latin",
    "German": "latin",
    "Afrikaans": "latin",
    "Italian": "latin",
    "Spanish": "latin",
    "Bosnian": "latin",
    "Portuguese": "latin",
    "Czech": "latin",
    "Welsh": "latin",
    "Danish": "latin",
    "Estonian": "latin",
    "Irish": "latin",
    "Croatian": "latin",
    "Uzbek": "latin",
    "Hungarian": "latin",
    "Serbian (Latin)": "latin",
    "Indonesian": "latin",
    "Occitan": "latin",
    "Icelandic": "latin",
    "Lithuanian": "latin",
    "Maori": "latin",
    "Malay": "latin",
    "Dutch": "latin",
    "Norwegian": "latin",
    "Polish": "latin",
    "Slovak": "latin",
    "Slovenian": "latin",
    "Albanian": "latin",
    "Swedish": "latin",
    "Swahili": "latin",
    "Tagalog": "latin",
    "Turkish": "latin",
    "Latin": "latin",
    "Azerbaijani": "latin",
    "Kurdish": "latin",
    "Latvian": "latin",
    "Maltese": "latin",
    "Pali": "latin",
    "Romanian": "latin",
    "Vietnamese": "latin",
    "Finnish": "latin",
    "Basque": "latin",
    "Galician": "latin",
    "Luxembourgish": "latin",
    "Romansh": "latin",
    "Catalan": "latin",
    "Quechua": "latin",
    "Arabic": "arabic",
    "Persian": "arabic",
    "Uyghur": "arabic",
    "Urdu": "arabic",
    "Pashto": "arabic",
    "Sindhi": "arabic",
    "Balochi": "arabic",
    "Russian": "east_slavic",
    "Belarusian": "east_slavic",
    "Ukrainian": "east_slavic",
    "Serbian (Cyrillic)": "cyrillic",
    "Bulgarian": "cyrillic",
    "Mongolian": "cyrillic",
    "Abkhazian": "cyrillic",
    "Adyghe": "cyrillic",
    "Kabardian": "cyrillic",
    "Avar": "cyrillic",
    "Dargin": "cyrillic",
    "Ingush": "cyrillic",
    "Chechen": "cyrillic",
    "Lak": "cyrillic",
    "Lezgin": "cyrillic",
    "Tabasaran": "cyrillic",
    "Kazakh": "cyrillic",
    "Kyrgyz": "cyrillic",
    "Tajik": "cyrillic",
    "Macedonian": "cyrillic",
    "Tatar": "cyrillic",
    "Chuvash": "cyrillic",
    "Bashkir": "cyrillic",
    "Malian": "cyrillic",
    "Moldovan": "cyrillic",
    "Udmurt": "cyrillic",
    "Komi": "cyrillic",
    "Ossetian": "cyrillic",
    "Buryat": "cyrillic",
    "Kalmyk": "cyrillic",
    "Tuvan": "cyrillic",
    "Sakha": "cyrillic",
    "Karakalpak": "cyrillic",
    "Hindi": "devanagari",
    "Marathi": "devanagari",
    "Nepali": "devanagari",
    "Bihari": "devanagari",
    "Maithili": "devanagari",
    "Angika": "devanagari",
    "Bhojpuri": "devanagari",
    "Magahi": "devanagari",
    "Santali": "devanagari",
    "Newari": "devanagari",
    "Konkani": "devanagari",
    "Sanskrit": "devanagari",
    "Haryanvi": "devanagari",
}
# 短码别名 -> 规范语言名
LANGUAGE_ALIASES = {
    "cn": "Chinese",
    "en": "English",
    "jp": "Japanese",
    "kr": "Korean",
    "chinese_cht": "Chinese Traditional",
    "japan": "Japanese",
    "korean": "Korean",
    "ta": "Tamil",
    "te": "Telugu",
    "ka": "Kannada",
    "th": "Thai",
    "el": "Greek",
    "latin": "English",
    "arabic": "Arabic",
    "east_slavic": "Russian",
    "cyrillic": "Russian",
    "devanagari": "Hindi",
}


def _normalize_language_name(name_or_code: str) -> str:
    """将输入语言名或短码规范化为规范语言名（用于 LLM 与显示）。"""
    s = (name_or_code or "").strip()
    if not s:
        return "Chinese"
    if s in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[s]
    if s in LANGUAGE_NAME_TO_OCR_CODE:
        return s
    for alias, canonical in LANGUAGE_ALIASES.items():
        if alias.lower() == s.lower():
            return canonical
    for canonical in LANGUAGE_NAME_TO_OCR_CODE:
        if canonical.lower() == s.lower():
            return canonical
    return s


def _get_ocr_code_for_language(name_or_code: str) -> str:
    """根据输入/输出语言名或短码返回 MinerU lang_list 使用的 OCR 模式（一语言一模式）。"""
    name = _normalize_language_name(name_or_code)
    return LANGUAGE_NAME_TO_OCR_CODE.get(name, "ch")


# 描述输出语言在 prompt 中的表述（部分语言用母语标签，其余用英文名）
language_for_description_prompt = {
    "cn": "中文",
    "Chinese": "中文",
    "kr": "韩文",
    "Korean": "韩文",
    "jp": "日文",
    "Japanese": "日文",
    "en": "英文",
    "English": "英文",
    "Chinese Traditional": "繁體中文",
    "Tamil": "Tamil",
    "Telugu": "Telugu",
    "Kannada": "Kannada",
    "Thai": "Thai",
    "Greek": "Greek",
    "French": "French",
    "German": "German",
    "Spanish": "Spanish",
    "Portuguese": "Portuguese",
    "Russian": "Russian",
    "Arabic": "Arabic",
    "Hindi": "Hindi",
    "Vietnamese": "Vietnamese",
    "Indonesian": "Indonesian",
    "Turkish": "Turkish",
    "Polish": "Polish",
    "Dutch": "Dutch",
    "Swedish": "Swedish",
    "Romanian": "Romanian",
    "Hungarian": "Hungarian",
    "Czech": "Czech",
}

# [暂时禁用] BP/DD 图片描述任务 prompt：先类型标签再描述，描述语言由调用方指定
# IMAGE_DESCRIPTION_PROMPT = """这是医药公司商业计划书(BP)和尽职调查(DD)报告的图片处理任务。请先判断图片是否与医药/投资/商业相关。
#
# 输出格式：先输出类型标签（如[图表]、[文字]、[医疗影像]、[装饰]），再输出描述内容。
#
# <需精读> 图表/数据可视化：直接提取关键要点、核心趋势、重要结论，不要逐项描述所有数据点。重点关注：主要趋势方向、关键拐点、显著差异/对比、极值、结论性信息。
#
# <需精读> 纯文字内容、医疗影像、临床数据图表：提取所有关键信息（文字内容、病灶、结构、标注、数据等）。
#
# <粗略提取> 示意图、流程图、架构图：用1-2句话概括主体，不超过30字。
#
# <忽略> 纯装饰图、logo、无关照片：直接返回"[装饰]装饰图，无需描述"或空字符串，不要生成其他内容。
#
# 请根据图片实际内容智能判断类别，并按上述格式和详细程度要求输出。"""


def collect_text_nodes_from_block(block):
    nodes = []
    block_type = block.get("type", "")
    content = block.get("content", {})

    if block_type == "title":
        for item in content.get("title_content", []):
            if item.get("type") == "text":
                nodes.append(item)
    elif block_type == "paragraph":
        for item in content.get("paragraph_content", []):
            if item.get("type") == "text":
                nodes.append(item)
    elif block_type == "list":
        for list_item in content.get("list_items", []):
            for sub_item in list_item.get("item_content", []):
                if sub_item.get("type") == "text":
                    nodes.append(sub_item)
    elif block_type == "image":
        for item in content.get("image_caption", []):
            if item.get("type") == "text":
                nodes.append(item)

    return nodes


_REF_HEADING_SET = {
    "references",
    "reference",
    "bibliography",
    "works cited",
    "literature cited",
    "参考文献",
    "参考资料",
}
_REF_LINE_RE = re.compile(r"^\s*(\[\d+\]|\d+[.)])\s+")
_REF_DOI_RE = re.compile(r"\bdoi\s*[:/]|10\.\d{4,9}/", re.IGNORECASE)
_REF_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _looks_like_reference_text(text: str) -> bool:
    """规则兜底：识别可能漏标为 ref_text 的参考文献行/段。"""
    s = clean_text(text or "").strip()
    if not s:
        return False
    title = s.lstrip("#").strip().rstrip(":：").lower()
    if title in _REF_HEADING_SET:
        return True
    if _REF_LINE_RE.match(s):
        # [1]/1. 开头且含年份/DOI，基本可判定为参考文献条目
        return bool(_REF_YEAR_RE.search(s) or _REF_DOI_RE.search(s) or "et al" in s.lower())
    # 非编号但包含典型参考文献特征：DOI + 年份（或 et al + 年份）
    lower = s.lower()
    if _REF_DOI_RE.search(s) and (_REF_YEAR_RE.search(s) or "et al" in lower):
        return True
    return False


def collect_translatable_middle_blocks(page_info, *, translate_reference: bool = False):
    blocks = []
    # 优先使用 auto/vlm 预处理后的段落块，如果没有再回退到 para_blocks
    block_list = page_info.get("preproc_blocks")
    if not isinstance(block_list, list):
        block_list = page_info.get("para_blocks", [])

    # 1) 主体块：preproc_blocks / para_blocks
    for block in block_list:
        btype = block.get("type")
        if btype in {"title", "text", "index"}:
            text = extract_text_from_middle_block(block)
            if text:
                blocks.append({"bbox": block["bbox"], "text": text})
        elif btype == "ref_text":
            if not translate_reference:
                continue
            text = extract_text_from_middle_block(block)
            if text:
                blocks.append({"bbox": block["bbox"], "text": text})
        elif btype == "list":
            text = extract_text_from_middle_block(block)
            if text:
                blocks.append({"bbox": block["bbox"], "text": text})
            for sub_block in block.get("blocks", []):
                sub_text = extract_text_from_middle_block(sub_block)
                if sub_text:
                    blocks.append({"bbox": sub_block["bbox"], "text": sub_text})
        elif btype == "image":
            for sub_block in block.get("blocks", []):
                sub_type = sub_block.get("type")
                if sub_type in {"image_caption", "image_footnote"}:
                    if sub_block.get("cross_page", False):
                        continue
                    sub_text = extract_html_or_text_from_middle_block(sub_block)
                    if sub_text:
                        blocks.append({"bbox": sub_block["bbox"], "text": sub_text})
        elif btype == "table":
            for sub_block in block.get("blocks", []):
                sub_type = sub_block.get("type")
                if sub_type in {"table_body", "table_caption", "table_footnote"}:
                    if sub_block.get("cross_page", False):
                        continue
                    sub_text = extract_html_or_text_from_middle_block(sub_block)
                    if sub_text:
                        blocks.append({"bbox": sub_block["bbox"], "text": sub_text})
        elif btype == "code":
            for sub_block in block.get("blocks", []):
                if sub_block.get("type") == "code_caption":
                    sub_text = extract_html_or_text_from_middle_block(sub_block)
                    if sub_text:
                        blocks.append({"bbox": sub_block["bbox"], "text": sub_text})
        elif btype in {"table_body", "table_caption", "table_footnote"}:
            # 顶层的表格块（如 auto middle 中的 table_body）也需要翻译，保留 HTML
            sub_text = extract_html_or_text_from_middle_block(block)
            if sub_text:
                blocks.append({"bbox": block["bbox"], "text": sub_text})
        elif btype == "page_footnote":
            # 页脚注说明，同样作为可翻译文本处理，保留 HTML（如 <sup>）
            sub_text = extract_html_or_text_from_middle_block(block)
            if sub_text:
                blocks.append({"bbox": block["bbox"], "text": sub_text})

    # 2) 额外块：有些流水线会把 page_footnote 丢到 discarded_blocks 里
    for block in page_info.get("discarded_blocks", []):
        if block.get("type") == "page_footnote":
            sub_text = extract_html_or_text_from_middle_block(block)
            if sub_text:
                blocks.append({"bbox": block["bbox"], "text": sub_text})

    # interline_equation / image_body / code_body 仍然跳过
    return blocks


def collect_image_bboxes_from_middle(middle_data):
    """
    从 middle 中收集所有图片的页码、bbox 及 MinerU 返回的图片文件名（供从 mineru_images 取裁切图，无需再裁切 PDF）。
    返回 list of dict: {"page_index", "bbox", "page_size", "image_key"}，image_key 为 middle 中 image_path 的文件名（如 xxx.jpg）。
    同时处理两种情况：
      1. type=="image" 块 -> image_body 子块 -> span with type=="image"
      2. type=="table" 块 -> table_body 子块 -> span with type=="table"（table_enable=False 时 MinerU 将表格渲染为图片）
    """
    
    image_infos = []
    for page_index, page_info in enumerate(middle_data.get("pdf_info", [])):
        page_size = page_info.get("page_size", [])
        block_list = page_info.get("preproc_blocks")
        if not isinstance(block_list, list):
            block_list = page_info.get("para_blocks", [])
        for block in block_list or []:
            block_type = block.get("type")
            if block_type == "image":
                sub_type_needle = "image_body"
                span_type_needle = "image"
            elif block_type == "table":
                sub_type_needle = "table_body"
                span_type_needle = "table"
            else:
                continue
            for sub in block.get("blocks", []):
                if sub.get("type") != sub_type_needle:
                    continue
                bbox = sub.get("bbox")
                if not bbox or len(bbox) != 4:
                    break
                image_key = None
                for line in sub.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("type") == span_type_needle and span.get("image_path"):
                            image_key = os.path.basename(span["image_path"])
                            break
                    if image_key:
                        break
                if image_key:
                    image_infos.append({
                        "page_index": page_index,
                        "bbox": bbox,
                        "page_size": page_size or [1, 1],
                        "image_key": image_key,
                        "block_type": block_type,
                    })
                break  # 每个 image/table 块只取一个 image_body/table_body
    return image_infos


async def _call_with_retry(coro_factory, initial_delay=1, backoff=3, max_retries=5):
    """失败后先等 initial_delay 秒重试，每次加重 backoff 秒，最多 max_retries 次。"""
    delay = initial_delay
    last_exc = None
    for attempt in range(max_retries):
        try:
            coro = coro_factory()
            return await coro
        except Exception as e:
            last_exc = e
            if attempt == max_retries - 1:
                raise
            print(f"API call failed (attempt {attempt + 1}/{max_retries}), retry in {delay}s: {e}")
            await asyncio.sleep(delay)
            delay += backoff
    if last_exc is not None:
        raise last_exc


async def _resolve_glossary_enabled(
    middle_data: dict,
    target_language_name: str,
    use_glossary: bool,
) -> bool:
    """Return whether glossary should be used: only for Chinese<->English pairs.
    Detects source language from the first page via LLM. Returns quickly (False) if
    use_glossary is already False so no extra LLM call is made."""
    if not use_glossary:
        return False
    _GLOSSARY_LANGUAGES = {"Chinese", "English"}
    try:
        pdf_info = middle_data.get("pdf_info", [])
        first_page_blocks = collect_translatable_middle_blocks(
            pdf_info[0], translate_reference=False
        ) if pdf_info else []
        first_page_text = " ".join(
            clean_text(b.get("text", "")) for b in first_page_blocks[:20]
        ).strip()
        if first_page_text:
            detected_source = await llm_detect_language(first_page_text)
            detected_source = _normalize_language_name(detected_source) if detected_source else ""
            print(f"[glossary] detected source language: {detected_source}, target: {target_language_name}")
            if detected_source not in _GLOSSARY_LANGUAGES or target_language_name not in _GLOSSARY_LANGUAGES:
                print("[glossary] disabled: source/target language pair not in Chinese-English scope")
                return False
    except Exception as _lang_detect_exc:
        print(f"[glossary] language detection failed, glossary disabled: {_lang_detect_exc}")
        return False
    return True


async def translate_middle_data(
    middle_data,
    target_language="zh-CN",
    *,
    translation_model_id: str = "",
    translate_reference: bool = False,
    on_progress: Optional[Callable[..., Any]] = None,
    on_post_progress: Optional[Callable[..., Any]] = None,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
    resolved_glossary_enabled: Optional[bool] = None,
):
    """纯内存翻译，不读写任何中间文件。返回 translated_pages 供写 PDF。target_language 为规范语言名或短码。
    on_progress(current_page_1based, total_pages, translated_page_data=None) 在每页翻译完成后调用，
    translated_page_data 为该页的 dict（page_size, blocks），用于 PDF 逐页渲染；可为 sync 或 async。

    当 target_language 为空时，LLM 侧采用自动中英互译规则：中文 → 英文，其它语言 → 中文。
    """
    auto_mode = not target_language or not str(target_language).strip()
    # auto_mode 下传递空字符串给 LLM，由 llm_translate_page_full_text 内部决定方向
    target_language_name = "" if auto_mode else _normalize_language_name(target_language)
    translated_pages = []
    prev_full_text = ""
    pdf_info = middle_data.get("pdf_info", [])
    total_pages = len(pdf_info)

    if resolved_glossary_enabled is None:
        glossary_enabled = await _resolve_glossary_enabled(
            middle_data,
            target_language_name,
            use_glossary,
        )
    else:
        glossary_enabled = bool(resolved_glossary_enabled)

    for page_index, page_info in enumerate(pdf_info):
        blocks = collect_translatable_middle_blocks(
            page_info, translate_reference=translate_reference
        )
        if not translate_reference and blocks:
            # 第二层兜底：当 MinerU 未标记 ref_text 时，按规则再过滤一次参考文献样式文本
            before = len(blocks)
            blocks = [b for b in blocks if not _looks_like_reference_text(b.get("text", ""))]
            filtered = before - len(blocks)
            if filtered > 0:
                print(
                    f"page {page_index + 1}: reference-like blocks filtered by rule = {filtered}"
                )
        text_dict = {}
        text_blocks = []
        text_indexes = []

        for block in blocks:
            text = clean_text(block.get("text", ""))
            if text:
                index = str(len(text_blocks))
                text_dict[index] = text
                text_blocks.append(block)
                text_indexes.append(index)
        # 统计本页可翻译文本的总字符数，用于小于等于阈值时直接跳过大模型调用
        total_chars = sum(len(v) for v in text_dict.values())

        page_full_text = ""

        # 若本页可翻译文本总长度 <= 3 个字符，则认为无有效内容：
        # - 不调用大模型翻译，避免无意义的 token 消耗
        # - 不绘制任何覆盖块（保持原始 PDF 页 / 原始图片外观）
        if text_dict and total_chars > 3:
            glossary_hint = ""
            if glossary_enabled:
                try:
                    block_texts = list(text_dict.values())
                    glossary_hits = await asyncio.to_thread(
                        search_glossary_batch,
                        block_texts,
                        12,
                        12,
                        use_glossary_embedding,
                    )
                    if target_language_name == "English":
                        glossary_hint = "\n".join(
                            f"{e['cn_term']} : {e['en_term']}"
                            for e in glossary_hits
                            if e.get("en_term") and e.get("cn_term")
                        )
                    else:
                        glossary_hint = "\n".join(
                            f"{e['en_term']} : {e['cn_term']}"
                            for e in glossary_hits
                            if e.get("en_term") and e.get("cn_term")
                        )
                except Exception as _glossary_exc:
                    print(f"page {page_index + 1}: glossary search failed: {_glossary_exc}")
            print(f"page {page_index + 1}: translate full_text start")
            start_time = time.perf_counter()
            full_text_response = await _call_with_retry(
                lambda: llm_translate_page_full_text(
                    text_dict,
                    target_language_name,
                    prev_full_text=prev_full_text,
                    translation_model_id=translation_model_id,
                    keep_reference_in_original=(not translate_reference),
                    prefer_markdown=True,
                    glossary_hint=glossary_hint,
                ),
                initial_delay=1,
                backoff=3,
            )
            prev_full_text = full_text_response
            page_full_text = (full_text_response or "").strip()
            elapsed = time.perf_counter() - start_time
            print(f"page {page_index + 1}: translate full_text done ({elapsed:.2f}s)")

            print(f"page {page_index + 1}: translate blocks start")
            start_time = time.perf_counter()
            blocks_response = await _call_with_retry(
                lambda: llm_translate_page_blocks(
                    text_dict,
                    full_text_response,
                    target_language_name,
                    translation_model_id=translation_model_id,
                    keep_reference_in_original=(not translate_reference),
                    prefer_markdown=True,
                    glossary_hint=glossary_hint,
                ),
                initial_delay=1,
                backoff=3,
            )
            elapsed = time.perf_counter() - start_time
            print(f"page {page_index + 1}: translate blocks done ({elapsed:.2f}s)")

            for index, block in enumerate(text_blocks):
                translated_text = blocks_response.get(str(index))
                if isinstance(translated_text, str):
                    block["text"] = translated_text.rstrip("\n")

        # 当 total_chars <= 3 时，blocks 置空以避免在该页画白底或写入任何文字；
        # 否则使用翻译后的 text_blocks。
        if total_chars <= 3:
            page_blocks_for_draw = []
        else:
            page_blocks_for_draw = text_blocks

        translated_pages.append(
            {
                "page_size": page_info.get("page_size", []),
                "blocks": page_blocks_for_draw,
                "full_text": page_full_text,
            }
        )
        if on_progress:
            page_data = translated_pages[-1]
            try:
                res = on_progress(page_index + 1, total_pages, page_data)
            except TypeError:
                res = on_progress(page_index + 1, total_pages)
            if inspect.iscoroutine(res):
                await res
        if on_post_progress:
            page_data = translated_pages[-1]
            try:
                post_res = on_post_progress(page_index + 1, total_pages, page_data)
            except TypeError:
                post_res = on_post_progress(page_index + 1, total_pages)
            if inspect.iscoroutine(post_res):
                await post_res

    return translated_pages


def _build_pdf_full_text_markdown(page_full_texts: list[str]) -> str:
    """将 PDF 各页 full text 合并为单个 markdown 文本。"""
    sections = []
    for i, text in enumerate(page_full_texts, start=1):
        body = (text or "").strip()
        sections.append(f"## Page {i}\n\n{body}")
    return "\n\n".join(sections).strip()


def image_to_pdf(image_path: str, pdf_path: Optional[str] = None) -> str:
    """将单张图片（jpg/png 等）转为单页 PDF：新建 PDF、按图片尺寸建一页并插入图片再保存。"""
    img_doc = fitz.open(image_path)
    if len(img_doc) == 0:
        img_doc.close()
        raise ValueError(f"Image has no pages: {image_path}")
    rect = img_doc[0].rect
    img_doc.close()

    pdf_doc = fitz.open()
    pdf_page = pdf_doc.new_page(width=rect.width, height=rect.height)
    pdf_page.insert_image(pdf_page.rect, filename=image_path)
    if pdf_path is None:
        pdf_path = str(Path(image_path).with_suffix(".pdf"))
    pdf_doc.save(pdf_path)
    pdf_doc.close()
    return pdf_path


def pdf_to_jpg(pdf_path: str, jpg_path: Optional[str] = None, dpi: int = 150) -> str:
    """将单页 PDF 渲染为 JPG 图片。"""
    with _fitz_lock:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            raise ValueError(f"PDF has no pages: {pdf_path}")
        if jpg_path is None:
            jpg_path = str(Path(pdf_path).with_suffix(".jpg"))
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        doc.close()
    pix.save(jpg_path)
    return jpg_path


def extract_pdf_region_to_jpg(
    pdf_path: str,
    page_index: int,
    bbox: list,
    page_size: list,
    jpg_path: str,
    dpi: int = 150,
) -> str:
    """
    从 PDF 指定页按 middle 的 bbox（像素坐标）裁剪区域并保存为 JPG。
    用于将文档内图片区域导出，供图片翻译或描述用。
    """
    with _fitz_lock:
        doc = fitz.open(pdf_path)
        if page_index >= len(doc):
            doc.close()
            raise ValueError(f"PDF page_index {page_index} out of range")
        page = doc[page_index]
        page_rect = page.rect
        rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect)
        pix = page.get_pixmap(clip=rect, dpi=dpi, alpha=False)
        pix.save(jpg_path)
        doc.close()
    return jpg_path


def extract_pdf_region_to_bytes(
    pdf_path: str,
    page_index: int,
    bbox: list,
    page_size: list,
    dpi: int = 150,
) -> bytes:
    """
    从 PDF 指定页按 bbox 裁剪区域，在内存中编码为 JPG 并返回 bytes，不落盘。
    """
    with _fitz_lock:
        doc = fitz.open(pdf_path)
        if page_index >= len(doc):
            doc.close()
            raise ValueError(f"PDF page_index {page_index} out of range")
        page = doc[page_index]
        page_rect = page.rect
        rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect)
        pix = page.get_pixmap(clip=rect, dpi=dpi, alpha=False)
        samples = bytes(pix.samples)
        height, width, n = pix.height, pix.width, pix.n
        doc.close()
    img = np.frombuffer(samples, dtype=np.uint8).reshape(height, width, n)
    if img.shape[-1] == 4:
        img = img[..., :3]
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    _, buf = cv2.imencode(".jpg", img_bgr)
    return buf.tobytes()


def _mineru_image_to_bytes(data_url_or_base64: str) -> bytes:
    """将 MinerU 返回的 data:image/jpeg;base64,... 或纯 base64 转为 bytes。"""
    s = data_url_or_base64.strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    return base64.b64decode(s)


def _prepare_one_input_bytes(
    i: int,
    info: dict,
    tmp_dir: str,
    origin_pdf_path: str,
    mineru_images: Optional[dict],
) -> tuple:
    """
    为第 i 张图准备输入（内存 bytes）和输出路径；在 asyncio.to_thread 中并行调用。
    返回 (info, image_bytes, translated_jpg_path)，失败则抛异常。
    """
    translated_jpg_path = os.path.join(tmp_dir, f"img_{i}_translated.jpg")
    image_key = info.get("image_key")
    if mineru_images and image_key and image_key in mineru_images:
        image_bytes = _mineru_image_to_bytes(mineru_images[image_key])
    else:
        image_bytes = extract_pdf_region_to_bytes(
            origin_pdf_path,
            info["page_index"],
            info["bbox"],
            info["page_size"],
            dpi=300,
        )
    return (info, image_bytes, translated_jpg_path)


async def translate_images_for_one_pdf_page(
    *,
    origin_pdf_path: str,
    page_image_infos: list,
    tmp_dir: str,
    mineru_images: Optional[dict],
    out_lang: str,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> list:
    """
    按页翻译 PDF 内图片（准备阶段并行 + 翻译阶段并发），返回该页可回填 annotations。
    annotations: [{"page_index", "bbox", "page_size", "translated_jpg_path"}]
    """
    if not page_image_infos:
        return []
    prepare_tasks = [
        asyncio.to_thread(
            _prepare_one_input_bytes,
            info.get("_global_idx", i),
            info,
            tmp_dir,
            origin_pdf_path,
            mineru_images,
        )
        for i, info in enumerate(page_image_infos)
    ]
    results_prepare = await asyncio.gather(*prepare_tasks, return_exceptions=True)
    tasks_inputs = []
    for i, r in enumerate(results_prepare):
        if isinstance(r, Exception):
            print(f"image {i} crop skip: {r}")
            continue
        tasks_inputs.append(r)
    if not tasks_inputs:
        return []

    async def translate_one(info, image_bytes, translated_jpg_path):
        result = await translate_image_from_bytes(
            image_bytes=image_bytes,
            output_path=translated_jpg_path,
            target_language=out_lang,
            return_has_text=True,
            is_table=info.get("block_type") == "table",
            use_glossary=use_glossary,
            use_glossary_embedding=use_glossary_embedding,
        )
        if isinstance(result, tuple):
            _out_path, has_text = result
        else:
            has_text = True
        return info, translated_jpg_path, bool(has_text)

    results = await asyncio.gather(
        *[translate_one(info, b, out) for info, b, out in tasks_inputs],
        return_exceptions=True,
    )
    annotations = []
    for r in results:
        if isinstance(r, Exception):
            print(f"image translation skip: {r}")
            continue
        info, translated_jpg_path, has_text = r
        if not has_text:
            print(
                f"[PDF image] skip fill-back(no text): page={info['page_index']}, out={translated_jpg_path}"
            )
            continue
        if os.path.isfile(translated_jpg_path):
            annotations.append(
                {
                    "page_index": info["page_index"],
                    "bbox": info["bbox"],
                    "page_size": info["page_size"],
                    "translated_jpg_path": translated_jpg_path,
                }
            )
            print(
                f"[PDF image] translated ok: page={info['page_index']}, out={translated_jpg_path}, size={os.path.getsize(translated_jpg_path)}"
            )
        else:
            print(f"[PDF image] translated file missing: {translated_jpg_path}")
    return annotations


# [暂时禁用] 对单张 JPG 调用 Gemini 做 BP/DD 图片描述
# def _describe_image_with_gemini(jpg_path: str, output_language: str) -> str:
#     """
#     对单张 JPG 调用 Gemini 做 BP/DD 图片描述：类型标签 + 描述内容，描述语言与 output_language 一致。
#     output_language: 规范语言名或短码（如 Chinese / cn / English / en）。
#     """
#     with open(jpg_path, "rb") as f:
#         image_bytes = f.read()
#     mime_type = _mime_type_from_image_path(jpg_path)
#     normalized = _normalize_language_name(output_language)
#     lang_label = language_for_description_prompt.get(normalized, normalized)
#     prompt = IMAGE_DESCRIPTION_PROMPT + f"\n\n请使用{lang_label}输出类型标签和描述内容，不要其他解释。"
#     contents = [
#         types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
#         prompt,
#     ]
#     response = client.models.generate_content(
#         model="gemini-3-flash-preview",
#         contents=contents,
#         config=types.GenerateContentConfig(
#             temperature=0,
#             thinking_config=types.ThinkingConfig(thinking_level="minimal"),
#         ),
#     )
#     return (response.text or "").strip()


# [暂时禁用] 对单张 JPG 做 BP/DD 图片描述，结果作为 PDF 内图片注释
# async def get_translated_ocr_for_image(jpg_path: str, output_language: str = "Chinese") -> str:
#     """
#     对单张 JPG 做 BP/DD 图片描述：类型标签 + 描述内容，描述语言与 output_language 一致。
#     结果作为图片注释内容（悬停可见），不遮挡正文/图片。
#     """
#     return await asyncio.to_thread(_describe_image_with_gemini, jpg_path, output_language)


# [暂时禁用] 在翻译后的 PDF 上为每张图片添加描述注释
# def add_image_ocr_annotations(
#     pdf_path: str,
#     annotations: list,
# ) -> None:
#     """
#     在翻译后的 PDF 上为每张图片添加注释：在图片一角放小图标，悬停可见描述内容，不遮挡正文和图片本身。
#     annotations: list of {"page_index", "bbox", "page_size", "translated_text"}，translated_text 为图片描述（类型标签+内容）。
#     """
#     if not annotations:
#         return
#     doc = fitz.open(pdf_path)
#     for item in annotations:
#         page_index = item.get("page_index", 0)
#         bbox = item.get("bbox", [])
#         page_size = item.get("page_size", [1, 1])
#         text = item.get("translated_text", "").strip()
#         if not text or page_index >= len(doc) or len(bbox) != 4:
#             continue
#         page = doc[page_index]
#         page_rect = page.rect
#         rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect)
#         # 注释图标放在图片右上角内侧，小矩形不挡住主体（约 18pt 图标区）
#         icon_size = 18
#         point = fitz.Point(rect.x1 - icon_size, rect.y0 + icon_size * 0.5)
#         page.add_text_annot(point, text)
#     # 保存到原路径时 PyMuPDF 要求必须 incremental；非 incremental 又会触发加密/垃圾回收限制。
#     # 改为先保存到临时文件再替换原文件，避免 "save to original must be incremental" 错误。
#     fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(pdf_path) or ".")
#     try:
#         os.close(fd)
#         doc.save(tmp_path, deflate=True)
#         doc.close()
#         doc = None
#         os.replace(tmp_path, pdf_path)
#     finally:
#         if doc is not None:
#             doc.close()
#         if os.path.exists(tmp_path):
#             try:
#                 os.unlink(tmp_path)
#             except OSError:
#                 pass


def add_image_translations_to_pdf(pdf_path: str, annotations: list) -> None:
    """
    在翻译后的 PDF 上把每张原文图片区域替换为翻译后的图片（贴图回填）。
    annotations: list of {"page_index", "bbox", "page_size", "translated_jpg_path"}。
    使用 redact 彻底移除原图 XObject 后再插入译图，避免原图数据残留造成文件体积翻倍。
    """
    if not annotations:
        print("[PDF image fill-back] annotations empty, return")
        return

    # Group by page so we can apply_redactions once per page (more efficient and correct).
    by_page: dict[int, list] = {}
    for item in annotations:
        by_page.setdefault(item.get("page_index", 0), []).append(item)

    doc = fitz.open(pdf_path)
    filled = 0
    for page_index, items in by_page.items():
        if page_index >= len(doc):
            continue
        page = doc[page_index]
        page_rect = page.rect

        # Pre-decode all translated images and compute rects; skip invalid items early.
        valid: list[tuple] = []  # (rect, img_bytes)
        for item in items:
            bbox = item.get("bbox", [])
            page_size = item.get("page_size", [1, 1])
            translated_jpg_path = item.get("translated_jpg_path", "").strip()
            if not translated_jpg_path or len(bbox) != 4:
                print(f"[PDF image fill-back] skip: missing path/bbox")
                continue
            if not os.path.isfile(translated_jpg_path):
                print(f"[PDF image fill-back] skip: file not found {translated_jpg_path}")
                continue
            rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect).normalize()
            # Re-encode at reduced quality to keep PDF size small.
            raw = open(translated_jpg_path, "rb").read()
            arr = np.frombuffer(raw, dtype=np.uint8)
            img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img_bgr is not None:
                _, buf = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
                img_bytes = buf.tobytes()
            else:
                img_bytes = raw
            valid.append((rect, img_bytes))
            # Add redact annotation so apply_redactions physically removes the original
            # image XObject from the page content stream. Using draw_rect instead would
            # merely paint white on top, leaving the original image data in the file.
            # FIX: draw_rect instead of add_redact_annot (apply_redactions crashes in PyMuPDF 1.27.x)
            page.draw_rect(rect, color=None, fill=(1, 1, 1))

        if not valid:
            continue

        # Insert translated images into the cleared regions.
        for rect, img_bytes in valid:
            page.insert_image(rect, stream=img_bytes)
            filled += 1

    print(f"[PDF image fill-back] drew {filled} images, saving to {pdf_path}")
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(pdf_path) or ".")
    try:
        os.close(fd)
        # FIX: tobytes(garbage=0) instead of save(garbage=4, clean=True) (PyMuPDF 1.27.x segfault)
        pdf_bytes = doc.tobytes(garbage=0)
        doc.close()
        doc = None
        with open(tmp_path, 'wb') as _f:
            _f.write(pdf_bytes)
        os.replace(tmp_path, pdf_path)
        print(f"[PDF image fill-back] done, replaced {pdf_path}")
    finally:
        if doc is not None:
            doc.close()
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def draw_layout_from_middle(translated_pages, pdf_path, output_path):
    doc = fitz.open(pdf_path)
    ocg_xref = doc.add_ocg("Translated", on=True)

    for page_index, page in enumerate(doc):
        if page_index >= len(translated_pages):
            break
        page_rect = page.rect
        page_data = translated_pages[page_index]
        page_size = page_data.get("page_size", [page_rect.width, page_rect.height])

        blocks_to_draw = []
        for block in page_data.get("blocks", []):
            text_content = clean_text(block.get("text", ""))
            if not text_content:
                continue
            bbox = block.get("bbox", [])
            if len(bbox) != 4:
                continue
            rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect)
            blocks_to_draw.append((rect, text_content))

        # Draw white filled rectangles to cover original text visually.
        # Previously used add_redact_annot+apply_redactions but that caused
        # a PyMuPDF 1.27.x segfault (worker crash) on certain PDF pages.
        for rect, _ in blocks_to_draw:
            page.draw_rect(rect, color=None, fill=(1, 1, 1), oc=ocg_xref)

        css = "html, body { margin: 0; padding: 0; } * { font-size: 50pt; }"
        for rect, text_content in blocks_to_draw:
            # 贴块为 Markdown 输出，需转为 HTML 供 insert_htmlbox 使用
            text_content = markdown_to_html(text_content)
            page.insert_htmlbox(rect, text_content, css=css, oc=ocg_xref)

    # doc.subset_fonts()  # Disabled: causes PyMuPDF hang/infinite loop
    # Use tobytes() + write to disk to avoid PyMuPDF 1.27.x segfault in doc.save() on certain PDFs.
    pdf_bytes = doc.tobytes(garbage=0)
    with open(output_path, 'wb') as _f:
        _f.write(pdf_bytes)


def draw_single_page_from_middle_on_original(
    origin_pdf_path: str,
    page_index_0based: int,
    translated_page: dict,
    output_pdf_path: str,
) -> None:
    """
    在原 PDF 的指定页上叠加白底+译文，输出为单页 PDF（与 draw_layout_from_middle 单页逻辑一致）。
    先复制原 PDF 该页到新文档，再在该页上画 white rect + 译文，供逐页导出图片用。
    """
    with _fitz_lock:
        doc_orig = fitz.open(origin_pdf_path)
        if page_index_0based >= len(doc_orig):
            doc_orig.close()
            raise ValueError(f"page_index {page_index_0based} out of range for {origin_pdf_path}")
        doc_new = fitz.open()
        doc_new.insert_pdf(doc_orig, from_page=page_index_0based, to_page=page_index_0based)
        doc_orig.close()
        page = doc_new[0]
        page_rect = page.rect
        page_size = translated_page.get("page_size", [page_rect.width, page_rect.height])
        ocg_xref = doc_new.add_ocg("Translated", on=True)
        blocks_to_draw = []
        for block in translated_page.get("blocks", []):
            text_content = clean_text(block.get("text", ""))
            if not text_content:
                continue
            bbox = block.get("bbox", [])
            if len(bbox) != 4:
                continue
            rect = convert_middle_bbox_to_pdf_rect(bbox, page_size, page_rect)
            blocks_to_draw.append((rect, text_content, block.get("is_table_cell", False)))

        # FIX: draw_rect instead of apply_redactions (PyMuPDF 1.27.x segfault)
        for rect, _, _ in blocks_to_draw:
            page.draw_rect(rect, color=None, fill=(1, 1, 1), oc=ocg_xref)

        css = "html, body { margin: 0; padding: 0; } * { font-size: 50pt; }"
        for rect, text_content, is_table_cell in blocks_to_draw:
            # 贴块为 Markdown 输出，需转为 HTML 供 insert_htmlbox 使用
            text_content = markdown_to_html(text_content)
            if is_table_cell:
                page.draw_rect(rect, color=(0, 0, 0), fill=None, width=0.5, oc=ocg_xref)
            page.insert_htmlbox(rect, text_content, css=css, oc=ocg_xref)
        # FIX: tobytes(garbage=0) instead of save(garbage=4, clean=True) (PyMuPDF 1.27.x segfault)
        pdf_bytes = doc_new.tobytes(garbage=0)
        doc_new.close()
    with open(output_pdf_path, 'wb') as _f:
        _f.write(pdf_bytes)


def _write_mineru_image_to_jpg(data_url_or_base64: str, jpg_path: str) -> None:
    """将 MinerU 返回的 data:image/jpeg;base64,... 或纯 base64 写入 jpg 文件。"""
    s = data_url_or_base64.strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[-1]
    raw = base64.b64decode(s)
    with open(jpg_path, "wb") as f:
        f.write(raw)


async def _detect_pdf_language(pdf_path: str) -> str:
    """
    Extract embedded text from the first 2 pages of a PDF and detect its language.
    Returns a canonical language name (e.g. 'Chinese', 'English'), or '' if detection fails.
    Falls back to '' for scanned PDFs with no embedded text.
    """
    try:
        doc = fitz.open(pdf_path)
        parts = []
        for page in doc[:2]:
            parts.append(page.get_text())
        doc.close()
        text = " ".join(parts).strip()
        if not text:
            return ""
        return await llm_detect_language(text[:1000])
    except Exception as e:
        print(f"[detect_pdf_language] failed: {e}")
        return ""


async def translate_pdf(
    origin_pdf_path: str,
    output_path: Optional[str] = None,
    target_language: str = "zh-CN",
    *,
    translation_model_id: str = "",
    translate_reference: bool = False,
    input_language: Optional[str] = None,
    middle_json_path: Optional[str] = None,
    middle_data: Optional[dict] = None,
    mineru_images: Optional[dict] = None,
    add_image_ocr_annotations_flag: bool = False,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    on_page_image_progress: Optional[Callable[..., Any]] = None,
    return_extra: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
):
    """
    只读 middle 和原 PDF，只写一个 translated 文件。middle 由 middle_json_path 或 middle_data 其一提供。
    若 add_image_ocr_annotations_flag 为 True，会对 PDF 内每张图片调用图片翻译接口得到译文图，并回填到译文 PDF 对应 bbox（与正文白底+译文回填类似，此处为贴图回填）。

    :param origin_pdf_path: 原始 PDF 路径
    :param output_path: 输出 PDF 路径；若为 None 则用与 origin 同目录下的 <stem>_translated.pdf
    :param target_language: 译文与图片翻译的目标语言；规范名或短码，如 Chinese / cn / English / en
    :param input_language: 源文档语言，用于 MinerU OCR 模式（本函数内未用，由 translate_file 传 MinerU）
    :param middle_json_path: middle.json 文件路径（与 middle_data 二选一）
    :param middle_data: 内存中的 middle 字典（与 middle_json_path 二选一）
    :param mineru_images: MinerU 返回的裁切图 dict，用于优先取裁切图作为图片翻译输入，无则从 PDF 按 bbox 裁切
    :param add_image_ocr_annotations_flag: 是否为 PDF 内图片做翻译并回填（仅 PDF 输出）
    :param on_page_image_progress: 每页图片翻译完成后的回调（可用于上传“图片回填后”页图）
    """
    out_lang = _normalize_language_name(target_language)
    if middle_data is None:
        if not middle_json_path:
            raise ValueError("必须提供 middle_json_path 或 middle_data")
        with open(middle_json_path, "r", encoding="utf-8") as f:
            middle_data = json.load(f)

    # Resolve glossary once here so both text and image translation paths share the same decision.
    # If source language is already known (from input_language or earlier auto-detect),
    # avoid an extra LLM language-detection call.
    _GLOSSARY_LANGUAGES = {"Chinese", "English"}
    source_lang_name = _normalize_language_name(input_language) if input_language else ""
    if not use_glossary:
        resolved_glossary = False
    elif source_lang_name:
        resolved_glossary = (
            source_lang_name in _GLOSSARY_LANGUAGES and out_lang in _GLOSSARY_LANGUAGES
        )
        if not resolved_glossary:
            print(
                "[glossary] disabled: source/target language pair not in Chinese-English scope "
                f"(source={source_lang_name}, target={out_lang})"
            )
    else:
        resolved_glossary = await _resolve_glossary_enabled(middle_data, out_lang, use_glossary)

    total_pages = len(middle_data.get("pdf_info", []))
    if on_progress:
        try:
            res = on_progress(0, total_pages, None)
        except TypeError:
            res = on_progress(0, total_pages)
        if inspect.iscoroutine(res):
            await res

    image_post_tasks = []
    image_annotations = []
    image_infos_by_page = {}
    image_tmp_ctx = None
    image_tmp_dir = ""
    image_worker_sem = asyncio.Semaphore(3)

    if add_image_ocr_annotations_flag:
        # Write image_infos to a debug file
        debug_file = os.path.join(image_tmp_dir, "image_infos_debug.json")
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(middle_data, f, indent=2, ensure_ascii=False)
        print(f"[PDF image] debug: image_infos written to {debug_file}")
        image_infos = collect_image_bboxes_from_middle(middle_data)
        print(f"[PDF image] collect_image_bboxes_from_middle: {len(image_infos)} images")
        for idx, inf in enumerate(image_infos):
            info = dict(inf)
            info["_global_idx"] = idx
            image_infos_by_page.setdefault(info.get("page_index", -1), []).append(info)
            print(
                f"  image {idx}: page={inf.get('page_index')}, bbox={inf.get('bbox')}, page_size={inf.get('page_size')}, image_key={inf.get('image_key')}"
            )
        image_tmp_ctx = tempfile.TemporaryDirectory()
        image_tmp_dir = image_tmp_ctx.name

    async def _process_page_images_async(current_page: int, total_pages: int, page_data: dict):
        if not add_image_ocr_annotations_flag:
            return
        page_index_0based = current_page - 1
        page_image_infos = image_infos_by_page.get(page_index_0based, [])
        if not page_image_infos:
            return
        page_annotations = None
        async with image_worker_sem:
            try:
                page_annotations = await asyncio.wait_for(
                    translate_images_for_one_pdf_page(
                        origin_pdf_path=origin_pdf_path,
                        page_image_infos=page_image_infos,
                        tmp_dir=image_tmp_dir,
                        mineru_images=mineru_images,
                        out_lang=out_lang,
                        use_glossary=resolved_glossary,
                        use_glossary_embedding=use_glossary_embedding,
                    ),
                    timeout=240.0
                )
            except asyncio.TimeoutError:
                print(f"[PDF image] page {current_page} image translation TIMEOUT (120s limit). Skipping.")
            except Exception as e:
                print(f"[PDF image] page {current_page} image translation FAILED: {e}. Skipping.")
        if page_annotations:
            image_annotations.extend(page_annotations)
            if on_page_image_progress:
                try:
                    res = on_page_image_progress(
                        current_page,
                        total_pages,
                        page_data,
                        page_annotations,
                    )
                except TypeError:
                    res = on_page_image_progress(current_page, total_pages, page_data)
                if inspect.iscoroutine(res):
                    await res

    def _schedule_page_image_task(current_page: int, total_pages: int, page_data: dict):
        if not add_image_ocr_annotations_flag:
            return
        if page_data is None:
            return
        task = asyncio.create_task(
            _process_page_images_async(current_page, total_pages, page_data)
        )
        image_post_tasks.append(task)

    try:
        translated_pages = await translate_middle_data(
            middle_data,
            target_language=out_lang,
            translation_model_id=translation_model_id,
            translate_reference=translate_reference,
            on_progress=on_progress,
            on_post_progress=_schedule_page_image_task if add_image_ocr_annotations_flag else None,
            use_glossary=resolved_glossary,
            use_glossary_embedding=use_glossary_embedding,
            resolved_glossary_enabled=resolved_glossary,
        )
        page_full_texts = [
            (p.get("full_text", "") or "").strip() for p in translated_pages
        ]
        translated_md_content = _build_pdf_full_text_markdown(page_full_texts)

        if output_path is None:
            origin = Path(origin_pdf_path)
            output_path = str(origin.parent / f"{origin.stem}_translated.pdf")

        draw_layout_from_middle(
            translated_pages=translated_pages,
            pdf_path=origin_pdf_path,
            output_path=output_path,
        )

        if image_post_tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*image_post_tasks, return_exceptions=True),
                    timeout=900.0
                )
                for i, r in enumerate(results):
                    if isinstance(r, Exception):
                        print(f"[PDF image] page image task {i} failed: {r}")
            except asyncio.TimeoutError:
                print("[PDF image] overall image post tasks TIMEOUT (600s limit). Proceeding with doc finalization.")
            except Exception as e:
                print(f"[PDF image] overall image post tasks failed: {e}. Proceeding with doc finalization.")
        if add_image_ocr_annotations_flag:
            print(f"[PDF image] fill-back: {len(image_annotations)} images to paste into {output_path}")
            if image_annotations:
                add_image_translations_to_pdf(output_path, image_annotations)
            else:
                print("[PDF image] no image_annotations, skip add_image_translations_to_pdf")
        if return_extra:
            return output_path, {
                "translated_md_content": translated_md_content,
            }
        return output_path
    finally:
        for task in image_post_tasks:
            if not task.done():
                task.cancel()
        if image_tmp_ctx is not None:
            image_tmp_ctx.cleanup()


async def translate_image(
    image_path: str,
    output_path: Optional[str] = None,
    target_language: str = "zh-CN",
    *,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    use_glossary_embedding: bool = True,
):
    """
    输入一张图片（jpg/png 等），使用 Paddle 版面检测 + VLM 提取并翻译，输出翻译后的 JPG。
    不依赖 middle，不落盘中间文件；内部：Paddle 版面 → 裁剪 → VLM 翻译 → 回填 → JPG。
    """
    from agent.translation.paddle_ocr import translate_image_to_jpg
    return await translate_image_to_jpg(
        image_path=image_path,
        output_path=output_path,
        target_language=target_language,
        on_progress=on_progress,
        use_glossary_embedding=use_glossary_embedding,
    )


async def translate_image_from_bytes(
    image_bytes: bytes,
    output_path: str,
    target_language: str = "zh-CN",
    return_has_text: bool = False,
    is_table: bool = False,
    *,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> Any:
    """
    输入图片的内存 bytes（JPG），调用 Paddle+VLM 翻译并写出到 output_path。
    用于 PDF 内图翻译时不落盘输入图，仅在 paddle 内部写一次临时文件。
    """
    from agent.translation.paddle_ocr import translate_image_to_jpg_from_bytes
    return await translate_image_to_jpg_from_bytes(
        image_bytes=image_bytes,
        output_path=output_path,
        target_language=target_language,
        return_has_text=return_has_text,
        is_table=is_table,
        use_glossary=use_glossary,
        use_glossary_embedding=use_glossary_embedding,
    )


async def translate_file(
    origin_path: str,
    target_language: str = "zh-CN",
    output_path: Optional[str] = None,
    *,
    translation_model_id: str = "",
    translate_reference: bool = False,
    input_language: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], Any]] = None,
    on_page_image_progress: Optional[Callable[..., Any]] = None,
    return_extra: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
):
    """
    一键翻译：输入原始待翻译文件（PDF 或 jpg/png 等）+ 输入/目标语言，仅输出一个 xxx_translated 文件。
    - 图片：走 Paddle + VLM 流程，不调用 MinerU。
    - PDF：内部调用 MinerU OCR 获取 middle 后执行翻译。

    :param origin_path: 原始文件路径（支持 .pdf、.jpg、.jpeg、.png 等）
    :param target_language: 译文目标语言；规范名或短码，如 cn / en / Chinese / English
    :param output_path: 输出路径；若为 None 则与 origin 同目录，名为 <stem>_translated.<pdf|jpg>
    :param input_language: 源文档语言，仅 PDF 时用于 MinerU OCR；不传则用 target_language
    :return: 输出文件路径；当 return_extra=True 时返回 (输出文件路径, 额外信息 dict)
    """
    path = Path(origin_path)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {origin_path}")

    if path.suffix.lower() in IMAGE_EXTENSIONS:
        image_out_path = await translate_image(
            image_path=origin_path,
            output_path=output_path,
            target_language=target_language,
            on_progress=on_progress,
            use_glossary_embedding=use_glossary_embedding,
        )
        if return_extra:
            return image_out_path, {}
        return image_out_path

    from agent.translation.mineru_ocr import call_mineru_and_get_middle_and_images
    if input_language:
        in_lang = _normalize_language_name(input_language)
    else:
        detected = await _detect_pdf_language(origin_path)
        if detected:
            in_lang = _normalize_language_name(detected)
            print(f"[translate_file] auto-detected source language: {in_lang}")
        else:
            in_lang = "Chinese"  # safe default for scanned PDFs with no embedded text
            print(f"[translate_file] language detection failed, defaulting to: {in_lang}")
    ocr_code = _get_ocr_code_for_language(in_lang)
    # 请求 MinerU 同时返回裁切图，供 PDF 内图片翻译时优先使用。
    # 使用 asyncio.to_thread 将同步阻塞的 HTTP 请求移入线程池，
    # 避免阻塞事件循环，使得并发的原文件逐页渲染任务能同时推进。
    middle_data, mineru_images = await asyncio.to_thread(
        call_mineru_and_get_middle_and_images,
        origin_path,
        lang_list=[ocr_code],
        return_images=True,
    )
    if middle_data is None:
        raise ValueError("MinerU 未返回 middle 数据，无法继续翻译")
    print(f"middle_data: {middle_data}")
    print(
        f"[translate_file] mineru_images returned: {'Yes' if mineru_images else 'No'}"
        + (f" ({len(mineru_images)} keys: {list(mineru_images.keys())[:5]})" if mineru_images else "")
    )
    return await translate_pdf(
        origin_pdf_path=origin_path,
        output_path=output_path,
        target_language=target_language,
        translation_model_id=translation_model_id,
        translate_reference=translate_reference,
        input_language=in_lang,
        middle_data=middle_data,
        mineru_images=mineru_images,
        add_image_ocr_annotations_flag=True,  # 对 PDF 内图片做翻译并回填
        on_progress=on_progress,
        on_page_image_progress=on_page_image_progress,
        return_extra=return_extra,
        use_glossary=use_glossary,
        use_glossary_embedding=use_glossary_embedding,
    )


async def process_translation_by_attachment_id(
    attachment_id: str,
    target_language: str,
    input_language: Optional[str],
    backend_task_id: int,
    translation_model_id: str = "",
    translate_reference: bool = False,
    use_glossary_embedding: bool = True,
) -> None:
    """
    由 Backend 上传后触发：拉取文件、执行 OCR 翻译、上传译文，与 BP 一致直写 DB 写回结果。
    前端可用 task_id 查询 TranslationTask 状态与 translated_attachment_id，后续可扩展 context 存已翻译页数等。
    """
    import logging
    import tempfile
    import httpx
    from pathlib import Path
    from config import api_config
    from utils.utils.attachment import AttachmentManager
    from utils.azure.blob_client import AzureBlobStorage
    from agent.translation.db import (
        azure_blob_attachment_storage,
        create_attachment_for_translation,
        read_translation_task,
        write_original_pages_context,
        write_translation_result,
        write_translation_task_page,
    )

    def _render_upload_page_image(
        origin_pdf_path: str,
        page_data: dict,
        backend_task_id: int,
        page_index_1based: int,
        azure: "AzureBlobStorage",
        container: str,
    ) -> Optional[str]:
        """同步：在原 PDF 指定页上叠加白底+译文 -> 单页 PDF -> JPG -> 上传 blob，返回该页图片的 read_url。"""
        import tempfile
        page_index_0based = page_index_1based - 1
        with tempfile.TemporaryDirectory() as tmp:
            tmp_pdf = os.path.join(tmp, "page.pdf")
            tmp_jpg = os.path.join(tmp, "page.jpg")
            try:
                draw_single_page_from_middle_on_original(
                    origin_pdf_path, page_index_0based, page_data, tmp_pdf
                )
                pdf_to_jpg(tmp_pdf, tmp_jpg)
                blob_key = f"attachments/translation/{backend_task_id}/page_{page_index_1based}.jpg"
                with open(tmp_jpg, "rb") as f:
                    azure.upload_file(container, blob_key, f)
                return azure.get_read_url(container, blob_key)
            except Exception as e:
                logging.warning(f"render/upload page {page_index_1based} failed: {e}")
                return None

    def _render_upload_page_image_with_image_fillback(
        origin_pdf_path: str,
        page_data: dict,
        page_annotations: list,
        backend_task_id: int,
        page_index_1based: int,
        azure: "AzureBlobStorage",
        container: str,
    ) -> Optional[str]:
        """同步：先按文本渲染单页，再将该页图片翻译结果回填，最后导出 JPG 上传。"""
        import tempfile
        page_index_0based = page_index_1based - 1
        with tempfile.TemporaryDirectory() as tmp:
            tmp_pdf = os.path.join(tmp, "page_with_image.pdf")
            tmp_jpg = os.path.join(tmp, "page_with_image.jpg")
            try:
                draw_single_page_from_middle_on_original(
                    origin_pdf_path, page_index_0based, page_data, tmp_pdf
                )
                single_page_annotations = []
                for item in page_annotations or []:
                    single_page_annotations.append(
                        {
                            "page_index": 0,
                            "bbox": item.get("bbox"),
                            "page_size": item.get("page_size"),
                            "translated_jpg_path": item.get("translated_jpg_path"),
                        }
                    )
                if single_page_annotations:
                    add_image_translations_to_pdf(tmp_pdf, single_page_annotations)
                pdf_to_jpg(tmp_pdf, tmp_jpg)
                blob_key = f"attachments/translation/{backend_task_id}/page_{page_index_1based}_img.jpg"
                with open(tmp_jpg, "rb") as f:
                    azure.upload_file(container, blob_key, f)
                return azure.get_read_url(container, blob_key)
            except Exception as e:
                logging.warning(
                    f"render/upload page with image fillback {page_index_1based} failed: {e}"
                )
                return None

    def _render_upload_original_page_sync(
        origin_pdf_path: str,
        page_index_0based: int,
        azure: "AzureBlobStorage",
        container: str,
        dpi: int = 150,
    ) -> Optional[str]:
        """同步：将原始 PDF 指定页直接渲染为 JPG 并上传 blob，返回 read_url；失败返回 None。"""
        import tempfile
        page_index_1based = page_index_0based + 1
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_jpg = os.path.join(tmp, f"original_page_{page_index_1based}.jpg")
                with _fitz_lock:
                    doc = fitz.open(origin_pdf_path)
                    try:
                        if page_index_0based >= len(doc):
                            doc.close()
                            return None
                        pix = doc[page_index_0based].get_pixmap(dpi=dpi, alpha=False)
                    finally:
                        doc.close()
                pix.save(tmp_jpg)
                blob_key = (
                    f"attachments/translation/{backend_task_id}"
                    f"/original_page_{page_index_1based}.jpg"
                )
                with open(tmp_jpg, "rb") as f:
                    azure.upload_file(container, blob_key, f)
                return azure.get_read_url(container, blob_key)
        except Exception as e:
            logging.warning(
                f"render/upload original page {page_index_1based} failed "
                f"(task={backend_task_id}): {e}"
            )
            return None

    async def _render_all_original_pages(
        origin_pdf_path: str,
        total_pages: int,
        azure_for_pages: "AzureBlobStorage",
        container_name: str,
    ) -> None:
        """
        与 MinerU OCR 并发执行：逐页将原始 PDF 渲染为 JPG 上传，
        每完成一页就写入 context.original_pages（累积完整列表）。
        任何单页失败只记录日志，不影响其余页面和主翻译流程。
        使用 public 存储，避免逐页预览图过期图裂。
        """
        original_pages_list: list = []
        for page_index_0based in range(total_pages):
            read_url = await asyncio.to_thread(
                _render_upload_original_page_sync,
                origin_pdf_path,
                page_index_0based,
                azure_for_pages,
                container_name,
            )
            if read_url:
                original_pages_list.append({
                    "page_index": page_index_0based + 1,
                    "url": read_url,
                })
                try:
                    write_original_pages_context(backend_task_id, original_pages_list)
                except Exception as e:
                    logging.warning(
                        f"write_original_pages_context failed "
                        f"(task={backend_task_id}, page={page_index_0based + 1}): {e}"
                    )

    def _fail_task(error: str) -> None:
        try:
            write_translation_result(
                backend_task_id,
                "failed",
                context_extra={"error": error},
            )
        except Exception as e:
            logging.error(f"write_translation_result (fail) failed: {e}")

    task_start_ts = time.perf_counter()

    try:
        task = read_translation_task(backend_task_id)
        if not task or task.get("owner_id") is None:
            _fail_task("task not found or no owner")
            return
        mgr = AttachmentManager(public=False)
        attachments = mgr.fetch_attachments([str(attachment_id)], False)
        if not attachments:
            _fail_task("attachment not found")
            return
        att = attachments[0]
        file_url = att.get("url") or ""
        file_name = att.get("name") or "file"
        if not file_url:
            _fail_task("attachment has no url")
            return
        azure = AzureBlobStorage(
            connection_string=api_config.AZURE_PRIVATE_STORAGE_CONNECTION_STRING,
            read_url_expiry_days=365,
        )
        azure_public = AzureBlobStorage(
            connection_string=api_config.AZURE_STORAGE_CONNECTION_STRING,
            read_url_expiry_days=365,
        )
        container = "nudata"
        # 下载到临时文件
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            data = resp.content
        suffix = Path(file_name).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            temp_path = f.name

        # 进度可见：尽早给出总页数（PDF 读取页数；图片固定 1），便于前端从 0/N 开始展示。
        initial_total_pages = 0
        temp_suffix = Path(temp_path).suffix.lower()
        if temp_suffix in IMAGE_EXTENSIONS:
            initial_total_pages = 1
        elif temp_suffix == ".pdf":
            try:
                with fitz.open(temp_path) as doc:
                    initial_total_pages = len(doc)
            except Exception as e:
                logging.warning(f"read pdf page count failed (task={backend_task_id}): {e}")

        # PDF: 先处于 parsing（OCR / 版面分析阶段）；进入逐页翻译后再切到 running。
        # 图片: 无 MinerU OCR 阶段，直接 running。
        initial_status = "parsing" if temp_suffix == ".pdf" else "running"
        write_translation_result(
            backend_task_id,
            initial_status,
            context_extra={"current_page": 0, "total_pages": initial_total_pages},
        )

        async def _on_progress(
            current_page: int,
            total_pages: int,
            translated_page_data: Optional[dict] = None,
        ) -> None:
            write_translation_result(
                backend_task_id,
                "running",
                context_extra={"current_page": current_page, "total_pages": total_pages},
            )
            # PDF 逐页渲染：每译完一页渲染为图并写入 TranslationTaskPage（仅 PDF 有多页时会多次调用）
            if translated_page_data is not None:
                read_url = await asyncio.to_thread(
                    _render_upload_page_image,
                    temp_path,
                    translated_page_data,
                    backend_task_id,
                    current_page,
                    azure_public,
                    container,
                )
                if read_url:
                    write_translation_task_page(backend_task_id, current_page, read_url)

        async def _on_page_image_progress(
            current_page: int,
            total_pages: int,
            translated_page_data: Optional[dict] = None,
            page_annotations: Optional[list] = None,
        ) -> None:
            if translated_page_data is None:
                return
            read_url = await asyncio.to_thread(
                _render_upload_page_image_with_image_fillback,
                temp_path,
                translated_page_data,
                page_annotations or [],
                backend_task_id,
                current_page,
                azure_public,
                container,
            )
            if read_url:
                # 同一页第二次写入时覆盖 URL，让前端轮询拿到图片回填后的新图
                write_translation_task_page(backend_task_id, current_page, read_url)

        try:
            # 仅 PDF 且页数已知时并发渲染原文件逐页预览图。
            # _render_all_original_pages 在 MinerU OCR（数分钟）期间完成（数十秒），
            # 使用 asyncio.gather 并发执行，互不阻塞；原文件渲染任何异常不影响主翻译流程。
            if temp_suffix == ".pdf" and initial_total_pages > 0:
                results = await asyncio.gather(
                    _render_all_original_pages(
                        temp_path, initial_total_pages, azure_public, container
                    ),
                    translate_file(
                        origin_path=temp_path,
                        target_language=target_language,
                        translation_model_id=translation_model_id,
                        translate_reference=translate_reference,
                        input_language=input_language,
                        output_path=None,
                        on_progress=_on_progress,
                        on_page_image_progress=_on_page_image_progress,
                        return_extra=True,
                        use_glossary_embedding=use_glossary_embedding,
                    ),
                    return_exceptions=False,
                )
                translate_result = results[1]
            else:
                translate_result = await translate_file(
                    origin_path=temp_path,
                    target_language=target_language,
                    translation_model_id=translation_model_id,
                    translate_reference=translate_reference,
                    input_language=input_language,
                    output_path=None,
                    on_progress=_on_progress,
                    on_page_image_progress=_on_page_image_progress,
                    return_extra=True,
                    use_glossary_embedding=use_glossary_embedding,
                )
            if isinstance(translate_result, tuple):
                out_path, translate_extra = translate_result
            else:
                out_path, translate_extra = translate_result, {}
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        if not out_path or not Path(out_path).is_file():
            _fail_task("translate_file did not produce output")
            return
        # 上传译文到私有 blob（与逐页图同一 container，前面已创建 azure）
        translated_name = Path(out_path).name
        blob_key = f"attachments/translation/{backend_task_id}/{translated_name}"
        try:
            final_size = os.path.getsize(out_path)
            print(
                f"[PDF final upload] path={out_path}, size_bytes={final_size}, size_mb={final_size / (1024 * 1024):.2f}"
            )
        except OSError as e:
            print(f"[PDF final upload] getsize failed: path={out_path}, err={e}")
        with open(out_path, "rb") as f:
            azure.upload_file(container, blob_key, f)
        read_url = azure.get_read_url(container, blob_key)

        translated_md_content = str(
            (translate_extra or {}).get("translated_md_content", "") or ""
        ).strip()
        translated_md_attachment_id = None
        translated_md_url = ""
        if translated_md_content:
            from io import BytesIO

            md_name = f"{Path(translated_name).stem}.md"
            blob_key_md = f"attachments/translation/{backend_task_id}/{md_name}"
            azure.upload_file(container, blob_key_md, BytesIO(translated_md_content.encode("utf-8")))
            translated_md_url = azure.get_read_url(container, blob_key_md)
            translated_md_attachment_id = create_attachment_for_translation(
                task["owner_id"],
                md_name,
                translated_md_url,
                storage=azure_blob_attachment_storage(container, blob_key_md),
            )

        try:
            os.unlink(out_path)
        except OSError:
            pass
        # 与 BP 一致：直写 DB，不通过 HTTP 回调
        owner_id = task["owner_id"]
        new_attachment_id = create_attachment_for_translation(
            owner_id,
            translated_name,
            read_url,
            storage=azure_blob_attachment_storage(container, blob_key),
        )
        translated_suffix = Path(translated_name).suffix.lower()
        if translated_suffix == ".pdf":
            context_extra = {
                "translated_pdf_attachment_id": new_attachment_id,
                "translated_pdf_url": read_url,
            }
        else:
            # 图片翻译路径保持兼容：仍使用 translated_file_url。
            context_extra = {"translated_file_url": read_url}
        if translated_md_attachment_id and translated_md_url:
            context_extra.update(
                {
                    "translated_md_attachment_id": translated_md_attachment_id,
                    "translated_md_url": translated_md_url,
                }
            )
        write_translation_result(
            backend_task_id,
            "complete",
            translated_attachment_id=new_attachment_id,
            context_extra=context_extra,
        )

        # PDF 任务：基于译文 md 预生成 docx / txt，生成一个写回一个，不影响主结果完成。
        if translated_md_content:
            from agent.translation.format_convert import convert_md_to_txt, convert_md_to_word

            with tempfile.TemporaryDirectory(prefix=f"pdf_extra_{backend_task_id}_") as extra_tmp_dir:
                md_temp_path = os.path.join(extra_tmp_dir, f"{Path(translated_name).stem}.md")
                with open(md_temp_path, "w", encoding="utf-8") as f:
                    f.write(translated_md_content)

                extra_outputs = []
                try:
                    docx_path = await asyncio.to_thread(convert_md_to_word, md_temp_path)
                    extra_outputs.append(docx_path)
                except Exception as e:
                    logging.warning(
                        f"pdf extra format generate docx failed (task={backend_task_id}): {e}"
                    )
                try:
                    txt_path = await asyncio.to_thread(convert_md_to_txt, md_temp_path)
                    extra_outputs.append(txt_path)
                except Exception as e:
                    logging.warning(
                        f"pdf extra format generate txt failed (task={backend_task_id}): {e}"
                    )

                for extra_path in extra_outputs:
                    try:
                        p = Path(extra_path)
                        if not p.is_file():
                            continue
                        ext = p.suffix.lower().lstrip(".")
                        extra_name = p.name
                        blob_key_extra = (
                            f"attachments/translation/{backend_task_id}/{extra_name}"
                        )
                        with open(extra_path, "rb") as f:
                            azure.upload_file(container, blob_key_extra, f)
                        extra_url = azure.get_read_url(container, blob_key_extra)
                        extra_attachment_id = create_attachment_for_translation(
                            owner_id,
                            extra_name,
                            extra_url,
                            storage=azure_blob_attachment_storage(
                                container, blob_key_extra
                            ),
                        )
                        write_translation_result(
                            backend_task_id,
                            "complete",
                            context_extra={
                                f"translated_{ext}_attachment_id": extra_attachment_id,
                                f"translated_{ext}_url": extra_url,
                            },
                        )
                    except Exception as e:
                        logging.warning(
                            f"pdf extra format upload failed (task={backend_task_id}, path={extra_path}): {e}"
                        )
    except Exception as e:
        logging.exception("process_translation_by_attachment_id failed")
        _fail_task(str(e))
    finally:
        elapsed = time.perf_counter() - task_start_ts
        print(
            f"[TranslationTask] task_id={backend_task_id} total_elapsed_seconds={elapsed:.2f}"
        )


async def main():
    # 一键翻译：输入原文件 + 输入/目标语言，仅输出 xxx_translated（支持 PDF 或 JPG）
    origin_path = "/Users/chenzichu/Desktop/NoahServer/NoahAgent/noah_agent/agent/translation/test/test_origin.pdf"
    out = await translate_file(
        origin_path=origin_path,
        input_language="English",
        target_language="German",
        output_path=None,
    )
    print("Done. Output:", out)


if __name__ == "__main__":
    asyncio.run(main())
