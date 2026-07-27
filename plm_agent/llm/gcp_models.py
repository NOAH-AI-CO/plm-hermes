import io
import os
import asyncio
import base64
import datetime
import logging

import httpx
import openai

from collections import defaultdict
from anthropic import AsyncAnthropicVertex
from google import auth
from google.auth.transport.requests import Request
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
import traceback

from config import api_config
from logging_config import log_id_var, task_id_var
from llm.base_model import BaseLLM
from llm.azure_models import OpenAIModel, GPT41
from utils.metadata import SingletonMeta
from utils.utils import deprecated_class

try:
    from google import genai
    from google.genai.types import HttpOptions, GenerateContentConfig, Content, Part, ThinkingConfig
except ImportError:
    genai = None

logger = logging.getLogger(__name__)

creds, project = auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
auth_req = Request()
PROJECT = api_config.VERTEX_PROJECT_ID
LOCATION = 'us-central1'

class GeminiClientSingleton:
    _instance: Optional[openai.AsyncOpenAI] = None
    _initialized: bool = False

    @classmethod
    def get_client(cls) -> openai.AsyncOpenAI:
        if cls._instance is None:
            cls.initialize()
        return cls._instance
    
    @classmethod
    def initialize(cls) -> None:
        if not cls._initialized:
            creds.refresh(auth_req)
            cls._instance = openai.AsyncOpenAI(
                base_url=f'https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/endpoints/openapi',
                api_key=creds.token
            )
            cls._initialized = True

    @classmethod
    async def cleanup(cls) -> None:
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
        cls._initialized = False

    @classmethod
    def refresh_credentials(cls) -> None:
        """Refresh credentials and recreate client"""
        if cls._instance:
            # Note: We can't await close() here in a sync method, 
            # but we'll recreate the instance which should handle cleanup
            creds.refresh(auth_req)
            cls._instance = openai.AsyncOpenAI(
                base_url=f'https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}/endpoints/openapi',
                api_key=creds.token
            )

class GoogleGenAIClientSingleton:
    _instance: Optional[genai.Client] = None
    _initialized: bool = False

    @classmethod
    def get_client(cls) -> genai.Client:
        if cls._instance is None:
            cls.initialize()
        return cls._instance
    
    @classmethod
    def initialize(cls) -> None:
        if not cls._initialized:
            if genai is None:
                logger.error("google.genai module is not available")
                return
            
            project = getattr(api_config, 'VERTEX_PROJECT_ID', None) or "noahai-440408"
            if not os.environ.get('GOOGLE_CLOUD_PROJECT'):
                 os.environ['GOOGLE_CLOUD_PROJECT'] = project
            if not os.environ.get('GOOGLE_CLOUD_LOCATION'):
                 os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
            if not os.environ.get('GOOGLE_GENAI_USE_VERTEXAI'):
                 os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

            cls._instance = genai.Client(http_options=HttpOptions(api_version="v1"))
            cls._initialized = True

    @classmethod
    async def cleanup(cls) -> None:
        # genai.Client doesn't have an explicit close for the whole client in some versions,
        # but handling it here for future-proofing or if it does.
        # Most importantly, setting _instance to None allows GC if needed, 
        # but usually we want to keep it alive.
        cls._instance = None
        cls._initialized = False
# Backward compatibility - remove this later
GEMINI_CLIENT = None  # Will be deprecated

