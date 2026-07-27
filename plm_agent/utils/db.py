
import time

from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import PineconeException
from pymilvus import MilvusClient, MilvusException
from elasticsearch import Elasticsearch, AsyncElasticsearch, ConnectionError as ESConnectionError

from config import api_config

import logging
logger = logging.getLogger(__name__)

class DBClientFactory():
    """
    Factory class to create clients for different databases.
    """
    @staticmethod
    def create_client(db_type, max_retries = 3, retry_delay = 2):
        if db_type == "milvus":
            return MilvusEngine(max_retries, retry_delay)
        elif db_type == "elasticsearch":
            return ESClient(max_retries, retry_delay)
        elif db_type == 'pinecone':
            return PineconeClient(max_retries, retry_delay)
        else:
            raise ValueError(f"Unsupported database type: {db_type}")


class BaseClient():
    """
    Base client class with common attributes.
    """
    def __init__(self, max_retries = 3, retry_delay = 2) -> None:
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.client = None
    
    def create_connection(self):
        raise NotImplementedError("Method create_connection must be implemented.")

class MilvusEngine(BaseClient):
    """Milvus database client implementation."""
    
    def _get_connection_config(self):
        """Return Milvus connection configuration."""
        return {
            'uri': f"http://{api_config.MILVUS_HOST}:{api_config.MILVUS_PORT}",
            'timeout': 20
        }
        
    def create_connection(self):
        """Create the connection to the Milvus server."""
        logger.info("Creating connection to Milvus server...")
        
        for attempt in range(self.max_retries):
            try:
                self.client = MilvusClient(**self._get_connection_config())
                logger.info("Successfully connected to Milvus")
                return self.client
                
            except MilvusException as error:
                logger.error(f"Connection attempt {attempt + 1}/{self.max_retries} failed: {error}")
                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to Milvus after all retries")
                    raise
                    
            except Exception as error:
                logger.error(f"Unexpected error while connecting to Milvus: {error}")
                logger.critical("Please check if SSH tunnel is required")
                raise
                
        
class ESClient(BaseClient):

    def _get_connection_config(self):
        """Return Elasticsearch connection configuration."""
        return {
            'hosts': api_config.ES_HOST,
            'basic_auth': (api_config.ES_USERNAME, api_config.ES_PASSWORD),
            'timeout': 20,
            'maxsize': 25
        }
        
    def create_connection(self):
        """Create the connection to the Elasticsearch server."""
        logger.info("Creating connection to Elasticsearch server...")
        
        for attempt in range(self.max_retries):
            try:
                self.client = Elasticsearch(**self._get_connection_config())
                
                if self.client.ping():
                    logger.info("Successfully connected to Elasticsearch")
                    return self.client
                    
            except ESConnectionError as error:
                logger.error(f"Connection attempt {attempt + 1}/{self.max_retries} failed: {error}")
                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to Elasticsearch after all retries")
                    raise
                    
            except Exception as error:
                logger.error(f"Unexpected error while connecting to Elasticsearch: {error}")
                raise
    
    def create_async_connection(self):
        """Create the connection to the Elasticsearch server."""
        logger.info("Creating connection to Elasticsearch server...")
        
        for attempt in range(self.max_retries):
            try:
                self.client = AsyncElasticsearch(**self._get_connection_config())
                return self.client
                    
            except ESConnectionError as error:
                logger.error(f"Connection attempt {attempt + 1}/{self.max_retries} failed: {error}")
                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to Elasticsearch after all retries")
                    raise
                    
            except Exception as error:
                logger.error(f"Unexpected error while connecting to Elasticsearch: {error}")
                raise        

class PineconeClient(BaseClient):
    """Pinecone vector database client implementation."""
    
    def _get_connection_config(self):
        """Return Pinecone connection configuration."""
        return {
            'api_key': api_config.PINECONE_API_KEY,
        }
        
    def create_connection(self):
        """Create the connection to the Pinecone service."""
        logger.info("Creating connection to Pinecone service...")
        
        for attempt in range(self.max_retries):
            try:
                self.client = Pinecone(**self._get_connection_config())
                logger.info("Successfully connected to Pinecone")
                return self.client
                
            except PineconeException as error:
                logger.error(f"Connection attempt {attempt + 1}/{self.max_retries} failed: {error}")
                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Failed to connect to Pinecone after all retries")
                    raise
                    
            except Exception as error:
                logger.error(f"Unexpected error while connecting to Pinecone: {error}")
                raise


# Test the connection creation    
if __name__ == "__main__":
    milvus_client = DBClientFactory.create_client("milvus")
    milvus_client.create_connection()
    
    es_client = DBClientFactory.create_client("elasticsearch")
    es_client.create_connection()
    
    print("\nAll connections created")    
    
        
        
        
    