
import os
import json
import logging
import asyncio
from typing import Any, Dict, List
from google import genai
from google.genai.types import HttpOptions
import logging

from agent.core.preset import AgentPreset
from llm.gcp_models import Gemini3Flash, Gemini31Pro
from llm.base_model import BaseLLM
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from agent.bp.pp import fetch_context_single
from utils.core.exception import UnexpectedException
from agent.human_in_loop.utils import *
from utils.utils.attachment import AttachmentManager
from config import settings
from agent.bp.db import read_bp_context, write_bp_context
from agent.bp.evaluate import evaluate_bp_json_text
from agent.knowledge.es import update_attachment_content_es, client, ES_INDEX_NAME, get_user_knowledge_embedding_fields
from pathlib import Path
from agent.iit.utils.guidelines.embedding import get_embedding

logger = logging.getLogger(__name__)


# 设置 Google Cloud 环境变量（如果需要）
gcp_key_path = "/Users/chenzichu/Desktop/NoahServer/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

# 定义 BP 解析的 JSON Schema
summary_schema = {
    "type": "OBJECT",
    "properties": {
        "summary": {
            "type": "STRING",
            "description": "文档总结"
        }
    },
    "required": [
        "summary",
    ]
}

attachment_manager: AttachmentManager = AttachmentManager()

async def batch_process_summary(files: list = []):
    if files:
        attachments = attachment_manager.fetch_attachments(files, False)
        toc_map = {}

        async def _fetch_toc(att):
            url = att.get('url', '')
            name = att.get('name', "Untitled")
            attachment_id = str(att.get('id', ''))
            
            _, toc_text = await fetch_context_single(
                url, name, attachment_id, detailed=1, include_toc=True
            )
            return name, attachment_id, toc_text

        results = await asyncio.gather(*[
            _fetch_toc(att) for att in attachments
        ])
        for doc_name, attachment_id, toc_text in results:
            toc_map[attachment_id] = {
                "doc_name": doc_name,
                "toc_text": toc_text,
            }

        async def _summarize(doc_name: str, toc_text: str) -> str:
            prompt = (
                "请基于文档名称和目录内容生成简洁摘要，只返回JSON对象，"
                "格式为 {\"summary\": \"...\"}。\n\n"
                f"文档名称: {doc_name}\n"
                f"目录内容:\n{toc_text}"
            )
            llm: BaseLLM = Gemini3Flash()
            result = await llm(
                sys_prompt="你是一个专业的文档总结助手。",
                user_prompt=prompt,
                json_mode=True,
                temperature=0,
                thinking_budget="low"
            )
            try:
                cleaned = str(result).strip().removeprefix("```json").removesuffix("```")
                data = json.loads(cleaned)
                return str(data.get("summary", "")).strip()
            except Exception:
                return str(result).strip()

        summarize_tasks = []
        for attachment_id, meta in toc_map.items():
            doc_name = meta.get("doc_name", "")
            toc_text = meta.get("toc_text", "")
            if not toc_text:
                continue
            summarize_tasks.append(
                asyncio.create_task(_summarize(doc_name, toc_text))
            )

        summaries = await asyncio.gather(*summarize_tasks) if summarize_tasks else []

        summary_index = 0
        for attachment_id, meta in toc_map.items():
            doc_name = meta.get("doc_name", "")
            toc_text = meta.get("toc_text", "")
            if not toc_text:
                continue
            summary = summaries[summary_index] if summary_index < len(summaries) else ""
            summary_index += 1
            content = {}
            if summary:
                content["summary"] = summary
                await update_attachment_content(attachment_id, content)
            content.update({
                "doc_name_embedding": get_embedding(doc_name) if doc_name else None,
                "toc_text_embedding": get_embedding(toc_text) if toc_text else None,
                "summary_embedding": get_embedding(summary) if summary else None,
            })
            update_attachment_content_es(attachment_id, content)
        return toc_map


