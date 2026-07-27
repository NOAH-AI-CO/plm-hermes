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


# doc reference https://serpapi.com/

class GoogleSerpapiSearch(BaseSearch):

    def __init__(
        self,
        api_key: str,
        region: str = 'us', # default is global or united states, so far we only support jp, cn,
        top_k: int = 10,
        black_list: list[str] = [],
        **kwargs):

        self.base_url = api_config.GOOGLE_SERPAPI_URL
        self.api_key = api_key
        self.region = region
        self.top_k = top_k
        self.timeout = httpx.Timeout(
            20.0,
            read=20.0,     # Read timeout
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
        params: dict):

        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"API请求失败: {type(e).__name__}: {e}")
            raise    
    
    @global_cache
    async def patents(
        self,
        query: str,
        country: List[str] = [],
        before: str = '',
        after: str = '',
        language: List[str] = [],
        page: int = 1,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                params = {
                    "engine": "google_patents",
                    "q": query,
                    "api_key": self.api_key,
                    "num": self.top_k,
                }
                if country:
                    params['country'] = country
                if before:
                    params['before'] = before
                if after:
                    params['after'] = after
                if language:
                    params['language'] = language
                if page != 1:
                    params['page'] = page
                response = await self._call_api(params=params)
                return self._parse_patents_response(response)
            except Exception as e:
                logging.warning(f"[Google Serpapi] Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))

    
    def _parse_patents_response(
        self,
        response: dict
    ) -> dict:
        raw_results = []

        for item in response.get("organic_results", []):
            patent_id = item.get("patent_id", "")
            url = item.get("patent_link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            attribute_key = ["priority_date", "filing_date", "publication_date", "inventor", "assignee", "publication_number", "language"]
            for key in attribute_key:
                if key in item:
                    snippet += f"{key}: {item[key]}, "

            raw_results.append({
                 "url": url,
                 "summ": snippet,
                 "title": title,
                 "site_name": "google.com",
                 "patent_id": patent_id
            })

        logger.info(f'[GoogleSerping] Patent search result {len(raw_results)}')

        return {index: result for index, result in enumerate(raw_results)}  
 

async def main():

    google_searcher = GoogleSerpapiSearch(
        api_key="4dec3b0e9c3316e1dacd89484f43507b6894429a7bb969bc6a2040f44cd9f556",
        top_k=50
    )

    query = "Artificial Intelligence"

    pattern = await google_searcher.patents(query=query)
    print(pattern)

    

if __name__ == "__main__":
    asyncio.run(main())
