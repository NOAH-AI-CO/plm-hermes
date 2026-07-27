import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import traceback
import urllib.request
from datetime import datetime, timezone
from typing import Any, TypedDict

from elasticsearch import NotFoundError

from agent.ethics.ethics_elastic_search import EthicsElasticsearchClientSingleton
from agent.iit.utils.guidelines.embedding import get_embedding
from llm.composite_models import EthicsPolicyMetadataModels
from utils.docs.parsing import convert_document
from utils.sql_client import get_connection_user, text

logger = logging.getLogger(__name__)

ETHICS_POLICY_SYSTEM_CHINA_INDEX = "ethics_policy_system_china_v1"
ETHICS_POLICY_SYSTEM_GLOBAL_INDEX = "ethics_policy_system_global_v1"
ETHICS_POLICY_USER_INDEX = "ethics_policy_user_v1"
ETHICS_POLICY_ANGLE_ROUTE: dict[str, list[str]] = {
    "intl_baseline": [ETHICS_POLICY_SYSTEM_GLOBAL_INDEX],
    "china_regulatory": [ETHICS_POLICY_SYSTEM_CHINA_INDEX],
    "gcp_trials": [ETHICS_POLICY_SYSTEM_CHINA_INDEX, ETHICS_POLICY_SYSTEM_GLOBAL_INDEX],
    "genetics_samples": [ETHICS_POLICY_SYSTEM_CHINA_INDEX, ETHICS_POLICY_USER_INDEX],
    "cross_cutting": [ETHICS_POLICY_USER_INDEX, ETHICS_POLICY_SYSTEM_CHINA_INDEX, ETHICS_POLICY_SYSTEM_GLOBAL_INDEX],
}
POLICY_INDEX_STATUS_PROCESSING = "processing"
POLICY_INDEX_STATUS_READY = "ready"
POLICY_INDEX_STATUS_FAILED = "failed"
_EMBEDDING_DIMS = 1024
_RRF_K = 60
_POLICY_META_MAX_CHARS = 12000
_DOC_CONVERT_TIMEOUT_SECONDS = 180
_POLICY_TYPE_ALLOWED_VALUES: set[str] = {
    "law_regulation",
    "guideline",
    "gcp_sop",
    "technical_standard",
    "review_template",
    "notice_announcement",
    "other",
}
_CHINA_REGION_TOKENS: set[str] = {"china", "cn", "domestic", "zh", "中国", "国内", "境内"}
_POLICY_METADATA_SYS_PROMPT = """
你是“伦理政策文档元数据抽取器”。
请从输入的文档标题与正文中抽取以下字段，并仅返回 JSON：
{
  "issuer": "发布机构，无法判断返回空字符串",
  "publication_date": "优先 YYYY-MM-DD；其次 YYYY-MM；再次 YYYY；无法判断返回空字符串",
  "policy_type": "限定枚举: law_regulation|guideline|gcp_sop|technical_standard|review_template|notice_announcement|other"
}

抽取规则：
1) 只依据给定文本，不要编造。
2) policy_type 必须在限定枚举内。
3) 若文本存在多个日期，优先“发布/印发/生效”相关日期；无法确认返回空字符串。
4) 返回必须是合法 JSON，不要 markdown，不要额外解释。
""".strip()


class PolicyMetadataResult(TypedDict):
    issuer: str
    publication_date: str
    policy_type: str

_es_client = EthicsElasticsearchClientSingleton.get_client()


def _resolve_es_client(es_client: Any | None = None) -> Any:
    return es_client or _es_client


def _normalize_policy_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _POLICY_TYPE_ALLOWED_VALUES:
        return normalized
    if normalized:
        return "other"
    return ""


def _normalize_publication_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    for fmt in ("%Y-%m", "%Y/%m", "%Y.%m"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}", raw):
        return raw
    return ""


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    json_str = text[start : end + 1]
    try:
        parsed = json.loads(json_str)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


