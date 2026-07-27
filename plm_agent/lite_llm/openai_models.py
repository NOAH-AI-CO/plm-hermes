# -*- coding: utf-8 -*-
import httpx
import logging

from typing import Union, Optional
from openai import AsyncOpenAI

from config import api_config
from lite_llm.azure_openai import AzureOpenAIModel
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton

logger = logging.getLogger(__name__)


class OpenAIModel(AzureOpenAIModel):

    provider = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: Union[float, httpx.Timeout] = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.model = model


class OpenAIImage2:

    provider = "openai"

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=api_config.OPENAI_API_KEY,
            timeout=120.0,
            max_retries=2,
        )
    
    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1024",
        quality: str = "medium",
        n: int = 1,
    ):
        response = await self.client.images.generate(
            model=api_config.OPENAI_IMAGE_2,
            prompt=prompt,
            size=size,
            quality=quality,
            n=n,
        )
        
        first_item = response.data[0] if response.data else None
        return getattr(first_item, "b64_json", None)

    async def edit_image(
        self,
        prompt: str,
        image: bytes,
        mask: Optional[bytes] = None,
        size: str = "1024x1024",
        quality: str = "medium",
        n: int = 1,
    ):
        response = await self.client.images.edit(
            model="gpt-image-1", # TODO so far image-2 don't support edits
            prompt=prompt,
            image=image,
            size=size,
        )

        first_item = response.data[0] if response.data else None
        return getattr(first_item, "b64_json", None)

class OpenAI5Nano(OpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.OPENAI_API_KEY,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.OPENAI_GPT5_NANO
        except Exception as e:
            logger.error(f"Error in OpenAI5Nano initialization: {e}")
            super().__init__(
                api_key=api_config.OPENAI_API_KEY,
                model=api_config.OPENAI_GPT5_NANO,
            )


class OpenAI5Mini(OpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.OPENAI_API_KEY,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.OPENAI_GPT5_MINI
        except Exception as e:
            logger.error(f"Error in OpenAI5Mini initialization: {e}")
            super().__init__(
                api_key=api_config.OPENAI_API_KEY,
                model=api_config.OPENAI_GPT5_MINI,
            )


class OpenAI5(OpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.OPENAI_API_KEY,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.OPENAI_GPT5
        except Exception as e:
            logger.error(f"Error in OpenAI5 initialization: {e}")
            super().__init__(
                api_key=api_config.OPENAI_API_KEY,
                model=api_config.OPENAI_GPT5,
            )


class OpenAI51(OpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.OPENAI_API_KEY,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.OPENAI_GPT5_1
        except Exception as e:
            logger.error(f"Error in OpenAI51 initialization: {e}")
            super().__init__(
                api_key=api_config.OPENAI_API_KEY,
                model=api_config.OPENAI_GPT5_1,
            )


class OpenAI52(OpenAIModel, AsyncLlmSDKSingleton):
    def __init__(self):
        try:
            self.client = self.get_client(
                client=AsyncOpenAI,
                api_key=api_config.OPENAI_API_KEY,
                timeout=120.0,
                max_retries=2,
            )
            self.model = api_config.OPENAI_GPT5_2
        except Exception as e:
            logger.error(f"Error in OpenAI52 initialization: {e}")
            super().__init__(
                api_key=api_config.OPENAI_API_KEY,
                model=api_config.OPENAI_GPT5_2,
            )