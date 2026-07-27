import os
import asyncio
import re


# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

import pymupdf

from google import genai
from google.genai.types import HttpOptions
import json
        
client = genai.Client(http_options=HttpOptions(api_version="v1"))

def clean_text(text):
    # Remove control characters like \u0007, \u0003, etc. but keep \n, \r, \t
    # return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text).strip()
    return re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', text)

async def llm_translate(text, target_language='Chinese'):
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"Help me translate the following text to {target_language}, maintaining formatting if possible, only return the translation result:\n\n" + text,
        config={
            "temperature": 0,
        },
    )
    return response.text




    
# print("translate_dict", translate_dict)

async def batch_translate(texts, translate_dict, target_language='Chinese'):
    results = {}
    tasks = []
    texts_to_request = []
    print("batch_translate texts:", texts)
    
    for text in texts:
        if text in translate_dict:
            results[text] = translate_dict[text]
        else:
            tasks.append(llm_translate(text, target_language))
            texts_to_request.append(text)
            
    if tasks:
        translations = await asyncio.gather(*tasks)
        for text, translation in zip(texts_to_request, translations):
            results[text] = translation
            translate_dict[text] = translation
            
    return results

language_mapping = {
    'zh-CN': "Chinese",
    'ko-KR': "Korean",
    'ja-JP': "Japanese",
    'en-US': "English"
    }

async def translate(path='3c.pdf', target_language='zh-CN'):
    
    file_name = os.path.basename(path).split('.')[0]
    print("file_name:", file_name)
    
    translate_dict = {}
    try:
        with open(f"{file_name}-{target_language}-translate.json", "r", encoding="utf-8") as f:
            translate_dict = json.load(f)
    except FileNotFoundError:
        pass
    WHITE = pymupdf.pdfcolor["white"]
    textflags = pymupdf.TEXT_DEHYPHENATE
    if target_language == 'zh-CN':
        target_language_name = language_mapping.get(target_language, 'Chinese')

    doc = pymupdf.open(path)
    
    ocg_xref = doc.add_ocg(target_language_name, on=True)
    
    for page in doc:
        blocks = page.get_text("blocks", flags=textflags)
        
        texts_to_translate = []
        for block in blocks:
            cleaned = clean_text(block[4])
            if cleaned and cleaned not in translate_dict:
                texts_to_translate.append(cleaned)
        
        if texts_to_translate:
            await batch_translate(texts_to_translate, translate_dict, target_language_name)
            
        for block in blocks:
            bbox = block[:4]
            orig_text = clean_text(block[4])
            if not orig_text:
                continue
                
            print("bbox:", bbox)
            # bbox = bbox[0], bbox[1], bbox[2], bbox[3] + (bbox[3] - bbox[1])
            print("orig_text:", orig_text)
            target_text = clean_text(translate_dict[orig_text])
            
            print("target lang text:", target_text)
            page.draw_rect(bbox, color=None, fill=WHITE, oc=ocg_xref)
            
            # Use a large font size and let it scale down to fit the box as much as possible.
            # This ensures the text fills the available space in the rectangle.
            css = "html, body { margin: 0; padding: 0; } * { font-size: 50pt; }"
            page.insert_htmlbox(bbox, target_text, css=css, oc=ocg_xref)

    with open(f"{file_name}-{target_language}-translate.json", "w", encoding="utf-8") as f:
        json.dump(translate_dict, f, ensure_ascii=False, indent=2)
        
    doc.subset_fonts()
    doc.ez_save(f"{file_name}-{target_language}.pdf")
    

if __name__ == "__main__":
    asyncio.run(translate(path='3c.pdf', target_language='zh-CN'))

