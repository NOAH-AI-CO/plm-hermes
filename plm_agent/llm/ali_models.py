from collections import defaultdict
import inspect
import io
import os
import time
import random
import logging
import datetime

from openai import AsyncOpenAI

from config import api_config
from logging_config import log_id_var, task_id_var
from llm.base_model import BaseLLM
from llm.base_model import CompositeModel
from llm.azure_models import GPT41
from llm.deepseek_models import DeepseekChat

logger = logging.getLogger(__name__)


async def _safe_close_stream(response) -> None:
    """关掉 OpenAI AsyncStream, 兼容不同 SDK / OTel instrumentation 的实现差异。

    Why: opentelemetry-instrumentation-openai-v2 会把 AsyncStream.close 包成
    sync wrapper, 调用后返回 None, 直接 `await response.close()` 会抛
    "object NoneType can't be used in 'await' expression"。新版 OpenAI SDK
    也把清理逻辑迁到了 aclose。这里统一兼容: 优先 aclose, 退回 close;
    返回值若是 awaitable 才 await。
    """
    if response is None:
        return
    try:
        aclose = getattr(response, "aclose", None)
        if aclose is not None:
            ret = aclose()
            if inspect.isawaitable(ret):
                await ret
            return
        close = getattr(response, "close", None)
        if close is None:
            return
        ret = close()
        if inspect.isawaitable(ret):
            await ret
    except Exception:
        logger.exception("[stream_call] response close failed (ignored)")