class VertexClaudeModel(BaseLLM):

    max_tokens = 32000

    """
    A base class for model req.
    """
    def __init__(self, region:str, project_id:str, model:str) -> None:
        self.client = AsyncAnthropicVertex(region=region,  project_id=project_id, timeout=300, max_retries=0)
        self.model = model

    @staticmethod
    def _sanitize_messages(messages: list) -> list:
        """Convert OpenAI Responses API content types to Anthropic-compatible types.

        - 'input_text' / 'output_text' -> 'text'
        - 'input_image' (with 'image_url' string, either a data URI or http(s) URL)
          -> 'image' with a 'source' object (base64 or url form)
        """
        for msg in messages:
            content = msg.get('content') if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            new_content = []
            for block in content:
                if not isinstance(block, dict):
                    new_content.append(block)
                    continue
                btype = block.get('type')
                if btype in ('input_text', 'output_text'):
                    block['type'] = 'text'
                    new_content.append(block)
                elif btype == 'input_image':
                    image_url = block.get('image_url')
                    if isinstance(image_url, dict):
                        image_url = image_url.get('url', '')
                    if not image_url:
                        continue
                    if image_url.startswith('data:'):
                        try:
                            header, data = image_url.split(',', 1)
                            media_type = header.split(';')[0].split(':', 1)[1] or 'image/jpeg'
                        except Exception:
                            media_type, data = 'image/jpeg', ''
                        if not data:
                            continue
                        media_type = media_type.strip().lower()
                        _alias = {
                            'image/jpg': 'image/jpeg',
                            'image/pjpeg': 'image/jpeg',
                            'image/x-png': 'image/png',
                        }
                        media_type = _alias.get(media_type, media_type)
                        if media_type not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'):
                            media_type = 'image/jpeg'
                        new_content.append({
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': media_type,
                                'data': data,
                            },
                        })
                    else:
                        new_content.append({
                            'type': 'image',
                            'source': {
                                'type': 'url',
                                'url': image_url,
                            },
                        })
                else:
                    new_content.append(block)
            msg['content'] = new_content
        return messages

    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 0.5, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
        if len(kwargs.pop("images", [])) > 0:
            user_message = [{"role": "user", 
                             "content": [
                                 {"type": "text", "text": user_prompt}, 
                                 ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
        else:
            user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages', []) if isinstance(kwargs.get('history_messages'), list) else []
        messages = self._sanitize_messages(history_messages + user_message)
        if sys_prompt:
            kwargs["system"] = sys_prompt
        response = await self.client.messages.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=self.max_tokens,
            **kwargs
        )
        await self.log_results(sys_prompt, user_prompt, response.content[0], "vertex-placeholder", call_start_time)
        return response.content

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.5, **kwargs):
        try:
            call_start_time = datetime.datetime.now()
            if len(kwargs.pop("images", [])) > 0:
                user_message = [{"role": "user",
                                "content": [
                                    {"type": "text", "text": user_prompt},
                                    ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
            else:
                user_message = [{"role": "user", "content": user_prompt}]
            history_messages = kwargs.pop('history_messages', []) if isinstance(kwargs.get('history_messages'), list) else []
            messages = self._sanitize_messages(history_messages + user_message)
            for key in ['system_prompt', 'stream', 'stream_status']:
                kwargs.pop(key, None)
            if sys_prompt:
                kwargs["system"] = sys_prompt
            
            """
            response = await asyncio.wait_for(self.client.messages.create(
                model=self.model,
                messages=messages,
                system=sys_prompt,
                temperature=temperature,
                stream=True,
                max_tokens=4000,
                **kwargs
            ), timeout=5)
            """
            logger.info(f"Claude call using temperature: {temperature}")
            response = await self.client.messages.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                max_tokens=self.max_tokens,
                **kwargs
            )
            string_buffer = io.StringIO()
            usage = defaultdict(int)
        
            async for chunk in response:
                if hasattr(chunk, 'message') and hasattr(chunk.message, 'usage') and chunk.message.usage:
                    for key, value in chunk.message.usage.__dict__.items():
                        if type(value) == int:
                            usage[key] += value
                if hasattr(chunk, 'usage') and chunk.usage:
                    for key, value in chunk.usage.__dict__.items():
                        if type(value) == int:
                            usage[key] += value
                if chunk.type == 'content_block_delta':
                    chunk_content = chunk.delta.text
                    string_buffer.write(chunk_content)
                    yield chunk_content
                if self.stream_break:
                    break
            await response.close()
            self.stream_break = False
            content = string_buffer.getvalue()
            string_buffer.close()
            await self.log_results(sys_prompt, user_prompt, content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}\n", call_start_time)
            if not usage.get('output_tokens', 0):
                raise Exception("No output tokens in usage, likely an error in the request or response.")
        except Exception as e:
            logger.error(f"Error in stream_call: {e}")
            raise e
        
    async def log_results(self, sys_prompt:str, user_prompt:str, content: str, usage: str, start_time=None) -> None:
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
        print("generate_stream", self.__class__.__name__)
        async for chunk in self.stream_call(user_prompt=user_prompt, **kwargs):
            yield chunk

class VertexClaudeThikingModel(VertexClaudeModel):
    
    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.5, **kwargs):
        try:
            call_start_time = datetime.datetime.now()
            if sys_prompt:
                kwargs["system"] = sys_prompt
            if len(kwargs.pop("images", [])) > 0:
                user_message = [{"role": "user", 
                                "content": [
                                    {"type": "text", "text": user_prompt}, 
                                    ] + [{"type": "image_url", "image_url": {"url": image64}} for image64 in kwargs.pop("images")]}]
            else:
                user_message = [{"role": "user", "content": user_prompt}]
            history_messages = kwargs.pop('history_messages', []) if isinstance(kwargs.get('history_messages'), list) else []
            messages = self._sanitize_messages(history_messages + user_message)

            response = await self.client.messages.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=True,
                max_tokens=self.max_tokens,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 5 * 1024
                    },
                **kwargs
            )
            reasoning_flag = False
            string_buffer = io.StringIO()
            usage = defaultdict(int)
            async for chunk in response:
                if hasattr(chunk, 'message') and hasattr(chunk.message, 'usage') and chunk.message.usage:
                    for key, value in chunk.message.usage.__dict__.items():
                        if type(value) == int:
                            usage[key] += value
                if hasattr(chunk, 'usage') and chunk.usage:
                    for key, value in chunk.usage.__dict__.items():
                        if type(value) == int:
                            usage[key] += value
                if chunk.type == 'content_block_delta':

                    if chunk.delta.type == 'thinking_delta':
                    
                        if not reasoning_flag:
                            reasoning_flag = True
                            chunk_content = f"<think>\n{chunk.delta.thinking}"
                        else:
                            chunk_content = chunk.delta.thinking
                    
                    elif chunk.delta.type == 'text_delta':

                        if reasoning_flag:
                            reasoning_flag = False
                            chunk_content = f"</think>\n{chunk.delta.text}"
                        else:
                            chunk_content = chunk.delta.text
                    
                    if chunk_content:
                        string_buffer.write(chunk_content)
                        yield chunk_content
                if self.stream_break:
                    break
            await response.close()
            self.stream_break = False
            content = string_buffer.getvalue()
            string_buffer.close()
            await self.log_results(sys_prompt, user_prompt, content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}\n", call_start_time)
            if not usage.get('output_tokens', 0):
                raise Exception("No output tokens in usage, likely an error in the request or response.")
        except Exception as e:
            logger.error(f"Error in stream_call: {e}")
            raise e

