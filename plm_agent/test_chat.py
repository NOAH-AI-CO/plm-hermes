from main import chat_api
    
body = {
    "history_messages":[{"role":"user", "content":"You're a helpful assistant. You speak in Chinese."}],
    "user_prompt":"Hi! Can you show me the weather in Beijing on 2024-10-02?",
    "agent":"chat"
}
    
import asyncio

async def test():
    res = await chat_api(body)
    print("res", res)
    async for chunk in res.body_iterator:
        print("chunk", chunk)
asyncio.run(test())

