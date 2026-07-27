# -*- coding: utf-8 -*-
import time
import logging

from typing import List, Optional
from datetime import datetime
from openai.types.responses import Response

import agent.explore.constants as constants
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini
from llm.openai_models import Openai5Mini

from agent.explore.mindsearch_agent_v3 import (
    MindSearchAgentV3, MindSearchThinkingAgent
)
from agent.explore.mindsearch_prompt_v3_1 import (
    gpt54mini_thinking_sys_pt, gpt_thinking_sys_pt,
    gpt_query_rewrite_user_pt, gpt_query_rewrite_with_attachment_user_pt
)
from tools.explore.mindsearch_tools_v3 import (
    FunctionCallResult, Finished
)
from agent.explore.schema import (
    MindSearchResponse, ProcessingType
)

logger = logging.getLogger(__name__)


class MindSearchAgentV3_1(MindSearchAgentV3):
    llm: BaseLLM = GPT54Mini

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.thinking_agent = MindSearchThinkingAgent()
        self.max_thinking_rounds = 7

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str = constants.ENGLISH):
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        user_prompt = (gpt_query_rewrite_with_attachment_user_pt if self.attachment_included else gpt_query_rewrite_user_pt).format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return gpt54mini_thinking_sys_pt, user_prompt

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
        # Check llm_response to avoid first call failed
        if current_step == 0 or not runtime_info['llm_response']:

            thinking_agent.sys_prompt, final_user_prompt = self._format_thinking_prompt(user_prompt, language)
            llm_response = thinking_agent.stream_call_origin(
                user_prompt=final_user_prompt,
                history_messages=history_messages,
                prompt_cache_key='mindsearch_thinking_v3_1',)
                #reasoning={"effort": "high", "summary": "auto"})
        else:
            
            llm_response = thinking_agent.stream_call_origin(
                user_prompt='',
                history_messages=history_messages[-last_function_calls:],
                previous_response_id=runtime_info['llm_response'][-1]['response'].id)
        
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
                        runtime_info['llm_response'].clear()
                    
                    # reset last function calls to avoid multiple chunks
                    nlast_function_calls = 0
                    break # break the async for loop avoid continue chunk is completed

                elif chunk.status == 'completed':
                    self._process_chunk(chunk, history_messages, runtime_info)
            
            elif isinstance(chunk, FunctionCallResult):
                # process fc result
                # accumulate function calls，since chatgpt would return multi function calls，so we need add all back
                nlast_function_calls += 1

                node = self._add_thinking_node(response, language)
                runtime_info['tool_results'].append(chunk)
                await self._process_fc_result(chunk, history_messages, runtime_info, node, language)

                # break process
                if chunk.name == Finished.__name__:
                    finished = True

        runtime_info['last_function_calls'] = nlast_function_calls
        return nlast_function_calls, finished

    async def _final_output(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH):

        # Force streaming output
        # For chatgpt change tool_choice won't change pre tokens.
        self.thinking_agent.tool_choice = 'none'
        last_function_calls = runtime_info['last_function_calls']

        output = ""
        buffer = ""
        last_yield_time = time.time()
        yield_interval = 0.3 # 调整输出时间间隔(秒)

        if runtime_info['llm_response']:
            llm_response = self.thinking_agent.stream_call_origin(
                user_prompt='',
                history_messages=history_messages[-last_function_calls:],
                previous_response_id=runtime_info['llm_response'][-1]['response'].id,
                reasoning={"effort": "high", "summary": "auto"})
        else:

            final_user_prompt = gpt_query_rewrite_user_pt.format(
                current_date=datetime.now().strftime('%Y-%m-%d'),
                language=language,
                user_question=user_prompt,
            )

            llm_response = self.thinking_agent.stream_call_origin(
                user_prompt=final_user_prompt,
                history_messages=history_messages,
                reasoning={"effort": "high", "summary": "auto"})

        is_incomplete = False
        async for chunk in llm_response:
            if isinstance(chunk, Response):
                # check streaming last chunk status
                if chunk.status in ['incomplete', 'failed']:
                    logger.warning(f"[_final_output] Output is incomplete, try again")
                    is_incomplete = True
                    break

            elif isinstance(chunk, str):
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

        if is_incomplete:
            # call supper method to try again
            self.final_output_agent.llm = Openai5Mini
            
            async for chunk in super()._final_output(
                user_prompt, 
                runtime_info['original_history_messages'],
                runtime_info,
                background,
                language):
                yield chunk

    async def use_tool(self, user_prompt: str, history_messages: Optional[List[dict]] = None, images: Optional[List[str]] = None, **kwargs):
        start_time = time.time()
        
        async for response, background, runtime_info, language, history_messages in self._init_agent(user_prompt, history_messages, images, **kwargs):
            yield response
        
        # Thinking and prepare meta for answering
        async for tmp_response in self._task_with_heartbeat(
            response, 
            self._thinking,
            response,
            runtime_info,
            user_prompt,
            history_messages,
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
 