@deprecated_class("Use ClaudeSonnet45 instead")             
class ClaudeSonnet35(VertexClaudeModel, metaclass=SingletonMeta):
    
    provider = "anthropic"
    max_tokens = 8192

    def __init__(self, max_tokens: int = 8192) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDE35_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDE35_MODEL_ID,
        )
        self.max_tokens = max_tokens

@deprecated_class("Use ClaudeSonnet45 instead")  
class ClaudeSonnet37(VertexClaudeModel, metaclass=SingletonMeta):
    
    provider = "anthropic"

    def __init__(self, max_tokens: int = 64000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDE37_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDE37_MODEL_ID,
        )
        self.max_tokens = max_tokens

@deprecated_class("Use ClaudeSonnet45 instead")  
class ClaudeSonnet4(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDE37_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDE4_MODEL_ID,
        )
        self.max_tokens = max_tokens

@deprecated_class("Use ClaudeOpus41 instead")     
class ClaudeOpus4(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDEOPUS4_MODEL_ID,
        )
        self.max_tokens = max_tokens

class ClaudeSonnet45(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDE45_MODEL_ID,
        )
        self.max_tokens = max_tokens

class ClaudeSonnet46(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            "claude-sonnet-4-6",
        )
        self.max_tokens = max_tokens

class ClaudeHaiku45(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDEHAIKU45_MODEL_ID,
        )
        self.max_tokens = max_tokens

