# -*- coding: utf-8 -*-
import io
import httpx
import time
import logging
import openai
import lite_llm.exceptions as LiteLLMExceptions

from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from openai import AsyncAzureOpenAI

from config import api_config
from lite_llm.base_model import BaseLLM
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton
from lite_llm.openai_function_calling import OpenaiFunctionCalling
from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class AzureOpenAIModel(BaseLLM, OpenaiFunctionCalling):
    """
    A base class for model req.
    https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?tabs=python-secure
    """
    
    provider = "azure_openai"

    def __init__(
        self,
        api_key: str,
        api_version: str,
        azure_endpoint: str,
        model: str,
        timeout: Union[float, httpx.Timeout] = 120.0,
        max_retries: int = 2,
    ) -> None:

        r"""
        Initialize the Azure OpenAI model.
        Args:
            api_key(str): The API key for the Azure OpenAI model.
            api_version(str): The API version for the Azure OpenAI model.
            azure_endpoint(str): The Azure endpoint for the Azure OpenAI model.
            model(str): The model name for the Azure OpenAI model.
        """
        self.client = AsyncAzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model

    async def function_call(
        self,
        input: List[Union[Dict[str, Any], object]],
        tools: List[BaseTool],
        tool_choice: Dict[str, Any],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> List:
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)
        tools = self._get_tools(tools)

        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
        
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                tools=tools,
                tool_choice=tool_choice,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="function_call")

        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                tools=tools,
                tool_choice=tool_choice,
                response=response,
                content=response.output,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)

            return response.output

    async def structured_output(
        self,
        input: List[Union[Dict[str, Any], object]],
        schema: BaseModel,
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> BaseModel:
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                text_format=schema,
                **kwargs,
            )
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="structured_output")

        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=response.output,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            return response.output_parsed

    async def stream_generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                stream=True,
                **kwargs,
            )

            string_buffer = io.StringIO()
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
                    last_chunk = chunk.response
            
            content = string_buffer.getvalue()
            string_buffer.close()
    
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="stream_generate")

        else:
            usage = last_chunk.usage if last_chunk else None
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=last_chunk,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            if last_chunk is None:
                raise LiteLLMExceptions.LLMStreamEndedWithoutResponse(
                    provider=self.provider, 
                    message=f"Stream ended without response.completed event, response may be truncated"
                )
    
    async def generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                **kwargs,
            )
            
            content = response.output_text
            usage = response.usage
    
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="stream_generate")

        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            return content

    async def sandbox_execute(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Execute tasks in sandbox with shell and python support.

        Tools available to LLM:
        - shell: Execute shell commands
        - sandbox_python: Execute Python code directly
        """
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        # Add sandbox tools: shell and python
        if 'tools' not in kwargs:
            kwargs['tools'] = []

        # Shell tool (new shell type instead of local_shell)
        kwargs['tools'].append({"type": "shell"})

        # Python tool (function calling)
        kwargs['tools'].append({
            "type": "function",
            "name": "sandbox_python",
            "description": "Execute Python code in the AgentRun cloud sandbox. Data file from previous tool calls is available at workspace/tool_results_data.json (exact path provided in system prompt). You can use `open('tool_results_data.json')` to read it from the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Common libraries available: json, pandas, numpy, matplotlib, etc."
                    }
                },
                "required": ["code"]
            }
        })

        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                **kwargs,
            )
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="sandbox_execute")
        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=response.output_text,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            return response

    async def local_shell(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Execute tasks with local_shell tool only (for backward compatibility).
        Used by cloud_executor.py for sandbox-based execution.
        """
        start_time = time.time()

        kwargs = self._get_valid_kwargs(**kwargs)

        if 'tools' not in kwargs:
            kwargs['tools'] = []
        kwargs['tools'].append({"type": "local_shell"})

        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=sys_prompt,
                input=input,
                **kwargs,
            )
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="local_shell")
        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=response.output_text,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            return response

    def _handle_exception(
        self, 
        e: Exception,
        method_name: str = "unknown"
    ):
        logger.error(f"Error in {method_name} for model {self.model}: {e}")
        if isinstance(e, openai.APIError):
            if e.code == 'context_length_exceeded':
                raise LiteLLMExceptions.LLMContextWindowExceeded(
                    provider=self.provider, 
                    message=f"Context length exceeded in {method_name} for model {self.model}"
                )
        elif isinstance(e, openai.RateLimitError):
            raise LiteLLMExceptions.LLMRateLimited(
                provider=self.provider, 
                message=f"Rate limit exceeded in {method_name} for model {self.model}"
            )
        elif isinstance(e, openai.Timeout):
            raise LiteLLMExceptions.LLMTimeout(
                provider=self.provider, 
                message=f"Timeout in {method_name} for model {self.model}"
            )
        raise e

    async def close(self):
        if hasattr(self, 'client'):
            await self.client.close()


