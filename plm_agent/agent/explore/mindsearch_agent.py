import re
import copy
import time
import json
import asyncio
import logging


from urllib.parse import quote
from typing import List, Callable, Any
from datetime import datetime
from openai.types.chat import ChatCompletionMessage
from utils.citation.citation_generator import generate_citation

import agent.explore.constants as constants
from agent.core.preset import AgentPreset
from agent.explore.schema import (MindSearchResponse, SearchNode, SearchType, WebSearchLink,
                                  ProcessingType, WebSearchSubject, WebSearchRegion,
                                  SearchEngine)
from agent.explore.mindsearch_prompt import (gpt_query_rewrite_sys_pt, gpt_query_rewrite_user_pt,
                                             ds_search_summarize_sys_pt, ds_search_summarize_user_pt,
                                             ds_search_final_output_sys_pt, ds_search_final_output_user_pt,
                                             ds_pubmed_synthesis_sys_pt, ds_pubmed_synthesis_user_pt)
from agent.explore.mindsearch_pubmed_prompt import (gpt_pubmed_simple_qr_sys_pt, gpt_pubmed_qr_user_pt,)
from agent.explore.prompt import (system_role, norag_final_output_pt, 
                                  rag_r1_final_output_pt, r1_refer_norag_pt,
                                  followup_questions_pt)
from llm.azure_models import Compositeo4mini, GPT4o, GPT41
from llm.base_model import BaseLLM
from llm.deepseek_models import CompositeDeepseekChat, CompositeDeepseekReasoner
from tools.core.base_tool import BaseTool
from agent.explore.helper import MindSearchHelper
from tools.explore.mindsearch_tools import (RegionWebSearch, BiotechOfiicialWebSearch,
                                            MindSearchFollowupQuestons, PubmedSearch)
from utils.scholar import SCIIF
from utils.web_search import ContentFetcher
from utils.tokenizer import tokenizer

logger = logging.getLogger(__name__)


class MindSearchQueryRewriteAgent(AgentPreset):
    llm: BaseLLM = Compositeo4mini
    sys_prompt: str = gpt_query_rewrite_sys_pt
    tools: List[BaseTool] = [
        RegionWebSearch
    ]
    tool_choice: str = "required"


class MindSearchOfficalSiteQueryRewriteAgent(AgentPreset):
    llm: BaseLLM = Compositeo4mini
    sys_prompt: str = gpt_query_rewrite_sys_pt
    tools: List[BaseTool] = [
        BiotechOfiicialWebSearch
    ]
    tool_choice: str = "required"


class MindSearchWebSearchSummaryAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekChat
    #llm: BaseLLM = GPT41
    sys_prompt: str = ds_search_summarize_sys_pt
    tools: List[BaseTool] = []


class MindSearchR1FinalOutputAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekReasoner
    sys_prompt: str = ""
    tools: List[BaseTool] = []


class MindSearchFinalOutputAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekChat
    #llm: BaseLLM = GPT41
    sys_prompt: str = ds_search_final_output_sys_pt
    tools: List[BaseTool] = []


class MindSearchFollowupQuestionsAgent(AgentPreset):
    llm: BaseLLM = GPT41
    sys_prompt: str = system_role
    tools: List[BaseTool] = [
        MindSearchFollowupQuestons
    ]
    tool_choice: str = "required"


class MindSearchPubMedQueryRewriteAgent(AgentPreset):
    llm: BaseLLM = GPT41
    sys_prompt: str = system_role
    tools: List[BaseTool] = [
        PubmedSearch
    ]
    tool_choice: str = "required"


class MindSearchPubMedAbstractsSummaryAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekChat
    #llm: BaseLLM = GPT41
    sys_prompt: str = ds_pubmed_synthesis_sys_pt
    tools: List[BaseTool] = []


