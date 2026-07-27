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
    base_url="http://localhost:8111/v1",
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
        max_tokens=2048,
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
    return full_text_by_page
        
    # with open(pdf_file_path.replace('.pdf','.json'), 'w', encoding='utf-8') as f:
    #     json.dump(full_text_by_page, f, ensure_ascii=False, indent=2)
        
# for root, dirs, files in os.walk("/home/noahai/csco/2025CSCO完全汇总全31本"):
#     pdf_file_path = None
#     for file in files:
#         if file.endswith('.pdf'):
#             if file.replace('.pdf','.json') in files:
#                 print("Skipping already processed PDF:", file)
#                 continue
#             pdf_file_path = os.path.join(root, file)
#         print("Processing PDF:", pdf_file_path)
#         with open('processed_gl_ids.txt', 'a') as f:
#             f.write(f"{pdf_file_path}\n")
#         try:
#             pdf_to_list(pdf_file_path, root)
#             with open('processed_gl_ids.txt', 'a') as f:
#                 f.write(f"Complete gl: {pdf_file_path}\n")
#         except Exception as e:
#             print("Error processing PDF:", pdf_file_path, e)
#             with open('error_gl_ids.txt', 'a') as f:
#                 f.write(f"Error processing gl: {pdf_file_path}: {e}\n")