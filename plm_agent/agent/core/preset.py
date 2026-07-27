import json
import logging
import traceback
from typing import List
from typing_extensions import Self
from pydantic import BaseModel, ConfigDict, model_validator

from agent.explore.schema import MindSearchResponse
from llm.azure_models import GPT41
from utils.core.exception import UnexpectedException
from utils.core.standardize import standardize_yield, standardize_yield_wo_dump
from llm.base_model import BaseLLM
from tools.core.base_tool import BaseTool
from utils.core.get_tool_schema import (get_anthropic_input_schema, get_azure_openai_input_schema,
                                        get_openai_input_schema, get_azure_openai_input_schema_v2)

logger = logging.getLogger(__name__)


class AgentPreset(BaseModel):
    """
    An agent preset that defines the system prompt, the LLM model, the tools, and the tool usage.
    Attributes:
        llm (BaseLLM): The LLM model to use.
        sys_prompt (str): The system prompt, defaults to an empty string.
        tools (list[str]): A list of tools to use, defaults to an empty list.
        tool_choice (str): The tool choice for openai models ('none', 'auto', {"type": "function", "function": {"name": "my_function"}}), defaults to an empty string.
        tool_use (str): The tool usage for claude models ('any', 'auto', {"type":"tool", "name": ""}), defaults to an empty string.
    """
    llm: BaseLLM = GPT41
    backup_llms: List[BaseLLM] = [GPT41]
    sys_prompt: str = ""
    tools: List[BaseTool] = []
    tool_choice: str = ""
    tool_use: str = ""
    break_stream: bool = False
    attachment_included: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @model_validator(mode='after')
    def check_tool_usage(self) -> Self:
        if not self.tools:
            self.tool_choice = ""
            self.tool_use = ""
            return self 
        if self.llm.provider == "openai":
            if isinstance(self.tool_choice, str):
                if self.tool_choice not in ["auto", "required", "none"]:
                    raise ValueError('openai function call tool_choice must be "auto" or "requred" or "none"')
            elif isinstance(self.tool_choice, dict):
                if "type" not in self.tool_choice or self.tool_choice["type"] != "function" or "name" not in self.tool_choice:
                    raise ValueError('openai function call tool_choice must be {"type": "function", "name": "get_weather"}')
                found = False
                for tool in self.tools:
                    if tool.name == self.tool_choice["name"]:
                        found = True
                if not found:
                    raise ValueError(f'openai function call tool_choice function {self.tool_choice["name"]} not in tools')
            else:
                raise ValueError('openai function call tool_choice must be "auto" or "requred" or "none" or like  {"type": "function", "name": "get_weather"}')
        if self.llm.provider == "anthropic":
            if isinstance(self.tool_choice, dict):
                if "type" not in self.tool_choice or self.tool_choice["type"] not in ["auto", "any", "tool"]:
                    raise ValueError('anthropic function call tool_choice must be {"type": "function", "name": "get_weather"}')
                if self.tool_choice["type"] == "tool":
                    if "name" not in self.tool_choice:
                        raise ValueError('anthropic function call tool_choice function must be like {"type": "tool", "name": "get_weather"}')
                    found = False
                    for tool in self.tools:
                        if tool.name == self.tool_choice["name"]:
                            found = True
                    if not found:
                        raise ValueError(f'anthropic function call tool_choice function {self.tool_choice["name"]} not in tools')
            else:
                raise ValueError('anthropic function call tool_choice function must be like {"type": "tool", "name": "get_weather"} or {"type": "noe"}')
        return self

    def get_schema(self) -> dict:
        """
        Get the tools input schema.
        Returns:
            dict: The schema of the agent preset.
        """
        if self.llm.provider == "openai":
            return [get_openai_input_schema(tool()) for tool in self.tools]
        elif self.llm.provider == "azure_openai":
            # TODO update this method
            if self.llm.__name__.startswith('GPT5'):
                return [get_azure_openai_input_schema_v2(tool()) for tool in self.tools] 
            return [get_azure_openai_input_schema(tool()) for tool in self.tools] 
        elif self.llm.provider == "anthropic":
            return [get_anthropic_input_schema(tool()) for tool in self.tools]
        elif self.llm.provider == "moonshot":
            return [get_azure_openai_input_schema(tool()) for tool in self.tools]
        else:
            return []
    
    def get_llm_params(self) -> list:
        return ['temperature', 'reasoning', 'previous_response_id', 'max_output_tokens', 'prompt_cache_key']
        
    @standardize_yield
    async def start(self, *args, **kwargs):
        try:
            async for chunk in self.use_tool(*args, **kwargs):
                yield chunk
        # except UnexpectedException as exc:
        #     yield {"error": str(exc)}
        except Exception as exc:
            logger.info(traceback.format_exc())
            logger.warning(f'Run use_tool failed: {exc}')
            yield {"error": str(exc)}
            return
            # if self.backup_llms:
            #     logger.info(f'{self.llm} failed, Using backup llms:', self.backup_llms)
            #     for backup_llm in self.backup_llms:
            #         try:
            #             logger.info('Using backup llm:', backup_llm)
            #             self.llm = backup_llm
            #             async for chunk in self.use_tool(*args, **kwargs):
            #                 yield chunk
            #                 if test and type(chunk) == MindSearchResponse and chunk.content:
            #                     return
            #             break
            #         except Exception as e:
            #             logger.warn(f'Run use_tool failed', e)
            
    
    @standardize_yield_wo_dump
    async def start_wo_dump(self, *args, **kwargs):
        async for chunk in self.use_tool(*args, **kwargs):
            yield chunk
    
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        body = {
            "sys_prompt": self.sys_prompt,
            "user_prompt": user_prompt,
            "history_messages": history_messages,
            "images": images
        }
        tools_schema = self.get_schema()
        agent_params = dict(self)
        agent_params = {k: v for k, v in agent_params.items() if v}
        # TODO 定义初始字典，只存llm需要的字段，等待模型参数统一之后
        agent_params.pop('backup_llms', None)
        agent_params.pop('work_dir', None)
        agent_params.pop('sandbox_url', None)
        agent_params.pop('use_sandbox', None)
        agent_params.pop('enable_file_management', None)
        agent_params.pop('enable_code_review', None)
        agent_params.pop('tool_config', None)
        agent_params.pop('coder_agent', None)
        agent_params.pop('intent_llm', None)
        agent_params.pop('helper', None)
        agent_params.pop('tool_prompt', None)
        if tools_schema:
            agent_params['tools'] = tools_schema
        llm = agent_params.pop('llm')()
        body.update(agent_params)
        # add max_tokens, temperature
        body.update({k: kwargs[k] for k in self.get_llm_params() if k in kwargs})
        response = await llm(**body)
        yield response

        if not response:
            return
        elif self.llm.provider == 'azure_openai':
            # Skip tool use for models with responses outside of OpenAI api response types (that dont support tool use)
            # chat completion create
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    for tool in self.tools:
                        if tool.__name__ == function_name:
                            async for chunk in tool(agent=self).run(**args):
                                yield chunk
            # response api
            elif hasattr(response, 'tools') and response.tools:
                for item in response.output:
                    if item.type == 'function_call':
                        function_name = item.name
                        args = json.loads(item.arguments)
                        args['_context'] = item
                        for tool in self.tools:
                            if tool.__name__ == function_name:
                                async for chunk in tool(agent=self).run(**args):
                                    yield chunk

        elif self.llm.provider == 'openai':
            # Skip tool use for models with responses outside of OpenAI api response types (that dont support tool use)
            if hasattr(response, 'tools') and response.tools:
                for item in response.output:
                    if item.type == 'function_call':
                        function_name = item.name
                        args = json.loads(item.arguments)
                        args['_context'] = item
                        for tool in self.tools:
                            if tool.__name__ == function_name:
                                async for chunk in tool(agent=self).run(**args):
                                    yield chunk

        elif self.llm.provider == 'anthropic':
            # Skip tool use for models with responses outside of OpenAI api response types (that dont support tool use)
            assistant_reasoning = ""
            for tool_call in response:
                if tool_call.type == "text":
                    assistant_reasoning = tool_call.text
                elif tool_call.type == "tool_use":
                    function_name = tool_call.name
                    args = tool_call.input
                    if assistant_reasoning:
                        args['assistant_reasoning'] = assistant_reasoning
                    for tool in self.tools:
                        if tool.__name__ == function_name:
                            async for chunk in tool(agent=self).run(**args):
                                yield chunk

        elif self.llm.provider == 'moonshot':
            
            if hasattr(response, 'tool_calls') and response.tool_calls:
                for tool_call in response.tool_calls:
                    function_name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    args['_context'] = tool_call
                    for tool in self.tools:
                        if tool.__name__ == function_name:
                            async for chunk in tool(agent=self).run(**args):
                                yield chunk            

    
    async def stream_call(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        body = {
            "sys_prompt": self.sys_prompt,
            "history_messages": history_messages,
            "user_prompt": user_prompt,
            "images": images
        }
        agent_params = dict(self)
        agent_params = {k: v for k, v in agent_params.items() if v}
        agent_params.pop('backup_llms', None)
        # try:
        llm = agent_params.pop('llm')()
        logger.info(f"using llm f{llm}")
        body.update({k: kwargs[k] for k in self.get_llm_params() if k in kwargs})
        async for chunk in llm.stream_call(**body):
            yield chunk
        # except Exception as exc:
        #     logger.info(f'{self.llm} failed', exc)
        #     if self.backup_llms:
        #         print("Using backup llms", self.backup_llms)
        #     for backup_llm in self.backup_llms:
        #         print("Using backup llm", backup_llm)
        #         llm = backup_llm()
        #         try:
        #             async for chunk in llm.stream_call(**body):
        #                 yield chunk
        #             break
        #         except: 
        #             pass

    async def stream_call_origin(
        self,
        user_prompt: str,
        history_messages: List[dict] = [],
        **kwargs):
        body = {
            'sys_prompt': self.sys_prompt,
            'user_prompt': user_prompt,
            'history_messages': history_messages,
        }
        tools_schema = self.get_schema()
        agent_params = dict(self)
        agent_params = {k: v for k, v in agent_params.items() if v}
        agent_params.pop('backup_llms', None)
        if tools_schema:
            agent_params['tools'] = tools_schema
        llm = agent_params.pop('llm')()
        body.update(agent_params)
        body.update({k: kwargs[k] for k in self.get_llm_params() if k in kwargs})
        
        result_type = None
        response = None
        last_chunk = None
        async for chunk in llm.stream_call_origin(**body):
            last_chunk = chunk
            if chunk.type == 'response.output_item.added':
                result_type = chunk.item.type
            elif chunk.type == 'response.completed':
                response = chunk
            if result_type == 'message':
                if chunk.type == 'response.output_text.delta':
                    yield chunk.delta
        
        if not response:
            yield last_chunk.response
            return

        response = response.response
        if result_type == 'function_call':
            yield response
        
            for item in response.output:
                if item.type == 'function_call':
                    function_name = item.name
                    args = json.loads(item.arguments)
                    args['_context'] = item
                    for tool in self.tools:
                        if tool.__name__ == function_name:
                            async for chunk in tool(agent=self).run(**args):
                                yield chunk
