# -*- coding: utf-8 -*-
import io
import re
import json
import time
import logging

from enum import Enum
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple, get_args, get_origin
from google import genai
from google.genai import types

from config import api_config
import lite_llm.exceptions as LiteLLMExceptions
from lite_llm.base_model import BaseLLM
from lite_llm.llm_sdk_singleton import AsyncLlmSDKSingleton
from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class GoogleModel(BaseLLM):
    """
    A base class for Google model.
    """
    provider = "google"

    # mapping of tool use type to Azure OpenAI property type
    tool_use_type_mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }

    def __init__(
        self,
        model: str,
    ) -> None:
        self.model = model
        self.client = genai.Client(location="global", )

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
            'temperature',
            'top_p',
            'top_k',
            'max_output_tokens',
            'thinking_config',
        ]
        return {k: v for k, v in kwargs.items() if k in valid_kwargs}

    def _extract_error_details(self, err: Exception) -> Optional[Any]:
        """
        Try to extract structured error details from Google GenAI exceptions.
        Returns a best-effort details object (dict/list/str) or None.
        """
        # Common attributes on google/api_core exceptions
        for attr in ("details", "error", "errors"):
            if hasattr(err, attr):
                value = getattr(err, attr)
                if value:
                    return value

        # Some errors carry a response object (requests/httpx style)
        response = getattr(err, "response", None)
        if response is not None:
            try:
                data = response.json()
                if isinstance(data, dict):
                    if isinstance(data.get("error"), dict) and data["error"].get("details"):
                        return data["error"]["details"]
                    if data.get("details"):
                        return data["details"]
                    return data
            except Exception:
                text = getattr(response, "text", None)
                if text:
                    return text

        # Try to parse JSON from the exception string
        err_str = str(err)
        if err_str:
            err_str = err_str.strip()
            if err_str.startswith("{") and err_str.endswith("}"):
                try:
                    data = json.loads(err_str)
                    if isinstance(data, dict):
                        if isinstance(data.get("error"), dict) and data["error"].get("details"):
                            return data["error"]["details"]
                        if data.get("details"):
                            return data["details"]
                        return data
                except Exception:
                    pass

        return None

    def _get_tool_choice(
        self,
        tool_choice: Dict[str, Any],
    ) -> Dict[str, Any]:
        r"""
        Get the tool choice from the tool choice.
        Args:
            tool_choice(Dict[str, Any]): The tool choice.
        Returns:
            Dict[str, Any]: The tool choice.
        """
        if isinstance(tool_choice, str):
            if tool_choice == "auto":
                return types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode='AUTO')
                )
            elif tool_choice == "required":
                return types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode='ANY')
                )
            elif tool_choice == "none":
                return types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode='NONE')
                )
        elif isinstance(tool_choice, dict):
            if "type" not in tool_choice:
                raise ValueError('google function call tool_choice must be "function" or "allowed_tools"')
            if tool_choice["type"] == "function":

                if "name" not in tool_choice:
                    raise ValueError('google function call tool_choice must be {"type": "function", "name": "get_weather"}')
                
                return types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=[tool_choice["name"]]
                    )
                )
            
            elif tool_choice["type"] == "allowed_tools":
                
                if "tools" not in tool_choice:
                    raise ValueError('google function call tool_choice must be {"type": "allowed_tools", "tools": [{ "type": "function", "name": "get_weather" },]}')
                
                names = [tool["name"] for tool in tool_choice["tools"]]
                return types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode='ANY',
                        allowed_function_names=[names]
                    )
                )
        raise ValueError(f'google function call tool_choice must be "function" or "allowed_tools"')

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
            underlying_type = self.get_underlying_type(v)
            property_obj = self.get_google_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

            # Open Ai require all field must be required when strict mode is true
            is_optional = (underlying_type is not v) and (type(None) in get_args(v))
            if not is_optional or tool.strict:
                function["parameters"]["required"].append(k)
                
            function["parameters"]["properties"][k] = property_obj
        
        return function

    def get_underlying_type(
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
    
    def get_google_property_schema(
        self,
        field_type,
        field_info,
        strict
    ) -> Dict[str, Any]:
        r"""
        Get the Google property schema from the field type and field info.
        Args:
            field_type(Any): The field type.
            field_info(Any): The field info.
            strict(bool): The strict mode.
        Returns:
            Dict[str, Any]: The Google property schema.
        """
        origin = get_origin(field_type)

        if origin is list:
            
            item_type = get_args(field_type)[0]
            
            property_type = "array"
            
            if type(None) in get_args(field_info.annotation):
                property_type = [property_type, "null"]
            
            return {
                "type": property_type,
                "items": self.get_google_property_schema(item_type, field_info, strict),
                "description": field_info.description
            }
        
        elif issubclass(field_type, BaseModel):
        
            return self.get_google_object_input_schema(field_type, field_info, strict)
        
        elif issubclass(field_type, Enum):
        
            return self.get_google_enum_schema(field_type, field_info)
        
        else:
        
            property_type = self.tool_use_type_mapping.get(field_type.__name__.lower())
            if type(None) in get_args(field_info.annotation):
                property_type = [property_type, "null"]
            return {
                "type": property_type,
                "description": field_info.description
            }

    def get_google_property_schema(
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
                "items": self.get_google_property_schema(item_type, field_info, strict),
                "description": field_info.description
            }
        
        elif issubclass(field_type, BaseModel):
        
            return self.get_google_object_input_schema(field_type, field_info, strict)
        
        elif issubclass(field_type, Enum):
        
            return self.get_google_enum_schema(field_type, field_info)
        
        else:
        
            property_type = self.tool_use_type_mapping.get(field_type.__name__.lower())
            if type(None) in get_args(field_info.annotation):
                property_type = [property_type, "null"]
            return {
                "type": property_type,
                "description": field_info.description
            }

    def get_google_object_input_schema(
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
            underlying_type = self.get_underlying_type(v)
            property_obj = self.get_google_property_schema(underlying_type, tool.model_fields[k], strict)

            is_optional = (underlying_type is not v) and (type(None) in get_args(v))
            if not is_optional or strict:
                property["required"].append(k)

            property["properties"][k] = property_obj
        return property

    def get_google_enum_schema(
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
        return [self._get_function_call_schema(tool()) for tool in tools]

    def _parse_data_uri(self, data_uri: str) -> Tuple[bytes, str]:
        r"""
        Parse a data URI and extract base64 data and MIME type.
        Args:
            data_uri(str): Data URI in format "data:image/jpeg;base64,{base64_data}"
        Returns:
            tuple[bytes, str]: A tuple of (decoded_bytes, mime_type)
        """
        # Match pattern: data:[mime_type];base64,[base64_data]
        match = re.match(r'data:([^;]+);base64,(.+)', data_uri)
        if not match:
            raise ValueError(f"Invalid data URI format: {data_uri}")
        
        mime_type = match.group(1)
        base64_data = match.group(2)
        
        return base64_data, mime_type

    def _format_input(
        self,
        input: List[Dict[str, Any]],
    ) -> List:
        r"""
        Format the input to the format expected by the Google model.
        Args:
            input(List[Dict[str, Any]]): The input.
        Returns:
            List[Dict[str, Any]]: The formatted input.
        """
        res = []
        for item in input:
            if isinstance(item, dict):
                
                role = 'model' if item["role"] == "assistant" else 'user'
                
                if isinstance(item["content"], str):
                    if role == 'model':
                        res.append(types.ModelContent(parts=types.Part.from_text(text=item["content"])))
                    else:
                        res.append(types.UserContent(parts=types.Part.from_text(text=item["content"])))

                elif isinstance(item["content"], list):

                    parts = []
                    
                    for content_item in item["content"]:
                        
                        if content_item["type"] == "input_text":
                            parts.append(types.Part.from_text(text=content_item["text"]))
                        
                        elif content_item["type"] == "input_image":
                            
                            url = content_item["image_url"]
                        
                            # Check if it's a data URI
                            if url.startswith("data:"):
                                decoded_bytes, mime_type = self._parse_data_uri(url)
                                parts.append(types.Part.from_bytes(data=decoded_bytes, mime_type=mime_type))
                            else:
                                # Regular URL
                                parts.append(types.Part.from_uri(file_uri=url))
                            
                            res.append(types.UserContent(parts=parts))
                        
                        else:
                            raise ValueError(f"Invalid content type: {type(content_item)}")
            
            else:
                # bypass other content type，i.e. function call, tool call, etc.
                res.append(item)

        return res

    async def function_call(
        self,
        input: List[Dict[str, Any]],
        tools: List[BaseTool],
        tool_choice: Dict[str, Any],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        r"""
        Call the Google model function.
        https://ai.google.dev/gemini-api/docs/function-calling?example=meeting
        Args:
            input(List[Dict[str, Any]]): The input.
            tools(List[BaseTool]): The tools.
            tool_choice(Dict[str, Any]): The tool choice.
            sys_prompt(Optional[str]): The system prompt.
            **kwargs: Additional keyword arguments.
        Returns:
            Any: The response.
        """
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)
        tools = self._get_tools(tools)
        tool_config = self._get_tool_choice(tool_choice)

        config = types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=tools)],
            system_instruction=sys_prompt,
            tool_config=tool_config,
            **kwargs,
        )

        try:
            # Format input from OpenAI format to Gemini format
            formatted_contents = self._format_input(input)
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=formatted_contents,
                config=config,
            )
        except Exception as e:
            await self.log_results(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            raise e
        else:
            usage = response.usage_metadata
            await self.log_results(
                input=input,
                tools=tools,
                tool_choice=tool_choice,
                sys_prompt=sys_prompt,
                response=response,
                content=response.candidates[0].content,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)
            
            return response.candidates[0].content

    async def structured_output(
        self,
        input: List[Dict[str, Any]],
        schema: BaseModel,
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> BaseModel:
        r"""
        Call the Google model structured output.
        Args:
            input(List[Dict[str, Any]]): The input.
            schema(BaseModel): The schema.
            sys_prompt(Optional[str]): The system prompt.
            **kwargs: Additional keyword arguments.
        Returns:
            Any: The response.
        """
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)
        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            response_mime_type='application/json',
            response_json_schema=schema.model_json_schema(),
            **kwargs,
        )

        try:
            formatted_contents = self._format_input(input)
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=formatted_contents,
                config=config,
            )
        except Exception as e:
            await self.log_results(
                input=input,
                schema=schema,
                sys_prompt=sys_prompt,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            raise e
        else:
            await self.log_results(
                input=input,
                schema=schema,
                sys_prompt=sys_prompt,
                response=response,
                content=response.text,
                usage=f"Model: {self.model}, Usage: {response.usage_metadata}",
                start_time=start_time)

            # Parse output_text as JSON
            return schema.model_validate_json(response.text)

    async def stream_generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        r"""
        Call the Google model stream generate.
        Args:
            input(List[Dict[str, Any]]): The input.
            sys_prompt(Optional[str]): The system prompt.
            **kwargs: Additional keyword arguments.
        Returns:
            Any: The response.
        """
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)
        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            **kwargs,
        )

        try:
            formatted_contents = self._format_input(input)
            response = await self.client.aio.models.generate_content_stream(
                model=self.model,
                contents=formatted_contents,
                config=config,
            )

            string_buffer = io.StringIO()
            last_chunk = None
            async for chunk in response:
                last_chunk = chunk
                string_buffer.write(chunk.text)
                yield chunk.text

            content = string_buffer.getvalue()

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
            usage = last_chunk.usage_metadata if last_chunk else None
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
                    message=f"Stream ended without any chunk, response may be truncated"
                )
    
    async def generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        start_time = time.time()

        # get required input parameters from kwargs
        kwargs = self._get_valid_kwargs(**kwargs)
        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            **kwargs,
        )

        try:
            formatted_contents = self._format_input(input)
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=formatted_contents,
                config=config,
            )

            content = response.text
            usage = response.usage_metadata

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

    async def image_generate(
        self,
        input: List[Dict[str, Any]],
        sys_prompt: Optional[str] = None,
        response_modalities: List[str] = None,
        image_config: types.ImageConfig = None,
        thinking_config: types.ThinkingConfig = None,
        **kwargs: Any,
    ):
        r"""
        Call the Google model image generate.
        Args:
            input: The input.
            sys_prompt: The system prompt.
            **kwargs: Additional keyword arguments.
        Returns:
            Any: The response.
        """
        start_time = time.time()

        if not response_modalities or not isinstance(response_modalities, list):
            response_modalities = ['IMAGE', 'TEXT']
        
        if not image_config or not isinstance(image_config, types.ImageConfig):
            image_config = types.ImageConfig(
                aspect_ratio="3:2",
                output_mime_type="image/png",
            )
        
        if not thinking_config or not isinstance(thinking_config, types.ThinkingConfig):
            thinking_config = types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=types.ThinkingLevel.MINIMAL # Default is minimal
            )

        config = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            response_modalities=response_modalities,
            image_config=image_config,
            thinking_config=thinking_config,
        )

        try:
            formatted_contents = self._format_input(input)
            
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=formatted_contents,
                config=config,
            )

        except Exception as e:
            details = self._extract_error_details(e)
            if details is not None:
                try:
                    details_str = json.dumps(details, ensure_ascii=False)
                except Exception:
                    details_str = str(details)
                logger.error("Google image_generate error details: %s", details_str)
                if not hasattr(e, "lite_llm_details"):
                    try:
                        setattr(e, "lite_llm_details", details)
                    except Exception:
                        pass
                    
            await self.log_results(
                input=input,
                response=e,
                content=str(e),
                usage=f"Model: {self.model}, Error: {e}",
                start_time=start_time)
            raise e

        else:
            usage = response.usage_metadata
            await self.log_results(
                input=input,
                response=response,
                content=response.text,
                usage=f"Model: {self.model}, Usage: {usage}",
                start_time=start_time)

            base64_data = None
            if response.candidates[0].finish_reason != types.FinishReason.STOP:
                reason = response.candidates[0].finish_reason
                logger.error(f"Image generation failed, Model: {self.model}, Error: {reason}")
                return None

            for part in response.candidates[0].content.parts:
                if part.thought:
                    continue # Skip displaying thoughts
                if part.inline_data:
                    base64_data = part.inline_data.data
            
            return base64_data

