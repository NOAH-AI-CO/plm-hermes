import httpx
import asyncio
import logging
import random
import requests
import json
from typing import List

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton
from utils.web_search.base_search import BaseSearch, global_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BaiduQianfanSearch(BaseSearch):

    def __init__(
        self,
        api_key: str,
        edition: str = 'standard',  # Baidu Qianfan edition
        search_recency_filter: str = None,  # e.g., 'week', 'month', 'year'
        top_k: int = 10,
        black_list: list[str] = [],
        **kwargs):

        self.base_url = "https://qianfan.baidubce.com/v2/ai_search/web_search"
        self.api_key = api_key
        self.edition = edition
        self.search_recency_filter = search_recency_filter
        self.top_k = top_k
        self.timeout = httpx.Timeout(
            5.0,
            read=10.0,     # Read timeout
        )
        if len(black_list) == 0:
            black_list = [
                'enoN',
                'youtube.com',
                'bilibili.com',
                'researchgate.net',
            ]
        self.proxy = kwargs.get('proxy')
        super().__init__(top_k, black_list)
        

    async def _call_api(
        self,
        query: str,
        type: str = 'search'):

        # Baidu Qianfan API payload format
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "edition": self.edition,
            "search_source": "baidu_search_v2"
        }
        
        # Add optional search recency filter
        if self.search_recency_filter:
            payload['search_recency_filter'] = self.search_recency_filter

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

        url = self.base_url

        try:
            client = HttpxClientSingleton.get_asynclient()
            # Convert payload to JSON string with ensure_ascii=False and encode to UTF-8
            payload_str = json.dumps(payload, ensure_ascii=False)
            response = await client.post(
                url,
                content=payload_str.encode('utf-8'),
                headers=headers,
                timeout=self.timeout,
                auth=None,
            )
            response.raise_for_status()
            response.encoding = 'utf-8'
            return response.json()
                
        except Exception as e:
            logger.error(f"Baidu Qianfan api request {type(e).__name__}: {e}")
            raise

    @global_cache
    async def search(
        self,
        query: str,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                response = await self._call_api(query=query, type='search')
                return response
                return self._parse_web_search_response(response)
            except Exception as e:
                logging.warning(f"[Baidu Qianfan] Retry {attempt + 1}/{max_retry} due to error:", e)
                await asyncio.sleep(random.randint(1, 3))



async def main():
    # Initialize BaiduQianfanSearch with API key and configuration
    search = BaiduQianfanSearch(
        api_key=api_config.BAIDU_QIANFAN_API_KEY,
        edition='standard',
        search_recency_filter='week',
        top_k=10
    )
    
    # Use the search method
    results = await search.search("今天热点新闻")
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    asyncio.run(main())