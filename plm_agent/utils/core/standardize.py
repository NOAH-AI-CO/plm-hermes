import json
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from agent.core.schema import BaseResponse

def standardize_yield(func):
    async def wrapper(*args, **kwargs):
        async for result in func(*args, **kwargs):
            res = ""
            if type(result) == ChatCompletionMessage or isinstance(result, BaseResponse):    
                res = json.dumps(result.model_dump(), ensure_ascii=False)
            elif type(result) == dict or type(result) == list:
                res = json.dumps(result, ensure_ascii=False)
            elif type(result) == str:
                res = result
            else:
                res = str(result)
            yield f"{res}\n"
    return wrapper

def standardize_yield_wo_dump(func):
    async def wrapper(*args, **kwargs):
        async for result in func(*args, **kwargs):
            res = ""
            if type(result) == ChatCompletionMessage or isinstance(result, BaseResponse):
                res = result.model_dump()
            elif type(result) in [dict,list,str]:
                res = result
            else:
                res = str(result)
            yield res
    return wrapper