# -*- coding: utf-8 -*-
import logging
import threading
from typing import Any, Dict, Optional
from pymilvus import connections, Collection

from config import settings
from utils.core.singleton import Singleton

logger = logging.getLogger(__name__)


class MilvusClientSingleton(Singleton):

    _initialized: bool = False
    _init_lock = threading.Lock()  # Thread lock for concurrent control
    _max_retries: int = 3  # Maximum retry attempts

    _milvus_collections: Dict[str, Collection] = {}

    _milvus_databases: Dict[str, Any] = {
        "Pubmed": {
            "params": {
                'alias': 'Pubmed',
                'uri': settings.MILVUS_URI_DATASERVER,
                'user': settings.MILVUS_USER_DATASERVER,
                'password': settings.MILVUS_PASSWORD_DATASERVER,
                'db_name': 'Pubmed',
                'timeout': 10,
            },
            "collections": ['pubmed_hot', 'pubmed_cold']
        }
    }

    @classmethod
    def initialize(cls, retry: bool = False) -> bool:
        r"""Connect to Milvus"""
        if cls._initialized and not retry:
            return True
        
        with cls._init_lock:  # Ensure only one thread executes initialization at a time
            # Double-check pattern
            if cls._initialized and not retry:
                return True
            
            # Connect to Milvus server
            for key, meta in cls._milvus_databases.items():
                try:
                    params = meta['params']
                    
                    # Disconnect old connection if retrying
                    if retry and connections.has_connection(params['alias']):
                        connections.disconnect(params['alias'])
                    
                    connections.connect(**params)

                    ok = connections.has_connection(params['alias'])
                    if not ok:
                        raise RuntimeError("Connect with Milvus database failed.")
                    else:
                        logger.info(f"Connecting with Milvus {params['uri']} success")

                    # Ensure we bind collections to the established connection alias
                    cls._milvus_collections.update({
                        name: Collection(name, using=params['alias']) 
                        for name in meta['collections']
                    })
                    
                    cls._initialized = True
                    logger.info(f"Connected to Milvus collection: {key}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to connect to Milvus: {key} for reason: {e}")
                    cls._initialized = False
                    return False
            
            return cls._initialized

    @classmethod
    def get_collection(cls, collection: str) -> Optional[Collection]:
        # Try to get collection directly first
        coll = cls._milvus_collections.get(collection)
        if coll is not None:
            return coll
        
        # If not initialized, attempt to initialize
        if not cls._initialized:
            logger.warning("Milvus not initialized, attempting to initialize...")
            if cls.initialize():
                return cls._milvus_collections.get(collection)
            else:
                logger.error("Failed to initialize Milvus connection")
                return None
        
        # If initialized but collection not found, attempt to reconnect
        logger.warning(f"Collection '{collection}' not found, attempting reconnection...")
        retry_count = 0
        while retry_count < cls._max_retries:
            if cls.initialize(retry=True):
                coll = cls._milvus_collections.get(collection)
                if coll is not None:
                    logger.info(f"Successfully reconnected and found collection: {collection}")
                    return coll
            
            retry_count += 1
            logger.warning(f"Retry {retry_count}/{cls._max_retries} failed for collection: {collection}")
        
        logger.error(f"Failed to get collection '{collection}' after {cls._max_retries} retries")
        return None