class Qwen(BaseLLM):

    first_chunk_timeout = 15
    timeout = 30
    extra_params = {}

    def __init__(self, model, **kwargs) -> None:
        self.model = model
        self.extra_params['timeout'] = kwargs.get('timeout', self.timeout)
        if 'max_retries' in kwargs:
            self.extra_params['max_retries'] = kwargs['max_retries']
        if kwargs.get('first_chunk_timeout', None):
            self.first_chunk_timeout = kwargs['first_chunk_timeout']
        super().__init__()
        
    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.3, max_tokens: int = 16384, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        
        if self.__class__.__name__.endswith('R1'):
            messages = history_messages + user_message
        elif sys_prompt != "":
            sys_message = [{"role": "system", "content": sys_prompt}]
            messages = sys_message + history_messages + user_message
        else:
            messages = history_messages + user_message
        
        client = random.choice(self.clients)
        for key in ['system_prompt', 'stream', 'stream_status', 'images']:
            kwargs.pop(key, None)

        print(f"{self.model} Using temperature: {temperature}")
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                # enable_thinking 参数开启思考过程，QwQ 与 Qwen-R1 模型总会进行思考，不支持该参数
                extra_body={"enable_thinking": True if 'tools' not in kwargs else False},
                stream=True,
                stream_options={
                    "include_usage": True
                },
                **kwargs
            )
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warn(f"{self.model} API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e

        string_buffer = io.StringIO()
        reasoning_flag = False
        usage = defaultdict(int)
        connection_time = time.time()
        first_valid_chunk = False
        tool_info = []
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage
                for key, value in usage.__dict__.items():
                    if type(value) == 'int':
                        usage[key] += value
            
            if len(chunk.choices) > 0:
                chunk_content = None
                delta = chunk.choices[0].delta
                content = getattr(delta, 'content', None)
                reasoning_content = getattr(delta, 'reasoning_content', None)

                if reasoning_content is not None and reasoning_content != '':
                    if not reasoning_flag:
                        reasoning_flag = True
                        chunk_content = f"<think>\n{reasoning_content}"
                    else:
                        chunk_content = reasoning_content

                # Get chunk_content, while in the reasoning stream there may be empty chunk, check content is 
                if content is not None and content != '':
                    if reasoning_flag:
                        reasoning_flag = False
                        chunk_content = f"</think>\n{content}"
                    else:
                        chunk_content = content

                if chunk_content:
                    # log first chunk cost time
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True

                    # return chunk content
                    string_buffer.write(chunk_content)
                
                if delta.tool_calls is not None:
                    # log first chunk cost time
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True
                    
                    for tool_call in delta.tool_calls:
                        index = tool_call.index  # 工具调用索引，用于并行调用
                        
                        # 动态扩展工具信息存储列表
                        while len(tool_info) <= index:
                            tool_info.append({})
                        
                        # 收集工具调用ID（用于后续函数调用）
                        if tool_call.id:
                            tool_info[index]['id'] = tool_info[index].get('id', '') + tool_call.id
                        
                        # 收集函数名称（用于后续路由到具体函数）
                        if tool_call.function and tool_call.function.name:
                            tool_info[index]['name'] = tool_info[index].get('name', '') + tool_call.function.name
                        
                        # 收集函数参数（JSON字符串格式，需要后续解析）
                        if tool_call.function and tool_call.function.arguments:
                            if '\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n' in tool_call.function.arguments:
                                raise RuntimeError(f"{self.model} Tool call outputting unlimited line breaks")
                                
                            tool_info[index]['arguments'] = tool_info[index].get('arguments', '') + tool_call.function.arguments

            # break when wait too long
            if not first_valid_chunk:
                if time.time() - connection_time > self.first_chunk_timeout:
                    logger.warn(f"{client.__class__.__name__} first chunk timeout")
                    raise RuntimeError(f'{self.model} first chunk waiting timeout!!!')

        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         tool_info or content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time, **kwargs)
    
        return tool_info or content

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.3, max_tokens: int = 16384, **kwargs):
        call_start_time = datetime.datetime.now()
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        
        if self.__class__.__name__.endswith('R1'):
            messages = history_messages + user_message
        elif sys_prompt != "":
            sys_message = [{"role": "system", "content": sys_prompt}]
            messages = sys_message + history_messages + user_message
        else:
            messages = history_messages + user_message
        
        client = random.choice(self.clients)
        for key in ['system_prompt', 'stream', 'stream_status', 'images']:
            kwargs.pop(key, None)

        print(f"{self.model} Using temperature: {temperature}")
        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                # enable_thinking 参数开启思考过程，QwQ 与 Qwen-R1 模型总会进行思考，不支持该参数
                extra_body={"enable_thinking": True if 'tools' not in kwargs else False},
                stream=True,
                stream_options={
                    "include_usage": True
                },
                **kwargs
            )
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warn(f"{self.model} API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e
        
        string_buffer = io.StringIO()
        reasoning_flag = False
        usage = defaultdict(int)
        connection_time = time.time()
        first_valid_chunk = False
        async for chunk in response:

            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage
                for key, value in usage.__dict__.items():
                    if type(value) == 'int':
                        usage[key] += value
            
            if len(chunk.choices) > 0:
                chunk_content = None
                content = getattr(chunk.choices[0].delta, 'content', None)
                reasoning_content = getattr(chunk.choices[0].delta, 'reasoning_content', None)

                if reasoning_content is not None and reasoning_content != '':
                    if not reasoning_flag:
                        reasoning_flag = True
                        chunk_content = f"<think>\n{reasoning_content}"
                    else:
                        chunk_content = reasoning_content

                # Get chunk_content, while in the reasoning stream there may be empty chunk, check content is 
                if content is not None and content != '':
                    if reasoning_flag:
                        reasoning_flag = False
                        chunk_content = f"</think>\n{content}"
                    else:
                        chunk_content = content

                if chunk_content:
                    # log first chunk cost time
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True

                    # return chunk content
                    string_buffer.write(chunk_content)
                    yield chunk_content

            # break when wait too long
            if not first_valid_chunk:
                if time.time() - connection_time > self.first_chunk_timeout:
                    logger.warn(f"{client.__class__.__name__} first chunk timeout")
                    raise RuntimeError(f'{self.model} first chunk waiting timeout!!!')
            if self.stream_break:
                break
        await _safe_close_stream(response)
        self.stream_break = False

        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time, **kwargs)
    
    async def log_results(self, sys_prompt: str, user_prompt: str, response, content: str, usage: str, start_time = None, **kwargs) -> None:
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.now()
        if not os.path.exists("logs"):
            os.makedirs("logs")
        log_id = log_id_var.get()
        task_id = task_id_var.get()
        date = datetime.datetime.now().strftime("%Y-%m-%d")
        with open(f"logs/open_api_{date}.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{log_id}] [{current_time}] {kwargs}\n")
            log_file.write(f"[{log_id}] [{current_time}] {sys_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {user_prompt}\n")
            log_file.write(f"[{log_id}] [{current_time}] {content}\n{usage}\n")
            if start_time:
                time_delta = end_time - start_time
                formatted_time_delta = f"{time_delta.total_seconds():.2f} seconds"
                log_file.write(f"[{log_id}] Time spent: {formatted_time_delta}\n")
            log_file.write("="*64+"\n")
        with open(f"logs/open_api_usage_{date}.log", "a", encoding="utf-8") as log_file:
            time_delta = f"[{time_delta.total_seconds():.2f}s]" if start_time else ''
            log_file.write(f"[{log_id}] [{current_time}][{task_id}] {time_delta} {usage}\n")
            
    async def generate_stream(self, user_prompt, **kwargs):
        print("generate_stream", self.__class__.__name__)
        async for chunk in self.stream_call(user_prompt=user_prompt, **kwargs):
            yield chunk
        
        
