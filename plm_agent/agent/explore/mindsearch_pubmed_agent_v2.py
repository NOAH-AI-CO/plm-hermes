import re
import copy
import time
import asyncio
import logging
import agent.explore.constants as constants

from datetime import datetime
from typing import List

from agent.core.preset import AgentPreset
from agent.explore.schema import (MindSearchResponse, SearchNode, ProcessingType,
                                  SearchType, WebSearchLink)
from agent.explore.mindsearch_agent import (MindSearchOfficialAgent, MindSearchR1FinalOutputAgent)
from llm.azure_models import GPT41, GPTo3, GPTo4Mini, Compositeo4mini
from llm.deepseek_models import CompositeDeepseekReasoner, CompositeDeepseekChat
from llm.base_model import BaseLLM
from tools.core.base_tool import BaseTool
from tools.explore.mindsearch_tools import (PubmedSearch, PubMedRecommendArticles)
from utils.document import AzureDocumentParser, Downloader
from utils.tokenizer import tokenizer

from agent.explore.mindsearch_pubmed_prompt_v2 import (system_role, gpt_pubmed_qr_pt, gpt_pubmed_qr_supplement_pt,
                                                       r1_pubmed_select_pt, r1_pubmed_synthesis_pt, r1_response_guidance_pt,
                                                       ds_pubmed_final_user_pt)
from agent.explore.prompt import (r1_refer_norag_pt, refer_norag_pt)

logger = logging.getLogger(__name__)


class PubMedSimpleQueryRewriteAgent(AgentPreset):
    llm: BaseLLM = Compositeo4mini
    sys_prompt: str = system_role
    tools: List[BaseTool] = [
        PubmedSearch
    ]
    tool_choice: str = "required"


class PubMedAssistantAgent(AgentPreset):
    llm: BaseLLM = Compositeo4mini
    sys_prompt: str = ''
    tools: List[BaseTool] = []


class PubMedRecommendArticlesAgent(AgentPreset):
    llm: BaseLLM = GPT41
    sys_prompt: str = system_role
    tools: List[BaseTool] = [
        PubMedRecommendArticles
    ]
    tool_choice: str = "required"


