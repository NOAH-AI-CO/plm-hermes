# -*- coding: utf-8 -*-
import re
import copy
import time
import json
import base64
import asyncio
import logging

import httpx
import openai
import anthropic
import tiktoken

from io import BytesIO
from typing import List, Callable, Any, Dict
from datetime import datetime
from urllib.parse import urlparse, unquote
from openai.types.responses import Response
from agent.knowledge.summary import search_and_selection
from utils.citation.citation_generator import generate_citation

import agent.explore.constants as constants
from i18n import translate, tool_name as i18n_tool_name
from agent.explore.helper import MindSearchHelper
from agent.core.preset import AgentPreset
from agent.bp.pp import fetch_context_single
from agent.core.exceptions import ModerationFailure
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini, GPT5Nano
from llm.openai_models import Openai5Mini
from llm.composite_models import CompositeGPT5
from llm.gcp_models import ClaudeSonnet46
from lite_llm import AzureOpenAI51Codex
from lite_llm.aliyun_models import AliyunWanImageGeneration
from lite_llm.exceptions import LLMIncomplete
from lite_llm.openai_models import OpenAIImage2
from agent.core.exceptions import ModerationFailure
from agent.iit.gl_toc_builder import pdf_to_text
from tools.core.base_tool import BaseTool
from utils.scholar import SCIIF
from utils.web_search import ContentFetcher
from utils.core.prompt_fetcher import PromptFetcher
from utils.pubmed_opt.pubmed_reader import PubMedReader
from utils.sensitive_check.diting import DitingSensitiveChecker
from utils.utils.attachment import AttachmentManager, Storage
from utils.tokenizer import tokenizer
from logging_config import task_id_var

from agent.explore.mindsearch_prompt_v3 import (
    gpt_thinking_sys_pt, gpt_query_rewrite_user_pt,
    gpt_5_search_final_output_sys_pt, gpt_o_search_final_output_user_pt,
    gpt_reading_sys_pt, gpt_reading_user_pt,
    gpt_compact_sys_pt, gpt_compact_user_pt,
)
from tools.explore.mindsearch_tools_v3 import (
    FunctionCallResult,
    GeneralSearch, MedicalSearch, NewsSearch, PatentSearch,
    StockGeneralSearch, StockNewsSearch, StockHistoricalPriceQuery,
    CompanyPressReleasesNewsQuery, CompanyInfoQuery,
    FinancialStatements, ChinaCompanyFinancialStatements,
    PubMedArticlesSearch, PubMedArticlesLocalSearch,
    DrugManualSearch, ClinicalGuidelineSearch,
    ContentReader, Finished,
    DocumentSearch, DocumentReader, DocumentSearchFinished,
    ClinicalTrailSearch, ImageGeneration, ImageEdit, 
    KnowledgeBasePreview,
)
from tools.sandbox import AgentRunSandbox, AgentRunSandboxExecutor
from tools.explore.attachment_tools import AttachmentDownload
from agent.explore.schema import (
    MindSearchResponse, SearchNode, SearchType, WebSearchLink,
    ProcessingType
)

logger = logging.getLogger(__name__)


class MindSearchThinkingAgent(AgentPreset):
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        GeneralSearch,
        MedicalSearch,
        NewsSearch,
        PatentSearch,
        PubMedArticlesLocalSearch,
        PubMedArticlesSearch,
        DrugManualSearch,
        ClinicalGuidelineSearch,
        StockHistoricalPriceQuery,
        StockNewsSearch,
        ContentReader,
        AttachmentDownload,
        AgentRunSandbox,
        ClinicalTrailSearch,
        ImageGeneration,
        #ImageEdit,
        Finished,
    ]
    tool_choice: str = "required"


class MindSearchFinalOutputAgent(AgentPreset):
    llm: BaseLLM = CompositeGPT5
    sys_prompt: str = ''
    tools: List[BaseTool] = []


class DocumentReadingAgent(AgentPreset):
    llm: BaseLLM = GPT5Nano
    sys_prompt: str = gpt_reading_sys_pt
    tools: List[BaseTool] = []


class CompactHistoryMessagesAgent(AgentPreset):
    llm: BaseLLM = GPT5Nano
    sys_prompt: str = gpt_compact_sys_pt
    tools: List[BaseTool] = []


