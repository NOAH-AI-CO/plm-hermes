import re
import asyncio
import random
import time
import json
import aiohttp
import hashlib

from urllib.parse import urlparse
from typing import Tuple, List
from functools import wraps

from config import api_config
from duckduckgo_search import DDGS
from bs4 import BeautifulSoup
from cachetools import TTLCache
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError


from config import api_config

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_global_content_cache = TTLCache(maxsize=100, ttl=600)

def global_cache(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        cache_key = kwargs.get('query')
        if cache_key in _global_content_cache:
            return _global_content_cache[cache_key]
        
        result = await func(*args, **kwargs)
        _global_content_cache[cache_key] = result
        return result
    return wrapper

_global_webpage_content_cache = TTLCache(maxsize=1000, ttl=60*60)

def global_webpage_cache(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        cache_key = kwargs.get('url')
        if cache_key in _global_webpage_content_cache:
            return _global_webpage_content_cache[cache_key]
        
        result = await func(*args, **kwargs)
        _global_webpage_content_cache[cache_key] = result
        return result
    return wrapper


class BaseSearch:

    def __init__(self, top_k: int = 3, black_list: List[str] = None):
        self.top_k = top_k
        self.black_list = black_list + ['verifiedmarketresearch.com']

    def _filter_results(self, results: List[tuple]) -> dict:
        filtered_results = {}
        count = 0
        for url, snippet, title, site_name in results:
            if all(domain not in url
                   for domain in self.black_list) and not url.endswith('.pdf'):
                filtered_results[count] = {
                    'url': url,
                    'summ': json.dumps(snippet, ensure_ascii=False)[1:-1],
                    'title': title,
                    'site_name': site_name,
                }
                count += 1
                if count >= self.top_k:
                    break
        return filtered_results


class DuckDuckGoSearch(BaseSearch):

    def __init__(self,
                 topk: int = 3,
                 black_list: List[str] = [
                     'enoN',
                     'youtube.com',
                     'bilibili.com',
                     'researchgate.net',
                     'verifiedmarketresearch.com'
                 ],
                 **kwargs):
        self.proxy = kwargs.get('proxy')
        self.timeout = kwargs.get('timeout', 30)
        super().__init__(topk, black_list)

    @global_cache
    async def search(self, query: str, max_retry: int = 3) -> dict:
        for attempt in range(max_retry):
            try:
                response = await self._async_call_ddgs(
                    query, timeout=self.timeout, proxy=self.proxy)
                return self._parse_response(response)
            except Exception as e:
                logging.exception(str(e))
                logger.warning(f'Retry {attempt + 1}/{max_retry} due to error: {e}')
                await asyncio.sleep(random.randint(2, 5))
        raise Exception(
            'Failed to get search results from DuckDuckGo after retries.')

    async def _async_call_ddgs(self, query: str, **kwargs) -> dict:
        ddgs = DDGS(**kwargs)
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(ddgs.text, query.strip("'"), max_results=10),
                timeout=self.timeout)
            return response
        except asyncio.TimeoutError:
            logging.exception('Request to DDGS timed out.')
            raise

    def _call_ddgs(self, query: str, **kwargs) -> dict:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                self._async_call_ddgs(query, **kwargs))
            return response
        finally:
            loop.close()

    def _parse_response(self, response: dict) -> dict:
        raw_results = []
        for item in response:
            raw_results.append(
                (item['href'],
                 item['description'] if 'description' in item else item['body'],
                 item['title'],
                 ''))
        return self._filter_results(raw_results)

