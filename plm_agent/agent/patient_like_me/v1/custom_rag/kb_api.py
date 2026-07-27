"""
FastAPI endpoints for PLM custom RAG.

Two-phase flow:
  1. Upload: POST /documents/upload  (single or batch, parse + store, no embedding)
  2. Process: POST /documents/process (batch chunk + embed + index)

Users can add/delete files freely between phases.
"""
from __future__ import annotations

import logging
import traceback
from typing import List

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from .chunking import ChunkConfig, ChunkStrategy
from . import kb_index
from . import kb_pipeline
from .kb_search import search_knowledge_base

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plm_custom_rag", tags=["PLM Custom RAG"])


def _build_chunk_config(
    chunk_strategy: str = "fixed_size",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    separator: str = "\n\n",
) -> ChunkConfig:
    try:
        strategy = ChunkStrategy(chunk_strategy)
    except ValueError:
        strategy = ChunkStrategy.FIXED_SIZE
    chunk_size = max(100, min(5000, chunk_size))
    chunk_overlap = max(0, min(500, chunk_overlap))
    return ChunkConfig(
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separator=separator,
    )


# ---------------------------------------------------------------------------
# Init & Stats
# ---------------------------------------------------------------------------

@router.post("/init")
async def init_custom_rag():
    try:
        created = await kb_index.ensure_kb_indices()
        return JSONResponse({"status": "ok", "indices_created": created})
    except Exception as e:
        logger.error("Custom RAG init error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/stats")
async def get_stats():
    try:
        stats = await kb_index.get_kb_stats()
        return JSONResponse(stats)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Phase 1: Upload (parse + store, no chunking/embedding)
# ---------------------------------------------------------------------------

@router.post("/documents/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """Upload one or more files. Parses them to text and stores in ES.
    Does NOT chunk or embed — call /documents/process after uploading."""
    if not files:
        return JSONResponse({"error": "至少上传一个文件"}, status_code=400)

    file_data = []
    for f in files:
        if not f.filename:
            continue
        content = await f.read()
        file_data.append((f.filename, content))

    if not file_data:
        return JSONResponse({"error": "无有效文件"}, status_code=400)

    try:
        results = await kb_pipeline.upload_documents_batch(file_data)
        return JSONResponse({
            "uploaded": results,
            "total": len(results),
            "success": sum(1 for r in results if r.get("status") != "error"),
        })
    except Exception as e:
        logger.error("Upload error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Phase 2: Process (chunk + embed + index)
# ---------------------------------------------------------------------------

@router.post("/documents/process")
async def process_documents(body: dict):
    """Batch process uploaded documents: chunk → embed → index.

    Body:
        doc_ids: list[str] | None  — specific docs to process (None = all uploaded)
        chunk_strategy: str = "fixed_size"
        chunk_size: int = 500
        chunk_overlap: int = 50
        separator: str = "\\n\\n"
    """
    config = _build_chunk_config(
        body.get("chunk_strategy", "fixed_size"),
        body.get("chunk_size", 500),
        body.get("chunk_overlap", 50),
        body.get("separator", "\n\n"),
    )

    doc_ids = body.get("doc_ids")
    if not doc_ids:
        _, docs = await kb_index.list_documents_by_status(["uploaded", "error"])
        doc_ids = [d["doc_id"] for d in docs]

    if not doc_ids:
        return JSONResponse({"error": "没有待处理的文档"}, status_code=400)

    try:
        results = await kb_pipeline.process_documents(doc_ids, config)
        return JSONResponse({
            "results": results,
            "total": len(results),
            "success": sum(1 for r in results if r.get("status") == "ready"),
        })
    except Exception as e:
        logger.error("Process error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------

@router.get("/documents")
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = Query(None),
):
    """List documents, optionally filtered by status."""
    try:
        total, docs = await kb_index.list_documents(page, page_size, status=status)
        return JSONResponse({"total": total, "documents": docs})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = await kb_index.get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "文档不存在"}, status_code=404)
    doc.pop("raw_text", None)
    return JSONResponse(doc)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    try:
        ok = await kb_pipeline.delete_document(doc_id)
        if not ok:
            return JSONResponse({"error": "文档不存在"}, status_code=404)
        return JSONResponse({"status": "deleted", "doc_id": doc_id})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: str, body: dict = {}):
    """Reprocess a single document with new chunking config."""
    config = _build_chunk_config(
        body.get("chunk_strategy", "fixed_size"),
        body.get("chunk_size", 500),
        body.get("chunk_overlap", 50),
        body.get("separator", "\n\n"),
    )
    try:
        results = await kb_pipeline.process_documents([doc_id], config)
        return JSONResponse(results[0] if results else {"error": "处理失败"})
    except Exception as e:
        logger.error("Reprocess error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Preview (stateless)
# ---------------------------------------------------------------------------

@router.post("/documents/preview_chunks")
async def preview_chunks_from_file(
    file: UploadFile = File(...),
    chunk_strategy: str = Form("fixed_size"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(50),
    separator: str = Form("\n\n"),
    max_preview: int = Form(10),
):
    """Preview chunking result from a new file without storing."""
    if not file.filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)

    config = _build_chunk_config(chunk_strategy, chunk_size, chunk_overlap, separator)
    try:
        file_bytes = await file.read()
        result = await kb_pipeline.preview_chunks_from_file(
            file.filename, file_bytes, config, max_preview,
        )
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Preview error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/documents/{doc_id}/preview_chunks")
async def preview_chunks_by_doc(doc_id: str, body: dict = {}):
    """Preview chunking result from an already-uploaded document (no re-parsing)."""
    config = _build_chunk_config(
        body.get("chunk_strategy", "fixed_size"),
        body.get("chunk_size", 500),
        body.get("chunk_overlap", 50),
        body.get("separator", "\n\n"),
    )
    max_preview = min(50, max(1, body.get("max_preview", 10)))
    try:
        result = await kb_pipeline.preview_chunks_by_doc_id(doc_id, config, max_preview)
        return JSONResponse(result)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.error("Preview error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@router.post("/search")
async def search(body: dict):
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    top_k = min(20, max(1, body.get("top_k", 5)))
    search_mode = body.get("search_mode", "hybrid")
    if search_mode not in ("hybrid", "semantic", "keyword"):
        search_mode = "hybrid"
    doc_ids = body.get("doc_ids")

    try:
        results = await search_knowledge_base(
            query=query, top_k=top_k, search_mode=search_mode, doc_ids=doc_ids,
        )
        return JSONResponse({
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "doc_id": r.doc_id,
                    "filename": r.filename,
                    "text": r.text,
                    "score": round(r.score, 4),
                    "bm25_score": round(r.bm25_score, 4),
                    "knn_score": round(r.knn_score, 4),
                    "chunk_index": r.chunk_index,
                    "highlight": r.highlight,
                }
                for r in results
            ],
            "total": len(results),
            "query": query,
        })
    except Exception as e:
        logger.error("Search error: %s", traceback.format_exc())
        return JSONResponse({"error": str(e)}, status_code=500)