async def search_and_selection(user_query: str, parent_id: str = None, user_email: str = None, force_empty: bool = False) -> List[str]:
    if not user_query or not user_query.strip():
        return []

    query_text = user_query.strip()
    parent_id_value = (parent_id or "").strip()
    if not parent_id_value:
        parent_id_value = None
    query_vector = await asyncio.to_thread(get_embedding, query_text)

    async def _search_by_field(field: str, size: int = 10) -> List[Dict[str, Any]]:
        def _do_search() -> List[Dict[str, Any]]:
            max_retries = 3
            base_delay = 1
            for attempt in range(max_retries):
                try:
                    knn_body: Dict[str, Any] = {
                        "field": field,
                        "query_vector": query_vector,
                        "k": size,
                        "num_candidates": max(size * 2, 10),
                    }
                    filter_conditions = [{"exists": {"field": "summary"}}]
                    if parent_id_value:
                        filter_conditions.append({
                            "bool": {
                                "should": [
                                    {"term": {"parent_id": parent_id_value}},
                                    {"term": {"parent_id.keyword": parent_id_value}}
                                ],
                                "minimum_should_match": 1
                            }
                        })

                    must_not_conditions: List[Dict[str, Any]] = [
                        {"term": {"type.keyword": "folder"}},
                    ]
                    if user_email:
                        # Blacklist: exclude documents where user_email appears in blocked_users
                        must_not_conditions.append({"term": {"blocked_users": user_email}})
                        # Whitelist: include only if allowed_users is empty/missing (no restriction)
                        # OR explicitly contains user_email.
                        # Blacklist takes priority because must_not is evaluated independently.
                        filter_conditions.append({
                            "bool": {
                                "should": [
                                    {"bool": {"must_not": {"exists": {"field": "allowed_users"}}}},
                                    {"term": {"allowed_users": user_email}},
                                ],
                                "minimum_should_match": 1,
                            }
                        })

                    filter_dict: Dict[str, Any] = {
                        "bool": {
                            "must": filter_conditions
                        }
                    }
                    if must_not_conditions:
                        filter_dict["bool"]["must_not"] = must_not_conditions

                    knn_body["filter"] = filter_dict
                    body = {
                        "knn": knn_body,
                        "size": size,
                    }
                    resp = client.search(index=ES_INDEX_NAME, body=body)
                    hits = resp.get("hits", {}).get("hits", [])
                    return hits
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.exception("ES search failed for field %s after %d attempts", field, max_retries)
                        return []
                    import time
                    import random
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("ES search failed for field %s, retrying in %.2fs. Error: %s", field, sleep_time, str(e))
                    time.sleep(sleep_time)
            return []

        return await asyncio.to_thread(_do_search)

    embedding_fields = get_user_knowledge_embedding_fields()
    doc_name_hits, toc_text_hits, summary_hits = await asyncio.gather(
        _search_by_field(embedding_fields["doc_name"]),
        _search_by_field(embedding_fields["toc_text"]),
        _search_by_field(embedding_fields["summary"]),
    )

    merged: Dict[str, Dict[str, Any]] = {}
    for hits in (doc_name_hits, toc_text_hits, summary_hits):
        for hit in hits:
            doc_id = str(hit.get("_id", ""))
            if not doc_id or doc_id in merged:
                continue
            source = hit.get("_source", {}) or {}
            content = source.get("content") or {}
            if not isinstance(content, dict):
                content = {"content": content}
            if not content:
                content = {
                    "summary": source.get("summary") or "",
                    "toc_text": source.get("toc_text") or "",
                }
            merged[doc_id] = {
                "id": doc_id,
                "name": source.get("name") or source.get("filename") or "",
                "summary": content.get("summary") or "",
                "toc_text": content.get("toc_text") or "",
            }
    logger.info(f"searched results: {merged}")

    candidates = list(merged.values())
    if not candidates:
        return []

    force_empty_prompt = ""
    if force_empty:
        force_empty_prompt = "如果用户的问题是关于整个知识库的概述，总结，归纳，没有指定特定的主题或者标准，请返回空数组。\n"

    prompt = (
        "你将从候选文档中选择与查询最相关的最多5个文档。\n"
        f"{force_empty_prompt}\n"
        "只返回JSON对象，格式为 {\"ids\": [\"id1\", \"id2\"]}。\n\n"
        f"查询: {query_text}\n\n"
        "候选文档:\n"
    )

    for idx, item in enumerate(candidates, 1):
        prompt += (
            f"{idx}. id={item['id']}\n"
            f"   name={item.get('name','')}\n"
            f"   summary={item.get('summary','')}\n"
            f"   table of contents={item.get('toc_text','')}\n"
        )

    llm: BaseLLM = Gemini3Flash()
    result = await llm(
        sys_prompt="你是一个严谨的检索筛选助手。",
        user_prompt=prompt,
        json_mode=True,
        temperature=0,
        thinking_budget="low"
    )
    logger.info(f"selected result: {result}")

    try:
        cleaned = str(result).strip().removeprefix("```json").removesuffix("```")
        data = json.loads(cleaned)
        ids = data.get("ids", []) if isinstance(data, dict) else []
        if isinstance(ids, list):
            normalized = [str(i) for i in ids if str(i) in merged]
            return normalized[:10]
    except Exception:
        logger.exception("LLM selection parse failed")

    return [item["id"] for item in candidates[:10]]


