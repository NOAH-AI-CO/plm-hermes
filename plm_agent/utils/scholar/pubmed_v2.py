import time
import random
import re
import asyncio
import aiohttp
from typing import Optional, List, Dict, Any

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


class PubMedSearchV2:

    def __init__(self):
        self.emails = api_config.PUBMED_EMAIL.split(',')
        self.api_keys = api_config.PUBMED_API_KEY.split(',')
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _init_entrez(self):
        index = random.randint(0, len(self.emails) - 1)
        return {
            'email': self.emails[index],
            'api_key': self.api_keys[index]
        }

    @query_global_cache
    async def esearch(self, query: str, db: str = 'pubmed', retstart: int = 0, max_retry: int = 3, top_k: int = 20):
        for attempt in range(max_retry):
            try:
                entrez = self._init_entrez()
                session = await self._get_session()
                
                # First get the IDs
                params = {
                    'db': db,
                    'term': query,
                    'retstart': retstart,
                    'retmax': top_k,
                    'idtype': 'acc',
                    'retmode': 'json',
                    'email': entrez['email'],
                    'api_key': entrez['api_key']
                }
                
                async with session.get(f"{self.base_url}/esearch.fcgi", params=params) as response:
                    search_record = await response.json()
                
                if not search_record.get('esearchresult', {}).get('idlist'):
                    return []
                
                # Then get the summaries
                ids = ",".join(search_record['esearchresult']['idlist'])
                params = {
                    'db': db,
                    'id': ids,
                    'retmode': 'json',
                    'email': entrez['email'],
                    'api_key': entrez['api_key']
                }
                
                async with session.get(f"{self.base_url}/esummary.fcgi", params=params) as response:
                    summary_record = await response.json()
                                
                return summary_record.get('result', {})

            except Exception as e:
                logging.exception(str(e))
                logger.warning(f"[Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))
        raise Exception('Failed to get pubmed esearch results after retries.')

    async def efetch(self, ids: str, db: str = 'pubmed', max_retry: int = 3):
        for attempt in range(max_retry):
            try:
                entrez = self._init_entrez()
                session = await self._get_session()
                
                params = {
                    'db': db,
                    'id': ids,
                    'rettype': 'abstract',
                    'retmode': 'text',
                    'email': entrez['email'],
                    'api_key': entrez['api_key']
                }
                
                async with session.get(f"{self.base_url}/efetch.fcgi", params=params) as response:
                    abstracts = await response.text()
                    return abstracts

            except Exception as e:
                logging.exception(str(e))
                logger.warning(f"[Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))
        raise Exception('Failed to get pubmed efetch results after retries.')

    async def fetch_by_ids(self, ids, db: str = 'pubmed', max_retry: int = 3):
        """
        通过 PMID 列表获取文章摘要，返回格式与 esearch 一致
        
        :param ids: PMID 列表或逗号分隔的字符串，如 ["17573961", "23766347"] 或 "17573961,23766347"
        :param db: 数据库，默认 'pubmed'
        :param max_retry: 最大重试次数
        :return: 字典格式，key 是 id，value 是摘要信息（与 esearch 返回格式一致）
        """
        # 统一转换为字符串格式
        if isinstance(ids, list):
            ids_str = ",".join(str(id) for id in ids)
        elif not isinstance(ids, str):
            ids_str = str(ids)
        else:
            ids_str = ids
        
        for attempt in range(max_retry):
            try:
                entrez = self._init_entrez()
                session = await self._get_session()
                
                # 使用 esummary 获取摘要（与 esearch 内部逻辑一致）
                params = {
                    'db': db,
                    'id': ids_str,
                    'retmode': 'json',
                    'email': entrez['email'],
                    'api_key': entrez['api_key']
                }
                
                async with session.get(f"{self.base_url}/esummary.fcgi", params=params) as response:
                    summary_record = await response.json()
                                
                return summary_record.get('result', {})
                
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f"[Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))
        raise Exception('Failed to get pubmed fetch_by_ids results after retries.')

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