class AzureOpenAI5Nano(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_NANO_DEPLOYEMNT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI5Nao initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                model=api_config.AZURE_GPT5_NANO_DEPLOYEMNT)


class AzureOpenAI5Mini(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_MIN_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI5Mini initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                model=api_config.AZURE_GPT5_MIN_DEPLOYMENT)


class AzureOpenAI54Mini(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_4_MIN_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_4_MIN_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI54Mini initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_4_MIN_VERSION,
                model=api_config.AZURE_GPT5_4_MIN_DEPLOYMENT)


class AzureOpenAI5(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI5 initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                model=api_config.AZURE_GPT5_DEPLOYMENT)


class AzureOpenAI51(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_1_DEPLOYEMNT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI51 initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                model=api_config.AZURE_GPT5_1_DEPLOYEMNT)


class AzureOpenAI52(AzureOpenAIModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_2_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI52 initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_VERSION,
                model=api_config.AZURE_GPT5_2_DEPLOYMENT)


class AzureOpenAI51Codex(AzureOpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAzureOpenAI,
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_1_CODEX_VERSION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.AZURE_GPT5_1_CODEX_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureOpenAI51Codex initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
                api_version=api_config.AZURE_GPT5_1_CODEX_VERSION,
                model=api_config.AZURE_GPT5_1_CODEX_DEPLOYMENT)


class AzureOpenAIImage2:

    provider = "azure_openai"

    def __init__(self):
        self.endpoint = api_config.AZURE_GPT5_IMAGE_2_ENDPOINT
        self.api_key = api_config.AZURE_GPT5_IMAGE_2_API_KEY
        self.api_version = api_config.AZURE_GPT5_IMAGE_2_VERSION

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "low",
        n: int = 1,
    ) -> Optional[List[str]]:
        start_time = time.time()
        url = f"{self.endpoint}?api-version={self.api_version}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": n,
        }
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(
                f"AzureOpenAIImage2 generate_image error: {e}, "
                f"elapsed={time.time() - start_time:.2f}s"
            )
            return None
        else:
            logger.info(
                f"AzureOpenAIImage2 generate_image success, "
                f"elapsed={time.time() - start_time:.2f}s"
            )
            return [item["b64_json"] for item in data["data"]]

    async def edit_image(
        self,
        prompt: str,
        image: bytes,
        mask: Optional[bytes] = None,
        size: str = "1024x1024",
        quality: str = "medium",
        output_format: str = "png",
        n: int = 1,
    ) -> Optional[List[str]]:
        start_time = time.time()
        url = self.endpoint.replace("images/generations", "images/edits")
        url = f"{url}?api-version={self.api_version}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        files = {
            "image": ("image.png", image, "image/png"),
        }
        if mask is not None:
            files["mask"] = ("mask.png", mask, "image/png")
        form_data = {
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "output_format": output_format,
            "n": str(n),
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    url, headers=headers, files=files, data=form_data
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(
                f"AzureOpenAIImage2 edit_image error: {e}, "
                f"elapsed={time.time() - start_time:.2f}s"
            )
            return None
        else:
            logger.info(
                f"AzureOpenAIImage2 edit_image success, "
                f"elapsed={time.time() - start_time:.2f}s"
            )
            return [item["b64_json"] for item in data["data"]]
