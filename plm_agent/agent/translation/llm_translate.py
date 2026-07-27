#!/usr/bin/env python3
"""
翻译相关 LLM 调用：当前使用 Gemini，后续可切换为其他大模型。

提供：
- llm_translate_page_full_text / llm_translate_page_blocks：按页全文翻译与分块回填
- llm_translate_single_text：单段文本翻译
- ocr_image_to_text / ocr_image_to_translated_text：单张图片 OCR 或一步到位 OCR+翻译（均为 async）
- build_blocks_schema：供分块翻译的 JSON schema 构建
"""
import datetime
import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)

from google import genai
from google.genai import types
from google.genai.types import HttpOptions
from config import api_config
from logging_config import log_id_var, task_id_var
from llm.gcp_models import Gemini3Flash, ClaudeSonnet45
from llm.azure_models import GPT5, GPT52, GPT54Mini
from llm.deepseek_models import DeepseekChat
from llm.moonshot_models import AZUREKimiK2Thinking

# Gemini 客户端与默认模型（后续切换大模型时替换此模块实现即可）
_DEFAULT_MODEL = "gemini-3-flash-preview"
_gcp_key_path = Path(__file__).resolve().parents[2] / "gcp_key.json"
if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key_path)
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "noahai-440408")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

_client = genai.Client(http_options=HttpOptions(api_version="v1"))

# ---------- 公共提示词片段（按 format / ref / target 切换） ----------
FORMAT_INSTRUCTION_MARKDOWN = (
    "Use Markdown formatting for structure (e.g., # headings, **bold**, *italic*, "
    "| table | syntax). Only use HTML tags for elements with no Markdown equivalent "
    "(e.g., <sup>, <sub>). Do NOT use <table>, <tr>, <td>, <h1>–<h6>, <b>, <i>, "
    "or other HTML tags that have Markdown equivalents."
)
FORMAT_INSTRUCTION_HTML = (
    "Preserve existing HTML tags (e.g., <sup>, <sub>, <i>, <b>, <table>) "
    "and if formatting is needed, use HTML tags instead of Markdown."
)

REF_GUARD_FULLTEXT_KEEP_ORIGINAL = (
    "If any entry looks like a bibliography/reference item (citations, author-year lines, "
    "journal/DOI metadata), keep that entry in original language and do not translate it.\n\n"
)
REF_GUARD_FULLTEXT_TRANSLATE_ALL = (
    "Translate every entry into the target language, including the reference list and every "
    "numbered citation; do not leave any bibliography item in the source language. "
    "Put one newline between each citation (one reference per line)."
)
REF_GUARD_BLOCKS_KEEP_ORIGINAL = (
    "If an index text looks like bibliography/reference metadata, return its original text unchanged "
    "(do not translate that index).\n\n"
)
REF_GUARD_BLOCKS_TRANSLATE_ALL = (
    "Translate every index into the target language, including the reference list and every "
    "numbered citation; do not leave any bibliography item in the source language. "
    "For indices that contain references/bibliography: end each reference entry (each citation line) "
    "with a newline (\\n), so that every ref line is separated by a newline in the output."
)

LANG_INSTRUCTION_BLOCKS_WITH_TARGET = (
    "The full_text is in {target_language}. Each index output must be in {target_language} only; "
    "do not translate into any other language. "
    "If the text at an index is already in {target_language} (same as target), do not translate it "
    'and output empty string "" for that index; the original will be kept.\n\n'
)
LANG_INSTRUCTION_BLOCKS_AUTO = (
    "The full_text follows auto translation (Chinese→English, other→Chinese). "
    "Each index output must be in the same language as the corresponding segment in full_text. "
    'If the segment at an index is already in the same language as in full_text, output empty string '
    '"" for that index; the original will be kept.\n\n'
)

_DEFAULT_TRANSLATION_MODEL_ID = "gpt-5-4-mini"
_TRANSLATION_LLM_CACHE: dict[str, Any] = {}
_SUPPORTED_TRANSLATION_MODEL_IDS = (
    "gemini-3",
    "gpt-5-4-mini",
    "gpt-5-2",
    "gpt-5",
    "claude-sonnet-4-5",
    "deepseek",
    "kimi",
)


