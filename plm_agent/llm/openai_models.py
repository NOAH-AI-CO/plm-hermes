import io
import os
import copy
import time
import httpx
import logging
import datetime

from abc import ABC
from typing import List, Optional
from collections import defaultdict

from openai import AsyncOpenAI

from config import api_config
from logging_config import log_id_var, task_id_var
from llm.azure_models import OpenAIReasoningModel, low_timeout_0_retry
from llm.base_model import BaseLLM, CompositeModel
from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)
granular_timeout = httpx.Timeout(45, connect=10.0)
low_timeout_0_retry = {"timeout": granular_timeout, "max_retries": 0}


# https://platform.openai.com/docs/guides/latest-model

class AsyncOpenaiClientSingletonMixin:
    """
    @summary: async openai singleton
    
    1. Use api_key to tell different clients.
    2. Put base_url, timeout, max_retries, default_headers in kwargs.
    """
    _instances: dict[str, AsyncOpenAI] = dict()

    @classmethod
    def make_key(cls, api_key, **kwargs):
        return api_key

    @classmethod
    def get_client(cls, api_key, **kwargs) -> AsyncOpenAI:
        key = cls.make_key(api_key, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = cls.initialize(api_key, **kwargs)
        return cls._instances[key]
    
    @classmethod
    def initialize(cls, api_key, **kwargs) -> None:
        key = cls.make_key(api_key, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = AsyncOpenAI(
                api_key=api_key,
                **kwargs
            )
        return cls._instances[key]

    @classmethod
    async def cleanup(cls, api_key, **kwargs) -> None:
        key = cls.make_key(api_key, **kwargs)
        if key in cls._instances:
            await cls._instances[key].close()
            del cls._instances[key]

class OpenaiModel(BaseLLM):
    r"""
    Openai official client, support latest model change. https://platform.openai.com/docs/guides/latest-model
    """

    provider = "openai"
    timeout = {
        "timeout": httpx.Timeout(120, connect=60.0),
        "max_retries": 0
    }

    def __init__(self, model, **kwargs) -> None:
        self.model = model
        super().__init__(**kwargs)
    
    async def __call__(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        max_output_tokens: int = 1024 * 10,
        reasoning: dict = None,
        json_mode: bool = False,
        **kwargs) -> str:
        """
        https://platform.openai.com/docs/api-reference/responses/create

        Asynchronously call the OpenAI API to generate a response.

        Args:
            sys_prompt (str): The system prompt, defaults to an empty string.
            user_prompt (str): The user prompt, defaults to an empty string.
            history_messages (List[dict]): History messages, defaults to None.
            max_output_tokens (int): Maximum tokens to generate, defaults to 8192.
            reasoning (dict): Reasoning configuration, defaults to None.
            json_mode (bool): Enable json structure output.
            **kwargs: Additional parameters to pass to the API.

        Returns:
            str: The content of the generated response from the API.
        """
        call_start_time = datetime.datetime.now()
        kwargs.pop('images', None)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        user_message = [{"role": "user", "content": user_prompt}] if user_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        instructions = sys_prompt if sys_prompt else None
        messages = history_messages + user_message
        if reasoning is None:
            reasoning = {
                'effort': 'medium',
                'summary': 'auto',
            }
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=messages,
                max_output_tokens=max_output_tokens,
                reasoning=reasoning,
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, history_messages, e,
            e, "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, history_messages, response,
            response.output, f"Model: {self.model}, Usage: {response.usage}", call_start_time)

        return response
    
    async def stream_call(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        max_output_tokens: int = 1024 * 20,
        reasoning: dict = None,
        **kwargs):
        call_start_time = datetime.datetime.now()
        kwargs.pop('stream', None)
        kwargs.pop('images', None)
        user_message = [{"role": "user", "content": user_prompt}] if user_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        instructions = sys_prompt if sys_prompt else None
        messages = history_messages + user_message 
        if reasoning is None:
            reasoning = {
                'effort': 'medium',
                'summary': 'auto',
            }
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=messages,
                max_output_tokens=max_output_tokens,
                reasoning=reasoning,
                stream=True,
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, history_messages, e,
            e, "error", call_start_time)
            raise e

        string_buffer = io.StringIO()
        usage = defaultdict(int)
        last_chunk = None
        async for chunk in response:

            if chunk.type == 'response.reasoning_summary_text.delta':
                # by pass summary text since summary don't support multi language
                pass
            elif chunk.type == 'response.output_text.delta':
                chunk_content = chunk.delta
                if chunk_content is not None:
                    string_buffer.write(chunk_content)
                    yield chunk_content
            elif chunk.type == 'response.completed':
                usage = chunk.response.usage.total_tokens
                last_chunk = chunk.response
            if self.stream_break:
                break
       
        await response.close()
        self.stream_break = False
        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, history_messages, last_chunk,
                         content, f"Model: {self.model}, Usage: {usage}", call_start_time)

    async def stream_call_origin(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        max_output_tokens: int = 1024 * 20,
        reasoning: dict = None,
        **kwargs):
        call_start_time = datetime.datetime.now()
        if reasoning is None:
            reasoning = {
                'effort': 'medium',
                'summary': 'auto',
            }
        tools = kwargs.pop('tools', None)
        
        user_message = [{"role": "user", "content": user_prompt}] if user_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        messages = history_messages + user_message
        
        instructions = sys_prompt if sys_prompt else None
        
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=messages,
                max_output_tokens=max_output_tokens,
                reasoning=reasoning,
                tools=tools,
                stream=True,
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, history_messages, None,
                                   str(e), f"Model: {self.model}", start_time=call_start_time)
            raise e

        usage = None
        last_chunk = None
        async for chunk in response:
            if chunk.type == 'response.completed':
                usage = chunk.response.usage
                last_chunk = chunk.response
            yield chunk
       
        self.stream_break = False
        await self.log_results(sys_prompt, user_prompt, history_messages, last_chunk,
                         last_chunk.output, f"Model: {self.model}, Usage: {usage}", call_start_time)
        
    async def log_results(self, sys_prompt: str, user_prompt: str, history_messages: list, response, content: str, usage: str, start_time = None) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {history_messages}\n")
            log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {content}\n{usage}\n")
            try:
                log_file.write(f"[{log_id}] Model: {response.model}\n")
            except:
                pass
            if start_time:
                time_delta = end_time - start_time
                formatted_time_delta = f"{time_delta.total_seconds():.2f} seconds"
                log_file.write(f"[{log_id}] Time spent: {formatted_time_delta}\n")
            log_file.write("="*64+"\n")
        with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
            time_delta = f"[{time_delta.total_seconds():.2f}s]" if start_time else ''
            log_file.write(f"[{log_id}] [{current_time}][{task_id}] {time_delta} {usage}\n")


