from inspect import isclass

from utils.core.get_tool_schema import get_azure_openai_property_schema, get_underlying_type, tool_use_type_mapping
from tools.core.base_tool import BaseTool
from typing import Type, get_args, Optional, Union, get_origin

from pydantic_core import PydanticUndefined
from pydantic import BaseModel

from utils.core.formatting import if_camel_to_snake


def get_openai_json_schema(model: BaseModel):
    json_schema = {
        "name": if_camel_to_snake(model.__class__.__name__),
        "schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    }
    for k, v in model.__annotations__.items():
        if v is None:
            continue
        underlying_type = get_underlying_type(v)
        property_obj = get_azure_openai_property_schema(underlying_type, model.model_fields[k])

        if underlying_type is not v:
            if type(None) not in get_args(v):
                json_schema["schema"]["required"].append(k)
        else:
            json_schema["schema"]["required"].append(k)
        json_schema["schema"]["properties"][k] = property_obj
        
    return {"type": "json_schema", "json_schema": json_schema}



def get_openai_json_schema_v2(model: BaseModel):
    model_name = if_camel_to_snake(model.__name__)
    model_description = model.__doc__ or f"Schema for {model_name}"
    
    json_schema = {
        "name": model_name,
        "description": model_description.strip(),
        "schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    }
    for k in model.model_fields:
        annotated_type = model.__annotations__.get(k)
        v = model.model_fields[k]
        if v is None:
            continue
        # If annotated_type is None, use the field's type information from model_fields
        if annotated_type is None:
            annotated_type = v.annotation
        underlying_type = get_underlying_type(annotated_type)
        # If underlying_type is still None, use the field's outer_type
        if underlying_type is None:
            underlying_type = getattr(v, 'outer_type', None) or v.annotation
        property_obj = get_azure_openai_property_schema(underlying_type, v)

        if underlying_type is not v:
            if type(None) not in get_args(v):
                json_schema["schema"]["required"].append(k)
        else:
            json_schema["schema"]["required"].append(k)
        json_schema["schema"]["properties"][k] = property_obj
        
    return {"type": "json_schema", "json_schema": json_schema}

def get_openai_json_schema_v3(model: BaseModel, schema_type='function'):
    """
    Converts a Pydantic model into OpenAI function calling compatible format.
    """
    model_name = if_camel_to_snake(model.__name__)
    model_description = model.__doc__ or f"Schema for {model_name}"
    
    function_schema = {
        "name": model_name,
        "description": model_description.strip(),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        },
        "strict": True
    }
    
    for k in model.model_fields:
        annotated_type = model.__annotations__.get(k)
        v = model.model_fields[k]
        if v is None:
            continue
        # If annotated_type is None, use the field's type information from model_fields
        if annotated_type is None:
            annotated_type = v.annotation
        underlying_type = get_underlying_type(annotated_type)
        # If underlying_type is still None, use the field's outer_type
        if underlying_type is None:
            underlying_type = getattr(v, 'outer_type', None) or v.annotation
        property_obj = get_azure_openai_property_schema(underlying_type, v)

        if underlying_type is not annotated_type:
            if type(None) not in get_args(annotated_type):
                function_schema["parameters"]["required"].append(k)
        else:
            function_schema["parameters"]["required"].append(k)
        function_schema["parameters"]["properties"][k] = property_obj
    result = {
        "type": schema_type,
        schema_type: function_schema
    }
    return [result]


def get_azure_openai_property_schema(field_type, field_info):
    # Handle the case when field_type is None
    if field_type is None:
        # Default to string type if we can't determine the type
        return {
            "type": "string",
            "description": field_info.description if hasattr(field_info, "description") else ""
        }
    
    origin = get_origin(field_type)
    if origin is list:
        item_type = get_args(field_type)[0]
        ret = {
            "type": "array",
            "items": get_azure_openai_property_schema(item_type, field_info),
        }
    elif issubclass(field_type, BaseModel):
        ret = get_openai_object_json_schema(field_type)
    else:
        ret = {
            "type": tool_use_type_mapping[field_type.__name__.lower()],
        }
        if field_info.description:
            ret["description"] = field_info.description
        if field_info.examples:
            ret["enum"] = field_info.examples
    # if field_info.json_schema_extra and field_info.json_schema_extra.get("optional", False):
    #     ret["type"] = [ret["type"], "null"]
    return ret

def get_openai_object_json_schema(tool: BaseModel):
    result = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    }
    for k, v in tool.__annotations__.items():
        if v is None:
            continue
        underlying_type = get_underlying_type(v)
        property_obj = get_azure_openai_property_schema(underlying_type, tool.model_fields[k])

        if underlying_type is not v:
            if type(None) not in get_args(v):
                result["required"].append(k)
        else:
            result["required"].append(k)
        result["properties"][k] = property_obj
    return result