def _build_min_thinking_kwargs(model_id: str) -> dict[str, Any]:
    """
    根据模型返回“最低思考”参数。
    仅在当前模型与 SDK 组合可稳定支持时注入，避免参数不兼容导致失败。
    """
    if model_id == "gemini-3":
        # Gemini 3 使用 thinking_level；当前封装对外暴露为 thinking_budget。
        return {"thinking_budget": "minimal"}
    if model_id in ("gpt-5-2", "gpt-5"):
        # OpenAI Responses API: reasoning.effort 支持 low/medium/high。
        return {"reasoning": {"effort": "low", "summary": "auto"}}
    return {}


def _get_client():
    """返回当前 LLM 客户端，后续可改为按配置返回不同实现。"""
    return _client


async def _log_qwen_call(
    prompt: str,
    content: str,
    usage: Any,
    model: str = "qwen3.5-plus",
    start_time: "datetime.datetime | None" = None,
) -> None:
    """Log a Qwen API call to the shared open_api log files (mirrors azure_models.py log_results)."""
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    end_time = datetime.datetime.now()
    if not os.path.exists("logs"):
        os.makedirs("logs")
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    log_id = log_id_var.get()
    task_id = task_id_var.get()
    with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
        log_file.write(f"[{log_id}] [{current_time}] {prompt}\n")
        log_file.write(f"[{log_id}] [{current_time}] {content}\n")
        log_file.write(f"[{log_id}] [{current_time}] Model: {model}, Usage: {usage}\n")
        if start_time:
            time_delta = end_time - start_time
            log_file.write(f"[{log_id}] Time spent: {time_delta.total_seconds():.2f} seconds\n")
        log_file.write("=" * 64 + "\n")
    with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
        time_delta_str = f"[{(end_time - start_time).total_seconds():.2f}s]" if start_time else ""
        log_file.write(f"[{log_id}] [{current_time}][{task_id}] {time_delta_str} Model: {model}, Usage: {usage}\n")


def _normalize_translation_model_id(translation_model_id: str = "") -> str:
    model_id = (translation_model_id or "").strip()
    if model_id in _SUPPORTED_TRANSLATION_MODEL_IDS:
        return model_id
    if model_id:
        print(
            f"[translation llm] unsupported translation_model_id={model_id}, "
            f"fallback={_DEFAULT_TRANSLATION_MODEL_ID}"
        )
    return _DEFAULT_TRANSLATION_MODEL_ID


def _get_translation_llm(translation_model_id: str = ""):
    model_id = _normalize_translation_model_id(translation_model_id)
    if model_id in _TRANSLATION_LLM_CACHE:
        return _TRANSLATION_LLM_CACHE[model_id]
    if model_id == "gemini-3":
        llm = Gemini3Flash()
    elif model_id == "gpt-5-2":
        llm = GPT52()
    elif model_id == "gpt-5-4-mini":
        llm = GPT54Mini()
    elif model_id == "gpt-5":
        llm = GPT5()
    elif model_id == "claude-sonnet-4-5":
        llm = ClaudeSonnet45()
    elif model_id == "deepseek":
        llm = DeepseekChat()
    elif model_id == "kimi":
        llm = AZUREKimiK2Thinking()
    else:
        llm = Gemini3Flash()
    _TRANSLATION_LLM_CACHE[model_id] = llm
    return llm


def _extract_text_from_llm_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response.strip()
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content.strip()
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            txt = getattr(item, "text", None)
            if isinstance(txt, str):
                parts.append(txt)
        if parts:
            return "".join(parts).strip()
    output = getattr(response, "output", None)
    if isinstance(output, list):
        chunks = []
        for item in output:
            txt = getattr(item, "text", None)
            if isinstance(txt, str):
                chunks.append(txt)
        if chunks:
            return "".join(chunks).strip()
    return str(response).strip()


async def _call_translation_llm(
    prompt: str,
    *,
    translation_model_id: str = "",
    json_mode: bool = False,
) -> str:
    model_id = _normalize_translation_model_id(translation_model_id)
    llm = _get_translation_llm(model_id)
    model_kwargs = _build_min_thinking_kwargs(model_id)
    logger.debug("[translation] model=%s kwargs=%s", model_id, model_kwargs)
    response = await llm(
        user_prompt=prompt,
        json_mode=json_mode,
        temperature=0,
        **model_kwargs,
    )
    return _extract_text_from_llm_response(response)


