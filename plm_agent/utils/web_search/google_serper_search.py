import httpx
import asyncio
import logging
import random

from urllib.parse import urlparse

from config import api_config
from utils.core.httpx_client import HttpxClientSingleton
from utils.web_search.base_search import BaseSearch, global_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# doc reference https://serper.dev/

class GoogleSerperSearch(BaseSearch):

    def __init__(
        self,
        api_key: str,
        region: str = 'us', # default is global or united states, so far we only support jp, cn,
        top_k: int = 10,
        black_list: list[str] = [],
        **kwargs):

        self.base_url = api_config.GOOGLE_SERPER_URL
        self.api_key = api_key
        self.region = region
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

        data = {
            "q": query,
            "num": self.top_k,
        }
        if type not in ['patents'] \
            and self.region != '':
            data['gl'] = self.region

        headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

        url = f"{self.base_url}/{type}"

        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.post(
                url,
                json=data,
                headers=headers,
                timeout=self.timeout,
                auth=None,
            )
            response.raise_for_status()
            return response.json()
                
        except Exception as e:
            logger.error(f"Serper api request {e.__class__.__name__}: {e}")
            raise

    @global_cache
    async def search(
        self,
        query: str,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                response = await self._call_api(query=query, type='search')
                return self._parse_web_search_response(response)
            except Exception as e:
                logging.warning(f"[Google Serper] Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))

    @global_cache
    async def patents(
        self,
        query: str,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                response = await self._call_api(query=query, type='patents')
                return self._parse_patents_response(response)
            except Exception as e:
                logging.warning(f"[Google Serper] Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))

    @global_cache
    async def news(
        self,
        query: str,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                response = await self._call_api(query=query, type='news')
                return self._parse_news_response(response)
            except Exception as e:
                logging.warning(f"[Google Serper] Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))

    @global_cache
    async def scholar(
        self,
        query: str,
        max_retry: int = 2):

        for attempt in range(max_retry):
            try:
                response = await self._call_api(query=query, type='scholar')
                return self._parse_scholar_response(response)
            except Exception as e:
                logging.warning(f"[Google Serper] Retry {attempt + 1}/{max_retry} due to error: {e}")
                await asyncio.sleep(random.randint(1, 3))

    def _parse_knowledge_graph(
        self,
        knowledge_graph: dict) -> tuple:

        def get_site_name(webpage: dict) -> str:
            site_name = webpage.get('descriptionSource', None)
            if site_name is None:
                parsed_url = urlparse(webpage.get('url', ''))
                site_name = parsed_url.netloc
            return site_name

        url = knowledge_graph.get("descriptionLink", "") or 'https://www.google.com'
        title = knowledge_graph.get("title", "")
        content = knowledge_graph.get("description", "")
        
        if 'attributes' in knowledge_graph:
            content += (",").join([
                f"{key}: {value}"
                for key, value in knowledge_graph['attributes'].items()
            ])

        return (url, content, title, get_site_name(knowledge_graph))
    
    def _parse_answerbox(
        self,
        answerbox: dict) -> tuple:

        answer = answerbox.get('answer', '') or answerbox.get('snippet', '') or answerbox.get('snippetHighlighted', '')

        return ('', answer, 'google answer box', 'google')

    def _parse_web_search_response(
        self,
        response: dict) -> list:

        def get_site_name(webpage: dict) -> str:
            #TODO serper api don't provide sitename map， justuse
            parsed_url = urlparse(webpage['link'])
            site_name = parsed_url.netloc
            return site_name
        
        raw_results = []
        if "knowledgeGraph" in response:
            raw_results.append(self._parse_knowledge_graph(response.get('knowledgeGraph')))

        if "answerBox" in response:
            raw_results.append(self._parse_answerbox(response.get('answerBox')))

        for item in response['organic']:
            url = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            if 'attributes' in item:
                snippet += (",").join([
                    f"{key}: {value}"
                    for key, value in item['attributes'].items()
                ])
            raw_results.append((url, snippet, title, get_site_name(item)))
        
        return self._filter_results(raw_results)

    def _parse_patents_response(
        self,
        response: dict) -> list:

        raw_results = []

        for item in response.get("organic", []):

            url = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            attribute_key = ["priorityDate", "filingDate", "publicationDate", "inventor", "assignee", "publicationNumber", "language"]
            for key in attribute_key:
                if key in item:
                    snippet += f"{key}: {item[key]}, "

            raw_results.append((url, snippet, title, 'google.com'))

        return self._filter_results(raw_results)

    def _parse_news_response(
        self,
        response: dict) -> list:

        def get_site_name(webpage: dict) -> str:
            site_name = webpage.get('source', None)
            if site_name is None:
                parsed_url = urlparse(webpage['url'])
                site_name = parsed_url.netloc
            return site_name

        raw_results = []

        for item in response.get("news", []):
            url = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            if "date" in item:
                snippet += f"date: {item['date']}"

            raw_results.append((url, snippet, title, get_site_name(item)))

        return self._filter_results(raw_results)

    def _parse_scholar_response(
        self,
        response: dict) -> list:
        
        def get_site_name(webpage: dict) -> str:
            #TODO serper api don't provide sitename map， justuse
            parsed_url = urlparse(webpage['url'])
            site_name = parsed_url.netloc
            return site_name
        
        raw_results = []

        for item in response.get("organic", []):
            url = item.get("link", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")

            attribute_key = ["publicationInfo", "year", "citedBy"]
            for key in attribute_key:
                if key in item:
                    snippet += f"{key}: {item[key]}, "

            raw_results.append((url, snippet, title, get_site_name(item)))

        return self._filter_results(raw_results)

async def main():

    google_searcher = GoogleSerperSearch(
        api_key="0a061bac583b822c7ae26a522240cd59cede88f7",
        top_k=50
    )

    query = "Artificial Intelligence latest developments"

    #websearch = await google_searcher.search(query=query)
    #print(websearch)
    
    #news = await google_searcher.news(query=query)
    #print(news)

    pattern = await google_searcher.patents(query=query)
    print(pattern)

    #scholar = await google_searcher.scholar(query=query)
    #print(scholar)
    

if __name__ == "__main__":
    asyncio.run(main())

