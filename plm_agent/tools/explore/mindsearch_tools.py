import re
import logging
import asyncio
import time
from enum import Enum

from typing import List, Dict, Tuple, Any, Optional
from pydantic import BaseModel, Field

from agent.explore.schema import WebSearchSubject, WebSearchRegion, SearchEngine
from tools.core.base_tool import BaseTool
from utils.web_search import (BaseSearch, BingSearch, BingCustomSearch, GoogleSerperSearch)
from utils.scholar import PubMedSearch

from config import api_config

logger = logging.getLogger(__name__)


class RegionWebSearchSubQueryInputSchema(BaseModel):
    sub_query: str = Field(description='A refined sub-query derived from the original request for focused web searching.')
    keyword: str = Field(description='The keyword for web search engines.')
    keyword_en: str = Field(description='The English keyword for international/global web search engines.')
    prefer_region: WebSearchRegion = Field(
        default=None,
        description='Indicates whether to prioritize special region search engine. Regardless of the language used in the query, only enable when query contains country or regions. Default is global'
    )
    prefer_engine: SearchEngine = Field(
        default=None,
        description='Indicates which search engine needed to use. Default is websearch.'
    )


class RegionWebSearchInputSchema(BaseModel):
    need_websearch: bool = Field(description='Indicates whether web search is required to enhance the answer. True will do the web search, false or not.')
    thought_process: str = Field(description='The explanation of why web search is or not necessary, or how the query is split into sub-queries for better search results.')
    sub_queries: List[RegionWebSearchSubQueryInputSchema] = Field(description='An array containing sub-queries and their respective keywords for web search. Empty when no need web searching.')
    subject: WebSearchSubject = Field(description='Web search subject, i.e. disease, medicine. So we can use different search engine to get better results.')


class RegionWebSearch(BaseTool):
    name: str = 'RegionWebSearch'
    description: str = 'Performs a web search to retrieve relevant information based on specified keywords.'
    input_schema: BaseModel = RegionWebSearchInputSchema
    strict: bool = True

    # https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/reference/market-codes
    global_search_engine: BaseSearch = BingSearch(api_key=api_config.BING_SEARCH_SUBSCRIPTION_KEY,
                                                  region='en-US',
                                                  top_k=8)
    
    cn_search_engine: BaseSearch = BingSearch(api_key=api_config.BING_SEARCH_SUBSCRIPTION_KEY,
                                              region='zh-CN',
                                              top_k=8)
    
    jp_search_engine: BaseSearch = BingSearch(api_key=api_config.BING_SEARCH_SUBSCRIPTION_KEY,
                                              region='ja-JP',
                                              top_k=8)
    # TODO SA region should be changed, since arab region countries may prefere use native news
    arab_search_engine: BaseSearch = BingSearch(api_key=api_config.BING_SEARCH_SUBSCRIPTION_KEY,
                                                region='SA',
                                                top_k=8)
    
    # news search
    news_search_engine: BaseSearch = GoogleSerperSearch(api_key=api_config.GOOGLE_SERPER_API_KEY,
                                                top_k=8)
    
    # patent search
    patent_search_engine: BaseSearch = GoogleSerperSearch(api_key=api_config.GOOGLE_SERPER_API_KEY,
                                                         top_k=12)
    
    
    def _safe_enum_convert(self, result, key, enum_class, default):
        try:
            value = result.get(key, default.value)
            return enum_class(value)
        except ValueError:
            return default
    
    async def run(self, **kwarg):
        need_websearch = kwarg.get("need_websearch", True)
        thought_process = kwarg.get("thought_process", "")
        sub_queries = kwarg.get("sub_queries", [])
        subject = self._safe_enum_convert(kwarg, "subject", WebSearchSubject, WebSearchSubject.UNKNOWN)

        res = {
            "need_websearch": need_websearch,
            "thought_process": thought_process,
            "subject": subject,
            "sub_queries": []
        }

        if not need_websearch or len(sub_queries) == 0:
            yield res
            return

        tasks = [(self._web_search_task(sub_query), sub_query) for sub_query in sub_queries]

        for task, sub_query in tasks:
            try:
                search_result = await task
                if search_result is not None:
                    
                    region = self._safe_enum_convert(sub_query, 'prefer_region', WebSearchRegion, WebSearchRegion.GLOBAL)
                    search_type = self._safe_enum_convert(sub_query, 'prefer_engine', SearchEngine, SearchEngine.WEB)

                    res['sub_queries'].append({
                        "sub_query": sub_query['sub_query'],
                        "key_word": sub_query['keyword'],
                        "region": region,
                        "search_type": search_type,
                        "search_result": search_result
                        })
                    
            except Exception as exc:
                logger.warning(f"[RawQueryWebSearch] {self.searcher_engine.__class__.__name__} query {sub_query['keyword']} failed: {exc}")
        yield res

    def _web_search_task(self, sub_query):
        keyword = sub_query.get('keyword', '')
        keyword_en = sub_query.get('keyword_en', '')
        prefer_region = self._safe_enum_convert(sub_query, 'prefer_region', WebSearchRegion, WebSearchRegion.GLOBAL)
        prefer_engine = self._safe_enum_convert(sub_query, 'prefer_engine', SearchEngine, SearchEngine.WEB)

        if SearchEngine.NEWS == prefer_engine:
            # remove news or latest news in the keyword
            keyword_en = re.sub(r'\b(latest\s+)?news\b', '', keyword_en, flags=re.IGNORECASE).strip()

            if WebSearchRegion.GLOBAL != prefer_region:
                task = asyncio.create_task(
                    self.news_search_engine.news(query=keyword)
                )
            else:
                task = asyncio.create_task(
                    self.news_search_engine.news(query=keyword_en)
                )
        elif SearchEngine.PATENT == prefer_engine:
            task = asyncio.create_task(
                self.patent_search_engine.search(query=keyword)
            )
        else:
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


