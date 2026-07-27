# -*- coding: utf-8 -*-

import logging

from enum import Enum
from pydantic import BaseModel
from typing import List, Dict, Any, get_args, get_origin

from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class OpenaiFunctionCalling:
    """
    A base class for model req.
    https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?tabs=python-secure
    """

    # mapping of tool use type to Azure OpenAI property type
    tool_use_type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }

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
    
        valid_kwargs = [
            'reasoning',
            'tools',
            'tool_choice',
            'max_output_tokens',
            'previous_response_id',
            'max_tool_calls',
            'parallel_tool_calls',
            'temperature',
            'top_p',
        ]
        return {k: v for k, v in kwargs.items() if k in valid_kwargs}

    def _get_function_call_schema(
        self,
        tool: BaseTool,
    ) -> Dict[str, Any]:
        r"""
        Get the function call schema from the tool.
        Args:
            tool(BaseTool): The tool.
        Returns:
            Dict[str, Any]: The function call schema.
        """
        function = {
            "type": "function",  
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }

        for k, v in tool.input_schema.__annotations__.items():
            if v is None:
                continue
            underlying_type = self._get_underlying_type(v)
            property_obj = self._get_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

            # Open Ai require all field must be required when strict mode is true
            is_optional = (underlying_type is not v) and (type(None) in get_args(v))
            if not is_optional or tool.strict:
                function["parameters"]["required"].append(k)
                
            function["parameters"]["properties"][k] = property_obj

        if tool.strict:
            function['strict'] = True
        
        return function

    def _get_underlying_type(
        self,
        annotation: Any,
    ) -> Any:
        r"""
        Get the underlying type from the annotation.
        Args:
            annotation(Any): The annotation.
        Returns:
            Any: The underlying type.
        """
        args = get_args(annotation)
        
        if len(args) == 2 and type(None) in args:
            
            return args[0] if args[1] is type(None) else args[1]
        
        return annotation 
    
    def _get_openai_property_schema(
        self,
        field_type,
        field_info,
        strict
    ) -> Dict[str, Any]:
        r"""
        Get the Azure OpenAI property schema from the field type and field info.
        Args:
            field_type(Any): The field type.
            field_info(Any): The field info.
            strict(bool): The strict mode.
        Returns:
            Dict[str, Any]: The Azure OpenAI property schema.
        """
        origin = get_origin(field_type)

        if origin is list:
            
            item_type = get_args(field_type)[0]
            
            property_type = "array"
            
            if type(None) in get_args(field_info.annotation):
                property_type = [property_type, "null"]
            
            return {
                "type": property_type,
                "items": self._get_openai_property_schema(item_type, field_info, strict),
                "description": field_info.description
            }
        
        elif issubclass(field_type, BaseModel):
        
            return self._get_openai_object_input_schema(field_type, field_info, strict)
        
        elif issubclass(field_type, Enum):
        
            return self._get_openai_enum_schema(field_type, field_info)
        
        else:
        
            property_type = self.tool_use_type_mapping.get(field_type.__name__.lower())
            if type(None) in get_args(field_info.annotation):
                property_type = [property_type, "null"]
            return {
                "type": property_type,
                "description": field_info.description
            }

    def _get_openai_object_input_schema(
        self,
        tool: BaseModel,
        tool_info,
        strict
    ) -> Dict[str, Any]:
        property_type = "object"
        if type(None) in get_args(tool_info.annotation):
            property_type = [property_type, "null"]
        property = {
            "type": property_type,
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
        for k, v in tool.__annotations__.items():
            if v is None:
                continue
            underlying_type = self._get_underlying_type(v)
            property_obj = self._get_openai_property_schema(underlying_type, tool.model_fields[k], strict)

            is_optional = (underlying_type is not v) and (type(None) in get_args(v))
            if not is_optional or strict:
                property["required"].append(k)

            property["properties"][k] = property_obj
        return property

    def _get_openai_enum_schema(
        self,
        enum_tool: Enum,
        field_info
    ) -> Dict[str, Any]:
        enum_type = "string"
        if type(None) in get_args(field_info.annotation):
            enum_type = ["string", "null"]
        values = [str(e.value) for e in enum_tool]
        description = enum_tool.__doc__ or f"Enum values for {enum_tool}"
        return {
            "type": enum_type,
            "enum": values,
            "description": description
        }

    def _get_tools(
        self,
        tools: List[BaseTool],
    ) -> List[Dict[str, Any]]:
        r"""
        Get the tools from the tools list.
        Args:
            tools(List[BaseTool]): The tools list.
        Returns:
            List[Dict[str, Any]]: The tools list.
        """
        new_tools = []
        for tool in tools:
            if isinstance(tool, BaseTool):
                new_tools.append(self._get_function_call_schema(tool()))
            else:
                new_tools.append(tool)
        return new_tools


class OpenaiFunctionCallingChatCompletion(OpenaiFunctionCalling):
    """
    A class for OpenAI function calling chat completion.
    """

    def _get_function_call_schema(
        self,
        tool: BaseTool,
    ) -> Dict[str, Any]:
        function = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False
                }
            }
        }

        for k, v in tool.input_schema.__annotations__.items():
            if v is None:
                continue
            underlying_type = self._get_underlying_type(v)
            property_obj = self._get_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

            # Open Ai require all field must be required when strict mode is true
            is_optional = (underlying_type is not v) and (type(None) in get_args(v))
            if not is_optional or tool.strict:
                function["function"]["parameters"]["required"].append(k)
                
            function["function"]["parameters"]["properties"][k] = property_obj

        if tool.strict:
            function['strict'] = True
        
        return function