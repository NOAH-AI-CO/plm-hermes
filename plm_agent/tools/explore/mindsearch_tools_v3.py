import re
import logging
import asyncio
import time
import requests

from enum import Enum
from datetime import datetime, timedelta
from typing import List, Optional, Union
from pydantic import BaseModel, Field

from config import api_config
from tools.core.base_tool import BaseTool
from utils.finance.financialmodelingprep import FinancialModelinGprep
from utils.finance.mairui import MaiRui
from utils.scholar import PubMedSearchV2
from utils.pubmed_opt.pubmed_search import PubMedSearch
from utils.drug_manuals.drug_manuals_elastic_search import DrugManualsElasticSearch
from utils.guidelines.guidelines_elastic_search import pipeline_guideline_search_with_content
from agent.explore.schema import (
    WebSearchSubject, WebSearchRegion, SearchEngine,
)
from utils.web_search import (
    BaseSearch, GoogleSerperSearch, GoogleSerpapiSearch,
    GoogleProgrammableSearch
)

logger = logging.getLogger(__name__)

class FunctionCallResult(BaseModel):
    name: str = Field(description='Function name, i.e. GeneralSearch.')
    id: str = Field(default=None, description='Model response id.')
    call_id: str = Field(default=None, description='Model response call_id.')
    args: dict = Field(default={}, description='Function call input args.')
    result: Union[dict, list] = Field(description='Function call result dict or list.')


class WebSearchSubQueryInputSchema(BaseModel):
    sub_query: str = Field(description='A refined sub-query derived from the original request for focused web searching.')
    keyword: str = Field(description='The keyword for web search engines.')
    keyword_en: str = Field(description='The English keyword for international/global web search engines.')
    prefer_region: WebSearchRegion = Field(
        default=None,
        description='Indicates whether to prioritize special region search engine. Regardless of the language used in the query, only enable when query contains country or regions. Default is global'
    )


class WebSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    sub_queries: List[WebSearchSubQueryInputSchema] = Field(description='An array containing sub-queries and their respective keywords for web search, must be no more than four. Each sub-query should focus on ONE specific search intent — do not combine multiple unrelated aspects into a single query. Empty when no need web searching.')
    subject: WebSearchSubject = Field(description='Web search subject, i.e. disease, medicine. So we can use different search engine to get better results.')


class GeneralSearch(BaseTool):
    name: str = 'GeneralSearch'
    description: str = 'Performs a web search to retrieve relevant information based on specified keywords.'
    input_schema: BaseModel = WebSearchInputSchema
    strict: bool = True

    # https://serper.dev/
    global_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        top_k=10)
    
    cn_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='cn',
        top_k=10)
    
    jp_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='jp',
        top_k=10)
    
    # TODO SA region should be changed, since arab region countries may prefere use native news
    arab_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='sa',
        top_k=10)

    def _safe_enum_convert(self, result, key, enum_class, default):
        try:
            value = result.get(key, default.value)
            return enum_class(value)
        except ValueError:
            return default
    
    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        sub_queries = kwargs.get("sub_queries", [])

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[]
        )

        tasks = [(self._web_search_task(sub_query), sub_query) for sub_query in sub_queries[:4]]

        for task, sub_query in tasks:
            try:
                search_result = await task
                if search_result is not None:
                    
                    region = self._safe_enum_convert(sub_query, 'prefer_region', WebSearchRegion, WebSearchRegion.GLOBAL)

                    res.result.append({
                        "sub_query": sub_query['sub_query'],
                        "keyword": sub_query['keyword'],
                        "keyword_en": sub_query['keyword_en'],
                        "region": region,
                        "search_type": SearchEngine.MEDICAL,
                        "search_result": search_result
                    })
                    
            except Exception as exc:
                logger.warning(f"[RawQueryWebSearch] query {sub_query['keyword']} failed: {exc}")
        
        yield res

    def _web_search_task(self, sub_query):
        keyword = sub_query.get('keyword', '')
        keyword_en = sub_query.get('keyword_en', '')
        prefer_region = self._safe_enum_convert(sub_query, 'prefer_region', WebSearchRegion, WebSearchRegion.GLOBAL)

        if WebSearchRegion.CHINA == prefer_region:
            task = asyncio.create_task(
                self.cn_search_engine.search(query=keyword)
            )
        elif WebSearchRegion.JAPAN == prefer_region:
            task = asyncio.create_task(
                self.jp_search_engine.search(query=keyword)
            )
        elif WebSearchRegion.ARAB == prefer_region:
            task = asyncio.create_task(
                self.arab_search_engine.search(query=keyword)
            )
        else:
            task = asyncio.create_task(
                self.global_search_engine.search(query=keyword_en)
            )

        return task