class Qwen3(Qwen):
    
    def __init__(self, **kwargs) -> None:
        super().__init__(model=api_config.QWEN3_MODEL, **kwargs)
        api_keys = (api_config.ALIYUN_BAILIAN_API_KEY).split(',')
        self.clients = [AsyncOpenAI(api_key=api_key, base_url=api_config.QWEN_API_ENDPOINT, **self.extra_params) for api_key in api_keys]


class SiliconFlowQwen3(Qwen):
    
    def __init__(self, **kwargs) -> None:
        super().__init__(model=api_config.SILICONFLOW_QWEN3_MODEL, **kwargs)
        api_keys = (api_config.SILICONFLOW_DEEPSEEK_API_KEYS).split(',')
        self.clients = [AsyncOpenAI(api_key=api_key, base_url=api_config.SILICONFLOW_DEEPSEEK_API_ENDPOINT, **self.extra_params) for api_key in api_keys]

    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", json_mode: bool = False, temperature: float = 1, max_tokens: int= 8192, **kwargs) -> str:
        """
        Asynchronously call the OpenAI API to generate a response.

        Args:
            sys_prompt (str): The system prompt, defaults to an empty string.
            user_prompt (str): The user prompt, defaults to an empty string.
            json_mode (bool): Whether to enable JSON mode, defaults to False.
            temperature (float): The randomness of the generation, defaults to 0.1.
            **kwargs: Additional parameters to pass to the API.

        Returns:
            str: The content of the generated response from the API.
        """
        if 'tools' in kwargs:
            return await super().__call__(sys_prompt=sys_prompt, user_prompt=user_prompt, temperature=temperature, max_tokens=max_tokens, **kwargs)
        call_start_time = datetime.datetime.now()
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages') if 'history_messages' in kwargs else []
        # Qwen don't like system prompt
        messages = history_messages + user_message
        #print("messages", messages)
        client = random.choice(self.clients)
        #so far Qwen don't support images
        kwargs.pop("images", None)
        print(f"{self.model} Using temperature: {temperature}")
        try:
            start_time = time.time()
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                extra_body={"enable_thinking": True if 'tools' not in kwargs else False},
                temperature=temperature,
                max_tokens=8192,
                **kwargs
            )
            end_time = time.time()
            print(f"{self.model} request cost time: {end_time - start_time}")
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warn(f"{self.model} API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e
        await self.log_results(sys_prompt, user_prompt, response,
            response.choices[0].message, f"Model: {self.model}, Temperature: {temperature}, Usage: {response.usage}", call_start_time, **kwargs)

        return response.choices[0].message

class CompositeQwen3(CompositeModel):
    def __init__(self, **params) -> None:
        self.models = [SiliconFlowQwen3(**params), Qwen3(**params), DeepseekChat(**params), GPT41()]
        super().__init__()


# ────────────────────── GLM-5.2 via DashScope ──────────────────────
# 通过百炼 OpenAI 兼容 endpoint 调用智谱 GLM-5.2;
# 思考模式由 extra_body.thinking.type 控制 (enabled/disabled),
# Qwen 父类的 enable_thinking 参数对 GLM 无效, 因此重写 __call__ / stream_call。

# Gemini SDK 特有的 kwargs, GLM 无法识别, 必须在调用前 pop 掉
_GEMINI_ONLY_KWARGS = (
    "response_mime_type",
    "response_schema",
    "thinking_budget",
    "images",
    "system_prompt",
    "stream_status",
    "json_mode",
)


def _strip_code_fence(text: str) -> str:
    """剥掉 ```json ... ``` / ``` ... ``` 包裹。GLM 在 JSON 任务下时常带, 调用方
    直接 json.loads 会失败。只剥最外层的包裹, 不递归。"""
    if not text:
        return text
    s = text.strip()
    if s.startswith("```"):
        # 去掉首行 ``` 或 ```json
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        else:
            return text  # 单行就退出, 不动
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    return s


class _Glm52Base(Qwen):
    """GLM-5.2 共用基类; 子类通过 thinking_mode 决定是否走思考。"""
    # 思考模式可能让首 chunk 很慢, 给它放宽到 60s
    first_chunk_timeout = 60
    timeout = 120
    thinking_mode = "enabled"   # "enabled" / "disabled"
    reasoning_effort = "high"   # 仅在 thinking_mode=enabled 时生效

    def __init__(self, **kwargs) -> None:
        super().__init__(model="glm-5.2", **kwargs)
        api_keys = api_config.QWEN_API_KEYS.split(",")
        self.clients = [
            AsyncOpenAI(api_key=k.strip(), base_url=api_config.QWEN_API_ENDPOINT, **self.extra_params)
            for k in api_keys if k.strip()
        ]

    def _build_extra_body(self, has_tools: bool) -> dict:
        if has_tools or self.thinking_mode == "disabled":
            return {"thinking": {"type": "disabled"}}
        body = {"thinking": {"type": "enabled"}}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _sanitize_kwargs(self, kwargs: dict) -> dict:
        for k in _GEMINI_ONLY_KWARGS:
            kwargs.pop(k, None)
        return kwargs

    async def __call__(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.3, max_tokens: int = 16384, **kwargs) -> str:
        call_start_time = datetime.datetime.now()
        kwargs = self._sanitize_kwargs(kwargs)
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages', [])

        if sys_prompt != "":
            messages = [{"role": "system", "content": sys_prompt}] + history_messages + user_message
        else:
            messages = history_messages + user_message

        client = random.choice(self.clients)
        for key in ['stream', 'stream_status']:
            kwargs.pop(key, None)

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self._build_extra_body('tools' in kwargs),
                stream=True,
                stream_options={"include_usage": True},
                **kwargs
            )
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warn(f"{self.model} API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e

        string_buffer = io.StringIO()
        reasoning_flag = False
        usage = defaultdict(int)
        connection_time = time.time()
        first_valid_chunk = False
        tool_info = []
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage

            if len(chunk.choices) > 0:
                chunk_content = None
                delta = chunk.choices[0].delta
                content = getattr(delta, 'content', None)
                reasoning_content = getattr(delta, 'reasoning_content', None)

                if reasoning_content:
                    if not reasoning_flag:
                        reasoning_flag = True
                        chunk_content = f"<think>\n{reasoning_content}"
                    else:
                        chunk_content = reasoning_content

                if content:
                    if reasoning_flag:
                        reasoning_flag = False
                        chunk_content = f"</think>\n{content}"
                    else:
                        chunk_content = content

                if chunk_content:
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True
                    string_buffer.write(chunk_content)

                if delta.tool_calls is not None:
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True
                    for tool_call in delta.tool_calls:
                        index = tool_call.index
                        while len(tool_info) <= index:
                            tool_info.append({})
                        if tool_call.id:
                            tool_info[index]['id'] = tool_info[index].get('id', '') + tool_call.id
                        if tool_call.function and tool_call.function.name:
                            tool_info[index]['name'] = tool_info[index].get('name', '') + tool_call.function.name
                        if tool_call.function and tool_call.function.arguments:
                            tool_info[index]['arguments'] = tool_info[index].get('arguments', '') + tool_call.function.arguments

            if not first_valid_chunk:
                if time.time() - connection_time > self.first_chunk_timeout:
                    logger.warn(f"{client.__class__.__name__} first chunk timeout")
                    raise RuntimeError(f'{self.model} first chunk waiting timeout!!!')

        content = string_buffer.getvalue()
        string_buffer.close()
        # 去掉 <think>...</think> 块, 业务侧不需要 reasoning 文本
        if '</think>' in content:
            content = content.split('</think>', 1)[1].lstrip('\n')
        elif content.startswith('<think>'):
            content = ''
        # 兼容调用方 (e.g. guideline/search.py) 直接 json.loads —
        # 剥掉 markdown code fence 包裹
        content = _strip_code_fence(content)
        await self.log_results(sys_prompt, user_prompt, response,
                         tool_info or content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time, **kwargs)
        return tool_info or content

    async def stream_call(self, sys_prompt: str = "", user_prompt: str = "", temperature: float = 0.3, max_tokens: int = 16384, **kwargs):
        call_start_time = datetime.datetime.now()
        kwargs = self._sanitize_kwargs(kwargs)
        user_message = [{"role": "user", "content": user_prompt}]
        history_messages = kwargs.pop('history_messages', [])

        if sys_prompt != "":
            messages = [{"role": "system", "content": sys_prompt}] + history_messages + user_message
        else:
            messages = history_messages + user_message

        client = random.choice(self.clients)
        for key in ['stream', 'stream_status']:
            kwargs.pop(key, None)

        try:
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=self._build_extra_body('tools' in kwargs),
                stream=True,
                stream_options={"include_usage": True},
                **kwargs
            )
        except Exception as e:
            error_detail = self.get_error_detail(exception=e)
            logger.warn(f"{self.model} API Error Details: {error_detail}")
            await self.log_results(sys_prompt, user_prompt, error_detail,
                                   f"Model: {self.model}, error: {error_detail}", call_start_time, **kwargs)
            raise e

        string_buffer = io.StringIO()
        usage = defaultdict(int)
        connection_time = time.time()
        last_activity = connection_time
        first_valid_chunk = False
        # stream_call 只 yield 正式 content, reasoning 不外泄给业务流
        async for chunk in response:
            if hasattr(chunk, 'usage') and chunk.usage:
                usage = chunk.usage

            if len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                content = getattr(delta, 'content', None)
                # thinking 模型在吐正文前会先流数十秒 reasoning_content; 只要有任何
                # token 就说明连接正常, 刷新活跃时间, 否则会把"正在思考"误判为首字超时。
                if getattr(delta, 'reasoning_content', None) or content:
                    last_activity = time.time()
                if content:
                    if not first_valid_chunk:
                        logger.info(f"{self.model} client first chunk cost {time.time() - connection_time}")
                    first_valid_chunk = True
                    string_buffer.write(content)
                    yield content

            if not first_valid_chunk:
                if time.time() - last_activity > self.first_chunk_timeout:
                    logger.warn(f"{client.__class__.__name__} first chunk timeout")
                    raise RuntimeError(f'{self.model} first chunk waiting timeout!!!')
            if self.stream_break:
                break
        await _safe_close_stream(response)
        self.stream_break = False

        content = string_buffer.getvalue()
        string_buffer.close()
        await self.log_results(sys_prompt, user_prompt, response,
                         content, f"Model: {self.model}, Temperature: {temperature}, Usage: {usage}", call_start_time, **kwargs)


class Glm52Pro(_Glm52Base):
    """GLM-5.2 Pro: thinking=enabled + reasoning_effort=high, 用于诊断/检查/治疗主报告。"""
    thinking_mode = "enabled"
    reasoning_effort = "high"


class Glm52Flash(_Glm52Base):
    """GLM-5.2 Flash: thinking=disabled, 用于结构化抽取等轻量任务。"""
    thinking_mode = "disabled"
    reasoning_effort = None
