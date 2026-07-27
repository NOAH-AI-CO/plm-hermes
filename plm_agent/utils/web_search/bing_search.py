import random
import logging
import asyncio
import httpx

from urllib.parse import urlparse

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton
from utils.web_search.base_search import BaseSearch, global_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BingSearch(BaseSearch):

    def __init__(self,
                 api_key: str,
                 region: str = 'zh-CN',
                 top_k: int = 3,
                 black_list=None,
                 timeout: int = 10,
                 **kwargs):
        if black_list is None:
            black_list = [
                'enoN',
                'youtube.com',
                'bilibili.com',
                'researchgate.net',
            ]
        self.api_key = api_key
        self.market = region
        self.timeout = httpx.Timeout(
            5.0,
            read=10.0,     # Read timeout
        )
        super().__init__(top_k, black_list)

    @global_cache
    async def search(self, query: str, max_retry: int = 3) -> dict:
        for attempt in range(max_retry):
            try:
                response = await self._call_web_search_api(query)
                return self._parse_web_search_response(response)
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f'BingSearch retry {attempt + 1}/{max_retry} due to error: {e}')
                                
                if attempt < max_retry - 1:  # Don't sleep on the last attempt
                    # Exponential backoff: 2^attempt seconds, max 10 seconds
                    sleep_time = min(2 ** attempt, 2)
                    await asyncio.sleep(sleep_time)
        raise Exception(
            'Failed to get search results from Bing Search after retries.')

    @global_cache
    async def news(self, query: str, max_retry: int = 3) -> dict:
        for attempt in range(max_retry):
            try:
                response = await self._call_news_api(query)
                return self._parse_news_search_response(response)
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f'Retry {attempt + 1}/{max_retry} due to error: {e}')
                
                # If it's a connection error, try resetting the HTTP client
                if "Failed to connect" in str(e) and attempt < max_retry - 1:
                    logger.info("Resetting HTTP client due to connection error")
                    HttpxClientSingleton.reset()
                
                if attempt < max_retry - 1:  # Don't sleep on the last attempt
                    # Exponential backoff: 2^attempt seconds, max 10 seconds
                    sleep_time = min(2 ** attempt, 10)
                    await asyncio.sleep(sleep_time)
        raise Exception(
            'Failed to get search results from Bing Search after retries.')

    async def _call_web_search_api(self, query: str, endpoint: str = api_config.BING_SEARCH_URL) -> dict:
        params = {'q': query, 'mkt': self.market, 'count': f'{self.top_k * 2}'}
        headers = {'Ocp-Apim-Subscription-Key': self.api_key}

        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Connection error to Bing API: {e}")
            raise Exception(f"Failed to connect to Bing API: {e}")
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error to Bing API: {e}")
            raise Exception(f"Request to Bing API timed out: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Bing API: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Bing API returned HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error(f"Unexpected error calling Bing API: {e}")
            raise Exception(f"Unexpected error calling Bing API: {e}")
    
    async def _call_news_api(self, query: str, endpoint: str = api_config.BING_NEWS_SEARCH_URL) -> dict:
        params = {'q': query, 'count': f'{self.top_k * 2}'}
        headers = {'Ocp-Apim-Subscription-Key': self.api_key}
        
        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                endpoint,
                headers=headers,
                params=params,
                timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            logger.error(f"Connection error to Bing News API: {e}")
            raise Exception(f"Failed to connect to Bing News API: {e}")
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error to Bing News API: {e}")
            raise Exception(f"Request to Bing News API timed out: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Bing News API: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Bing News API returned HTTP {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error(f"Unexpected error calling Bing News API: {e}")
            raise Exception(f"Unexpected error calling Bing News API: {e}")

    def _parse_web_search_response(self, response: dict) -> dict:
        def get_site_name(webpage: dict) -> str:
            site_name = webpage.get('siteName', None)
            if site_name is None:
                parsed_url = urlparse(webpage['url'])
                site_name = parsed_url.netloc
            return site_name

        webpages = {
            w['id']: w
            for w in response.get('webPages', {}).get('value', [])
        }
        raw_results = []

        for item in response.get('rankingResponse',
                                 {}).get('mainline', {}).get('items', []):
            if item['answerType'] == 'WebPages':
                webpage = webpages.get(item['value']['id'])
                if webpage:
                    raw_results.append(
                        (webpage['url'], webpage['snippet'], webpage['name'], get_site_name(webpage=webpage)))

            elif item['answerType'] == 'News' and item['value'][
                    'id'] == response.get('news', {}).get('id'):
                for news in response.get('news', {}).get('value', []):
                    raw_results.append(
                        (news['url'], news['description'], news['name'], get_site_name(webpage=webpage)))

        return self._filter_results(raw_results)
    
    def _parse_news_search_response(self, response: dict) -> dict:
        def get_site_name(webpage: dict) -> str:
            site_name = None
            providers = webpage.get('provider', [])
            if len(providers) > 0:
                provider = providers[0]
                site_name = provider.get('name', '')
            if site_name is None:
                parsed_url = urlparse(webpage['url'])
                site_name = parsed_url.netloc
            return site_name

        raw_results = []
        for news in response.get('value', []):
            raw_results.append((news['url'], news['description'], news['name'], get_site_name(webpage=news)))
        
        return self._filter_results(raw_results)
    
class BingCustomSearch(BingSearch):
    r"""
    guideline https://learn.microsoft.com/zh-cn/bing/search-apis/bing-custom-search/how-to/quick-start
    portal https://www.customsearch.ai/applications
    """

    def __init__(self,
                 api_key: str,
                 custom_config_id: str,
                 region: str = 'zh-CN',
                 top_k: int = 3,
                 black_list=None,
                 **kwargs):
        if black_list is None:
            black_list = [
                'enoN',
                'youtube.com',
                'bilibili.com',
                'researchgate.net',
            ]
        self.custom_config_id = custom_config_id
        super().__init__(api_key, region, top_k, black_list, **kwargs)

    async def _call_bing_api(self, query: str) -> dict:
        endpoint = api_config.BING_CUSTOMER_SEARCH_URL
        params = {'q': query, 'customconfig': self.custom_config_id, 'mkt': self.market, 'count': f'{self.top_k * 2}'}
        headers = {'Ocp-Apim-Subscription-Key': self.api_key}
        
        client = HttpxClientSingleton.get_asynclient()
        response = await client.get(
            endpoint,
            headers=headers,
            params=params,
            timeout=self.timeout)
        response.raise_for_status()
        return response.json()

async def main():

    bing_searcher = BingSearch(
        api_key="your_bing_api_key",
        top_k=3
    )

    query = "Artificial Intelligence latest developments"

    result = await bing_searcher.search(query=query)

    print(result)


if __name__ == "__main__":
    asyncio.run(main())