def build_blocks_schema(indexes):
    """构建分块翻译返回的 JSON Schema（index -> 译文）。"""
    properties = {}
    for index in indexes:
        properties[str(index)] = {"type": "STRING"}
    return {
        "type": "OBJECT",
        "properties": properties,
        "required": [str(index) for index in indexes],
        "additionalProperties": False,
    }


async def llm_detect_language(text: str) -> str:
    """Detect the language of the given text. Returns a canonical language name (e.g. 'Chinese', 'English')."""
    if not text or not text.strip():
        return ""
    sample = text[:1000]
    prompt = (
        "Detect the language of the following text. "
        "Output ONLY the canonical English language name or NA if the language cannot be determined (e.g. Chinese, English, Japanese, Korean, French). "
        "Do not output anything else.\n\n"
        f"{sample}"
    )
    result = await _call_translation_llm(prompt, translation_model_id="gemini-3", json_mode=False)
    return (result or "").strip()


async def llm_translate_page_full_text(
    text_dict,
    target_language="Chinese",
    prev_full_text="",
    *,
    translation_model_id: str = "",
    keep_reference_in_original: bool = False,
    prefer_markdown: bool = False,
    glossary_hint: str = "",
):
    """
    将一页的索引化文本翻译为整段目标语言全文。
    使用上一页译文作为上下文以保持术语一致。
    prefer_markdown=True 时输出优先使用 Markdown 语法（适用于文本类文件翻译），
    否则保留 HTML 标签风格（适用于 PDF 内容翻译）。
    """
    format_instruction = FORMAT_INSTRUCTION_MARKDOWN if prefer_markdown else FORMAT_INSTRUCTION_HTML
    ref_guard = (
        REF_GUARD_FULLTEXT_KEEP_ORIGINAL
        if keep_reference_in_original
        else REF_GUARD_FULLTEXT_TRANSLATE_ALL
    )
    has_target = bool(target_language and str(target_language).strip())
    glossary_section = (
        f"Glossary (use these translations for domain-specific terms when applicable, prioritize exact matches):\n{glossary_hint}\n\n"
        if glossary_hint
        else ""
    )
    if not has_target:
        prompt = (
            "You are given a JSON dict that maps an index to its original text. "
            "First detect the main language of the page. "
            "If the original text is Chinese (Simplified or Traditional), translate the whole page "
            "into natural English. If the original text is not Chinese, translate the whole page "
            f"into natural Simplified Chinese. Then output ONLY the full translated text in natural "
            f"reading order. {format_instruction} Preserve line breaks "
            "from the source as much as possible; do not merge or split lines unless necessary for "
            "correct translation.\n\n"
            f"{ref_guard}"
            f"{glossary_section}"
            f"Previous page full_text:\n{prev_full_text}\n\n"
            f"Current page indexed text:\n{json.dumps(text_dict, ensure_ascii=False)}"
        )
    else:
        ref_emphasis = (
            ""
            if keep_reference_in_original
            else (
                f" The reference list and every numbered citation must be in {target_language} "
                "as well; do not leave any in the source language.\n\n"
            )
        )
        prompt = (
            f"You are given a JSON dict that maps an index to its original text. "
            f"Translate everything to {target_language}.{ref_emphasis} "
            f"First read all entries to "
            f"reconstruct context. Use the previous page translation below as context "
            f"to keep terminology consistent. Then output ONLY the full translated "
            f"text in natural reading order. {format_instruction} "
            f"Preserve line breaks from the source as much as possible; "
            f"do not merge or split lines unless necessary for correct translation.\n\n"
            f"{ref_guard}"
            f"{glossary_section}"
            f"Previous page full_text:\n{prev_full_text}\n\n"
            f"Current page indexed text:\n{json.dumps(text_dict, ensure_ascii=False)}"
        )
    return await _call_translation_llm(
        prompt,
        translation_model_id=translation_model_id,
        json_mode=False,
    )