# Official query
class BiotechOfiicialWebSearch(RegionWebSearch):
    name: str = 'BiotechOfiicialWebSearch'
    description: str = 'Performs a web search to retrieve relevant information based on specified keywords.'

    search_engine: BaseSearch = BingCustomSearch(api_key=api_config.BING_CUSTOMER_SEARCH_SUBSCRIPTION_KEY,
                                                        custom_config_id=api_config.BING_CUSTOMER_SEARCH_CONFIGURATION_ID,
                                                        region='en-US',
                                                        top_k=10)

    #cn_search_engine: BaseSearch = BingCustomSearch(api_key=api_config.BING_CUSTOMER_SEARCH_SUBSCRIPTION_KEY,
    #                                                    custom_config_id=api_config.BING_CUSTOMER_SEARCH_CONFIGURATION_ID,
    #                                                    region='zh-CN',
    #                                                    top_k=10)
    cn_search_engine: BaseSearch = GoogleSerperSearch(api_key=api_config.GOOGLE_SERPER_API_KEY,
                                                top_k=8)

    jp_search_engine: BaseSearch = BingCustomSearch(api_key=api_config.BING_CUSTOMER_SEARCH_SUBSCRIPTION_KEY,
                                                        custom_config_id=api_config.BING_CUSTOMER_SEARCH_CONFIGURATION_ID,
                                                        region='ja-JP',
                                                        top_k=10)
    
    arab_search_engine: BaseSearch = BingCustomSearch(api_key=api_config.BING_CUSTOMER_SEARCH_SUBSCRIPTION_KEY,
                                                        custom_config_id=api_config.BING_CUSTOMER_SEARCH_CONFIGURATION_ID,
                                                        region='SA',
                                                        top_k=10)
    
    news_search_engine: BaseSearch = GoogleSerperSearch(api_key=api_config.GOOGLE_SERPER_API_KEY,
                                                top_k=8)
    
    pattern_search_engine: BaseSearch = GoogleSerperSearch(api_key=api_config.GOOGLE_SERPER_API_KEY,
                                                top_k=12)


# Web search follow up question

class MindSearchFollowupQuestonsInputSchema(BaseModel):
    followup_questions: list[str] = Field(description="Follow up questions of the input", )
    

class MindSearchFollowupQuestons(BaseTool):
    name: str = 'MindSearchFollowupQuestons'
    description: str = 'Retrieves relevant response to make up current response byt a few following up questions.'
    input_schema: BaseModel = MindSearchFollowupQuestonsInputSchema
    strict: bool = True

    async def run(self, followup_questions):
        yield followup_questions

# Pubmed search.

class PubmedSearchInputSchema(BaseModel):
    thought_process: str = Field(description='The explanation of the necessity (or lack thereof) of a PubMed search, or provide a logical analysis of the query rewrite.')
    pubmed_query: str = Field(description="A PubMed medicine Boolean query, i.e. '(differentiated[Title/Abstract] OR thyroid[Title/Abstract])'. If the value is empty or null, there won't trigger a PubMed search.")