async def search_and_selection_docs(
    user_query: str,
    parent_id: str = None,
    user_email: str = None,
) -> List[Dict[str, str]]:
    """
    返回筛选后的文档列表，每个文档包含:
    - id
    - name
    - text   (当前取 toc_text)
    - summary
    """
    if not user_query or not user_query.strip():
        return []

    query_text = user_query.strip()
    parent_id_value = (parent_id or "").strip()
    if not parent_id_value:
        parent_id_value = None

    query_vector = await asyncio.to_thread(get_embedding, query_text)

    async def _search_by_field(field: str, size: int = 10) -> List[Dict[str, Any]]:
        def _do_search() -> List[Dict[str, Any]]:
            max_retries = 3
            base_delay = 1
            for attempt in range(max_retries):
                try:
                    knn_body: Dict[str, Any] = {
                        "field": field,
                        "query_vector": query_vector,
                        "k": size,
                        "num_candidates": max(size * 2, 10),
                    }

                    filter_conditions = [{"exists": {"field": "summary"}}]
                    if parent_id_value:
                        filter_conditions.append({
                            "bool": {
                                "should": [
                                    {"term": {"parent_id": parent_id_value}},
                                    {"term": {"parent_id.keyword": parent_id_value}},
                                ],
                                "minimum_should_match": 1,
                            }
                        })

                    must_not_conditions: List[Dict[str, Any]] = [
                        {"term": {"type.keyword": "folder"}},
                    ]
                    if user_email:
                        must_not_conditions.append({"term": {"blocked_users": user_email}})
                        filter_conditions.append({
                            "bool": {
                                "should": [
                                    {"bool": {"must_not": {"exists": {"field": "allowed_users"}}}},
                                    {"term": {"allowed_users": user_email}},
                                ],
                                "minimum_should_match": 1,
                            }
                        })

                    filter_dict: Dict[str, Any] = {"bool": {"must": filter_conditions}}
                    if must_not_conditions:
                        filter_dict["bool"]["must_not"] = must_not_conditions

                    knn_body["filter"] = filter_dict
                    body = {"knn": knn_body, "size": size}

                    resp = client.search(index=ES_INDEX_NAME, body=body)
                    return resp.get("hits", {}).get("hits", [])
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.exception("ES search failed for field %s after %d attempts", field, max_retries)
                        return []
                    import random
                    import time
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("ES search failed for field %s, retrying in %.2fs. Error: %s", field, sleep_time, str(e))
                    time.sleep(sleep_time)
            return []

        return await asyncio.to_thread(_do_search)

    embedding_fields = get_user_knowledge_embedding_fields()
    doc_name_hits, toc_text_hits, summary_hits = await asyncio.gather(
        _search_by_field(embedding_fields["doc_name"]),
        _search_by_field(embedding_fields["toc_text"]),
        _search_by_field(embedding_fields["summary"]),
    )

    # 候选去重 + 组装基础信息
    merged: Dict[str, Dict[str, str]] = {}
    for hits in (doc_name_hits, toc_text_hits, summary_hits):
        for hit in hits:
            doc_id = str(hit.get("_id", ""))
            if not doc_id or doc_id in merged:
                continue

            source = hit.get("_source", {}) or {}
            content = source.get("content") or {}
            if not isinstance(content, dict):
                content = {"content": content}
            if not content:
                content = {
                    "summary": source.get("summary") or "",
                    "toc_text": source.get("toc_text") or "",
                }

            summary = str(content.get("summary") or "")
            toc_text = str(content.get("toc_text") or "")

            merged[doc_id] = {
                "id": doc_id,
                "name": str(source.get("name") or source.get("filename") or ""),
                "text": str(source.get("content")),        # 你要的 text
                "summary": str(source.get("summary")),
            }

    candidates = list(merged.values())
    if not candidates:
        return []

    # LLM 选择最多 5 个
    prompt = (
        "你将从候选文档中选择与查询最相关的最多5个文档。\n"
        "只返回JSON对象，格式为 {\"ids\": [\"id1\", \"id2\"]}。\n\n"
        f"查询: {query_text}\n\n"
        "候选文档:\n"
    )
    for idx, item in enumerate(candidates, 1):
        prompt += (
            f"{idx}. id={item['id']}\n"
            f"   name={item.get('name', '')}\n"
            f"   summary={item.get('summary', '')}\n"
            f"   text={item.get('text', '')}\n"
        )

    llm: BaseLLM = Gemini3Flash()
    result = await llm(
        sys_prompt="你是一个严谨的检索筛选助手。",
        user_prompt=prompt,
        json_mode=True,
        temperature=0,
        thinking_budget="low",
    )

    try:
        cleaned = str(result).strip().removeprefix("").removesuffix("```")
        data = json.loads(cleaned)
        ids = data.get("ids", []) if isinstance(data, dict) else []
        if isinstance(ids, list):
            ordered_docs = [merged[str(i)] for i in ids if str(i) in merged]
            return ordered_docs[:5]
    except Exception:
        logger.exception("LLM selection parse failed")

    # 兜底：按候选顺序返回前5个
    return candidates[:5]