class Gemini25FlastLite(GoogleModel, AsyncLlmSDKSingleton):
    def __init__(self, api_version: str = "v1"):
        try:
            self.client = self.get_client(
                client=genai.Client,
            )
            self.model = api_config.VERTEX_GEMINI25_FLASH_LITE_MODRL_ID
        except Exception as e:
            logger.error(f"Error in Gemini25FlastLite initialization: {e}")
            super().__init__(
                model=api_config.VERTEX_GEMINI25_FLASH_LITE_MODRL_ID,
                api_version=api_version,
            )


class Gemini3FlastLite(GoogleModel, AsyncLlmSDKSingleton):
    def __init__(self, api_version: str = "v1"):
        try:
            self.client = self.get_client(
                client=genai.Client,
            )
            self.model = api_config.VERTEX_GEMINI30_FLASH_LITE_MODEL_ID
        except Exception as e:
            logger.error(f"Error in Gemini3FlastLite initialization: {e}")
            super().__init__(
                model=api_config.VERTEX_GEMINI30_FLASH_LITE_MODEL_ID,
                api_version=api_version,
            )


class Gemini3Pro(GoogleModel, AsyncLlmSDKSingleton):
    def __init__(self, api_version: str = "v1"):
        try:
            self.client = self.get_client(
                client=genai.Client,
            )
            self.model = api_config.VERTEX_GEMINI30_PRO_MODRL_ID
        except Exception as e:
            logger.error(f"Error in Gemini3Pro initialization: {e}")
            super().__init__(
                model=api_config.VERTEX_GEMINI30_PRO_MODRL_ID,
                api_version=api_version,
            )


class Gemini31FlashLiteImage(GoogleModel, AsyncLlmSDKSingleton):
    def __init__(self, api_version: str = "v1"):
        try:
            self.client = self.get_client(
                client=genai.Client,
            )
            self.model = api_config.VERTEX_GEMINI31_FLASH_LITE_IMAGE_MODEL_ID
        except Exception as e:
            logger.error(f"Error in Gemini31FlashLiteImage initialization: {e}")
            super().__init__(
                model=api_config.VERTEX_GEMINI31_FLASH_LITE_IMAGE_MODEL_ID,
                api_version=api_version,
            )

class Gemini31Pro(GoogleModel, AsyncLlmSDKSingleton):
    def __init__(self, api_version: str = "v1"):
        try:
            self.client = self.get_client(
                client=genai.Client,
            )
            self.model = api_config.VERTEX_GEMINI31_PRO_MODRL_ID
        except Exception as e:
            logger.error(f"Error in Gemini31Pro initialization: {e}")
            super().__init__(
                model=api_config.VERTEX_GEMINI31_PRO_MODRL_ID,
                api_version=api_version,
            )
