# -*- coding: utf-8 -*-
import time
import json
import logging

from typing import List
from datetime import datetime
from openai.types.responses import Response

from i18n import tool_name as i18n_tool_name
from agent.knowledge.summary import search_and_selection
from agent.core.preset import AgentPreset
from agent.explore.helper import MindSearchHelper
from llm.base_model import BaseLLM
from llm.azure_models import GPT55
from tools.core.base_tool import BaseTool
from utils.utils.attachment import AttachmentManager
from agent.explore.mindsearch_rewrite_prompt_v4 import (
    gpt_rewrite_sys_pt, gpt_rewrite_user_pt
)
from agent.explore.schema import (
    MindSearchResponse, ProcessingType,
)
from agent.explore.schema import (
    MindSearchResponse, SearchType,
    SearchNode, ProcessingType,
)
from tools.explore.mindsearch_tools_v3 import (
    GeneralSearch, FunctionCallResult,
)
from tools.explore.rewrite_tools_v2 import (
    Clarification, RewrittenUserPrompt,
)

logger = logging.getLogger(__name__)


class MindSearchRewritingAgent(AgentPreset):
    llm: BaseLLM = GPT55
    sys_prompt: str = gpt_rewrite_sys_pt
    tools: List[BaseTool] = [
        GeneralSearch,
        Clarification,
        RewrittenUserPrompt,
    ]
    tool_choice: str = "required"


