
import logging

from typing import List, Any, Dict, Callable
from datetime import datetime
from openai.types.chat import ChatCompletionMessage

import agent.explore.constants as constants
from i18n import translate
from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini
from llm.moonshot_models import KimiK2Thinking
from agent.core.exceptions import ModerationFailure
from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3
from utils.sensitive_check.llm_moderator import topic_filter, political_topic_filter
from tools.core.base_tool import BaseTool
from utils.sensitive_check.diting import DitingSensitiveChecker


from agent.explore.mindsearch_prompt_v3 import (
    gpt_query_rewrite_user_pt, gpt_o_search_final_output_user_pt,
    kimi_thinking_sys_pt, kimi_search_final_output_sys_pt,
)
from tools.explore.mindsearch_tools_v3 import (
    FunctionCallResult,
    GeneralSearch, MedicalSearch, NewsSearch, PatentSearch,
    PubMedArticlesSearch, PubMedArticlesLocalSearch,
    ClinicalTrailSearch,
    ContentReader, Finished,
)
from agent.explore.schema import (
    MindSearchResponse, SearchNode, SearchType, WebSearchLink,
    ProcessingType
)

logger = logging.getLogger(__name__)


class MindSearchChinaThinkingAgent(AgentPreset):
    llm: BaseLLM = KimiK2Thinking
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        GeneralSearch,
        MedicalSearch,
        NewsSearch,
        PatentSearch,
        PubMedArticlesLocalSearch,
        PubMedArticlesSearch,
        ClinicalTrailSearch,
        ContentReader,
        Finished,
    ]
    tool_choice: str = "required"


class MindSearchChinaFinalOutputAgent(AgentPreset):
    llm: BaseLLM = KimiK2Thinking
    sys_prompt: str = ''
    tools: List[BaseTool] = []


class SensitiveChecker:
    
    sensitive_checker: DitingSensitiveChecker = DitingSensitiveChecker()

    def format_sensitive_content(self, language: str):
        return translate("ui.sensitive_response", language)

    async def _check_sensitive_query(
        self,
        user_prompt: str,
        history_messages: List[dict],
        background: str,
        attachments: List[dict],
    ):
        r"""
        Check whether user input is sensitive.
        """
        context = f"<user_question>{user_prompt}</user_question>\n"

        if background:
            context = context + f"<background>{background}</background>\n"

        # Filter out previous answers that are sensitive responses.
        from i18n.translations.ui import TRANSLATIONS as _ui_translations
        sensitive_values = set(_ui_translations["ui.sensitive_response"].values())
        for message in history_messages:
            if message.get('role') == 'assistant':
                if message.get('content') not in sensitive_values:
                    context = context + f"<previous_answer>{message.get('content')}</previous_answer>\n"
        
        sensitive_check = not (await self.sensitive_checker.simple_check(user_prompt, chunk_size=150))
        logger.info(f"MindSearch China agent input sensitive check result: {sensitive_check}")

        if not sensitive_check:
            sensitive_check = await political_topic_filter(context)
            logger.info(f"MindSearch China agent context check result: {sensitive_check}")
    
        return sensitive_check