async def llm_translate_page_blocks(
    text_dict,
    full_text,
    target_language="Chinese",
    *,
    translation_model_id: str = "",
    keep_reference_in_original: bool = False,
    prefer_markdown: bool = True,
    glossary_hint: str = "",
):
    """
    根据整页译文全文与索引化原文，为每个索引生成对应译文（JSON）。
    固定使用 Gemini 处理结构化 JSON 输出（response_schema），translation_model_id 对此函数无效。
    prefer_markdown=True 时输出使用 Markdown（PDF 路径贴块前会转 HTML），否则使用 HTML。
    """
    indexes = list(text_dict.keys())
    schema = build_blocks_schema(indexes)
    ref_guard = (
        REF_GUARD_BLOCKS_KEEP_ORIGINAL
        if keep_reference_in_original
        else REF_GUARD_BLOCKS_TRANSLATE_ALL
    )
    has_target = bool(target_language and str(target_language).strip())
    if has_target:
        lang_instruction = LANG_INSTRUCTION_BLOCKS_WITH_TARGET.format(
            target_language=target_language
        )
    else:
        lang_instruction = LANG_INSTRUCTION_BLOCKS_AUTO
    format_instruction = (
        f"{FORMAT_INSTRUCTION_MARKDOWN} Preserve line breaks in each index text as much as "
        f"possible; do not merge or split lines unless necessary for correct translation."
        if prefer_markdown
        else (
            "Preserve existing HTML tags (e.g., <sup>, <sub>, <i>, <b>, <table>) and "
            "use HTML tags instead of Markdown. Preserve line breaks in each index text as much as "
            "possible; do not merge or split lines unless necessary for correct translation. "
        )
    )
    glossary_section = (
        f"Glossary (use these translations for domain-specific terms when applicable, prioritize exact matches):\n{glossary_hint}\n\n"
        if glossary_hint
        else ""
    )
    prompt = (
        f"You are given the full translated text for a page and a JSON dict that maps "
        f"an index to its original text. Using the full_text as context, provide the "
        f"translated text for each index. Output a JSON object with one field per index. "
        f"{format_instruction} "
        f"Only return JSON.\n\n"
        f"{lang_instruction}"
        f"{ref_guard}"
        f"{glossary_section}"
        f"full_text:\n{full_text}\n\n"
        f"Current page indexed text:\n{json.dumps(text_dict, ensure_ascii=False)}"
    )
    llm = Gemini3Flash()
    response = await llm(
        user_prompt=prompt,
        json_mode=True,
        temperature=0,
        thinking_budget="minimal",
        response_schema=schema,
    )
    raw = _extract_text_from_llm_response(response)
    obj = _extract_json_object(raw)
    return _normalize_blocks_result(obj, indexes)


def _mime_type_from_image_path(path: str) -> str:
    """根据图片路径扩展名返回 MIME 类型。"""
    ext = Path(path).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    return "image/jpeg"


async def ocr_image_to_text(jpg_path: str) -> str:
    """
    对单张 JPG 调用当前 LLM（Gemini）做 OCR，返回识别出的文本。
    供翻译流程中图片内文字提取使用。
    """
    client = _get_client()
    with open(jpg_path, "rb") as f:
        image_bytes = f.read()
    mime_type = _mime_type_from_image_path(jpg_path)
    prompt = (
        "Extract all text from this image in reading order. "
        "Output only the extracted text, no explanation or JSON."
    )
    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        prompt,
    ]
    response = await client.aio.models.generate_content(
        model=_DEFAULT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        ),
    )
    return (response.text or "").strip()


async def ocr_image_to_translated_text(image_path: str, target_language: str = "Chinese") -> str:
    """
    对单张图片一步到位：OCR 提取图中文字并翻译为目标语言，一次 Gemini 调用返回译文。
    供 DOCX 翻译流程中图片片段使用，减少请求次数。
    """
    client = _get_client()
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    mime_type = _mime_type_from_image_path(image_path)
    if not target_language or not str(target_language).strip():
        # 自动中英互译：中文 → 英文，其它语言 → 中文
        prompt = (
            "Extract all text from this image in reading order. "
            "Detect the language of the extracted text. "
            "If the text is Chinese (Simplified or Traditional), translate it into natural English. "
            "If the text is not Chinese, translate it into natural Simplified Chinese. "
            "Output ONLY the translated text, no explanation or JSON."
        )
    else:
        prompt = (
            f"Extract all text from this image in reading order, then translate the extracted text "
            f"to {target_language}. Output ONLY the translated text, no explanation or JSON."
        )
    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        prompt,
    ]
    response = await client.aio.models.generate_content(
        model=_DEFAULT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        ),
    )
    return (response.text or "").strip()


