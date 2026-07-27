"""
Unified PLM guidelines index: combines Path 1 (text+vectors for RAG) and
Path 2 (decision graph with nodes/edges/care_phases) in a single ES table.

Indexes:
    - plm_guidelines: document-level metadata, full text, TOC, summary, graph source data
    - plm_guideline_chunks: page/chunk-level passages for evidence retrieval

Doc ID: int(md5(filename)[:15], 16)  — deterministic from filename
"""
import logging
from hashlib import md5

from elasticsearch import Elasticsearch

from config import api_config

logger = logging.getLogger(__name__)

PLM_INDEX = "plm_guidelines"
PLM_CHUNK_INDEX = "plm_guideline_chunks"

_es_client: Elasticsearch | None = None


def get_es_client() -> Elasticsearch:
    global _es_client
    if _es_client is None:
        _es_client = Elasticsearch(
            hosts=api_config.ES_HOST,
            basic_auth=(
                api_config.ES_USERNAME,
                api_config.ES_PASSWORD,
            ),
            max_retries=5,
            retry_on_timeout=True,
            request_timeout=30,
        )
    return _es_client


def make_doc_id(filename: str) -> int:
    return int(md5(filename.encode("utf-8")).hexdigest()[:15], 16)


_PLM_MAPPINGS = {
    "dynamic": False,
    "properties": {
        # --- Identity ---
        "doc_id": {"type": "long"},
        "filename": {"type": "keyword"},
        "file_path": {"type": "keyword"},
        "is_cn_content": {"type": "boolean"},
        "guideline_key": {"type": "keyword"},
        "page_count": {"type": "integer"},
        "char_count": {"type": "integer"},

        # --- Path 1: text fields ---
        "title_cn": {"type": "text"},
        "content": {"type": "text"},
        "toc": {"type": "text"},
        "summary": {"type": "text"},

        # --- Path 1: vector fields for KNN ---
        "title_vector": {
            "type": "dense_vector", "dims": 1024,
            "index": True, "similarity": "cosine",
        },
        "toc_vector": {
            "type": "dense_vector", "dims": 1024,
            "index": True, "similarity": "cosine",
        },
        "summary_vector": {
            "type": "dense_vector", "dims": 1024,
            "index": True, "similarity": "cosine",
        },

        # --- Path 2: graph metadata (searchable) ---
        "has_graph": {"type": "boolean"},
        "guideline_name": {"type": "keyword"},
        "organization": {"type": "keyword"},
        "version": {"type": "integer"},
        "year": {"type": "integer"},
        "description": {"type": "text"},
        "next_id": {"type": "integer"},

        # --- 产品隔离 & 付费门禁 (sahzu 付费专区) ---
        # product_scope: 'public' | 'sahzu_only'; 缺省视为 public。
        # paid: 是否受付费门禁 (未解锁一律屏蔽)。
        "product_scope": {"type": "keyword"},
        "paid": {"type": "boolean"},

        # --- Path 2: graph entities (stored, not indexed) ---
        # dynamic=false at index level means these arrays are stored
        # in _source but not indexed, which is what we want.
        # They are: files, pages, nodes, edge_rules, conditions,
        # node_entry_conditions, page_links, page_global_rules, care_phases
    },
}


_PLM_CHUNK_MAPPINGS = {
    "dynamic": False,
    "properties": {
        "chunk_id": {"type": "keyword"},
        "doc_id": {"type": "long"},
        "filename": {"type": "keyword"},
        "filename_text": {"type": "text"},
        "file_path": {"type": "keyword"},
        "guideline_key": {"type": "keyword"},
        "is_cn_content": {"type": "boolean"},
        "year": {"type": "integer"},
        "version": {"type": "integer"},
        "page_start": {"type": "integer"},
        "page_end": {"type": "integer"},
        "section_title": {"type": "text"},
        "text": {"type": "text"},
        "text_vector": {
            "type": "dense_vector", "dims": 1024,
            "index": True, "similarity": "cosine",
        },
    },
}


def ensure_plm_index() -> None:
    client = get_es_client()
    if not client.indices.exists(index=PLM_INDEX):
        client.indices.create(index=PLM_INDEX, mappings=_PLM_MAPPINGS)
        logger.info("Created index '%s'.", PLM_INDEX)
    else:
        logger.info("Index '%s' already exists.", PLM_INDEX)


def ensure_plm_chunk_index() -> None:
    client = get_es_client()
    if not client.indices.exists(index=PLM_CHUNK_INDEX):
        client.indices.create(index=PLM_CHUNK_INDEX, mappings=_PLM_CHUNK_MAPPINGS)
        logger.info("Created index '%s'.", PLM_CHUNK_INDEX)
    else:
        logger.info("Index '%s' already exists.", PLM_CHUNK_INDEX)


def ensure_plm_indices() -> None:
    ensure_plm_index()
    ensure_plm_chunk_index()


def upgrade_plm_index_scope_fields() -> None:
    """幂等地把 product_scope / paid 补到已有索引 (老索引无这些字段时使用)。"""
    client = get_es_client()
    if not client.indices.exists(index=PLM_INDEX):
        ensure_plm_index()
        return
    client.indices.put_mapping(
        index=PLM_INDEX,
        properties={
            "product_scope": {"type": "keyword"},
            "paid": {"type": "boolean"},
        },
    )