class MindSearchAgent(AgentPreset):
    llm: BaseLLM = GPT4o

    raw_query_rewrite_agent: MindSearchQueryRewriteAgent = MindSearchQueryRewriteAgent()
    search_summarize_agent: MindSearchWebSearchSummaryAgent = MindSearchWebSearchSummaryAgent()
    final_output_agent: MindSearchFinalOutputAgent =  MindSearchFinalOutputAgent()
    followup_questions_agent: MindSearchFollowupQuestionsAgent = MindSearchFollowupQuestionsAgent()
    search_content_fetcher: ContentFetcher = ContentFetcher()
    helper: MindSearchHelper = MindSearchHelper()

    max_retry_times: int = 2

    def _init_components(self, kwargs) -> tuple[str, str, str, bool]:
        r"""Init agent components by language or whether need rag.
        """

        language, background, model, enable_rag = self.helper.get_context(kwargs=kwargs)

        self._init_final_output_agent(enable_rag, model)
        
        return language, background, model, enable_rag
    
    def _init_final_output_agent(self, enable_rag: bool, model: str):
        if constants.DEEPSEEK_R1 == model:
            self.final_output_agent = MindSearchR1FinalOutputAgent()
    
    async def _query_rewrite(self,
                             response: MindSearchResponse,
                             query: str,
                             history_messages: List[dict] = [],
                             background: str = '',
                             language: str = constants.ENGLISH):
        r"""Execute all configured rewrite tools"""
        start_time = time.time()

        # Add thinking node, let user waiting
        node = self._add_thinking_node(response=response, query=query, language=language)
        yield response

        tools = self._get_rewrite_tools()
        
        # Create tasks for each tool
        tasks = [tool(query, history_messages, background, language) for tool in tools]
        
        # Execute all tasks concurrently
        results = await asyncio.gather(*tasks)
        
        # Combine results (implement combination logic as needed)
        enable_rag = False
        combined_result = SearchNode(search_type=SearchType.UNKNOWN,
                                     query=query)
        for result in results:
            if result is not None:
                # check rewrite result
                if result.search_type != SearchType.DISABLE:
                    enable_rag |= True
                if result.thought_process:
                    combined_result.thought_process += "\n" + result.thought_process
                combined_result.children.extend(result.children)

        # Update thinking node
        # Add thought process to the first step summary, so user could read query rewrite detail
        node.summary = combined_result.thought_process
        # Set status as DONE
        node.processing_type = ProcessingType.DONE
        # Set response search graph
        if enable_rag:
            # Add children and set id
            response.search_graph.children.extend(combined_result.children)
            for index, node in enumerate(response.search_graph.children, start=1):
                node.id = index
            yield response
        else:
            response.search_graph.search_type = SearchType.DISABLE
        logger.info(f"Query rewrite cost time {time.time() - start_time}s")

    def _add_thinking_node(
        self,
        response: MindSearchResponse,
        query: str,
        language: str = constants.ENGLISH) -> SearchNode:

        def format_query(language):
            if constants.CHINESE == language:
                return "思考..."
            elif constants.JAPANESE == language:
                return "考え…"
            elif constants.ARABIC == language:
                return "أفكر..."
            else:
                return "Think..."
        
        def format_thought_process(language):
            if constants.CHINESE == language:
                return "任务分析与解决..."
            elif constants.JAPANESE == language:
                return "タスクの分析と問題解決..."
            elif constants.ARABIC == language:
                return "تحليل المهام وحل المشكلات..."
            else:
                return "Task Analysis and Problem Solving..."

        if not response.search_graph:
            response.search_graph = SearchNode(
                search_type=SearchType.UNKNOWN,
                query=query,
                thought_process=format_thought_process(language))
            response.processing_type = ProcessingType.PROCESSING

        elif len(response.search_graph.children) > 0:
            node = response.search_graph.children[-1]
            if node.processing_type == ProcessingType.THINKING:
                return node
        
        node = SearchNode(
            search_type=SearchType.UNKNOWN,
            query=format_query(language),
            processing_type=ProcessingType.THINKING)
        response.search_graph.add_child(node)

        return node
    
    def _get_rewrite_tools(self) -> List[Callable]:
        tools = []

        # Add PubMed search rewrite if available
        if hasattr(self, 'pubmed_query_rewrite_agent'):
            tools.append(self._query_rewrite_with_pubmed)
        
        # Add web search rewrite if available
        if hasattr(self, 'raw_query_rewrite_agent'):
            tools.append(self._query_rewrite_with_websearch)
            
        return tools
        
    async def _query_rewrite_with_websearch(self,
                                            query: str,
                                            history_messages: List[dict] = [],
                                            background: str = '',
                                            language: str = constants.ENGLISH) -> SearchNode:
        search_graph = None
        query_rewrite = None
        for _ in range(self.max_retry_times):
            try:
                user_prompt = gpt_query_rewrite_user_pt.format(current_date=datetime.now().strftime('%Y-%m-%d'),
                                                               language=language,
                                                               background=background,
                                                               user_question=query)
                async for chunk in self.raw_query_rewrite_agent.use_tool(user_prompt=user_prompt, history_messages=history_messages):
                    query_rewrite = chunk
                    if isinstance(query_rewrite, ChatCompletionMessage):
                        logger.info(f"[_query_rewrite_with_websearch] gpt output {query_rewrite}")

                #logger.info(f"[_query_rewrite_with_websearch] result query: {user_prompt} rewrite result: {query_rewrite}")
                # break down retry
                if isinstance(query_rewrite, dict):
                    search_graph = self._convert_websearch_query_rewrite(query, query_rewrite)
                    break

            except Exception as exc:
                logger.warning(f"Mindsearch web engine query rewrite failed, raw query {query}: {exc}")
        
        # just use raw input as the query.
        if not isinstance(query_rewrite, dict):
            query = re.sub(r'\s+', ' ', query.strip()) 
            raw_rewite = {
                "need_websearch": True,
                "thought_process": query,
                "sub_queries": [{
                    "sub_query": query,
                    "key_word": query,
                    "key_word_en": query,
                    }]
                }
            search_graph = self._convert_websearch_query_rewrite(query, raw_rewite)
        
        return search_graph
    
    async def _query_rewrite_with_pubmed(self,
                                         query: str,
                                         history_messages: List[dict] = [],
                                         background: str = '',
                                         language: str = constants.ENGLISH) -> SearchNode:
        search_graph = None
        query_rewrite = None
        for _ in range(self.max_retry_times):
            try:
                sys_prompt = gpt_pubmed_simple_qr_sys_pt.format(current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                                language=language)
                user_prompt = sys_prompt + gpt_pubmed_qr_user_pt.format(user_question=query,
                                                               background=background,)
                #self.pubmed_query_rewrite_agent.sys_prompt = sys_prompt
                #print(f"[MindSearchQueryRewrite] input messages {history_messages} {query}")
                async for chunk in self.pubmed_query_rewrite_agent.use_tool(user_prompt=user_prompt, history_messages=history_messages):
                    query_rewrite = chunk
                    if isinstance(query_rewrite, ChatCompletionMessage):
                        logger.info(f"[_query_rewrite_with_pubmed] gpt output {query_rewrite}")

                #logger.info(f"[_query_rewrite_with_pubmed] result query: {query} rewrite result: {query_rewrite}")
                # break down retry
                if isinstance(query_rewrite, dict):
                    if query_rewrite.get('pubmed_query', ''):
                        search_graph = self._convert_pubmed_query_rewrite(query, query_rewrite, language)
                    break

            except Exception as exc:
                logger.warn(f"Mindsearch Pubmed query rewrite failed, raw query {query}, exception : {exc}")
    
        return search_graph
    
    async def _fetch_search_link_content(self, raw_query: str, node: SearchNode) -> tuple[list, int]:
        new_search_result = []

        try:
            urls = [search_result.url for search_result in node.search_results if search_result.url != '']
                        
            url_content_map = await self.search_content_fetcher.fetch_urls(urls=urls, region=node.region.value, type=node.search_type.name)
        
        except Exception as exc:
            logger.warning(f"MindSearch fetch search link content failed: {exc}")
        
        else:
            is_official_search = 'official' in self.__class__.__name__.lower()
            content_length = 1024 * 16 if is_official_search else 1024 * 3
            page_count = 5 if is_official_search else len(node.search_results)
            if is_official_search and (node.subject == WebSearchSubject.DISEASE or node.subject == WebSearchSubject.MEDICINE):
                content_length = 1024 * 32
                page_count = 3
            
            for url, content in url_content_map.items():
                for search_result in node.search_results:
                    if url == search_result.url:
                        search_result.content = content[:content_length]
                        search_result.is_open = True if search_result.content else False

            # For official search we would only use a few result.
            if is_official_search:
                for index, _ in enumerate(node.search_results):
                    if page_count > 0 and node.search_results[index].is_open:
                        page_count -= 1
                    elif node.search_results[index].is_open:
                        node.search_results[index].is_open = False

            # Since web page content is to big, to save network transport, use new_search_result array contains
            for search_result in node.search_results:
                new_search_result.append(copy.deepcopy(search_result))
                search_result.content = ''

        return new_search_result, node.id

    async def _fetch_pubmed_abstract(self, raw_query: str, node: SearchNode) -> tuple[list, int]:
        if len(node.search_results) == 0:
            return [], node.id
        
        ids = ",".join([search_result.pubmed_id for search_result in node.search_results if search_result.pubmed_id])
        if not ids:
            return node.search_results
        pubmed_search = PubmedSearch()
        abstracts = await pubmed_search.efetch(ids)
        
        abstract_list = abstracts.split("\n\n\n")
        for index, search_result in enumerate(node.search_results):
            if index < len(abstract_list):
                search_result.summ = abstract_list[index].replace('\n', '')
                # remove first line begin id, i.e. 7.J Transl Med. 2025 Jan 4;23
                search_result.summ = re.sub(r'^\d+\.\s*', '', search_result.summ)
        
        new_search_result = []
        for search_result in node.search_results:
            new_search_result.append(copy.deepcopy(search_result))
            search_result.summ = search_result.summ[:150]
        return new_search_result, node.id

    def _convert_websearch_query_rewrite(self, user_prompt:str, query_rewrite: dict) -> SearchNode:
        def convert_search_type(search_type: SearchEngine):
            if SearchEngine.NEWS == search_type:
                return SearchType.NEWS
            elif SearchEngine.PATENT == search_type:
                return SearchType.PATENT
            else:
                return SearchType.WEB

        root = SearchNode(search_type=SearchType.UNKNOWN,
                          query=user_prompt,
                          key_word="")
        root.thought_process = query_rewrite.get("thought_process", "")
        root.subject = query_rewrite.get("subject", WebSearchSubject.UNKNOWN)
        need_websearch = query_rewrite.get("need_websearch", True)

        # Disable search graph when query rewrite decide not to web search
        if not need_websearch:
            root.search_type = SearchType.DISABLE
            return root
        
        for index, sub_query in enumerate(query_rewrite.get("sub_queries", [])):
            search_type = convert_search_type(sub_query.get('search_type', SearchEngine.WEB))
            
            node = SearchNode(search_type=search_type,
                              query=sub_query.get("sub_query", ""),
                              key_word=sub_query.get("key_word", ""),
                              region=sub_query.get("region", WebSearchRegion.GLOBAL),
                              processing_type=ProcessingType.PROCESSING)
            # Only set the first question subject, since in the next step fetching page content we would use the subject to determin
            # the length of the page.
            if index == 0:
                node.subject = root.subject
            for value in sub_query.get("search_result", {}).values():
                node.add_search_result(self._format_websearch_weblink(value))
            root.add_child(node)
        return root

    def _format_websearch_weblink(self, websearch_response: dict, type: SearchType = SearchType.WEB) -> WebSearchLink:
        link = WebSearchLink(
            url=websearch_response.get("url", ""),
            summ=websearch_response.get("summ", ""),
            title=websearch_response.get("title", ""),
            site_name=websearch_response.get("site_name", ""),
            patent_id=websearch_response.get("patent_id", ""),
            type=type
        )
        link.citation = generate_citation(link)
        return link

    def _convert_pubmed_query_rewrite(self,
                                      user_prompt:str,
                                      query_rewrite: dict,
                                      language: str = constants.ENGLISH) -> SearchNode:
        root = SearchNode(search_type=SearchType.UNKNOWN,
                          query=user_prompt,
                          key_word="")
        root.thought_process = query_rewrite.get("thought_process", "")
        
        # set show query word
        query = self.helper.pubmed_search_query(language)

        node = SearchNode(search_type=SearchType.PUBMED,
                          query=query,
                          key_word=query_rewrite.get("pubmed_query", ""),
                          processing_type=ProcessingType.PROCESSING)
        
        for value in query_rewrite.get("query_results", []):
            node.add_search_result(self._format_pubmed_weblink(value))
        root.add_child(node)

        return root

    def _format_pubmed_weblink(self, pubmed_response: dict) -> WebSearchLink:
        # init web search link
        article_ids = pubmed_response.get('ArticleIds', {})
        link = WebSearchLink(
            pubmed_id=pubmed_response.get("Id", ''),
            pmcid=article_ids.get('pmcid', ''),
            pmc=article_ids.get('pmc', ''),
            pii=article_ids.get('pii', ''),
            summ="",
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_response.get('Id', '')}",
            title=pubmed_response.get("Title", ""),
            site_name=pubmed_response.get('Source', "PubMed"),
            issn=pubmed_response.get("ISSN", ""),
            essn=pubmed_response.get("ESSN", ""),
            full_journal_name=pubmed_response.get("FullJournalName", ""),
            nlm_id=pubmed_response.get("NlmUniqueID", ""),
            pub_date=pubmed_response.get("PubDate", ''),
            doi=pubmed_response.get("DOI", ""),
            author=pubmed_response.get("LastAuthor", ""),
            type=SearchType.PUBMED,
            journal_abbr=pubmed_response.get("JournalAbbr", ""),
            year_of_publication=pubmed_response.get("YearOfPublication", ""),
            volume=pubmed_response.get("Volume", ""),
            issue=pubmed_response.get("Issue", ""),
            pagination=pubmed_response.get("Pagination", ""),
        )
        
        # Generate citation (Vancouver format)
        link.citation = generate_citation(link)

        # get sci if
        key_word = link.issn or link.full_journal_name or link.nlm_id or link.site_name
        if key_word != '':
            sciif_response = self.sci_if_client.search_by_issn(value=key_word)
            if 'factor' in sciif_response:
                link.cite_score = str(sciif_response['factor'])

        return link

    async def _summarize_search_result(self,
                                       query: str,
                                       node: SearchNode,
                                       internal_search_results: list[WebSearchLink],
                                       language:str = 'English') -> str:
        try:
            if len(node.search_results) == 0:
                return self.helper.websearch_no_results(node, language)

            search_results = ("\n").join([
                f"""[webpage {index} begin]
                Webage Title: {search_result.title},
                Webage Summary: {search_result.summ},
                Webpage Content: {search_result.content}
                [webpage {index} end]"""
                for index, search_result in enumerate(internal_search_results, start=1) if search_result.is_open
            ])

            search_results = tokenizer.truncate_by_tokens(search_results, 50 * 1000, 'deepseek-v3')

            user_prompt = ds_search_summarize_user_pt.format(current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                           language=language,
                                                            user_question=node.query,
                                                            web_search=search_results)
            
            #self.search_summarize_agent.sys_prompt = sys_prompt
            async for chunk in self.search_summarize_agent.stream_call(user_prompt=user_prompt):
                node.summary += chunk

            # fix reference issues
            node = self._format_summary_result(node)

            logger.info(f"Current web search query: {node.query}, display summary: {node.summary}")
            return node
        except Exception as exc:
            logger.warning(f"summarize current query {node.query} summarize failed: {exc}")

    async def _summarize_pubmed_abstracts(self,
                                          query: str,
                                          node: SearchNode,
                                          internal_search_results: list[WebSearchLink],
                                          language: str = constants.ENGLISH) -> str:
        if len(node.search_results) == 0:
            return ""
        
        pubmed_abstracts = ("\n").join([
            f"""[webpage {index} begin]
            <title>{search_result.title}</title>
            <sci_if_score>{search_result.cite_score}</sci_if_score>
            <abstract>{search_result.summ}</abstract>
            [webpage {index} end]"""
            for index, search_result in enumerate(internal_search_results, start=1)
        ])

        user_prompt = ds_pubmed_synthesis_user_pt.format(current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                         language=language,
                                                         pubmed_results=pubmed_abstracts,
                                                         user_question=query)
        
        try:
            async for chunk in self.pubmed_search_summarize_agent.stream_call(user_prompt=user_prompt):
                node.summary += chunk
            
            # fix out reference issues
            node.summary += f'\n\n**PubMed Search Term:** {node.key_word}'
            node = self._format_summary_result(node)
                        
            logger.info(f"Current pubmed search query: {user_prompt[:500]}, display summary: {node.summary}")
            return node
        except Exception as exc:
            logger.warn(f"summarize current query {node.query} summarize failed, exception {exc} ")

    
    def _format_summary_result(self, node: SearchNode) -> SearchNode:
        # Set status as Done
        node.processing_type = ProcessingType.DONE
        
        if node.summary == '':
            return
                
        # fix referenc issue, i.e. 【citation:1】，【citation:1]
        node.summary = self.helper.format_invalid_citation(node.summary, [r'【citation:(\d+)】',
                                                                          r'【citation:(\d+)\]',
                                                                          r'\[citation:(\d+)】',
                                                                          r'\[webpage (\d+)\]',
                                                                          r'\[引用:(\d+)\]'])

        # format citation from [citation:1] to [1](http://www.baidu.com)
        url_list = [search_result.dict() for search_result in node.search_results]
        node.summary = self.helper.format_citation(url_list, node.summary)
        
        """
        # so far we use deepseek citation like [citation:x] instead of markdown link [1](url)
        # fix gpt response Chinese citation issue, i.e 减少偏头痛的发生【5】
        node.summary = self.helper.format_invalid_reference(node.summary, node, [r'【(\d+)】', r'【(\d+)]'])

        # fix out reference issue, i.e【1](https://www.baidu.com)
        # [2](https://pubmed.ncbi.nlm.nih.gov/40033803)(https://pubmed.ncbi.nlm.nih.gov/40033803)
        node.summary = self.helper.format_output_reference(node.summary, [r'【(.*?)\]\(([\w+.-]+:[^\s\)]+)\)', 
                                                                                     r'【(.*?)】\(([\w+.-]+:[^\s\)]+)\)', 
                                                                                     r'【(.*?)】\(([\w+.-]+:[^\s\)]+)\)】',
                                                                                     r'\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)\(([\w+.-]+:[^\s\)]+)\)'])
        """
        
        return node

    async def _scan_and_summary_search_link(self, user_prompt: str , children: list[SearchNode], response: MindSearchResponse, language):
        tasks = []
        for child in children:
            if child.search_type == SearchType.PUBMED:
                 tasks.append(self._fetch_pubmed_abstract(user_prompt, child))
            elif child.search_type == SearchType.WEB \
                or child.search_type == SearchType.NEWS \
                or child.search_type == SearchType.PATENT:
                tasks.append(self._fetch_search_link_content(user_prompt, child))               

        tmp_search_results = []
        for completed_task in asyncio.as_completed(tasks):
            tmp_search_results.append(await completed_task) # search_result array and node id

        # summarize page content
        summarize_tasks = []
        for internal_search_results, node_id in tmp_search_results:
            if len(internal_search_results) == 0:
                continue
            for child in children:
                if child.id != node_id:
                    continue
                if child.search_type == SearchType.PUBMED:
                    summarize_tasks.append(self._summarize_pubmed_abstracts(user_prompt, child, internal_search_results, language))
                elif child.search_type == SearchType.WEB \
                    or child.search_type == SearchType.NEWS \
                    or child.search_type == SearchType.PATENT:
                    summarize_tasks.append(self._summarize_search_result(user_prompt, child, internal_search_results, language))
                    

        for completed_task in asyncio.as_completed(summarize_tasks):
            await completed_task

        # check children summary
        for child in children:
            if not child.summary:
                child.summary = self.helper.websearch_fail_reason(child, language)
        
        return children
    
    async def _task_with_heartbeat(self, response: MindSearchResponse, func: Callable, *args: Any, **kwargs: Any):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        start_time = time.time()
        task = asyncio.create_task(func(*args, **kwargs))
        shielded = asyncio.shield(task)

        while not task.done():
            yield response
            await asyncio.sleep(2)
        
        result = await shielded
        end_time = time.time()
        logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
        yield response

    async def _followup_questions(self,
                                  user_prompt: str,
                                  response: MindSearchResponse,
                                  history_messages: List[dict] = [],
                                  language: str = constants.ENGLISH):
        if self.followup_questions_agent is None:
            return response
        followup_history_messages = [{
            "role": "assistant",
            "content": datetime.now().strftime('The current date is %Y-%m-%d.')
        }]
        followup_questions = []
        final_user_prompt = followup_questions_pt.format(user_question=user_prompt,
                                                         response=response.content,
                                                         language=language)
        for _ in range(self.max_retry_times):
            async for chunk in self.followup_questions_agent.use_tool(user_prompt=final_user_prompt, history_messages=followup_history_messages):
                followup_questions = chunk
            if isinstance(followup_questions, list):
                break
        response.followup_questions = followup_questions if isinstance(followup_questions, list) else []
        response.processing_type = ProcessingType.FOLLOWUPQUESTION
        logger.info(f"[_followup_questions] follow up questions: {followup_questions}")
        return response
        
    def _merge_search_summ(self, children: list[SearchNode]) -> tuple[str, dict]:

        pattern = r'\[(\d+)\]\((.*?)\)'

        def format_internal_summary(summ: str, url_map: dict) -> str:
            def replace_func(match):
                url = match.group(2)
                if url in url_map:
                    num = url_map[url]['id']
                    return f'[citation:{num}]'
                else:
                    return ''
            
            summ = re.sub(pattern, replace_func, summ)
            return summ

        summ = ""
        url_map = {}
        for child in children:
            references = re.findall(pattern=pattern, string=child.summary)
            for reference  in references:
                try:
                    number = int(reference[0]) - 1
                    url = reference[1]
                    if number < len(child.search_results) and child.search_results[number].url == url:
                        if not url in url_map:
                            url_map[url] = self._format_final_source(id=len(url_map) + 1, search_result=child.search_results[number])
                except Exception as exc:
                    pass
            n_summ = format_internal_summary(summ=child.summary, url_map=url_map)
            summ += f"""<web_search>
            <web_search_query>{child.query}</web_search_query>
            <web_search_summary>{n_summ}</web_search_summary>
            <web_search>\n"""

        return summ, url_map
    
    def _format_final_source(self, id: int, search_result: WebSearchLink) -> dict:

        def _compress_json(obj: dict) -> str:
            res = ''
            try:
                res = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
            except Exception as e:
                logger.warning(f"Invalid compres {e}")
            return res

        return {
            'id': id,
            'url': search_result.url,
            'title': search_result.title,
            'site_name': search_result.site_name,
            'summary': search_result.summ,
            'cite_score': search_result.cite_score,
            'pubmed_id': search_result.pubmed_id,
            'pub_date': search_result.pub_date,
            'type': search_result.type,
            'doi': search_result.doi,
            'author': search_result.author,
            'full_journal_name': search_result.full_journal_name,
            'citation': _compress_json(search_result.citation),
        }
    
    def _format_rag_summary(self, response: MindSearchResponse) -> str:
        search_summary, url_map = self._merge_search_summ(response.search_graph.children)
        response.search_graph.source = list(url_map.values()) # for output formatting
        response.search_graph.summary = 'DONE'
        return search_summary
    
    async def _final_output(self, user_prompt: str, history_messages: List[dict]):
        # use different agent
        output = ""
        buffer = ""
        last_yield_time = time.time()
        yield_interval = 0.3 # 调整输出时间间隔(秒)
        async for chunk in self.final_output_agent.stream_call(user_prompt=user_prompt, history_messages=history_messages):
            buffer += chunk
            current_time = time.time()

            if current_time - last_yield_time >= yield_interval:
                output += buffer
                yield output
                buffer = ""
                last_yield_time = current_time

        if buffer:
            output += buffer
            yield output

    def _add_finalout_node(self, response: MindSearchResponse, language: str) -> SearchNode:
        r"""
        Add a search node to notify user, current is preparing final output.
        """
        def format_though_process(language: str):
            if constants.CHINESE == language:
                return '模型预处理中'
            elif constants.JAPANESE == language:
                return 'モデルの前処理中'
            elif constants.ARABIC == language:
                return 'أثناء المعالجة المسبقة للنموذج'
            else:
                return 'During model preprocessing'
    
        if not response.search_graph:
            response.search_graph = SearchNode(
                search_type=SearchType.UNKNOWN,
                query=format_though_process(language=language),
                thought_process=format_though_process(language=language))
            
        node = SearchNode(
            search_type=SearchType.HELPER,
            query=format_though_process(language=language),
            summary=format_though_process(language=language),
            processing_type=ProcessingType.PROCESSING)
        
        response.search_graph.add_child(node)

        return node
        
    def _update_finalout_node(self, response: MindSearchResponse, language: str):
        if not response.search_graph or len(response.search_graph.children) == 0:
            return
        
        def format_summary(language: str):
            if constants.CHINESE == language:
                return '模型处理完成'
            elif constants.JAPANESE == language:
                return 'モデルの処理が完了しました'
            elif constants.ARABIC == language:
                return 'اكتملت معالجة النموذج'
            else:
                return 'Model processing completed'
        
        if response.search_graph.children[-1].search_type == SearchType.HELPER:
            response.search_graph.children[-1].summary = format_summary(language=language)
            response.search_graph.children[-1].processing_type = ProcessingType.DONE

    def _format_final_output(
        self,
        response: MindSearchResponse,
        model: str = '',
        language: str = constants.ENGLISH,
        runtime_info: dict = {},
        remove_citation: bool = False):

        for node in response.search_graph.children:
            node.processing_type = ProcessingType.DONE   
        
        self._update_finalout_node(response=response, language=language)

        # rewrite citation issue
        if response.search_graph:
            response.content = self.helper.format_citation(response.content)
            response.content, response.search_graph.source = self.helper.remove_unused_citation(
                runtime_info.get('source', []), 
                response.content)
        
        # remove invalid citation like [citation:背景知识]
        invalid_reference_patterns: list[str] = [r'\[citation:\s*\]']

        # Apply the invalid reference pattern to remove them
        for pattern in invalid_reference_patterns:
            response.content = re.sub(pattern, '', response.content)

        # remove summary to reduce body length
        if response.search_graph:
            for child in response.search_graph.children:
                for search_result in child.search_results:
                    if hasattr(search_result, 'summ'):
                        search_result.summ = ''
            for item in response.search_graph.source:
                if 'summary' in item:
                    item['summary'] = item['summary'][:200]

        url_pattern = r'\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)'

        # remove all citation in the content
        if remove_citation:
            # get all citations
            response.content = re.sub(url_pattern, '', response.content)

        # fix norag output doesnot contain citation issue
        if response.search_graph and len(response.search_graph.source) == 0:
            # get all citations
            matches = re.findall(url_pattern, response.content)

            url_map = {}
            for match in matches:
                url = match[1]
                domain = self.helper.get_domain(url=url)
                if url not in url_map:
                    url_map[url] = {
                        'id': len(url_map) + 1,
                        'title': domain,
                        'site_name': domain,
                        'summary': url,
                        'url': url,
                    }

            def replace_func(match):
                url = match.group(2)
                url = url.replace("(", "%28").replace(")", "%29")
                value = url_map[url]
                return f"[{value['id']}]({value['url']})"
            
            # rewrite content fix id not continue issue
            response.content = re.sub(url_pattern, replace_func, response.content)
            # rewrite 
            response.search_graph.source = list(url_map.values())
        return response

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        
        start_time = time.time()

        # init components
        language, background, model, enable_rag = self._init_components(kwargs=kwargs)
        response = self.helper.init_response(self)
        yield response

        # query rewrite
        if enable_rag:
            async for tmp_response in self._query_rewrite(response=response,
                                                          query=user_prompt,
                                                          history_messages=copy.deepcopy(history_messages),
                                                          background=background,
                                                          language=language):
                yield tmp_response
        
        # request need web search retrieval augmented
        if response.search_graph.search_type != SearchType.DISABLE:
            # fetch all search links and summarize, since it may took a long time, use heartbeat to avoid connection closed.
            async for tmp_response in self._task_with_heartbeat(response, 
                                                                self._scan_and_summary_search_link,
                                                                user_prompt,
                                                                response.search_graph.children,
                                                                response,
                                                                language):
                yield tmp_response
            
            search_summary = self._format_rag_summary(response)

            # add the related search summary in finally user prompt, performance is batter than add them in the history messages.
            if constants.DEEPSEEK_R1 == model:
                final_user_prompt = rag_r1_final_output_pt.format(
                    background=background,
                    websearch_results=search_summary,
                    user_prompt=user_prompt,
                    current_datetime=datetime.now().strftime('%Y-%m-%d.'),
                    language=language)
            else:
                final_user_prompt = ds_search_final_output_user_pt.format(current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                                                       language=language,
                                                                                       background=background,
                                                                                       websearch_results=search_summary,
                                                                                       user_question=user_prompt)
        else:
            pt_template = r1_refer_norag_pt if constants.DEEPSEEK_R1 == model else norag_final_output_pt
            final_user_prompt = pt_template.format(
                background=background,
                user_prompt=user_prompt,
                current_datetime=datetime.now().strftime('%Y-%m-%d.'),
                language=language)

        logger.info(f"Mindesearch final response input: {history_messages} {final_user_prompt}")

        async for chunk in self._final_output(user_prompt=final_user_prompt, history_messages=history_messages):
            # 确保content字段只包含字符串内容
            if hasattr(chunk, 'content') and chunk.content:
                response.content = chunk.content
            elif isinstance(chunk, str):
                response.content = chunk
            else:
                response.content = str(chunk)
            yield response
        self._format_final_output(response=response, model=model, language=language)
        yield response
        logger.info(f"MindSearch final output: {response.content} {response} cost {time.time() - start_time}s")
        if not kwargs.get('skip_followup', False):
            # Add follow update questions.
            response = await self._followup_questions(user_prompt=user_prompt, response=response, history_messages=history_messages, language=language)
            yield response


class MindSearchOfficialAgent(MindSearchAgent):
    raw_query_rewrite_agent: MindSearchOfficalSiteQueryRewriteAgent = MindSearchOfficalSiteQueryRewriteAgent()
    pubmed_query_rewrite_agent: MindSearchPubMedQueryRewriteAgent = MindSearchPubMedQueryRewriteAgent()
    pubmed_search_summarize_agent: MindSearchPubMedAbstractsSummaryAgent = MindSearchPubMedAbstractsSummaryAgent()
    search_summarize_agent: MindSearchWebSearchSummaryAgent = MindSearchWebSearchSummaryAgent()
    final_output_agent: MindSearchFinalOutputAgent =  MindSearchFinalOutputAgent()
    sci_if_client: SCIIF = SCIIF()
