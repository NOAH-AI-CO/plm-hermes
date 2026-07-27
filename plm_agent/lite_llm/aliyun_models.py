# -*- coding: utf-8 -*-
import base64
import io
import os
import httpx
import time
import json
import logging
import asyncio

from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union
from openai import AsyncOpenAI
from dashscope.aigc.image_generation import ImageGeneration
from dashscope.api_entities.dashscope_response import Message

from config import api_config
from lite_llm.base_model import BaseLLM
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton
from lite_llm.openai_function_calling import OpenaiFunctionCallingChatCompletion
from tools.core.base_tool import BaseTool
from PIL import Image as PILImage


logger = logging.getLogger(__name__)

class AliyunModel(BaseLLM, OpenaiFunctionCallingChatCompletion):
    """
    A base class for Ali model.
    """
    provider = "aliyun"

    def __init__(
        self,
        api_key: str,
        base_url: str,
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
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model

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
            new_kwargs['extra_body'] = {"enable_thinking": True}
    
        valid_kwargs = [
            'tools',
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

        # format messages
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages += input

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=input,
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
                content=response.choices[0].message,
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
        
        # format messages
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages += input

        try:
            response = await self.client.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=schema,
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
                content=response.choices[0].message,
                usage=f"Model: {self.model}, Usage: {response.usage}",
                start_time=start_time)

            content = response.choices[0].message.content

            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content

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
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages += input

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                #stream_options={"include_usage": True},
                **kwargs,
            )
            
            string_buffer = io.StringIO()
            usage = None
            async for chunk in response:
                if not chunk.choices:
                    usage = chunk.usage
                    continue

                delta = chunk.choices[0].delta

                # reasoning content
                if hasattr(delta, "reasoning_content") and delta.reasoning_content is not None:
                    pass

                if hasattr(delta, "content") and delta.content:
                    yield delta.content
                    string_buffer.write(delta.content)          

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
            await self.log_results(
                input=input,
                sys_prompt=sys_prompt,
                response=response,
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

        # format messages
        messages = []
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages += input

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
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
        

class AliyunQwen3Max(AliyunModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                timeout=120.0,
                max_retries=2,
            )
            self.mode = api_config.QWEN3_MAX_MODEL_ID
        except Exception as e:
            logger.error(f"Error in AliyunQwen3Max initialization: {e}")
            super().__init__(
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                model=api_config.QWEN3_MAX_MODEL_ID,
            )


class AliyunQwenPlus(AliyunModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                timeout=120.0,
                max_retries=2,
            )
            self.mode = api_config.QWEN_PLUS_MODLE_ID
        except Exception as e:
            logger.error(f"Error in AliyunQwen3Max initialization: {e}")
            super().__init__(
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                model=api_config.QWEN_PLUS_MODLE_ID,
            )


class AliyunQwenFlash(AliyunModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                timeout=120.0,
                max_retries=2,
            )
            self.mode = api_config.QWEN_FLASH
        except Exception as e:
            logger.error(f"Error in AliyunQwen3Max initialization: {e}")
            super().__init__(
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                model=api_config.QWEN_FLASH,
            )

class AliyunQwenVLOCR(AliyunModel, AsyncLlmSDKSingleton):

    def __init__(self):
        try:
            model_id = getattr(api_config, "QWEN_VL_OCR_MODEL_ID", "qwen-vl-ocr-latest")
            
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                timeout=120.0,
                max_retries=2,
            )
            self.model = model_id
        except Exception as e:
            logger.error(f"Error in AliyunQwenVLOCR initialization: {e}")
            super().__init__(
                api_key=api_config.QWEN_API_KEYS,
                base_url=api_config.QWEN_API_ENDPOINT,
                model="qwen-vl-ocr-latest",
            )

    def _process_image_input(self, image_input: Union[str, Any]) -> str:
        # 1. 如果是 PIL Image 对象
        if isinstance(image_input, PILImage.Image):
            buf = io.BytesIO()
            # 统一转为 JPEG 以保证兼容性和压缩率
            image_input.save(buf, format='JPEG') 
            return base64.b64encode(buf.getvalue()).decode('utf-8')
        
        # 2. 如果是字符串
        if isinstance(image_input, str):
            # 2a. 如果是本地文件路径
            if os.path.exists(image_input):
                with open(image_input, "rb") as image_file:
                    return base64.b64encode(image_file.read()).decode('utf-8')
            # 2b. 假设已经是 Base64 字符串（简单清洗，去掉 data:image 前缀如果存在）
            if image_input.startswith("data:image"):
                return image_input.split(",")[1]
            return image_input

        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    def build_ocr_message(self, image_input: Union[str, Any], prompt: str = "ocr the page") -> List[Dict[str, Any]]:
        """
        构建符合 Qwen-VL-OCR 要求的 message 结构。
        
        Args:
            image_input: 可以是 本地路径(str)、PIL Image对象、或者 Base64字符串
            prompt (str): OCR 提示词
        """
        base64_image = self._process_image_input(image_input)
        
        # Qwen-VL 推荐使用 jpeg 格式头，即使原图是 png，base64 流通常也能被兼容解析
        message_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{base64_image}"
                },
                # Qwen-VL 特有优化参数
                "min_pixels": 32 * 32 * 3,
                "max_pixels": 32 * 32 * 8192
            },
            {
                "type": "text",
                "text": prompt
            }
        ]

        return [{"role": "user", "content": message_content}]

class AliyunWanImageGeneration:
    """Wan 2.6 image generation via DashScope SDK."""

    def __init__(self):
        self.model = "qwen-image-max"
        self.api_key = api_config.QWEN_API_KEYS

    async def image_generate(self, prompt: str, size: str = "1280*1280") -> str:
        """
        Generate image, return image URL (valid 24h).
        Uses dashscope ImageGeneration.call() in a thread executor (SDK is sync-only).
        Returns image URL string or None on failure.
        """

        model = self.model
        api_key = self.api_key

        def _sync_call():
            message = Message(role="user", content=[{"text": prompt}])
            rsp = ImageGeneration.call(
                model=model,
                api_key=api_key,
                messages=[message],
                n=1,
                size=size,
                prompt_extend=True,
                watermark=False,
            )
            logger.info(f"Wan 2.0 response: {rsp}")
            if rsp and rsp.output and rsp.output.get("choices"):
                choice = rsp.output["choices"][0]
                content = choice.get("message", {}).get("content", [])
                for item in content:
                    if item.get("image"):
                        return item["image"]
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _sync_call)