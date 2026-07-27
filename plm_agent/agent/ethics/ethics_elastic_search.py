import logging
from typing import Optional

import elasticsearch

from config import settings
from utils.core.singleton import Singleton

logger = logging.getLogger(__name__)


def _pick(value: Optional[str], fallback: Optional[str]) -> Optional[str]:
    resolved = str(value or "").strip()
    if resolved:
        return resolved
    fallback_resolved = str(fallback or "").strip()
    return fallback_resolved or None


class EthicsElasticsearchClientSingleton(Singleton):
    _async_instance: Optional[elasticsearch.AsyncElasticsearch] = None
    _instance: Optional[elasticsearch.Elasticsearch] = None
    _initialized: bool = False

    @classmethod
    def get_client(cls) -> elasticsearch.Elasticsearch:
        if cls._instance is None:
            cls.initialize()
        return cls._instance

    @classmethod
    def get_asyncclient(cls) -> elasticsearch.AsyncElasticsearch:
        if cls._async_instance is None:
            cls.initialize()
        return cls._async_instance

    @classmethod
    def initialize(cls) -> None:
        if cls._initialized:
            return

        es_url = _pick(getattr(settings, "ETHICS_ELASTICSEARCH_URL", None), None)
        es_username = _pick(getattr(settings, "ETHICS_ES_USERNAME", None), None)
        es_password = _pick(getattr(settings, "ETHICS_ES_PASSWARD", None), None)
        print(
            f"[ethics_es_init] ETHICS_ELASTICSEARCH_URL={es_url}, "
            f"ETHICS_ES_USERNAME={es_username}, ETHICS_ES_PASSWARD={es_password}"
        )

        if not es_url:
            raise ValueError("Ethics ES initialization failed: missing elasticsearch url")
        if not es_username or not es_password:
            raise ValueError("Ethics ES initialization failed: missing username/password")

        cls._async_instance = elasticsearch.AsyncElasticsearch(
            hosts=es_url,
            basic_auth=(es_username, es_password),
            max_retries=10,
            retry_on_timeout=True,
            request_timeout=30,
        )
        cls._instance = elasticsearch.Elasticsearch(
            hosts=es_url,
            basic_auth=(es_username, es_password),
            max_retries=10,
            retry_on_timeout=True,
            request_timeout=30,
        )
        if cls._instance.ping():
            logger.info("Ethics Elasticsearch connection success.")
        cls._initialized = True

    @classmethod
    async def cleanup(cls) -> None:
        if cls._async_instance:
            await cls._async_instance.close()
            cls._async_instance = None
        if cls._instance:
            cls._instance.close()
            cls._instance = None
        cls._initialized = False
