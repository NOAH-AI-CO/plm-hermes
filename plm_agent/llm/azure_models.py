import io
import os
import httpx
import logging
import datetime

from typing import List, Optional
from collections import defaultdict

from openai import AsyncAzureOpenAI, AzureOpenAI

from config import api_config
from logging_config import log_id_var, task_id_var
from llm.base_model import BaseLLM, CompositeModel

logger = logging.getLogger(__name__)
low_timeout_0_retry = {"timeout": httpx.Timeout(45, connect=10.0), "max_retries": 0}

class OpenAIModel(BaseLLM):
    """
    A base class for model req.
    """
    
    provider = "azure_openai"

    def __init__(self, model, **kwargs) -> None:
        self.model = model
        super().__init__(**kwargs)

    # @retry(wait=wait_random_exponential(multiplier=1, max=3), stop=stop_after_attempt(3))
    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 0.1, max_tokens: int = 8192, **kwargs) -> str:
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
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}} for base64_image in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        sys_message = [{"role": "system", "content": sys_prompt}] if sys_prompt else []
        messages = sys_message + history_messages + user_message
        if hasattr(self, 'timeout') and self.timeout:
            kwargs['timeout'] = self.timeout
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,                
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, e,
            e, "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
            response.choices[0].message, f"Model: {self.model}, Temperature: {temperature}, Usage: {response.usage}", call_start_time)

        return response.choices[0].message

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.1, max_tokens: int = 8192, **kwargs):
        call_start_time = datetime.datetime.now()
        kwargs.pop('stream', None)
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        sys_message = [{"role": "system", "content": sys_prompt}] if sys_prompt else []
        messages = sys_message + history_messages + user_message
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                max_tokens=max_tokens,
                stream_options={"include_usage": True},
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, e,
                                   "error", call_start_time)
            raise e
        string_buffer = io.StringIO()
        usage = defaultdict(int)
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage
            if len(chunk.choices) > 0:
                 chunk_content = chunk.choices[0].delta.content
                 if chunk_content is not None:
                     string_buffer.write(chunk_content)
                     yield chunk_content
            if self.stream_break:
                break
        await response.close()
        self.stream_break = False
        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time)

    async def log_results(self, sys_prompt: str, user_prompt: str, response, content: str, usage: str, start_time = None) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {content}\n")
            log_file.write(f"[{log_id}] [{current_time}] {usage}\n")
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


class OpenAIReasoningModel(OpenAIModel):
    """
    Openai reasoning model
    """

    provider = "openai"

    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 0.1, **kwargs) -> str:
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
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.pop('backup_llms', None)
        kwargs.pop('max_tokens', None)
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}} for base64_image in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        sys_message = [{"role": "developer", "content": sys_prompt}] if sys_prompt else []
        messages = sys_message + history_messages + user_message
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                reasoning_effort=self.reasoning_effort,
                messages=messages,
                #temperature=temperature,
                max_completion_tokens=8192,
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, None,
            e, "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
            response.choices[0].message, f"Model: {self.model}, Temperature: {temperature}, Usage: {response.usage}", call_start_time)
        
        #print(response.model_dump_json(indent=2))
        return response.choices[0].message

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature=0.1, **kwargs):
        call_start_time = datetime.datetime.now()
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        sys_message = [{"role": "developer", "content": sys_prompt}] if sys_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        messages = sys_message + history_messages + user_message
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_completion_tokens=1024*16,
                stream_options={"include_usage": True},
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, None,
                                   str(e), f"Model: {self.model}", start_time=call_start_time)
            raise e
        string_buffer = io.StringIO()
        usage = defaultdict(int)
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage
            if len(chunk.choices) > 0:
                chunk_content = chunk.choices[0].delta.content
                if chunk_content is not None:
                    string_buffer.write(chunk_content)
                    yield chunk_content
            if self.stream_break:
                break
        await response.close()
        self.stream_break = False
        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time)

    async def stream_call_origin(self, sys_prompt: str = "", user_prompt: str = "", temperature=0.1, **kwargs):
        call_start_time = datetime.datetime.now()
        kwargs.pop('stream', None)
        tools = kwargs.pop('tools', None)
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        sys_message = [{"role": "developer", "content": sys_prompt}] if sys_prompt else []
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        messages = sys_message + history_messages + user_message
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_completion_tokens=1024*16,
                stream_options={"include_usage": True},
                tools=tools,
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, None,
                                   str(e), f"Model: {self.model}", start_time=call_start_time)
            raise e

        async for chunk in response:
            yield chunk
        