class ContentFetcher:

    r"""
    Simple web page content fetcher.
    """

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'zh,en-US;q=0.9,en;q=0.8',
            'cache-control': 'max-age=0',
            'cookie': 'PHPSESSID=1434598fa2c827d8317cfd07a12690d8; _gid=GA1.2.604967175.1731922120; _scor_uid=e0f790ec51844e36833bd77a4a73ef8a; __gsas=ID=48d3e9940af69df0:T=1731922153:RT=1731922153:S=ALNI_MZvQxBWz3qs01VOpC-AgbL99KNZSw; pbjs_sharedId=e6b81549-4440-4f26-b278-847e2f24241c; _curator_id=DE.V1.706645562c.1731922161728; _cm=eyIxIjpmYWxzZSwiMiI6ZmFsc2UsIjMiOmZhbHNlfQ==; _lr_sampling_rate=100; _lr_env_src_ats=false; pbjs_sharedId_cst=VyxHLMwsHQ%3D%3D; bm_ss=ab8e18ef4e; bm_s=YAAQ7jDUFyCwWzOTAQAA0GidQwLg7a9tYEtS5HnTjwvZI/q0kUR/pt260oa6RHPbg33ZW+9I7Z6qcH5Lt8iUWGzUyRIXhBSRwHF9gZN1jxsJyhkAoiXCvSEO01iSKjrf8eSClOdCTs04ki+0B3tw1DT7vbNrccXftK3WQQpWi4QQWVzJ7TgTgYTRYS73rSdhHkPJCGCzht5tiVzCZhk9zgOhulYTZua0iG5J1jjowi9y/dro0VwLdf1cyGprqZAwOkFLVO//sIDgOp7uTLo+EdwdJHOiBEY/hBiwGYCCsurVwQYMSaz3WgX8iq6ywu0dAEuyAKs0afRqAVmWx9kjeX0Y3Q==; bm_so=76BBE50CCAB1B9F1594ED191389CB12A1158EB3EEDDE72173C2964DD0FF5BA30~YAAQ7jDUFyGwWzOTAQAA0GidQwHLnYj2AWYU67KqOqFIsKoRvooemEGGVh82IPEiHPsEhUqZ3IXtqs3BQ3qmVEWvt6EvHaELxF6YwodxnELK4TZwW33Up+RHk1KoHbl0t/v4EVmp78S9lEYwCTJE61Z57b3xjpNxUnpQyOvzdmrPfbiArVBpONd1+g7c8/29wMxkZ/Z3qAAY2BioDDGrNdF6/E7aMfNjwJcNifHdgK2IkHO1BACwB4tNGhpJ6DFbfEhS+jwQSq7mz008e2xAyCPGx/5KLGCOMyyFP5FaBRtWPJfJdAzddz1myFT+6lV+GhshxFeKdc+n9z6TiJyqtbMi9zjWORp1GEYWa5eMhPCzyg+2/ryBW/x+POll7TSmT4t1Xg81DOUFUBxdf47bEb/yyiOMutGik/4QJDHoLRTt+ZWPdeUCyCRVeKON1JDIX1vocn63OP+CBpCCDiU=; __gads=ID=98893d9b3e09f75d:T=1731922153:RT=1732006210:S=ALNI_Mb_3STKX6jvQCHV9pA2yGeiRrcQng; __gpi=UID=00000f980d73b9dc:T=1731922153:RT=1732006210:S=ALNI_MaiZE88SgJOXXk11b7rDOjxgTZgYg; __eoi=ID=ff671c38912eed08:T=1731922153:RT=1732006210:S=AA-AfjZmaXfPXYKBDO3CeZ20PetO; FCNEC=%5B%5B%22AKsRol81F-Al6Ry07LLoB4JVsBadj_i-9Tx1M3P6lFqBO7pVeE9Rvd6g0lSIp2BlZPSYMpLDOaskPub0s4xRRC8Fzs-KUzNA54DfJUJWl5eFpNXRYkHGfQhFR1UCEIzgoXQ4wvlVsmkbZyQBOt3mmz3td4bMaXmEbw%3D%3D%22%5D%5D; bm_lso=76BBE50CCAB1B9F1594ED191389CB12A1158EB3EEDDE72173C2964DD0FF5BA30~YAAQ7jDUFyGwWzOTAQAA0GidQwHLnYj2AWYU67KqOqFIsKoRvooemEGGVh82IPEiHPsEhUqZ3IXtqs3BQ3qmVEWvt6EvHaELxF6YwodxnELK4TZwW33Up+RHk1KoHbl0t/v4EVmp78S9lEYwCTJE61Z57b3xjpNxUnpQyOvzdmrPfbiArVBpONd1+g7c8/29wMxkZ/Z3qAAY2BioDDGrNdF6/E7aMfNjwJcNifHdgK2IkHO1BACwB4tNGhpJ6DFbfEhS+jwQSq7mz008e2xAyCPGx/5KLGCOMyyFP5FaBRtWPJfJdAzddz1myFT+6lV+GhshxFeKdc+n9z6TiJyqtbMi9zjWORp1GEYWa5eMhPCzyg+2/ryBW/x+POll7TSmT4t1Xg81DOUFUBxdf47bEb/yyiOMutGik/4QJDHoLRTt+ZWPdeUCyCRVeKON1JDIX1vocn63OP+CBpCCDiU=^1732006214445; ddc-pvc=4; _ga_NC862DPYNN=GS1.1.1732006215.2.0.1732006215.60.0.0; _ga=GA1.2.394647214.1731922119; _gat_UA-78451-2=1; _clck=5p0138%7C2%7Cfr0%7C0%7C1783; _clsk=mslxpu%7C1732006216480%7C1%7C0%7Cf.clarity.ms%2Fcollect',
            'priority': 'u=0, i',
            'sec-ch-ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'cross-site',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'x-wz-env': 'wanzhi-gray-branch'
        }
        self.table_service_client = TableServiceClient.from_connection_string(conn_str=api_config.AZURE_CRAWLER_STORAGE_CONNECTION_STRING)
        self.table_client = self.table_service_client.get_table_client(table_name="webpage")

    def _urlhash(self, url: str) -> str:
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    
    def _get_domain(self, url: str) -> str:
        parsed_url = urlparse(url)
        domain_with_port = parsed_url.netloc
        domain = domain_with_port.split(':')[0]
        return domain

    def _fetch_from_azure_blob(self, url: str) -> Tuple[bool, str]:

        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)

            entity = self.table_client.get_entity(
                row_key=urlhash,
                partition_key=domain,
                logging_enable=False, # avoid to many unused logs
            )

            if 'webpagecontent' not in entity:
                logger.error(f'Azure blob missing content, partition_key:{domain} row_key: {urlhash}')
                return False, 'Azure blob missing content'
            
            return True, entity['webpagecontent']

        except ResourceNotFoundError as e:
            #logger.error(f"azure blob don't exist", e)
            return False, "Azure blob don't exist"

        except Exception as e:
            logger.error(f"fetch web content from azure blob failed: {e}")
            return False, f"{type(e).__name__}: {str(e)}"
        

    def _save_azure_blob(self, url: str, content: str):
        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)

            entity = {
                'partition_key': domain,
                'row_key': urlhash,
                'url': url,
                'webpagecontent': content,
            }
            self.table_client.upsert_entity(entity=entity)
        except Exception as e:
            logger.warning(f"Azure blob save failed: {e}")


    @global_webpage_cache
    async def fetch(self, url: str) -> Tuple[bool, str]:
        try:
            
            #Try fetch from Azure table storage
            #found, content = self._fetch_from_azure_blob(url=url)
            #if found:
            #    return found, content

            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    ssl=False
                )as response:
                    response.raise_for_status()
                    html = await response.read()
        except Exception as e:
            logger.warn(f"Request failed for {url}: {type(e).__name__} - {str(e)}")
            return False, f"{type(e).__name__}: {str(e)}"

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, lambda: BeautifulSoup(html, 'html.parser').get_text())
        cleaned_text = await loop.run_in_executor(None, lambda: re.sub(r'\n+', '\n', text))

        return True, cleaned_text


