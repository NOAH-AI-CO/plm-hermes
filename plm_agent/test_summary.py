from llm.azure_models import GPT5Mini
from llm.gcp_models import Gemini25Pro
from llm.ali_models import Qwen3

llm = GPT5Mini()
# llm = Gemini25Pro()
# llm = Qwen3()
import asyncio

async def test_summary():
    prompt = ""
    with open("test_qwen.txt", "r") as f:
        prompt = f.read()
    gen = llm.stream_call(user_prompt=prompt, temperature=0.3)
    async for chunk in gen:
        print(chunk, end='', flush=True)

asyncio.run(test_summary())