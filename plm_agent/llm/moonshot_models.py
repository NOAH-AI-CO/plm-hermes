
import io
import os
import time
import random
import logging
import datetime
from typing import List
from abc import ABC

from collections import defaultdict
from openai import AsyncOpenAI, AsyncStream

from config import api_config
from logging_config import log_id_var, task_id_var
from llm.base_model import BaseLLM
from utils.metadata import SingletonMeta

logger = logging.getLogger(__name__)


class Kimi(BaseLLM):

    first_chunk_timeout = 60
    timeout = 60
    extra_params = {'max_retries': 0}

    def __init__(self, model, **kwargs) -> None:
        self.extra_params['timeout'] = kwargs.get('timeout', self.timeout)
        if kwargs.get('max_retries', None) is not None:
            self.extra_params['max_retries'] = kwargs['max_retries']
        if kwargs.get('first_chunk_timeout', None):
            self.first_chunk_timeout = kwargs['first_chunk_timeout']
        self.model = model
        super().__init__()

    async def __call__(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        json_mode: bool = False,
        temperature: float = 0.6,
        max_tokens: int= 1024 * 32,
        **kwargs) -> str:
        """
        Asynchronously call the OpenAI API to generate a response.

        Args:
            sys_prompt (str): The system prompt, defaults to an empty string.
            user_prompt (str): The user prompt, defaults to an empty string.
            json_mode (bool): Whether to enable JSON mode, defaults to False.
            temperature (float): The randomness of the generation, defaults to 0.1.
            **kwargs: Additional parameters to pass to the API.

        Returns:
            str: The content of the generated response from the API.
        """
        call_start_time = datetime.datetime.now()
        tools = kwargs.get('tools', None)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        sys_message = [{"role": "system", "content": sys_prompt}] if sys_prompt else []
        user_message = [{"role": "user", "content": user_prompt}] if user_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        # Moonshot don't like system prompt
        messages = sys_message + history_messages + user_message
        #logger.info(f"Moonshot input {messages}")
        logger.info(f"Using temperature: {temperature}")
        #so far Moonshot don't support images
        try:
            start_time = time.time()
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                n=1, # TODO temperally for kimi k2 return 1 function calling
            )
            end_time = time.time()
            logger.info(f"Moonshot request cost time: {end_time - start_time}")
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warning(f"Moonshot API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
            response.choices[0].message, f"Model: {self.model}, Temperature: {temperature}, Usage: {response.usage}", call_start_time, **kwargs)

        return response.choices[0].message

    async def stream_call(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.6,
        max_tokens: int= 1024 * 32,
        **kwargs):

        call_start_time = datetime.datetime.now()
        sys_message = [{"role": "system", "content": sys_prompt}] if sys_prompt else []
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        messages = sys_message + history_messages + user_message
        

        for key in ['system_prompt', 'stream', 'stream_status', 'images']:
            kwargs.pop(key, None)

        #logger.info(f"Moonshot input {messages}")
        #logger.info(f"Using temperature: {temperature}")
        try:
            response: AsyncStream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                max_tokens=max_tokens,
                stream_options = {"include_usage": True},
            )
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warning(f"Moonshot API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e
        
        string_buffer = io.StringIO()
        reasoning_flag = False
        usage = defaultdict(int)
        connection_time = time.time()
        first_valid_chunk = False
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                # print('chunk usage', chunk.usage)
                usage = chunk.usage
                for key, value in usage.__dict__.items():
                    if type(value) == 'int':
                        usage[key] += value
            
            if len(chunk.choices) > 0:
                chunk_content = None
                content = getattr(chunk.choices[0].delta, 'content', None)
                reasoning_content = getattr(chunk.choices[0].delta, 'reasoning_content', None)

                # Huoshan and Moonshot original put thinking in reasoning_content
                if reasoning_content is not None and reasoning_content != '':
                    if not reasoning_flag:
                        reasoning_flag = True
                        chunk_content = f"<think>\n{reasoning_content}"
                    else:
                        chunk_content = reasoning_content

                # Get chunk_content, while in the reasoning stream there may be empty chunk, check content is 
                if content is not None and content != '':
                    if reasoning_flag:
                        reasoning_flag = False
                        chunk_content = f"</think>\n{content}"
                    else:
                        chunk_content = content

                if chunk_content:
                    # log first chunk cost time
                    if not first_valid_chunk:
                        logger.info(f"{self.client.__class__.__name__} Moonshot client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True

                    # return chunk content
                    string_buffer.write(chunk_content)
                    yield chunk_content
                    # if len(string_buffer.getvalue()) > 55:
                    #     break

            # break when wait too long
            if not first_valid_chunk:
                if time.time() - connection_time > self.first_chunk_timeout:
                    logger.warning(f"{self.client.__class__.__name__} first chunk timeout")
                    raise RuntimeError('Moonshot first chunk waiting timeout!!!')
            if self.stream_break:
                break
        await response.close()
        self.stream_break = False
        
        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time, **kwargs)
    
    async def log_results(self, sys_prompt: str, user_prompt: str, response, content: str, usage: str, start_time = None, **kwargs) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{log_id}] [{current_time}] {kwargs}\n")
            log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {content}\n{usage}\n")
            if start_time:
                time_delta = end_time - start_time
                formatted_time_delta = f"{time_delta.total_seconds():.2f} seconds"
                log_file.write(f"[{log_id}] Time spent: {formatted_time_delta}\n")
            log_file.write("="*64+"\n")
        with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
            time_delta = f"[{time_delta.total_seconds():.2f}s]" if start_time else ''
            log_file.write(f"[{log_id}] [{current_time}][{task_id}] {time_delta} {usage}\n")
            
    async def generate_stream(self, user_prompt, **kwargs):
        async for chunk in self.stream_call(user_prompt=user_prompt, **kwargs):
            yield chunk        


class KimiK2Thinking(Kimi, metaclass=SingletonMeta):
    
    provider = 'moonshot'

    def __init__(self, **kwargs) -> None:
        super().__init__(model='kimi-k2-thinking', **kwargs)
        self.client = AsyncOpenAI(api_key=api_config.MOONSHOT_API_KEY, base_url=api_config.MOONSHOT_API_ENDPOINT, **self.extra_params)


class KimiK2(Kimi, metaclass=SingletonMeta):
    
    provider = 'moonshot'

    def __init__(self, **kwargs) -> None:
        super().__init__(model='kimi-k2-0905-preview', **kwargs)
        self.client = AsyncOpenAI(api_key=api_config.MOONSHOT_API_KEY, base_url=api_config.MOONSHOT_API_ENDPOINT, **self.extra_params)

class AZUREKimiK2Thinking(Kimi, metaclass=SingletonMeta):
    
    provider = 'moonshot'

    def __init__(self, **kwargs) -> None:
        super().__init__(model=api_config.AZURE_KIMI_K2_THINKING_DEPLOYMENT, **kwargs)
        self.client = AsyncOpenAI(api_key=api_config.AZURE_KIMI_K2_THINKING_API_KEY, base_url=api_config.AZURE_KIMI_K2_THINKING_ENDPOINT, **self.extra_params)
