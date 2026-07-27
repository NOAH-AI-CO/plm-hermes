# -*- coding: utf-8 -*-
import io
import httpx
import time
import logging
import json
import random

from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from openai import AsyncOpenAI

from config import api_config
import lite_llm.exceptions as LiteLLMExceptions
from lite_llm.base_model import BaseLLM
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton
from lite_llm.openai_function_calling import OpenaiFunctionCallingChatCompletion
from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class DeepSeekModel(BaseLLM, OpenaiFunctionCallingChatCompletion):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: Union[float, httpx.Timeout] = 120.0,
        max_retries: int = 2,
        ):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)

    def _get_valid_kwargs(
        self,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        r"""
        Get the valid kwargs from the kwargs.
        Args:
            kwargs(dict): The keyword arguments.
        Returns:
            Dict[str, Any]: The valid kwargs.
        """

        new_kwargs = {}
        if 'reasoning' in kwargs:
            new_kwargs['extra_body'] = {"thinking": {"type": "enabled"}}
    
        valid_kwargs = [
            'temperature',
            'top_p',
        ]
        new_kwargs.update({k: v for k, v in kwargs.items() if k in valid_kwargs})

        return new_kwargs

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
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=input,
                tools=tools,
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
                content=response.choices[0].message.content,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            
            return response.choices[0].message

    async def structured_output(
        self,
        input: List[Union[Dict[str, Any], object]],
        schema: BaseModel,
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict:
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)

        input.append({
            'role': 'user',
            'content': f"""
Please carefully read the messages, then parse the data and output them in JSON format.

***IMPORTANT***
The output must be a valid JSON object as the schema below:
```json
{json.dumps(schema.model_json_schema(), indent=4)}
```
"""
        })

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=input,
                response_format={
                    'type': 'json_object'
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
            self._handle_exception(e, method_name="structured_output")
            
        else:
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
                content=response.choices[0].message.content,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)
            
            return schema.model_validate_json(response.choices[0].message.content)

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
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=input,
                stream=True,
                **kwargs,
            )

            string_buffer = io.StringIO()
            connection_time = time.time()
            reasoning_flag = False
            first_valid_chunk = False
            last_chunk = None
            async for chunk in response:

                if len(chunk.choices) == 0:
                    continue
                
                chunk_content = None
                content = getattr(chunk.choices[0].delta, 'content', None)
                reasoning_content = getattr(chunk.choices[0].delta, 'reasoning_content', None)
                
                # Huoshan and deepseek original put thinking in reasoning_content
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
                        logger.info(f"{self.client.__class__.__name__} Deepseek client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True

                    # return chunk content
                    string_buffer.write(chunk_content)
                    yield chunk_content
                
                last_chunk = chunk

            content = string_buffer.getvalue()
            string_buffer.close()

        except Exception as e:
            print(e)
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
                response=response,
                content=content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            if last_chunk is None:
                raise LiteLLMExceptions.LLMStreamEndedWithoutResponse(
                    provider=self.provider,
                    message=f"Stream ended without any chunk, response may be truncated"
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
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=input,
                **kwargs,
            )

            content = response.choices[0].message.content
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

    def _handle_exception(
        self, 
        e: Exception,
        method_name: str = "unknown"
    ):
        logger.error(f"Error in {method_name} for model {self.model}: {e}")
        raise e


class DeepSeekChatModel(DeepSeekModel, AsyncLlmSDKSingleton):

    def __init__(self):
        keys = api_config.DEEPSEEK_API_KEYS.split(",")
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=random.choice(keys),
                base_url=api_config.DEEPSEEK_API_ENDPOINT,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.DEEPSEEK_API_CHAT_MODEL
        except Exception as e:
            logger.error(f"Error in DeepSeekChatModel initialization: {e}")
            super().__init__(
                api_key=random.choice(keys),
                base_url=api_config.DEEPSEEK_API_ENDPOINT,
                model=api_config.DEEPSEEK_API_CHAT_MODEL)
