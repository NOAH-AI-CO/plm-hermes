from enum import Enum
from inspect import isclass

from tools.core.base_tool import BaseTool
from typing import Type, get_args, Optional, Union, get_origin

from pydantic_core import PydanticUndefined
from pydantic import BaseModel, Field


tool_use_type_mapping = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "dict": "object",
}
    
def get_underlying_type(annotation):
    args = get_args(annotation)
    if len(args) == 2 and type(None) in args:
        return args[0] if args[1] is type(None) else args[1]
    return annotation

def get_azure_openai_input_schema(tool: BaseTool):
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
        underlying_type = get_underlying_type(v)
        property_obj = get_azure_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

        # Open Ai require all field must be required when strict mode is true
        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or tool.strict:
            function["parameters"]["required"].append(k)
            
        function["parameters"]["properties"][k] = property_obj

    if tool.strict:
        function['strict'] = True
    
    tools_result = {
        "type": "function",
        "function": function,
    }

    return tools_result

def get_azure_openai_input_schema_v2(tool: BaseTool):
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
        underlying_type = get_underlying_type(v)
        property_obj = get_azure_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

        # Open Ai require all field must be required when strict mode is true
        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or tool.strict:
            function["parameters"]["required"].append(k)
            
        function["parameters"]["properties"][k] = property_obj

    if tool.strict:
        function['strict'] = True
    
    return function

def get_openai_input_schema_v3(tool: BaseTool):
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

    all_fields = {}
    for field_name, field_info in tool.input_schema.model_fields.items():
        all_fields[field_name] = field_info.annotation
        
    for k, v in all_fields.items():
        if v is None:
            continue
        underlying_type = get_underlying_type(v)
        property_obj = get_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

        # Open Ai require all field must be required when strict mode is true
        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or tool.strict:
            function["parameters"]["required"].append(k)
            
        function["parameters"]["properties"][k] = property_obj

    if tool.strict:
        function['strict'] = True

    tools_result = {
        "type": "function",
        "function": function,
    }

    return tools_result


def get_azure_openai_property_schema(field_type, field_info, strict):
    origin = get_origin(field_type)
    # Check if the field type is a list type annotation (e.g. List[str])
    if origin is list:
        item_type = get_args(field_type)[0]
        property_type = "array"
        if type(None) in get_args(field_info.annotation):
            property_type = [property_type, "null"]
        return {
            "type": property_type,
            "items": get_azure_openai_property_schema(item_type, field_info, strict),
            "description": field_info.description
        }
    elif issubclass(field_type, BaseModel):
        return get_azure_openai_object_input_schema(field_type, field_info, strict)
    elif issubclass(field_type, Enum):
        return get_azure_openai_enum_schema(field_type, field_info)
    else:
        property_type = tool_use_type_mapping[field_type.__name__.lower()]
        if type(None) in get_args(field_info.annotation):
            property_type = [property_type, "null"]
        return {
            "type": property_type,
            "description": field_info.description
        }

def get_azure_openai_object_input_schema(tool: BaseModel, tool_info, strict):
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
        underlying_type = get_underlying_type(v)
        property_obj = get_azure_openai_property_schema(underlying_type, tool.model_fields[k], strict)

        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or strict:
            property["required"].append(k)

        property["properties"][k] = property_obj
    return property

def get_azure_openai_enum_schema(enum_tool: Enum, field_info):
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

def get_anthropic_input_schema(tool: BaseTool):
    result = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
    for k, v in tool.input_schema.__annotations__.items():
        if v is None:
            continue
        underlying_type = get_underlying_type(v)
        property_obj = get_anthropic_property_schema(underlying_type, tool.input_schema.model_fields[k])
        
        if tool.input_schema.model_fields[k].default != PydanticUndefined:
            property_obj["default"] = tool.input_schema.model_fields[k].default

        # if tool.input_schema.model_fields[k]
        if underlying_type is not v:
            if type(None) in get_args(v):
                pass
            else:
                result["input_schema"]["required"].append(k)
        else:
            result["input_schema"]["required"].append(k)
        result["input_schema"]["properties"][k] = property_obj
    return result

