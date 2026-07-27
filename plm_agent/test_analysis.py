from main import chat_api
from utils.catalyst.technical_analysis import draw_technical_plot
import base64
import asyncio

ticker = "NFLX"
    
body = {
    "user_prompt": "Here's stock market chart info for a stock, can you provide a technical analysis?",
    "agent": "technical_analysis",
    "images": [draw_technical_plot(ticker)]
}
    
async def test():
    res = await chat_api(body)
    print("res", res)
    async for chunk in res.body_iterator:
        print("chunk", chunk)
        
asyncio.run(test())

# async def main():
#     tasks = [test() for _ in range(21)]
#     await asyncio.gather(*tasks)
        
# asyncio.run(main())

# # Function to encode the image
# def encode_image(image_path):
#   with open(image_path, "rb") as image_file:
#     return base64.b64encode(image_file.read()).decode('utf-8')

# # Path to your image
# image_path = "full_plot.jpeg"

# # Getting the base64 string
# base64_image = encode_image(image_path)
