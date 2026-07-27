"""ES index definitions and CRUD for user knowledge base."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from elasticsearch import AsyncElasticsearch

from config import api_config

logger = logging.getLogger(__name__)

KB_DOC_INDEX = "plm_user_kb_documents"
KB_CHUNK_INDEX = "plm_user_kb_chunks"

_async_client: AsyncElasticsearch | None = None


def _get_async_client() -> AsyncElasticsearch:
    global _async_client
    if _async_client is None:
        _async_client = AsyncElasticsearch(
            hosts=api_config.ES_HOST,
            basic_auth=(api_config.ES_USERNAME, api_config.ES_PASSWORD),
            max_retries=5,
            retry_on_timeout=True,
            request_timeout=30,
        )
    return _async_client


_KB_DOC_MAPPINGS = {
    "dynamic": False,
    "properties": {
        "doc_id":          {"type": "keyword"},
        "filename":        {"type": "keyword"},
        "file_type":       {"type": "keyword"},
        "file_size":       {"type": "long"},
        "char_count":      {"type": "integer"},
        "chunk_count":     {"type": "integer"},
        "chunk_strategy":  {"type": "keyword"},
        "chunk_size":      {"type": "integer"},
        "chunk_overlap":   {"type": "integer"},
        "separator":       {"type": "keyword"},
        "status":          {"type": "keyword"},
        "error_message":   {"type": "text"},
        "content_preview": {"type": "text"},
        "raw_text":        {"type": "text", "index": False},
        "created_at":      {"type": "date"},
        "updated_at":      {"type": "date"},
    },
}

_KB_CHUNK_MAPPINGS = {
    "dynamic": False,
    "properties": {
        "chunk_id":     {"type": "keyword"},
        "doc_id":       {"type": "keyword"},
        "filename":     {"type": "keyword"},
        "chunk_index":  {"type": "integer"},
        "text":         {"type": "text"},
        "text_vector":  {
            "type": "dense_vector",
            "dims": 1024,
            "index": True,
            "similarity": "cosine",
        },
        "char_offset":  {"type": "integer"},
        "char_length":  {"type": "integer"},
    },
}


async def ensure_kb_indices() -> list[str]:
    es = _get_async_client()
    created = []
    for idx, mapping in [
        (KB_DOC_INDEX, _KB_DOC_MAPPINGS),
        (KB_CHUNK_INDEX, _KB_CHUNK_MAPPINGS),
    ]:
        if not await es.indices.exists(index=idx):
            await es.indices.create(index=idx, mappings=mapping)
            logger.info("Created index '%s'.", idx)
            created.append(idx)
        else:
            logger.info("Index '%s' already exists.", idx)
    return created


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

async def index_document(doc: dict) -> None:
    es = _get_async_client()
    doc.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    doc.setdefault("updated_at", doc["created_at"])
    await es.index(index=KB_DOC_INDEX, id=doc["doc_id"], document=doc)
    await es.indices.refresh(index=KB_DOC_INDEX)


async def update_document(doc_id: str, fields: dict) -> None:
    es = _get_async_client()
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await es.update(index=KB_DOC_INDEX, id=doc_id, doc=fields)
    await es.indices.refresh(index=KB_DOC_INDEX)


async def get_document(doc_id: str) -> dict | None:
    es = _get_async_client()
    try:
        resp = await es.get(index=KB_DOC_INDEX, id=doc_id)
        return resp["_source"]
    except Exception:
        return None


async def delete_document_record(doc_id: str) -> bool:
    es = _get_async_client()
    try:
        await es.delete(index=KB_DOC_INDEX, id=doc_id)
        await es.indices.refresh(index=KB_DOC_INDEX)
        return True
    except Exception:
        return False


async def list_documents(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> tuple[int, list[dict]]:
    es = _get_async_client()
    query: dict = {"match_all": {}} if not status else {"term": {"status": status}}
    body = {
        "query": query,
        "sort": [{"created_at": {"order": "desc"}}],
        "from": (page - 1) * page_size,
        "size": page_size,
        "_source": {"excludes": ["raw_text"]},
    }
    resp = await es.search(index=KB_DOC_INDEX, body=body)
    total = resp["hits"]["total"]["value"]
    docs = [hit["_source"] for hit in resp["hits"]["hits"]]
    return total, docs


async def list_documents_by_status(statuses: list[str]) -> tuple[int, list[dict]]:
    es = _get_async_client()
    body = {
        "query": {"terms": {"status": statuses}},
        "sort": [{"created_at": {"order": "desc"}}],
        "size": 1000,
        "_source": {"excludes": ["raw_text"]},
    }
    resp = await es.search(index=KB_DOC_INDEX, body=body)
    total = resp["hits"]["total"]["value"]
    docs = [hit["_source"] for hit in resp["hits"]["hits"]]
    return total, docs


async def has_any_documents() -> bool:
    es = _get_async_client()
    try:
        if not await es.indices.exists(index=KB_DOC_INDEX):
            return False
        resp = await es.count(index=KB_DOC_INDEX, query={"term": {"status": "ready"}})
        return resp["count"] > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Chunk CRUD
# ---------------------------------------------------------------------------

async def bulk_index_chunks(chunks: list[dict]) -> int:
    if not chunks:
        return 0
    es = _get_async_client()
    actions = []
    for c in chunks:
        actions.append({"index": {"_index": KB_CHUNK_INDEX, "_id": c["chunk_id"]}})
        actions.append(c)
    resp = await es.bulk(operations=actions)
    await es.indices.refresh(index=KB_CHUNK_INDEX)
    failed = sum(1 for item in resp["items"] if item["index"].get("error"))
    return len(chunks) - failed


async def delete_chunks_by_doc(doc_id: str) -> int:
    es = _get_async_client()
    try:
        resp = await es.delete_by_query(
            index=KB_CHUNK_INDEX,
            query={"term": {"doc_id": doc_id}},
            refresh=True,
        )
        return resp.get("deleted", 0)
    except Exception:
        return 0


async def get_kb_stats() -> dict:
    es = _get_async_client()
    stats = {"document_count": 0, "chunk_count": 0, "total_chars": 0}
    try:
        if not await es.indices.exists(index=KB_DOC_INDEX):
            return stats
        doc_count = await es.count(index=KB_DOC_INDEX, query={"term": {"status": "ready"}})
        stats["document_count"] = doc_count["count"]

        if await es.indices.exists(index=KB_CHUNK_INDEX):
            chunk_count = await es.count(index=KB_CHUNK_INDEX)
            stats["chunk_count"] = chunk_count["count"]

        agg_resp = await es.search(
            index=KB_DOC_INDEX,
            size=0,
            query={"term": {"status": "ready"}},
            aggs={"total_chars": {"sum": {"field": "char_count"}}},
        )
        stats["total_chars"] = int(
            agg_resp["aggregations"]["total_chars"]["value"]
        )
    except Exception as e:
        logger.warning("Failed to get KB stats: %s", e)
    return stats
