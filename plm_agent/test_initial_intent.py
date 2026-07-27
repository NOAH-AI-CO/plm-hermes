from math import prod
from pydantic import BaseModel
from pydantic.fields import FieldInfo
from tools.human_in_loop.planning.schema import WebSearchInputSchema
from openai.types.chat import ChatCompletionTokenLogprob
from openai.types.chat.chat_completion import ChoiceLogprobs
from utils.core.get_json_schema import get_openai_json_schema, get_openai_json_schema_v2
from fastapi.responses import JSONResponse, StreamingResponse
from agent.human_in_loop.intent import IntentAgent
    
body1 = {
    "history_messages": [{"role": "user", "content": "You're a helpful assistant. You speak in Chinese."}],
    "user_prompt": "Hi! Can you show me the weather in Beijing on 2024-10-02?",
    "agent": "chat"
}

body2 = {
    "history_messages": [],
    "user_prompt": "What is the best treatment for systemic lupus?",
    "agent": "chat"
}

body3 = {
    "history_messages": [],
    "user_prompt": "What is the best treatment for breast cancer and whats the weather in Beijing like?", 
    "agent": "chat"
}

body4 = {
    "history_messages": [],
    "user_prompt": "Search all phase I and II results for obesity drugs and tell me which drug is the best-in-disease",
    "agent": "chat",
    "tool_selected": "Clinical-Trial-Result-Analysis",
}
    
import asyncio

async def test():
    agent = IntentAgent()
    data = dict(body4)
    data.pop('agent')
    
    res = StreamingResponse(agent.start(**data), media_type='text/event-stream')
    async for chunk in res.body_iterator:
        print("chunk", chunk)
        
asyncio.run(test())

# print(get_openai_json_schema_v2(WebSearchInputSchema))


# cl = ChoiceLogprobs(content=[ChatCompletionTokenLogprob(token='{"', bytes=[123, 34], logprob=-1.8624639e-06, top_logprobs=[]), ChatCompletionTokenLogprob(token='source', bytes=[115, 111, 117, 114, 99, 101], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='":"', bytes=[34, 58, 34], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='N', bytes=[78], logprob=-0.16064134, top_logprobs=[]), ChatCompletionTokenLogprob(token='CC', bytes=[67, 67], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='N', bytes=[78], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='-G', bytes=[45, 71], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='uid', bytes=[117, 105, 100], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='elines', bytes=[101, 108, 105, 110, 101, 115], logprob=0.0, top_logprobs=[]), ChatCompletionTokenLogprob(token='"}', bytes=[34, 125], logprob=-5.025915e-05, top_logprobs=[])], refusal=None)
# for logprob_obj in cl.content:
#     logprob = logprob_obj.logprob
#     print(logprob_obj)
    
# print(sum([logprob_obj.logprob for logprob_obj in cl.content])/len(cl.content))

# # Convert log probability to probability using exponential function
# probabilities = [2.718281828459045 ** logprob_obj.logprob for logprob_obj in cl.content]
# print(prod(probabilities))

# probabilities = [2.718281828459045 ** -0.16064134]
# print(prod(probabilities))