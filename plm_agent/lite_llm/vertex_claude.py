# -*- coding: utf-8 -*-
from calendar import c
import io
import httpx
import time
import logging

from typing import List, Optional, Dict, Any, Union
from anthropic import AsyncAnthropicVertex

from config import api_config
from lite_llm.base_model import BaseLLM
from lite_llm.claude_model_base import ClaudeModelBase
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton

logger = logging.getLogger(__name__)


class VertexClaudeModel(BaseLLM, ClaudeModelBase):
    """
    A base class for model req.
    https://platform.claude.com/docs/en/build-with-claude
    """

    provider = "vertex_claude"

    def __init__(
        self,
        project_id: str,
        model: str,
        region: str = 'global',
        timeout: Union[float, httpx.Timeout] = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.client = AsyncAnthropicVertex(
            project_id=project_id,
            region=region,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model

    async def stream_generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any
    ):
        start_time = time.time()
        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        try:
            string_buffer = io.StringIO()
            last_event = None
            async with self.client.messages.stream(
                model=self.model,
                messages=input,
                system=sys_prompt,
                **kwargs,
            ) as stream:

                async for event in stream:
                    if event.type == "content_block_delta":
                        if event.delta.type == "thinking_delta":
                            # bypass thinking text
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
            raise e
        else:
            usage = last_event.message.usage
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=last_event,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)

    async def generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        start_time = time.time()
        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        try:
            response = await self.client.messages.create(
                model=self.model,
                messages=input,
                system=sys_prompt,
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
            raise e
        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            return content


class VertexClaude45Opus(VertexClaudeModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAnthropicVertex,
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.VERTEX_CLAUDEOPUS45_MODEL_ID
        except Exception as e:
            logger.error(f"Error in VertexClaude45Opus initialization: {e}")
            super().__init__(
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                model=api_config.VERTEX_CLAUDEOPUS45_MODEL_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
            )


class VertexClaude45Sonnet(VertexClaudeModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAnthropicVertex,
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.VERTEX_CLAUDE45_MODEL_ID
        except Exception as e:
            logger.error(f"Error in VertexClaude45Opus initialization: {e}")
            super().__init__(
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                model=api_config.VERTEX_CLAUDE45_MODEL_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
            )


class VertexClaude45Haiku(VertexClaudeModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncAnthropicVertex,
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.VERTEX_CLAUDEHAIKU45_MODEL_ID
        except Exception as e:
            logger.error(f"Error in VertexClaude45Opus initialization: {e}")
            super().__init__(
                project_id=api_config.VERTEX_CLAUDE_PROJECT_ID,
                model=api_config.VERTEX_CLAUDEHAIKU45_MODEL_ID,
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
            )
   