async def llm_translate_single_text(
    text: str,
    target_language: str = "Chinese",
    *,
    translation_model_id: str = "",
) -> str:
    """将一段文本翻译为目标语言，仅输出译文。"""
    if not text or not text.strip():
        return ""
    if not target_language or not str(target_language).strip():
        # 自动中英互译：中文 → 英文，其它语言 → 中文
        prompt = (
            "Detect the language of the following text. "
            "If the text is Chinese (Simplified or Traditional), translate it into natural English. "
            "If the text is not Chinese, translate it into natural Simplified Chinese. "
            "Output ONLY the translation, no explanation. Preserve the original line breaks as much "
            "as possible; do not merge or split lines unless necessary for correct translation.\n\n"
            f"{text}"
        )
    else:
        prompt = (
            f"Translate the following to {target_language}. Output ONLY the translation, no explanation. "
            f"Preserve the original line breaks as much as possible; do not merge or split lines unless "
            f"necessary for correct translation.\n\n{text}"
        )
    return await _call_translation_llm(
        prompt,
        translation_model_id=translation_model_id,
        json_mode=False,
    )


def _normalize_blocks_result(obj: dict, indexes) -> dict:
    result = {}
    idx_list = [str(x) for x in indexes]
    if not isinstance(obj, dict):
        obj = {}
    for idx in idx_list:
        val = obj.get(idx, "")
        result[idx] = str(val or "")
    return result


