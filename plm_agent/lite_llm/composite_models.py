# -*- coding: utf-8 -*-
import json
import logging

import lite_llm.exceptions as LiteLLMExceptions

from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel

from tools.core.base_tool import BaseTool
from lite_llm.base_model import BaseLLM


logger = logging.getLogger(__name__)


class CompositeModel:

    models: List[BaseLLM] = []

    def __init__(self, models: List[BaseLLM]):
        self.models = models

    def _convert_input(self, input: List[Union[Dict[str, Any], object]]) -> List[Dict[str, Any]]:
        new_input = []
        for item in input:
            if isinstance(item, dict):
                if 'role' in item:
                    new_input.append(item)
                else:
                    new_input.append({
                        'role': 'user',
                        'content': json.dumps(item)
                     })
            else:
                new_input.append(item.model_dump())
        return new_input

    async def structured_output(
        self,
        input: List[Union[Dict[str, Any], object]],
        schema: BaseModel,
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        for index, model in enumerate(self.models):
            try:
                response = await model.structured_output(input, schema, sys_prompt, **kwargs)
                if not response:
                    raise RuntimeError(f"No structured_output response from model {model.__class__.__name__}")
                return response
            except LiteLLMExceptions.LLMContextWindowExceeded as e:
                raise e
            except Exception as e:
                logger.error(f"Error in model {model.__class__.__name__}: {e}")

                if index + 1 >= len(self.models):
                    raise LiteLLMExceptions.LLMNoModelAvailable(provider='composite', message="No model available")

                if self.models[index + 1].provider == model.provider:
                    continue

                input = self._convert_input(input)

        raise LiteLLMExceptions.LLMNoModelAvailable(provider='composite', message="No model available")

    async def stream_generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        for index, model in enumerate(self.models):
            try:
                response = model.stream_generate(input, sys_prompt, **kwargs)
                async for chunk in response:
                    yield chunk
                return
            except LiteLLMExceptions.LLMContextWindowExceeded as e:
                raise e
            except Exception as e:
                logger.error(f"Error in model {model.__class__.__name__}: {e}")

                if index + 1 >= len(self.models):
                    raise LiteLLMExceptions.LLMNoModelAvailable(provider='composite', message="No model available")

                if self.models[index + 1].provider == model.provider:
                    continue

                input = self._convert_input(input)

        raise LiteLLMExceptions.LLMNoModelAvailable(provider='composite', message="No model available")

    async def generate(
        self,
        input: List[Union[Dict[str, Any], object]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        for index, model in enumerate(self.models):
            try:
                response = await model.generate(input, sys_prompt, **kwargs)
                return response
            except Exception as e:
                logger.error(f"Error in model {model.__class__.__name__}: {e}")

                if index + 1 >= len(self.models):
                    raise LiteLLMExceptions.LLMNoModelAvailable(provider='composite', message="No model available")

                if self.models[index + 1].provider == model.provider:
                    continue