class ClaudeOpus41(VertexClaudeModel, metaclass=SingletonMeta):
    provider = "anthropic"

    def __init__(self, max_tokens:int = 32000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDEOPUS41_MODEL_ID,
        )
        self.max_tokens = max_tokens

class ClaudeSonnet37Thinking(VertexClaudeThikingModel, metaclass=SingletonMeta):

    provider = "anthropic"

    def __init__(self, max_tokens: int = 64000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDE37_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            api_config.VERTEX_CLAUDE37_MODEL_ID,
        )
        self.max_tokens = max_tokens

class ClaudeSonnet46Thinking(VertexClaudeThikingModel, metaclass=SingletonMeta):

    provider = "anthropic"

    def __init__(self, max_tokens: int = 64000) -> None:
        super().__init__(
            api_config.VERTEX_CLAUDEOPUS4_REGION,
            api_config.VERTEX_CLAUDE_PROJECT_ID,
            "claude-sonnet-4-6",
        )
        self.max_tokens = max_tokens

class ClaudeSonnet37ThinkingBypass(ClaudeSonnet37Thinking):
    
    provider = "anthropic"

    async def stream_call(self, sys_prompt = "", user_prompt = "", temperature = 0.5, **kwargs):
        data = {"prompt": user_prompt, "thinking": True}
        # gen = llm.stream_call(user_prompt=prompt, temperature=0.5)
        url = 'https://test.noahai.co/api/claude/'
        token = api_config.NOAH_ADMIN_TOKEN
        headers = {'Content-Type': 'application/json', 'Authorization': token}
        # response = requests.post(url, headers=headers, json=data, stream=True)
        async with httpx.AsyncClient() as client:
            async with client.stream('POST', url, headers=headers, json=data, timeout=30) as r:
                async for chunk in r.aiter_text():  # or, for line in r.iter_lines():
                    yield chunk
        

class ClaudeSonnet37Bypass(ClaudeSonnet37):
    
    provider = "anthropic"

    async def stream_call(self, sys_prompt = "", user_prompt = "", temperature = 0.5, **kwargs):
        data = {"prompt": user_prompt}
        # gen = llm.stream_call(user_prompt=prompt, temperature=0.5)
        url = 'https://test.noahai.co/api/claude/'
        token = api_config.NOAH_ADMIN_TOKEN
        headers = {'Content-Type': 'application/json', 'Authorization': token}
        # response = requests.post(url, headers=headers, json=data, stream=True)
        async with httpx.AsyncClient() as client:
            async with client.stream('POST', url, headers=headers, json=data, timeout=30) as r:
                async for chunk in r.aiter_text():  # or, for line in r.iter_lines():
                    yield chunk
        
class VertexGeminiModel(OpenAIModel):
    def __init__(self, *args, **kwargs) -> None:
        self.client = GeminiClientSingleton.get_client()
        super().__init__(*args, **kwargs)
        
    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.1, max_tokens: int = 32000, **kwargs):
        call_start_time = datetime.datetime.now()
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
                **kwargs
            )
        except openai.AuthenticationError as e:
            if e.response.status_code == 401:  # Unauthorized
            # Refresh credentials and retry
                logger.info("Gemini authentication error, refreshing credentials and retrying...")
                GeminiClientSingleton.refresh_credentials()
                self.client = GeminiClientSingleton.get_client()
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                    max_tokens=max_tokens,
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
                for key, value in usage.__dict__.items():
                    if type(value) == 'int':
                        usage[key] += value
            if len(chunk.choices) > 0:
                 choice = chunk.choices[0]
                 if choice.delta is not None and choice.delta.content is not None:
                     chunk_content = choice.delta.content
                     string_buffer.write(chunk_content)
                     yield chunk_content
        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time)

    async def generate_stream(self, user_prompt, **kwargs):
        async for chunk in super().stream_call(user_prompt=user_prompt):
            yield chunk
            
    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.1, max_tokens: int = 32000, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
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
                max_tokens=max_tokens,
                **kwargs
            )
        except openai.AuthenticationError as e:
            if e.response.status_code == 401:  # Unauthorized
            # Refresh credentials and retry
                logger.info("Gemini authentication error, refreshing credentials and retrying...")
                GeminiClientSingleton.refresh_credentials()
                self.client = GeminiClientSingleton.get_client()
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )
        except Exception as e:
            await self.log_results(sys_prompt, user_prompt, e,
                                   "error", call_start_time)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
                         response.choices[0].message.content, f"Model: {self.model}, Temperature: {temperature}, Usage: {response.usage}", call_start_time)
        return response.choices[0].message.content
        