class OpenAIReasoningModelV2(OpenAIModel):
    """
    Openai reasoning model
    """

    provider = "azure_openai"

    async def __call__(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        max_output_tokens: int = 1024 * 16,
        reasoning: dict = None,
        json_mode: bool = False,
        **kwargs) -> str:
        """
        https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?tabs=python-secure

        Asynchronously call the AsyncAzure API to generate a response.

        Args:
            sys_prompt (str): The system prompt, defaults to an empty string.
            user_prompt (str): The user prompt, defaults to an empty string.
            history_messages (List[dict]): History messages, defaults to None.
            temperature (float): The randomness of the generation, defaults to 0.1.
            max_tokens (int): Maximum tokens to generate, defaults to 8192.
            reasoning (dict): Reasoning configuration, defaults to None.
            **kwargs: Additional parameters to pass to the API.

        Returns:
            str: The content of the generated response from the API.
        """
        call_start_time = datetime.datetime.now()
        kwargs.pop('images', None)
        kwargs.pop('temperature', None)
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
            await self.log_results(sys_prompt, user_prompt, e,
            e, "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, history_messages, response,
            response.output, f"Model: {self.model}, Usage: {response.usage}", call_start_time)

        return response

    async def stream_call(
        self,
        sys_prompt: str = "",
        user_prompt: str = "",
        max_output_tokens: int = 1024 * 16,
        reasoning: dict = None,
        **kwargs):
        call_start_time = datetime.datetime.now()
        kwargs.pop('stream', None)
        kwargs.pop('images', None)
        kwargs.pop('temperature', None)
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
        default_chunk = None
        async for chunk in response:
            default_chunk = chunk
            if chunk.type == 'response.reasoning_summary_text.delta':
                # by pass summary text since summary don't support multi language
                pass
            elif chunk.type == 'response.output_text.delta':
                chunk_content = chunk.delta
                if chunk_content is not None:
                    string_buffer.write(chunk_content)
                    yield chunk_content
            elif chunk.type == 'response.completed':
                usage = chunk.response.usage
                last_chunk = chunk.response
            if self.stream_break:
                break
       
        self.stream_break = False
        content = string_buffer.getvalue()
        string_buffer.close()
        logger.info(f"default_chunk: {default_chunk}")
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
        default_chunk = None
        async for chunk in response:
            if chunk.type == 'response.completed':
                usage = chunk.response.usage
                last_chunk = chunk.response
            default_chunk = chunk
            yield chunk
       
        self.stream_break = False
        output = last_chunk.output if last_chunk else ''
        logger.info(f"default_chunk: {default_chunk}")
        await self.log_results(sys_prompt, user_prompt, history_messages, last_chunk,
            output, f"Model: {self.model}, Usage: {usage}", call_start_time)

    async def compact(self, input: list, instructions: str = None) -> list:
        """调用 responses.compact() 压缩对话历史。
        需用 AsyncOpenAI + /openai/v1/ 路径，因为 AsyncAzureOpenAI 的 compact 端点不可用。
        """
        call_start_time = datetime.datetime.now()
        compact_client = self._get_compact_client()
        try:
            compact_response = await compact_client.responses.compact(
                model=self.model,
                input=input,
                instructions=instructions,
            )
        except Exception as e:
            await self.log_results(instructions, '', input, e, str(e),
                f"Model: {self.model}, compact() Error: {e}", call_start_time)
            raise e
        await self.log_results(instructions, '', input, compact_response,
            compact_response.output,
            f"Model: {self.model}, compact() Usage: {compact_response.usage}",
            call_start_time)
        return compact_response.output

    def _get_compact_client(self):
        """获取 compact 专用的 AsyncOpenAI 客户端（缓存在实例上）"""
        if not hasattr(self, '_compact_client') or self._compact_client is None:
            from openai import AsyncOpenAI
            azure_ep = str(self.client._azure_endpoint).rstrip('/')
            base_url = azure_ep + '/openai/v1/'
            self._compact_client = AsyncOpenAI(api_key=self.client.api_key, base_url=base_url)
        return self._compact_client

    async def log_results(self, sys_prompt: str, user_prompt: str, history_messages: list, response, content: str, usage: str, start_time = None) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            #log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {history_messages}\n")
            log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {content}\n")
            log_file.write(f"[{log_id}] [{current_time}] {usage}\n")
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


class AsyncOpenAIClientSingletonMixin:
    """
    @summary: async openai 单例
    """
    _instances: dict[str, AsyncAzureOpenAI] = dict()

    @classmethod
    def make_key(cls, api_key, api_version, azure_endpoint, **kwargs):
        return api_key, api_version, azure_endpoint

    @classmethod
    def get_client(cls, api_key, api_version, azure_endpoint, **kwargs) -> AsyncAzureOpenAI:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = cls.initialize(api_key, api_version, azure_endpoint, **kwargs)
        return cls._instances[key]
    
    @classmethod
    def initialize(cls, api_key, api_version, azure_endpoint, **kwargs) -> None:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = AsyncAzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=azure_endpoint,
                **kwargs
            )
        return cls._instances[key]

    @classmethod
    async def cleanup(cls, api_key, api_version, azure_endpoint, **kwargs) -> None:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key in cls._instances:
            await cls._instances[key].close()
            del cls._instances[key]

