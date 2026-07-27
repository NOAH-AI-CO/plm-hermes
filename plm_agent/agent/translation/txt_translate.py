"""
文本型文件翻译：md、doc、docx、txt → 整篇翻译 → 输出 .md + .docx。
读取阶段统一走 format_convert 的转 md 流程（doc/docx 会上传图片并插入链接），
再由 LLM 整篇/分块翻译，并基于译文 md 预生成多种下载格式。
MD 中的内联图片可先走与 PDF 内图相同的「Paddle+VLM」翻译流程，再翻译正文。
与 ocr_translate 一致：直写 DB、上传私有 blob、写回 translated_attachment_id（主结果 docx）+ context 可带 md_attachment_id。
"""
import asyncio
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

from config import api_config
from agent.translation.llm_translate import llm_detect_language, llm_translate_page_full_text
from agent.translation.glossary.es_search import search_glossary_batch
from agent.translation.convert_markdown_to_word import convert_markdown_to_word
from agent.translation.format_convert import _upload_image_and_get_url

# 文本型扩展名（用于路由与校验）
TEXT_EXTENSIONS = {".md", ".doc", ".docx", ".txt"}


def _normalize_language_name(lang: str) -> str:
    """规范语言名：cn -> Chinese, en -> English 等，与 ocr_translate 一致。"""
    m = {
        "cn": "Chinese",
        "en": "English",
        "zh": "Chinese",
        "zh-CN": "Chinese",
        "ja": "Japanese",
        "jp": "Japanese",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "ko": "Korean",
        "ru": "Russian",
    }
    key = (lang or "").strip().lower()
    return m.get(key, lang or "Chinese")


def _markdown_word_format_type(target_language: Optional[str]) -> str:
    s = (target_language or "").strip().lower()
    if s in {"cn", "zh", "zh-CN", "ch", "chinese", "chinese traditional"}:
        return "chinese"
    return "english"


def read_document_to_markdown(
    origin_path: str,
    *,
    inline_images_public: bool = False,
    work_dir: Optional[str] = None,
) -> str:
    """
    将 md/doc/docx/txt 转成 markdown 字符串。
    统一走 format_convert 的转 md 流程：
    - doc/docx: convert_word_to_md（可上传图片或写本地）
    - txt: convert_txt_to_md
    - md: 直接读取
    :param inline_images_public: 为 True 且未传 work_dir 时，文档内图片上传到公开存储。
    :param work_dir: 翻译流程用：指定目录写入 MD 与 images/，图片不上传，MD 内为相对路径。
    """
    from agent.translation.format_convert import convert_txt_to_md, convert_word_to_md

    path = Path(origin_path)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {origin_path}")
    suffix = path.suffix.lower()

    if suffix == ".md":
        return path.read_text(encoding="utf-8", errors="ignore")

    if work_dir is not None:
        tmp_md_path = str(Path(work_dir) / f"{path.stem}.md")
        if suffix in {".doc", ".docx"}:
            convert_word_to_md(
                origin_path,
                output_path=tmp_md_path,
                upload_images=False,
            )
        elif suffix == ".txt":
            convert_txt_to_md(origin_path, output_path=tmp_md_path)
        else:
            raise ValueError(f"不支持的文本类型: {suffix}")
        return Path(tmp_md_path).read_text(encoding="utf-8", errors="ignore")

    with tempfile.TemporaryDirectory(prefix="source_to_md_") as tmp_dir:
        tmp_md_path = str(Path(tmp_dir) / f"{path.stem}.md")
        if suffix in {".doc", ".docx"}:
            conn_str = (
                api_config.AZURE_STORAGE_CONNECTION_STRING
                if inline_images_public
                else api_config.AZURE_PRIVATE_STORAGE_CONNECTION_STRING
            )
            converted_md = convert_word_to_md(
                origin_path,
                output_path=tmp_md_path,
                connection_string=conn_str,
                upload_images=True,
            )
        elif suffix == ".txt":
            converted_md = convert_txt_to_md(
                origin_path,
                output_path=tmp_md_path,
            )
        else:
            raise ValueError(f"不支持的文本类型: {suffix}")
        return Path(converted_md).read_text(encoding="utf-8", errors="ignore")