class Gemini15Flash(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI15_FLASH_MODEL_ID}")

class Gemini15Pro(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI15_PRO_MODEL_ID}")

class Gemini20Flash(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI20_FLASH_MODEL_ID}")

class Gemini20Pro(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI20_FLASH_MODEL_ID}")

class Gemini25Pro(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI25_PRO_MODEL_ID}")

class Gemini25Flash(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI25_FLASH_MODEL_ID}")

class Gemini25FlashLite(VertexGeminiModel):
    def __init__(self) -> None:
        super().__init__(model=f"google/{api_config.VERTEX_GEMINI25_FLASH_LITE_MODRL_ID}")

class Gemini31Pro(BaseLLM):
    
    provider = "google"

    def __init__(self, model: str = "gemini-3.1-pro-preview") -> None:
        self.model = "gemini-3.1-pro-preview"
        self.project = getattr(api_config, 'VERTEX_PROJECT_ID', None) or "noahai-440408"
        self.client = GoogleGenAIClientSingleton.get_client()

    def _convert_messages(self, user_prompt, history_messages, images):
        contents = []
        
        # History
        if history_messages:
            for msg in history_messages:
                role = msg.get('role')
                content = msg.get('content')
                
                parts = []
                if isinstance(content, str):
                    parts.append(Part.from_text(text=content))
                elif isinstance(content, list):
                    for item in content:
                        if item.get('type') == 'text':
                            parts.append(Part.from_text(text=item.get('text')))
                        elif item.get('type') == 'image_url':
                             img_url = item.get('image_url', {}).get('url', '')
                             if img_url.startswith("data:"):
                                 header, data = img_url.split(",", 1)
                                 mime_type = header.split(";")[0].split(":")[1]
                                 image_bytes = base64.b64decode(data)
                                 parts.append(Part.from_bytes(data=image_bytes, mime_type=mime_type))
                
                g_role = "user" if role == "user" else "model"
                contents.append(Content(role=g_role, parts=parts))

        # Current user message
        parts = []
        if user_prompt is not None:
            parts.append(Part.from_text(text=user_prompt))
        
        if images:
             for img in images:
                 if img.startswith("data:"):
                     header, data = img.split(",", 1)
                     mime_type = header.split(";")[0].split(":")[1]
                     image_bytes = base64.b64decode(data)
                     parts.append(Part.from_bytes(data=image_bytes, mime_type=mime_type))
                 else:
                     try:
                         image_bytes = base64.b64decode(img)
                         parts.append(Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                     except:
                         pass

        if parts:
            contents.append(Content(role="user", parts=parts))
            
        return contents

    def _format_usage(self, usage_metadata):
        if not usage_metadata:
            return "Usage info unavailable"
            
        try:
            parts = []
            if hasattr(usage_metadata, 'prompt_token_count'):
                parts.append(f"Prompt: {usage_metadata.prompt_token_count}")
            if hasattr(usage_metadata, 'candidates_token_count'):
                parts.append(f"Output: {usage_metadata.candidates_token_count}")
            if hasattr(usage_metadata, 'total_token_count'):
                parts.append(f"Total: {usage_metadata.total_token_count}")
            if hasattr(usage_metadata, 'thoughts_token_count') and usage_metadata.thoughts_token_count:
                parts.append(f"Thoughts: {usage_metadata.thoughts_token_count}")
                
            return "Usage: " + ", ".join(parts)
        except Exception:
            return f"Usage: {str(usage_metadata)}"

    @retry(
        reraise=True,
        stop=stop_after_attempt(15),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 0.5, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
        history_messages = kwargs.pop('history_messages', [])
        images = kwargs.pop('images', [])

        thinking_budget = kwargs.pop('thinking_budget', None)

        if thinking_budget is not None:
            _budget_map = {"low": 1024, "medium": 4096, "high": -1}
            if isinstance(thinking_budget, str):
                thinking_budget = _budget_map.get(thinking_budget.lower(), 1024)
            kwargs['thinking_config'] = ThinkingConfig(thinking_budget=thinking_budget)
        
        if json_mode:
            kwargs['response_mime_type'] = "application/json"
        
        if not user_prompt and sys_prompt:
            user_prompt = sys_prompt
            sys_prompt = ""
        
        contents = self._convert_messages(user_prompt, history_messages, images)
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=GenerateContentConfig(
                    system_instruction=sys_prompt if sys_prompt else None,
                    temperature=temperature,
                    **kwargs
                )
            )
            content = response.text
            usage = self._format_usage(getattr(response, 'usage_metadata', None))
            log_msg = f"Model: {self.model}, Temperature: {temperature}, {str(usage)}"
            await self.log_results(sys_prompt, user_prompt, content, log_msg, call_start_time)
            return content
        except Exception as e:
            logger.error(f"Gemini31Pro Call Error: {e}")
            raise e

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.5, **kwargs):
        call_start_time = datetime.datetime.now()
        history_messages = kwargs.pop('history_messages', [])
        images = kwargs.pop('images', [])
        thinking_budget = kwargs.pop('thinking_budget', None)

        kwargs = {}
        if thinking_budget is not None:
            _budget_map = {"low": 1024, "medium": 4096, "high": -1}
            if isinstance(thinking_budget, str):
                thinking_budget = _budget_map.get(thinking_budget.lower(), 1024)
            kwargs['thinking_config'] = ThinkingConfig(thinking_budget=thinking_budget)
        
        
        if not user_prompt and sys_prompt:
            user_prompt = sys_prompt
            sys_prompt = ""
        
        contents = self._convert_messages(user_prompt, history_messages, images)
        
        attempt = 0
        max_attempts = 15
        last_exception = None

        while attempt < max_attempts:
            string_buffer = io.StringIO()
            has_yielded = False
            
            try:
                response_stream = await self.client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=GenerateContentConfig(
                        system_instruction=sys_prompt if sys_prompt else None,
                        temperature=temperature,
                        **kwargs
                    )
                )
                
                usage_metadata = None
                async for chunk in response_stream:
                    if hasattr(chunk, 'text'):
                        delta = chunk.text
                        if delta:
                            string_buffer.write(delta)
                            yield delta
                            has_yielded = True
                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        usage_metadata = chunk.usage_metadata
                
                # If we complete the loop successfully, break the retry loop
                content = string_buffer.getvalue()
                string_buffer.close()
                
                usage_str = self._format_usage(usage_metadata)
                log_msg = f"Model: {self.model}, Temperature: {temperature}, {usage_str}"
                await self.log_results(sys_prompt, user_prompt, content, log_msg, call_start_time)
                return

            except Exception as e:
                last_exception = e
                # If we have already yielded content, we cannot transparently retry
                if has_yielded:
                    logger.error(f"Gemini31Pro Stream Error after yielding data: {e}")
                    raise e
                
                attempt += 1
                if attempt >= max_attempts:
                    logger.error(f"Gemini31Pro Stream Error (Max attempts reached): {e}")
                    raise e
                
                # Calculate backoff
                wait_time = min(30, 2 * (2 ** (attempt - 1))) # 2, 4, 8, 16...
                logger.warning(f"Gemini31Pro Stream Error: {e}. Retrying in {wait_time}s (Attempt {attempt}/{max_attempts})...")
                logger.warning(traceback.format_exc())
                await asyncio.sleep(wait_time)
        
        if last_exception:
            raise last_exception
            
    async def structured_output(self, input: list, schema: type, sys_prompt: str = "", **kwargs):
        user_prompt = ""
        for msg in input:
            if msg.get("role") == "user":
                user_prompt += msg.get("content", "") + "\n"
        
        response_text = await self.__call__(
            sys_prompt=sys_prompt,
            user_prompt=user_prompt.strip(),
            json_mode=True,
            response_schema=schema,
            **kwargs
        )
        return schema.model_validate_json(response_text)

    async def log_results(self, sys_prompt:str, user_prompt:str, content: str, usage: str, start_time=None) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        
        try:
            with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
                log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
                log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
                log_file.write(f"[{log_id}] [{current_time}] {content}\n{usage}\n")
                if start_time:
                    time_delta = end_time - start_time
                    formatted_time_delta = f"{time_delta.total_seconds():.2f} seconds"
                    log_file.write(f"[{log_id}] Time spent: {formatted_time_delta}\n")
                log_file.write("="*64+"\n")
            with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
                time_delta_str = ''
                if start_time:
                    time_delta = end_time - start_time
                    time_delta_str = f"[{time_delta.total_seconds():.2f}s]"
                log_file.write(f"[{log_id}] [{current_time}][{task_id}] {time_delta_str} {usage}\n")
        except Exception as e:
            logger.error(f"Failed to log results: {e}")

