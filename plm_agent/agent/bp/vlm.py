#!/usr/bin/env python3
import json
import os
import re
import base64
import asyncio
from openai import AsyncOpenAI
from config import api_config

# Initialize OpenAI client with Aliyun Dashscope
client = AsyncOpenAI(
    api_key=api_config.ALIYUN_BAILIAN_API_KEY,  
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

detailed_text_map = {0: '请提取这个图片的描述，返回文本尽量简洁概要。', 
                     1: '请提取这个图片的描述，返回文本。', 
                     2: '请提取这个图片的描述，返回文本尽量详实完整。', 
                     3: "请提取并描述这张图片的内容，返回文本。\n\n仅对以下类别做详尽描述：图表/数据可视化（说明图表类型、坐标轴与单位、趋势、比例、对比、极值、结论等）、纯文字内容、医疗影像（病灶、结构、标注等）。\n\n照片、示意图、形状、装饰图等非信息类图片则用一两句话概括主体即可，不要展开细节。", 
                     4: "这是医药公司商业计划书(BP)和尽职调查(DD)报告的图片处理任务。请先判断图片是否与医药/投资/商业相关。\n\n输出格式：先输出类型标签（如[图表]、[文字]、[医疗影像]、[装饰]），再输出描述内容。\n\n<需精读> 图表/数据可视化：直接提取关键要点、核心趋势、重要结论，不要逐项描述所有数据点。重点关注：主要趋势方向、关键拐点、显著差异/对比、极值、结论性信息。\n\n<需精读> 纯文字内容、医疗影像、临床数据图表：提取所有关键信息（文字内容、病灶、结构、标注、数据等）。\n\n<粗略提取> 示意图、流程图、架构图：用1-2句话概括主体，不超过30字。\n\n<忽略> 纯装饰图、logo、无关照片：直接返回\"[装饰]装饰图，无需描述\"或空字符串，不要生成其他内容。\n\n请根据图片实际内容智能判断类别，并按上述格式和详细程度要求输出。"
                     }

def find_image_references(parsed_pages):
    """Find all image references in markdown file."""
    # Pattern: ![](images/filename.jpg)
    pattern = r'!\[\]\(images/([a-f0-9]+\.jpg)\)'
    matches = re.finditer(pattern, parsed_pages)
    
    return [(m.group(0), m.group(1), m.start(), m.end()) for m in matches]

async def image_to_base64(image_path):
    """Convert image file to base64 string."""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')

async def send_to_vlm(image_base64, detailed=2):
    """Send image to VLM and get text response."""
    print(f"Sending image to VLM... (Detailed Lvl: {detailed})")
    print(f"Image base64: {image_base64[:100]}")
    try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                completion = await client.chat.completions.create(
                    model="qwen3-vl-plus",
                    messages=[
                    {
                        "role": "user",
                        "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                            "url": f"{image_base64}"
                            },
                        },
                        {
                            "type": "text", 
                            "text": f"{detailed_text_map.get(detailed, '请提取这个图片的描述，返回文本。')}" 
                        },
                        ],
                    }
                    ],
                    temperature=0
                )
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"Retry attempt {attempt + 1}/{max_retries}, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    raise
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Error sending to VLM: {e[:100]}")
        return None

async def process_image(i, total, markdown_ref, image_filename, image_base64, detailed):
    """Process a single image and return replacement tuple."""
    
    if not image_base64:
        print(f"  [{i}/{total}] ❌ Image not found: {image_filename}")
        return None
    
    print(f"  [{i}/{total}] Processing {image_filename}...")
    
    try:
        # Send to VLM
        text_content = await send_to_vlm(image_base64, detailed=detailed)
        
        if text_content:
            print(f"    ✓ Extracted text ({len(text_content)} chars)")
            return (markdown_ref, "Image[" + text_content + "]")
        else:
            print(f"    ❌ Failed to get text from VLM")
            return None
    except Exception as e:
        print(f"    ❌ Error: {str(e)[:100]}")
        return None

async def process_markdown_images(parsed_pages, images_dict, detailed=2):
    """Process all images in markdown file in batches of 300."""
    # Find all image references
    print("Finding image references...")
    updated_pages = []
    tasks = []
    references = []
    for page in parsed_pages:
        references.extend(find_image_references(page))
        
    if not references:
        print("No images found to process")
        return parsed_pages
    
    replacements = []
        
    # Process images in batches of 300
    total_refs = len(references)
        
            
    # Process batch concurrently
    tasks.extend([
        process_image(i + 1, total_refs, markdown_ref, image_filename, images_dict.get(image_filename, None), detailed=detailed)
        for i, (markdown_ref, image_filename, start, end) in enumerate(references)
    ])
        
    batch_replacements = [r for r in await asyncio.gather(*tasks) if r is not None]
    replacements.extend(batch_replacements)
    
    # Apply replacements
    print(f"\nApplying {len(replacements)} replacements...")
    for page in parsed_pages:
        for old, new in replacements:
            page = page.replace(old, new)
        updated_pages.append(page)
    
    print(f"✓ Updated parsed_pages with extracted image texts")
    print(f"Replaced {len(replacements)} image references with text")
    return updated_pages
    

if __name__ == "__main__":
    # Target file and directory
    bp_md = "/Users/andy/repos/NoahAgent/noah_agent/agent/bp/BP.md"
    images_dir = "/Users/andy/repos/NoahAgent/noah_agent/agent/bp/images"
    
    images_dict = {}
    
    asyncio.run(process_markdown_images(bp_md, images_dict))