class MindSearchPubMedAgentV2(MindSearchOfficialAgent):

    pubmed_simple_query_rewrite_agent: PubMedSimpleQueryRewriteAgent = PubMedSimpleQueryRewriteAgent()
    pubmed_assistatn_agent: PubMedAssistantAgent = PubMedAssistantAgent()
    pubmed_recommend_articles_agent: PubMedRecommendArticlesAgent = PubMedRecommendArticlesAgent()
    pmc_download_tool: Downloader = Downloader()
    azure_document_parse: AzureDocumentParser = AzureDocumentParser()
    min_count: int = 0

    def _init_final_output_agent(self, enable_rag: bool, model: str):
        if not enable_rag:
            if model == constants.DEEPSEEK_R1:
                self.final_output_agent = MindSearchR1FinalOutputAgent()

    def _init_response(self, query: str, language: str) -> MindSearchResponse:
        
        def though_process(language: str):
            if language == constants.CHINESE:
                return '以下思考、分析过程基于PubMed检索'
            elif language == constants.JAPANESE:
                return '以下の考察プロセスは、PubMedでの検索結果に基づいています'
            elif language == constants.ARABIC:
                return 'تعتمد عملية التفكير التالية على بحث في PubMed'
            else:
                return 'The following thought and analysis process is based on a PubMed search'
        
        response = self.helper.init_response(self)
        response.processing_type = ProcessingType.PROCESSING
        response.search_graph = SearchNode(search_type=SearchType.UNKNOWN,
                                           query=query,
                                           thought_process=though_process(language=language))
        return response
    
    async def _query_rewrite(self, 
                             response: MindSearchResponse,
                             query_results: List,
                             query: str,
                             history_messages: List[dict] = ...,
                             background: str = '',
                             model: str = '',
                             language: str = constants.ENGLISH):
        r"""
        Rwrite user's question into PubMed Boolean query.
        Since ChatGPT prefer write a very complex result which may fetch too less results.
        We would rewrite a few times to expand search scope.
        """

        def qr_query(language: str):
            if language == constants.CHINESE:
                return 'PubMed查询...'
            elif language == constants.JAPANESE:
                return 'PubMed検索...'
            elif language == constants.ARABIC:
                return 'بحث PubMed ...'
            else:
                return 'PubMed Searching ...'
        
        def qr_summary(language: str):
            if language == constants.CHINESE:
                return '尝试改写原始问题...'
            elif language == constants.JAPANESE:
                return '元の質問を書き換えてみてください...'
            elif language == constants.ARABIC:
                return 'حاول إعادة صياغة السؤال الأصلي ...'
            else:
                return 'Try rewriting the original question ...'
        
        def qr_suplyment_summary(language: str):
            if language == constants.CHINESE:
                return '获取更多信息补充回答...'
            elif language == constants.JAPANESE:
                return '追加情報を取得して回答を補足します...'
            elif language == constants.ARABIC:
                return 'جلب المزيد من المعلومات لاستكمال الإجابة ...'
            else:
                return 'Retrieve more information to supplement the answer ...'
            
        def qr_stop_query(language: str):
            if language == constants.CHINESE:
                return 'PubMed检索完成'
            elif language == constants.JAPANESE:
                return 'PubMedの検索が完了しました'
            elif language == constants.ARABIC:
                return 'اكتمل البحث في PubMed'
            else:
                return 'PubMed search completed'            
            
        def format_search_results(pubmed_query: dict, node: SearchNode, language: str) -> str:
            r"""
            Update PubMed query node.
            """
            
            original_query = pubmed_query.get('pubmed_query', '')
            query = original_query if original_query != '' else f"{qr_stop_query(language=language)}"
            node.query = f"{query[:60]}..." if len(query) >= 60 else query

            thought_process = pubmed_query.get('thought_process', '')
            node.summary = f"""<think>{thought_process}</think>\n**{query}**\n""" if thought_process else f"""**{query}**"""
            
            for value in query_rewrite.get("query_results", []):
                node.add_search_result(self._format_pubmed_weblink(value))

            return original_query      
        
        for index in range(0, 3):
            # Add query rewrite node
            summary = qr_summary(language=language) if index == 0 else qr_suplyment_summary(language=language)
            if len(response.search_graph.children) > 0 \
                and response.search_graph.children[-1].summary == '':
                node = response.search_graph.children[-1]
            else:
                node = SearchNode(
                    search_type=SearchType.PUBMED,
                    query=qr_query(language=language),
                    summary=summary)
                response.search_graph.add_child(node)
            
            # try query rewrite
            if index == 0:
                query_rewrite = await self._query_rewrite_by_simple(query, history_messages, background, language)
            else:
                query_rewrite = await self._query_rewrite_by_supplement(query, query_results, language)
            
            if query_rewrite is None:
                continue
            
            # search PubMed and get artiles' abstract
            pubmed_query = format_search_results(query_rewrite, node, language)
            
            # don't pubmed search info just return
            if pubmed_query == '':
                # indicate don't need searching
                if index == 0:
                    response.search_graph.search_type = SearchType.DISABLE
                node.processing_type = ProcessingType.DONE
                return
            
            # fetch pubmed article abstract
            search_results, _ = await self._fetch_pubmed_abstract(query, node)
            node.processing_type = ProcessingType.DONE

            # cache history query and search results
            query_results.append({
                'pubmed_query': pubmed_query,
                'pubmed_results': search_results,
            })

    async def _query_rewrite_by_simple(self,
                                       query: str,
                                       history_messages: List[dict] = [],
                                       background: str = '',
                                       language: str = constants.ENGLISH) -> dict:
        r"""
        Simple PubMed query rewrite, this method just simple translate user's raw query into PubMed Boolean query and may fetch less results.
        """
        query_rewrite = None

        try:
            user_prompt = gpt_pubmed_qr_pt.format(current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                  language=language,
                                                  user_question=query,
                                                  background=background,)

            async for chunk in self.pubmed_simple_query_rewrite_agent.use_tool(user_prompt=user_prompt):
                query_rewrite = chunk

        except Exception as exc:
            logger.warning(f"Mindsearch Simple Pubmed query rewrite failed, raw query {query}: {exc}")
        
        return query_rewrite
    
    async def _query_rewrite_by_supplement(self,
                                           query: str,
                                           query_results: list,
                                           language: str):
        r"""
        Refine query rewrite to fetch more information.
        """
        
        historical_queries = ""
        for index, item in enumerate(query_results, start=1):
            recommed_artciles = ('\n').join([
                f"""<PubMed_article_abstract>
                Title:{weblink.title},
                SCIIF: {weblink.cite_score},
                Abstract: {weblink.summ}
                </PubMed_article_abstract>\n"""
                for weblink in item['pubmed_results']
            ])
            historical_queries += f"""<PubMed_step_{index}_query>
            <PubMed_query_command>{item['pubmed_query']}</PubMed_query_command>
            <PubMed_recommend_articles>{recommed_artciles}</PubMed_recommend_articles>
            </PubMed_step_{index}_query>"""
        
        user_prompt = gpt_pubmed_qr_supplement_pt.format(historical_queries=historical_queries,
                                                         current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                         user_question=query,
                                                         language=language)
        
        #print(historical_queries)
        logger.info(f"MindSearch Supplement PubMed query user_prompt: {user_prompt[:200]}...{user_prompt[-200:]}")
        
        query_rewrite = None

        try:
            async for chunk in self.pubmed_simple_query_rewrite_agent.use_tool(user_prompt=user_prompt):
                query_rewrite = chunk

        except Exception as exc:
            logger.warning(f"Mindsearch Supplement Pubmed query rewrite failed, raw query {query}: {exc}")

        return query_rewrite
    
    def _sort_query_results(self, query_results: list) -> list:
        # query pubmed
        pubmed_results = [result for item in query_results for result in item['pubmed_results']]
        # sort pubmed_results by score
        pubmed_results.sort(key=lambda x: x.score, reverse=True)
        # filter out same pubmed id
        seen_pubmed_ids = set()
        unique_pubmed_results = []
        for result in pubmed_results:
            if result.pubmed_id not in seen_pubmed_ids:
                seen_pubmed_ids.add(result.pubmed_id)
                unique_pubmed_results.append(result)
        # deepcopy to avoid too big article content
        return  unique_pubmed_results

    
    def _query_rewrite_fail(self, response: MindSearchResponse, user_prompt: str, language: str = constants.ENGLISH):
        if response.search_graph:
            for node in response.search_graph.children:
                node.processing_type = ProcessingType.DONE

        if language == constants.CHINESE:
            response.content = f"""当前问题关联搜索: **{user_prompt}** 没有检索到结果，请简化问题或者指定PubMed搜索，如输入如下格式:
[(breast cancer[Title/Abstract]) AND (("2020/12/12"[Date - Create] : "3000"[Date - Create]))] 乳腺癌三期治疗方案"""
        elif language == constants.JAPANESE:
            response.content = f"""現在の質問に関連する検索: **{user_prompt}** では結果が見つかりませんでした。質問を簡略化するか、PubMed検索を指定してください。例えば、以下のフォーマットで入力してください:
[(breast cancer[Title/Abstract]) AND (("2020/12/12"[Date - Create] : "3000"[Date - Create]))] 乳がんIII期の治療計画"""
        elif language == constants.ARABIC:
            response.content = f"""لم يتم العثور على نتائج لعملية البحث المرتبطة بالمشكلة الحالية: **{user_prompt}**. يرجى تبسيط السؤال أو تحديد بحث PubMed باستخدام التنسيق التالي:  
[(breast cancer[Title/Abstract]) AND (("2020/12/12"[Date - Create] : "3000"[Date - Create]))] مثال: خطة علاج سرطان الثدي في المرحلة الثالثة."""
        else:
            response.content = f"""Current query's associated search: **{user_prompt}** returned no results. Please simplify your query or specify a PubMed search, for example, by entering the following format:
[(breast cancer[Title/Abstract]) AND (("2020/12/12"[Date - Create] : "3000"[Date - Create]))] Treatment plan for stage III breast cancer"""

    async def _parse_recommended_article_ids(self,
                                           llm_response: str,
                                           search_results: List[WebSearchLink]) -> List[WebSearchLink]:
        article_ids = []
        try:
            user_prompt = f"""Please parse the recommended article ids.
            You can find them at the end of the content, just after keyword: 需要深入阅读的论文 or need reading articles, i.e. 需要深入阅读的论文:7,2, or Need reading articles: 7, 2, 8.
            <content>{llm_response}</content>"""

            async for chunk in self.pubmed_recommend_articles_agent.use_tool(user_prompt=user_prompt):
                article_ids = chunk

        except Exception as exc:
            logger.warning(f"Mindsearch parse recommended article ids failed, raw query {search_results}: {exc}")

        logger.info(f"Mindsearch PubMed parse recommended articles result: {article_ids}")
        
        res = [search_results[article_id - 1] for article_id in article_ids 
               if 0 <= article_id - 1 < len(search_results)]
        return res

    def _copy_search_results(self, search_results: list[WebSearchLink]) -> list:
        res = copy.deepcopy(search_results)
        for item in res:
            item.summ = item.summ[:200]
        return res        
    
    async def _get_recommend_articles(
        self,
        response: MindSearchResponse,
        search_results: List[WebSearchLink],
        query: str,
        recommend_articles: list,
        language: str = constants.ENGLISH):
        
        def pubmed_recommend(language: str):
            if language == constants.CHINESE:
                return f'筛选出需要阅读的PubMed文章...'
            elif language == constants.JAPANESE:
                return f'読む必要があるPubMedの記事を選別する...'
            elif language == constants.ARABIC:
                return f'تصفية المقالات من PubMed التي تحتاج إلى قراءة...'
            else:
                return f'Filtering out the PubMed articles that need to be read....'
        
        def merge_search_summ(search_results: list[WebSearchLink]) -> str:
            res = ""
            for index, weblink in enumerate(search_results, start=1):
                res += f"""[article {index} begin]
                Title:{weblink.title},
                SCIIF: {weblink.cite_score},
                Abstract: {weblink.summ}
                [article {index} end]
                """
            return res

        node = SearchNode(search_type=SearchType.UNKNOWN,
                          query=pubmed_recommend(language=language),
                          search_results=self._copy_search_results(search_results))
        response.search_graph.add_child(node)

        # read abstract and find most relavent issues
        search_content = merge_search_summ(search_results=search_results)

        pubmed_select_prompt = r1_pubmed_select_pt.format(pubmed_search=search_content,
                                                          current_date=datetime.now().strftime('%Y-%m-%d.'),
                                                          user_question=query,
                                                          language=language)
        
        async for chunk in self.pubmed_assistatn_agent.stream_call(pubmed_select_prompt):
            node.summary += chunk

        self._format_summary_result(node)
        logger.info(f"PubMed select response: {node.summary[-100:]}")

        # get prompting articles
        """
        recommend_articles_str = next((item for item in reversed(node.summary.split('\n')) if item), '')
        matches = re.findall(r'(\d+)', recommend_articles_str)
        for match in matches:
            id = int(match[0])
            if id > 0 and id <= len(search_results):
                recommend_articles.append(search_results[id - 1])
        """
        
        # when output is not formatted try use llm
        parsed_articles = await self._parse_recommended_article_ids(node.summary, search_results)
        recommend_articles.extend(parsed_articles)

        # logging article titles
        titles = (",").join([
            artilce.title
            for artilce in recommend_articles
        ])
        logger.info(f"Mindsearch PubMed final get recommend articles: {titles}")

    def _get_free_articles(
            self,
            pubmed_results: List[WebSearchLink],
            response: MindSearchResponse,
            language: str):
        
        free_articles = [article for article in pubmed_results if article.pmc != '' and article.doi != '']

        if len(free_articles) > 0:
            return free_articles

        logger.info(f"Mindsearch PubMed no free recommend articles")

        def no_free_articles(language: str):
            if language == constants.CHINESE:
                return f'阅读论文结束'
            elif language == constants.JAPANESE:
                return f'論文を深く読み終える'
            elif language == constants.ARABIC:
                return f'إتمام القراءة المتعمقة للورقة البحثية'
            else:
                return f'Complete an in-depth reading of the paper'
            
        def summary(language: str, pubmed_results: List[WebSearchLink]):
            titles = ("\n").join([
                f"- [{weblink.title}]({weblink.url})"
                for weblink in pubmed_results
            ])

            explain = ''
            if language == constants.CHINESE:
                explain = f'需要深入阅读的论文均非免费，无法获取论文内容'
            elif language == constants.JAPANESE:
                explain = f'深く読む必要がある論文はすべて有料であり、論文の内容を入手することはできません'
            elif language == constants.ARABIC:
                explain = f'جميع الأوراق البحثية التي تتطلب قراءة متعمقة ليست مجانية، ولا يمكن الحصول على محتوى الأوراق'
            else:
                explain = f'All papers that require in-depth reading are not free, and the content of the papers cannot be obtained'

            return f"> {explain} \n {titles}"

        node = SearchNode(search_type=SearchType.HELPER,
                          processing_type=ProcessingType.DONE,
                          query=no_free_articles(language),
                          summary=summary(language, pubmed_results))
            
        response.search_graph.add_child(node)

        return []

    async def _try_read_articles(
        self,
        user_prompt: str,
        pubmed_results: List[WebSearchLink],
        response: MindSearchResponse,
        language: str = constants.ENGLISH):

        r"""
        Try read articles.
        """
        logger.info(f"Mindsearch PubMed search try download articles {len(pubmed_results)}")

        free_articles = self._get_free_articles(pubmed_results, response, language)[:2]
        
        if len(free_articles) == 0:
            return

        # try read free articles
        times = 1
        for free_article in free_articles:
            if free_article.pmc == '' or free_article.doi == '':
                continue
            if times <= 0:
                break

            try:
                node = self._read_article_node(free_article, response)
                action = await self._read_article(free_article, node, language)

                if action:
                    times -= 1

            except asyncio.TimeoutError:
                logger.warning(f"Mindsearch PubMed read article time out {free_article.title} {free_article.pubmed_id}")

    def _read_article_node(
        self,
        weblink: WebSearchLink,
        response: MindSearchResponse) -> SearchNode:

        node = SearchNode(search_type=SearchType.UNKNOWN,
                          processing_type=ProcessingType.PROCESSING,
                          query=f"{weblink.title[:100]}...",
                          search_results=[copy.deepcopy(weblink)])
        response.search_graph.add_child(node) 

        return node

    async def _read_article(
        self,
        weblink: WebSearchLink,
        node: SearchNode,
        language: str) -> bool:
        
        r"""
        Read article
        """
        logger.info(f"Mindsearch PubMed try to get article : {weblink.title} {weblink.doi}")
        
        def downloading(title: str, language: str):
            if language == constants.CHINESE:
                return f'尝试下载论文"{title}"...'
            elif language == constants.JAPANESE:
                return f'論文「{title}」のダウンロードを試みています…'
            elif language == constants.ARABIC:
                return f'جارٍ محاولة تنزيل الورقة البحثية بعنوان "{title}"...'
            else:
                return f'Attempting to download the paper titled "{title}" ...'

        def parsing(title: str, language: str):
            if language == constants.CHINESE:
                return f'尝试下载论文"{title}"...'
            elif language == constants.JAPANESE:
                return f'論文「{title}」のダウンロードを試みています…'
            elif language == constants.ARABIC:
                return f'جارٍ محاولة تنزيل الورقة البحثية بعنوان "{title}"...'
            else:
                return f'Attempting to download the paper titled "{title}" ...'
        
        def parsing_failed(language: str):
            if language == constants.CHINESE:
                return f'获取论文失败'
            elif language == constants.JAPANESE:
                return f'論文の取得に失敗しました'
            elif language == constants.ARABIC:
                return f'فشل في الحصول على الورقة البحثية'
            else:
                return f'Failed to retrieve the paper'
            
        def parsing_failed_summary(title: str, language: str):
            if language == constants.CHINESE:
                return f'获取论文{title}失败'
            elif language == constants.JAPANESE:
                return f'論文{title}の取得に失敗しました'
            elif language == constants.ARABIC:
                return f'فشل في الحصول على الورقة البحثية'
            else:
                return f'Failed to retrieve the paper: {title}'
            
        def parsing_finish(language: str):
            if language == constants.CHINESE:
                return f'阅读论文结束'
            elif language == constants.JAPANESE:
                return f'論文の読解が完了しました'
            elif language == constants.ARABIC:
                return f'اكتملت قراءة الورقة البحثية'
            else:
                return f'Finished reading the paper'

        try:
            start_time = time.time()
            node.summary = downloading(weblink.title, language)
            # download article
            download_result = await self.pmc_download_tool.doi(weblink.doi)
            if 'error' in download_result:
                raise Exception(f"{download_result['error']} for {weblink.title}")

            # parse article
            node.summary = parsing(weblink.title, language)
            parse_result = self.azure_document_parse.analyze_read(download_result['file_path'])

            if not parse_result:
                raise Exception(f"Azure Document Intelligence parsing {weblink.title} failed")
            
            weblink.content = parse_result.content
            node.processing_type = ProcessingType.DONE
            node.summary = parsing_finish(language=language)

            logger.info(f"Mindsearch PubMed get article : {weblink.title}, content length: {len(weblink.content)}, cost {time.time() - start_time}")

        except Exception as exc:
            logger.warning(f"PubMed agent read article failed {weblink.title}: {exc}")
            node.processing_type = ProcessingType.DONE
            node.query = parsing_failed(language)
            node.summary = parsing_failed_summary(weblink.title, language)
            return False
        
        else:
            return True

    async def _no_rag_final_output(
        self,
        user_prompt: str,
        history_messages: List[dict],
        response: MindSearchResponse,
        background: str = '',
        model: str = '',
        language: str = constants.ENGLISH):
        
        pt_template = r1_refer_norag_pt if model == constants.DEEPSEEK_R1 else refer_norag_pt

        final_user_prompt = pt_template.format(
            background=background,
            user_prompt=user_prompt,
            current_datetime=datetime.now().strftime('%Y-%m-%d.'),
            language=language)

        logger.info(f"Mindesearch refer final response input: {len(history_messages)} {final_user_prompt[:600]}")

        async for chunk in super()._final_output(user_prompt=final_user_prompt, history_messages=history_messages):
            response.content = chunk
            yield response
        
        self._format_final_output(response=response)
        yield response

    async def _answer_guidance(
        self,
        response: MindSearchResponse,
        user_prompt: str,
        history_messages: List[dict],
        pubmed_results: List = [],
        background: str = '',
        language: str = constants.ENGLISH):
        
        # PubMed articles abstract
        pubmed_abstract = ("\n").join([
            f"""[article {index} begin]
                <title>{article.title}</title>
                <abstract>{article.summ}</abstract>
                <content>{article.content}</content>
                [article {index} end]"""
            for index, article in enumerate(pubmed_results, start=1)
        ])

        pubmed_abstract = tokenizer.truncate_by_tokens(pubmed_abstract, 50 * 1000, 'deepseek-r1')

        final_user_prompt = r1_response_guidance_pt.format(
            background=background,
            web_search=pubmed_abstract,
            user_question=user_prompt,
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language
        )

        def query(language: str):
            if language == constants.CHINESE:
                return f'整理搜索结果...'
            elif language == constants.JAPANESE:
                return f'検索結果を整理しています...'
            elif language == constants.ARABIC:
                return f' جارٍ تنظيم نتائج البحث...'
            else:
                return f'Organizing search results...'

        node = SearchNode(search_type=SearchType.ASSISTANT,
                          processing_type=ProcessingType.PROCESSING,
                          query=query(language=language),
                          search_results=self._copy_search_results(pubmed_results))
        
        response.search_graph.add_child(node)

        async for chunk in self.pubmed_assistatn_agent.stream_call(user_prompt=final_user_prompt):
            node.summary += chunk

        node.processing_type = ProcessingType.DONE
        self._format_summary_result(node)


    async def _final_output(
        self,
        user_prompt: str,
        history_messages: List[dict],
        response: MindSearchResponse,
        background: str = '',
        model: str = '',
        pubmed_results: List[WebSearchLink] = [],
        language: str = constants.ENGLISH):
        
        # PubMed articles abstract
        pubmed_abstract = ("\n").join([
            f"""[article {index} begin]
                <title>{article.title}</title>
                <abstract>{article.summ}</abstract>
                <content>{article.content}</content>
                [article {index} end]"""
            for index, article in enumerate(pubmed_results, start=1)
        ])

        pubmed_abstract = tokenizer.truncate_by_tokens(pubmed_abstract, 50 * 1000, 'deepseek-r1')
        # generate search source
        url_map = {item.url: self._format_final_source(id=index, search_result=item) for index, item in enumerate(pubmed_results, start=1)}
        runtime_info = {
            'source': list(url_map.values())
        }

        answer_guidance = ''
        if len(response.search_graph.children) > 0 and response.search_graph.children[-1].search_type == SearchType.HELPER:
            answer_guidance = response.search_graph.children[-1].summary
        
        if constants.DEEPSEEK_R1 == model:
            final_user_prompt = r1_pubmed_synthesis_pt.format(
                background=background,
                web_search=pubmed_abstract,
                user_question=user_prompt,
                current_date=datetime.now().strftime('%Y-%m-%d.'),
                language=language
            )
        else:
            final_user_prompt = ds_pubmed_final_user_pt.format(
                answer_guidance=answer_guidance,
                pubmed_results=pubmed_abstract,
                user_question=user_prompt,
                current_date=datetime.now().strftime('%Y-%m-%d.'),
                language=language)
        
        logger.info(f"Mindesearch PubMed final response input: {len(history_messages)} {final_user_prompt[:600]}...{final_user_prompt[-600:]}")

        async for chunk in super()._final_output(user_prompt=final_user_prompt, history_messages=history_messages):
            response.content = chunk
            yield response
        
        self._format_final_output(response=response, model=model, runtime_info=runtime_info)
        yield response

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):

        start_time = time.time()
  
        # init components
        yield self.helper.init_response(self)
        language, background, model, enable_rag = self._init_components(kwargs=kwargs)
        response = self._init_response(user_prompt, language)
        yield response

        # try query rewrite user's question
        query_results = []
        if enable_rag:
            # try rewrite user's query to PubMed query command
            async for tmp_response in self._task_with_heartbeat(response,
                                                                self._query_rewrite,
                                                                response,
                                                                query_results,
                                                                user_prompt,
                                                                history_messages,
                                                                background,
                                                                model,
                                                                language):
                yield tmp_response

        # user current question don't need query
        if response.search_graph and response.search_graph.search_type == SearchType.DISABLE:

            async for response in self._no_rag_final_output(user_prompt, history_messages, response, background, model, language):
                yield response

            logger.info(f"MindSearch PubMed final output: {response.content} cost {time.time() - start_time}s")
            return

        pubmed_results = self._sort_query_results(query_results)

        if len(pubmed_results) <= self.min_count:
            self._query_rewrite_fail(response, user_prompt, language)
            yield response
            logger.info(f"MindSearch PubMed query failed final output {response.content}")
            return
        
        # get best articles
        recommend_artilces = []
        async for tmp_response in self._task_with_heartbeat(
            response,
            self._get_recommend_articles,
            response,
            pubmed_results,
            user_prompt,
            recommend_artilces,
            language):
            yield tmp_response

        # read suggested articles
        async for tmp_response in self._task_with_heartbeat(
            response,
            self._try_read_articles,
            user_prompt,
            recommend_artilces,
            response,
            language):
            yield tmp_response

        # generate guidance
        async for tmp_response in self._task_with_heartbeat(
            response,
            self._answer_guidance,
            response,
            user_prompt,
            history_messages,
            pubmed_results,
            background,
            language):
            yield tmp_response
        
        # final response
        response.processing_type = ProcessingType.RESPONSING
        async for tmp_response in self._final_output(user_prompt=user_prompt, history_messages=history_messages, response=response,
                                                     background=background, model=model, pubmed_results=pubmed_results,
                                                     language=language):
            yield tmp_response

        response.processing_type = ProcessingType.RESPONSEDONE
        yield response
        logger.info(f"MindSearch PubMed final output: {response.content} cost {time.time() - start_time}s")