def get_anthropic_property_schema(field_type, field_info):
    origin = get_origin(field_type)
    if origin is list:
        item_type = get_args(field_type)[0]
        return {
            "type": "array",
            "items": get_anthropic_property_schema(item_type, field_info),
            "description": field_info.description
        }
    elif issubclass(field_type, BaseModel):
        return get_anthropic_object_input_schema(field_type)
    elif issubclass(field_type, Enum):
        return get_anthropic_enum_schema(field_type)
    else:
        return {
            "type": tool_use_type_mapping[field_type.__name__.lower()],
            "description": field_info.description
        }

def get_anthropic_object_input_schema(tool: BaseModel):
    result = {
        "type": "object",
        "properties": {},
        "required": []
    }
    for k, v in tool.__annotations__.items():
        if v is None:
            continue
        underlying_type = get_underlying_type(v)
        property_obj = get_anthropic_property_schema(underlying_type, tool.model_fields[k])

        if tool.model_fields[k].default != PydanticUndefined:
            property_obj["default"] = tool.model_fields[k].default

        if underlying_type is not v:
            if type(None) not in get_args(v):
                result["required"].append(k)
        else:
            result["required"].append(k)
        result["properties"][k] = property_obj
    return result

def get_anthropic_enum_schema(enum_tool: Enum):
    values = [e.value for e in enum_tool]
    description = enum_tool.__doc__ or f"Enum values for {enum_tool}"
    return {
        "type": "string",
        "enum": values,
        "description": description
    }


def get_openai_input_schema(tool: BaseTool):
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
        underlying_type = get_underlying_type(v)
        property_obj = get_openai_property_schema(underlying_type, tool.input_schema.model_fields[k], tool.strict)

        # Open Ai require all field must be required when strict mode is true
        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or tool.strict:
            function["parameters"]["required"].append(k)
            
        function["parameters"]["properties"][k] = property_obj

    if tool.strict:
        function['strict'] = True

    return function

def get_openai_property_schema(field_type, field_info, strict):
    origin = get_origin(field_type)
    # Check if the field type is a list type annotation (e.g. List[str])
    if origin is list:
        item_type = get_args(field_type)[0]
        property_type = "array"
        if type(None) in get_args(field_info.annotation):
            property_type = [property_type, "null"]
        return {
            "type": property_type,
            "items": get_openai_property_schema(item_type, field_info, strict),
            "description": field_info.description
        }
    elif issubclass(field_type, BaseModel):
        return get_openai_object_input_schema(field_type, field_info, strict)
    elif issubclass(field_type, Enum):
        return get_openai_enum_schema(field_type, field_info)
    else:
        property_type = tool_use_type_mapping[field_type.__name__.lower()]
        if type(None) in get_args(field_info.annotation):
            property_type = [property_type, "null"]
        return {
            "type": property_type,
            "description": field_info.description
        }

def get_openai_object_input_schema(tool: BaseModel, tool_info, strict):
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
        underlying_type = get_underlying_type(v)
        property_obj = get_openai_property_schema(underlying_type, tool.model_fields[k], strict)

        is_optional = (underlying_type is not v) and (type(None) in get_args(v))
        if not is_optional or strict:
            property["required"].append(k)

        property["properties"][k] = property_obj
    return property

def get_openai_enum_schema(enum_tool: Enum, field_info):
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



def test_get_input_schema():
    class TestClassFunctionInputSchema(BaseModel):
        simple: Optional[bool] = Field(description='Simple field')

    class TestFunctionInputSchema(BaseModel):
        #simple: bool = Field(description='Simple field')
        #optional_filed: Optional[bool] = Field(description='Optional field')
        class_filed: Optional[TestClassFunctionInputSchema] = Field(description='Class field')

    class TestFunction(BaseTool):
        name: str = 'TestFunction'
        description: str = 'Test function tool'
        input_schema: BaseModel = TestFunctionInputSchema
        strict: bool = True

    async def run(self, **kwarg):
        pass

    result = get_azure_openai_input_schema(TestFunction())
    print("azure openai input schema")
    print(result)

    result = get_openai_input_schema(TestFunction())
    print("openai input schema")
    print(result)    

if __name__ == "__main__":
    test_get_input_schema()