class MindSearchAgentV3(AgentPreset):
    # LLMs
    llm: BaseLLM = CompositeGPT5
    codex_llm: AzureOpenAI51Codex = AzureOpenAI51Codex()
    wan_image_llm: AliyunWanImageGeneration = AliyunWanImageGeneration()
    image2_llm: OpenAIImage2 = OpenAIImage2()

    # Sub Agents
    thinking_agent: MindSearchThinkingAgent = MindSearchThinkingAgent()
    final_output_agent: MindSearchFinalOutputAgent =  MindSearchFinalOutputAgent()
    reading_agent: DocumentReadingAgent = DocumentReadingAgent()
    compact_agent: CompactHistoryMessagesAgent = CompactHistoryMessagesAgent()

    # Compotents    
    webpage_fetcher: ContentFetcher = ContentFetcher()
    pt_fetcher: PromptFetcher = PromptFetcher()
    helper: MindSearchHelper = MindSearchHelper()
    sci_if_client: SCIIF = SCIIF()
    pmc_reader: PubMedReader = PubMedReader()
    attachment_manager: AttachmentManager = AttachmentManager()
    image_storage: AttachmentManager = AttachmentManager(public=True)

    # Sensitive checker
    sensitive_checker: DitingSensitiveChecker = None
    
    # AgentRun sandbox executor (for AgentRunSandbox tool, e.g. Finance)
    agentrun_sandbox_executor: AgentRunSandboxExecutor = None

    # Session ID for persistent workspace (thread_id from Backend)
    thread_id: str = ''

    # Language control flags from API params
    force_output_language: bool = False
    preferred_output_language: str = ''

    # Sandbox URL placeholder prefix
    sandbox_url_prefix: str = r"SANDBOX_URL_PLACEHOLDER_"

    # Tiktoken encoding for GPT models
    _tiktoken_enc = tiktoken.encoding_for_model("gpt-4o")

    # Constant variables
    max_thinking_rounds: int = 7
    attachment_length: int = 60000
    compact_max_item_tokens: int = 150000 # Token count
    proactive_compact_threshold: int = 100000 # Trigger proactive compaction above this token count
    single_content_max_lenght: int = 50000 # Characters count
    max_concurrent_tasks: int = 3
    retry_sleep_timespan: int = 25 # Seconds
    final_output_source_max_length: int = 30
    max_source_count: int = 30

    def _resolve_attachment_fetch_mode(self, client_ip: str) -> str:
        return 'api' if client_ip == '121.43.134.95' else 'sql'

    def _estimate_history_tokens(self, history_messages: List[dict]) -> int:
        """Fast token estimation via tiktoken. Used for proactive compaction threshold check."""
        full_text = "".join(str(msg) for msg in history_messages)
        return len(self._tiktoken_enc.encode(full_text))

    def _mask_sandbox_urls(self, text: str, runtime_info: dict) -> str:
        """Replace long OSS-signed sandbox URLs with short placeholders before they
        enter history / shell_result, to keep the final-output LLM input within
        token limits. Real URLs are restored in `_unmask_sandbox_urls`.

        Storage: a single `url -> placeholder` map under `runtime_info['sandbox_url_map']`.
        Mask path needs O(1) dedup-by-url, so this direction is the cheap one;
        unmask flips it on the fly."""

        sandbox_url_pattern = re.compile(
            r'https?://[^\s\)\]\"\'<>]*oss-cn-hangzhou\.aliyuncs\.com[^\s\)\]\"\'<>]*'
        )

        if not isinstance(text, str) or not text:
            return text
        url_to_placeholder: dict = runtime_info.setdefault('sandbox_url_map', {})

        def _repl(match: re.Match) -> str:
            url = match.group(0)
            placeholder = url_to_placeholder.get(url)
            if placeholder is None:
                placeholder = f"[[{self.sandbox_url_prefix}{len(url_to_placeholder)}]]"
                url_to_placeholder[url] = placeholder
            return placeholder

        return sandbox_url_pattern.sub(_repl, text)

    def _unmask_sandbox_urls(self, text: str, runtime_info: dict) -> str:
        """Restore real OSS URLs from `[[<sandbox_url_prefix>N]]` placeholders by
        flipping the stored `url -> placeholder` map (called once at final-output time)."""

        sandbox_placeholder_pattern = re.compile(rf'\[\[{re.escape(self.sandbox_url_prefix)}\d+\]\]')

        if not isinstance(text, str) or not text:
            return text
        url_to_placeholder = runtime_info.get('sandbox_url_map') or {}
        if not url_to_placeholder:
            return text
        placeholder_to_url = {p: u for u, p in url_to_placeholder.items()}

        def _repl(match: re.Match) -> str:
            return placeholder_to_url.get(match.group(0), match.group(0))

        return sandbox_placeholder_pattern.sub(_repl, text)

    def _age_history_content(self, history_messages: List[dict], preserve_last_n: int = 2):
        """
        Progressively truncate older function_call_output content in history.

        Tiers (by distance from end of fc_output list):
        - Last preserve_last_n outputs: keep full
        - 2-3 away: truncate to 20,000 chars
        - 4+ away: truncate to 5,000 chars
        """
        fc_indices = [
            i for i, msg in enumerate(history_messages)
            if isinstance(msg, dict) and msg.get('type') == 'function_call_output'
        ]

        if len(fc_indices) <= preserve_last_n:
            return

        total = len(fc_indices)
        for rank, idx in enumerate(fc_indices):
            distance = total - 1 - rank
            if distance < preserve_last_n:
                continue

            output = history_messages[idx].get('output', '')
            if not isinstance(output, str):
                continue

            limit = 5000 if distance >= 4 else 20000
            if len(output) > limit:
                history_messages[idx]['output'] = output[:limit] + f"\n[...truncated from {len(output)} chars...]"

    # Thinking process
    async def _thinking(
        self,
        response: MindSearchResponse,
        runtime_info: dict,
        user_prompt: str,
        history_messages: List[dict],
        background: str = '',
        language: str = constants.ENGLISH):
        
        # Add background to history_messages the end.
        if background:
            history_messages.append({
                'role': 'user',
                'content': f'Current conversation background: {background}'
            })

        # Searching global context
        finished = False
        last_function_calls = 0

        try:
            for i in range(0, self.max_thinking_rounds):

                try:
                    last_function_calls, finished  = await self._execute_thinking(
                        i,
                        last_function_calls,
                        response,
                        runtime_info,
                        user_prompt,
                        history_messages,
                        language
                    )
                    if finished:
                        break

                    # Proactive compaction: age old content, then check token count
                    self._age_history_content(history_messages)
                    estimated_tokens = self._estimate_history_tokens(history_messages)
                    if estimated_tokens > self.proactive_compact_threshold:
                        logger.info(f"[ProactiveCompact] {estimated_tokens} tokens > {self.proactive_compact_threshold}, compacting")
                        await self._compact_history_messages(history_messages, user_prompt, runtime_info)

                except (openai.APITimeoutError) as ex:
                    logger.warning(f"Call llm timeout, Error code: {ex.code}, Error message: {ex}")
                    await asyncio.sleep(self.retry_sleep_timespan)

                except (openai.APIError) as ex:
                    logger.warning(f"Call llm API error for Error code: {ex.code}, Error message: {ex}")
                    if ex.code == 'context_length_exceeded':

                        # Try compact history messages and clean llm_response.
                        logger.info(f"Context length exceeded, try to compact history messages")
                        await self._compact_history_messages(history_messages, user_prompt, runtime_info)

                    elif ex.code in ['rate_limit_exceeded', 'too_many_requests']:
                        logger.warning(f"Rate limit exceeded, sleep 25 seconds and continue to think.")
                        await asyncio.sleep(self.retry_sleep_timespan)

                    elif 'Duplicate item' in str(ex):
                        # Duplicate response ID in history — rebuild clean state
                        logger.warning(f"Duplicate response ID detected, rebuilding history_messages")
                        history_messages.clear()
                        history_messages.extend(runtime_info['original_history_messages'])
                        if self._check_history_results(runtime_info):
                            search_results = self._format_final_searchresults(runtime_info, history_messages)
                            history_messages.append({'role': 'assistant', 'content': search_results})
                        runtime_info['llm_response'].clear()
                        last_function_calls = 0

                except (anthropic.APIStatusError) as ex:
                    logger.warning(f"Call Anthropic API error: status_code={ex.status_code}, message={ex}")
                    if ex.status_code == 413:
                        logger.info(f"Context length exceeded, try to compact history messages")
                        await self._compact_history_messages(history_messages, user_prompt, runtime_info)
                    elif ex.status_code in [429, 529]:
                        logger.warning(f"Rate limited or overloaded, sleep {self.retry_sleep_timespan}s and continue.")
                        await asyncio.sleep(self.retry_sleep_timespan)

                except (ModerationFailure) as ex:
                    logger.warning(f"Moderation failure, Error message: {ex}")
                    raise ex

                except Exception as ex:
                    logger.warning(f"Call llm failed, Error message: {ex}", exc_info=True)

            if not finished:
                # To avoid search don't end with finished
                # Set tool_choice to force Finished function
                logger.info(f"Invode Finished Function.")
                if Finished in self.thinking_agent.tools:
                    self.thinking_agent.tool_choice = { "type": "function", "name": Finished.__name__}
                elif DocumentSearchFinished in self.thinking_agent.tools:
                    self.thinking_agent.tool_choice = { "type": "function", "name": DocumentSearchFinished.__name__ }

                # Force execute finished function.
                try:
                    await self._execute_thinking(
                        self.max_thinking_rounds,
                        last_function_calls,
                        response,
                        runtime_info,
                        user_prompt,
                        history_messages,
                        language
                    )
                except (ModerationFailure) as ex:
                    logger.warning(f"Moderation failure, Error message: {ex}")
                    raise ex
                except Exception as ex:
                    # Just by pass, since it's already added a failed node.
                    logger.warning(f"Call llm failed, Error message: {ex}")
                    node = self._add_thinking_node(response, language)
                    node.processing_type = ProcessingType.FAILED
                    pass
        finally:
            # Cleanup sandbox at end of thinking session.
            # asyncio.shield prevents CancelledError from aborting the cleanup
            # when the client disconnects mid-stream (Starlette cancel scope).
            if self.agentrun_sandbox_executor is not None:
                try:
                    await asyncio.shield(self.agentrun_sandbox_executor.close())
                    logger.info("[AgentRunSandbox] Sandbox cleaned up after thinking session")
                except asyncio.CancelledError:
                    logger.warning("[AgentRunSandbox] Sandbox cleanup cancelled by disconnect, spawning background task")
                    asyncio.get_event_loop().create_task(self.agentrun_sandbox_executor.close())
                except Exception as e:
                    logger.warning(f"[AgentRunSandbox] Failed to cleanup sandbox: {e}")

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

        # Add a default node to tell user we are currently 
        node = self._add_thinking_node(response, language)

        # We can mix model to optimize performance, e.g. first time use gpt-5 and followings are gpt-5-mini
        # So the first time would generate thoughtfull thinking results.
        # While azure don't support mix models.
        thinking_agent = self.thinking_agent
        reasoning = {"effort": "medium", "summary": "auto"}
        if current_step == 0 or not runtime_info['llm_response']:

            # To improve llm performance, set effort as high, while it cost too long.
            #reasoning = {"effort": "high", "summary": "auto"}
            thinking_agent.sys_prompt, final_user_prompt = self._format_thinking_prompt(user_prompt, language)
            llm_response = thinking_agent.use_tool(
                user_prompt=final_user_prompt,
                history_messages=history_messages,
                reasoning=reasoning,
                max_output_tokens=1024 * 24)
        else:
            
            llm_response = thinking_agent.use_tool(
                user_prompt='',
                history_messages=history_messages[-last_function_calls:],
                reasoning=reasoning,
                previous_response_id=runtime_info['llm_response'][-1]['response'].id,
                max_output_tokens=1024 * 24)
        
        nlast_function_calls = 0
        finished = False
        async for chunk in llm_response:
                
            if isinstance(chunk, Response):
                logger.info(f"[_query_rewrite_with_mindsearch] gpt output {chunk.output}")
                
                # check chunk status
                if chunk.status in ['incomplete', 'failed']:
                    logger.warning(f"[_execute_thinking] Thinking is incomplete for {chunk.incomplete_details}, try again")
                    # try another model
                    self.thinking_agent.llm = Openai5Mini
                    # check history messages, compact search
                    if self._check_history_results(runtime_info):
                        search_results = self._format_final_searchresults(runtime_info, history_messages)
                        # clean history messages to avoid response id
                        history_messages.clear()
                        history_messages.extend(runtime_info['original_history_messages'])
                        history_messages.append({
                            'role': 'assistant',
                            'content': search_results,
                        })
                    
                    # reset last function calls to avoid multiple chunks
                    nlast_function_calls = 0
                    break # break the async for loop avoid continue chunk is completed

                elif chunk.status == 'completed':
                    self._process_chunk(chunk, history_messages, runtime_info)
                
            elif isinstance(chunk, FunctionCallResult):
                # process fc result
                # accumulate function calls，since chatgpt would return multi function calls，so we need add all back
                nlast_function_calls += 1
                logger.info(f"[_execute_thinking] Processing function call: {chunk.name}")

                node = self._add_thinking_node(response, language)
                runtime_info['tool_results'].append(chunk)
                await self._process_fc_result(chunk, history_messages, runtime_info, node, language)
                logger.info(f"[_execute_thinking] Function call {chunk.name} processed, node.query={node.query[:50] if node.query else None}, node.processing_type={node.processing_type}")

                # break process
                if chunk.name in [Finished.__name__, DocumentSearchFinished.__name__, ImageGeneration.__name__, ImageEdit.__name__]:
                    finished = True
                    logger.info(f"[_execute_thinking] Finished tool called, ending thinking")

        return nlast_function_calls, finished
    
    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str
    ) -> tuple[str, str]:
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        user_prompt = gpt_query_rewrite_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return gpt_thinking_sys_pt, user_prompt
    
    def _add_thinking_node(
        self,
        response: MindSearchResponse,
        language: str
    ) -> SearchNode:
        r"Add thinking node tips."

        # Give user an immediately response.
        if len(response.search_graph.children) > 0:
            node = response.search_graph.children[-1]
            if node.processing_type == ProcessingType.THINKING:
                return node

        node = SearchNode(
            search_type=SearchType.UNKNOWN,
            query=translate("ui.think", language),
            processing_type=ProcessingType.THINKING)
        response.search_graph.add_child(node)

        return node
    
    def _process_chunk(
        self,
        response: Response,
        history_messages: List[dict],
        runtime_info: dict = {}):
        
        r"""
        So far this function only support Azure openai model, since the function calling result are stored in tool_calls.
        https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/function-calling
        While Openai has already use another parameters.
        https://platform.openai.com/docs/guides/function-calling

        1. Save reasoning response in history messages.
        2. Update frontend display.
        """

        """
        for item in response:
            if item.type == 'reasoning':
                history_messages.append({
                    'id': item.id,
                    'type': 'reasoning',
                    'summary': item.summary
                })
            elif item.type == 'function_call':
                history_messages.append({
                    'type': 'function_call',
                    'name': item.name,
                    'call_id': item.call_id,
                    'arguments': item.arguments,
                })
        """
        # Save history messages for future compact.
        # Only openai and claude use extended history messages, since they use response items which is a list.
        # Gemini must use append since it's a single item.
        history_messages.extend(response.output)
        
        # Save response content
        # We save response content and function calling results in llm_response by tuple, i.e. (response, function_calling_results).
        runtime_info['llm_response'].append({
            'response': response,
            'function_calling_results': [],
        })
                
    def _tool_name_translation(
        self,
        tool_name: str,
        language: str):
        r"""
        Mindsearch tool name translation.
        """
        return i18n_tool_name(tool_name, language)

    async def _handle_image_generation(
        self,
        result: FunctionCallResult,
        node: SearchNode,
        history_messages: List[dict],
        runtime_info: dict,
        language: str,
    ) -> None:
        """
        Handle ImageGeneration tool result: generate image via LLM and save to storage.
        Override this method in subclasses to customize image generation behavior.
        """
        
        function_name = result.name
        node.query = self._tool_name_translation(function_name, language)

        image_prompt = result.args.get('image_prompt', '')
        image_name = result.args.get('image_name', '')
        image_name = image_name.split('.')[0] # avoid image name with extension like .png, .jpg and generate error oss link

        related_image_urls = result.args.get('related_image_urls', [])

        try:
            image_url = await self._llm_image_generation(image_prompt, image_name, related_image_urls, runtime_info)
        except Exception as e:
            logger.error(f"Error in _handle_image_generation: {e}")
            image_url = None
        
        if image_url:
            node.summary = node.summary + f"\n\n**Image:** [{image_name}]({image_url})"

            runtime_info['generated_images'].append({
                "url": image_url,
                "name": image_name,
            })
            output = [
                {
                    "type": "input_text",
                    #"text": f"Image generated successfully. Image Name: {image_name}, URL: {image_url}",
                    "text": f"Image generated successfully. Image Name: {image_name}",
                },
                {
                    "type": "input_image",
                    "image_url": image_url,
                }
            ]
        else:
            output = [
                {
                    "type": "input_text",
                    "text": f"Image generation failed.",
                }
            ]
            runtime_info['generated_images'].append({
                "name": image_name,
                "status": "failed",
            })

        message = self._format_history_message(result, output)
        history_messages.append(message)
        runtime_info['llm_response'][-1]['function_calling_results'].append(message)
    
    async def _llm_image_generation(
        self,
        image_prompt: str,
        image_name: str,
        related_image_urls: List[str],
        runtime_info: dict,
    ) -> str:
        """Generate image via Wan 2.6. Returns image URL or None."""
        try:
            wan_image_url = await self.wan_image_llm.image_generate(prompt=image_prompt)
            if not wan_image_url:
                logger.warning(f"Wan 2.6 image generation failed")
                return None

            image_path = f"generated-images"
            task = runtime_info['task_context'].get('task_id')
            if task:
                image_path = image_path + f"/{task}"
            
            # Save image to storage
            async with httpx.AsyncClient() as client:
                resp = await client.get(wan_image_url)
                if resp.status_code == 200:
                    image_data = resp.content
                    image_url = self.image_storage.save_image(
                        storage_meta={
                            "storage": Storage.AZURE_BLOB.value,
                            "container": "nudata",
                            "blob": f"{image_path}/{image_name}.png",
                        },
                        base64_data=image_data,
                    )
                    if image_url:
                        return image_url

        except Exception as e:
            logger.error(f"Error in _llm_image_generation: {e}")
            return None

    async def _handle_image_edit(
        self,
        result: FunctionCallResult,
        node: SearchNode,
        history_messages: List[dict],
        runtime_info: dict,
        language: str,
    ) -> None:
        function_name = result.name
        node.query = self._tool_name_translation(function_name, language)

        image_prompt = result.args.get('image_prompt', '')
        image_name = result.args.get('image_name', '')
        image_name = image_name.split('.')[0]
        source_image_url = result.args.get('source_image_url', '')

        try:
            source_image_bytes = None
            if source_image_url:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(source_image_url)
                    resp.raise_for_status()
                    source_image_bytes = resp.content

            if not source_image_bytes:
                logger.warning(f"_handle_image_edit: failed to download source image from {source_image_url}")
                raise ValueError("Source image is required for image editing")

            b64_list = await self.image2_llm.edit_image(
                prompt=image_prompt,
                image=source_image_bytes,
            )

            if not b64_list:
                raise ValueError("Image edit returned empty result")

            image_data = base64.b64decode(b64_list)

            image_path = "generated-images"
            task = runtime_info['task_context'].get('task_id')
            if task:
                image_path = f"{image_path}/{task}"

            image_url = self.image_storage.save_image(
                storage_meta={
                    "storage": Storage.AZURE_BLOB.value,
                    "container": "nudata",
                    "blob": f"{image_path}/{image_name}.png",
                },
                base64_data=image_data,
            )
        except Exception as e:
            logger.error(f"Error in _handle_image_edit: {e}")
            image_url = None

        if image_url:
            node.summary = node.summary + f"\n\n**Image:** [{image_name}]({image_url})"
            runtime_info['generated_images'].extend([
                {
                    "url": source_image_url,
                    "name": 'edit-source-image',
                    "type": "source",
                },
                {
                    "url": image_url,
                    "name": image_name,
                    "type": "edit",
                },
            ])
            output = [
                {
                    "type": "input_text",
                    "text": f"Image edited successfully. Image Name: {image_name}",
                },
                {
                    "type": "input_image",
                    "image_url": image_url,
                }
            ]
        else:
            output = [
                {
                    "type": "input_text",
                    "text": "Image editing failed.",
                }
            ]
            runtime_info['generated_images'].append({
                "name": image_name,
                "status": "failed",
            })

        message = self._format_history_message(result, output)
        history_messages.append(message)
        runtime_info['llm_response'][-1]['function_calling_results'].append(message)

    async def _process_fc_result(
        self,
        result: FunctionCallResult,
        history_messages: List[dict],
        runtime_info: dict,
        node: SearchNode,
        language: str,
    ):
        r"""
        1. update node query
        2. add citation id in web search link
        3. format weblink
        """

        function_name = result.name
        url_content_map = {}

        def format_query(language: str, tool_name: str, titles_str: str):
            tool = self._tool_name_translation(tool_name, language)
            if titles_str == '':
                return translate("ui.tool_finished", language, tool=tool)
            return translate("ui.tool_title_finished", language, tool=tool, titles=titles_str[:20])

        def reading_webpage_summary(language: str, links: list) -> str:
            if not links:
                return ""

            # [WebSearchLink(url=url, summ='', title=title) for url, title in url_title_map.items()]
            links_str = ("\n").join([
                f"- [{title}]({url})"
                for url, title in links
            ])
            return translate("ui.key_reference", language) + "\n" + links_str

        def format_finished_query(language: str):
            return translate("ui.search_finished", language)

        def format_document_search(language: str):
            return translate("ui.doc_search_finished", language)

        # Add llm explain to node summary
        # Format llm explanation for citatin formation
        llm_explanation= result.args.get('explanation', '')
        try:
            node.summary = self._format_citation(llm_explanation, runtime_info)
        except Exception as e:
            logger.error(f"Error formatting citation: {e}")
            node.summary = llm_explanation

        # Format display node
        if function_name in [GeneralSearch.__name__, MedicalSearch.__name__, NewsSearch.__name__, PatentSearch.__name__]:
            # Merge query
            query = "\n".join([
                sub_query.get('keyword', '') if language != constants.ENGLISH else sub_query.get('keyword_en', '')
                for sub_query in result.result
            ])
            
            # Merge summary 
            sub_query_summary = result.args.get('explanation‌', '') + translate("ui.search_keywords", language) + "\n" + "\n".join([
                f"- {sub_query.get('sub_query', '')}"
                for sub_query in result.result
            ])
            
            # Format search_type
            search_type = SearchType.WEB
            if function_name == PatentSearch.__name__:
                search_type = SearchType.PATENT
            elif function_name == NewsSearch.__name__:
                search_type = SearchType.NEWS

            # Add search results
            for sub_query in result.result:
                if self.sensitive_checker:
                    is_safe = await self.sensitive_checker.simple_check(str(sub_query), chunk_size=200, only_politics=True, min_ratio=0.2)
                    if not is_safe:
                        raise ModerationFailure("Search results contains sensitive content.")
                for value in sub_query.get('search_result', {}).values():
                    node.add_search_result(self._format_websearch_weblink(value, runtime_info, search_type))

            # Format search result for llm model next step
            function_output = []
            for sub_query in result.result:
                tmp = {
                    'keyword_en': sub_query.get('keyword_en', ''),
                    'search_result': []
                }
                for value in sub_query.get('search_result', {}).values():
                    url = value.get('url', '')
                    link = runtime_info['url_map'].get(url)
                    if link:
                        tmp['search_result'].append({
                            'citation_id': link.id,
                            'summ': link.summ,
                            'title': link.title,
                            'site_name': link.site_name,
                        })
                function_output.append(tmp)

            node.search_type = search_type
            node.query = format_query(language, function_name, query)
            node.summary = node.summary + f"\n\n{sub_query_summary}"

            function_output = json.dumps(function_output, ensure_ascii=False)
            message = self._format_history_message(result, function_output)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
            
            """
            history_messages.append({
                "call_id": result.call_id,
                "output": json.dumps(function_output, ensure_ascii=False),
                "type": "function_call_output",
            })
            """

        elif function_name in [PubMedArticlesSearch.__name__, PubMedArticlesLocalSearch.__name__]:
            node.key_word = result.args.get('pubmed_query', '')
            node.search_type = SearchType.PUBMED
            node.query = translate("query.pubmed_search", language)
            node.summary = node.summary + f"\n\n**PubMed Search Term:** {node.key_word}"
            
            # Check result
            if not result.result:
                node.processing_type = ProcessingType.FAILED
                message = self._format_history_message(result, "Fetch PubMed artilce failed, try use other methods.")
                history_messages.append(message)
                runtime_info['llm_response'][-1]['function_calling_results'].append(message)
                return
            
            # 查询优先级 PMID
            priority_pubmed_ids = runtime_info.get('priority_pubmed_ids', [])
            if priority_pubmed_ids:

                try:
                    # 方式1：直接使用 PubMedArticlesSearch 工具
                    pubmed_tool = PubMedArticlesSearch()
                    
                    # 构造 query：将 PMID 列表转换为 "PMID[uid] OR PMID[uid]" 格式
                    query = " OR ".join([f"{pmid}[uid]" for pmid in priority_pubmed_ids])
                    
                    # 调用工具，它会自动处理 esearch + efetch + 解析
                    async for res in pubmed_tool.run(pubmed_query=query):
                        priority_results = res.result
                        break  # 只取第一个结果
                    
                    # 把优先结果放到 result.result 的最前面
                    if priority_results:
                        result.result = result.result + priority_results
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch priority PMIDs: {e}")
                        
            # Add search results
            function_output = []
            for value in result.result:
                link = self._format_pubmed_weblink(value, runtime_info)
                node.add_search_result(link)
                function_output.append({
                    'citation_id': link.id,
                    'pubmed_id': link.pubmed_id,
                    'pmcid': link.pmcid,
                    'doi': link.doi,
                    'title': link.title,
                    'abstract': link.summ,
                    'sci_if': link.cite_score,
                    'journal': link.full_journal_name,
                })

            function_output = json.dumps(function_output, ensure_ascii=False)
            message = self._format_history_message(result, function_output)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == DrugManualSearch.__name__:
            node.key_word = result.args.get('drug_names_query', '')
            node.search_type = SearchType.DRUG_MANUAL
            node.query = translate("query.drug_manual_search", language)
            node.summary = node.summary + f"\n\n**Drug names:** {node.key_word}"
            if not result.result:
                node.processing_type = ProcessingType.FAILED
                message = self._format_history_message(result, "No drug manual found for the given names.")
                history_messages.append(message)
                runtime_info['llm_response'][-1]['function_calling_results'].append(message)
                return
            function_output = json.dumps(result.result, ensure_ascii=False)
            message = self._format_history_message(result, function_output)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == ClinicalGuidelineSearch.__name__:
            try:
                logger.info(f"[ClinicalGuidelineSearch] Processing started, result.result type: {type(result.result)}, length: {len(result.result) if result.result else 0}")
                node.key_word = result.args.get('guideline_query', '')
                node.search_type = SearchType.CLINICAL_GUIDELINE
                node.query = translate("query.clinical_guideline_search", language)
                node.summary = node.summary + f"\n\n**Guideline query:** {node.key_word}"
                if not result.result:
                    logger.info(f"[ClinicalGuidelineSearch] No result found, but query succeeded - setting DONE")
                    node.processing_type = ProcessingType.DONE
                    message = self._format_history_message(result, "No clinical guideline content found for the query.")
                    history_messages.append(message)
                    runtime_info['llm_response'][-1]['function_calling_results'].append(message)
                    return
                function_output = json.dumps(result.result, ensure_ascii=False)
                message = self._format_history_message(result, function_output)
                history_messages.append(message)
                runtime_info['llm_response'][-1]['function_calling_results'].append(message)
                node.processing_type = ProcessingType.DONE
                logger.info(f"[ClinicalGuidelineSearch] Processing completed, set DONE")
            except Exception as e:
                logger.error(f"[ClinicalGuidelineSearch] Error processing result: {e}")
                node.processing_type = ProcessingType.FAILED
                # 确保添加 tool output 以避免 "No tool output found" 错误
                message = self._format_history_message(result, f"Error processing clinical guideline: {e}")
                history_messages.append(message)
                runtime_info['llm_response'][-1]['function_calling_results'].append(message)
            return

        elif StockHistoricalPriceQuery.__name__ == function_name:
            symbol = result.args.get('symbol', '')
            date_from = result.args.get('date_from', '')
            date_to = result.args.get('date_to', '')
                
            def format_stockprice_summary(
                result: dict) -> tuple[list, str]:
                chart_data = []
                symbol = result.get('symbol', '')
                for row in result.get('historical', []):
                    chart_data.append({
                        "date": row['date'],
                        "open": round(float(row['open']), 2),
                        "high": round(float(row['high']), 2),
                        "low": round(float(row['low']), 2),
                        "close": round(float(row['close']), 2),
                        "volume": int(row['volume'])
                    })
                # To avoid too big graph
                vega_spec = self.helper.create_candlestick_chart(chart_data[:30], symbol)
                return chart_data, f"""```vega
{json.dumps(vega_spec, indent=2, ensure_ascii=False)}
```
"""
            
            history_price, history_price_chart = format_stockprice_summary(result.result)

            node.query = translate("query.get_stock_prices", language, symbol=symbol, date_from=date_from, date_to=date_to)
            node.summary = node.summary + f"\n\n{history_price_chart}"

            history_price = json.dumps(history_price, ensure_ascii=False)
            message = self._format_history_message(result, history_price)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif StockNewsSearch.__name__ == function_name:
            symbol = result.args.get('symbol', '')
            date_from = result.args.get('date_from', '')
            date_to = result.args.get('date_to', '')
            
            def format_link(link: dict):
                url = link.get('url', '')
                id = runtime_info['url_map'][url].id if url in runtime_info['url_map'] else len(runtime_info['url_map']) + 1
                parsed_url = urlparse(url)
                site_name = parsed_url.netloc
                link = WebSearchLink(
                    id=id,
                    url=link.get('url', ''),
                    title=link.get('title', ''),
                    summ=link.get('text', ''),
                    site_name=site_name,
                    type=SearchType.NEWS
                )
                
                # Generate citation (Vancouver format)
                link.citation = generate_citation(link)

                # Update global url map
                runtime_info['url_map'][url] = link
                runtime_info['citation_id_map'][id] = link

                return link
                
            def format_function_call_output(link: WebSearchLink):
                return {
                    'citation_id': link.id,
                    'title': link.title,
                    'summ': link.summ,
                    'site_name': link.site_name,
                }
                
            node.query = translate("query.get_stock_news", language, symbol=symbol, date_from=date_from, date_to=date_to)
            node.search_results = [format_link(link) for link in result.result if link.get('url', '') != '']

            stock_news = [format_function_call_output(link) for link in node.search_results]
            stock_news = json.dumps(stock_news, ensure_ascii=False)
            message = self._format_history_message(result, stock_news)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name in [ContentReader.__name__, Finished.__name__]:
            # Find url related title
            titles_str, url_content_map, url_items = await self._fetch_webpage_content(result.args.get('citation_ids', []), runtime_info)
            
            # Update runtime info url_content_map
            runtime_info['url_content_map'].update(url_content_map)

            node.query = format_finished_query(language) \
                if Finished.__name__ == function_name \
                else format_query(language=language, tool_name=function_name, titles_str=titles_str)
            node.summary = node.summary + "\n\n" + reading_webpage_summary(language, url_items)

            # TODO to use mini llm or just truncate the reference content to fit openai context window.
            # Format reference content function calling result
            reference_content = self._format_reference_fcr(url_content_map, runtime_info)
            reference_content = json.dumps(reference_content, ensure_ascii=False)
            # TODO: truncate reference content to fit openai context window.
            # In future, we can use mini llm to truncate the reference content.
            reference_content = tokenizer.truncate_by_tokens(reference_content, self.compact_max_item_tokens, 'openai-o3')

            message = self._format_history_message(result, reference_content)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
        
        elif function_name in [DocumentReader.__name__, DocumentSearchFinished.__name__]:

            # Find url related detail, this step already compact the content to fit openai context window.
            titles_str, url_content_map, url_items = await self._read_intreseting_documents(
                result.args.get('citation_ids', []),
                result.args.get('user_goal', ''),
                result.args.get('focus_aspects', []),
                result.args.get('detail_level', ''),
                runtime_info)

            # Update runtime info url_content_map
            runtime_info['url_content_map'].update(url_content_map)

            node.query = format_finished_query(language) \
                if DocumentSearchFinished.__name__ == function_name \
                else format_query(language=language, tool_name=function_name, titles_str=titles_str)
            node.summary = node.summary + "\n\n" + reading_webpage_summary(language, url_items)

            # Format reference content function calling result
            reference_content = self._format_reference_fcr(url_content_map, runtime_info)
            reference_content = json.dumps(reference_content, ensure_ascii=False)

            message = self._format_history_message(result, reference_content)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif AgentRunSandbox.__name__ == function_name:
            explanation = result.args.get('explanation', '')
            task = result.args.get('task', '')
            if explanation:
                task = f"{explanation}\n\n## Task\n{task}"
            data_description = result.args.get('data_description', '')
            files = result.args.get('files', [])

            # Auto-inject attachment files from previous AttachmentDownload results
            # Successful → add blob_path; Failed → use SDK fallback via storage metadata
            for tool_result in runtime_info.get('tool_results', []):
                tr_name = tool_result.name if hasattr(tool_result, 'name') else tool_result.get('name', '')
                if tr_name == AttachmentDownload.__name__:
                    tr_data = tool_result.result if hasattr(tool_result, 'result') else tool_result.get('result', [])
                    if isinstance(tr_data, list):
                        for att in tr_data:
                            if not isinstance(att, dict):
                                continue
                            if att.get('success') and att.get('blob_path'):
                                if att['blob_path'] not in files:
                                    files.append(att['blob_path'])
                            elif att.get('url'):
                                # SAS URL may be broken (e.g., blob names with literal % chars).
                                # Try SDK fallback: find storage metadata and download directly.
                                matched = next(
                                    (a for a in runtime_info.get('attachments', [])
                                     if a.get('url') == att['url']),
                                    None
                                )
                                if matched and matched.get('storage', {}).get('blob'):
                                    fallback = {
                                        'type': 'sdk_fallback',
                                        'storage': matched['storage'],
                                        'filename': att.get('filename') or matched.get('name', 'unknown'),
                                    }
                                    files.append(fallback)
                                elif att['url'] not in files:
                                    files.append(att['url'])

            # Auto-inject user-uploaded attachments from runtime_info.
            # These were fetched by _read_attachments() but may not have
            # gone through AttachmentDownload tool call.
            seen_att_ids = set()
            for att in runtime_info.get('attachments', []):
                att_id = att.get('id', '')
                if not att_id or att_id in seen_att_ids:
                    continue
                seen_att_ids.add(att_id)
                name = att.get('name', '')
                storage = att.get('storage', {})
                if isinstance(storage, dict) and storage.get('blob'):
                    files.append({
                        'type': 'sdk_fallback',
                        'storage': storage,
                        'filename': name,
                    })
                elif att.get('url'):
                    files.append(att['url'])

            # V3 style: LLM provides natural language task, executor drives shell agent
            logger.info(f"[AgentRunSandbox] Executing task (V3 style - LLM driven), task={task[:100]}, files={len(files)}...")

            try:
                if self.agentrun_sandbox_executor is None:
                    self.agentrun_sandbox_executor = AgentRunSandboxExecutor(
                        session_id=self.thread_id or None
                    )

                # Collect tool results and upload to sandbox
                tool_data = self._collect_tool_data(runtime_info)
                data_file_path = f"{self.agentrun_sandbox_executor.default_cwd}/tool_results_data.json"

                # Always create tool_results_data.json so sandbox scripts
                # can rely on its existence
                data_content = json.dumps(tool_data, ensure_ascii=False, indent=2)
                upload_success = await self.agentrun_sandbox_executor.write_file(
                    path=data_file_path,
                    content=data_content,
                )

                data_info = ""
                if upload_success and tool_data:
                    # Append data file info to task with data description from LLM
                    data_info = f"""
**Important**: The data from previous tool calls has been saved to `{data_file_path}` in the sandbox.
You can load it in Python with:
```python
import json
with open('{data_file_path}', 'r') as f:
    data = json.load(f)
```
The file contains keys: {list(tool_data.keys())}"""

                if data_description:
                    data_info += f"""\n
**Data Structure Description** (provided by the caller):
{data_description}"""

                task = f"{task}\n{data_info}"
                logger.info(f"[AgentRunSandbox] Tool data uploaded to {data_file_path}, keys={list(tool_data.keys())}")

                # Adapt node updates to on_progress callback
                def _node_progress(text, append=False):
                    if append:
                        node.summary += text
                    else:
                        node.summary = text

                # Execute task using LLM-driven shell loop in AgentRun cloud sandbox
                sandbox_summary = await self.agentrun_sandbox_executor.execute(
                    task=task,
                    language=language,
                    files=files,
                    on_progress=_node_progress,
                )
            except Exception as e:
                logger.error(f"[AgentRunSandbox] Execution failed: {e}")
                sandbox_summary = f"Error: Task execution failed - {str(e)}"

            # Mask long OSS-signed download URLs before they enter the LLM-facing
            # history & shell_result; they will be restored when streaming the
            # final output back to the user. `node.summary` is intentionally NOT
            # masked since it is shown to the user directly.
            sandbox_summary = self._mask_sandbox_urls(sandbox_summary, runtime_info)

            runtime_info['shell_result'].append(sandbox_summary)
            node.query = self._tool_name_translation(function_name, language)
            # node.summary is already set by executor.execute()
            message = self._format_history_message(result, sandbox_summary)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
        
        elif DocumentSearch.__name__ == function_name:

            document_search_results = await self._search_documents(
                result.args.get('citation_ids', []),
                result.args.get('query', ''),
                result.args.get('keywords', []),
                runtime_info)
            
            node.query = format_document_search(language)
            # _search_documents returns list[dict]; node.summary must be str
            if document_search_results:
                parts = []
                for item in document_search_results:
                    cid = item.get('citation_id', '')
                    ctx = item.get('context_text', '')
                    if ctx:
                        parts.append(f"[Citation {cid}]: {ctx[:200]}")
                node.summary = "\n".join(parts) if parts else ""
            else:
                node.summary = ""

            message = self._format_history_message(result, document_search_results)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif KnowledgeBasePreview.__name__ == function_name:
            
            id = result.args.get('knowledge_base_id', '')
            page = result.args.get('page', 1)
            page_size = result.args.get('page_size', 30)

            attachment_chunks, _, _ = self._build_attachment_content_arr_by_folder(
                folder_id=id,
                runtime_info=runtime_info,
                format_attachment_link=MindSearchAgentV3.format_attachment_link,
                page=page,
                page_size=page_size,
            )

            node.query = self._tool_name_translation(function_name, language)

            message = self._format_history_message(result, attachment_chunks)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)            

        elif AttachmentDownload.__name__ == function_name:
            # Handle attachment download results
            attachment_results = result.result if hasattr(result, 'result') else []

            # Format output for LLM
            successful = [r for r in attachment_results if r.get('success')]
            failed = [r for r in attachment_results if not r.get('success')]

            output_parts = []
            if successful:
                output_parts.append(f"Successfully downloaded {len(successful)} attachment(s):")
                for att in successful:
                    output_parts.append(f"  - {att.get('filename')}: blob_path={att.get('blob_path')}")
                    if att.get('text_preview'):
                        preview = att['text_preview'][:1000]
                        output_parts.append(f"    Preview: {preview}...")
                    if att.get('data_description'):
                        output_parts.append(f"    Data: {att['data_description']}")
            if failed:
                output_parts.append(f"Failed to download {len(failed)} attachment(s):")
                for att in failed:
                    output_parts.append(f"  - {att.get('url')}: {att.get('error')}")

            output_str = "\n".join(output_parts)
            node.query = self._tool_name_translation(function_name, language)
            node.summary = output_str[:500] if len(output_str) > 500 else output_str

            message = self._format_history_message(result, output_str)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
        
        elif ClinicalTrailSearch.__name__ == function_name:
            node.query = self._tool_name_translation(function_name, language)

            try:
                raw_results = result.result.get('data', {}).get('results', [])
                
                # TODO remove this part later since data access would be updated
                if not raw_results:
                    raw_results = result.result.get('results', [])

                for item in raw_results:
                    link = self._format_clinical_trail_weblink(item, runtime_info)
                    if link:
                        node.add_search_result(link)

                raw_results_str = json.dumps(raw_results, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[ClinicalTrailSearch] Error processing result: {e}")
                raw_results_str = "Error: Clinical trail search failed"
            
            message = self._format_history_message(result, raw_results_str)
            logger.info(f"[ClinicalTrailSearch] message: {message}")
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == FinancialStatements.__name__:
            symbol = result.args.get('symbol', '')
            period = result.args.get('period', 'annual')

            node.query = translate("query.get_financial_statements", language, symbol=symbol, period=period)
            node.search_type = SearchType.STOCKPRICES

            raw = result.result if hasattr(result, 'result') else {}
            summary_parts = []
            historical = raw.get('historical', [])
            if historical:
                latest = historical[0] if historical else {}
                summary_parts.append(f"**{symbol}** Latest Price Data\n")
                summary_parts.append(f"| Metric | Value |")
                summary_parts.append(f"|--------|-------|")
                if latest.get('close'):
                    summary_parts.append(f"| Close | {latest['close']} |")
                if latest.get('changePercent'):
                    summary_parts.append(f"| Change% | {latest['changePercent']}% |")
                if latest.get('volume'):
                    summary_parts.append(f"| Volume | {latest['volume']:,} |")
                if latest.get('date'):
                    summary_parts.append(f"| Date | {latest['date']} |")
                if raw.get('marketcapitalization'):
                    mcap = raw['marketcapitalization']
                    if mcap >= 1e9:
                        summary_parts.append(f"| Market Cap | ${mcap/1e9:.2f}B |")
                    else:
                        summary_parts.append(f"| Market Cap | ${mcap/1e6:.2f}M |")

            node.summary = "\n".join(summary_parts) if summary_parts else "No data available"

            # Send condensed summary to LLM instead of full historical JSON.
            # Full data is available to AgentRunSandbox via _collect_tool_data().
            llm_parts = []
            if historical:
                latest = historical[0]
                llm_parts.append(f"Stock data for {symbol}: {len(historical)} trading day(s).")
                llm_parts.append(f"Latest: date={latest.get('date')}, close={latest.get('close')}, "
                                 f"change%={latest.get('changePercent')}, volume={latest.get('volume')}")
                if raw.get('marketcapitalization'):
                    llm_parts.append(f"Market cap: {raw['marketcapitalization']}")
            llm_summary = " ".join(llm_parts) if llm_parts else "No data available"
            llm_summary += " Use AgentRunSandbox to analyze full historical data."

            message = self._format_history_message(result, llm_summary)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == ChinaCompanyFinancialStatements.__name__:
            symbol = result.args.get('symbol', '')

            node.query = translate("query.get_china_financial_statements", language, symbol=symbol)
            node.search_type = SearchType.STOCKPRICES

            raw = result.result if hasattr(result, 'result') else {}

            # --- Frontend display (node.summary) ---
            # raw = {"balance": {...}, "income": {...}, "cashflow": {...}}
            # Each value is a nested dict/list from MaiRui API. Show a high-level summary.
            summary_parts = [f"**{symbol}** finance details\n"]
            for report_type in ['balance', 'income', 'cashflow']:
                report_data = raw.get(report_type) if isinstance(raw, dict) else None
                if report_data:
                    if isinstance(report_data, list):
                        count = len(report_data)
                        summary_parts.append(f"- {report_type}: {count} period(s)")
                    elif isinstance(report_data, dict):
                        keys = list(report_data.keys())
                        summary_parts.append(f"- {report_type}: {len(keys)} field(s)")
                else:
                    summary_parts.append(f"- {report_type}: No data")

            # Fallback: if raw is a flat list (not the nested dict structure), show period count
            if isinstance(raw, list) and raw:
                summary_parts = [f"**{symbol}** Financial Statements ({len(raw)} period(s))"]

            node.summary = "\n".join(summary_parts) if summary_parts else "No data available"

            # --- LLM history (condensed, not full JSON) ---
            # Full data is available to AgentRunSandbox via _collect_tool_data().
            llm_summary = f"Retrieved financial statements for {symbol}. "
            llm_summary += "Data includes: "
            available = []
            if isinstance(raw, dict):
                for report_type in ['balance', 'income', 'cashflow']:
                    report_data = raw.get(report_type)
                    if report_data:
                        if isinstance(report_data, list):
                            available.append(f"{report_type} ({len(report_data)} period(s))")
                        elif isinstance(report_data, dict):
                            available.append(f"{report_type} ({len(report_data)} fields)")
            elif isinstance(raw, list):
                available.append(f"{len(raw)} period(s) of financial data")
            llm_summary += ", ".join(available) if available else "no data"
            llm_summary += ". Use AgentRunSandbox to analyze the full data."

            message = self._format_history_message(result, llm_summary)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == CompanyInfoQuery.__name__:
            symbol = result.args.get('symbol', '')

            node.query = translate("query.get_company_info", language, symbol=symbol)

            raw = result.result if hasattr(result, 'result') else {}
            profile = raw[0] if isinstance(raw, list) and raw else raw if isinstance(raw, dict) else {}
            summary_parts = []
            if profile:
                name = profile.get('companyName', symbol)
                summary_parts.append(f"**{name}** ({profile.get('symbol', symbol)})\n")
                summary_parts.append(f"| Item | Detail |")
                summary_parts.append(f"|------|--------|")
                if profile.get('exchangeShortName'):
                    summary_parts.append(f"| Exchange | {profile['exchangeShortName']} |")
                if profile.get('industry'):
                    summary_parts.append(f"| Industry | {profile['industry']} |")
                if profile.get('sector'):
                    summary_parts.append(f"| Sector | {profile['sector']} |")
                if profile.get('price'):
                    summary_parts.append(f"| Price | {profile['price']} |")
                if profile.get('mktCap'):
                    mcap = profile['mktCap']
                    if mcap >= 1e9:
                        summary_parts.append(f"| Market Cap | ${mcap/1e9:.2f}B |")
                    else:
                        summary_parts.append(f"| Market Cap | ${mcap/1e6:.2f}M |")
                if profile.get('country'):
                    summary_parts.append(f"| Country | {profile['country']} |")
                if profile.get('ceo'):
                    summary_parts.append(f"| CEO | {profile['ceo']} |")

            node.summary = "\n".join(summary_parts) if summary_parts else "No data available"

            output_str = json.dumps(raw, ensure_ascii=False, indent=2)
            message = self._format_history_message(result, output_str)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == CompanyPressReleasesNewsQuery.__name__:
            symbol = result.args.get('symbol', '')

            def format_link(link: dict):
                url = link.get('url', '') or ''
                if not url:
                    return None
                id = runtime_info['url_map'][url].id if url in runtime_info['url_map'] else len(runtime_info['url_map']) + 1
                parsed_url = urlparse(url)
                site_name = parsed_url.netloc
                wsl = WebSearchLink(
                    id=id,
                    url=url,
                    title=link.get('title', ''),
                    summ=link.get('text', ''),
                    site_name=site_name,
                    type=SearchType.NEWS
                )
                wsl.citation = generate_citation(wsl)
                runtime_info['url_map'][url] = wsl
                runtime_info['citation_id_map'][id] = wsl
                return wsl

            node.query = translate("query.get_press_releases", language, symbol=symbol)
            raw = result.result if hasattr(result, 'result') else []
            if isinstance(raw, list):
                node.search_results = [l for l in (format_link(item) for item in raw) if l is not None]

            def format_fc_output(link: WebSearchLink):
                return {'citation_id': link.id, 'title': link.title, 'summ': link.summ, 'site_name': link.site_name}

            press_news = [format_fc_output(l) for l in node.search_results]
            output_str = json.dumps(press_news, ensure_ascii=False)
            message = self._format_history_message(result, output_str)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)

        elif function_name == StockGeneralSearch.__name__:
            query = result.args.get('query', '')

            node.query = translate("query.search_stock_symbol", language, query=query)

            raw = result.result if hasattr(result, 'result') else []
            summary_parts = []
            if isinstance(raw, list) and raw:
                summary_parts.append(f"| Symbol | Name | Exchange | Currency |")
                summary_parts.append(f"|--------|------|----------|----------|")
                for item in raw[:10]:
                    summary_parts.append(
                        f"| {item.get('symbol', '')} | {item.get('name', '')} "
                        f"| {item.get('stockExchange', '')} | {item.get('currency', '')} |")

            node.summary = "\n".join(summary_parts) if summary_parts else "No results found"

            output_str = json.dumps(raw, ensure_ascii=False, indent=2)
            message = self._format_history_message(result, output_str)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
        
        elif function_name == ImageGeneration.__name__:
            await self._handle_image_generation(result, node, history_messages, runtime_info, language)

        elif function_name == ImageEdit.__name__:
            await self._handle_image_edit(result, node, history_messages, runtime_info, language)

        else:
            # Generic handler for tools without dedicated display logic
            tool_display = self._tool_name_translation(function_name, language)
            node.query = tool_display
            raw = result.result if hasattr(result, 'result') else {}
            try:
                output_str = json.dumps(raw, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                output_str = str(raw)
            node.summary = (output_str[:500] + '...') if len(output_str) > 500 else output_str
            message = self._format_history_message(result, output_str)
            history_messages.append(message)
            runtime_info['llm_response'][-1]['function_calling_results'].append(message)
        
        # Set search finished
        node.processing_type = ProcessingType.DONE

    def _collect_tool_data(self, runtime_info: dict) -> dict:
        """
        Collect tool results for AgentRunSandbox.

        Collects data from:
        - StockHistoricalPriceQuery: Historical stock prices
        - FinancialStatements: Company financial statements
        - ChinaCompanyFinancialStatements: China company financials
        - StockNewsSearch: Stock news
        - CompanyInfoQuery: Company information

        Returns:
            Dict with collected tool data, keyed by tool name
        """
        tool_data = {}

        for tool_result in runtime_info.get('tool_results', []):
            tool_name = tool_result.name if hasattr(tool_result, 'name') else tool_result.get('name', '')
            result_data = tool_result.result if hasattr(tool_result, 'result') else tool_result.get('result', {})

            if not result_data:
                continue

            if tool_name == StockHistoricalPriceQuery.__name__:
                # Extract historical price data
                key = f"stock_prices_{tool_result.args.get('symbol', 'unknown')}"
                tool_data[key] = {
                    'symbol': tool_result.args.get('symbol', ''),
                    'date_from': tool_result.args.get('date_from', ''),
                    'date_to': tool_result.args.get('date_to', ''),
                    'historical': result_data.get('historical', []) if isinstance(result_data, dict) else result_data,
                }

            elif tool_name in [FinancialStatements.__name__, ChinaCompanyFinancialStatements.__name__]:
                # Extract financial statements
                key = f"financials_{tool_result.args.get('symbol', 'unknown')}"
                tool_data[key] = {
                    'symbol': tool_result.args.get('symbol', ''),
                    'period': tool_result.args.get('period', ''),
                    'data': result_data,
                }

            elif tool_name == StockNewsSearch.__name__:
                # Extract stock news
                key = f"news_{tool_result.args.get('symbol', 'unknown')}"
                tool_data[key] = {
                    'symbol': tool_result.args.get('symbol', ''),
                    'news': result_data,
                }

            elif tool_name == CompanyInfoQuery.__name__:
                # Extract company info
                key = f"company_info_{tool_result.args.get('symbol', 'unknown')}"
                tool_data[key] = result_data

            elif tool_name == AttachmentDownload.__name__:
                # Extract attachment info (both successful and failed)
                if isinstance(result_data, list):
                    for att in result_data:
                        if not isinstance(att, dict):
                            continue
                        if att.get('success'):
                            fname = att.get('filename', 'unknown')
                            tool_data[f"attachment_{fname}"] = {
                                'filename': fname,
                                'type': att.get('type', ''),
                                'blob_path': att.get('blob_path', ''),
                                'sandbox_path': f"attachments/{fname}",
                                'data_description': att.get('data_description', ''),
                            }
                        else:
                            url = att.get('url', '')
                            if url:
                                tool_data[f"failed_download_{len(tool_data)}"] = {
                                    'url': url,
                                    'filename': att.get('filename', ''),
                                    'error': att.get('error', ''),
                                    'note': 'Download failed from server. May be accessible via curl in sandbox.',
                                }

            elif tool_name in [GeneralSearch.__name__, MedicalSearch.__name__,
                               NewsSearch.__name__, PatentSearch.__name__]:
                # Extract web search URLs and snippets so sandbox can download from them
                urls = []
                if isinstance(result_data, list):
                    for sub_query in result_data:
                        for value in sub_query.get('search_result', {}).values():
                            url = value.get('url', '')
                            if url:
                                urls.append({
                                    'url': url,
                                    'title': value.get('name', ''),
                                    'snippet': value.get('snippet', ''),
                                })
                if urls:
                    key = f"web_search_{len(tool_data)}"
                    tool_data[key] = {'urls': urls}

        return tool_data

    def _format_history_message(
        self,
        result: FunctionCallResult,
        output: Any,
    ) -> Dict[str, Any]:
        return {
            "call_id": result.call_id,
            "type": "function_call_output",
            "output": output,
        }

    def _format_websearch_weblink(
        self,
        websearch_response: dict,
        runtime_info: dict,
        type: SearchType = SearchType.WEB) -> WebSearchLink:
        r"""
        Update global web search result map and format common websearch link result.
        """
        url = websearch_response.get("url", "")
        id = runtime_info['url_map'][url].id if url in runtime_info['url_map'] else len(runtime_info['url_map']) + 1
        
        link =  WebSearchLink(
            id=id,
            url=url,
            summ=websearch_response.get("summ", ""),
            title=websearch_response.get("title", ""),
            site_name=websearch_response.get("site_name", ""),
            patent_id=websearch_response.get("patent_id", ""),
            type=type
        )
        
        # Generate citation (Vancouver format)
        link.citation = generate_citation(link)

        # Update global url map
        runtime_info['url_map'][url] = link
        runtime_info['citation_id_map'][id] = link
        
        return link
    
    def _format_clinical_trail_weblink(
        self,
        clinical_trail: dict, # data access api result
        runtime_info: dict) -> WebSearchLink:
        r"""
        Format clinical trail search result.
        """
        if not clinical_trail.get('nct_id'):
            return None
        
        # TODO Use noah clinical trail detail page url not clincialtrail.gov url
        url = f"https://clinicaltrials.gov/study/{clinical_trail.get('nct_id')}"
        title = clinical_trail.get('brief_title') or clinical_trail.get('official_title') or clinical_trail.get('nct_id')
        summ = clinical_trail.get('summary') or clinical_trail.get('description') or ''
        
        id = runtime_info['url_map'][url].id if url in runtime_info['url_map'] else len(runtime_info['url_map']) + 1

        link = WebSearchLink(
            id=id,
            url=url,
            title=title,
            summ=summ,
            type=SearchType.CLINICAL_TRIAL
        )
        
        # Update global url map
        runtime_info['url_map'][url] = link
        runtime_info['citation_id_map'][id] = link
        
        return link

    def get_url_title(
        self,
        urls: list[int],
        runtime_info: dict):
        url_title_map = {}
        citation_id_map = runtime_info['citation_id_map']
        for id in urls:
            value = citation_id_map.get(id)
            if value:
                title = value.title or value.site_name
                if title == '':
                    continue
                url_title_map[value.url] = title
        return url_title_map
    
    async def _fetch_webpage_content(
        self,
        urls: list[int],
        runtime_info: dict,
    ):
        r"""
        Fetch webpage content.
        """

        def get_google_patent_id(urls: list[int]):
            google_patent_map = {}
            citation_id_map = runtime_info['citation_id_map']
            for id in urls:
                for value in citation_id_map.values():
                    if id == value.id and value.type == SearchType.PATENT \
                        and value.site_name == 'google.com' and value.patent_id != '':
                        google_patent_map[value.url] = value.patent_id
            return google_patent_map

        def format_pmc_id(pmc_id: str) -> str:
            r"""
            Extract and format PMC ID from various input formats.
            
            Examples:
                - "PMC12512031" -> "PMC12512031"
                - "pmc-id: PMC12512031;embargo-date: 2026/10/09;" -> "PMC12512031"
                - Invalid input -> ""
            """
            if not pmc_id:
                return ""
            
            try:
                # Use case-insensitive search for PMC followed by digits
                if match := re.search(r'PMC(\d+)', pmc_id, re.IGNORECASE):
                    return f"PMC{match.group(1)}"
            except Exception as e:
                logger.warning(f'Failed to format PMC ID: {e}')
            
            return ""


        def get_pmc_id(urls: list[int]) -> dict[str, str]:
            pmc_id_map = {}
            citation_id_map = runtime_info['citation_id_map']
            
            # Convert urls list to set for O(1) lookup instead of O(n)
            url_set = set(urls)
            
            # Single pass through citation_id_map
            for value in citation_id_map.values():
                if (value.id in url_set and value.type == SearchType.PUBMED and 
                    (formatted_pmc := format_pmc_id(value.pmcid))):
                    pmc_id_map[value.url] = formatted_pmc
            
            return pmc_id_map

        def get_web_search_id(urls: list[int]) -> list[str]:
            web_search_set = set()
            citation_id_map = runtime_info['citation_id_map']

            # Convert urls list to set for O(1) lookup instead of O(n)
            url_set = set(urls)
            for value in citation_id_map.values():
                if (value.id in url_set and value.type in [SearchType.WEB, SearchType.NEWS]):
                    web_search_set.add(value.url)
            
            return list(web_search_set)
        
        # User history upload attachments, not webpage attachments.
        def get_attachments(urls: list[int]) -> dict[str, str]:
            attachments_map = {}
            citation_id_map = runtime_info['citation_id_map']

            # Convert urls list to set for O(1) lookup instead of O(n)
            url_set = set(urls)
            for value in citation_id_map.values():
                if (value.id in url_set and value.type == SearchType.ATTACHEMNT):
                    attachments_map[value.url] = value.attachment_id
            
            return attachments_map

        # Filter out URLs that are either unknown or already have cached content
        urls = [
            citation_id
            for citation_id in urls
            if citation_id in runtime_info["citation_id_map"] \
                and runtime_info["citation_id_map"][citation_id].url not in runtime_info["url_content_map"]
        ]

        # get link titles
        url_title_map = self.get_url_title(urls, runtime_info)
        titles_str = ",".join(url_title_map.values())

        url_content_map = {}
        # fetch webpage content
        web_search_urls = get_web_search_id(urls)
        if web_search_urls:
            url_content_map = await self.webpage_fetcher.fetch_urls(web_search_urls, enable_retry=True)

        # fetch pmc content, so far we only support two
        pmc_url_map = get_pmc_id(urls)
        if pmc_url_map:
            pmc_content = await self._pmc_reading(pmc_url_map)
            url_content_map.update(pmc_content)

        # fetch patents
        google_patent_url_map = get_google_patent_id(urls)
        if google_patent_url_map:
            google_patent_map = await self.webpage_fetcher.fetch_google_patents(patent_ids=list(google_patent_url_map.values()))
            logger.info(f"Read Google patent {len(google_patent_url_map)} and get {len(google_patent_map)}")
            for url, patent_id in google_patent_url_map.items():
                content = google_patent_map.get(patent_id, None)
                if content:
                    url_content_map[url] = content

        # fetch attachments
        attachment_map = get_attachments(urls)
        if attachment_map:
            # attachment has already been add to the url content map
            for url in attachment_map.keys():
                if url in runtime_info['attachment_url_map']:
                    url_content_map[url] = runtime_info['attachment_url_map'][url]

        return titles_str, url_content_map, list(url_title_map.items())

    async def _pmc_reading(
        self,
        pmc_url_map: dict,
        fetch_count: int = 2, # Avoid context window too large, only read first two articles.
    ) -> dict:
        r"Fast reading pmc article."
        ret = {}
        pmc_ids = list(pmc_url_map.values())[:fetch_count]
        pmc_content_map = await self.pmc_reader.read_pmc_batch(pmcids=pmc_ids)
        logger.info(f"Read PMC {pmc_ids} and get {len(pmc_content_map)}")
        for url, pmc_id in pmc_url_map.items():
            content = pmc_content_map.get(pmc_id)
            if not content:
                continue
                
            content_sections = []
            for field in ['title', 'authors_aff', 'abstract', 'body']:
                field_content = content.get(field, '').strip()
                if field_content:
                    content_sections.append(f"#{field}\n{field_content}")
                
            if content_sections:
                ret[url] = '\n'.join(content_sections)
        return ret

    async def _download_attachments_for_reading(
        self,
        url: str,
        content: str,
        max_attachments: int = 3
    ) -> str:
        """
        精读场景：检测并下载附件，合并到网页内容中

        Args:
            url: 网页 URL
            content: 网页内容
            max_attachments: 最多下载的附件数量

        Returns:
            合并附件内容后的完整内容
        """
        try:
            # 检测附件
            detected = self.webpage_fetcher.attachment_detector.detect(content, url)

            if not detected.direct:
                return content

            downloader = self.webpage_fetcher.attachment_downloader

            # 下载并解析附件
            for att in detected.direct[:max_attachments]:
                try:
                    result = await downloader.download_single(att.url)
                    if result.success and result.text_preview:
                        content += f"\n\n---\n## Attachment: {result.filename}\n{result.text_preview}"
                        logger.info(f"Downloaded attachment for reading: {att.url}, length: {len(result.text_preview)}")
                except Exception as e:
                    logger.warning(f"Failed to download attachment {att.url}: {e}")

            return content

        except Exception as e:
            logger.warning(f"Attachment processing failed for {url}: {e}")
            return content

    async def _compact_history_messages(
        self,
        history_messages: list[dict],
        user_question: str,
        runtime_info: dict,
    ):
        r"""
        Compact history messages. Routes to the best strategy based on provider:
        - azure_openai/openai: use responses.compact() API (server-side, no extra LLM call)
        - others: fall back to LLM summarization via compact_agent
        """
        thinking_llm = self.thinking_agent.llm()
        provider = getattr(thinking_llm, 'provider', '')

        if provider in ('azure_openai', 'openai'):
            try:
                await self._compact_via_responses_api(history_messages, user_question, runtime_info)
                return
            except Exception as e:
                logger.warning(f"compact() API failed, falling back to summarization: {e}")

        await self._compact_via_summarization(history_messages, user_question, runtime_info)

    async def _compact_via_responses_api(
        self,
        history_messages: list[dict],
        user_question: str,
        runtime_info: dict,
    ):
        r"""
        Use Azure OpenAI responses.compact() to compress conversation history.
        The compacted output is opaque tokens that can be passed directly to responses.create() input.
        """
        thinking_llm = self.thinking_agent.llm()
        sys_prompt = self.thinking_agent.sys_prompt or None

        logger.info(f"Compact via responses.compact(), history_messages len: {len(history_messages)}")
        compacted_output = await thinking_llm.compact(
            input=history_messages,
            instructions=sys_prompt,
        )
        logger.info(f"Compact via responses.compact() success, compacted items: {len(compacted_output)}")

        # Sanitize compacted items for Azure Responses API compatibility.
        # The compact endpoint (standard OpenAI path) may return items with 'input_text'
        # content type in assistant-role positions, which Azure's responses.create()
        # rejects — it only accepts 'output_text' and 'refusal' for non-user items.
        compacted_output = self._sanitize_compacted_items(compacted_output)

        history_messages.clear()
        history_messages.extend(compacted_output)

        # Clean llm_response so next _execute_thinking takes the "first call" path (no previous_response_id).
        runtime_info['llm_response'].clear()
        runtime_info['last_step_hms_length'] = len(history_messages)

    def _sanitize_compacted_items(self, items: list) -> list:
        """
        Fix content types in compacted items for Azure Responses API compatibility.
        Azure rejects 'input_text' in non-user-role messages; convert to 'output_text'.
        """
        sanitized = []
        for item in items:
            if hasattr(item, 'model_dump'):
                item = item.model_dump(exclude_unset=True)
            elif not isinstance(item, dict):
                sanitized.append(item)
                continue

            role = item.get('role', '')
            content = item.get('content')
            if content and isinstance(content, list) and role != 'user':
                for c in content:
                    if isinstance(c, dict) and c.get('type') == 'input_text':
                        c['type'] = 'output_text'

            sanitized.append(item)
        return sanitized

    async def _compact_via_summarization(
        self,
        history_messages: list[dict],
        user_question: str,
        runtime_info: dict,
    ):
        r"""
        Fallback: use GPT5Nano to generate a text summary of the conversation history.
        Original compact logic preserved as fallback for non-OpenAI providers or API failures.
        """
        # Age old content before summarizing to reduce input to compact LLM
        self._age_history_content(history_messages)

        # Format function calling results
        fc_results = []
        for llm_response_item in runtime_info['llm_response']:
            try:
                response_output = ''
                for output_item in llm_response_item['response'].output:
                    response_output += output_item.model_dump_json()

                fc_results.append({
                    'role': 'assistant',
                    'content': response_output,
                })
                fc_results.append({
                    'role': 'user',
                    'content': json.dumps(llm_response_item['function_calling_results'], ensure_ascii=False),
                })
            except Exception as e:
                logger.warning(f'Format function calling result failed {e}')
                continue

        first_fc_result = fc_results[:-2]
        second_fc_result = fc_results[-2:]

        # compact history messages
        # last step history messages + current function calling results + original user question
        compact_messages = history_messages[:runtime_info['last_step_hms_length']]
        # add function calling results
        compact_messages.extend(first_fc_result)
        # add system info and user original question for compress
        compact_messages.append({
            'role': 'user',
            'content': gpt_compact_user_pt.format(
                current_date=datetime.now().strftime('%Y-%m-%d'),
                user_question=user_question,
            ),
        })

        # call llm to compact
        summary = ''
        try:
            async for chunk in self.compact_agent.stream_call('', compact_messages):
                summary += chunk
        except Exception as e:
            logger.warning(f'Try to compact history messages failed {e}')
            new_history_messages = history_messages[:runtime_info['last_step_hms_length']] # Rollback to last step history messages.
        else:
            new_history_messages = [
                {
                    'role': 'user',
                    'content': summary,
                }
            ]
        finally:
            logger.info(f"Compact history messages len: {len(summary)} first chunk: {summary[:100]}")

        # truncate function calling results
        total_tokens = len(tokenizer.openai(user_prompt='', history_messages=second_fc_result, model='openai-o3'))
        if total_tokens > self.compact_max_item_tokens:
            second_fc_result[-1]['content'] = tokenizer.truncate_by_tokens(second_fc_result[-1]['content'], self.compact_max_item_tokens, 'openai')

        # add last function calling result and llm
        new_history_messages.extend(second_fc_result)

        history_messages.clear()
        history_messages.extend(new_history_messages)

        # clean llm_response, since next llm calling would use whole history messages.
        runtime_info['llm_response'].clear()
        runtime_info['last_step_hms_length'] = len(history_messages)


    async def _search_documents(
        self,
        urls: list[int],
        query: str,
        keywords: list[str],
        runtime_info: dict,
    ) -> list:
        r"""
        If there is document corpus, search documents from whole document corpus.
        Otherwise, search documents from specific documents.
        """

        attachment_ids = runtime_info['attachments']
        parent_id = runtime_info.get('parent_id', None)
        if parent_id:
            attachment_ids = await search_and_selection(user_query=query, parent_id=parent_id)

        # Search uploaded or history files as document corpus.
        async def _fetch_attachment_context(att):
            url = att.get('url', '')
            name = att.get('name', "Untitled")
            attachment_id = str(att.get('id', ''))
            try:
                context_text = await fetch_context_single(
                    url,
                    name,
                    attachment_id,
                    query=query,
                    detailed=1,
                    mode=runtime_info.get('attachment_fetch_mode', 'sql'),
                )
            except Exception as e:
                logger.warning(f"Failed to fetch attachment context for {name} ({attachment_id}): {e}")
                context_text = ""
            return attachment_id, context_text

        results = await asyncio.gather(*[
            _fetch_attachment_context(att) for att in attachment_ids
        ])

        res = []
        for attachment_id, context_text in results:
            # Find citation id by attachment id
            for item in runtime_info['url_map'].values():
                if item.attachment_id == attachment_id:
                    res.append({
                        'citation_id': item.id,
                        'context_text': context_text,
                    })
                    break
        return res
        
    async def _read_intreseting_documents(
        self,
        urls: list[int],
        user_goal: str,
        focus_aspects: list[str],
        detail_level: str,
        runtime_info: dict,
    ):
        r"""
        Fetch document query.

        1. Fetch document raw content (PubMed, Patents, Web)
        2. Compress content using reading agent
        3. Return compressed content for final output
        """

        async def reading(content: str, title: str = ''):
            """Read and compress document content using LLM."""
            user_prompt = gpt_reading_user_pt.format(
                user_goal=user_goal,
                focus_aspects=focus_aspects,
                detail_level=detail_level,
            )
            messages = [
                {
                    "role": "assistant",
                    "content": f"# Doucment:\n{content}",
                },
            ]
            summary = ''
            try:
                async for chunk in self.reading_agent.stream_call(user_prompt, messages):
                    summary += chunk
            except Exception as e:
                logger.warning(f'Reading article failed {e}')
            finally:
                logger.info(f"Fetch document query success: {summary[:100] if summary else 'empty'}")
                return summary

        def get_pmc_id(urls: list[int]):
            pmc_id_map = {}
            citation_id_map = runtime_info['citation_id_map']
            for id in urls:
                for value in citation_id_map.values():
                    if id == value.id and value.type == SearchType.PUBMED and value.pmcid != '':
                        pmc_id_map[value.url] = value.pmcid
            return pmc_id_map

        def get_google_patent_id(urls: list[int]):
            """Get Google patent IDs from citation_id_map."""
            google_patent_map = {}
            citation_id_map = runtime_info['citation_id_map']
            url_set = set(urls)
            for value in citation_id_map.values():
                if value.id in url_set and value.type == SearchType.PATENT \
                    and value.site_name == 'google.com' and value.patent_id != '':
                    google_patent_map[value.url] = value.patent_id
            return google_patent_map

        def get_web_urls(urls: list[int]):
            """Get web/news URLs from citation_id_map."""
            web_urls = []
            citation_id_map = runtime_info['citation_id_map']
            url_set = set(urls)
            for value in citation_id_map.values():
                if value.id in url_set and value.type in [SearchType.WEB, SearchType.NEWS]:
                    web_urls.append(value.url)
            return web_urls

        # Limit concurrency to 3
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)  
        
        async def reading_with_semaphore(content: str, title: str):
            async with semaphore:
                return await reading(content, title)

        # get link titles
        url_title_map = self.get_url_title(urls, runtime_info)
        titles_str = ",".join(url_title_map.values())

        # Collect all raw content from different sources
        raw_content_map = {}

        # 1. Fetch PubMed (PMC) articles
        pmc_url_map = get_pmc_id(urls)
        if pmc_url_map:
            pmc_content_map = await self._pmc_reading(pmc_url_map, 100)
            raw_content_map.update(pmc_content_map)
            logger.info(f"Fetched {len(pmc_content_map)} PMC articles")

        # 2. Fetch Google Patents
        google_patent_url_map = get_google_patent_id(urls)
        if google_patent_url_map:
            google_patent_map = await self.webpage_fetcher.fetch_google_patents(
                patent_ids=list(google_patent_url_map.values())
            )
            logger.info(f"Read Google patent {len(google_patent_url_map)} and get {len(google_patent_map)}")
            for url, patent_id in google_patent_url_map.items():
                content = google_patent_map.get(patent_id, None)
                if content:
                    raw_content_map[url] = content

        # 3. Fetch Web/News content
        web_urls = get_web_urls(urls)
        if web_urls:
            # 精读场景：关闭附件列表追加，改为自动下载附件内容
            web_content_map = await self.webpage_fetcher.fetch_urls(
                web_urls,
                enable_retry=True,
                detect_attachments=False  # 精读场景不追加列表，而是自动下载
            )

            # 检测并下载附件，合并到网页内容中
            for url, content in list(web_content_map.items()):
                if content:
                    content_with_attachments = await self._download_attachments_for_reading(url, content)
                    web_content_map[url] = content_with_attachments

            raw_content_map.update(web_content_map)
            logger.info(f"Fetched {len(web_content_map)} web pages")

        # 4. Fetch user-uploaded attachments
        attachment_url_map = runtime_info.get('attachment_url_map', {})
        citation_id_map = runtime_info['citation_id_map']
        url_set = set(urls)
        for value in citation_id_map.values():
            if value.id in url_set and value.type == SearchType.ATTACHEMNT:
                if value.url in attachment_url_map:
                    raw_content_map[value.url] = attachment_url_map[value.url]
        if attachment_url_map:
            fetched_attachments = len([u for u in raw_content_map if u in attachment_url_map])
            if fetched_attachments:
                logger.info(f"Fetched {fetched_attachments} attachments")

        # If no content fetched, return empty
        if not raw_content_map:
            logger.info("No content fetched for DocumentReader")
            return '', {}, []
        
        # Compress large contents using reading agent
        url_content_map = {}

        # fetch pmc article raw content (only when PMC or priority pubmed IDs exist)
        if pmc_url_map or runtime_info.get('priority_pubmed_ids', []):
            from workflows.thesis_writing.temp_sinovac_thesis_data import pmid_map
            pmc_content_map = await self._pmc_reading(pmc_url_map, 100)
        # fast reading and abstract article to avoid hallucination
        ## 读优先级的文章
        if runtime_info.get('priority_pubmed_ids', []):
            priority_pubmed_ids = runtime_info.get('priority_pubmed_ids', [])
            priority_urls = ['https://pubmed.ncbi.nlm.nih.gov/'+id for id in priority_pubmed_ids]
            
            # 遍历每个优先级 URL
            for url in priority_urls:
                # 从 citation_id_map 中找到对应的 WebSearchLink
                link = None
                for citation_id, weblink in runtime_info['citation_id_map'].items():
                    if weblink.url == url:
                        link = weblink
                        break
                
                if not link:
                    logger.warning(f"Could not find WebSearchLink for priority URL: {url}")
                    continue
                
                # 读取 PDF 原文
                pmid = url.split('/')[-1]
                file_path = pmid_map.get(pmid, '')
                if not file_path:
                    logger.warning(f"Could not find PDF file for URL: {url}")
                    continue
                    
                try:
                    with open(file_path, "rb") as file:
                        file_content_bytes = file.read()
                    buf = BytesIO(file_content_bytes)
                    text = pdf_to_text(buf, by_page=True)
                    
                    # 将 text 列表合并为字符串（如果需要）
                    if isinstance(text, list):
                        text = "\n".join(text)
                    
                    url_content_map[url] = f"Title: {link.title}\n\nAbstract: {link.summ}\n\nAuthor: {link.author}\n\nContent:\n{text}"
                except Exception as e:
                    logger.warning(f"Failed to read PDF for {url}: {e}")
                    continue
            
        tasks = []
        task_urls = []
        for url, raw_content in raw_content_map.items():
            # Get title for this URL
            title = url_title_map.get(url, '')
            if not title:
                # Try to get from citation_id_map
                for citation_id, link in runtime_info['citation_id_map'].items():
                    if link.url == url:
                        title = link.title or link.site_name or ''
                        break

            # Check raw_content length
            if len(raw_content) > self.single_content_max_lenght:
                task = asyncio.create_task(
                    reading_with_semaphore(raw_content, title)
                )
                tasks.append(task)
                task_urls.append(url)
            else:
                url_content_map[url] = raw_content

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(task_urls, results):
            if isinstance(result, Exception):
                logger.warning(f'Reading article for {url} failed: {result}')
                continue
            if result:
                url_content_map[url] = result

        logger.info(f"DocumentReader compressed {len(url_content_map)} documents")
        return titles_str, url_content_map, list(url_title_map.items())

    def _format_reference_fcr(
        self,
        url_content_map: dict,
        runtime_info: dict,
    ) -> dict:
        r"""Format reference function calling result."""
        res = {
            'reading_content': [],
        }
        for url, content in url_content_map.items():
            link = runtime_info['url_map'].get(url)
            if link:
                res['reading_content'].append({
                    'citation_id': link.id,
                    'content': content,
                })
        return res
    
    def _format_pubmed_weblink(
        self,
        pubmed_response: dict,
        runtime_info: dict) -> WebSearchLink:
        # init web search link
        # set url
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pubmed_response.get('uid', '')}"
        id = runtime_info['url_map'][url].id if url in runtime_info['url_map'] else len(runtime_info['url_map']) + 1
        pubmed_response['pubmed_id'] = pubmed_response.get('uid', '')
        
        # get article ids, i.e. pmc, doi
        article_ids = pubmed_response.get('articleids', [])
        article_ids = {item.get('idtype', ''): item.get('value', '') for item in article_ids if isinstance(item, dict)}
        # get author
        authors = ",".join([item.get('name', '') for item in pubmed_response.get('authors', [])])

        link = WebSearchLink(
            id=id,
            pubmed_id=pubmed_response.get("uid", ''),
            pmcid=article_ids.get('pmcid', ''),
            pmc=article_ids.get('pmc', ''),
            pii=article_ids.get('pii', ''),
            doi=article_ids.get("DOI", ""),
            summ=pubmed_response.get('summary', ''),
            url=url,
            title=pubmed_response.get("title", ""),
            site_name=pubmed_response.get('source', "PubMed"),
            issn=pubmed_response.get("issn", ""),
            essn=pubmed_response.get("essn", ""),
            full_journal_name=pubmed_response.get("fulljournalname", ""),
            nlm_id=pubmed_response.get("nlmuniqueid", ""),
            pub_date=pubmed_response.get("pubdate", ''),
            author=authors,
            type=SearchType.PUBMED,
            journal_abbr=pubmed_response.get("journal_abbr", ""),
            year_of_publication=pubmed_response.get("year_of_publication", ""),
            volume=pubmed_response.get("volume", ""),
            issue=pubmed_response.get("issue", ""),
            pagination=pubmed_response.get("pagination", ""),
        )
        
        # Generate citation (Vancouver format)
        link.citation = generate_citation(link)

        # get sci if
        key_word = link.issn or link.full_journal_name or link.nlm_id or link.site_name
        if key_word != '':
            sciif_response = self.sci_if_client.search_by_issn(value=key_word)
            if 'factor' in sciif_response:
                link.cite_score = str(sciif_response['factor'])
                pubmed_response['cite_score'] = str(sciif_response['factor'])

        # Update global url map
        runtime_info['url_map'][url] = link
        runtime_info['citation_id_map'][id] = link

        return link

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
        #logger.info(f"Attachments: {attachments}, folders: {folders}")
    
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
            'original_history_messages': copy.deepcopy(history_messages), # Store the original history messages for future rollback.
            'shell_result': [], # Store local shell task results.
            'sandbox_url_map': {}, # real OSS url -> placeholder; flipped on unmask
            'attachments': [], # Store user uploaded files.
            'parent_id': parent_id,
            'task_context': { # Store task context, e.g. task idm
                'task_id': task_id,
            },
            'generated_images': [], # Store generated images
            'priority_pubmed_ids': kwargs.get('priority_pubmed_ids', []),
            'attachment_fetch_mode': attachment_fetch_mode,
            'last_function_calls': 0,
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

    def _init_response(
        self,
        user_prompt: str,
        attachments: List,
        folders: List,
        language: str = constants.ENGLISH) -> MindSearchResponse:

        response = MindSearchResponse(
            search_graph=SearchNode(
                search_type=SearchType.UNKNOWN,
                query=user_prompt,
                thought_process=translate("ui.task_analysis", language),
                children=[SearchNode(
                        search_type=SearchType.UNKNOWN,
                        query=translate("ui.think", language),
                        processing_type=ProcessingType.THINKING)],
            ),
            processing_type=ProcessingType.PROCESSING,
            files=[{'name': f.get('name'), 'id': f.get('id')} for f in attachments],
            folders=[{'name': f.get('name'), 'id': f.get('id'), 'full_path': f.get('full_path')} for f in folders],
        )

        return response
    
    def _init_components(
        self,
        history_messages: List[dict], 
        kwargs
    ):
        r"""
        Init agent components by language or whether need rag.
        """

        params = kwargs.get('params', {})
        language = self.helper.get_intention_language(params.get('language', ''))
        self.force_output_language = bool(params.get('force_output_language', False))
        self.preferred_output_language = params.get('preferred_output_language', '')
        background = params.get('background', '')
        files = params.get('files', [])
        history_attachments = params.get('history_files', []) or kwargs.get('history_files', [])
        history_folders = params.get('history_folders', []) or kwargs.get('history_folders', [])
        parent_id = params.get('parent_id', None)
        user_email = params.get('user', None)
        task_id = params.get('task_id', None) or task_id_var.get()
        client_ip = params.get('client_ip', '')
        attachment_fetch_mode = self._resolve_attachment_fetch_mode(client_ip)

        history_messages = [] if history_messages is None else copy.deepcopy(history_messages)
        return (
            language, 
            background,
            self._remove_reference(history_messages),
            files,
            history_attachments,
            parent_id,
            user_email,
            task_id,
            attachment_fetch_mode,
        )

    @staticmethod
    def format_attachment_link(
        attachment: dict,
        runtime_info: dict
    ) -> WebSearchLink:

        url = attachment.get('url', '')
        if not url:
            return None

        if url in runtime_info['url_map']:
            return runtime_info['url_map'][url]
        
        id = len(runtime_info['url_map']) + 1
        link = WebSearchLink(
            id = id,
            url=attachment.get('url', ''),
            summ='',
            title=attachment.get('name', ''),
            attachment_id=str(attachment.get('id', '')),
            type=SearchType.ATTACHEMNT,
        )
        
        # Generate citation (Vancouver format)
        link.citation = generate_citation(link)
        
        # Update global url map
        runtime_info['url_map'][link.url] = link
        runtime_info['citation_id_map'][id] = link

        return link

    async def _read_attachments(
        self,
        user_prompt: str,
        history_messages: List[dict],
        attachment_ids: List[str],
        history_attachments: List[List[str]],
        folders: List[dict],
        runtime_info: dict,
        response: MindSearchResponse,
        language: str,
        user_email: str = None
    ):
        r"""
        1. Fetch attachment record from database by file ids.
        2. Fetch attachment content from cloud storage.
        3. Add attachment first parts into the history messages.
        """
        # Check if all inner lists in history_attachments are empty
        # history_attachments is List[List[str]], so we need to check if any sublist has content
        has_history_attachment_ids = any(group for group in (history_attachments or []))
        has_folders = any(group for group in (folders or []))
        if not attachment_ids and not has_history_attachment_ids and not has_folders:
            return

        def format_reading_query(language: str):
            return translate("ui.reading_attachment", language)

        def format_finished_query(language: str):
            return translate("ui.attachment_read", language)
        
        node = self._add_thinking_node(response, language)
        node.query = format_reading_query(language)
        yield response

        has_history_attachment_context = False
        has_current_attachment_context = False
        has_kb_attachment_context = False

        # Merge history attachments id into sets.
        # Keep historical context before current-turn context to reduce recency bias.
        history_attachment_ids = set()
        for attachment in history_attachments:
            history_attachment_ids.update(attachment)

        history_attachment_ids = list(history_attachment_ids)
        attachment_chunks, images, image_urls = self._build_attachment_content_arr_by_ids(
            attachment_ids=history_attachment_ids,
            runtime_info=runtime_info,
            format_attachment_link=MindSearchAgentV3.format_attachment_link,
        )
        if runtime_info.get('attachments'):
            self.attachment_included = True

        content_arr = []
        if attachment_chunks:
            has_history_attachment_context = True
            content_arr = content_arr + [
                {
                    'type': "input_text",
                    "text": (
                        "Context type: historical attachments from previous turns (low priority). "
                        "Use only as supplementary context when current-turn attachments or knowledge-base "
                        "evidence are missing. If there is any conflict, do not prioritize historical content."
                    )
                },
                {'type': "input_text", "text": attachment_chunks},
            ]
        if images:
            has_history_attachment_context = True
            content_arr = content_arr + [
                {
                    'type': "input_text",
                    "text": (
                        "Context type: historical uploaded images from previous turns (low priority). "
                        "Use only as supplementary context."
                    )
                },
            ] + images

        # Only append if content_arr is not empty to avoid Claude API error
        if content_arr:
            history_messages.append({
                "role": "user",
                "content": content_arr,
            })

        # Build attachment content array for current attachments
        attachment_chunks, images, image_urls = self._build_attachment_content_arr_by_ids(
            attachment_ids=attachment_ids,
            runtime_info=runtime_info,
            format_attachment_link=MindSearchAgentV3.format_attachment_link,
        )
        if runtime_info.get('attachments'):
            self.attachment_included = True

        content_arr = []
        if attachment_chunks:
            has_current_attachment_context = True
            content_arr = content_arr + [
                {
                    'type': "input_text",
                    "text": (
                        "Context type: current-turn uploaded attachments (high priority). "
                        "Treat these as primary evidence for the current user question."
                    )
                },
                {'type': "input_text", "text": attachment_chunks},               
            ]
        if images:
            has_current_attachment_context = True
            text = f"There are user upload image files."
            if image_urls:
                text = text + f"The image urls are: {image_urls}, you can use the image urls to generate image."

            content_arr = content_arr + [
                {'type': "input_text", "text": text},
            ] + images

        # Only append if content_arr is not empty to avoid Claude API error
        if content_arr:
            history_messages.append({
                "role": "user",
                "content": content_arr,
            })

        # Build folder content array
        # First try to search and selection from database
        # Second try to list all files in the folder, for question like "find all files in the folder", "tell me what about this folder"
        if folders:
            # First try to search and select related files from database
            for folder in folders:
                if not folder.get('id'):
                    continue
                # search and selection from database
                # use mini llm to check user's query is related to the folder
                # when user's query is ask to summarize, scan the folder, we should simply return the folder's detail
                folder_id = folder.get('id')
                folder_file_ids = await search_and_selection(
                    user_query=user_prompt,
                    parent_id=folder_id,
                    user_email=user_email,
                    force_empty=True)
                
                if folder_file_ids and len(folder_file_ids) > 0:
                    attachment_chunks, images, image_urls = self._build_attachment_content_arr_by_ids(
                        attachment_ids=folder_file_ids,
                        runtime_info=runtime_info,
                        format_attachment_link=MindSearchAgentV3.format_attachment_link,
                    )
                else:
                    attachment_chunks, images, image_urls = self._build_attachment_content_arr_by_folder(
                        folder_id=folder_id,
                        runtime_info=runtime_info,
                        format_attachment_link=MindSearchAgentV3.format_attachment_link,
                    )

                content_arr = []
                if attachment_chunks:
                    has_kb_attachment_context = True
                    attachment_intro = (
                        "Context type: knowledge-base attachments selected for this question (high priority), "
                        f"knowledge base name: {folder.get('name')}, "
                        f"knowledge base id: {folder_id}."
                    )
                    content_arr = content_arr + [
                        {'type': "input_text", "text": attachment_intro},
                        {'type': "input_text", "text": attachment_chunks},
                    ]
                if images:
                    has_kb_attachment_context = True
                    text = (
                        "Context type: knowledge-base uploaded images selected for this question (high priority). "
                        f"knowledge base name: {folder.get('name')}, "
                        f"knowledge base id: {folder_id}."
                    )
                    if image_urls:
                        text = text + f"The image urls are: {image_urls}, you can use the image urls to generate image."

                    content_arr = content_arr + [
                        {'type': "input_text", "text": text},
                    ] + images

                # Only append if content_arr is not empty to avoid Claude API error
                if content_arr:
                    history_messages.append({
                        "role": "user",
                        "content": content_arr,
                    })

        # Add explicit evidence-priority instruction for final answering model.
        if has_history_attachment_context or has_current_attachment_context or has_kb_attachment_context:
            priority_instruction = (
                "Evidence priority for this turn:\n"
                "1) Current-turn uploaded attachments and knowledge-base content selected for this question are primary evidence.\n"
                "2) Historical attachments from previous turns are secondary context.\n"
                "3) If historical content conflicts with current-turn attachments or knowledge-base content, follow the primary evidence and ignore the conflicting historical part.\n"
                "4) If primary evidence is insufficient, state the gap explicitly instead of overusing historical content."
            )
            history_messages.append({
                "role": "user",
                "content": [
                    {'type': "input_text", "text": priority_instruction},
                ],
            })
            
        node.query = format_finished_query(language)
        node.processing_type = ProcessingType.DONE
        yield response

    def _build_attachment_content_arr_by_ids(
        self,
        attachment_ids: List[str],
        runtime_info: dict,
        format_attachment_link: Callable[[dict, dict], WebSearchLink],
    ) -> list:
        """
        Build the message content array for attachments and update runtime_info.
        """
        if not attachment_ids or len(attachment_ids) == 0:
            return '', [], []

        attachments = self.attachment_manager.fetch_attachments(
            attachment_ids,
            True,
            mode=runtime_info.get('attachment_fetch_mode', 'sql'),
        )
        # store attachments to runtime_info
        runtime_info['attachments'] = runtime_info['attachments'] + attachments
        if not attachments:
            logger.warning(f"[_build_attachment_content_arr] No attachments found")
            return '', [], []
        
        return self._format_attachments_content(attachments, runtime_info, format_attachment_link)

    def _build_attachment_content_arr_by_folder(
        self,
        folder_id: str,
        runtime_info: dict,
        format_attachment_link: Callable[[dict, dict], WebSearchLink],
        page: int = 1,
        page_size: int = 50,
    ) -> list:
        """
        Build the message content array for attachments and update runtime_info.
        """
        if not folder_id:
            return '', [], []

        attachments = self.attachment_manager.fetch_attachments_by_floder(
            folder_id,
            page,
            page_size,
        )
        # store attachments to runtime_info
        runtime_info['attachments'] = runtime_info['attachments'] + attachments
        if not attachments:
            logger.warning(f"[_build_attachment_content_arr] No attachments found")
            return '', [], []
        
        return self._format_attachments_content(attachments, runtime_info, format_attachment_link)
    
    def _format_attachments_content(
        self,
        attachments: List[dict],
        runtime_info: dict,
        format_attachment_link: Callable[[dict, dict], WebSearchLink],
        chunk_length: int = 4 * 1024,
    ) -> str:
        """
        Format attachments content to string.
        """
        # Filter out content attachments
        documents = [attachment for attachment in attachments if attachment.get('content', '')]

        # Filter out image attachments
        images = [attachment for attachment in attachments if attachment.get('type', '') in ['image']]

        # Filter out no-content file attachments (e.g. scanned PDFs where Backend couldn't extract text)
        image_ids = {id(img) for img in images}
        no_content_files = [
            a for a in attachments
            if not a.get('content', '') and id(a) not in image_ids
        ]

        # Add attachments to runtime_info['url_map'] and history message
        attachments_chunks = ""
        chunk_length = 4 * 1024 if len(documents) < 15 else 2 * 1024
        for document in documents:
            # add runtime_info url_map
            attachment_link = format_attachment_link(document, runtime_info)
            if attachment_link is None:
                logger.warning("[_format_attachments_content] Skip document attachment without url")
                continue
            runtime_info['url_map'][attachment_link.url] = attachment_link
            # add content asbtract
            content = document['content'].get('content', '')
            tokens = document.get('content', {}).get('tokens', 0)
            if tokens == 0:
                tokens = len(content) * 1.25
            runtime_info['attachment_url_map'][attachment_link.url] = content

            # add content preview (truncated for context)
            if isinstance(content, list):
                content_preview = "\n".join(content)
            else:
                content_preview = content
            content_preview = content_preview[:chunk_length]

            # add history_messages
            attachments_chunks = attachments_chunks + f"""
[citation:{attachment_link.id}]
Title: {attachment_link.title}
Length: {tokens}
URL: {attachment_link.url}
Content Preview (Only first part of the whole document): {content_preview}
[citation:{attachment_link.id}]
"""

        # Add no-content file attachments so LLM knows they exist and can download/parse them
        for file_attachment in no_content_files:
            attachment_link = format_attachment_link(file_attachment, runtime_info)
            if attachment_link is None:
                logger.warning("[_format_attachments_content] Skip file attachment without url")
                continue
            runtime_info['url_map'][attachment_link.url] = attachment_link
            attachments_chunks = attachments_chunks + f"""
[citation:{attachment_link.id}]
Title: {attachment_link.title}
URL: {attachment_link.url}
Note: File content not pre-extracted. Use AttachmentDownload to download this file, then use AgentRunSandbox to parse and analyze it.
[citation:{attachment_link.id}]
"""

        image_messages = []
        image_urls = []
        max_size = (768, 768) if len(images) > 3 else (1024, 1024)
        for image in images:
            attachment_link = format_attachment_link(image, runtime_info)
            if attachment_link is None:
                logger.warning("[_format_attachments_content] Skip image attachment without url")
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

    def _format_final_source(
        self,
        id: int,
        search_result: WebSearchLink) -> dict:
        r"""
        Format final source link.
        """
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
            'citation': self._compress_json(search_result.citation),
        }

    def _compress_json(self, obj: dict) -> str:
        res = ''
        try:
            res = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Invalid compres {e}")
        return res
    
    def _format_source(
        self,
        runtime_info: dict,
        source: List[WebSearchLink]
    ) -> str:
        r"""
        Format search result source to string, e.g.
        [citation:1]
        site name: pubmed
        publisted date: 2024
        [citation:1]
        """

        def format_pubmed(item: dict) -> dict:
            return {
                'title': item.get('title', ''),
                'summary': item.get('summary', '') or item.get('summ', ''),
                'content': item.get('content', ''),
                'site name': 'PubMed',
                'journal name': item.get('fulljournalname', '') or item.get('full_journal_name', ''),
                'published time': item.get('epubdate', ''),
                'authors': item.get('authors', ''),
                'sci impact factor': item.get('sci_if', ''),
                'is free': True if item.get('pmcid') else False,
                'citation': self._compress_json(item.get('citation')),
            }

        def format_websearch(item: dict) -> dict:
            return {
                'site name': item.get('site_name', ''),
                'title': item.get('title', ''),
                'summary': item.get('summary', '') or item.get('summ', ''),
                'content': item.get('content', ''),
                'citation': self._compress_json(item.get('citation')),
            }

        websearch_results = f""

        for link in source[:self.max_source_count]:
            link_json = link.model_dump()
            
            # Add url content
            if link.url in runtime_info['url_content_map']:
                link_json['content'] = runtime_info['url_content_map'][link.url]

            # Add url related detail, e.g. site name, published date.
            if link.type == SearchType.PUBMED:
                link_json =  format_pubmed(link_json)
            else:
                link_json = format_websearch(link_json)
            
            id = link.id
            webpage_content = f"[citation:{id}]\n"
            for key, value in link_json.items():
                if value != '':
                    webpage_content += f"{key}: {value}\n"
            webpage_content += f"[citation:{id}]\n"
            
            websearch_results += webpage_content

        # Include ClinicalGuidelineSearch and DrugManualSearch results (not in url_map)
        guideline_results = [r for r in runtime_info['tool_results'] if r.name == ClinicalGuidelineSearch.__name__ and r.result]
        drug_manual_results = [r for r in runtime_info['tool_results'] if r.name == DrugManualSearch.__name__ and r.result]
        for r in guideline_results:
            websearch_results += "\n[ClinicalGuidelineSearch]\n"
            websearch_results += json.dumps(r.result, ensure_ascii=False, indent=2) + "\n"
        for r in drug_manual_results:
            websearch_results += "\n[DrugManualSearch]\n"
            websearch_results += json.dumps(r.result, ensure_ascii=False, indent=2) + "\n"

        return websearch_results

    def _check_history_results(
        self,
        runtime_info: dict,
    ) -> bool:
        """
        Check if the history results are enough to answer the user's question.
        """
        tool_results = len(runtime_info['tool_results'])
        search_results = len(runtime_info['url_map'])
        shell_results = len(runtime_info['shell_result'])
        return tool_results + search_results + shell_results > 0

    def _format_final_searchresults(
        self,
        runtime_info: dict,
        history_messages: List[dict]) -> str:

        # format history search, add explanation to final output llm
        history_search = "\n".join([
            result.name + ":" + result.args.get('explanation', '')
            for result in runtime_info['tool_results']
        ])

        # sort web search result
        # 1. links with content
        # 2. PubMed search results
        # 3. Patents
        # 4. Common links
        source = []
        url_set = set()

        # Fetch links with content
        for url, item in runtime_info['url_map'].items():
            if url in runtime_info['url_content_map']:
                source.append(item)
                url_set.add(url)
        
        # Fetch PubMed links
        for url, item in runtime_info['url_map'].items():
            if url not in url_set and item.type == SearchType.PUBMED:
                source.append(item)
                url_set.add(url)

        # Fetch Patent links
        for url, item in runtime_info['url_map'].items():
            if url not in url_set and item.type == SearchType.PATENT:
                source.append(item)
                url_set.add(url)
        
        # Add left links
        for url, item in runtime_info['url_map'].items():
            if url not in url_set:
                source.append(item)

        # Constrain the source length to avoid context window too large.
        source = source[:self.final_output_source_max_length]
        # format websearch result str
        websearch_results = self._format_source(runtime_info, source)

        # add local shell task results
        local_shell_results = [
            result
            for result in runtime_info['shell_result']
        ]

        # add stock prices
        stock_prices = [
            result.result
            for result in runtime_info['tool_results'] if result.name == StockHistoricalPriceQuery.__name__
        ]

        # add financial statements
        """
        financial_statements = [
            search.get('result', {})
            for search in runtime_info['tool_results'] if search.get('function', '') in [FinancialStatements().name, ChinaCompanyFinancialStatements().name]
        ]
        """

        # truncate input prompt
        #logger.info(f"{websearch_results}")
        """
        websearch_results, history_messages = tokenizer.truncate_messages_by_tokens(
            json.dumps(websearch_results, separators=(',', ':'), ensure_ascii=False),
            history_messages,
            56*1000,
            "deepseek"
        )
        """
        #logger.info(f"{websearch_results}")

        final_result = f"""
<history_search_steps>
{json.dumps(history_search, separators=(',', ':'), ensure_ascii=False)}
</history_search_steps>

<searching_resutls>
{json.dumps(websearch_results, separators=(',', ':'), ensure_ascii=False)}
</searching_resutls>
"""

        if len(local_shell_results) > 0:
            final_result += f"""
<local_shell_results>
{json.dumps(local_shell_results, separators=(',', ':'), ensure_ascii=False)}
</local_shell_results>
"""

        if len(stock_prices) > 0:
            final_result += f"""
<stock_prices>
{json.dumps(stock_prices, separators=(',', ':'), ensure_ascii=False)}
</stock_prices>
"""

        generated_images = runtime_info.get('generated_images', [])
        successful_images = [img for img in generated_images if img.get('url')]
        if successful_images:
            images_info = "\n".join([
                #f"- Image name: {img['name']}, URL: {img['url']}"
                f"- Image name: {img['name']}"
                for img in successful_images
            ])
            final_result += f"""
<generated_images>
{images_info}
</generated_images>
"""

        #if len(financial_statements) > 0:
        #    final_result += f"""<financial_statements>{json.dumps(financial_statements, separators=(',', ':'), ensure_ascii=False)}</financial_statements>"""
        # truncate final result to fit context window (leave room for sys_prompt, history_messages, etc.)
        # Determine tokenizer model based on final_output_agent's LLM provider
        tokenizer_model = 'openai-o3'
        token_limit = 200000
        if self.final_output_agent.llm.provider == 'anthropic':
            tokenizer_model = 'claude'
            token_limit = 130000
        final_result = tokenizer.truncate_by_tokens(final_result, token_limit, tokenizer_model)
        return final_result
    
    def _truncate_final_output(
        self,
        content: str
    ) -> str:
        return tokenizer.truncate_by_tokens(content, self.compact_max_item_tokens, 'openai-o3')

    def _remove_reference(
        self,
        history_messages: List[dict]):
        r"""
        Remove history messages' citation link to avoid hallucination.
        """
        # Replace numeric markdown citations like [1](url) with human readable site names.
        cloud_keywords = (
            "aliyuncs.com",
            "blob.core.windows.net",
        )

        def _get_site_name(url: str) -> str:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            path = parsed.path or ""
            last_segment = unquote(path.rstrip("/").split("/")[-1]) if path else ""
            is_cloud = any(k in host for k in cloud_keywords)

            if is_cloud and last_segment:
                return last_segment

            if host:
                return host[4:] if host.startswith("www.") else host

            return last_segment or url

        pattern = re.compile(r"\[(\d+)\]\(([^)]+)\)")

        for message in history_messages:
            if 'role' in message and message['role'] == 'assistant':
                content = message.get('content', '')
                if not content:
                    continue

                def repl(match):
                    url = match.group(2).strip()
                    site_name = _get_site_name(url)
                    return f"[{site_name}]({url})"

                message['content'] = pattern.sub(repl, content)

        return history_messages

    def _add_finalout_node(
        self,
        response: MindSearchResponse,
        language: str) -> SearchNode:
        r"""
        Add a search node to notify user, current is preparing final output.
        """
        answering = translate("ui.answering", language)
        node = SearchNode(
            search_type=SearchType.HELPER,
            query=answering,
            summary=answering,
            processing_type=ProcessingType.PROCESSING)
        
        response.search_graph.add_child(node)
        return node

    async def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        # Response user's question
        websearch_results = self._format_final_searchresults(runtime_info, history_messages)

        if self.force_output_language and self.preferred_output_language:
            # Add an explicit instruction into the user-question block so downstream
            # prompt constraints consistently respect API-level language requests.
            user_prompt = (
                f"{user_prompt}\n\n"
                f"[Output language requirement: reply in {self.preferred_output_language}.]"
            )

        final_user_prompt = gpt_o_search_final_output_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language,
            background=background,
            websearch_results=websearch_results,
            user_question=user_prompt)
        
        return gpt_5_search_final_output_sys_pt, final_user_prompt

    def _get_generated_images(
        self,
        runtime_info: dict) -> List[str]:
        generated_images = runtime_info.get('generated_images', [])
        successful_images = [img for img in generated_images if img.get('url')]
        return [img['url'] for img in successful_images]

    async def _final_output_with_compact(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async for chunk in self._final_output(user_prompt, history_messages, runtime_info, background, language):
                    yield chunk
                return  # Success, exit
            except (openai.APIError, anthropic.APIStatusError) as e:
                is_context_exceeded = (
                    (isinstance(e, openai.APIError) and e.code == 'context_length_exceeded') or
                    (isinstance(e, anthropic.APIStatusError) and e.status_code == 413)
                )
                is_overloaded = (
                    isinstance(e, anthropic.APIStatusError) and e.status_code == 529
                )
                is_rate_limited = (
                    (isinstance(e, openai.APIError) and e.code in ['rate_limit_exceeded', 'too_many_requests']) or
                    (isinstance(e, anthropic.APIStatusError) and e.status_code == 429)
                )

                if is_context_exceeded:
                    logger.warning(f"Context length exceeded, try to compact history messages.")
                    await self._compact_history_messages(history_messages, user_prompt, runtime_info)
                    # After compact, retry with compacted history_messages
                    async for chunk in self._final_output(user_prompt, history_messages, runtime_info, background, language):
                        yield chunk
                    return
                elif (is_overloaded or is_rate_limited) and attempt < max_retries - 1:
                    wait_time = 2 ** attempt * 5  # 5s, 10s, 20s
                    logger.warning(f"API overloaded/rate limited (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.warning(f"Final output failed {e}")
                    raise e
            except (openai.APITimeoutError, httpx.TimeoutException) as e:
                timeout_wait_time = 15
                is_last_attempt = attempt >= max_retries - 1

                # Do not swallow the final timeout failure.
                if is_last_attempt:
                    logger.warning(
                        f"Final output timeout (attempt {attempt + 1}/{max_retries}), no retries left: {e}"
                    )
                    raise e

                # First timeout: backoff and retry with current model.
                if attempt == 0:
                    logger.warning(
                        f"Final output timeout (attempt {attempt + 1}/{max_retries}), retrying in {timeout_wait_time}s..."
                    )
                    await asyncio.sleep(timeout_wait_time)
                    continue

                # Subsequent timeout: switch to smaller model class and retry.
                if self.final_output_agent.llm != GPT5Nano:
                    logger.warning("Final output timeout again, switching final output llm to GPT5Nano for retry.")
                    self.final_output_agent.llm = GPT5Nano
                await asyncio.sleep(timeout_wait_time)
                continue
            except LLMIncomplete as e:
                logger.warning(f"Final output incomplete, change another model and try again")
                self.final_output_agent.llm = ClaudeSonnet46
                continue

        raise Exception(f"Final output failed after {max_retries} attempts")

    async def _final_output(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH):

        sys_prompt, final_user_prompt = await self._format_final_output_prompt(
            user_prompt, history_messages, runtime_info, background, language)
        # Add image generation tool url for final output llm
        generated_images = self._get_generated_images(runtime_info)
        self.final_output_agent.sys_prompt = sys_prompt

        logger.info(f"Mindesearch final response input, history_messages: {len(history_messages)}, generated_images: {len(generated_images)}  final_user_prompt: {final_user_prompt[:300]}...{final_user_prompt[-300:]}, generated_images: {generated_images}")
        # check token length
        
        # use different agent
        output = ""
        buffer = ""
        last_yield_time = time.time()
        yield_interval = 0.3 # 调整输出时间间隔(秒)
        async for chunk in self.final_output_agent.stream_call(
            user_prompt=final_user_prompt,
            history_messages=history_messages,
            images=generated_images):
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

        # TODO: handle azure content filter issue
        if output == "I'm sorry, but I cannot assist with that request.":
            raise LLMIncomplete(provider=self.final_output_agent.llm.provider, message="Incomplete")

    def _update_finalout_node(self, response: MindSearchResponse, language: str):
        if not response.search_graph or len(response.search_graph.children) == 0:
            return
        
        final_node = response.search_graph.children[-1]

        if final_node.search_type == SearchType.HELPER:
            final_node.summary = translate("ui.model_completed", language)

    def _format_citation(
        self,
        content: str,
        runtime_info: dict,
    ) -> str:
        urls = [
            self._format_final_source(item.id, item)
            for item in runtime_info['url_map'].values()
        ]
        content = self.helper.format_citation(content)
        content, _ = self.helper.remove_unused_citation(urls, content)
        return content

    def _format_final_output(
        self,
        response: MindSearchResponse,
        language: str = constants.ENGLISH,
        runtime_info: dict = {},
        remove_citation: bool = False):

        # update final node query
        self._update_finalout_node(response=response, language=language)

        # Mark unfinished nodes done, but keep explicit FAILED so the HITL
        # thought board can still show which search steps failed.
        for node in response.search_graph.children:
            if node.processing_type != ProcessingType.FAILED:
                node.processing_type = ProcessingType.DONE

        # format source
        if not runtime_info.get('source'):
            runtime_info['source'] = [
                self._format_final_source(item.id, item)
                for item in runtime_info['url_map'].values()
            ]

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
                    search_result.summ = ''
            for item in response.search_graph.source:
                if 'summary' in item:
                    item['summary'] = item['summary'][:200]

        # remove all citation in the content, but ignore image markdown like ![alt](url)
        url_pattern = r'(?<!!)\[(.*?)\]\(([\w+.-]+:[^\s\)]+)\)'
        if remove_citation:
            response.content = re.sub(url_pattern, '', response.content)

        # fix norag output doesnot contain citation issue
        if response.search_graph and len(response.search_graph.source) == 0:
            # get all citations
            matches = re.findall(url_pattern, response.content)

            url_map = {}
            for match in matches:
                url = match[1]
                # Skip sandbox download links (OSS presigned URLs) — these are file attachments, not citations
                if 'project-sandbox.oss' in url or '/mnt/workspace/' in url:
                    continue
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
                value = url_map.get(url)
                if not value:
                    return match.group(0)  # keep original link (e.g. sandbox download links)
                return f"[{value['id']}]({value['url']})"
            
            # rewrite content fix id not continue issue
            response.content = re.sub(url_pattern, replace_func, response.content)
            # rewrite 
            response.search_graph.source = list(url_map.values())

        # add generated images
        # check content contains image url
        generated_images = runtime_info.get('generated_images', [])
        for image in generated_images:
            if image.get('url'):
                image_url = image['url']
                image_markdown_pattern = rf"!\[[^\]]*\]\(\s*{re.escape(image_url)}(?:\s+\"[^\"]*\")?\s*\)"
                if not re.search(image_markdown_pattern, response.content or ''):
                    image_name = image.get('name') or 'image'
                    response.content = (response.content or '').rstrip() + f"\n\n![{image_name}]({image_url})"
        
        # Restore real OSS sandbox download URLs from `[[SANDBOX_URL_N]]` placeholders
        # that were masked into the LLM input. Done before any downstream content
        # processing so subsequent sandbox-URL-aware logic sees the real URLs.
        response.content = self._unmask_sandbox_urls(response.content, runtime_info)

        return response

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        start_time = time.time()
        
        async for response, background, runtime_info, language, history_messages in self._init_agent(
            user_prompt,
            history_messages,
            images,
            **kwargs):
            yield response
        
        # Thinking and prepare meta for answering
        async for tmp_response in self._task_with_heartbeat(
            response, 
            self._thinking,
            response,
            runtime_info,
            user_prompt,
            copy.deepcopy(history_messages),
            background,
            language):
            yield tmp_response

        # Use tmp response to avoid chunk too big
        tmp_response = MindSearchResponse(processing_type=ProcessingType.RESPONSING)
        async for chunk in self._final_output_with_compact(
            user_prompt=user_prompt,
            history_messages=history_messages,
            runtime_info=runtime_info,
            background=background,
            language=language):
            if not chunk:
                continue
            tmp_response.content = chunk
            yield tmp_response

        response.content = tmp_response.content  
            
        self._format_final_output(response=response, language=language, runtime_info=runtime_info)
        yield response

        response.processing_type = ProcessingType.RESPONSEDONE
        yield response
        logger.info(f"MindSearch final output: {response.content} cost {time.time() - start_time}s")