async def _extract_policy_metadata_with_llm(*, doc_name: str, content_text: str) -> PolicyMetadataResult:
    sampled_text = (content_text or "").strip()
    if len(sampled_text) > _POLICY_META_MAX_CHARS:
        sampled_text = sampled_text[:_POLICY_META_MAX_CHARS]
    if not sampled_text:
        return {"issuer": "", "publication_date": "", "policy_type": ""}

    user_prompt = (
        f"文档标题:\n{doc_name or ''}\n\n"
        f"文档正文(截断):\n{sampled_text}\n\n"
        "请严格按 JSON 输出。"
    )
    try:
        llm = EthicsPolicyMetadataModels()
        response_stream = llm.stream_call(
            sys_prompt=_POLICY_METADATA_SYS_PROMPT,
            user_prompt=user_prompt,
            temperature=0,
        )
        raw_response = ""
        async for chunk in response_stream:
            if chunk:
                raw_response += str(chunk)
        payload = _extract_json_object(raw_response)
        issuer = str(payload.get("issuer") or "").strip()
        publication_date = _normalize_publication_date(payload.get("publication_date"))
        policy_type = _normalize_policy_type(payload.get("policy_type"))
        return {
            "issuer": issuer,
            "publication_date": publication_date,
            "policy_type": policy_type,
        }
    except Exception:
        logger.warning("extract policy metadata with llm failed: %s", traceback.format_exc())
        return {"issuer": "", "publication_date": "", "policy_type": ""}


def _merge_llm_metadata_into_props(
    *,
    current_props: dict[str, Any],
    llm_meta: PolicyMetadataResult,
) -> dict[str, Any]:
    merged = dict(current_props or {})
    current_issuer = str(merged.get("issuer") or "").strip()
    current_pub_date = str(merged.get("publication_date") or "").strip()
    current_type = _normalize_policy_type(merged.get("policy_type"))
    inferred_issuer = str(llm_meta.get("issuer") or "").strip()
    inferred_pub_date = _normalize_publication_date(llm_meta.get("publication_date"))
    inferred_type = _normalize_policy_type(llm_meta.get("policy_type"))

    if not current_issuer and inferred_issuer:
        merged["issuer"] = inferred_issuer
    if not current_pub_date and inferred_pub_date:
        merged["publication_date"] = inferred_pub_date
    if not current_type and inferred_type:
        merged["policy_type"] = inferred_type
    return merged


def _ensure_policy_indexes(*, es_client: Any | None = None) -> None:
    target_es_client = _resolve_es_client(es_client)
    base_mappings = {
        "properties": {
            "doc_id": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "scope": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "content": {"type": "text"},
            "content_vector": {
                "type": "dense_vector",
                "dims": _EMBEDDING_DIMS,
                "index": True,
                "similarity": "cosine",
            },
            "policy_type": {"type": "keyword"},
            "issuer": {"type": "keyword"},
            "publication_date": {"type": "keyword"},
            "region": {"type": "keyword"},
            "updated_at": {"type": "date"},
        }
    }
    for idx in (ETHICS_POLICY_SYSTEM_CHINA_INDEX, ETHICS_POLICY_SYSTEM_GLOBAL_INDEX, ETHICS_POLICY_USER_INDEX):
        if not target_es_client.indices.exists(index=idx):
            target_es_client.indices.create(index=idx, mappings={"properties": base_mappings["properties"]})
            continue
        target_es_client.indices.put_mapping(index=idx, properties=base_mappings["properties"])


def _normalize_system_region(region_value: Any) -> str:
    raw = str(region_value or "").strip().lower()
    if raw in _CHINA_REGION_TOKENS:
        return "china"
    return "global"


def _get_system_index_by_region(region_value: Any) -> str:
    region = _normalize_system_region(region_value)
    if region == "china":
        return ETHICS_POLICY_SYSTEM_CHINA_INDEX
    return ETHICS_POLICY_SYSTEM_GLOBAL_INDEX


def _build_sparse_query(query_text: str) -> dict[str, Any]:
    q = (query_text or "").strip()
    return {
        "dis_max": {
            "tie_breaker": 0.1,
            "queries": [
                {"match_phrase": {"title": {"query": q, "boost": 8.0}}},
                {"match_phrase": {"content": {"query": q, "boost": 5.0}}},
                {"match": {"title": {"query": q, "operator": "and", "boost": 4.0}}},
                {"match": {"content": {"query": q, "operator": "and", "boost": 2.5}}},
                {"multi_match": {"query": q, "fields": ["title^2", "content"]}},
            ],
        }
    }


def _rrf_score(rank: int) -> float:
    return 1.0 / (_RRF_K + rank)


def _prepare_embedding_text(text: str, max_chars: int = 6000) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars]


