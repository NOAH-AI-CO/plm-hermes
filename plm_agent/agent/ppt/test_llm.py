import asyncio
import json
from .llm import async_stream, async_chat, LLMReq

# tool 获取天气情况
tool_get_weather = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气情况",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如：北京、上海"
                }
            },
            "required": ["city"]
        }
    }
}

# tool 获取股票情况
tool_get_stock = {
    "type": "function",
    "function": {
        "name": "get_stock",
        "description": "获取指定股票代码的股票情况",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "股票代码，例如：000001"
                }
            },
            "required": ["code"]
        }
    }
}

def get_weather(city: str) -> str:
    return f"{city}天气：晴，温度25℃，湿度40%"

def get_stock(code: str) -> str:
    return f"股票{code}：当前价10.23，涨跌幅+0.8%"

def _run_tool(name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return "参数解析失败"
    if name == "get_weather":
        return get_weather(**args)
    if name == "get_stock":
        return get_stock(**args)
    return f"未知工具: {name}"

async def test_chat(model: str):
    """流式聊天"""
    req = LLMReq(
        model=model,
        messages=[{"role": "user", "content": "你好，请介绍一下你自己, 不要超过100字"}]
    )
    print("请求:", end="")
    print(req.to_dict())
    print("回复:", end="")
    async for chunk in async_stream(req):
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

async def test_more_chat(model: str):
    """多轮聊天"""
    messages = [{"role": "user", "content": "你好我叫小明, 请简单介绍一下你自己, 不要超过100字"}]
    req = LLMReq(model=model, messages=messages)
    print("请求:", end="")
    print(req.to_dict())
    print("回复:", end="")
    full_content = ""
    async for chunk in async_stream(req):
        if chunk.choices and chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            print(content, end="", flush=True)
            full_content += content
    print()
    messages.append({"role": "assistant", "content": full_content})
    print("请求:", end="")
    print(req.to_dict())
    print("回复:", end="")
    if i == 0:
        messages.append({"role": "user", "content": "我喜欢打篮球"})
    elif i == 1:
        messages.append({"role": "user", "content": "你还记得我叫什么名字吗？我喜欢什么运动？"})

async def test_struct_output(model: str):
    """JSON输出"""
    print(f"\n\n---------- test03 JSON输出 ---------- {model} ----------")
    req = LLMReq(
        model=model,
        messages=[{"role": "user", "content": "随意编造一个用户信息给我，要求输出格式为json，不要超过100字"}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "user_info",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "xname": {"type": "string"},
                        "xage": {"type": "integer"}
                    },
                    "required": ["xname", "xage"],
                    "additionalProperties": False
                }
            }
        }
    )
    print("请求:", end="")
    print(req.to_dict())
    print("回复:", end="")
    x = ""
    async for chunk in async_stream(req):
        if chunk.choices and chunk.choices[0].delta.content:
            x += chunk.choices[0].delta.content
            print(chunk.choices[0].delta.content, end="", flush=True)
    x = json.loads(x)
    x['xname']
    x['xage']
    print()


async def test_tools(model: str):
    """使用工具"""
    print(f"\n\n---------- test_tools 使用工具 ---------- {model} ----------")
    messages = [{"role": "user", "content": "帮我查一下000001这支股票的情况"}]
    req = LLMReq(model=model, messages=messages, tools=[tool_get_weather, tool_get_stock])
    print("请求:", end="")
    print(f"{req.model} {req.messages}")
    print("回复:", end="")
    result = await async_chat(req)
    message = result.choices[0].message
    if not message.tool_calls:
        print(message.content or "")
        return
    print("工具调用:", end="")
    for tool_call in message.tool_calls:
        if tool_call.function:
            print(f"{tool_call.function.name or ''}{tool_call.function.arguments or ''}", end="", flush=True)
    print()
    messages.append(message.model_dump(exclude_none=True))
    for tool_call in message.tool_calls:
        if tool_call.function and tool_call.id:
            tool_result = _run_tool(tool_call.function.name or "", tool_call.function.arguments or "")
            print(f"工具结果: {tool_result}")
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})
    follow_req = LLMReq(model=model, messages=messages)
    print("回复:", end="")
    async for chunk in async_stream(follow_req):
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

async def test_parallel_tool(model: str):
    """并行使用工具"""
    print(f"\n\n---------- test_parallel_tool 并行使用工具 ---------- {model} ----------")
    messages = [{"role": "user", "content": "帮我查一下北京的天气和000001股票的情况"}]
    req = LLMReq(
        model=model,
        messages=messages,
        tools=[tool_get_weather, tool_get_stock],
        parallel_tool_calls=True
    )
    print("请求:", end="")
    print(f"{req.model} {req.messages}")
    print("回复:", end="")
    result = await async_chat(req)
    message = result.choices[0].message
    if not message.tool_calls:
        print(message.content or "")
        return
    print("工具调用:", end="")
    for tool_call in message.tool_calls:
        if tool_call.function:
            print(f"{tool_call.function.name or ''}{tool_call.function.arguments or ''}", end="", flush=True)
    print()
    messages.append(message.model_dump(exclude_none=True))
    for tool_call in message.tool_calls:
        if tool_call.function and tool_call.id:
            tool_result = _run_tool(tool_call.function.name or "", tool_call.function.arguments or "")
            print(f"工具结果: {tool_result}")
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})
    follow_req = LLMReq(model=model, messages=messages)
    print("回复:", end="")
    async for chunk in async_stream(follow_req):
        if chunk.choices and chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

async def test_all(model: str):
    print('\n\n\n\n\n\n')
    try:
        await test_chat(model)
    except Exception:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!失败")
    try:
        await test_more_chat(model)
    except Exception:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!失败")
    try:
        await test_struct_output(model)
    except Exception:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!失败")
    try:
        await test_tools(model)
    except Exception:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!失败")
    try:
        await test_parallel_tool(model)
    except Exception:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!失败")

async def main():
    await test_all("openai/gpt-4o-mini")
    await test_all("openai/gpt-5")
    await test_all("openai/gpt-5-chat")
    await test_all("openai/gpt-5-mini")
    await test_all("openai/gpt-5-codex")
    await test_all("openai/gpt-5.1")
    await test_all("openai/gpt-5.2")
    await test_all("openai/gpt-5.2-chat")
    await test_all("openai/gpt-5.2-codex")
    await test_all("anthropic/claude-3.5-sonnet") # 不支持并行tools 不支持json输出
    await test_all("anthropic/claude-3.7-sonnet") # 不支持并行tools 不支持json输出
    await test_all("anthropic/claude-sonnet-4") # 不支持json输出
    await test_all("anthropic/claude-sonnet-4.5")
    await test_all("anthropic/claude-haiku-4.5") # 不支持json输出
    await test_all("google/gemini-3-flash-preview")
    await test_all("google/gemini-3.1-pro-preview")
    await test_all("google/gemini-2.5-pro-preview-05-06")
    await test_all("google/gemini-2.5-flash-preview-09-2025")


if __name__ == "__main__":
    asyncio.run(main())