class MedicalSearch(GeneralSearch):
    name: str = 'MedicalSearch'
    description: str = 'Performs a medical or biotech search on from authoritative websites to retrieve relevant information based on specified keywords.'
    input_schema: BaseModel = WebSearchInputSchema
    strict: bool = True

    # https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list
    global_search_engine: BaseSearch = GoogleProgrammableSearch(
        api_key=api_config.GOOGLE_PROGRAMMABLE_SEARCH_API_KEY,
        cx=api_config.GOOGLE_PROGRAMMABLE_SEARCH_ENGINE,
        top_k=10
    )
    cn_search_engine: BaseSearch = GoogleProgrammableSearch(
        api_key=api_config.GOOGLE_PROGRAMMABLE_SEARCH_API_KEY,
        cx=api_config.GOOGLE_PROGRAMMABLE_SEARCH_ENGINE,
        region='cn',
        top_k=10)
    
    jp_search_engine: BaseSearch = GoogleProgrammableSearch(
        api_key=api_config.GOOGLE_PROGRAMMABLE_SEARCH_API_KEY,
        cx=api_config.GOOGLE_PROGRAMMABLE_SEARCH_ENGINE,
        region='jp',
        top_k=10)
    # TODO SA region should be changed, since arab region countries may prefere use native news
    arab_search_engine: BaseSearch = GoogleProgrammableSearch(
        api_key=api_config.GOOGLE_PROGRAMMABLE_SEARCH_API_KEY,
        cx=api_config.GOOGLE_PROGRAMMABLE_SEARCH_ENGINE,
        region='sa',
        top_k=10)


class NewsSearch(GeneralSearch):
    name: str = 'NewsSearch'
    description: str = 'Performs a news search to retrieve relevant information based on specified keywords.'
    input_schema: BaseModel = WebSearchInputSchema
    strict: bool = True

    # news search
    global_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        top_k=10)
    
    cn_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='cn',
        top_k=10)
    
    jp_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='jp',
        top_k=10)
    
    # TODO SA region should be changed, since arab region countries may prefere use native news
    arab_search_engine: BaseSearch = GoogleSerperSearch(
        api_key=api_config.GOOGLE_SERPER_API_KEY,
        region='sa',
        top_k=10)

    def _web_search_task(self, sub_query):
        keyword = sub_query.get('keyword', '')
        keyword_en = sub_query.get('keyword_en', '')
        prefer_region = self._safe_enum_convert(sub_query, 'prefer_region', WebSearchRegion, WebSearchRegion.GLOBAL)

        if WebSearchRegion.CHINA == prefer_region:
            task = asyncio.create_task(
                self.cn_search_engine.news(query=keyword)
            )
        elif WebSearchRegion.JAPAN == prefer_region:
            task = asyncio.create_task(
                self.jp_search_engine.news(query=keyword)
            )
        elif WebSearchRegion.ARAB == prefer_region:
            task = asyncio.create_task(
                self.arab_search_engine.news(query=keyword)
            )
        else:
            task = asyncio.create_task(
                self.global_search_engine.news(query=keyword_en)
            )

        return task
    

class GooglePatentLanguage(str, Enum):
    r"""Google patent language. ENGLISH, GERMAN, CHINESE, FRENCH, SPANISH, ARABIC, JAPANESE, KOREAN, PORTUGUESE, RUSSIAN, ITALIAN, DUTCH, SWEDISH, FINNISH, NORWEGIAN, DANISH"""
    ENGLISH = 'ENGLISH'
    GERMAN = 'GERMAN'
    CHINESE = 'CHINESE'
    FRENCH = 'FRENCH'
    SPANISH = 'SPANISH'
    ARABIC = 'ARABIC'
    JAPANESE = 'JAPANESE'
    KOREAN = 'KOREAN'
    PORTUGUESE = 'PORTUGUESE'
    RUSSIAN = 'RUSSIAN'
    ITALIAN = 'ITALIAN'
    DUTCH = 'DUTCH'
    SWEDISH = 'SWEDISH'
    FINNISH = 'FINNISH'
    NORWEGIAN = 'NORWEGIAN'
    DANISH = 'DANISH'


