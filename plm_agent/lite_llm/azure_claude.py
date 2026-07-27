# -*- coding: utf-8 -*-
import io
import httpx
import time
import logging
import json
import anthropic
import lite_llm.exceptions as LiteLLMExceptions

from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from anthropic import AsyncAnthropicFoundry

from config import api_config
from lite_llm.base_model import BaseLLM
from lite_llm.claude_model_base import ClaudeModelBase
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton

logger = logging.getLogger(__name__)


class AzureClaudeModel(BaseLLM, ClaudeModelBase):
    r"""
    https://platform.claude.com/docs/en/build-with-claude/claude-in-microsoft-foundry
    """

    provider = "azure_claude"

    def __init__(
        self,
        api_key: str,
        azure_endpoint: str,
        model: str,
        timeout: Union[float, httpx.Timeout] = 120.0,
        max_retries: int = 2
    ) -> None:
        # If env var is set, let SDK use it; otherwise use base_url
        self.client = AsyncAnthropicFoundry(api_key=api_key, base_url=azure_endpoint)
        self.model = model

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
            response = await self.client.messages.parse(
                model=self.model,
                messages=input,
                output_format=schema,
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
                content=response.content,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            
            try:
                return response.parsed_output
            except json.JSONDecodeError:
                # If parsing fails, return the string as-is
                logger.warning(f"Failed to parse output_text as JSON: {response.content}")
                return response.content[0].parsed_output
    
    async def stream_generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):

        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        # format messages
        messages = list(input)
        # When thinking is enabled, Azure Anthropic API requires system to be a list (not None),
        # so always pass sys_prompt via system parameter in that case.
        use_system_param = bool(kwargs.get('thinking'))
        if sys_prompt and len(sys_prompt) > 100 and not use_system_param:
            messages.insert(0, {"role": "user", "content": sys_prompt})

        system_value = [{"type": "text", "text": sys_prompt}] if sys_prompt and (len(sys_prompt) <= 100 or use_system_param) else None

        try:
            string_buffer = io.StringIO()
            last_event = None
            async with self.client.messages.stream(
                model=self.model,
                messages=messages,
                system=system_value,
                **kwargs,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "thinking_delta":
                            # bypass thinking text (reasoning summary)
                            # event.delta.thinking
                            pass
                        elif event.delta.type == "text_delta":
                            string_buffer.write(event.delta.text)
                            yield event.delta.text
                    last_event = event

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
            usage = getattr(getattr(last_event, "message", None), "usage", None)
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=last_event,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)

    async def generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        # format messages (same as stream_generate)
        messages = list(input)
        use_system_param = bool(kwargs.get('thinking'))
        if sys_prompt and len(sys_prompt) > 100 and not use_system_param:
            messages.insert(0, {"role": "user", "content": sys_prompt})

        system_value = [{"type": "text", "text": sys_prompt}] if sys_prompt and (len(sys_prompt) <= 100 or use_system_param) else None

        try:
            response = await self.client.messages.create(
                model=self.model,
                messages=messages,
                system=system_value,
                **kwargs,
            )
            content = ""
            for item in response.content:
                if item.type == "text":
                    content += item.text
            usage = response.usage
        except Exception as e:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="generate")
        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            return content
    
    async def compact_generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        summary_prompt: Optional[str] = None,
        max_tokens: int = 1024 * 20,
        thinking_budget_tokens: int = 1024 * 8,
        context_token_threshold: int = 1024 * 100,
    ):
        start_time = time.time()

        try:
            runner = self.client.beta.messages.tool_runner(
                model=self.model,
                messages=input,
                max_tokens=max_tokens,
                tools=[],  # pass tools via method param if needed
                thinking={
                    "type": "enabled",
                    "budget_tokens": thinking_budget_tokens,
                },
                compaction_control={
                    "enabled": True,
                    "summary_prompt": summary_prompt,
                    "context_token_threshold": context_token_threshold,
                }
            )
            response = await runner.until_done()
        except Exception as e:
            await self.log_results(
                input=input,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            self._handle_exception(e, method_name="compact_generate")
        else:
            await self.log_results(
                input=input,
                response=response,
                content=response.content,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
        
            # merge thinking and text content
            summary = ""
            for item in response.content:
                if item.type == "thinking":
                    summary = summary + f"<thinking>\n{item.thinking}\n</thinking>\n"
                if item.type == "text":
                    summary = summary + f"{item.text}\n"
            return summary

    async def sandbox_execute(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> object:
        """
        Execute tasks in sandbox with shell and python support via Claude Messages API.

        Args:
            tools: Tool definitions (required). Typically SANDBOX_TOOLS from
                   tools.sandbox.cloud_executor.

        Returns the raw response object (with .content, .stop_reason, etc.)
        """
        if tools is None:
            raise ValueError("sandbox_execute requires explicit tools parameter")

        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        # Enable prompt caching on system prompt and tools to reduce
        # redundant input token processing across multi-step sandbox loops.
        system_value = None
        if sys_prompt:
            system_value = [{
                "type": "text",
                "text": sys_prompt,
                "cache_control": {"type": "ephemeral"},
            }]

        tools_with_cache = list(tools)
        if tools_with_cache:
            tools_with_cache[-1] = {
                **tools_with_cache[-1],
                "cache_control": {"type": "ephemeral"},
            }

        try:
            response = await self.client.messages.create(
                model=self.model,
                system=system_value,
                messages=input,
                tools=tools_with_cache,
                timeout=300.0,  # sandbox final answers may take longer
                thinking={
                    "type": "enabled",
                    "budget_tokens": 1024 * 6,
                },
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
            # Extract text content for logging
            content = ""
            for item in response.content:
                if item.type == "text":
                    content += item.text
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=content,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            #logger.info(f"Sandbox llm execute input: {input}\n")
            #logger.info(f"Sandbox llm execute response: {response.content}\n")
            return response

    def _handle_exception(
        self, 
        e: Exception,
        method_name: str = "unknown"
    ):
        logger.error(f"Error in {method_name} for model {self.model}: {e}")
        if isinstance(e, anthropic.RateLimitError):
            raise LiteLLMExceptions.LLMRateLimited(
                provider=self.provider, 
                message=f"Rate limit exceeded in {method_name} for model {self.model}"
            )
        elif isinstance(e, anthropic.APITimeoutError):
            raise LiteLLMExceptions.LLMTimeout(
                provider=self.provider, 
                message=f"Timeout in {method_name} for model {self.model}"
            )
        if getattr(e, 'status_code', None) == 413:
            raise LiteLLMExceptions.LLMContextWindowExceeded(
                provider=self.provider, 
                message=f"Context length exceeded in {method_name} for model {self.model}"
            )
        raise e    


class AzureClaudeSonnet45(AzureClaudeModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            import os
            # If env var is set, let SDK use it; otherwise use base_url
            if os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE"):
                self.client = self.get_client(
                    client=AsyncAnthropicFoundry,
                    api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                    timeout=120.0,
                    max_retries=2,
                )
            else:
                self.client = self.get_client(
                    client=AsyncAnthropicFoundry,
                    api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                    base_url=api_config.AZURE_CLAUDE_SONNET_45_ENDPOINT,
                    timeout=120.0,
                    max_retries=2,
                )
            self.model = api_config.AZURE_CLAUDE_SONNET_45_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureClaudeSonnet45 initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_CLAUDE_SONNET_45_ENDPOINT,
                model=api_config.AZURE_CLAUDE_SONNET_45_DEPLOYMENT)

class AzureClaudeSonnet46(AzureClaudeModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            import os
            # If env var is set, let SDK use it; otherwise use base_url
            if os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE"):
                self.client = self.get_client(
                    client=AsyncAnthropicFoundry,
                    api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                    timeout=120.0,
                    max_retries=2,
                )
            else:
                self.client = self.get_client(
                    client=AsyncAnthropicFoundry,
                    api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                    base_url=api_config.AZURE_CLAUDE_SONNET_45_ENDPOINT,
                    timeout=120.0,
                    max_retries=2,
                )
            self.model = api_config.AZURE_CLAUDE_SONNET_46_DEPLOYMENT
        except Exception as e:
            logger.error(f"Error in AzureClaudeSonnet45 initialization: {e}")
            super().__init__(
                api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
                azure_endpoint=api_config.AZURE_CLAUDE_SONNET_45_ENDPOINT,
                model=api_config.AZURE_CLAUDE_SONNET_46_DEPLOYMENT)
