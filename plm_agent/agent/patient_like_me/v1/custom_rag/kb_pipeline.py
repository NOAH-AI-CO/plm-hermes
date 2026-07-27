"""
Document processing pipeline — two-phase design:

Phase 1 (upload):   parse file → store raw_text + metadata in ES (status=uploaded)
Phase 2 (process):  chunk → embed → index chunks (status=ready)
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from io import BytesIO
from typing import Callable

from .chunking import ChunkConfig, chunk_text
from .embedding import batch_embed
from . import kb_index

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
_MAX_FILE_SIZE_MB = 50
_MAX_PDF_PAGES = 300

_indices_ensured = False


def _file_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename.lower())
    return ext


async def _ensure_indices_once():
    global _indices_ensured
    if not _indices_ensured:
        await kb_index.ensure_kb_indices()
        _indices_ensured = True


def _pdf_to_text_no_limit(file_bytes: bytes) -> str | None:
    """Extract text from PDF using pypdf without page limit."""
    import pypdf
    try:
        reader = pypdf.PdfReader(BytesIO(file_bytes))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        result = "\n".join(texts)
        return result if result.strip() else None
    except Exception as e:
        logger.warning("[kb_pipeline] pypdf extraction failed: %s", e)
        return None


async def _parse_file(filename: str, file_bytes: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = await asyncio.to_thread(_pdf_to_text_no_limit, file_bytes)
        if text:
            return text
    if lower.endswith(".txt") or lower.endswith(".md"):
        return file_bytes.decode("utf-8", errors="ignore")
    from utils.docs.parsing import convert_document
    return await asyncio.to_thread(convert_document, filename, file_bytes)


# ---------------------------------------------------------------------------
# Phase 1: Upload — parse and store, no chunking/embedding
# ---------------------------------------------------------------------------

async def upload_document(filename: str, file_bytes: bytes) -> dict:
    ext = _file_extension(filename)
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"不支持的文件类型: {ext}。支持: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )

    file_size_mb = len(file_bytes) / (1024 * 1024)
    if file_size_mb > _MAX_FILE_SIZE_MB:
        raise ValueError(f"文件过大: {file_size_mb:.1f}MB，上限 {_MAX_FILE_SIZE_MB}MB")

    if ext == ".pdf":
        import pypdf
        try:
            reader = pypdf.PdfReader(BytesIO(file_bytes))
            if len(reader.pages) > _MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF 页数过多: {len(reader.pages)} 页，上限 {_MAX_PDF_PAGES} 页"
                )
        except pypdf.errors.PdfReadError as e:
            raise ValueError(f"PDF 文件损坏或无法读取: {e}")

    await _ensure_indices_once()

    raw_text = await _parse_file(filename, file_bytes)
    if not raw_text or not raw_text.strip():
        raise ValueError("文件解析后无文本内容")

    doc_id = uuid.uuid4().hex[:16]
    doc = {
        "doc_id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_size": len(file_bytes),
        "char_count": len(raw_text),
        "chunk_count": 0,
        "status": "uploaded",
        "content_preview": raw_text[:500],
        "raw_text": raw_text,
    }
    await kb_index.index_document(doc)

    logger.info("[kb_pipeline] Uploaded '%s' (%d chars) → doc_id=%s", filename, len(raw_text), doc_id)
    return {
        "doc_id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "char_count": len(raw_text),
        "status": "uploaded",
    }


async def upload_documents_batch(
    files: list[tuple[str, bytes]],
) -> list[dict]:
    results = []
    for filename, file_bytes in files:
        try:
            info = await upload_document(filename, file_bytes)
            results.append(info)
        except Exception as e:
            results.append({
                "filename": filename,
                "status": "error",
                "error_message": str(e),
            })
    return results


# ---------------------------------------------------------------------------
# Phase 2: Process — chunk + embed + index
# ---------------------------------------------------------------------------

async def _process_single(doc_id: str, chunk_config: ChunkConfig) -> dict:
    doc = await kb_index.get_document(doc_id)
    if not doc:
        raise ValueError(f"文档不存在: {doc_id}")

    raw_text = doc.get("raw_text")
    if not raw_text:
        raise ValueError("文档无原始文本")

    await kb_index.update_document(doc_id, {"status": "processing"})

    try:
        await kb_index.delete_chunks_by_doc(doc_id)

        chunks = chunk_text(raw_text, chunk_config)
        if not chunks:
            raise ValueError("分块结果为空")

        texts = [c.text for c in chunks]
        vectors = await batch_embed(texts)

        filename = doc.get("filename", "")
        es_chunks = []
        for chunk, vec in zip(chunks, vectors):
            es_chunks.append({
                "chunk_id": f"{doc_id}:{chunk.chunk_index}",
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "text_vector": vec,
                "char_offset": chunk.char_offset,
                "char_length": chunk.char_length,
            })

        indexed = await kb_index.bulk_index_chunks(es_chunks)

        await kb_index.update_document(doc_id, {
            "status": "ready",
            "chunk_count": indexed,
            "chunk_strategy": chunk_config.strategy.value,
            "chunk_size": chunk_config.chunk_size,
            "chunk_overlap": chunk_config.chunk_overlap,
            "separator": chunk_config.separator,
        })

        logger.info("[kb_pipeline] Processed doc %s: %d chunks indexed.", doc_id, indexed)
        return {"doc_id": doc_id, "chunk_count": indexed, "status": "ready"}

    except Exception as e:
        await kb_index.update_document(doc_id, {
            "status": "error",
            "error_message": str(e),
        })
        return {"doc_id": doc_id, "status": "error", "error_message": str(e)}


async def process_documents(
    doc_ids: list[str],
    chunk_config: ChunkConfig,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    results = []
    total = len(doc_ids)
    for i, doc_id in enumerate(doc_ids):
        result = await _process_single(doc_id, chunk_config)
        results.append(result)
        if on_progress:
            on_progress(i + 1, total)
    return results


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_document(doc_id: str) -> bool:
    deleted_chunks = await kb_index.delete_chunks_by_doc(doc_id)
    deleted_doc = await kb_index.delete_document_record(doc_id)
    logger.info(
        "[kb_pipeline] Deleted doc %s: %d chunks removed, doc_record=%s",
        doc_id, deleted_chunks, deleted_doc,
    )
    return deleted_doc


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

async def preview_chunks_by_doc_id(
    doc_id: str,
    chunk_config: ChunkConfig,
    max_preview: int = 10,
) -> dict:
    """Preview chunks from an already-uploaded document (no re-parsing)."""
    doc = await kb_index.get_document(doc_id)
    if not doc:
        raise ValueError(f"文档不存在: {doc_id}")
    raw_text = doc.get("raw_text", "")
    if not raw_text:
        raise ValueError("文档无原始文本")

    chunks = chunk_text(raw_text, chunk_config)
    preview = [
        {"chunk_index": c.chunk_index, "text": c.text, "char_length": c.char_length}
        for c in chunks[:max_preview]
    ]
    return {
        "doc_id": doc_id,
        "filename": doc.get("filename", ""),
        "total_chunks": len(chunks),
        "preview": preview,
        "char_count": len(raw_text),
    }


async def preview_chunks_from_file(
    filename: str,
    file_bytes: bytes,
    chunk_config: ChunkConfig,
    max_preview: int = 10,
) -> dict:
    """Preview chunks from a new file (stateless, no storage)."""
    raw_text = await _parse_file(filename, file_bytes)
    if not raw_text or not raw_text.strip():
        return {"total_chunks": 0, "preview": [], "char_count": 0}

    chunks = chunk_text(raw_text, chunk_config)
    preview = [
        {"chunk_index": c.chunk_index, "text": c.text, "char_length": c.char_length}
        for c in chunks[:max_preview]
    ]
    return {
        "total_chunks": len(chunks),
        "preview": preview,
        "char_count": len(raw_text),
    }