class MindSearchChinaAgent(MindSearchAgentV3, SensitiveChecker):
    
    thinking_agent: MindSearchChinaThinkingAgent = MindSearchChinaThinkingAgent()
    final_output_agent: MindSearchChinaFinalOutputAgent =  MindSearchChinaFinalOutputAgent()

    async def _execute_thinking(
        self,
        current_step: int,
        last_function_calls: int,
        response: MindSearchResponse,
        runtime_info: dict,
        user_prompt: str,
        history_messages: List[dict],
        language: str,
    ) -> tuple[int, bool]:
        r"""
        Execute thinking actions, e.g. web search, web page reader.
        Return is the function calling counts and current task is whether finished. 
        """

        # Add a default node to tell user we are currently execute function calling.
        node = self._add_thinking_node(response, language)

        thinking_agent = self.thinking_agent
        if current_step == 0:

            thinking_agent.sys_prompt, final_user_prompt = self._format_thinking_prompt(user_prompt, language)
            llm_response = thinking_agent.use_tool(
                user_prompt=final_user_prompt,
                history_messages=history_messages)
        else:
            
            llm_response = thinking_agent.use_tool(
                user_prompt='',
                history_messages=history_messages,)
        
        nlast_function_calls = 0
        finished = False
        async for chunk in llm_response:
                
            if isinstance(chunk, ChatCompletionMessage):
                logger.info(f"[_query_rewrite_with_mindsearch] gpt output {chunk}")
                self._process_chunk(chunk, history_messages, runtime_info)
                
                # Kimi don't support tool_choice required.
                if not chunk.tool_calls:

                    sensitive_check = await self.sensitive_checker.simple_check(chunk.content, chunk_size=150, only_politics=True, min_ratio=0.2)
                    if not sensitive_check:
                        raise ModerationFailure("Output contains sensitive content during thinking process.")
                    
                    node = self._add_thinking_node(response, language)
                    node.query = translate("ui.search_finished", language)
                    node.summary = chunk.content
                    node.processing_type = ProcessingType.DONE
                    return nlast_function_calls, True

            elif not isinstance(chunk, FunctionCallResult):
                continue

            else:
                # process fc result
                # accumulate function calls，since chatgpt would return multi function calls，so we need add all back
                nlast_function_calls += 1

                node = self._add_thinking_node(response, language)
                runtime_info['tool_results'].append(chunk)
                await self._process_fc_result(chunk, history_messages, runtime_info, node, language)

                sensitive_check = await self.sensitive_checker.simple_check(node.query + node.summary, chunk_size=150, only_politics=True, min_ratio=0.2)
                if not sensitive_check:
                    raise ModerationFailure("Output contains sensitive content during thinking process.")

                # break process
                if chunk.name == Finished.__name__:
                    finished = True

        return nlast_function_calls, finished

    def _process_chunk(
        self,
        response: ChatCompletionMessage,
        history_messages: List[dict],
        runtime_info: dict = {}
    ) -> None:
        history_messages.append(response)
        runtime_info['llm_response'].append({
            'response': response,
            'function_calling_results': [],
        })
        
    def _format_history_message(
        self,
        result: FunctionCallResult,
        output: Any,
    ) -> Dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": result.id,
            "name": result.name,
            "content": output 
        }

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str,
    ) -> tuple[str, str]:
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        user_prompt = gpt_query_rewrite_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return kimi_thinking_sys_pt, user_prompt

    def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        # Response user's question
        websearch_results = self._format_final_searchresults(runtime_info, history_messages)

        final_user_prompt = gpt_o_search_final_output_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language,
            background=background,
            websearch_results=websearch_results,
            user_question=user_prompt)
        
        return kimi_search_final_output_sys_pt, final_user_prompt, history_messages
    
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        attachments = kwargs.get('params', {}).get('files', [])

        # Parse input parameters
        async for response, background, runtime_info, language, history_messages in self._init_agent(user_prompt, history_messages, images, **kwargs):
            yield response
        # IMPORTANT: Immediately return an empty node for frontend to show the user's question.
        # yield MindSearchResponse()

        if await self._check_sensitive_query(user_prompt, history_messages, background, attachments):
            yield MindSearchResponse(
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE
            )
            return
        
        try:
            async for res in super().use_tool(
                user_prompt=user_prompt,
                history_messages=history_messages,
                images=images,
                **kwargs,
            ):
                yield res
        except ModerationFailure as e:
            logger.warning(f"ModerationFailure caught in MindSearchChinaAgent: {e}")
            yield MindSearchResponse(
                search_graph=SearchNode(
                    search_type=SearchType.UNKNOWN,
                    query="",
                    key_word=""
                ),
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE
            )


