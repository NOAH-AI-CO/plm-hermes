import time
import random
import asyncio

from Bio import Entrez
from functools import wraps
from cachetools import TTLCache

from config import api_config

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_global_content_cache = TTLCache(maxsize=1000, ttl=60*60*24)

def query_global_cache(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        query = kwargs.get('query')
        top_k = kwargs.get('top_k')
        cache_key = f"{query}-{top_k}"
        if cache_key in _global_content_cache:
            return _global_content_cache[cache_key]
        
        result = await func(*args, **kwargs)
        _global_content_cache[cache_key] = result
        return result
    return wrapper


class PubMedSearch:

    def __init__(self):
        self.emails = api_config.PUBMED_EMAIL.split(',')
        self.api_keys = api_config.PUBMED_API_KEY.split(',')

    def _init_entrez(self):
        index = random.randint(0, len(self.emails) - 1)
        Entrez.email = self.emails[index]
        Entrez.api_key = self.api_keys[index]
        return Entrez

    @query_global_cache
    async def esearch(self, query: str, db: str = 'pubmed', retstart: int = 0, max_retry: int = 3, top_k: int = 20):
        for attempt in range(max_retry):
            try:
                entrez = self._init_entrez()
                search_handle = entrez.esearch(db=db,
                        term=query,
                        retstart=retstart,
                        retmax=top_k,
                        idtype="acc")
                search_record = entrez.read(search_handle)
                search_handle.close()

                if search_record is None or len(search_record['IdList']) == 0:
                    return []
                
                ids = ",".join(search_record['IdList'])
                summary_handle = entrez.esummary(db=db,
                                 id=ids)
                summary_record = entrez.read(summary_handle)
                summary_handle.close()

                return summary_record
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f"[Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))
        raise Exception(
            'Failed to get pubmed esearch results after retires.'
        )


    async def efetch(self, ids: str, db: str = 'pubmed', max_retry: int = 3):
        for attempt in range(max_retry):
            try:
                entrez = self._init_entrez()
                fetch_handle = entrez.efetch(id=ids,
                                             db=db,
                                             rettype="abstract",
                                             retmode="text")
                abstracts = ""
                for line in fetch_handle.readlines():
                    abstracts += line
                fetch_handle.close()

                return abstracts
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f"[Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))
        raise Exception(
            'Failed to get pubmed efetch results after retires.'
        )