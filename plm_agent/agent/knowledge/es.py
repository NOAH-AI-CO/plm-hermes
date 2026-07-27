import logging
import re
import traceback
from typing import Any, Dict, Iterable, List, Tuple, Union

from elasticsearch import Elasticsearch, NotFoundError

from config import api_config

_user_knowledge_es_url = getattr(api_config, "USER_KNOWLEDGE_ES_URL", None)
if _user_knowledge_es_url is None:
	_user_knowledge_es_url = api_config.ES_HOST

_user_knowledge_es_user = getattr(api_config, "USER_KNOWLEDGE_ES_USER", None)
if _user_knowledge_es_user is None:
	_user_knowledge_es_user = api_config.ES_USERNAME

_user_knowledge_es_password = getattr(api_config, "USER_KNOWLEDGE_ES_PASSWORD", None)
if _user_knowledge_es_password is None:
	_user_knowledge_es_password = api_config.ES_PASSWORD

client = Elasticsearch(
	hosts=_user_knowledge_es_url,
	basic_auth=(_user_knowledge_es_user, _user_knowledge_es_password),
)


logger = logging.getLogger(__name__)

ES_INDEX_NAME = "user_knowledge"

_CONTENT_OBJECT_CACHE: Union[bool, None] = None

def _content_is_object() -> bool:
	global _CONTENT_OBJECT_CACHE
	if _CONTENT_OBJECT_CACHE is not None:
		return _CONTENT_OBJECT_CACHE
	try:
		mapping = client.indices.get_mapping(index=ES_INDEX_NAME)
		index_mapping = (mapping or {}).get(ES_INDEX_NAME, {}).get("mappings", {})
		properties = index_mapping.get("properties", {}) if isinstance(index_mapping, dict) else {}
		content_mapping = properties.get("content")
		if not content_mapping:
			_CONTENT_OBJECT_CACHE = False
			return False
		if isinstance(content_mapping, dict):
			content_type = content_mapping.get("type")
			if content_type and content_type != "object":
				_CONTENT_OBJECT_CACHE = False
				return False
			if "properties" in content_mapping:
				_CONTENT_OBJECT_CACHE = True
				return True
		_CONTENT_OBJECT_CACHE = True
		return True
	except Exception:
		logger.exception("error checking content mapping type")
		_CONTENT_OBJECT_CACHE = True
		return True


def get_user_knowledge_embedding_fields() -> Dict[str, str]:
	return {
		"doc_name": "doc_name_embedding",
		"toc_text": "toc_text_embedding",
		"summary": "summary_embedding",
	}

def _ensure_user_knowledge_index() -> None:
	try:
		mappings = {
			"properties": {
				"doc_name_embedding": {
					"type": "dense_vector",
					"dims": 1024,
					"index": True,
					"similarity": "cosine",
				},
				"toc_text_embedding": {
					"type": "dense_vector",
					"dims": 1024,
					"index": True,
					"similarity": "cosine",
				},
				"summary_embedding": {
					"type": "dense_vector",
					"dims": 1024,
					"index": True,
					"similarity": "cosine",
				},
				"summary": {"type": "text"},
				"toc_text": {"type": "text"},
			},
		}

		if not client.indices.exists(index=ES_INDEX_NAME):
			client.indices.create(index=ES_INDEX_NAME, mappings=mappings)
			return

		client.indices.put_mapping(index=ES_INDEX_NAME, properties=mappings["properties"])
	except Exception:
		logger.exception("error ensuring Elasticsearch index mapping")


_ensure_user_knowledge_index()

def _sanitize_for_es(value: Any) -> Any:
	if isinstance(value, str):
		return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
	if isinstance(value, list):
		return [_sanitize_for_es(item) for item in value]
	if isinstance(value, tuple):
		return tuple(_sanitize_for_es(item) for item in value)
	if isinstance(value, dict):
		sanitized: Dict[Any, Any] = {}
		for key, val in value.items():
			safe_key = _sanitize_for_es(key) if isinstance(key, str) else key
			sanitized[safe_key] = _sanitize_for_es(val)
		return sanitized
	return value


def _extract_attachment_fields(source: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
	name = source.get("name") or source.get("filename") or ""
	url = source.get("url") or ""
	content = source.get("content")
	if content is None:
		content = source
	elif not isinstance(content, dict):
		content = {"content": content}
	return name, url, content


def get_attachments_es(files: Iterable[str]) -> Union[List[Tuple[str, str, Dict[str, Any]]], Dict]:
	try:
		file_ids = list(files)
		if not file_ids:
			return []

		resp = client.mget(index=ES_INDEX_NAME, ids=file_ids)
		docs = resp.get("docs", [])
		if not docs:
			raise Exception("no attachments found in Elasticsearch")

		results: List[Tuple[str, str, Dict[str, Any]]] = []
		for doc in docs:
			if not doc.get("found"):
				continue
			source = doc.get("_source", {})
			results.append(_extract_attachment_fields(source))

		if not results:
			raise Exception("no attachments found in Elasticsearch")

		return results
	except Exception:
		traceback.print_exc()
		logger.exception("error getting attachment content from Elasticsearch")
		return {}


def get_attachment_content_es(attachment_id: str) -> Dict[str, Any]:
	try:
		resp = client.get(index=ES_INDEX_NAME, id=attachment_id)
		source = resp.get("_source", {})
		content = source.get("content")
		if content is None:
			return source
		if not isinstance(content, dict):
			return {"content": content}
		return content
	except NotFoundError:
		logger.info(f"Attachment with ID {attachment_id} not found in Elasticsearch")
		return {}
	except Exception:
		traceback.print_exc()
		logger.exception("error getting attachment content from Elasticsearch")
		return {}


def update_attachment_content_es(attachment_id: str, content: Dict[str, Any]) -> Dict:
	try:
		sanitized_content = _sanitize_for_es(content)
		existing_content: Dict[str, Any] = {}

		try:
			resp = client.get(index=ES_INDEX_NAME, id=attachment_id)
			source = resp.get("_source", {})
			existing_content = source.get("content") or {}
			if not isinstance(existing_content, dict):
				existing_content = {"content": existing_content}
			if not existing_content and isinstance(source, dict):
				for key in (
					"doc_name_embedding",
					"toc_text_embedding",
					"summary_embedding",
					"summary",
					"toc_text",
				):
					if key in source:
						existing_content[key] = source.get(key)
		except NotFoundError:
			existing_content = {}

		merged: Dict[str, Any]
		if isinstance(sanitized_content, dict):
			merged = {**existing_content, **sanitized_content}
		else:
			merged = {"content": sanitized_content}

		max_retries = 3
		base_delay = 1
		for attempt in range(max_retries):
			try:
				if _content_is_object():
					client.update(
						index=ES_INDEX_NAME,
						id=attachment_id,
						doc={"content": merged},
						doc_as_upsert=True,
					)
				else:
					client.update(
						index=ES_INDEX_NAME,
						id=attachment_id,
						doc=merged,
						doc_as_upsert=True,
					)
				return {}
			except Exception as e:
				if attempt == max_retries - 1:
					raise e
				import time
				import random
				sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 1)
				logger.warning("ES update failed for attachment %s, retrying in %.2fs. Error: %s", attachment_id, sleep_time, str(e))
				time.sleep(sleep_time)
		return {}
	except Exception:
		traceback.print_exc()
		logger.exception("error updating attachment content in Elasticsearch")
		return {}