def _hybrid_search_index(
    *,
    index_name: str,
    query_text: str,
    top_k: int,
    owner_id: str | None = None,
    es_client: Any | None = None,
) -> list[dict[str, Any]]:
    target_es_client = _resolve_es_client(es_client)
    q = (query_text or "").strip()
    if not q:
        return []

    keyword_size = max(top_k * 3, top_k)
    vector_size = max(top_k * 3, top_k)
    filter_clauses: list[dict[str, Any]] = []
    if owner_id:
        filter_clauses.append({"term": {"owner_id": str(owner_id)}})

    bm25_body: dict[str, Any] = {
        "size": keyword_size,
        "_source": ["doc_id", "title", "content", "policy_type", "issuer", "publication_date", "scope", "owner_id"],
        "query": {
            "bool": {
                "must": [_build_sparse_query(q)],
                "filter": filter_clauses,
            }
        },
    }

    try:
        bm25_resp = target_es_client.search(index=index_name, body=bm25_body)
        bm25_hits = ((bm25_resp or {}).get("hits") or {}).get("hits") or []
    except Exception:
        logger.error("bm25 search failed on %s: %s", index_name, traceback.format_exc())
        bm25_hits = []

    knn_hits: list[dict[str, Any]] = []
    try:
        query_vector = get_embedding(_prepare_embedding_text(q))
        knn_body: dict[str, Any] = {
            "size": vector_size,
            "_source": ["doc_id", "title", "content", "policy_type", "issuer", "publication_date", "scope", "owner_id"],
            "knn": {
                "field": "content_vector",
                "query_vector": query_vector,
                "k": vector_size,
                "num_candidates": vector_size * 3,
            },
        }
        if filter_clauses:
            knn_body["knn"]["filter"] = {"bool": {"filter": filter_clauses}}
        knn_resp = target_es_client.search(index=index_name, body=knn_body)
        knn_hits = ((knn_resp or {}).get("hits") or {}).get("hits") or []
    except Exception:
        logger.error("knn search failed on %s: %s", index_name, traceback.format_exc())

    merged_scores: dict[str, float] = {}
    merged_sources: dict[str, dict[str, Any]] = {}
    for rank, hit in enumerate(bm25_hits, start=1):
        doc_id = str(hit.get("_id") or "")
        if not doc_id:
            continue
        merged_scores[doc_id] = merged_scores.get(doc_id, 0.0) + _rrf_score(rank)
        if doc_id not in merged_sources:
            merged_sources[doc_id] = hit.get("_source") or {}
    for rank, hit in enumerate(knn_hits, start=1):
        doc_id = str(hit.get("_id") or "")
        if not doc_id:
            continue
        merged_scores[doc_id] = merged_scores.get(doc_id, 0.0) + _rrf_score(rank)
        if doc_id not in merged_sources:
            merged_sources[doc_id] = hit.get("_source") or {}

    ranked_ids = sorted(merged_scores.keys(), key=lambda x: merged_scores[x], reverse=True)
    rows: list[dict[str, Any]] = []
    for doc_id in ranked_ids[:top_k]:
        source = merged_sources.get(doc_id) or {}
        source["retrieval_score"] = merged_scores.get(doc_id, 0.0)
        rows.append(source)
    return rows


def search_policy_context(*, owner_id: str, query_text: str, top_k: int = 5, es_client: Any | None = None) -> list[dict[str, Any]]:
    _ensure_policy_indexes(es_client=es_client)
    query = (query_text or "").strip()
    if not query:
        query = "ethics policy review"
    user_hits = _hybrid_search_index(
        index_name=ETHICS_POLICY_USER_INDEX,
        query_text=query,
        owner_id=owner_id,
        top_k=max(top_k * 2, top_k),
        es_client=es_client,
    )
    china_system_hits = _hybrid_search_index(
        index_name=ETHICS_POLICY_SYSTEM_CHINA_INDEX,
        query_text=query,
        owner_id=None,
        top_k=max(top_k, 3),
        es_client=es_client,
    )
    global_system_hits = _hybrid_search_index(
        index_name=ETHICS_POLICY_SYSTEM_GLOBAL_INDEX,
        query_text=query,
        owner_id=None,
        top_k=max(top_k, 3),
        es_client=es_client,
    )

    merged: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for row in user_hits + china_system_hits + global_system_hits:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id or doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)
        merged.append(row)
        if len(merged) >= top_k:
            break
    return merged


