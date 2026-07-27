from __future__ import annotations
from typing import Any, List, Dict, Optional, List, Optional, List, Dict, Iterable, Any, AsyncGenerator, Type, cast
from config import api_config
from copy import deepcopy
from pydantic import BaseModel
from openai import AsyncStream, AsyncOpenAI
from openai.types import ReasoningEffort
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam, ChatCompletionToolChoiceOptionParam, ChatCompletionToolUnionParam
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
from openai.types.chat.completion_create_params import ResponseFormat


_async_client = None


# -------------------------------------------------- x --------------------------------------------------

def _get_async_client() -> AsyncOpenAI:
    # 只是为了延迟加载，不在意到底创建了几个 _async_client
    global _async_client
    if _async_client is None:
        # api_key = os.environ.get("OPENROUTER_API_KEY")
        api_key = api_config.OPENROUTER_API_KEY
        _async_client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    return _async_client


class LLMReq(BaseModel):
    """
    LLM 参数，字段与 openai 参数完全一致，model 请选择 llm-info.txt 中的 Model ID
    """
    model: str
    messages: List[ChatCompletionMessageParam]
    temperature: Optional[float] = None
    reasoning_effort: Optional[ReasoningEffort] = None
    response_format: Optional[ResponseFormat] = None
    tools: Optional[Iterable[ChatCompletionToolUnionParam]] = None
    tool_choice: Optional[ChatCompletionToolChoiceOptionParam] = None
    parallel_tool_calls: Optional[bool] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    timeout: Optional[float] = None
    
    # # 最好别用，请保持简单，保持傻逼
    # audio: Optional[ChatCompletionAudioParam]
    # frequency_penalty: Optional[float]
    # function_call: Optional[FunctionCall]
    # functions: Optional[Iterable[Function]]
    # logit_bias: Optional[Dict[str, int]]
    # logprobs: Optional[bool]
    # metadata: Optional[Any]
    # modalities: Optional[List[Literal['text', 'audio']]]
    # n: Optional[int]
    # prediction: Optional[ChatCompletionPredictionContentParam]
    # presence_penalty: Optional[float]
    # prompt_cache_key: Optional[str]
    # prompt_cache_retention: Optional[Literal['in-memory', '24h']]
    # safety_identifier: Optional[str]
    # seed: Optional[int]
    # service_tier: Optional[Literal['auto', 'default', 'flex', 'scale', 'priority']]
    # stop: Optional[SequenceNotStr[str]]
    # store: Optional[bool]
    # stream_options: Optional[ChatCompletionStreamOptionsParam]
    # top_logprobs: Optional[int]
    # top_p: Optional[float]
    # user: Optional[str]
    # verbosity: Optional[Literal['low', 'medium', 'high']]
    # web_search_options: Optional[Any]
    # extra_headers: Optional[Headers]
    # extra_query: Optional[Query]
    # extra_body: Optional[Body]
    
    class Config:
        arbitrary_types_allowed = True
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为dict，给openai的底层函数直接解析这个dict即可"""
        return self.model_dump(exclude_none=True, exclude_unset=True)


def _add_routing_logic(req_dict: Dict[str, Any], model_name: str):
    """
    Google 模型，强制指定 Google Vertex 为提供商
    """
    if model_name.startswith("google/"):
        req_dict['extra_body'] = {
            "provider": {
                "order": ["Google"],
                "allow_fallbacks": False 
            }
        }


async def async_stream(req: LLMReq) -> AsyncGenerator[ChatCompletionChunk, None]:
    """流式访问LLM，返回值与 openai 完全 TMD 一致"""
    req_dict = req.to_dict()
    req_dict['stream'] = True
    req_dict['stream_options'] = {"include_usage": True}
    # _add_routing_logic(req_dict, req.model)
    client = _get_async_client()
    stream = await client.chat.completions.create(**req_dict)
    stream = cast(AsyncStream[ChatCompletionChunk], stream)
    async for chunk in stream:
        try:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
                cached_tokens = getattr(chunk.usage.prompt_tokens_details, 'cached_tokens', 0) if chunk.usage.prompt_tokens_details else 0
                # print(f"输入token: {input_tokens}, 输出token: {output_tokens}, 缓存token: {cached_tokens}")
        except Exception:
            pass

        yield chunk

async def async_chat(req: LLMReq) -> ChatCompletion:
    """非流式访问LLM，返回值与 openai 完全一致"""
    req_dict = req.to_dict()
    # _add_routing_logic(req_dict, req.model)
    client = _get_async_client()
    result = await client.chat.completions.create(**req_dict)
    return result


# -------------------------------------------------- messages --------------------------------------------------


def content_pdf(filename: str, pdf_base64_data: str) -> dict:
    data_url = f"data:application/pdf;base64,{pdf_base64_data}"
    return {"type": "file", "file": {"filename": filename, "file_data": data_url}}

def content_image(image_base64_data: str, mime_type: str) -> dict:
    return {"type": "image_url","image_url": {"url": f"data:{mime_type};base64,{image_base64_data}"}}

def content_text(text: str) -> dict:
    return {"type": "text", "text": text}

def role_user(content: list[dict] | str) -> dict:
    return {"role": "user", "content": content}

def role_assistant(content: str, tool_calls: list[dict] = None) -> dict:
    if tool_calls:
        x_tool_calls = []
        for tool_call in tool_calls:
            x_tool_calls.append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                }
            })
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": x_tool_calls
        }
    else:
        return {
            "role": "assistant",
            "content": content
        }

def role_system(content: str) -> dict:
    return {"role": "system", "content": content}

def role_tool(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


# -------------------------------------------------- strip llm raw text --------------------------------------------------


def strip_llm_json(raw: str) -> str:
    if raw.startswith("```json"):
        raw = raw[len("```json") :]
    if raw.startswith("```"):
        raw = raw[len("```") :]
    if raw.endswith("```"):
        raw = raw[: -len("```")]
    return raw.strip()


def strip_llm_python(raw: str) -> str:
    if raw.startswith("```python"):
        raw = raw[len("```python") :]
    if raw.startswith("```"):
        raw = raw[len("```") :]
    if raw.endswith("```"):
        raw = raw[: -len("```")]
    return raw.strip()


def pydantic_to_response_format(model_cls: Type[BaseModel], schema_name: str | None = None) -> dict:
    schema = deepcopy(model_cls.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
                for sub in node.get("properties", {}).values():
                    walk(sub)

            for key in ("$defs", "definitions"):
                if key in node and isinstance(node[key], dict):
                    for sub in node[key].values():
                        walk(sub)

            for key in ("items", "anyOf", "oneOf", "allOf"):
                value = node.get(key)
                if isinstance(value, dict):
                    walk(value)
                elif isinstance(value, list):
                    for sub in value:
                        walk(sub)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)

    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name or model_cls.__name__,
            "strict": True,
            "schema": schema,
        },
    }


# -------------------------------------------------- pydantic --------------------------------------------------

def _resolve_json_pointer(root: dict[str, Any], ref: str) -> Any:
    """解析本地 JSON 指针引用，例如 '#/$defs/Address'。"""
    if not ref.startswith("#/"):
        raise ValueError(f"Only local JSON refs are supported, got: {ref!r}")

    current: Any = root

    for raw_part in ref[2:].split("/"):
        # JSON Pointer unescaping
        part = raw_part.replace("~1", "/").replace("~0", "~")

        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Cannot resolve JSON ref {ref!r}; missing part {part!r}")

        current = current[part]

    return current


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """将本地 $ref 内联展开，并删除 $defs/definitions。

    Pydantic 常生成类似结构: 

        {
            "$defs": {
                "Address": {...}
            },
            "properties": {
                "address": {"$ref": "#/$defs/Address"}
            }
        }

    本函数把 $ref 展开为内联 schema，对多 model 场景更安全。

    故意拒绝递归 schema；LLM 工具 schema 应避免自引用结构。
    """
    root = deepcopy(schema)

    def resolve(node: Any, seen_refs: tuple[str, ...] = ()) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]

                if ref in seen_refs:
                    chain = " -> ".join((*seen_refs, ref))
                    raise ValueError(f"Recursive $ref detected: {chain}")

                resolved = deepcopy(_resolve_json_pointer(root, ref))

                # Preserve useful sibling fields beside $ref, such as description.
                siblings = {k: v for k, v in node.items() if k != "$ref"}

                if siblings:
                    if not isinstance(resolved, dict):
                        raise ValueError(f"Cannot merge siblings into non-object ref: {ref!r}")
                    resolved.update(siblings)

                return resolve(resolved, (*seen_refs, ref))

            return {
                k: resolve(v, seen_refs)
                for k, v in node.items()
                if k not in {"$defs", "definitions"}
            }

        if isinstance(node, list):
            return [resolve(item, seen_refs) for item in node]

        return node

    return resolve(root)


def _strip_keys_recursive(schema: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    """递归删除指定键"""
    schema = deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: walk(v)
                for k, v in node.items()
                if k not in keys
            }

        if isinstance(node, list):
            return [walk(item) for item in node]

        return node

    return walk(schema)


def _simplify_nullable_anyof(schema: dict[str, Any]) -> dict[str, Any]:
    """将简单可空 anyOf 转为 type 数组。

    例如: 

        {"anyOf": [{"type": "integer"}, {"type": "null"}]}

    变为: 

        {"type": ["integer", "null"]}

    若父节点尚未定义，会从非 null 分支保留 description/title 等元数据。
    """
    schema = deepcopy(schema)

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                if isinstance(value, (dict, list)):
                    node[key] = walk(value)

            any_of = node.get("anyOf")

            if isinstance(any_of, list) and len(any_of) >= 2:
                types: list[Any] = []
                metadata: dict[str, Any] = {}
                can_simplify = True

                for item in any_of:
                    if not isinstance(item, dict):
                        can_simplify = False
                        break

                    item_keys = set(item.keys())

                    # Keep this intentionally conservative.
                    # Complex anyOf branches should remain anyOf.
                    allowed_keys = {
                        "type",
                        "description",
                        "title",
                    }

                    if not item_keys.issubset(allowed_keys) or "type" not in item:
                        can_simplify = False
                        break

                    item_type = item["type"]

                    if isinstance(item_type, list):
                        types.extend(item_type)
                        is_null_branch = set(item_type) == {"null"}
                    else:
                        types.append(item_type)
                        is_null_branch = item_type == "null"

                    if not is_null_branch:
                        for meta_key in ("description", "title"):
                            if meta_key in item and meta_key not in node:
                                metadata[meta_key] = item[meta_key]

                if can_simplify and "null" in types:
                    deduped_types: list[Any] = []

                    for t in types:
                        if t not in deduped_types:
                            deduped_types.append(t)

                    node.pop("anyOf", None)
                    node["type"] = deduped_types

                    for k, v in metadata.items():
                        node.setdefault(k, v)

            return node

        if isinstance(node, list):
            return [walk(item) for item in node]

        return node

    return walk(schema)


def _add_additional_properties_false(schema: dict[str, Any]) -> dict[str, Any]:
    """为每个 object schema 递归设置 additionalProperties=false。"""
    schema = deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            is_object = node.get("type") == "object" or "properties" in node

            if is_object:
                node.setdefault("type", "object")
                node["additionalProperties"] = False

                properties = node.get("properties")

                if isinstance(properties, dict):
                    for sub in properties.values():
                        walk(sub)

            for key in (
                "items",
                "prefixItems",
                "anyOf",
                "oneOf",
                "allOf",
                "not",
                "if",
                "then",
                "else",
            ):
                value = node.get(key)

                if isinstance(value, dict):
                    walk(value)
                elif isinstance(value, list):
                    for sub in value:
                        walk(sub)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return schema


def _force_required_all_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """递归将 object 的每个 property 都列入 required。

    对 OpenRouter / OpenAI 兼容的 strict schema，较稳妥的写法是: 

    - 所有 property 都出现在 required 中
    - 可选语义用可空 type 表示，例如 {"type": ["string", "null"]}
    """
    schema = deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            is_object = node.get("type") == "object" or "properties" in node

            if is_object:
                properties = node.get("properties")

                if isinstance(properties, dict):
                    node["required"] = list(properties.keys())

                    for sub in properties.values():
                        walk(sub)

            for key in (
                "items",
                "prefixItems",
                "anyOf",
                "oneOf",
                "allOf",
            ):
                value = node.get(key)

                if isinstance(value, dict):
                    walk(value)
                elif isinstance(value, list):
                    for sub in value:
                        walk(sub)

        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return schema


def _pydantic_to_openrouter_schema(
    model_cls: Type[BaseModel],
    *,
    by_alias: bool = True,
    strict: bool = True,
    inline_ref: bool = True,
    strip_validation_keywords: bool = True,
) -> dict[str, Any]:
    """将 Pydantic 模型转为 OpenRouter / OpenAI 兼容的 JSON Schema。

    此 schema 用于: 

    - tools[].function.parameters
    - response_format.json_schema.schema

    参数: 
        model_cls: Pydantic BaseModel 子类。

        by_alias: JSON Schema 中是否使用 Pydantic 字段别名。

        strict: 为 True 时递归执行: 
            - 设置 additionalProperties=false
            - 将所有 property 加入 required
            可选字段应标成可空，例如 value: str | None = None

        inline_ref: 为 True 时内联 $defs/definitions 中的本地 $ref。

        strip_validation_keywords: 为 True 时删除可移植性较差的 JSON Schema
            校验关键字；多供应商 OpenRouter 时建议开启。
            若只面向单一模型且需保留 minimum/maxLength/pattern 等约束，可置为 False。
    """
    if not isinstance(model_cls, type) or not issubclass(model_cls, BaseModel):
        raise TypeError("model_cls must be a Pydantic BaseModel subclass")

    schema = deepcopy(
        model_cls.model_json_schema(
            by_alias=by_alias,
            ref_template="#/$defs/{model}",
        )
    )

    if inline_ref:
        schema = _inline_refs(schema)

    schema = _simplify_nullable_anyof(schema)
    schema = _add_additional_properties_false(schema)

    if strict:
        schema = _force_required_all_properties(schema)

    keys_to_strip: set[str] = set()


    strip_keys = {
        # Noisy / commonly problematic
        "title",
        "default",
        "examples",
        "example",

        # Composition keywords: portability is poor across providers
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",

        # Validation keywords: useful for app-side validation,
        # but less portable across OpenRouter providers/models.
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "patternProperties",
        "unevaluatedProperties",
        "propertyNames",
        "minProperties",
        "maxProperties",
        "unevaluatedItems",
        "contains",
        "minContains",
        "maxContains",
        "minItems",
        "maxItems",
        "uniqueItems",
    }


    if strip_validation_keywords:
        keys_to_strip.update(strip_keys)
    else:
        # Even when preserving validation keywords, these two are usually just noise
        # and can cause avoidable compatibility issues.
        keys_to_strip.update({"title", "default"})

    if keys_to_strip:
        schema = _strip_keys_recursive(schema, keys_to_strip)

    return schema


def to_openrouter_tool(
    model_cls: Type[BaseModel],
    *,
    name: str,
    description: str,
    strict: bool = True,
    by_alias: bool = True,
    strip_validation_keywords: bool = True,
) -> dict[str, Any]:
    """构造 OpenRouter /chat/completions 的 tool 定义。

    在需要模型调用函数/工具时使用。

    适用于 openai/、google/、anthropic/、deepseek/、meta-llama/ 等
    及任意支持 tool calling 的 OpenRouter 模型。
    """
    parameters = _pydantic_to_openrouter_schema(
        model_cls,
        by_alias=by_alias,
        strict=strict,
        strip_validation_keywords=strip_validation_keywords,
    )

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": strict,
            "parameters": parameters,
        },
    }


def to_openrouter_response_format(
    model_cls: Type[BaseModel],
    *,
    name: str | None = None,
    strict: bool = True,
    by_alias: bool = True,
    strip_validation_keywords: bool = True,
) -> dict[str, Any]:
    """构造 OpenRouter /chat/completions 的结构化 JSON response_format。

    在需要助手正文本体为 JSON（而非走 tool 调用）时使用。
    """
    schema = _pydantic_to_openrouter_schema(
        model_cls,
        by_alias=by_alias,
        strict=strict,
        strip_validation_keywords=strip_validation_keywords,
    )

    return {
        "type": "json_schema",
        "json_schema": {
            "name": name or model_cls.__name__,
            "strict": strict,
            "schema": schema,
        },
    }