class GooglePatentCountryCode(str, Enum):
    r"""Google patent country code, WO, US"""
    WORLD_INTELLECTUAL_PROPERTY_ORGANIZATION = 'WO'
    UNITED_STATES_OF_AMERICA = 'US'
    EUROPEAN_PATENT_OFFICE = 'EP'
    JAPAN = 'JP'
    REPUBLIC_OF_KOREA = 'KR'
    CHINA = 'CN'
    UNITED_KINGDOM = 'GB'


class GooglePatentSubQueryInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    sub_query: str = Field(description='A refined sub-query derived from the original request for focused google patent searching.')
    keyword: str = Field(description='The keyword for google paten search engines.')
    keyword_en: str = Field(description='The English keyword for international/global google paten search engines.')
    country: List[GooglePatentCountryCode] = Field(
        default=[],
        description='Patent countries.'
    )
    before: str = Field(
        default=None,
        description='The maximum date of the results. The format of this field is type:YYYYMMDD. type can be one of priority, filing, and publication. E.g. priority:20221231, publication:20230101'
    )
    after: str = Field(
        default=None,
        description='The maximum date of the results. The format of this field is type:YYYYMMDD. type can be one of priority, filing, and publication. E.g. priority:20221231, publication:20230101'
    )
    language: List[GooglePatentLanguage] = Field(
        default=[],
        description='The language of the patent search. Default is ENGLISH.'
    )
    page: int = Field(
        default=1,
        description='Pagination number, start from 1.'
    )


class GooglePatentInputSchema(BaseModel):
    sub_queries: List[GooglePatentSubQueryInputSchema] = Field(description='An array containing sub-queries and their respective keywords for google patent search, must be no more than four. Empty when no need web searching.')

class PatentSearch(GeneralSearch):
    name: str = 'PatentSearch'
    description: str = 'Performs a patent search to retrieve relevant information based on specified keywords.'
    input_schema: BaseModel = GooglePatentInputSchema
    strict: bool = True

    # news search
    patent_search_engine: BaseSearch = GoogleSerpapiSearch(
        api_key=api_config.GOOGLE_SERPAPI_API_KEY,
        top_k=10)

    def _web_search_task(self, sub_query):
        keyword_en = sub_query.get('keyword_en', '')
        country = sub_query.get('country', [])
        before = sub_query.get('before', '')
        after = sub_query.get('after', '')
        language = sub_query.get('language', [])

        return asyncio.create_task(
            self.patent_search_engine.patents(query=keyword_en, country=country, before=before, after=after, language=language)
        )

class PubMedArticlesSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    pubmed_query: str = Field(description="A PubMed medicine Boolean query, i.e. '(differentiated[Title/Abstract] OR thyroid[Title/Abstract])'. If the value is empty or null, there won't trigger a PubMed search.")


