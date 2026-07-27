import httpx
import asyncio
import logging
import random

from typing import List
from urllib.parse import urlparse

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton
from utils.web_search.base_search import BaseSearch, global_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# doc
# https://developers.google.com/custom-search/v1/overview?hl=zh-cn


class GoogleProgrammableSearch(BaseSearch):

    def __init__(
        self,
        api_key: str,
        cx: str,
        region: str = '', # us
        top_k: int = 10,
        **kwargs):

        self.base_url = api_config.GOOGLE_PROGRAMMABLE_SEARCH_URL
        self.api_key = api_key.split(',')
        self.cx = cx
        self.region = region
        self.top_k = top_k
        self.max_request_num = 10
        self.timeout = httpx.Timeout(25.0)
        self.proxy = kwargs.get('proxy')
        super().__init__(top_k, [])

    async def _call_api(
        self,
        params: dict):

        try:
            # Since Google programmable search only support fetch 10 results at one time, so we have to split the top_k into parallel tasks.
            client = HttpxClientSingleton.get_asynclient()
            
            # Calculate how many parallel requests we need
            num_requests = (self.top_k + self.max_request_num - 1) // self.max_request_num
            
            # Create tasks for parallel requests
            tasks = []
            for i in range(num_requests):
                start_index = i * self.max_request_num + 1
                request_params = params.copy()
                request_params['start'] = start_index
                request_params['num'] = min(self.max_request_num, self.top_k - i * self.max_request_num)
                
                task = self._make_single_request(client, request_params)
                tasks.append(task)
            
            # Execute all requests in parallel
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combine results from all responses
            all_items = []
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    logger.warning(f"Request {i} failed: {response}")
                    continue
                if response and 'items' in response:
                    all_items.extend(response['items'])
            
            return {"items": all_items}
        except Exception as e:
            logger.error(f"Error in _call_api: {e}")
            raise

    async def _make_single_request(self, client, params):
        """Make a single API request to Google Custom Search"""
        try:
            response = await client.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Single request failed: {e}")
            raise

    @global_cache
    async def search(self, query: str, max_retry: int = 3) -> dict:
        """Search using Google Custom Search API"""
        for attempt in range(max_retry):
            try:
                params = {
                    'key': random.choice(self.api_key),
                    'cx': self.cx,  # Custom search engine ID
                    'q': query,
                    'num': self.top_k,
                    'start': 1,
                    #'lr': 'lang_en'  # Language restriction
                }
                if self.region:
                    params['gl'] = self.region
                
                response = await self._call_api(params)
                logger.info(f"[Google Programmable search] query: {query}, count: {len(response.get('items', []))}")
                return self._parse_response(response)
                
            except Exception as e:
                logger.warning(f'Retry {attempt + 1}/{max_retry} due to error: {e}')
                if attempt < max_retry - 1:
                    await asyncio.sleep(random.randint(2, 5))
                else:
                    raise Exception(f'Failed to get search results from Google Custom Search after {max_retry} retries: {e}')

    def _parse_response(self, response: dict) -> dict:
        """Parse Google Custom Search API response"""
        raw_results = []
        
        if 'items' not in response:
            logger.warning("No items found in Google Custom Search response")
            return {}
        
        for item in response['items']:
            url = item.get('link', '')
            snippet = item.get('snippet', '')
            title = item.get('title', '')
            site_name = item.get('displayLink', '')
            
            raw_results.append((url, snippet, title, site_name))
        
        return self._filter_results(raw_results)


