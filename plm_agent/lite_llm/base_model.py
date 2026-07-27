# -*- coding: utf-8 -*-
import os
import time
import datetime
import logging

from abc import ABC
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from logging_config import log_id_var, task_id_var
from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class BaseLLM(ABC):
    """
    A base class for model req followed by OpenAI SDK function call and structured output interface.
    Subclasses should implement the function_call and structured_output methods and convert the input to the format expected by the OpenAI SDK, i.e. inputs, tools, tool_choice, etc.
    """
    provider: str = ""
    
    model: str = ""

    async def function_call(
        self,
        input: List[Dict[str, Any]],
        tools: List[BaseTool],
        tool_choice: Dict[str, Any],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        raise NotImplementedError(f"{self.__class__.__name__} function_call is not implemented")

    async def structured_output(
        self,
        input: List[Dict[str, Any]],
        schema: BaseModel,
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> BaseModel:
        raise NotImplementedError(f"{self.__class__.__name__} structured_output is not implemented")

    async def stream_generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        raise NotImplementedError(f"{self.__class__.__name__} stream_generate is not implemented")

    async def generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        raise NotImplementedError(f"{self.__class__.__name__} generate is not implemented")

    async def close(self):
        if hasattr(self, 'client'):
            try:
                await self.client.close()
            except Exception as e:
                logger.error(f"Error in close for model {self.model}: {e}")
                pass

    async def log_results(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        schema: Optional[BaseModel] = None,
        response: Optional[Any] = None,
        content: Optional[str] = None,
        usage: Optional[str] = None,
        start_time: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        """
        Log the results of an LLM API call.
        
        Args:
            inputs: List of input messages/dicts sent to the model
            sys_prompt: Optional system prompt
            tools: Optional list of tools for function calling
            tool_choice: Optional tool choice configuration
            schema: Optional Pydantic schema for structured output
            response: Optional raw response object from the API
            content: Optional response content/text
            usage: Optional usage information (tokens, cost, etc.)
            start_time: Optional timestamp when the call started
            **kwargs: Additional keyword arguments
        """
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = time.time()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{log_id}] [{current_datetime}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_datetime}] {input}\n")
            #log_file.write(f"[{log_id}] [{current_datetime}] {input[:-1]}\n")
            log_file.write(f"[{log_id}] [{current_datetime}] {content}\n")
            log_file.write(f"[{log_id}] [{current_datetime}] {usage}\n")
            try:
                log_file.write(f"[{log_id}] Model: {response.model}\n")
            except:
                pass
            if start_time:
                time_delta = end_time - start_time
                formatted_time_delta = f"{time_delta:.2f} seconds"
                log_file.write(f"[{log_id}] Time spent: {formatted_time_delta}\n")
            log_file.write("="*64+"\n")
        with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
            time_delta = end_time - start_time if start_time else None
            time_delta_str = f"[{time_delta:.2f}s]" if time_delta is not None else ''
            log_file.write(f"[{log_id}] [{current_datetime}][{task_id}] {time_delta_str} {usage}\n")