def search_policy_context_user(*, owner_id: str, query_text: str, top_k: int = 5, es_client: Any | None = None) -> list[dict[str, Any]]:
    _ensure_policy_indexes(es_client=es_client)
    query = (query_text or "").strip() or "ethics policy review"
    return _hybrid_search_index(
        index_name=ETHICS_POLICY_USER_INDEX,
        query_text=query,
        owner_id=owner_id,
        top_k=max(top_k, 1),
        es_client=es_client,
    )


def search_policy_context_china(*, query_text: str, top_k: int = 5, es_client: Any | None = None) -> list[dict[str, Any]]:
    _ensure_policy_indexes(es_client=es_client)
    query = (query_text or "").strip() or "ethics policy review china"
    return _hybrid_search_index(
        index_name=ETHICS_POLICY_SYSTEM_CHINA_INDEX,
        query_text=query,
        owner_id=None,
        top_k=max(top_k, 1),
        es_client=es_client,
    )


def search_policy_context_global(*, query_text: str, top_k: int = 5, es_client: Any | None = None) -> list[dict[str, Any]]:
    _ensure_policy_indexes(es_client=es_client)
    query = (query_text or "").strip() or "ethics policy review global"
    return _hybrid_search_index(
        index_name=ETHICS_POLICY_SYSTEM_GLOBAL_INDEX,
        query_text=query,
        owner_id=None,
        top_k=max(top_k, 1),
        es_client=es_client,
    )


def search_policy_context_by_angle(
    *,
    angle_id: str,
    owner_id: str,
    query_text: str,
    top_k: int = 5,
    es_client: Any | None = None,
) -> list[dict[str, Any]]:
    _ensure_policy_indexes(es_client=es_client)
    angle_key = str(angle_id or "").strip()
    route = ETHICS_POLICY_ANGLE_ROUTE.get(angle_key)
    if not route:
        raise ValueError(f"unknown policy angle: {angle_key}")
    query = (query_text or "").strip() or "ethics policy review"
    merged: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for index_name in route:
        index_top_k = max(top_k * 2, top_k) if index_name == ETHICS_POLICY_USER_INDEX else max(top_k, 3)
        rows = _hybrid_search_index(
            index_name=index_name,
            query_text=query,
            owner_id=owner_id if index_name == ETHICS_POLICY_USER_INDEX else None,
            top_k=index_top_k,
            es_client=es_client,
        )
        for row in rows:
            doc_id = str(row.get("doc_id") or "").strip()
            if not doc_id or doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            tagged_row = dict(row)
            tagged_row["policy_angle"] = angle_key
            tagged_row["retrieval_source"] = index_name
            merged.append(tagged_row)
            if len(merged) >= top_k:
                return merged
    return merged