async def test_search_engine(searcher, query: str):
    try:
        search_results = await searcher.search(query=query)
        print(f"\n{searcher.__class__.__name__} Results:")
        print(search_results)

        fetcher = ContentFetcher()
        new_search_results = {}
        
        # 并发获取所有URL的内容
        tasks = []
        for select_id, result in search_results.items():
            tasks.append(fetcher.fetch(result['url']))
        
        fetch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理结果
        for select_id, (web_success, web_content) in enumerate(fetch_results):
            if isinstance(web_success, Exception):
                logger.warning(f'{select_id} generated an exception: {web_success}')
                continue
                
            if web_success:
                search_results[select_id]['content'] = web_content[:8192]
                new_search_results[select_id] = search_results[select_id].copy()
                new_search_results[select_id].pop('summ')
        
        print(f"\n{searcher.__class__.__name__} Fetched Contents:")
        print(new_search_results)
        
    except Exception as e:
        print(f"Error testing {searcher.__class__.__name__}: {str(e)}")

async def main():    
    
    ddg_searcher = DuckDuckGoSearch(
        topk=3
    )
    
    # 测试查询
    query = "Artificial Intelligence latest developments"
    
    # 依次测试每个搜索引擎
    await test_search_engine(ddg_searcher, query)
    #await test_search_engine(google_searcher, query)
    #await test_search_engine(ddg_searcher, query)

if __name__ == "__main__":
    asyncio.run(main())