class PubmedSearch(BaseTool):
    name: str = 'PubmedSearch'
    description: str = 'Retrieves articles for the given PubMed Boolean query.'
    input_schema: BaseModel = PubmedSearchInputSchema
    strict: bool = True
    pubmed_client: Optional[PubMedSearch] = None    

    def __init__(self, **data):
        super().__init__(**data)
        if self.pubmed_client is None:
            self.pubmed_client = PubMedSearch()

    async def run(self, **kwarg):
        logger.info(f"[Pubmed search] rewrite result is {kwarg}")

        start_time = time.time()

        query = kwarg.get('pubmed_query', '')
        thought_process = kwarg.get('thought_process', '')
        res = {
            'pubmed_query': query,
            'thought_process': thought_process,
            'query_results': []
        }

        if query == '':
            yield res
            return

        # Call PubMed Entrez search
        try:
            query_results = await asyncio.wait_for(
                self.pubmed_client.esearch(query=query),
                timeout=20.0  # 30 seconds timeout
            )
        except Exception as exc:
            logger.warn(f"[PubmedSearch] {self.searcher_engine.__class__.__name__} query {query} failed, exception {exc}")
            query_results = []
        end_time = time.time()
        
        res['query_results'] = query_results
        logger.info(f"PubMed search engine query time cost {end_time - start_time}s get {len(query_results)}")
        yield res

    async def efetch(self, ids: str, db: str = "pubmed"):
        return await self.pubmed_client.efetch(ids, db)
    

class PubMedRecommendArticlesInputSchema(BaseModel):
    articles_id: List[int] = Field(default=[], description='Recommended article IDs. This field may be empty if no recommendations are available.')


class PubMedRecommendArticles(BaseTool):
    name: str = 'PubMedRecommendArticles'
    description: str = 'Download and read recommended articles'
    input_schema: BaseModel = PubMedRecommendArticlesInputSchema
    strict: bool = True

    async def run(self, articles_id):
        yield articles_id


class MindSearchPreTemplateInputSchema(BaseModel):
    template_id: Optional[int] = Field(
        default=None,
        description='Pre template id for similar questions.')
    

class MindSearchPreTemplate(BaseTool):
    name: str = 'MindSearchPreTemplate'
    description: str = "Find similar questions' template id"
    input_schema: BaseModel = MindSearchPreTemplateInputSchema
    strict: bool = True
    
    async def run(self, template_id):
        yield template_id


class PICOTRewriteInputSchema(BaseModel):
    p: Optional[list[str]] = Field(description="(Patient/Population/Problem): Who is the patient or population? Consider age, gender, medical condition, or risk factors.")
    i: Optional[list[str]] = Field(description="(Intervention): What is the intervention or treatment under consideration? This could be a drug, therapy, diagnostic test, or lifestyle modification.")
    c: Optional[list[str]] = Field(description="(Comparison): What is the alternative intervention (if applicable)? It could be a placebo, standard treatment, or another therapy.")
    o: Optional[list[str]] = Field(description="(Outcome): What are the measurable clinical outcomes of interest? This could include improvement, mortality, side effects, or quality of life.")
    t: Optional[str] = Field(description='(Time): What is the researchs time spane? It could be a time format "YYYY/MM/DD" with type:, Completion, Create, Entry, MeSH, Modification, Publication, i.e. "1988/07/30"[Date - Create].')


class PubMedPICOTRewrite(BaseTool):
    name: str = 'PubMedPICOTRewrite'
    description: str = 'Retrieves articles for the given PubMed Boolean query which is rewrited by the raw query followed the PICOT rule.'
    input_schema: BaseModel = PICOTRewriteInputSchema
    strict: bool = True
    pubmed_client: Optional[PubMedSearch] = None    

    def __init__(self, **data):
        super().__init__(**data)
        if self.pubmed_client is None:
            self.pubmed_client = PubMedSearch()

    def _pico_format_query(self, index: str, meta: dict) -> str:
        return " OR ".join([
            f"({item}[Title/Abstract])"
            for item in meta.get(index, [])
        ])

    def _check_t(self, t: str) -> str:
        # check t is valid
        # i.e. "1988/07/30"[Date - Create]:"2024/02/24"[Date - Create]
        pattern = r'"\d{4}/\d{2}/\d{2}"\[Date - [Completion|Create|Entry|MeSH|Modification|Publication]\]:"\d{4}/\d{2}/\d{2}"\[Date - [Completion|Create|Entry|MeSH|Modification|Publication]\]'
        if re.match(pattern, t):
            return t
        return ''

    # https://jefflibraries.libguides.com/PICO/FramingASearch
    async def run(self, **kwarg):
        logger.info(f"[PICOT] rewrite result is {kwarg}")

        p = self._pico_format_query('p', kwarg)
        i = self._pico_format_query('i', kwarg)
        c = self._pico_format_query('c', kwarg)
        o = self._pico_format_query('o', kwarg)
        t = self._check_t(kwarg.get('t', ''))
        
        query = " AND ".join([
            item for item in [p, i, c, o, t] if item != ''
        ])

        res = {
            'pubmed_query': query,
            'query_results': []
        }

        if not res.get('pubmed_query', ''):
            yield res
            return
            
        res['query_results'] = await self.pubmed_client.esearch(query=res['pubmed_query'])
        logger.info(f"PubMed query {query}, search resluts {len(res['query_results'])}")
        yield res

    async def efetch(self, ids: str, db: str = "pubmed"):
        return await self.pubmed_client.efetch(ids, db)