def _get_attachment_records(doc_ids: list[str]) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT id, owner_id, name, url, content, file_properties, time_updated
        FROM "API_attachment"
        WHERE is_delete = FALSE
          AND id = ANY(ARRAY[:doc_ids]::uuid[])
        """
    )
    with get_connection_user() as conn:
        rows = conn.execute(sql, {"doc_ids": doc_ids}).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            {
                "id": str(row[0]),
                "owner_id": str(row[1]) if row[1] is not None else None,
                "name": row[2] or "",
                "url": row[3] or "",
                "content": row[4] if isinstance(row[4], dict) else {},
                "file_properties": row[5] if isinstance(row[5], dict) else {},
                "time_updated": row[6],
            }
        )
    return records


def _download_file_bytes(url: str, timeout_seconds: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        payload = response.read()
    if not payload:
        raise ValueError("downloaded attachment is empty")
    return payload


def _convert_doc_bytes_to_docx_bytes(file_bytes: bytes, file_name: str) -> bytes:
    if not file_bytes:
        raise ValueError("doc file bytes are empty")
    source_name = os.path.basename(file_name or "document.doc")
    if not source_name.lower().endswith(".doc"):
        source_name = f"{os.path.splitext(source_name)[0]}.doc"
    source_stem = os.path.splitext(source_name)[0]
    with tempfile.TemporaryDirectory(prefix="ethics_doc_convert_") as temp_dir:
        source_path = os.path.join(temp_dir, source_name)
        with open(source_path, "wb") as file_obj:
            file_obj.write(file_bytes)

        office_binary = shutil.which("soffice") or shutil.which("libreoffice")
        if not office_binary:
            raise ValueError("soffice/libreoffice is required for .doc conversion")

        convert_cmd = [
            office_binary,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            temp_dir,
            source_path,
        ]
        try:
            subprocess.run(
                convert_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_DOC_CONVERT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("doc to docx conversion timeout") from error
        except subprocess.CalledProcessError as error:
            stderr_text = (error.stderr or b"").decode("utf-8", errors="ignore").strip()
            raise ValueError(f"doc to docx conversion failed: {stderr_text or error}") from error

        target_path = os.path.join(temp_dir, f"{source_stem}.docx")
        if not os.path.exists(target_path):
            candidates = [name for name in os.listdir(temp_dir) if name.lower().endswith(".docx")]
            if not candidates:
                raise ValueError("doc to docx conversion produced no output")
            target_path = os.path.join(temp_dir, candidates[0])

        with open(target_path, "rb") as file_obj:
            converted_bytes = file_obj.read()
        if not converted_bytes:
            raise ValueError("converted docx is empty")
        return converted_bytes


async def _parse_attachment_text_with_bp(record: dict[str, Any]) -> str:
    from agent.bp.pp import fetch_context_single

    name = str(record.get("name") or "")
    url = str(record.get("url") or "")
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in {"pdf", "doc", "docx"}:
        content_obj = record.get("content") or {}
        return str(content_obj.get("content") or "")
    if not url:
        raise ValueError("attachment url is empty")
    if ext == "doc":
        source_bytes = await asyncio.to_thread(_download_file_bytes, url)
        converted_docx_bytes = await asyncio.to_thread(_convert_doc_bytes_to_docx_bytes, source_bytes, name)
        converted_name = f"{os.path.splitext(name)[0]}.docx"
        parsed_text = await asyncio.to_thread(convert_document, converted_name, converted_docx_bytes)
        parsed_text = str(parsed_text or "").strip()
        if not parsed_text:
            raise ValueError("doc to docx parse returned empty content")
        return parsed_text

    parsed_pages = await fetch_context_single(
        path=url,
        doc_name=name,
        attachment_id=record["id"],
        parse_only=True,
        detailed=2,
        mode="sql",
    )
    if isinstance(parsed_pages, list):
        parsed_text = "\n\n".join([str(x) for x in parsed_pages if x is not None]).strip()
        if not parsed_text:
            raise ValueError("bp parse returned empty content")
        return parsed_text
    if isinstance(parsed_pages, str):
        parsed_text = parsed_pages.strip()
        if not parsed_text:
            raise ValueError("bp parse returned empty content")
        return parsed_text
    raise ValueError("bp parse returned unsupported content type")


def _set_attachment_index_status(
    *,
    doc_id: str,
    status: str,
    error_message: str,
    extra_props: dict[str, Any] | None = None,
) -> None:
    select_sql = text(
        """
        SELECT file_properties
        FROM "API_attachment"
        WHERE id = CAST(:doc_id AS uuid)
        LIMIT 1
        """
    )
    update_sql = text(
        """
        UPDATE "API_attachment"
        SET file_properties = CAST(:file_properties AS jsonb),
            time_updated = NOW()
        WHERE id = CAST(:doc_id AS uuid)
        """
    )
    with get_connection_user() as conn:
        row = conn.execute(select_sql, {"doc_id": doc_id}).fetchone()
        props = row[0] if row and isinstance(row[0], dict) else {}
        if extra_props:
            props.update(extra_props)
        props["index_status"] = status
        props["index_error"] = error_message or ""
        conn.execute(
            update_sql,
            {"doc_id": doc_id, "file_properties": json.dumps(props, ensure_ascii=False)},
        )
        conn.commit()


async def index_policy_documents(owner_id: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    _ensure_policy_indexes()
    doc_ids = [str(a.get("doc_id") or "").strip() for a in attachments if str(a.get("doc_id") or "").strip()]
    records = _get_attachment_records(doc_ids)
    scope_by_doc_id = {str(a.get("doc_id")): str(a.get("scope") or "user").strip().lower() for a in attachments}
    indexed: list[str] = []
    skipped: list[str] = []
    for record in records:
        scope = scope_by_doc_id.get(record["id"], "user")
        if scope == "user" and str(record.get("owner_id") or "") != str(owner_id):
            _set_attachment_index_status(
                doc_id=record["id"],
                status=POLICY_INDEX_STATUS_FAILED,
                error_message="owner mismatch",
            )
            skipped.append(record["id"])
            continue
        _set_attachment_index_status(
            doc_id=record["id"],
            status=POLICY_INDEX_STATUS_PROCESSING,
            error_message="",
        )
        try:
            parsed_text = await _parse_attachment_text_with_bp(record)
            props = record.get("file_properties") or {}
            embedding_text = _prepare_embedding_text(parsed_text)
            embedding_task = asyncio.to_thread(get_embedding, embedding_text)
            metadata_task = _extract_policy_metadata_with_llm(
                doc_name=str(record.get("name") or ""),
                content_text=parsed_text,
            )
            content_vector, llm_meta = await asyncio.gather(embedding_task, metadata_task)
            merged_props = _merge_llm_metadata_into_props(
                current_props=props,
                llm_meta=llm_meta,
            )
            payload = {
                "doc_id": record["id"],
                "owner_id": str(owner_id) if scope == "user" else "",
                "scope": scope,
                "title": record.get("name") or "",
                "content": parsed_text,
                "content_vector": content_vector,
                "policy_type": str(merged_props.get("policy_type") or ""),
                "issuer": str(merged_props.get("issuer") or ""),
                "publication_date": str(merged_props.get("publication_date") or ""),
                "region": str(merged_props.get("region") or ""),
                "updated_at": (record.get("time_updated") or datetime.now(timezone.utc)).isoformat(),
            }
            index_name = ETHICS_POLICY_USER_INDEX
            if scope == "system":
                index_name = _get_system_index_by_region(merged_props.get("region"))
                opposite_index = (
                    ETHICS_POLICY_SYSTEM_GLOBAL_INDEX
                    if index_name == ETHICS_POLICY_SYSTEM_CHINA_INDEX
                    else ETHICS_POLICY_SYSTEM_CHINA_INDEX
                )
                try:
                    _es_client.delete(index=opposite_index, id=record["id"])
                except NotFoundError:
                    pass
                except Exception:
                    logger.warning(
                        "cleanup opposite system index failed for %s: %s",
                        record["id"],
                        traceback.format_exc(),
                    )
            _es_client.index(index=index_name, id=record["id"], document=payload)
            _set_attachment_index_status(
                doc_id=record["id"],
                status=POLICY_INDEX_STATUS_READY,
                error_message="",
                extra_props={
                    "issuer": str(merged_props.get("issuer") or ""),
                    "publication_date": str(merged_props.get("publication_date") or ""),
                    "policy_type": str(merged_props.get("policy_type") or ""),
                },
            )
            indexed.append(record["id"])
        except Exception as e:
            logger.error("index policy doc failed %s: %s", record["id"], traceback.format_exc())
            _set_attachment_index_status(
                doc_id=record["id"],
                status=POLICY_INDEX_STATUS_FAILED,
                error_message=str(e),
            )
    return {"indexed": indexed, "skipped": skipped}


async def index_system_policy_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Index local system policy records using the same indexing path as policy documents.
    Each record should include:
      - doc_id: str (required)
      - title: str (required)
      - content: str (required)
      - region: str ("china" | "global", optional; default global)
    """
    _ensure_policy_indexes()
    total = len(records or [])
    logger.info("[ethics_index_system] start total_records=%s", total)
    indexed: list[str] = []
    skipped: list[str] = []
    errors: dict[str, str] = {}
    for idx, record in enumerate(records, start=1):
        doc_id = str((record or {}).get("doc_id") or "").strip()
        title = str((record or {}).get("title") or "").strip()
        content = str((record or {}).get("content") or "").strip()
        region_raw = (record or {}).get("region")
        logger.info(
            "[ethics_index_system] processing %s/%s doc_id=%s title=%s",
            idx,
            total,
            doc_id or "<missing_doc_id>",
            title[:60],
        )
        if not doc_id or not title or not content:
            skipped.append(doc_id or "<missing_doc_id>")
            logger.info(
                "[ethics_index_system] skipped %s/%s doc_id=%s reason=missing_required_fields",
                idx,
                total,
                doc_id or "<missing_doc_id>",
            )
            continue
        try:
            embedding_text = _prepare_embedding_text(content)
            embedding_task = asyncio.to_thread(get_embedding, embedding_text)
            metadata_task = _extract_policy_metadata_with_llm(
                doc_name=title,
                content_text=content,
            )
            content_vector, llm_meta = await asyncio.gather(embedding_task, metadata_task)
            merged_props = _merge_llm_metadata_into_props(
                current_props={"region": _normalize_system_region(region_raw)},
                llm_meta=llm_meta,
            )

            payload = {
                "doc_id": doc_id,
                "owner_id": "",
                "scope": "system",
                "title": title,
                "content": content,
                "content_vector": content_vector,
                "policy_type": str(merged_props.get("policy_type") or ""),
                "issuer": str(merged_props.get("issuer") or ""),
                "publication_date": str(merged_props.get("publication_date") or ""),
                "region": _normalize_system_region(merged_props.get("region")),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            index_name = _get_system_index_by_region(payload["region"])
            opposite_index = (
                ETHICS_POLICY_SYSTEM_GLOBAL_INDEX
                if index_name == ETHICS_POLICY_SYSTEM_CHINA_INDEX
                else ETHICS_POLICY_SYSTEM_CHINA_INDEX
            )
            try:
                _es_client.delete(index=opposite_index, id=doc_id)
            except NotFoundError:
                pass
            except Exception:
                logger.warning(
                    "cleanup opposite system index failed for %s: %s",
                    doc_id,
                    traceback.format_exc(),
                )
            _es_client.index(index=index_name, id=doc_id, document=payload)
            indexed.append(doc_id)
            logger.info(
                "[ethics_index_system] indexed %s/%s doc_id=%s index=%s",
                idx,
                total,
                doc_id,
                index_name,
            )
        except Exception as e:
            logger.error("index system policy record failed %s: %s", doc_id, traceback.format_exc())
            errors[doc_id] = str(e)
            logger.info(
                "[ethics_index_system] failed %s/%s doc_id=%s error=%s",
                idx,
                total,
                doc_id or "<missing_doc_id>",
                str(e),
            )
    logger.info(
        "[ethics_index_system] done total=%s indexed=%s skipped=%s errors=%s",
        total,
        len(indexed),
        len(skipped),
        len(errors),
    )
    return {"indexed": indexed, "skipped": skipped, "errors": errors}


async def delete_policy_documents(owner_id: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Delete policy documents from ES with idempotent semantics:
    - If the document does not exist in index, treat as success.
    - For user scope, enforce owner_id isolation before deletion.
    """
    _ensure_policy_indexes()
    deleted: list[str] = []
    skipped: list[str] = []
    errors: dict[str, str] = {}

    for item in attachments:
        doc_id = str((item or {}).get("doc_id") or "").strip()
        if not doc_id:
            continue
        scope = str((item or {}).get("scope") or "user").strip().lower()
        index_names: list[str]
        if scope == "system":
            index_names = [ETHICS_POLICY_SYSTEM_CHINA_INDEX, ETHICS_POLICY_SYSTEM_GLOBAL_INDEX]
        else:
            index_names = [ETHICS_POLICY_USER_INDEX]
        try:
            if scope == "user":
                source = _es_client.get(index=ETHICS_POLICY_USER_INDEX, id=doc_id)["_source"]
                source_owner_id = str(source.get("owner_id") or "")
                if source_owner_id and source_owner_id != str(owner_id):
                    skipped.append(doc_id)
                    continue
            deleted_any = False
            for index_name in index_names:
                try:
                    _es_client.delete(index=index_name, id=doc_id)
                    deleted_any = True
                except NotFoundError:
                    continue
            deleted.append(doc_id)
            if not deleted_any:
                # Idempotent delete: already absent is still treated as success.
                pass
        except Exception as e:
            logger.error("delete policy doc failed %s: %s", doc_id, traceback.format_exc())
            errors[doc_id] = str(e)

    return {"deleted": deleted, "skipped": skipped, "errors": errors}

if __name__ == "__main__":
    result = search_policy_context(
        owner_id="1",
        query_text="本研究为一项涉及人的生命科学与医学研究，主要审查焦点在于受试者的知情同意过程、风险获益评估以及隐私保护措施是",
        top_k=5,
    )
    logger.info("%s", json.dumps(result, ensure_ascii=False, indent=4))