async def qwen_vl_extract_and_translate(
    image_bytes_or_pil,
    target_language: str = "Chinese",
) -> str:
    """
    单张裁剪图送入阿里云 qwen-vl：提取图中文字并翻译为目标语言，直接返回译文文本。
    用于图片翻译流程中的每个版面区域。
    image_bytes_or_pil: 可为 numpy (BGR)、PIL Image，或 bytes。
    """
    import base64
    from io import BytesIO
    from openai import AsyncOpenAI
    from config import api_config

    if image_bytes_or_pil is None:
        return ""
    # 转为 base64 data URI
    if hasattr(image_bytes_or_pil, "save"):
        buf = BytesIO()
        img = image_bytes_or_pil.convert("RGB") if image_bytes_or_pil.mode != "RGB" else image_bytes_or_pil
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    elif isinstance(image_bytes_or_pil, bytes):
        b64 = base64.b64encode(image_bytes_or_pil).decode("utf-8")
    else:
        import cv2
        import numpy as np
        arr = np.asarray(image_bytes_or_pil)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        elif arr.shape[-1] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        from PIL import Image
        pil = Image.fromarray(arr)
        buf = BytesIO()
        pil.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    data_uri = f"data:image/jpeg;base64,{b64}"

    api_key = getattr(api_config, "ALIYUN_BAILIAN_API_KEY", None) or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return ""
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )
    lang_name = target_language if target_language else "Chinese"
    prompt = (
        f"请提取并且翻译这个图片中的文字到{lang_name}，只输出翻译后的内容，不要解释。"
    )
    call_start_time = datetime.datetime.now()
    completion = await client.chat.completions.create(
        model="qwen3.5-plus",
        extra_body={"enable_thinking": False},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    text = (completion.choices[0].message.content or "").strip()
    await _log_qwen_call(prompt, text, getattr(completion, "usage", None), start_time=call_start_time)
    return text


def _to_qwen_data_uri(image_bytes_or_pil: Any) -> str:
    import base64
    from io import BytesIO

    if image_bytes_or_pil is None:
        return ""
    if hasattr(image_bytes_or_pil, "save"):
        buf = BytesIO()
        img = image_bytes_or_pil.convert("RGB") if image_bytes_or_pil.mode != "RGB" else image_bytes_or_pil
        img.save(buf, format="JPEG", quality=95)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    elif isinstance(image_bytes_or_pil, bytes):
        b64 = base64.b64encode(image_bytes_or_pil).decode("utf-8")
    else:
        import cv2
        import numpy as np
        arr = np.asarray(image_bytes_or_pil)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
        elif arr.shape[-1] == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        from PIL import Image
        pil = Image.fromarray(arr)
        buf = BytesIO()
        pil.save(buf, format="JPEG", quality=95)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return {}
    return {}


def _normalize_batch_result(obj: dict, n: int) -> List[str]:
    results = [""] * n
    arr = obj.get("results", []) if isinstance(obj, dict) else []
    if not isinstance(arr, list):
        return results
    for item in arr:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        text = item.get("text", "")
        if isinstance(idx, int) and 0 <= idx < n:
            results[idx] = str(text or "").strip()
    return results


# 批量失败时 fallback 单图请求的分批大小，避免瞬时 QPS 过高导致限流/重试
QWEN_VL_FALLBACK_BATCH_SIZE = 4
# Seconds to sleep between consecutive batch chunks to avoid 429 rate-limit errors.
QWEN_VL_INTER_BATCH_SLEEP = float(os.environ.get("QWEN_VL_INTER_BATCH_SLEEP", "0.5"))


async def _qwen_vl_fallback_single_images(
    images: list,
    target_language: str,
) -> list[str]:
    """
    分批对多图做单图 Qwen 请求，每批最多 QWEN_VL_FALLBACK_BATCH_SIZE 个并发，
    避免整批 asyncio.gather 导致瞬时 QPS 过高。
    """
    if not images:
        return []
    batch_size = QWEN_VL_FALLBACK_BATCH_SIZE
    out = [""] * len(images)
    for batch_num, start in enumerate(range(0, len(images), batch_size)):
        if batch_num > 0:
            await asyncio.sleep(QWEN_VL_INTER_BATCH_SLEEP)
        chunk = images[start : start + batch_size]
        results = await asyncio.gather(
            *[
                qwen_vl_extract_and_translate(im, target_language=target_language)
                for im in chunk
            ],
            return_exceptions=True,
        )
        for i, item in enumerate(results):
            idx = start + i
            if isinstance(item, Exception):
                out[idx] = ""
            else:
                out[idx] = str(item or "").strip()
    return out


async def _qwen_vl_one_batch(
    images: list,
    target_language: str,
    api_key: str,
) -> list[str]:
    """
    对一批图片（已控制数量）发一次 Qwen 多图请求，返回等长 list[str]。
    失败时回退到单图请求。
    """
    from openai import AsyncOpenAI

    data_uris = [_to_qwen_data_uri(im) for im in images]
    if not any(data_uris):
        return [""] * len(images)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )
    lang_name = target_language if target_language else "Chinese"
    n = len(images)
    prompt = (
        f"你会收到{n}张图片。请严格按图片出现顺序逐张处理：第1张图对应 results[0]，第2张对应 results[1]，依此类推。"
        f"提取每张图中的文字并翻译为{lang_name}，"
        "严格返回 JSON："
        '{"results":[{"index":0,"text":"..."},{"index":1,"text":"..."}]}。'
        f"results 数组长度必须等于{n}，且 results[i] 必须是第 i+1 张图的译文，严禁打乱顺序或把同一段文字填到多个 index。"
        'index 从 0 开始；text 仅含该张图的译文，不要解释。'
        '若某张图无文字/全空白，该条 text 为空字符串 ""，不可省略该条。'
    )
    content = []
    for uri in data_uris:
        if uri:
            content.append({"type": "image_url", "image_url": {"url": uri}})
    content.append({"type": "text", "text": prompt})

    call_start_time = datetime.datetime.now()
    try:
        for _attempt in range(4):
            try:
                completion = await client.chat.completions.create(
                    model="qwen3.5-plus",
                    temperature=0,
                    extra_body={"enable_thinking": False},
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": content}],
                )
                break
            except Exception as _exc:
                _is_429 = "429" in str(_exc) or "rate" in str(_exc).lower()
                if _is_429 and _attempt < 3:
                    _delay = 0.5 * (2 ** _attempt)
                    logger.warning("[qwen_vl_batch] 429 on attempt %d, sleeping %.0fs", _attempt + 1, _delay)
                    await asyncio.sleep(_delay)
                    continue
                raise
    except Exception:
        try:
            completion = await client.chat.completions.create(
                model="qwen3.5-plus",
                temperature=0,
                extra_body={"enable_thinking": False},
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            return await _qwen_vl_fallback_single_images(images, target_language)

    msg = completion.choices[0].message.content
    if isinstance(msg, list):
        text = "".join(
            [x.get("text", "") if isinstance(x, dict) else str(x) for x in msg]
        )
    else:
        text = str(msg or "")
    await _log_qwen_call(prompt, text, getattr(completion, "usage", None), start_time=call_start_time)
    obj = _extract_json_object(text)
    results = _normalize_batch_result(obj, len(images))
    if any(results):
        return results

    return await _qwen_vl_fallback_single_images(images, target_language)


async def qwen_vl_extract_and_translate_batch(
    images: list,
    target_language: str = "Chinese",
    batch_size: int = 16,
) -> list[str]:
    """
    多图批量送入 qwen3-vl-flash，按输入顺序返回 list[str]。

    :param images: 图片列表，每项可为 numpy array / PIL Image / bytes
    :param target_language: 目标语言名，如 "Chinese"
    :param batch_size: 每批最多发送的图片数（默认 16）；超出时分批顺序发送，结果拼接后返回
    若批量失败，回退到单图调用，避免整批丢失。
    """
    from config import api_config

    if not images:
        return []

    # 可强制走单图请求保证 1:1（批量接口实测存在返回顺序与图片顺序不一致的问题）
    if os.environ.get("QWEN_VL_FORCE_SINGLE_IMAGE", "").strip().lower() in ("1", "true", "yes"):
        logger.info(
            "[qwen_vl] QWEN_VL_FORCE_SINGLE_IMAGE=1, using single-image requests (n=%s) to guarantee order",
            len(images),
        )
        return await _qwen_vl_fallback_single_images(images, target_language)

    api_key = getattr(api_config, "ALIYUN_BAILIAN_API_KEY", None) or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return [""] * len(images)

    total = len(images)
    if total <= batch_size:
        # 不超过 batch_size，一次发完
        return await _qwen_vl_one_batch(images, target_language, api_key)

    # 超出则并行分批，每批结果按序拼接
    logger.info(
        "[qwen_vl] splitting %s images into %s parallel batches of %s",
        total,
        (total + batch_size - 1) // batch_size,
        batch_size,
    )
    chunks = [images[start : start + batch_size] for start in range(0, total, batch_size)]
    chunk_results_list = await asyncio.gather(
        *[_qwen_vl_one_batch(chunk, target_language, api_key) for chunk in chunks]
    )
    out: list[str] = []
    for chunk_results in chunk_results_list:
        out.extend(chunk_results)
    return out


async def _qwen_vl_extract_only_one_batch(images: list, api_key: str) -> list[str]:
    """Send a batch of images and return extracted (OCR) text only, no translation."""
    from openai import AsyncOpenAI

    data_uris = [_to_qwen_data_uri(im) for im in images]
    if not any(data_uris):
        return [""] * len(images)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )
    n = len(images)
    prompt = (
        f"你会收到{n}张图片。请严格按图片出现顺序逐张处理：第1张图对应 results[0]，第2张对应 results[1]，依此类推。"
        "仅提取每张图中的原始文字，不要翻译，严格返回 JSON："
        '{"results":[{"index":0,"text":"原始文字"},{"index":1,"text":"原始文字"}]}。'
        f"results 数组长度必须等于{n}。若某张图无文字，text 为空字符串 \"\"，不可省略该条。"
    )
    content = [
        {"type": "image_url", "image_url": {"url": uri}}
        for uri in data_uris if uri
    ]
    content.append({"type": "text", "text": prompt})

    call_start_time = datetime.datetime.now()
    try:
        for _attempt in range(4):
            try:
                completion = await client.chat.completions.create(
                    model="qwen3.5-plus",
                    temperature=0,
                    extra_body={"enable_thinking": False},
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": content}],
                )
                break
            except Exception as _exc:
                _is_429 = "429" in str(_exc) or "rate" in str(_exc).lower()
                if _is_429 and _attempt < 3:
                    _delay = 0.5 * (2 ** _attempt)
                    logger.warning("[qwen_vl_extract_batch] 429 on attempt %d, sleeping %.0fs", _attempt + 1, _delay)
                    await asyncio.sleep(_delay)
                    continue
                raise
    except Exception:
        try:
            completion = await client.chat.completions.create(
                model="qwen3.5-plus",
                temperature=0,
                extra_body={"enable_thinking": False},
                messages=[{"role": "user", "content": content}],
            )
        except Exception:
            return ["[extract_error]"] * len(images)

    msg = completion.choices[0].message.content
    text = "".join([x.get("text", "") if isinstance(x, dict) else str(x) for x in msg] if isinstance(msg, list) else [str(msg or "")])
    await _log_qwen_call(prompt, text, getattr(completion, "usage", None), start_time=call_start_time)
    obj = _extract_json_object(text)
    return _normalize_batch_result(obj, len(images))


