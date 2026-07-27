import elasticsearch
import asyncio
import logging

from config import settings
from typing import Optional
from utils.core.singleton import Singleton

logger = logging.getLogger(__name__)


class ElasticsearchClientSingleton(Singleton):
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
        # Default client
        es_url = settings.NOAH_ELASTICSEARCH_URL
        es_username = settings.NOAH_ELASTICSEARCH_USERNAME
        es_password = settings.NOAH_ELASTICSEARCH_PASSWORD
        if not cls._initialized:
            cls._async_instance = elasticsearch.AsyncElasticsearch(
                hosts=es_url ,
                basic_auth=(es_username, es_password),
                max_retries=10,
                retry_on_timeout=True,
                request_timeout=30
            )
            cls._instance = elasticsearch.Elasticsearch(
                hosts=es_url ,
                basic_auth=(es_username, es_password),
                max_retries=10,
                retry_on_timeout=True,
                request_timeout=30
            )
            if cls._instance.ping():
                logger.info("Elasticsearch connection success.")
            cls._initialized = True
        else:
            pass
        return

    @classmethod
    async def cleanup(cls) -> None:
        if cls._async_instance:
            await cls._async_instance.close()
            cls._async_instance = None
        else:
            pass
        if cls._instance:
            cls._instance.close()
            cls._instance = None
        else:
            pass
        cls._initialized = False
        return

    @classmethod
    def reset(cls) -> None:
        cls.cleanup()
        cls._initialized = False
        return
