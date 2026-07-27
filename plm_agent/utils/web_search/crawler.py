import io
import re
import time
import json
import httpx
import asyncio
import hashlib

from enum import Enum
from urllib.parse import urlparse, unquote
from typing import Tuple, List
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

from utils.core.httpx_client import HttpxClientSingleton
from utils.azure.blob_client import AzureBlobStorage
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError

from config import api_config

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CacheResultEnum(Enum):
    UNKNOWN = 0
    TIMEOUT = 1
    FETCHED = 2
    FAILED = 3


class ContentFetcherBase:

    def __init__(self):
        
        self.timeout = httpx.Timeout(
            15.0,
            read=20.0,     # Read timeout
        )

        self.table_service_client = TableServiceClient.from_connection_string(conn_str=api_config.AZURE_BLOB_CONN_STR)
        self.table_client = self.table_service_client.get_table_client(table_name="webpage")

        # Azure Blob Storage client (for large content, no size limit)
        self.blob_storage_client = AzureBlobStorage(
            connection_string=api_config.AZURE_BLOB_CONN_STR_CRAWLER
        )
        self.blob_container = "crawler-files"

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

    def _urlhash(self, url: str) -> str:
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    
    def _get_domain(self, url: str) -> str:
        parsed_url = urlparse(url)
        domain_with_port = parsed_url.netloc
        domain = domain_with_port.split(':')[0]
        return domain

    def _fetch_from_azure_blob(self, url: str) -> Tuple[CacheResultEnum, str]:

        try:
            # TODO add time check for content update
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)

            entity = self.table_client.get_entity(
                row_key=urlhash,
                partition_key=domain,
            )

            if 'webpagecontent' not in entity:
                logger.error(f'Azure blob missing content, partition_key:{domain} row_key: {urlhash}')
                return CacheResultEnum.FAILED, 'Azure blob missing content'
            
            # check timeless
            # entity.metadata
            # {'etag': 'W/"datetime\'2025-03-27T07%3A20%3A06.6738491Z\'"', 'timestamp': TablesEntityDatetime(2025, 3, 27, 7, 20, 6, 673849, tzinfo=datetime.timezone.utc)}
            if hasattr(entity, 'metadata'):
                timestamp = entity.metadata.get('timestamp', None)
                if timestamp:
                    # 计算1个月前的时间戳
                    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
                    one_month_ago_timestamp = one_month_ago.timestamp()
                    
                    # 如果entity的时间戳早于1个月前，说明内容过期，需要重新获取
                    if timestamp.timestamp() < one_month_ago_timestamp:
                        logger.info(f"Content for {url} is expired (updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}, expired since: {one_month_ago.strftime('%Y-%m-%d %H:%M:%S')})")
                        return CacheResultEnum.TIMEOUT, entity['webpagecontent']
                    
                    logger.info(f"Content for {url} is fresh (updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
            
            return CacheResultEnum.FETCHED, entity['webpagecontent']

        except ResourceNotFoundError as e:
            #logger.error(f"azure blob don't exist", e)
            return CacheResultEnum.FAILED, "Azure blob don't exist"

        except Exception as e:
            logger.error(f"fetch web content from azure blob failed: {e}")
            return CacheResultEnum.FAILED, f"{type(e).__name__}: {str(e)}"

    def _fetch_from_blob(self, url: str) -> Tuple[CacheResultEnum, str]:
        """Fetch webpage content from Azure Blob Storage"""
        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)
            
            blob_path = f"ttl_365d/{domain}/{urlhash}"
            
            # Get blob metadata to check if exists and get last_modified time
            meta = self.blob_storage_client.get_blob_meta(
                container=self.blob_container,
                blob=blob_path
            )
            
            if meta is None:
                return CacheResultEnum.FAILED, "Blob doesn't exist"
            
            # Check if content is expired (30 days)
            last_modified = meta.get('last_modified')
            is_expired = False
            if last_modified:
                one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
                if last_modified < one_month_ago:
                    is_expired = True
                    logger.info(f"Content for {url} is expired (updated: {last_modified})")
            
            # Load content
            content_bytes = self.blob_storage_client.load_file(
                container=self.blob_container,
                blob=blob_path
            )
            
            if content_bytes is None:
                return CacheResultEnum.FAILED, "Failed to load blob content"
            
            # Decode bytes to string
            content = content_bytes.decode('utf-8')
            
            if is_expired:
                return CacheResultEnum.TIMEOUT, content
            
            logger.info(f"Content for {url} is fresh")
            return CacheResultEnum.FETCHED, content
            
        except Exception as e:
            logger.error(f"fetch web content from Azure Blob failed: {e}")
            return CacheResultEnum.FAILED, f"{type(e).__name__}: {str(e)}"

    def _save_azure_blob(self, url: str, content: str, create_partition_key: bool = False):
        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)

            entity = {
                "PartitionKey": domain,
                "RowKey": urlhash,
                "url": url,
                "webpagecontent": content[:31 * 1024], # azure blob max string size is utf-16 32k
            }
            result = self.table_client.upsert_entity(entity=entity)
            logger.info(f"save to Azure blob url:{url}, result:{result}")
        except Exception as e:
            logger.warn("Azure blob save failed", e)

    def _save_to_blob(self, url: str, content: str):
        """Save webpage content to Azure Blob Storage (no size limit)"""
        try:
            domain = self._get_domain(url)
            urlhash = self._urlhash(url)
            
            # Blob path: ttl_365d/domain/urlhash (no extension, store string directly)
            blob_path = f"ttl_365d/{domain}/{urlhash}"
            
            # Encode string to bytes for storage
            content_bytes = content.encode('utf-8')
            file_obj = io.BytesIO(content_bytes)
            
            result = self.blob_storage_client.upload_file(
                container=self.blob_container,
                blob=blob_path,
                file_obj=file_obj,
                metadata={"url": url},
            )
            logger.info(f"save to Azure Blob Storage url:{url}, blob:{blob_path}")
        except Exception as e:
            logger.warn(f"Azure Blob Storage save failed: {e}")

    async def _fetch(self, url: str) -> str:
        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                url, 
                headers=self.headers, 
                timeout=self.timeout,
                follow_redirects=True,
                auth=None,
            )
            response.raise_for_status()
            html = response.text

            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, lambda: BeautifulSoup(html, 'html.parser').get_text())
            cleaned_text = await loop.run_in_executor(None, lambda: re.sub(r'\n+', '\n', text))
            
            return cleaned_text
        except Exception as e:
            logger.warn(f"Request failed for {url}: {type(e).__name__} - {str(e)}")
            return None
        
    def _parse_content(self, content:str, url: str, type: str) -> str:
        if content is None:
            return None
        
        if 'patent' == type:
            if 'patents.google' in url:
                _, _, wanted = content.partition("Description")
                wanted = wanted.lstrip()
                if wanted != '':
                    return wanted[:1024 * 15]
            elif 'magtech' in url:
                _, _, wanted = content.partition("下一篇")
                wanted = wanted.lstrip()
                if wanted != '':
                    return wanted[:1024 * 15]
        return content

    async def fetch(self, url: str, type: str = 'web') -> Tuple[bool, str]:
        try:
            # Try fetch from Azure Table (cache); read path not using _fetch_from_blob for now
            cache_result, content = self._fetch_from_azure_blob(url=url)
            if CacheResultEnum.FETCHED == cache_result:
                return True, str(content)
            
            result = await self._fetch(url)

            result = self._parse_content(result, url, type)

            if result:
                # Save to both Azure Table and Azure Blob Storage
                self._save_azure_blob(url, result)
                self._save_to_blob(url, result)

                return True, result
            
            elif CacheResultEnum.TIMEOUT == cache_result:
                return True, str(content)

            else:
                return False, 'fetching failed'
            
        except asyncio.TimeoutError:
            logger.warn(f"Timeout firecrawl while fetching {url}")
            return False, "Request timeout"
        except Exception as e:
            logger.warn(f"Error while fetching {url} {str(e)}")
            return False, str(e)