class Gemini3Flash(Gemini31Pro):

    provider = "google"

    def __init__(self, model: str = "gemini-3.0-flash-preview") -> None:
        self.model = "gemini-3-flash-preview"
        self.project = getattr(api_config, 'VERTEX_PROJECT_ID', None) or "noahai-440408"
        self.client = GoogleGenAIClientSingleton.get_client()

class Gemini35Flash(Gemini31Pro):

    provider = "google"

    def __init__(self, model: str = "gemini-3.5-flash") -> None:
        self.model = "gemini-3.5-flash"
        self.project = getattr(api_config, 'VERTEX_PROJECT_ID', None) or "noahai-440408"
        self.client = GoogleGenAIClientSingleton.get_client()

class CompositeClaude(VertexClaudeModel):

    models = [ClaudeSonnet45(), ClaudeHaiku45(), ClaudeSonnet4(), GPT41()]

    def __init__(self) -> None:
        self.current_index = 0
        self.loop_count = 5
        self.current_model = self.models[self.current_index]
        self.provider = self.current_model.provider if hasattr(self.current_model, 'provider') else ''

    def _try_next_model(self):
        r"""Try to switch to the next available model in the chain"""
        if self.current_index >= len(self.models) - 1 and len(self.models) and self.loop_count > 0:
            self.loop_count -= 1
            self.current_index = 0
        if self.current_index < len(self.models) - 1:
            self.current_index += 1
            self.current_model = self.models[self.current_index]
            self.provider = self.current_model.provider if hasattr(self.current_model, 'provider') else ''
            logger.info(f"Switching to {self.models.__class__.__name__}...")
            return True
        return False

    async def __call__(self, **kwargs) -> str:
        last_error = None
        while True:
            try:
                res = await self.current_model.__call__(**kwargs)
                self.current_index = 0  # Reset index on success
                self.current_model = self.models[self.current_index]
                self.loop_count = 5  # Reset loop count on success
                return res
            except Exception as e:
                last_error = e
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")
                
    async def stream_call(self, timeout: float = 15.0, **kwargs):
        last_error = None
        while True:
            try:
                async for chunk in self.current_model.stream_call(**kwargs):
                    yield chunk
                self.current_index = 0  # Reset index on success
                self.current_model = self.models[self.current_index]
                self.loop_count = 5  # Reset loop count on success
                return
            except asyncio.TimeoutError:
                logger.warn(f"Stream call timeout after {timeout} seconds")
                last_error = f"Timeout after {timeout} seconds"
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {last_error}")
            except Exception as e:
                logger.warn(f"Error: {str(e)}")
                logger.warn("Retrying with next model...")
                last_error = e
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")


class CompositeClaudeChat(CompositeClaude):

    provider = "anthropic"

    models = [ClaudeSonnet45(), ClaudeHaiku45(), ClaudeSonnet4(), GPT41()]

