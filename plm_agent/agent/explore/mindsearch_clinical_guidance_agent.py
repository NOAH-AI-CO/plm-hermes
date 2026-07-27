import re
import copy
import time
import json
import asyncio
import logging
import elasticsearch

from datetime import datetime
from typing import List

import agent.explore.constants as constants
from agent.core.preset import AgentPreset
from agent.explore.mindsearch_agent import MindSearchOfficialAgent
from agent.explore.schema import MindSearchResponse, SearchNode, SearchType, ProcessingType
from agent.explore.mindsearch_clinical_guidance_prompt import (system_role, choose_subtree_pt,
                                                               r1_dt_guideline_pt, claude_guideline_pt,
                                                               claude_subtree_review_pt, claude_graph_pt, gemini_graph_pt,
                                                               claude_graph_review_pt)
from agent.explore.prompt import (search_final_output_pt, rag_r1_final_output_pt)
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini
from llm.gcp_models import CompositeClaudeChat, Gemini25Pro
from utils.core.standardize import standardize_yield_wo_dump
from tools.core.base_tool import BaseTool
from tools.explore.clinical_tools import GetClinicalGuidelineSubTree, CheckCurrentSubTree
from utils.tokenizer import tokenizer
from utils.core.elasticsearch_client import ElasticsearchClientSingleton
from config import api_config

logger = logging.getLogger(__name__)


class ClinicalGuidelineSubTreeChoosingAgent(AgentPreset):
    #llm: BaseLLM = GPT41 # local test
    llm: BaseLLM = CompositeClaudeChat # claude 35 reasoning part contains more detail, so we don't want to user 37
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        GetClinicalGuidelineSubTree
    ]
    #tool_choice: str = "required"
    tool_choice: str = {'type': 'any'}


class ClinicalGuidelineSubTreeReviewAgent(AgentPreset):
    #llm: BaseLLM = GPT41 # local test
    llm: BaseLLM = CompositeClaudeChat 
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        CheckCurrentSubTree
    ]
    #tool_choice: str = "required"
    tool_choice: str = {'type': 'any'}
    

class ClinicalGuidelineFinalOutputAgent(AgentPreset):
    # deepseek input max token is 128k, while clinical guideline may exceed, so we use GPT4.1
    #llm: BaseLLM = GPT41
    llm: BaseLLM = CompositeClaudeChat
    sys_prompt: str = system_role
    tools: List[BaseTool] = []
    #tool_choice: str = "required"
    tool_choice: str = {'type': 'any'}


class GraphAgent(AgentPreset):
    llm: BaseLLM = Gemini25Pro
    sys_prompt: str = ''
    tools: List[BaseTool] = []
    tool_choice: str = {'type': 'any'}


class GraphReviewAgent(AgentPreset):
    #llm: BaseLLM = GPT41
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: List[BaseTool] = []
    #tool_choice: str = "required"
    tool_choice: str = {'type': 'any'}