async def search_and_context_detail_map(
    user_query: str,
    parent_id: str = None,
    user_email: str = None,
    detailed: int = 1,
) -> Dict[str, Dict[str, str]]:
    if not user_query or not user_query.strip():
        return {}

    if parent_id == "root":
        parent_id = None

    file_ids = await search_and_selection(
        user_query=user_query,
        parent_id=parent_id,
        user_email=user_email,
    )
    if not file_ids:
        return {}

    attachments = attachment_manager.fetch_attachments(file_ids, False)
    if not attachments:
        return {}

    async def _fetch_attachment_context(att):
        url = att.get("url", "")
        name = att.get("name", "Untitled")
        attachment_id = str(att.get("id", ""))

        context_text = await fetch_context_single(
            url,
            name,
            attachment_id,
            query=user_query,
            detailed=detailed,
        )
        return attachment_id, name, context_text

    results = await asyncio.gather(*[
        _fetch_attachment_context(att) for att in attachments
    ])

    context_map: Dict[str, Dict[str, str]] = {}
    for attachment_id, name, context_text in results:
        context_map[str(attachment_id)] = {
            "name": name or "",
            "text": context_text or "",
        }

    return context_map


if __name__ == "__main__":
    result = asyncio.run(search_and_selection("Which file is my IIT? help me find it and summarize it"))
    logger.info(f"result: {result}")