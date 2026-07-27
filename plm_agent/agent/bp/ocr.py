from pdf2image import convert_from_path
from io import BytesIO
import base64
import time
from openai import OpenAI
from PIL import Image
import json
import os

# vllm serve deepseek-ai/DeepSeek-OCR --logits_processors vllm.model_executor.models.deepseek_ocr:NGramPerReqLogitsProcessor --no-enable-prefix-caching --mm-processor-cache-gb 0

client = OpenAI(
    api_key="EMPTY",
    base_url="http://136.117.67.190:8111/v1",
    timeout=3600
)

def image_to_txt(img_base64):
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{img_base64}"
                    }
                },
                {
                    "type": "text",
                    "text": "Free OCR."
                }
            ]
        }
    ]

    start = time.time()
    response = client.chat.completions.create(
        model="deepseek-ai/DeepSeek-OCR",
        messages=messages,
        max_tokens=2040,
        temperature=0.0,
        extra_body={
            "skip_special_tokens": False,
            # args used to control custom logits processor
            "vllm_xargs": {
                "ngram_size": 30,
                "window_size": 90,
                # whitelist: <td>, </td>
                "whitelist_token_ids": [128821, 128822],
            },
        },
    )
    print(f"Response costs: {time.time() - start:.2f}s")
    print(f"Generated text: {response.choices[0].message.content}")
    return response.choices[0].message.content

# Convert the PDF pages to a list of Pillow Image objects
def pdf_to_list(path):
    pages = convert_from_path(path)

    # Save each page as a JPEG file
    # Store each page image in memory as base64 strings
    image_base64_list = []
    for i, page in enumerate(pages):
        buffer = BytesIO()
        page.save(buffer, format='JPEG')
        buffer.seek(0)
        base64_str = base64.b64encode(buffer.read()).decode('utf-8')
        image_base64_list.append(base64_str)

    print("PDF converted to base64 encoded JPG images successfully!")

    full_text_by_page = []

    for img_base64 in image_base64_list:
        text = image_to_txt(img_base64)
        full_text_by_page.append(text)
        
    with open(path.replace('.pdf','.json'), 'w', encoding='utf-8') as f:
        json.dump(full_text_by_page, f, ensure_ascii=False, indent=2)
        
# pdf_to_list("/Users/andy/repos/NoahAgent/noah_agent/outputs3/iit2.pdf")