class MindSearchChinaGPTAgent(MindSearchAgentV3, SensitiveChecker):

    llm: BaseLLM = GPT54Mini
    async def _init_agent(
        self,
        user_prompt: str,
        history_messages: List[dict],
        images: List[str],
        **kwargs,
    ):
        # Parse input parameters
        (
            language,
            background,
            history_messages,
            files,
            history_attachments,
            parent_id,
            user_email,
            task_id,
            attachment_fetch_mode,
        ) = self._init_components(history_messages=history_messages, kwargs=kwargs)

        # ********************IMPORTANT ********************
        # Immediately return an empty node for frontend to show the user's question.
        file_detail = []
        attachments = self.attachment_manager.fetch_attachments(files, mode=attachment_fetch_mode)
        if attachments:
            file_detail = [{'name': f.get('name'), 'id': f.get('id'), 'url': f.get('url')} for f in attachments]
        folder_detail = []
        folders = self.attachment_manager.fetch_folders([parent_id])
        if folders:
            folder_detail = [{'name': f.get('name'), 'id': f.get('id'), 'full_path': f.get('full_path')} for f in folders]

        yield MindSearchResponse(files=file_detail, folders=folder_detail), None, None, None, None

        # Init response
        response = self._init_response(user_prompt, attachments, folders, language)
        yield response, None, None, None, None

        # Init running time variable.
        runtime_info = {
            'llm_response': [], # Store thinking process's llm responses and function callings results.
            'tool_results': [], # Store thinking process's function callings results.
            'url_map': {}, # Store thinking process's web search results.
            'citation_id_map': {}, # Remove later
            'url_content_map': {}, 
            'attachment_url_map': {}, # attachment cache
            'last_step_hms_length': len(history_messages), # Store the length of history messages in the last step for future compact.
            'shell_result': [], # Store local shell task results.
            'attachments': [], # Store user uploaded files.
            'task_context': { # Store task context, e.g. task idm
                'task_id': task_id,
            },
            'generated_images': [], # Store generated images
            'priority_pubmed_ids': kwargs.get('priority_pubmed_ids', []),
            'attachment_fetch_mode': attachment_fetch_mode,
        }

        # Read attachments
        async for response in self._read_attachments(
            user_prompt,
            history_messages,
            files,
            history_attachments,
            folders,
            runtime_info,
            response,
            language,
            user_email):
            yield response, None, None, None, None

        yield response, background, runtime_info, language, history_messages
        
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        attachments = kwargs.get('params', {}).get('files', [])

        # Parse input parameters
        async for response, background, runtime_info, language, history_messages in self._init_agent(user_prompt, history_messages, images, **kwargs):
            yield response
        # IMPORTANT: Immediately return an empty node for frontend to show the user's question.
        # yield MindSearchResponse()

        if await self._check_sensitive_query(user_prompt, history_messages, background, attachments):
            yield MindSearchResponse(
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE
            )
            return
        
        try:
            async for res in super().use_tool(
                user_prompt=user_prompt,
                history_messages=history_messages,
                images=images,
                **kwargs,
            ):
                yield res
        except ModerationFailure as e:
            logger.warning(f"ModerationFailure caught in MindSearchChinaAgent: {e}")
            yield MindSearchResponse(
                search_graph=SearchNode(
                    search_type=SearchType.UNKNOWN,
                    query="",
                    key_word=""
                ),
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE
            )
            
    def _build_attachment_content_arr(
        self,
        attachment_ids: List[str],
        runtime_info: dict,
        format_attachment_link: Callable[[dict, dict], WebSearchLink],
    ) -> list:
        """
        Build the message content array for attachments and update runtime_info.
        """
        attachments = self.attachment_manager.fetch_attachments(
            attachment_ids,
            True,
            mode=runtime_info.get('attachment_fetch_mode', 'sql'),
        )
        # store attachments to runtime_info
        runtime_info['attachments'] = attachments
        if not attachments:
            logger.warning(f"[_build_attachment_content_arr] No attachments found")
            return '', [], []

        # Filter out content attachments
        documents = [attachment for attachment in attachments if attachment.get('content', '')]

        # Filter out image attachments
        images = [attachment for attachment in attachments if attachment.get('type', '') in ['image']]

        # Add attachments to runtime_info['url_map'] and history message
        attachments_chunks = ""
        for document in documents:
            # add runtime_info url_map
            attachment_link = format_attachment_link(document, runtime_info)
            if attachment_link is None:
                logger.warning("[_build_attachment_content_arr] Skip document attachment without url")
                continue
            runtime_info['url_map'][attachment_link.url] = attachment_link
            # add content asbtract
            content = document['content'].get('raw_content', document['content'].get('content',''))
            tokens = document.get('content', {}).get('tokens', 0)
            if tokens == 0:
                tokens = len(content) * 1.25
            runtime_info['attachment_url_map'][attachment_link.url] = content

            # add content preview (truncated for context)
            if isinstance(content, list):
                content_preview = content[:3]
            else:
                content_preview = content[:4096]
            # add history_messages
            attachments_chunks = attachments_chunks + f"""
[citation:{attachment_link.id}]
Title: {attachment_link.title}
Length: {tokens}
URL: {attachment_link.url}
Content Preview (Only first part of the whole document): {content_preview}
[citation:{attachment_link.id}]
"""

        image_messages = []
        image_urls = []
        max_size = (768, 768) if len(images) > 3 else (1024, 1024)
        for image in images:
            attachment_link = format_attachment_link(image, runtime_info)
            if attachment_link is None:
                logger.warning("[_build_attachment_content_arr] Skip image attachment without url")
                continue
            runtime_info['url_map'][attachment_link.url] = attachment_link
            image_urls.append({
                "url": attachment_link.url,
                "name": attachment_link.title,
            })
            
            compress_image = self.attachment_manager.fetch_images(image['storage'], max_size)
            if compress_image:
                image_messages.append({
                    "type": "input_image",
                    "image_url": f"data:image/{image['type']};base64,{compress_image}"
                })
        
        return attachments_chunks, image_messages, image_urls