# MD 内联图片：![alt](url)，用于定位并替换为翻译后图片 URL
_INLINE_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


async def _translate_one_image_ref_and_upload(
    ref: str,
    target_language: str,
    blob_prefix: str,
    index: int,
    *,
    base_dir: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    """
    ref 为 URL 时下载，为相对路径时从 base_dir 读；翻译后上传，并写入 base_dir/translated/image_N.jpg。
    返回 (new_url, local_path)。失败时返回 (ref, None)。
    """
    from agent.translation.ocr_translate import translate_image_from_bytes

    image_bytes = None
    if (ref or "").strip().lower().startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(ref)
                resp.raise_for_status()
                image_bytes = resp.content
        except Exception as e:
            logging.warning("[translate inline image] download failed ref=%s err=%s", ref[:80], e)
            return (ref, None)
    elif base_dir:
        local_path = Path(base_dir) / ref
        if local_path.is_file():
            image_bytes = local_path.read_bytes()
        else:
            logging.warning("[translate inline image] local file not found: %s", local_path)
            return (ref, None)
    if not image_bytes:
        return (ref, None)

    translated_dir = Path(base_dir) / "translated" if base_dir else None
    if translated_dir is not None:
        translated_dir.mkdir(parents=True, exist_ok=True)
    out_path = None
    try:
        if translated_dir is not None:
            out_path = str(translated_dir / f"image_{index}.jpg")
        else:
            fd, out_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
        await translate_image_from_bytes(
            image_bytes,
            output_path=out_path,
            target_language=target_language,
        )
        with open(out_path, "rb") as f:
            out_bytes = f.read()
        blob_key = f"{blob_prefix}/image_{index}.jpg"
        new_url = _upload_image_and_get_url(
            out_bytes,
            container="nudata",
            blob_key=blob_key,
            connection_string=api_config.AZURE_STORAGE_CONNECTION_STRING,
            read_url_expiry_days=365,
        )
        local_ret = out_path if (translated_dir and Path(out_path).is_file()) else None
        return (new_url or ref, local_ret)
    except Exception as e:
        logging.warning("[translate inline image] ref=%s failed: %s", ref[:80], e)
        return (ref, None)
    finally:
        if not base_dir and out_path and os.path.isfile(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass


async def _translate_inline_images_in_md(
    md_content: str,
    target_language: str,
    *,
    blob_prefix: Optional[str] = None,
    base_dir: Optional[str] = None,
) -> tuple[str, dict[str, str]]:
    """
    解析 MD 中所有 ![alt](ref)，对每张图翻译并上传；ref 为本地路径时从 base_dir 读（不下载）。
    返回 (替换后的 md_content, url_to_local_path)，便于后续 docx/pdf 用本地文件插入不下载。
    """
    matches = list(_INLINE_IMAGE_MD_RE.finditer(md_content))
    if not matches:
        return (md_content, {})
    prefix = blob_prefix or f"attachments/translation/inline/{int(time.time())}"
    new_urls: list[str] = []
    url_to_local: dict[str, str] = {}
    for i, match in enumerate(matches):
        ref = match.group(2)
        new_url, local_path = await _translate_one_image_ref_and_upload(
            ref,
            target_language,
            prefix,
            i,
            base_dir=base_dir,
        )
        new_urls.append(new_url)
        if local_path:
            url_to_local[new_url] = local_path
    result = md_content
    for i in range(len(matches) - 1, -1, -1):
        m = matches[i]
        alt = m.group(1)
        result = result[: m.start()] + f"![{alt}]({new_urls[i]})" + result[m.end() :]
    return (result, url_to_local)


# 单次翻译大致字符上限，避免超长上下文
_CHUNK_CHARS = 6000


async def _translate_chunk(
    chunk: str,
    target_language: Optional[str],
    prev_full_text: str,
    *,
    translation_model_id: str = "",
    translate_reference: bool = False,
    glossary_hint: str = "",
) -> str:
    """翻译一段文本，带上一段译文作为上下文。"""
    if not chunk or not chunk.strip():
        return ""
    text_dict = {"0": chunk}
    # target_language 为空时由 llm_translate_page_full_text 内部执行「自动中英互译」规则
    # prefer_markdown=True：文本类文件输出优先使用 Markdown 语法，避免 LLM 生成 HTML 标签
    return await llm_translate_page_full_text(
        text_dict,
        target_language=target_language or "",
        prev_full_text=prev_full_text,
        translation_model_id=translation_model_id,
        keep_reference_in_original=not translate_reference,
        prefer_markdown=True,
        glossary_hint=glossary_hint,
    )


async def translate_markdown(
    md_text: str,
    target_language: str,
    *,
    input_language: Optional[str] = None,
    translation_model_id: str = "",
    translate_reference: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> str:
    """
    将整篇 markdown 文本翻译为目标语言。长文分块翻译，用上一块译文做上下文。
    当 target_language 为空时，采用自动中英互译规则：中文 → 英文，其它语言 → 中文。
    translate_reference=False 时通过提示词让 LLM 对参考文献类内容保持原文；True 时全文翻译。
    """
    auto_mode = not target_language or not str(target_language).strip()
    target = None if auto_mode else _normalize_language_name(target_language)
    if not md_text or not md_text.strip():
        return ""

    source_md = md_text.strip()

    # Resolve whether glossary should be used (only for Chinese<->English pairs)
    _GLOSSARY_LANGUAGES = {"Chinese", "English"}
    target_norm = target or ""
    glossary_enabled = False
    if use_glossary and target_norm in _GLOSSARY_LANGUAGES:
        try:
            detected_source = await llm_detect_language(source_md[:1000])
            if detected_source in _GLOSSARY_LANGUAGES:
                glossary_enabled = True
                print(f"[txt_translate glossary] enabled: {detected_source} -> {target_norm}")
            else:
                print(f"[txt_translate glossary] disabled: source={detected_source} not in Chinese/English scope")
        except Exception as _lang_exc:
            print(f"[txt_translate glossary] language detection failed, glossary disabled: {_lang_exc}")

    # 按段落粗分，再按字符数合并为块
    parts = source_md.split("\n\n")
    chunks = []
    current = []
    current_len = 0
    for p in parts:
        p_strip = p.strip()
        if not p_strip:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            continue
        add_len = len(p) + 2
        if current_len + add_len > _CHUNK_CHARS and current:
            chunks.append("\n\n".join(current))
            current = [p_strip]
            current_len = len(p_strip)
        else:
            current.append(p_strip)
            current_len += add_len
    if current:
        chunks.append("\n\n".join(current))

    # Search glossary chunk by chunk, combine and deduplicate all hits into one hint
    combined_glossary_hint = ""
    if glossary_enabled and chunks:
        try:
            all_hits: list[dict] = []
            for chunk in chunks:
                hits = await asyncio.to_thread(
                    search_glossary_batch, [chunk], 12, 12, use_glossary_embedding
                )
                all_hits.extend(hits)
            seen: set[tuple[str, str]] = set()
            deduped = []
            for e in all_hits:
                key = (e.get("cn_term") or "", e.get("en_term") or "")
                if key[0] and key[1] and key not in seen:
                    seen.add(key)
                    deduped.append(e)
            if target_norm == "English":
                combined_glossary_hint = "\n".join(
                    f"{e['cn_term']} : {e['en_term']}" for e in deduped
                )
            else:
                combined_glossary_hint = "\n".join(
                    f"{e['en_term']} : {e['cn_term']}" for e in deduped
                )
            if combined_glossary_hint:
                print(f"[txt_translate glossary] combined hits: {len(all_hits)} -> deduped: {len(deduped)}, hint lines: {len(combined_glossary_hint.splitlines())}")
                print(f"[txt_translate glossary] hint:\n{combined_glossary_hint}")
        except Exception as _glossary_exc:
            print(f"[txt_translate glossary] search failed: {_glossary_exc}")

    prev_full_text = ""
    translated = []
    for chunk in chunks:
        t = await _translate_chunk(
            chunk,
            target,
            prev_full_text,
            translation_model_id=translation_model_id,
            translate_reference=translate_reference,
            glossary_hint=combined_glossary_hint,
        )
        translated.append(t)
        prev_full_text = t
    return "\n\n".join(translated).strip()


async def translate_text_file(
    origin_path: str,
    target_language: str,
    output_dir: Optional[str] = None,
    *,
    input_language: Optional[str] = None,
    translation_model_id: str = "",
    translate_reference: bool = False,
    use_glossary: bool = True,
    use_glossary_embedding: bool = True,
) -> tuple[str, str, dict[str, str]]:
    """
    文本型文件整篇翻译，输出 .md 和 .docx。
    doc/docx 时图片先写本地再翻译上传，转 docx/pdf 时用本地文件插入，无需下载。
    :return: (md_path, docx_path, image_url_to_local_path)，无图时第三项为 {}。
    """
    import shutil

    path = Path(origin_path)
    stem = path.stem
    suffix = path.suffix.lower()
    if output_dir is None:
        output_dir = str(path.parent)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    work_dir = tempfile.mkdtemp(prefix="translate_text_")
    try:
        if suffix in {".doc", ".docx"}:
            md_content = read_document_to_markdown(origin_path, work_dir=work_dir)
        else:
            md_content = read_document_to_markdown(
                origin_path, inline_images_public=True
            )
        if not md_content or not md_content.strip():
            raise ValueError("文档解析结果为空，无法翻译")

        md_content, image_url_to_local_path = await _translate_inline_images_in_md(
            md_content,
            target_language,
            base_dir=work_dir,
        )

        translated_md = await translate_markdown(
            md_content,
            target_language,
            input_language=input_language,
            translation_model_id=translation_model_id,
            translate_reference=translate_reference,
            use_glossary=use_glossary,
            use_glossary_embedding=use_glossary_embedding,
        )
        if not translated_md or not translated_md.strip():
            raise ValueError("翻译结果为空")

        md_name = f"{stem}_translated.md"
        docx_name = f"{stem}_translated.docx"
        md_path = out_dir / md_name
        docx_path = out_dir / docx_name

        # 将翻译图从 work_dir 拷到 out_dir/translated，便于后续 pdf 等用本地路径且不依赖 work_dir
        if work_dir and image_url_to_local_path:
            translated_src = Path(work_dir) / "translated"
            translated_dst = out_dir / "translated"
            if translated_src.is_dir():
                translated_dst.mkdir(parents=True, exist_ok=True)
                for url, local_path in list(image_url_to_local_path.items()):
                    src = Path(local_path)
                    if src.is_file():
                        dst = translated_dst / src.name
                        shutil.copy2(src, dst)
                        image_url_to_local_path[url] = str(dst)

        md_path.write_text(translated_md, encoding="utf-8")
        convert_markdown_to_word(
            str(md_path),
            str(docx_path),
            format_type=_markdown_word_format_type(target_language),
            image_url_to_path=image_url_to_local_path or None,
        )
        if not docx_path.is_file():
            raise RuntimeError("md2docx 未生成 docx 文件")

        return (str(md_path), str(docx_path), image_url_to_local_path or {})
    finally:
        if work_dir and os.path.isdir(work_dir):
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
            except OSError:
                pass


async def translate_document_with_images(
    origin_path: str,
    target_language: str,
    output_dir: Optional[str] = None,
    *,
    input_language: Optional[str] = None,
    translation_model_id: str = "",
) -> tuple[str, str]:
    """
    DOCX/DOC 解析为「文本+图片」片段后：按与图片的相对顺序，将「图片之间的所有文本」合并为一段再翻译
    （减少请求）；图片使用 ocr_image_to_translated_text 一步到位得到译文。最后输出 .md 与 .docx。
    :return: (md_path, docx_path)
    """
    from agent.translation.llm_translate import ocr_image_to_translated_text
    from utils.docs.parsing import parse_document_with_images

    path = Path(origin_path)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {origin_path}")
    name = path.name
    stem = path.stem
    file_bytes = path.read_bytes()
    lower = name.lower()
    if not (lower.endswith(".doc") or lower.endswith(".docx")):
        raise ValueError("translate_document_with_images 仅支持 .doc/.docx")

    if output_dir is None:
        output_dir = str(path.parent)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segments = parse_document_with_images(name, file_bytes)
    # target_language 为空时交由下游 LLM 自动中英互译
    target_lang = _normalize_language_name(target_language) if target_language and target_language.strip() else None

    # 合并「图片之间的所有文本」为一段，只保留与图片的相对顺序，减少请求次数
    runs = []
    text_buf = []
    for seg in segments:
        if seg["type"] == "text":
            content = (seg.get("content") or "").strip()
            if content:
                text_buf.append(content)
        else:
            if text_buf:
                runs.append({"type": "text", "content": "\n\n".join(text_buf)})
                text_buf = []
            runs.append(seg)
    if text_buf:
        runs.append({"type": "text", "content": "\n\n".join(text_buf)})

    with tempfile.TemporaryDirectory(prefix="doc_img_") as tmp_dir:
        translated_parts = []
        tmp_path = Path(tmp_dir)
        for i, run in enumerate(runs):
            if run["type"] == "text":
                merged = (run.get("content") or "").strip()
                if not merged:
                    translated_parts.append("")
                    continue
                part = await translate_markdown(
                    merged,
                    target_lang,
                    input_language=input_language,
                    translation_model_id=translation_model_id,
                )
                translated_parts.append(part)
                continue
            # type == "image"
            content = run.get("content")
            if content:
                img_path = tmp_path / f"image_{run.get('index', i)}.png"
                img_path.write_bytes(content)
                part = await ocr_image_to_translated_text(str(img_path), target_language=target_lang)
                translated_parts.append(part if part.strip() else "[图片]")
            else:
                translated_parts.append("[图片]")

    full_md = "\n\n".join(translated_parts)
    if not full_md.strip():
        raise ValueError("翻译结果为空")

    md_name = f"{stem}_translated.md"
    docx_name = f"{stem}_translated.docx"
    md_path = out_dir / md_name
    docx_path = out_dir / docx_name
    md_path.write_text(full_md, encoding="utf-8")
    convert_markdown_to_word(
        str(md_path),
        str(docx_path),
        format_type=_markdown_word_format_type(target_language),
    )
    if not docx_path.is_file():
        raise RuntimeError("md2docx 未生成 docx 文件")
    return str(md_path), str(docx_path)


async def process_text_translation_by_attachment_id(
    attachment_id: str,
    target_language: str,
    input_language: Optional[str],
    backend_task_id: int,
    translation_model_id: str = "",
    translate_reference: bool = False,
) -> None:
    """
    由 Backend 上传后触发：拉取文本型文件、整篇翻译、输出 md + docx，
    并基于 md 额外预生成 pdf / txt，分步写回 DB。
    """
    import httpx
    from utils.utils.attachment import AttachmentManager
    from utils.azure.blob_client import AzureBlobStorage
    from agent.translation.format_convert import convert_md_to_pdf, convert_md_to_txt
    from agent.translation.db import (
        azure_blob_attachment_storage,
        create_attachment_for_translation,
        read_translation_task,
        write_translation_result,
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

        suffix = Path(file_name).suffix.lower()
        if suffix not in TEXT_EXTENSIONS:
            _fail_task(f"unsupported text type: {suffix}")
            return

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            data = resp.content
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            temp_path = f.name
        try:
            write_translation_result(
                backend_task_id,
                "running",
                context_extra={"current_page": 1, "total_pages": 1},
            )
            md_path, docx_path, image_url_to_path = await translate_text_file(
                temp_path,
                target_language,
                output_dir=None,
                input_language=input_language,
                translation_model_id=translation_model_id,
                translate_reference=translate_reference,
            )
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        if not Path(md_path).is_file() or not Path(docx_path).is_file():
            _fail_task("translate_text_file did not produce md and docx")
            return

        container = "nudata"
        owner_id = task["owner_id"]
        azure = AzureBlobStorage(
            connection_string=api_config.AZURE_PRIVATE_STORAGE_CONNECTION_STRING,
            read_url_expiry_days=365,
        )

        md_name = Path(md_path).name
        docx_name = Path(docx_path).name
        blob_key_md = f"attachments/translation/{backend_task_id}/{md_name}"
        blob_key_docx = f"attachments/translation/{backend_task_id}/{docx_name}"
        with open(md_path, "rb") as f:
            azure.upload_file(container, blob_key_md, f)
        with open(docx_path, "rb") as f:
            azure.upload_file(container, blob_key_docx, f)
        url_md = azure.get_read_url(container, blob_key_md)
        url_docx = azure.get_read_url(container, blob_key_docx)

        md_attachment_id = create_attachment_for_translation(
            owner_id,
            md_name,
            url_md,
            storage=azure_blob_attachment_storage(container, blob_key_md),
        )
        docx_attachment_id = create_attachment_for_translation(
            owner_id,
            docx_name,
            url_docx,
            storage=azure_blob_attachment_storage(container, blob_key_docx),
        )
        write_translation_result(
            backend_task_id,
            "complete",
            translated_attachment_id=docx_attachment_id,
            context_extra={
                "translated_md_attachment_id": md_attachment_id,
                "translated_md_url": url_md,
                "translated_docx_url": url_docx,
            },
        )

        # 基于译文 md 预生成额外格式：pdf / txt。
        # 采用“生成一个，写回一个”的方式，单个格式失败不影响任务主流程。
        def _upload_one_extra_format(extra_path: str) -> tuple[str, str, str, str]:
            extra_name = Path(extra_path).name
            ext = Path(extra_path).suffix.lower().lstrip(".")
            blob_key = f"attachments/translation/{backend_task_id}/{extra_name}"
            with open(extra_path, "rb") as f:
                azure.upload_file(container, blob_key, f)
            extra_url = azure.get_read_url(container, blob_key)
            extra_attachment_id = create_attachment_for_translation(
                owner_id,
                extra_name,
                extra_url,
                storage=azure_blob_attachment_storage(container, blob_key),
            )
            return ext, extra_name, extra_url, extra_attachment_id

        extra_outputs: list[str] = []
        try:
            pdf_path = await asyncio.to_thread(
                convert_md_to_pdf,
                md_path,
                image_url_to_path=image_url_to_path or None,
            )
            extra_outputs.append(pdf_path)
        except Exception as e:
            logging.warning(f"pre-generate pdf failed (task={backend_task_id}): {e}")

        try:
            txt_path = await asyncio.to_thread(convert_md_to_txt, md_path)
            extra_outputs.append(txt_path)
        except Exception as e:
            logging.warning(f"pre-generate txt failed (task={backend_task_id}): {e}")

        for extra_path in extra_outputs:
            if not Path(extra_path).is_file():
                continue
            try:
                ext, _name, extra_url, extra_attachment_id = _upload_one_extra_format(extra_path)
                write_translation_result(
                    backend_task_id,
                    "complete",
                    context_extra={
                        f"translated_{ext}_attachment_id": extra_attachment_id,
                        f"translated_{ext}_url": extra_url,
                    },
                )
            except Exception as e:
                logging.warning(f"upload extra format failed (task={backend_task_id}, path={extra_path}): {e}")
            finally:
                try:
                    os.unlink(extra_path)
                except OSError:
                    pass

        try:
            os.unlink(md_path)
            os.unlink(docx_path)
        except OSError:
            pass
    except Exception as e:
        logging.exception("process_text_translation_by_attachment_id failed")
        _fail_task(str(e))