class MindSearchRewriteAgentV4(AgentPreset):
    llm: BaseLLM = GPT55
    
    # Agent template (do not mutate this object across requests)
    rewrite_agent: MindSearchRewritingAgent = MindSearchRewritingAgent()

    # Components
    helper: MindSearchHelper = MindSearchHelper()
    attachment_manager: AttachmentManager = AttachmentManager()

    max_thinking_rounds: int = 3

    def _init_components(
        self,
        kwargs):
        r"""
        Init agent components by language or whether need rag.
        """

        response = MindSearchResponse(
            search_graph=SearchNode(
                search_type=SearchType.UNKNOWN,
                thought_process='MindSearch Rewrite'
            ),
            processing_type=ProcessingType.PROCESSING
        )
        
        params = kwargs.get('params', {})
        language = self.helper.get_intention_language(params.get('language', ''))
        feedbacks = params.get('feedbacks', [])
        rewrites = params.get('rewrites', [])
        attachments = params.get('files', [])
        parent_id = params.get('parent_id', '')
        tool_use_context = params.get('tool_use_context', '')

        return response, language, feedbacks, rewrites, attachments, parent_id, tool_use_context

    def _add_thinking_node(
        self,
        response: MindSearchResponse,
        tool_name: str,
        language: str) -> SearchNode:
        
        node = SearchNode(
            search_type=SearchType.UNKNOWN,
            query=self._tool_name_translation(tool_name, language),
            processing_type=ProcessingType.THINKING)
        response.search_graph.add_child(node)

        return node

    def _tool_name_translation(
        self,
        tool_name: str,
        language: str):
        return i18n_tool_name(tool_name, language)

    async def _read_attachment(
        self,
        user_prompt: str,
        history_messages: List[dict],
        attachment_ids: List[str],
        parent_id: str,
        language: str,
        response: MindSearchResponse,
    ):
        if not attachment_ids and not parent_id:
            return
        
        # Start fetch attachment
        node = self._add_thinking_node(response, 'Attachment', language)
        yield response

        attachments = []
        if attachment_ids:
            attachments = self.attachment_manager.fetch_attachments(attachment_ids, True)

        # Start fetch parent attachment
        folders = []
        if parent_id:
            folders = self.attachment_manager.fetch_folders([parent_id])
            logger.info(f"[_read_attachment] parent_id: {parent_id}, folders detail: {folders}")
            # Knowledge base related attachments
            nattachment_ids = await search_and_selection(user_query=user_prompt, parent_id=parent_id)
            nattachements = self.attachment_manager.fetch_attachments(nattachment_ids, True)
            # if no attachments, try to fetch all attachments from folder
            if not nattachements:
                nattachements = self.attachment_manager.fetch_attachments_by_floder(parent_id, 1, 30)
            attachments = attachments + nattachements
        
        if not attachments:
            return

        # Filter out content attachments
        documents = [attachment for attachment in attachments if attachment['content']]

        # Filter out image attachments
        images = [attachment for attachment in attachments if attachment['type'] in ['image']]

        # Add attachments to runtime_info['url_map'] and history message
        attachments_chunks = ""
        if parent_id:
            folder = folders[0] if folders else None
            if folder:
                attachments_chunks = (
                    "There are user's knowledge base attachments preview content chunks "
                    f"knowledge base name: {folder.get('name')}, "
                    f"knowledge base id: {folder.get('id')}."
                )
        chunk_length = 4 * 1024 if len(documents) < 15 else 2 * 1024
        for document in documents:
            # add content asbtract
            content = document['content'].get('raw_content', '')

            # add content preview (truncated for context)
            if isinstance(content, list):
                content_preview = "\n".join(content)
            else:
                content_preview = content
            content_preview = content_preview[:chunk_length]
            # add history_messages
            attachments_chunks = attachments_chunks + f"""
Title: {document.get('name', '')}
Content Preview (Only first part of the whole document): {content_preview}
"""

        image_messages = []
        max_size = (768, 768) if len(images) > 3 else (1024, 1024)
        for image in images:
            compress_image = self.attachment_manager.fetch_images(image['storage'], max_size)
            if compress_image:
                image_messages.append({
                    "type": "input_image",
                    "image_url": f"data:image/{image['type']};base64,{compress_image}"
                })
        
        content_arr = []
        if attachments_chunks:
            content_arr = content_arr + [
                {'type': "input_text", "text": f"There are user upload attachment preview content chunks."},
                {'type': "input_text", "text": attachments_chunks},               
            ]
        if image_messages:
            content_arr = content_arr + [
                {'type': "input_text", "text": f"There are user upload image files."},
            ] + image_messages

        history_messages.append({
            "role": "user",
            "content": content_arr,
        })
        
        node.processing_type = ProcessingType.DONE

    async def _rewrite(
        self,
        user_prompt: str,
        history_messages: list[dict],
        rewrites: list,
        feedbacks: list,
        tool_use_context: str,
        language: str,
        response: MindSearchResponse,
    ):
        r"""
        1. Check whether need confirmation.
        2. Do web search for translation or fact checking.
        3. Rewriting.
        """

        self._add_thinking_node(response, None, language)
        yield response
        # history confirmation and user feedback
        nfb = ""
        for confirmation, feedback in zip(rewrites, feedbacks):
            nfb += f"Item to Confirm: {confirmation} \n User Answer: {feedback} \n"
        
        # Create per-request rewrite agent to avoid cross-request mutable state pollution.
        rewrite_agent = MindSearchRewritingAgent()

        force_rewrite = False
        # force rewrite user original question
        if len(feedbacks) >= 2 \
            or (len(feedbacks) > 0 and feedbacks[-1].strip().lower() == 'skip'): # user skip the clarification process
            force_rewrite = True
            rewrite_agent.tool_choice = {
                "type": "allowed_tools",
                "mode": "required",
                "tools": [
                    { "type": "function", "name": GeneralSearch.__name__ },
                    { "type": "function", "name": RewrittenUserPrompt.__name__ }
                ]
            }

        finished = False
        last_function_calls = 0
        llm_results = []

        for current_step in range(0, self.max_thinking_rounds):

            if current_step == 0 or len(llm_results) == 0:

                final_user_prompt = gpt_rewrite_user_pt.format(
                    current_date=datetime.now().strftime('%Y-%m-%d'),
                    language=language,
                    context=tool_use_context,
                    feedbacks=nfb,
                    user_question=user_prompt,
                )

                llm_response = rewrite_agent.use_tool(
                    user_prompt=final_user_prompt,
                    history_messages=history_messages,
                    reasoning={"effort": "medium", "summary": "auto"})
            else:

                llm_response = rewrite_agent.use_tool(
                    user_prompt='',
                    history_messages=history_messages[-last_function_calls:],
                    reasoning={"effort": "medium", "summary": "auto"},
                    previous_response_id=llm_results[-1].id,
                )

            nlast_function_calls = 0
            async for chunk in llm_response:
                    
                if isinstance(chunk, Response):
                    logger.info(f"[_query_rewrite_with_mindsearch] gpt output {chunk.output}")
                    llm_results.append(chunk)

                else:
                    # process fc result
                    # accumulate function calls，since chatgpt would return multi function calls，so we need add all back
                    nlast_function_calls += await self._process_fc_result(chunk, history_messages, language, response)

                    if chunk.name in [Clarification.__name__, RewrittenUserPrompt.__name__]:
                        finished = True

            last_function_calls = nlast_function_calls
        
            yield response

            if finished:
                break

        logger.info(f"[_rewrite] force_rewrite: {force_rewrite}, finished: {finished}")
        # Force call clarify or rewrite tool
        if not finished:
            # Force call rewrite tool
            if force_rewrite:
                logger.info(f"[_rewrite] force call rewrite tool")
                rewrite_agent.tool_choice = {
                    "type": "allowed_tools",
                    "mode": "required",
                    "tools": [
                        { "type": "function", "name": RewrittenUserPrompt.__name__ }
                    ]
                }
            else:
                # Force call clarify tool
                logger.info(f"[_rewrite] force call clarify tool")
                rewrite_agent.tool_choice = {
                    "type": "allowed_tools",
                    "mode": "required",
                    "tools": [
                        { "type": "function", "name": Clarification.__name__ }
                    ]
                }

            previous_response_id = llm_results[-1].id if llm_results else None
            llm_response = rewrite_agent.use_tool(
                user_prompt='',
                history_messages=history_messages[-last_function_calls:],
                reasoning={"effort": "medium", "summary": "auto"},
                previous_response_id=previous_response_id,
            )

            async for chunk in llm_response:
                    
                if isinstance(chunk, Response):
                    logger.info(f"[_query_rewrite_with_mindsearch] gpt output {chunk.output}")
                    llm_results.append(chunk)

                else:
                    # process fc result
                    # accumulate function calls，since chatgpt would return multi function calls，so we need add all back
                    await self._process_fc_result(chunk, history_messages, language, response)
        
            yield response            

    async def _process_fc_result(
        self,
        result: FunctionCallResult,
        history_messages: List[dict],
        language: str,
        response: MindSearchResponse,
    ) -> int:
        r"""
        1. update node query
        2. 
        """

        function_name = result.name
        node = self._add_thinking_node(response, function_name, language)

        # Format display node
        if function_name in [GeneralSearch.__name__]:
            # Format search result for llm model next step
            function_output = []
            for sub_query in result.result:
                tmp = {
                    'keyword_en': sub_query.get('keyword_en', ''),
                    'search_result': [],
                }
                for value in sub_query.get('search_result', {}).values():
                    tmp['search_result'].append({
                        'summ': value.get('summ', ''),
                        'title': value.get('title', ''),
                        'site_name': value.get('site_name', ''),
                    })
                function_output.append(tmp)
            
            message = {
                "call_id": result.call_id,
                "type": "function_call_output",
                "output": json.dumps(function_output, ensure_ascii=False),
            }
            history_messages.append(message)
            added_function_call_output = 1

        elif function_name == Clarification.__name__:
            response.content = result.result.get('prompt_to_user', '')
            added_function_call_output = 0

        elif function_name == RewrittenUserPrompt.__name__:
            response.content = result.result.get('rewritten_question', '')
            response.processing_type = ProcessingType.REWRITE
            added_function_call_output = 0
        else:
            added_function_call_output = 0

        node.processing_type = ProcessingType.DONE
        return added_function_call_output

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = None, images: List[str] = None, **kwargs):
        start_time = time.time()    
        history_messages = list(history_messages) if history_messages else []

        # init components
        response, language, feedbacks, \
            rewrites, attachments, parent_id, \
                tool_use_context = self._init_components(kwargs=kwargs)
        logger.info((
            f"[MindSearchRewrite] language: {language}, feedbacks: {feedbacks},"
            f"attachments: {attachments},"
            f"rewrites: {rewrites}, user_prompt: {user_prompt}, parent_id: {parent_id}"))

        # read attachment
        async for rsp in self._read_attachment(user_prompt, history_messages, attachments, parent_id, language, response):
            yield rsp

        async for rsp in self._rewrite(user_prompt, history_messages, rewrites, feedbacks, tool_use_context, language, response):
            yield rsp

        logger.info(f"MindSearch Rewrite final output {response.content} total cost {time.time() - start_time:.2f} seconds")