class OpenAIClientSingletonMixin:
    """
    @summary: openai 单例
    """
    _instances: dict[str, AzureOpenAI] = dict()

    @classmethod
    def make_key(cls, api_key, api_version, azure_endpoint, **kwargs):
        return (api_key, api_version, azure_endpoint) + tuple(sorted(kwargs.items()))

    @classmethod
    def get_client(cls, api_key, api_version, azure_endpoint, **kwargs) -> AzureOpenAI:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = cls.initialize(api_key, api_version, azure_endpoint, **kwargs)
        return cls._instances[key]
    
    @classmethod
    def initialize(cls, api_key, api_version, azure_endpoint, **kwargs) -> None:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key not in cls._instances:
            cls._instances[key] = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=azure_endpoint,
                **kwargs
            )
        return cls._instances[key]

    @classmethod
    def cleanup(cls, api_key, api_version, azure_endpoint, **kwargs) -> None:
        key = cls.make_key(api_key, api_version, azure_endpoint, **kwargs)
        if key in cls._instances:
            cls._instances[key].close()
            del cls._instances[key]

class GPT4o(OpenAIModel, AsyncOpenAIClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            max_retries=5
        )

        self.client = client
        super().__init__(model=api_config.AZURE_GPT4_AZURE_DEPLOYMENT)
    
    async def call_response(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 0.1, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if 'json' not in user_prompt:
            user_prompt += '\nPlease output in json'
        if "images" in kwargs:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}} for base64_image in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
            
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        sys_message = [{"role": "system", "content": sys_prompt}] if sys_prompt else []
        messages = sys_message + history_messages + user_message
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
                
                **kwargs
            )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, e,
                                   "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
            response.choices[0].message, response.usage, call_start_time)

        return response

class GPT41(OpenAIModel, AsyncOpenAIClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT4_1_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT, 
            **low_timeout_0_retry
        )
        self.client = client
        super().__init__(model=api_config.AZURE_GPT4_1_DEPLOYMENT)

class GPT4oWorkflow(OpenAIModel, AsyncOpenAIClientSingletonMixin):

    def __init__(self) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT4_OPENAI_API_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            **low_timeout_0_retry
        )
        self.client = client
        super().__init__(model=api_config.AZURE_GPT4_AZURE_DEPLOYMENT)

class GPTo3(OpenAIReasoningModel, AsyncOpenAIClientSingletonMixin):

    def __init__(self, reasoning_effort: str="medium") -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPTo3_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            **low_timeout_0_retry
        )
        self.client = client
        self.reasoning_effort  = reasoning_effort
        super().__init__(model=api_config.AZURE_GPTo3_DEPLOYMENT)

class GPTo4Mini(OpenAIReasoningModel, AsyncOpenAIClientSingletonMixin):

    def __init__(self, reasoning_effort: str="high", timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPTo4_MIN_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            **low_timeout_0_retry
        )
        self.client = client
        self.reasoning_effort  = reasoning_effort
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPTo4_MIN_DEPLOYMENT)

class GPT5Nano(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_NANO_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_NANO_DEPLOYEMNT)

class GPT5Mini(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_MIN_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_MIN_DEPLOYMENT)

class GPT54Mini(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_4_MIN_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_4_MIN_DEPLOYMENT)

class GPT5(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_DEPLOYMENT)

class GPT51(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_1_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_2_DEPLOYMENT)

class GPT52(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_2_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=600,
        )
        self.client = client
        self.timeout = 600
        super().__init__(model=api_config.AZURE_GPT5_2_DEPLOYMENT)

class GPT54(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_4_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=600,
        )
        self.client = client
        self.timeout = 600
        super().__init__(model=api_config.AZURE_GPT5_4_DEPLOYMENT)

class GPT55(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_5_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=600,
        )
        self.client = client
        self.timeout = 600
        super().__init__(model=api_config.AZURE_GPT5_5_DEPLOYMENT)

class GPT51Codex(OpenAIReasoningModelV2, AsyncOpenAIClientSingletonMixin):

    def __init__(self, timeout: Optional[float]=None) -> None:
        client = AsyncOpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_GPT5_1_CODEX_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            timeout=120,
        )
        self.client = client
        self.timeout = timeout
        super().__init__(model=api_config.AZURE_GPT5_1_CODEX_DEPLOYMENT)

class Ada(OpenAIModel, OpenAIClientSingletonMixin):

    def __init__(self) -> None:
        client = OpenAIClientSingletonMixin.get_client(
            api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
            api_version=api_config.AZURE_ADA002_OPENAI_API_VERSION,
            azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
            azure_deployment=api_config.AZURE_ADA002_AZURE_DEPLOYMENT
        )
        self.client = client
        self.provider = "azure_openai"
        super().__init__(model=api_config.AZURE_ADA002_MODEL)

    def get_embedding(self, text: str) -> list[float]:
        """
        Get the embedding vector for the given text.

        Args:
            text (str): The text to be embedded.

        Returns:
            list[float]: The embedding vector of the text.
        """
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding

class Compositeo4mini(CompositeModel):
    provider = "azure_openai"
    
    models = [GPTo4Mini(reasoning_effort='medium', timeout=60), GPT41(), GPTo4Mini(reasoning_effort='low', timeout=55), GPT41()]
    
class DiagnosisModels(CompositeModel):
    def __init__(self, **kwargs) -> None:
        self.models = [GPTo3(), GPTo4Mini(), GPT41()]
        super().__init__()