class MindSearchClinicalGuideline(MindSearchOfficialAgent):

    final_output_agent: ClinicalGuidelineFinalOutputAgent = ClinicalGuidelineFinalOutputAgent()
    sub_tree_choosing_agent: ClinicalGuidelineSubTreeChoosingAgent = ClinicalGuidelineSubTreeChoosingAgent()
    sub_tree_review_agent: ClinicalGuidelineSubTreeReviewAgent = ClinicalGuidelineSubTreeReviewAgent()
    graph_agent: GraphAgent = GraphAgent()
    graph_review_agent: GraphReviewAgent = GraphReviewAgent()
    es_client: elasticsearch.Elasticsearch = None
    
    def __init__(self, **kwarg):
        super().__init__()
        self.es_client = ElasticsearchClientSingleton.get_client()
    
    @standardize_yield_wo_dump
    async def start_wo_dump(self, *args, **kwargs):
        async for chunk in self.use_tool(*args, **kwargs):
            yield chunk

    def format_guideline(self, background: str):
        # load guideline
        guideline = json.loads(background)

        # convert guideline subtree id to index, since subtree id is es unique id
        for sub_tree in guideline['sub_tree']:
            sub_tree['es_id'] = sub_tree['id']
            # since elastic search result may change the sub tree order, so we sort the tree order
            sub_tree['id'] = sub_tree['id'].split('-')[-1] 
        guideline['sub_tree'].sort(key=lambda x: x['id'])

        # format guideline background
        guideline_background = ('/n').join(
            [
                f"<sub_tree_name>{sub_tree['name']}</sub_tree_name><description>{sub_tree['description']}</description>"
                for sub_tree in guideline['sub_tree'] if sub_tree['description']
            ]
        )
        return guideline, guideline_background

    def format_though_process(self, language: str):
            if constants.CHINESE == language:
                return '以下搜索、推理过程基于当前的临床指南信息'
            elif constants.JAPANESE == language:
                return '以下の検索および推論のプロセスは、最新の臨床ガイドラインに基づいています'
            elif constants.ARABIC == language:
                return 'تستند عملية البحث والاستدلال التالية إلى أحدث الإرشادات السريرية'
            else:
                return 'The following search and reasoning process is based on the latest clinical guidelines'
    
    async def _choose_subtrees(self,
                               response: MindSearchResponse,
                               user_prompt: str,
                               history_messages: List[dict],
                               guideline: dict,
                               language: str = constants.ENGLISH):
        
        def format_query(language: str):
            if constants.CHINESE == language:
                return '根据问题推断可能的子树'
            elif constants.JAPANESE == language:
                return '質問に基づいて、可能なサブツリーを推論する'
            elif constants.ARABIC == language:
                return 'استنتاج الفروع الفرعية المحتملة بناءً على السؤال'
            else:
                return 'Infer possible subtrees based on the question'

        node = SearchNode(search_type=SearchType.UNKNOWN,
                          query=format_query(language),
                          processing_type=ProcessingType.PROCESSING)
        if not response.search_graph:
            response.search_graph = SearchNode(search_type=SearchType.UNKNOWN,
                                               thought_process=self.format_though_process(language))
        response.search_graph.add_child(node)
        yield response

        background = []
        sub_trees = guideline.get('sub_tree', [])
        for index, sub_tree in enumerate(sub_trees, start=1):
            background.append({
                'id': index, # use ordinal id instead of real sub tree id to make it easy for llm to understand
                'name': sub_tree.get('name', ''),
                'disease': sub_tree.get('disease', []),
                'keywords': sub_tree.get('keywords', []),
                'description': sub_tree.get('description', ''),
            })

        final_user_prompt = choose_subtree_pt.format(background=background,
                                                     user_prompt=user_prompt,
                                                     current_datetime=datetime.now().strftime('%Y-%m-%d.'),
                                                     language=language)

        sub_tree_result = None
        async for chunk in self.sub_tree_choosing_agent.use_tool(user_prompt=final_user_prompt, history_messages=history_messages):
            sub_tree_result = chunk
        
        # get llm select sub tree index
        sub_tree_index = sub_tree_result.get('sub_tree_index', [])
        sub_tree_index = [id for id in sub_tree_index if id - 1 >= 0 and id - 1 < len(sub_trees)]
        
        if sub_tree_result:
            node.summary = f"<think>{sub_tree_result.get('reasoning', '')}\n</think>\n"
            sub_tree_names = (", ").join([
                sub_trees[id - 1].get('name', '')
                for id in sub_tree_index
            ])
            node.summary += f"Choosen sub trees: {sub_tree_names}"
        
        # Set status as done
        node.processing_type = ProcessingType.DONE
        logger.info(f"Choose subs tree index {sub_tree_index} {node.summary}")
        yield response

        # get sub tree raw text from elastic search
        search_result = self.es_client.search(
            index = 'clinical_guidelines_subtree',
            body = {
                "query": {
                    "terms": {
                        "_id": [
                            sub_trees[id - 1].get('es_id')
                            for id in sub_tree_index
                        ]
                    }
                },
                "fields": ["id", "raw_text"],
            }
        )
        for hit in search_result['hits']['hits']:
            source = hit['_source']
            for sub_tree in guideline['sub_tree']:
                if sub_tree['es_id'] == source['id']:
                    sub_tree['raw_text'] = source['raw_text']

    async def _review_choosen_sub_tree(self,
                                       response: MindSearchResponse,
                                       user_prompt: str,
                                       history_messages: List[dict],
                                       guideline: dict,
                                       guideline_background: str,
                                       language: str,):
        
        def format_query(language: str):
            if constants.CHINESE == language:
                return '检查当前选择的子树是否能够回答提问'
            elif constants.JAPANESE == language:
                return '現在選択されているサブツリーが質問に答えられるかを確認してください'
            elif constants.ARABIC == language:
                return 'تحقق مما إذا كان التفرع المحدد حاليًا يمكنه الإجابة على السؤال'
            else:
                return 'Check whether the currently selected subtree can answer the question'

        node = SearchNode(search_type=SearchType.UNKNOWN,
                          query=format_query(language),
                          processing_type=ProcessingType.PROCESSING)
        if not response.search_graph:
            response.search_graph = SearchNode(search_type=SearchType.UNKNOWN,
                                               thought_process=self.format_though_process(language))
        response.search_graph.add_child(node)
        yield response, True

        subtree = ('/n').join(
            [
                f"<sub_tree_name>{sub_tree['name']}</sub_tree_name><sub_tree>{sub_tree['raw_text']}</sub_tree>"
                for sub_tree in guideline['sub_tree'] if sub_tree['raw_text']
            ]
        )

        review_prompt = claude_subtree_review_pt.format(language=language,
                                                        background=guideline_background,
                                                        current_subtree=subtree,
                                                        user_prompt=user_prompt)

        subtree_review_result = None
        async for chunk in self.sub_tree_review_agent.use_tool(user_prompt=review_prompt, history_messages=history_messages):
            subtree_review_result = chunk
        
        if subtree_review_result:
            node.summary = f"<think>{subtree_review_result.get('reasoning', '')}\n</think>\n"

            sub_tree_index = subtree_review_result.get('sub_tree_index', [])
            sub_tree_index = [id for id in sub_tree_index if id - 1 >= 0 and id - 1 < len(guideline['sub_tree'])]

            sub_tree_names = (", ").join([
                guideline['sub_tree'][id - 1].get('name', '')
                for id in sub_tree_index
            ])
            node.summary += f"Suggestion sub trees: {sub_tree_names}"
        
        response.search_graph.children[-1].processing_type=ProcessingType.DONE

        is_relevant = subtree_review_result.get('is_relevant', True)

        if not is_relevant:
            def format_content(language: str):
                if constants.CHINESE == language:
                    return '当前选择的子树似乎无法回答您的提问，您可以回退到上一层或者选择建议的子树重新提问'
                elif constants.JAPANESE == language:
                    return '現在選択されているサブツリーでは、ご質問に答えられないようです。前の階層に戻るか、提案されたサブツリーを選んで再度質問してください'
                elif constants.ARABIC == language:
                    return 'لا يبدو أن التفرع المحدد حاليًا يمكنه الإجابة على سؤالك. يمكنك الرجوع إلى المستوى السابق أو اختيار أحد التفرعات المقترحة لإعادة طرح السؤال.'
                else:
                    return "The currently selected subtree doesn't seem to answer your question. You can go back to the previous level or choose one of the suggested subtrees to ask again."
        
            response.content = format_content(language=language)

        yield response, is_relevant

    async def _final_output_heartbeat(self, response: MindSearchResponse, user_prompt: str):
        task = asyncio.create_task(self._final_output(response=response, user_prompt=user_prompt))
        shielded = asyncio.shield(task)

        while not task.done():
            yield response
            await asyncio.sleep(1.0)
        
        _ = await shielded
        yield response
            
    def _format_final_output(self, guideline: dict, response: MindSearchResponse, model: str, language: str = constants.ENGLISH):
        r"""
            Match pattern [Guidance](page_num) and replace with simple [number]
        """

        self._update_finalout_node(response=response, language=language)

        pattern = r"\[([^\]]+)\]\((\d+)\)"
        # for nccn we should use original guideline link instead of file
        if guideline['source'] == 'nccn' and 'source_url' in guideline:
            def replace_func(match):
                attribute = match.group(1)
                return f"[{attribute}]({guideline['source_url']})"
            
            response.content = re.sub(pattern, replace_func, response.content)
        elif guideline['source'] == 'esmo' and 'doc_url' in guideline:
            def replace_func(match):
                attribute = match.group(1)
                num = match.group(2)
                return f"[{attribute}]({guideline['doc_url']}?page_num={num})"
            
            response.content = re.sub(pattern, replace_func, response.content)

    async def _draw_graphic(self, user_prompt: str, response: MindSearchResponse, background: str):
        
        raw_content = response.content
        yield raw_content + "\n\n# Graph Preparing....\n"

        output = ""
        buffer = ""
        last_yield_time = time.time()
        yield_interval = 0.3 # 调整输出时间间隔(秒)
        prompt = gemini_graph_pt.format(user_prompt=user_prompt,
                                        content=response.content)

        async for chunk in self.graph_agent.stream_call(prompt, max_tokens= 64 * 1024):
            buffer += chunk
            current_time = time.time()

            if current_time - last_yield_time >= yield_interval:
                output += buffer
                yield raw_content + "\n\n# Graph Preparing....\n" + output
                buffer = ""
                last_yield_time = current_time

        if buffer:
            output += buffer
            yield raw_content + "\n\n# Graph Preparing....\n" + output

        # remove thinking part
        logger.info(f'Graph result is : {output}')

        output = re.sub(r'<think>\s*(.*?)\s*</think>', r'', output, flags=re.DOTALL)
        #graph = re.sub(r'```', r'\`\`\`', graph)
        #graph = re.sub(r'\n\s*\n', '\n', graph.strip())
        output = self.helper.remove_empty_mermaid_blocks(output)
        if output != '':

            prompt = claude_graph_review_pt.format(mermaid_code=output)

            # user claude 3.7 thinking to review and fix graph issue
            output = ""
            buffer = ""
            last_yield_time = time.time()
            yield_interval = 0.3 # 调整输出时间间隔(秒)
        
            async for chunk in self.graph_review_agent.stream_call(prompt, temperature=1):
                buffer += chunk
                current_time = time.time()

                if current_time - last_yield_time >= yield_interval:
                    output += buffer
                    yield raw_content + "\n\n# Graph Preparing....\n" + output
                    buffer = ""
                    last_yield_time = current_time

            if buffer:
                output += buffer
                yield raw_content + "\n\n# Graph Preparing....\n" + output

            # remove thinking part
            logger.info(f'Review graph result is : {output}')
            output = re.sub(r'<think>\s*(.*?)\s*</think>', r'', output, flags=re.DOTALL)
                
            #graph = re.sub(r'```', r'\`\`\`', graph)
            #graph = re.sub(r'\n\s*\n', '\n', graph.strip())
            output = self.helper.remove_empty_mermaid_blocks(output)

            # remove other content
            output = self.helper.omit_markdown_block(output)

            logger.info(f'Fianl graph result is : {output}')

            if output != '':
                raw_content = raw_content + "\n\n# Graph\n" + output
        
        yield raw_content
        

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        r"""
        Mindsearch refer agent used for read article, news scenses.
        1. When enable_rag is true, we must search.
        2. The enable_rag is false, the output prompt would be very consice to avoid hallucination
        """
        start_time = time.time()

        # init components
        language, background, model, enable_rag = self._init_components(kwargs=kwargs)
        response = self.helper.init_response(self)
        yield response
        response.processing_type = ProcessingType.PROCESSING

        # get guideline tree from background
        guideline, guideline_background = self.format_guideline(background=background)

        # query rewrite
        if enable_rag:
            # user enable web search, try query rewrite
            async for tmp_response in self._query_rewrite(response=response,
                                                          query=user_prompt,
                                                          history_messages=copy.deepcopy(history_messages),
                                                          background=background,
                                                          language=language):
                yield tmp_response
        
        # request need web search retrieval augmented
        if response.search_graph and response.search_graph.search_type != SearchType.DISABLE:
            # fetch all search links and summarize, since it may took a long time, use heartbeat to avoid connection closed.
            async for tmp_response in self._task_with_heartbeat(response, 
                                                                self._scan_and_summary_search_link,
                                                                user_prompt,
                                                                response.search_graph.children,
                                                                response,
                                                                language):
                yield tmp_response

            # get web search summary from response search graph
            search_summary = self._format_rag_summary(response)

            pt_template = rag_r1_final_output_pt if model == constants.DEEPSEEK_R1 else search_final_output_pt

            final_user_prompt = pt_template.format(
                background=guideline_background,
                websearch_results=search_summary,
                user_prompt=user_prompt,
                current_datetime=datetime.now().strftime('%Y-%m-%d.'),
                language=language)
            
            # check r1 max token
            if constants.DEEPSEEK_R1 == model:
                if len(tokenizer.deepseek_v3(final_user_prompt, history_messages)) > 65536:
                    final_user_prompt = search_final_output_pt.format(background=guideline_background,
                                                                      websearch_results=search_summary,
                                                                      user_prompt=user_prompt,
                                                                      current_datetime=datetime.now().strftime('%Y-%m-%d.'),
                                                                      language=language)
                    self.final_output_agent = ClinicalGuidelineFinalOutputAgent()
            
        else:
            # if not choose sub tree, use llm select one sub tree
            if not guideline.get('choosen_subtree', False):
                async for tmp_response in self._choose_subtrees(response=response,
                                                                user_prompt=user_prompt,
                                                                history_messages=history_messages,
                                                                guideline=guideline,
                                                                language=language):
                    yield tmp_response
            else:
                # fetch sub tree raw text from choosen ids
                async for tmp_response, is_relevant in self._review_choosen_sub_tree(response=response,
                                                                                     user_prompt=user_prompt,
                                                                                     history_messages=history_messages,
                                                                                     guideline=guideline,
                                                                                     guideline_background=guideline_background,
                                                                                     language=language):
                    yield tmp_response

                if not is_relevant:
                    return
            
            # guideline may be decision tree or common description, so we have to check the guideline type
            if guideline['source'] in ['NCCN', 'ESMO']:
                pt_template = r1_dt_guideline_pt if constants.DEEPSEEK_R1 == model else claude_guideline_pt

                background = ('/n').join(
                    [
                        f"<sub_tree_name>{sub_tree['name']}</sub_tree_name><sub_tree>{sub_tree['raw_text']}</sub_tree>"
                        for sub_tree in guideline['sub_tree'] if sub_tree['raw_text']
                    ]
                )

                final_user_prompt = pt_template.format(
                    language=language,
                    publish_date=guideline.get('publication_date', None) or datetime.now().strftime('%Y-%m-%d.'),
                    background=background,
                    user_prompt=user_prompt)
                
                # check r1 max token
                if constants.DEEPSEEK_R1 == model:
                    r1_encode_length = len(tokenizer.deepseek_v3(final_user_prompt, history_messages))
                    logger.info(f'Current length is max than deepseek thinking {r1_encode_length}')
                    if r1_encode_length > 64 * 1024:
                        final_user_prompt = claude_guideline_pt.format(language=language,
                                                                   publish_date=guideline.get('publication_date', None) or datetime.now().strftime('%Y-%m-%d.'),
                                                                   background=background,
                                                                   user_prompt=user_prompt)
                        self.final_output_agent = ClinicalGuidelineFinalOutputAgent()

            else:
                pass

        logger.info(f"Mindesearch clinicl-guideline final response input: {len(history_messages)} {final_user_prompt[:800]}...{final_user_prompt[-800:]}")

        # add search node to notify user, generating final response
        self._add_finalout_node(response=response, language=language)
        yield response

        # change model since clinical guidance may be too big
        async for chunk in self._final_output(user_prompt=final_user_prompt, history_messages=history_messages):
            # remove model preparing notice
            response.content = chunk
            yield response
        
        self._format_final_output(guideline, response, model, language)
        yield response

        # try draw graph
        async for chunk in self._draw_graphic(user_prompt=user_prompt, response=response, background=background):
            response.content = chunk
            yield response

        response.processing_type = ProcessingType.RESPONSEDONE
        yield response

        logger.info(f"MindSearch clinicl-guideline final output: {response.content} cost {time.time() - start_time}s")