class FirecrawlFetcher(ContentFetcherBase):

    #https://docs.firecrawl.dev/api-reference/endpoint/scrape
    #https://docs.firecrawl.dev/features/fast-scraping

    def __init__(self):
        super().__init__()

    async def _fetch(self, url: str) -> str:
        try:

            payload = {
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "maxAge": 604800000, # 1 week
                "timeout": 25*1000, #ms
                "parsers": ["pdf"]
            }

            headers = {
                "Authorization": f"Bearer {api_config.FIRECRAWL_API_KEY}",
                "Content-Type": "application/json"
            }

            client = HttpxClientSingleton.get_asynclient()
            response = await client.post(
                url=api_config.FIRECRAWL_BASE_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                auth=None,
            )
            response.raise_for_status()
            result = response.json()

            markdown = None
            if result and result.get('success', False):
                markdown = str(result.get('data', {}).get('markdown', ''))
            
            return markdown

        except Exception as e:
            #logger.warn(f"Firecrawl failed to fetch {url}", e)
            logger.warning(f"Firecrawl failed to fetch {url} {str(e)}")
            return None


class JinaFetcher(ContentFetcherBase):

    def __init__(self):
        self.api_key = api_config.JINA_API_KEY
        self.headers = {
            "Authorization": f" Bearer {self.api_key}",
            "X-Retain-Images": "none",
            "X-Return-Format": "markdown", # cost time too long
            "X-Token-Budget": 250000,
        }
        super().__init__()

    async def _fetch(self, url: str) -> str:
        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                auth=None,
            )
            response.raise_for_status()
            content = response.text
            
            return str(content)
        except asyncio.TimeoutError:
            logger.warn(f"Timeout jina while fetching {url}")
            return None
        except Exception as e:
            logger.warn(f"Jina failed to fetch {url} {str(e)}")
            return None
        