class PubMedArticlesSearch(BaseTool):
    name: str = 'PubMedArticlesSearch'
    description: str = 'Retrieves articles for the given PubMed Boolean query.'
    input_schema: BaseModel = PubMedArticlesSearchInputSchema
    strict: bool = True
    pubmed_client: Optional[PubMedSearchV2] = None    

    def __init__(self, **data):
        super().__init__(**data)
        if self.pubmed_client is None:
            self.pubmed_client = PubMedSearchV2()

    async def run(self, **kwargs):
        start_time = time.time()
        
        context = kwargs.pop('_context', None)
        query = kwargs.get('pubmed_query', '')
        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[]
        )

        if query == '':
            yield res
            return

        # Call PubMed Entrez search
        try:
            # query PubMed articles
            article_results = await asyncio.wait_for(
                self.pubmed_client.esearch(query=query),
                timeout=30.0  # 20 seconds timeout
            )

            # fetch PubMed articles abstract
            if len(article_results.get('uids', [])) == 0:
                yield res
                return

            ids = ",".join(article_results.get('uids', []))
            abstracts = await asyncio.wait_for(
                self.pubmed_client.efetch(ids),
                timeout=30.0  # 20 seconds timeout
            )
            
            # parse PubMed articles abstract content
            final_results = []
            abstract_list = abstracts.split("\n\n\n")
            for index, abstract in enumerate(abstract_list):
                abstract = abstract.replace('\n', '')
                abstract = re.sub(r'^\d+\.\s*', '', abstract)
                uid = article_results['uids'][index]
                if uid in article_results:
                    article_result = article_results[uid]
                    article_result['summary'] = abstract
                    final_results.append(article_result)
        except asyncio.TimeoutError:
            logger.warning(f"[PubmedSearch] query {query} timed out after 20 seconds")
            final_results = []
        except Exception as exc:
            logger.warning(f"[PubmedSearch] query {query} failed, exception: {exc}")
            final_results = []
        finally:
            # Ensure we close the session
            await self.pubmed_client.close()
            
        end_time = time.time()
        logger.info(f"PubMed search engine query time cost {end_time - start_time}s get {len(final_results)}")
        
        res.result = final_results
        yield res

    async def efetch(self, ids: str, db: str = "pubmed"):
        return await self.pubmed_client.efetch(ids, db)


class DrugManualSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    drug_names_query: str = Field(
        description='Comma-separated drug names to search for official drug manuals (e.g. "阿司匹林, 布洛芬" or "aspirin, ibuprofen"). Supports Chinese and English names.'
    )


# Max length for `text` field in each result to avoid huge tokens (manual content can be very long)
DRUG_MANUAL_TEXT_TRUNCATE = 8000


class DrugManualSearch(BaseTool):
    name: str = 'DrugManualSearch'
    description: str = 'Searches official drug manuals (药品说明书) by drug names; returns indications, dosage, contraindications, etc. Input: comma-separated drug names in Chinese or English.'
    input_schema: BaseModel = DrugManualSearchInputSchema
    strict: bool = True

    async def run(self, **kwargs):
        context = kwargs.pop('_context', None)
        query = kwargs.get('drug_names_query', '').strip()
        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[],
        )
        if not query:
            yield res
            return
        try:
            client = DrugManualsElasticSearch()
            results, count, _ = await client.search_by_drugnames(raw_query=query, size=1)
            # Build serializable list; truncate long `text` to avoid token overflow
            out = []
            for r in results or []:
                item = dict(r)
                text = item.get('text')
                if isinstance(text, str) and len(text) > DRUG_MANUAL_TEXT_TRUNCATE:
                    item['text'] = text[:DRUG_MANUAL_TEXT_TRUNCATE] + '...[truncated]'
                out.append(item)
            res.result = out
        except Exception as exc:
            logger.warning('[DrugManualSearch] query %s failed: %s', query, exc)
            res.result = []
        yield res


class ClinicalGuidelineSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    guideline_query: str = Field(
        description='Natural language query for clinical guidelines. **IMPORTANT: Must be in Chinese** (e.g. disease, indication, guideline name). Examples: "HR+HER2-乳腺癌", "肺癌一线治疗", "CSCO 非小细胞肺癌", "头孢菌素安全监测 肾功能损害".'
    )


class ClinicalGuidelineSearch(BaseTool):
    name: str = 'ClinicalGuidelineSearch'
    description: str = 'Searches clinical guidelines (e.g. CSCO, NCCN) by condition or topic; returns relevant section content. Input: guideline_query **in Chinese** (e.g. "HR+HER2-乳腺癌", "肺癌诊疗", "头孢菌素用药安全").'
    input_schema: BaseModel = ClinicalGuidelineSearchInputSchema
    strict: bool = True

    async def run(self, **kwargs):
        context = kwargs.pop('_context', None)
        query = kwargs.get('guideline_query', '').strip()
        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[],
        )
        if not query:
            yield res
            return
        try:
            result = await pipeline_guideline_search_with_content(query)
            res.result = result
        except Exception as exc:
            logger.warning('[ClinicalGuidelineSearch] query %s failed: %s', query, exc)
            res.result = []
        yield res


class PubMedArticlesLocalSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    pubmed_query: str = Field(description='A vector search query **in English** without OR, AND operators, i.e. differentiated thyroid RVS.')
    years: List[int] = Field(default=[], description='Article published time, i.e. 2024, 2025, empty is the latest two years.')


class PubMedArticlesLocalSearch(BaseTool):
    name: str = 'PubMedArticlesLocalSearch'
    description: str = 'Retrieves articles title and abstract for the give query.'
    input_schema: BaseModel = PubMedArticlesLocalSearchInputSchema
    strict: bool = True
    pubmed_search: PubMedSearch = PubMedSearch()

    async def run(self, **kwargs):
        start_time = time.time()

        context = kwargs.pop('_context', None)
        query = kwargs.get('pubmed_query', '')
        years = kwargs.get('years', [])
        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[]
        )

        if query == '':
            yield res
            return

        results = await self.pubmed_search.hybrid_search(query=query, years=years)

        end_time = time.time()
        logger.info(f"PubMed search engine query time cost {end_time - start_time}s get {len(results)}")
        
        res.result = results
        yield res


class SymbolInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    symbol: str = Field(
        description='Ticker symbol (e.g., "AAPL").'
    )

class StockTimeSpaneQueryInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    symbol: str = Field(
        description='Ticker symbol (e.g., "AAPL").'
    )
    date_from: str = Field(
        description='Start date in YYYY-MM-DD format (e.g., "2023-12-01"). '
                    'If omitted, defaults to six months ago.'
    )
    date_to: str = Field(
        description='End date in YYYY-MM-DD format (e.g., "2024-01-01"). '
                    'If omitted, defaults to today.'
    )


class StockHistoricalPriceQuery(BaseTool):
    name: str = 'StockHistoricalPriceQuery'
    description: str = 'Fetch stock history price by symbol and date spane'
    input_schema: BaseModel = StockTimeSpaneQueryInputSchema
    strict: bool = True   

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    def _format_symbol(self, symbol: str) -> str:
        # For HK symbol should like 06855.HK -> 6855.HK, not starts with 0
        if symbol.endswith('.HK'):
            # Remove leading zeros from the numeric part
            num_part = symbol.split('.')[0].lstrip('0')
            if not num_part:  # If all zeros, keep one zero
                num_part = '0'
            return f"{num_part}.HK"
        return symbol

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')
        date_from = kwargs.get('date_from', (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'))
        date_to = kwargs.get('date_to',  datetime.now().strftime('%Y-%m-%d'))

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={},
        )

        if symbol != '':
            loop = asyncio.get_event_loop()
            if date_from != '' and date_to != '':
                res.result = await loop.run_in_executor(None, lambda: self.fmp_client.daily_char_eod(symbol=symbol, date_from=date_from, date_to=date_to))
            else:
                res.result = await loop.run_in_executor(None, lambda: self.fmp_client.daily_char_eod(symbol=symbol))

        yield res


class StockNewsSearch(BaseTool):
    name: str = 'StockNewsSearch'
    description: str = 'Query stock news by symbol and date spane'
    input_schema: BaseModel = StockTimeSpaneQueryInputSchema
    strict: bool = True   

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')
        date_from = kwargs.get('date_from', (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'))
        date_to = kwargs.get('date_to', datetime.now().strftime('%Y-%m-%d'))

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[]
        )

        if symbol != '':
            loop = asyncio.get_event_loop()
            if date_from != '' and date_to != '':
                res.result = await loop.run_in_executor(None, lambda: self.fmp_client.stock_news(tickers=[symbol], date_from=date_from, date_to=date_to))
            else:
                res.result = await loop.run_in_executor(None, lambda: self.fmp_client.stock_news(tickers=[symbol]))

        yield res


class CompanyPressReleasesNewsQuery(BaseTool):
    name: str = 'CompanyPressReleasesNewsQuery'
    description: str = 'Query company press releases news by symbol and date spane'
    input_schema: BaseModel = StockTimeSpaneQueryInputSchema
    strict: bool = True   

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={},
        )

        if symbol != '':
            loop = asyncio.get_event_loop()
            res.result = await loop.run_in_executor(None, lambda: self.fmp_client.press_releases(symbol=symbol))
    
        yield res


class CompanyInfoQuery(BaseTool):
    name: str = 'CompanyInfoQuery'
    description: str = 'Company detail information, i.e. market place, industry, exchange, current price.'
    input_schema: BaseModel = SymbolInputSchema

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={},
        )

        if symbol != '':
            loop = asyncio.get_event_loop()
            res.result = await loop.run_in_executor(None, lambda: self.fmp_client.company_profile(symbol=symbol))

        yield res


class StockGeneralSearchInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    query: str = Field(
        description='Company name in English or stock symbol, e.g. APPLE or Apple Inc. would fetch AAPL. 6855.HK would fetch Ascentage Pharma Group International.'
    )


class StockGeneralSearch(BaseTool):
    name: str = 'StockGeneralSearch'
    description: str = 'General search for symbol or company name in English; result contains symbol, name, currency, stock exchange. Use when you need to find the correct stock symbol by company name.'
    input_schema: BaseModel = StockGeneralSearchInputSchema
    strict: bool = True

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        query = kwargs.get('query', '')

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result=[],
        )

        if query != '':
            loop = asyncio.get_event_loop()
            res.result = await loop.run_in_executor(None, lambda: self.fmp_client.general_search(query=query))

        yield res


class FinancialStatementsPeriod(str, Enum):
    r"""Financial statements period."""
    ANNUAL = 'annual'
    QUARTER = 'quarter'
    

class FinancialStatementsInputSchema(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    symbol: str = Field(
        description='Ticker symbol (e.g., "AAPL").'
    )
    period: FinancialStatementsPeriod = Field(
        default=FinancialStatementsPeriod.ANNUAL,
        description='Financial statements period, only support annual and quarter. Default is annual'
    )
    limit: int = Field(
        default=1,
        description='Amount of financial statements, default is 1.'
    )


class FinancialStatements(BaseTool):
    name: str = 'FinancialStatements'
    description: str = "Query company's financial statements by stock symbol, support annual and quarter"
    input_schema: BaseModel = FinancialStatementsInputSchema
    strict: bool = True

    fmp_client: FinancialModelinGprep = FinancialModelinGprep()

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={},
        )

        if symbol == '':
            yield res
            return

        period = kwargs.get('period', FinancialStatementsPeriod.ANNUAL.value)
        limit = kwargs.get('limit', 1)

        loop = asyncio.get_event_loop()
        fincacial_statements = await loop.run_in_executor(None, lambda: self.fmp_client.financial_statements_as_reported(symbol=symbol, period=period, limit=limit))

        # add special case
        stock_price = await loop.run_in_executor(None, lambda: self.fmp_client.daily_char_eod(symbol=symbol))
        if stock_price:
            historical = stock_price.get('historical', [])
            if len(historical) > 0:
                close_price = historical[-1].get('close', None)
                if close_price is not None and fincacial_statements:
                    commonstocksharesoutstanding = fincacial_statements[0].get('commonstocksharesoutstanding', 0)
                    fincacial_statements[0]['marketcapitalization'] = commonstocksharesoutstanding * close_price
        
        res.result = stock_price

        yield res


class ChinaCompanyFinancialStatements(BaseModel):
    explanation: str = Field(description="The step by step explanation of why triggering this query.")
    symbol: str = Field(
        description='Ticker symbol (e.g., "0000001.SZ", "600276.SS").'
    )
    date_from: str = Field(
        description='Start date in YYYY-MM-DD format (e.g., "2023-12-01"). '
                    'If omitted, defaults to six months ago.'
    )
    date_to: str = Field(
        description='End date in YYYY-MM-DD format (e.g., "2024-01-01"). '
                    'If omitted, defaults to today.'
    )