class Openai5(OpenaiModel, AsyncOpenaiClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenaiClientSingletonMixin.get_client(
            api_key=api_config.OPENAI_API_KEY,
            **self.timeout
        )
        self.client = client
        super().__init__(model=api_config.OPENAI_GPT5)

class Openai52(OpenaiModel, AsyncOpenaiClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenaiClientSingletonMixin.get_client(
            api_key=api_config.OPENAI_API_KEY,
            **self.timeout
        )
        self.client = client
        super().__init__(model=api_config.OPENAI_GPT5_2)

class Openai54(OpenaiModel, AsyncOpenaiClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenaiClientSingletonMixin.get_client(
            api_key=api_config.OPENAI_API_KEY,
            **self.timeout
        )
        self.client = client
        super().__init__(model=api_config.OPENAI_GPT5_4)


class Openai5Mini(OpenaiModel, AsyncOpenaiClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenaiClientSingletonMixin.get_client(
            api_key=api_config.OPENAI_API_KEY,
            **self.timeout
        )
        self.client = client
        super().__init__(model=api_config.OPENAI_GPT5_MINI)

class Openaio4Mini(OpenAIReasoningModel):
    
    def __init__(self, reasoning_effort: str="high") -> None:
        self.client = AsyncOpenAI(api_key=api_config.OPENAI_API_KEY,
                                  **low_timeout_0_retry)
        self.reasoning_effort  = reasoning_effort
        super().__init__(model=api_config.OPENAI_GPTo4_MINI_MODEL)


class Openaio3(OpenAIReasoningModel, AsyncOpenaiClientSingletonMixin):

    def __init__(self, reasoning_effort: str="medium") -> None:
        client = AsyncOpenaiClientSingletonMixin.get_client(
            api_key=api_config.OPENAI_API_KEY,
            **low_timeout_0_retry
        )
        self.reasoning_effort  = reasoning_effort
        self.client = client
        self.reasoning_effort  = reasoning_effort
        super().__init__(model=api_config.OPENAI_GPTo3_MODEL)