class SerperFetch(ContentFetcherBase):

    def __init__(self):
        self.api_key = api_config.GOOGLE_SERPER_API_KEY
        self.base_url = api_config.SERPER_SCRAPE_URL
        self.headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json',
        }
        super().__init__()

    async def _fetch(self, url: str) -> str:
        try:
            payload = json.dumps({
                "url": url,
                "includeMarkdown": True
                })
            client = HttpxClientSingleton.get_asynclient()
            response = await client.post(
                self.base_url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout,
                auth=None,
            )
            data = response.read()
            return str(data)
        except asyncio.TimeoutError:
            logger.warn(f"Timeout Seper while fetching {url}")
            return None
        except Exception as e:
            logger.warn(f"Seper failed to fetch {url} {str(e)}")
            return None
        
class SerpapiFetch(ContentFetcherBase):

    def __init__(self):
        
        self.api_key = api_config.GOOGLE_SERPAPI_API_KEY
        self.base_url = api_config.GOOGLE_SERPAPI_URL
        super().__init__()

    async def fetch_patent(self, patent_id: str) -> str:
        r"""
        Serpapi only support google patent.
        """
        params = {
            "engine": "google_patents_details",
            "patent_id": patent_id,
            "api_key": self.api_key,
            "no_cache": True,
        }

        try:
            client = HttpxClientSingleton.get_asynclient()
            response = await client.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            
            # Fetch detail
            description = ''
            description_link = data.get('description_link', '')
            if description_link:
                description_response = await client.get(
                    description_link,
                    timeout=self.timeout,
                )
                soup = BeautifulSoup(description_response.content, "html.parser")
                description = soup.get_text(separator="\n", strip=True)

            res = {
                'abstract': data.get('abstract', ''),
                'claims': data.get('claims', []),
                'description': description,
                'title': data.get('title', ''),
                'publication_number': data.get('publication_number', ''),
                'country': data.get('country', ''),
                'prior_art_keywords': data.get('prior_art_keywords', []),
            }
            return True, json.dumps(res, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Serpapi call failed: {type(e).__name__}: {e}")
            raise  

class ContentFetcher:

    firecrawl_client = FirecrawlFetcher()
    jina_client = JinaFetcher()
    serper_client = SerperFetch()
    serpapi_client = SerpapiFetch()

    # 附件检测器 (懒加载)
    _attachment_detector = None

    # 附件下载器 (懒加载)
    _attachment_downloader = None

    # 可直接下载的文件扩展名
    DOWNLOADABLE_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.csv'}

    @property
    def attachment_detector(self):
        """懒加载附件检测器"""
        if self._attachment_detector is None:
            from utils.web_search.attachment_detector import AttachmentDetector
            self._attachment_detector = AttachmentDetector()
        return self._attachment_detector

    @property
    def attachment_downloader(self):
        """懒加载附件下载器"""
        if self._attachment_downloader is None:
            from utils.web_search.attachment_downloader import AttachmentDownloader
            self._attachment_downloader = AttachmentDownloader()
        return self._attachment_downloader

    def _is_downloadable_file(self, url: str) -> bool:
        """判断 URL 是否是可直接下载的文件"""
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        return any(path.endswith(ext) for ext in self.DOWNLOADABLE_EXTENSIONS)

    def _get_extension_from_url(self, url: str) -> str:
        """从 URL 获取扩展名"""
        parsed = urlparse(url)
        path = unquote(parsed.path).lower()
        for ext in self.DOWNLOADABLE_EXTENSIONS:
            if path.endswith(ext):
                return ext
        return ''

    async def _fetch_file(self, url: str):
        """使用本地下载器获取文件"""
        return await self.attachment_downloader.download_single(url)

    async def _retry(
        self,
        urls: list[str],
        url_map: dict,
        crawler: str = 'firecrawl'):
        
        tasks = []
        urls = [url for url in urls if url not in url_map]
        for url in urls:
            if 'firecrawl' == crawler:
                task = asyncio.create_task(
                    self.jina_client.fetch(url)
                )
            else:
                task = asyncio.create_task(
                    self.firecrawl_client.fetch(url)
                )
            tasks.append((task, url))

        count = 0
        for task, url in tasks:
            try:
                web_success, web_content = await task
                if web_success:
                    count += 1
                    url_map[url] = web_content
            except Exception as exc:
                logger.warn(f"Retry {url} fetch failed and meet exception {str(exc)}")
        
        return url_map

    async def fetch_google_patents(self, patent_ids: list[str], enable_retry: bool = False):
        start_time = time.time()

        tasks = []
        for patent_id in patent_ids:
            task = asyncio.create_task(
                self.serpapi_client.fetch_patent(patent_id)
            )
            tasks.append((task, patent_id))

        res = {}
        for task, patent_id in tasks:
            try:
                web_success, web_content = await task
                if web_success:
                    res[patent_id] = web_content
            except Exception as exc:
                logger.warning(f"{patent_id} fetch failed and meet exception: {exc}")

        end_time = time.time()
        logger.info(f"Fetch link content cost {end_time - start_time}, fetched page count {len(res)}, total count {len(patent_ids)}")
        
        return res

    async def fetch_urls(
        self,
        urls: list[str],
        region: str = 'global',
        type: str = 'web',
        enable_retry: bool = False,
        detect_attachments: bool = True,
        max_attachments_per_page: int = 5
    ):
        r"""
        Fetch webpage content from URLs.

        Args:
            urls: List of URLs to fetch
            region: Region for search (global, china, etc.)
            type: Content type (web, patent, etc.)
            enable_retry: Whether to retry failed URLs
            detect_attachments: Whether to detect and list attachments found in webpages
            max_attachments_per_page: Maximum number of attachments to list per page

        Returns:
            {url: content_string, ...}
            注：
            - 对于 PDF/Excel/Word 等文件 URL，会使用本地下载并解析，返回解析后的文本
            - 对于普通网页，会检测其中的附件链接并追加列表供 LLM 决定是否下载
        """
        start_time = time.time()

        tasks = []
        crawler = 'firecrawl'
        for url in urls:
            # 检测是否是可直接下载的文件（PDF/Excel/Word等）
            if self._is_downloadable_file(url):
                task = asyncio.create_task(
                    self._fetch_file(url)
                )
                tasks.append((task, url, 'file'))
            elif 'china' == region.lower() or 'patent' == type.lower():
                task = asyncio.create_task(
                    self.jina_client.fetch(url, type.lower())
                )
                crawler = 'jina'
                tasks.append((task, url, 'text'))
            else:
                task = asyncio.create_task(
                    self.firecrawl_client.fetch(url, type.lower())
                )
                tasks.append((task, url, 'text'))

        res = {}
        failed_text_urls = []

        for task, url, content_type in tasks:
            try:
                if content_type == 'file':
                    # 文件类型：使用本地下载器
                    result = await task
                    if result.success:
                        # 返回解析后的文本预览，保持与网页内容相同的格式
                        res[url] = result.text_preview
                        logger.info(f"File downloaded and parsed: {url}, blob_path: {result.blob_path}")
                    else:
                        logger.warning(f"File download failed: {url}, error: {result.error}")
                else:
                    # 文本类型：原有逻辑
                    web_success, web_content = await task
                    if web_success:
                        res[url] = web_content

                        # 检测并追加附件列表
                        if detect_attachments and web_content:
                            attachment_list = self._detect_and_format_attachments(
                                web_content, url, max_attachments_per_page
                            )
                            if attachment_list:
                                res[url] = web_content + attachment_list
                    else:
                        failed_text_urls.append(url)
            except Exception as exc:
                logger.warning(f"{url} fetch failed and meet exception {str(exc)}")
                if content_type == 'text':
                    failed_text_urls.append(url)

        # retry 逻辑（仅对 text 类型的 URL）
        if enable_retry and failed_text_urls:
            res = await self._retry(failed_text_urls, res, crawler)

        end_time = time.time()
        logger.info(f"Fetch link content cost {end_time - start_time}, fetched page count {len(res)}, total count {len(urls)} for region {region} and type {type}")

        return res

    def _detect_and_format_attachments(
        self,
        content: str,
        source_url: str,
        max_count: int = 5
    ) -> str:
        """
        检测网页内容中的附件链接并格式化为列表

        Args:
            content: 网页内容
            source_url: 来源 URL
            max_count: 最多列出的附件数量

        Returns:
            格式化的附件列表字符串，如果没有附件则返回空字符串
        """
        try:
            detected = self.attachment_detector.detect(content, source_url)

            if not detected.direct:
                return ""

            attachments = detected.direct[:max_count]

            lines = [
                "\n\n---",
                "## Available Attachments",
                "The following attachments were detected on this page. "
                "Use **AttachmentDownload** tool to read them if needed:\n"
            ]

            for i, att in enumerate(attachments, 1):
                lines.append(f"{i}. [{att.filename}]({att.url}) - {att.type.value.upper()}")

            logger.info(f"Detected {len(attachments)} attachments in {source_url}")
            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Attachment detection failed for {source_url}: {e}")
            return ""

    async def fetch_url(self, url: str, region: str = 'global', type: str = 'web'):
        start_time = time.time()

        if 'china' == region.lower() or 'patent' == type.lower():
            result = await self.jina_client.fetch(url)
        else:
            result = await self.firecrawl_client.fetch(url)
            
        end_time = time.time()
        logger.info(f"Fetch link content cost {end_time - start_time}")
        return result


async def main():

    crawler = ContentFetcher()

    google_patent = await crawler.fetch_google_patents(patent_ids=['patent/US11734097B1/en'])
    print(google_patent)

if __name__ == "__main__":
    asyncio.run(main())