async def qwen_vl_extract_batch(
    images: list,
    batch_size: int = 16,
) -> list[str]:
    """
    OCR-only batch: extract raw text from each image without translating.
    Returns list[str] in input order.
    """
    from config import api_config

    if not images:
        return []

    api_key = getattr(api_config, "ALIYUN_BAILIAN_API_KEY", None) or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return [""] * len(images)

    total = len(images)
    if total <= batch_size:
        return await _qwen_vl_extract_only_one_batch(images, api_key)

    chunks = [images[start : start + batch_size] for start in range(0, total, batch_size)]
    chunk_results_list = await asyncio.gather(
        *[_qwen_vl_extract_only_one_batch(chunk, api_key) for chunk in chunks]
    )
    out: list[str] = []
    for chunk_results in chunk_results_list:
        out.extend(chunk_results)
    return out


async def qwen_translate_texts_batch(
    texts: list[str],
    target_language: str,
    batch_size: int = 16,
    *,
    glossary_hint: str = "",
) -> list[str]:
    """
    Translate a list of plain-text strings (no images) to target_language.
    Returns list[str] in input order. Empty / whitespace-only inputs pass through as "".
    """
    from config import api_config
    from openai import AsyncOpenAI

    if not texts:
        return []

    api_key = getattr(api_config, "ALIYUN_BAILIAN_API_KEY", None) or os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return [""] * len(texts)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=90.0,
    )
    lang_name = target_language or "Chinese"
    out: list[str] = [""] * len(texts)

    async def _translate_chunk(start: int, chunk: list[str]) -> None:
        n = len(chunk)
        items_json = json.dumps(
            [{"index": i, "text": t} for i, t in enumerate(chunk)],
            ensure_ascii=False,
        )
        glossary_section = (
            f"术语表（翻译时请参考这些专业术语的译法）：\n{glossary_hint}\n\n"
            if glossary_hint
            else ""
        )
        prompt = (
            f"将以下{n}条文本翻译为{lang_name}，严格按原顺序返回 JSON："
            '{"results":[{"index":0,"text":"译文"},{"index":1,"text":"译文"}]}。'
            f"results 长度必须等于{n}，index 从 0 起。若某条原文为空，译文也为空字符串。\n"
            f"{glossary_section}"
            f"原文列表：{items_json}"
        )
        call_start_time = datetime.datetime.now()
        try:
            completion = await client.chat.completions.create(
                model="qwen3.5-plus",
                temperature=0,
                extra_body={"enable_thinking": False},
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            msg = completion.choices[0].message.content or ""
            obj = _extract_json_object(msg)
            results = _normalize_batch_result(obj, n)
            await _log_qwen_call(prompt, msg, getattr(completion, "usage", None), start_time=call_start_time)
        except Exception as exc:
            logger.warning("[qwen_translate_texts] chunk start=%d failed: %s", start, exc)
            results = [""] * n
        for i, translated in enumerate(results):
            out[start + i] = translated

    await asyncio.gather(
        *[_translate_chunk(s, texts[s : s + batch_size]) for s in range(0, len(texts), batch_size)]
    )
    return out