class ChinaCompanyFinancialStatements(BaseTool):
    name: str = 'ChinaCompanyFinancialStatements'
    description: str = "Query China National Stock Exchange company's financial statements, i.e. 0000001.SZ"
    input_schema: BaseModel = ChinaCompanyFinancialStatements

    mairui: MaiRui = MaiRui()

    def _format_symbol(
        self,
        symbol: str
    ):
        # Format Chinese stock symbol
        if symbol.lower().endswith('ss'):
            symbol = symbol.split('.')[0] + ".SH"
        return symbol

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        symbol = kwargs.get('symbol', '')
        symbol = self._format_symbol(symbol)

        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={},
        )

        if symbol == '':
            yield res
            return        

        date_from = kwargs.get('date_from', '')
        date_to = kwargs.get('date_to', '')
        
        # Convert date format from YYYY-MM-DD to YYYYMMDD
        if date_from:
            date_from = date_from.replace('-', '')
        if date_to:
            date_to = date_to.replace('-', '')

        loop = asyncio.get_event_loop()
        res.result = await loop.run_in_executor(None, lambda: self.mairui.financial_statements(symbol=symbol, date_from=date_from, date_to=date_to))

        yield res


class ContentReaderInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )
    citation_ids: List[int] = Field(
        description='Citation id list.'
    )


class ContentReader(BaseTool):
    name: str = 'ContentReader'
    description: str = 'Content reader which can load the webpage content, articles or other reference.'
    input_schema: BaseModel = ContentReaderInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={
                'citation_ids': kwargs.get('citation_ids', [])
            }
        )


class DocumentSearchInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )
    query: str = Field(
        description='Retrieval query in natural language could be used as vector searching.'
    )
    keywords: List[str] = Field(
        description='Keywords list for Boolean searching.'
    )
    citation_ids: List[int] = Field(
        default=[],
        description=('Restrict search to these citation IDs (specific documents). Leave empty to search the entire document corpus.'
        ),
    )


class DocumentSearch(BaseTool):
    name: str = 'DocumentSearch'
    description: str = 'Document search which can search long document or multiple documents by using hybrid search (both vector and keyword) engine content by user query.'
    input_schema: BaseModel = DocumentSearchInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={
                'citation_ids': kwargs.get('citation_ids', []),
                'keywords': kwargs.get('keywords', []),
                'query': kwargs.get('query', ''),
            }
        )


class ArticleDetailLevel(str, Enum):
    r"""Financial statements period."""
    HIGH = 'high'
    BALANCED = 'balanced'
    DETAILED = 'detailed'


class ArticleReaderInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )

    user_goal: str = Field(
        description=(
            "The user's concrete purpose for reading the paper, e.g. 'reproduce the training details in the paper','compare the baselines used in recommender systems','understand the loss function and symbol definitions of this method'. "
        )
    )

    focus_aspects: List[str] = Field(
        description=(
            "Key aspects of the article to focus on. Each item should be a short phrase, such as 'problem definition', 'main contributions', 'method overview', 'model architecture', 'loss functions and symbol definitions', 'datasets and preprocessing', 'training hyperparameters', 'evaluation metrics', 'ablation studies', 'limitations and future work'. Choose only what is relevant to the user's goal."
        )
    )

    detail_level: ArticleDetailLevel = Field(
        default=ArticleDetailLevel.HIGH,
        description=(
            "How detailed the extraction should be: 'high' for a brief overview; 'balanced' for a normal level of detail; 'detailed' for maximum retention of original details and minimal summarization."
        )
    )

    citation_ids: List[int] = Field(
        description=(
            "List of citation IDs of the article(s) to be read. These IDs should match the citation system used in the current context."
        )
    )


class DocumentReader(BaseTool):
    name: str = 'DocumentReader'
    description: str = 'Document reader which can load the document content by user query.'
    input_schema: BaseModel = ContentReaderInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={
                'citation_ids': kwargs.get('citation_ids', [])
            }
        )    


class Finished(BaseTool):
    name: str = 'Finished'
    description: str = 'Finsihment notice function.'
    input_schema: BaseModel = ContentReaderInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={
                'citation_ids': kwargs.get('citation_ids', [])
            }
        )


class DocumentSearchFinished(BaseTool):
    name: str = 'DocumentSearchFinished'
    description: str = 'Finsihment notice function.'
    input_schema: BaseModel = ArticleReaderInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={
                'citation_ids': kwargs.get('citation_ids', [])
            }
        )


class ClinicalTrailSearchInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )

    nctid: List[str] = Field(
        description='NCTID list, i.e. NCT00090233, NCT00090234.'
    )


class ClinicalTrailSearch(BaseTool):
    name: str = 'ClinicalTrailSearch'
    description: str = 'Clinical trail search which can search clinical trail detail from "clinicaltrials.gov" by user query.'
    input_schema: BaseModel = ClinicalTrailSearchInputSchema
    retry: int = 2
    timeout: int = 2
    data_access_version: str = 'v1'

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)

        # call data access api to get clinical trail data
        url = f"{api_config.NOAH_DATA_ACCESS_HOST}/api/{self.data_access_version}/items/clinical_trial/"

        data_json = {
            'nctid': kwargs.get('nctid', [])
        }
        logger.info(f"Try to search clinical trail data from 'clinicaltrials.gov' by user query: {data_json}")
        res = FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={}
        )

        # Check if the data_json is valid
        if not data_json or all(not v for v in data_json.values()):
            yield res
            return

        response = None
        loop = asyncio.get_event_loop()
        for _ in range(self.retry):
            try:
                response = await loop.run_in_executor(None, lambda: requests.post(url, json=data_json, timeout=self.timeout))
                break
            except Exception as e:
                logger.warning(f"Request failed (retry): {e}")
        else:
            err_msg = f"Request failed after {self.retry} attempt(s). No data returned."
            logger.info(err_msg)
            res.result = {
                "code": 500,
                "message": err_msg,
            }
            yield res
            return
        
        try:
            payload = response.json()
            logger.info(f"[ClinicalTrailSearch] response: {payload}")
            if (
                self.data_access_version == 'v2'
                and isinstance(payload, dict)
                and 'data' in payload
            ):
                if payload.get('code', 0) != 0:
                    logger.warning(
                        f"data_access v2 error: code={payload.get('code')} msg={payload.get('message')}"
                    )
                payload = payload.get('data') or {}
            res.result = payload
        except:
            pass

        yield res



class ImageGenerationInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )
    image_prompt: str = Field(
        description='The image prompt and labels preferred in English.'
    )
    image_name: str = Field(
        description='The short meaningful name of the image.'
    )
    related_image_urls: List[str] = Field(
        default=[],
        description='The related image urls from previous context to be used for image generation, e.g. reference:![cat](https://example.com/cat.jpg "a little cat"), then related_image_urls should be ["https://example.com/cat.jpg"].'
    )


class ImageGeneration(BaseTool):
    name: str = 'ImageGeneration'
    description: str = 'Image generation which can generate image by user query.'
    input_schema: BaseModel = ImageGenerationInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)

        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={}
        )


class ImageEditInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )
    image_prompt: str = Field(
        description='The editing instruction describing what changes to apply, preferred in English.'
    )
    image_name: str = Field(
        description='The short meaningful name of the output image, e.g. cat-black-and-white.png'
    )
    source_image_url: str = Field(
        default='',
        description='The url of the image to edit from previous context, e.g. reference:![cat](https://example.com/cat.jpg "a little cat"), then source_image_url should be "https://example.com/cat.jpg".'
    )


class ImageEdit(BaseTool):
    name: str = 'ImageEdit'
    description: str = 'Edit an existing image based on user instructions, such as changing style, adding or removing elements.'
    input_schema: BaseModel = ImageEditInputSchema

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)

        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={}
        )


class KnowledgeBasePreviewInputSchema(BaseModel):
    explanation: str = Field(
        description="The step by step explanation of why triggering this query."
    )
    knowledge_base_id: str = Field(
        description='The knowledge base id.'
    )
    page: int = Field(
        default=1,
        description='The page number of the knowledge base.'
    )
    page_size: int = Field(
        default=30,
        description='The page size of the knowledge base.'
    )


class KnowledgeBasePreview(BaseTool):
    name: str = 'KnowledgeBasePreview'
    description: str = 'Knowledge base preview which can preview the knowledge base content by user query.'
    input_schema: BaseModel = KnowledgeBasePreviewInputSchema
    strict: bool = True

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)
        
        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            name=self.name,
            args=kwargs,
            result={}
        )
