import os
import time
import json
from typing import List

import tiktoken


# 拼接出 gcp_key.json 的绝对路径
gcp_key_path = "/Users/andy/repos/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"

from agent.iit.v3.guideline_prompts import toc_reader_prompt, toc_reader_by_query_prompt, toc_reader_by_query_batch_prompt
import asyncio

# llm = DeepseekChat()

from google import genai
from google.genai.types import HttpOptions
from google.genai import types
import logging

logger = logging.getLogger(__name__)

section_selection_schema = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "section": {"type": "STRING"},
            "page_range": {"type": "STRING"},
        },
        "required": ["section", "page_range"]
    }
}

guideline_selection_schema = {
    "type": "ARRAY",
    "items": {
        "type": "STRING",
    }
}

# 批量选章节返回结构：每条指南对应一项，含 guideline_id 和 sections 列表
batch_section_selection_schema = {
    "type": "OBJECT",
    "properties": {
        "results": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "guideline_id": {"type": "STRING"},
                    "sections": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "section": {"type": "STRING"},
                                "page_range": {"type": "STRING"},
                            },
                            "required": ["section", "page_range"],
                        },
                    },
                },
                "required": ["guideline_id", "sections"],
            },
        },
    },
    "required": ["results"],
}

# async def read_toc_v0():
#     start = time.time()
#     iit_text = ""
#     with open("/home/noahai/iit_plan.json", "rb") as f:
#         import json
#         iit_text = json.load(f)
#         print("Loaded JSON with", len(iit_text), "pages")
#         iit_text = "\n".join(iit_text)
        
#     client = genai.Client(http_options=HttpOptions(api_version="v1"))
#     response = client.models.generate_content(
#         model="gemini-2.5-pro",
#         contents=toc_reader_prompt.format(iit_text=iit_text, guideline_toc=csco_toc_bc),
#         config={
#             "response_mime_type": "application/json",
#             "response_schema": section_selection_schema,
#         },
#     )

#     print("Pages to read:", response.text)
#     json_content = json.loads(response.text)
#     print("Parsed JSON content:", json_content)
#     end = time.time()
#     print(f"Time taken: {end - start} seconds")
#     return json_content


async def select_sections(iit_text, toc):
    start = time.time()
        
    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    
    max_retries = 5
    base_delay = 1
    
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=toc_reader_prompt.format(iit_text=iit_text, guideline_toc=toc),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=section_selection_schema,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_level="low")
                ),
            )
            break
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed")
                raise

    json_content = json.loads(response.text)
    print("Parsed JSON content:", json_content)
    end = time.time()
    print(f"Time taken: {end - start} seconds")
    return json_content


async def select_sections_by_query(query: str, toc):
    """
    Select guideline sections relevant to a user query (no IIT context).
    Used by mindsearch ClinicalGuidelineSearch tool. Does not modify select_sections.
    Returns list of {"section": str, "page_range": str}.
    """
    if not toc:
        return []
    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    max_retries = 5
    base_delay = 1
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=toc_reader_by_query_prompt.format(query=query or "", guideline_toc=toc),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=section_selection_schema,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_level="low")
                ),
            )
            json_content = json.loads(response.text)
            return json_content if isinstance(json_content, list) else []
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("select_sections_by_query attempt %s failed: %s. Retrying in %ss...", attempt + 1, e, delay)
                await asyncio.sleep(delay)
            else:
                logger.error("select_sections_by_query all %s attempts failed", max_retries)
                return []


async def select_sections_by_query_batch(
    query: str, guidelines: List[dict]
) -> List[list]:
    """
    Select sections for multiple guidelines in one LLM call (batch).
    guidelines: list of {"id", "title_cn", "toc"}.
    Returns list of section lists in same order as guidelines; each item is [{"section", "page_range"}, ...].
    On parse failure or missing guideline, that position is [].
    """
    if not query or not guidelines:
        return [[] for _ in guidelines]
    # Build block: one block per guideline with id, title, toc
    blocks = []
    for g in guidelines:
        gid = g.get("id")
        title = g.get("title_cn") or ""
        toc = g.get("toc") or ""
        blocks.append(
            f"--- 指南 id: {gid}, 标题: {title} ---\n目录:\n{toc}"
        )
    guidelines_block = "\n\n".join(blocks)
    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    max_retries = 5
    base_delay = 1
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-3-flash-preview",
                contents=toc_reader_by_query_batch_prompt.format(
                    query=query or "", guidelines_block=guidelines_block
                ),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=batch_section_selection_schema,
                    temperature=0,
                    thinking_config=types.ThinkingConfig(thinking_level="low")
                ),
            )
            data = json.loads(response.text)
            results = data.get("results") or []
            # Map by guideline_id for lookup; preserve order by guidelines
            by_id = {str(r.get("guideline_id")): (r.get("sections") or []) for r in results}
            out = []
            for g in guidelines:
                gid = str(g.get("id"))
                sections = by_id.get(gid, [])
                if isinstance(sections, list):
                    out.append([x for x in sections if isinstance(x, dict) and x.get("section") is not None and x.get("page_range") is not None])
                else:
                    out.append([])
            return out
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "select_sections_by_query_batch attempt %s failed: %s. Retrying in %ss...",
                    attempt + 1, e, delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("select_sections_by_query_batch all %s attempts failed", max_retries)
                return [[] for _ in guidelines]


async def select_guideline_ids_by_query(query: str, guideline_titles: list) -> list:
    """
    From candidate guidelines (list of {id, title}), return top 3 guideline ids by LLM.
    Used by mindsearch ClinicalGuidelineSearch tool. Does not modify select_guidelines.
    """
    if not guideline_titles or not query:
        return []
    sys_prompt = f"""
    你是一名医学指南选择专家。你的任务是从搜索结果中选择最符合用户查询的最相关临床指南。

    你将获得：
    1. 原始查询：{query}
    2. 搜索结果指南：{json.dumps(guideline_titles, indent=2)}

    根据标题选择与查询相关性最高的三（3）条指南。
    其中一条指南必须基于查询中提到的适应症/疾病。（例如，如果查询提到"乳腺癌"，至少一条选定的指南应该以乳腺癌为主题）
    如果多条指南的相关性相同，按权威性和最新性优先级进行排序：
    1.肿瘤：CSCO>NCCN>中国其他指南>ESMO/ASCO； 非肿瘤：中华医学会>国家诊疗规范 / 专家共识>国际主流指南（ESC / AHA / KDIGO / GINA 等）
    2.同一个协会的指南，优先选择最新的版本，不同指南来源最重要，其次是年份（即2024的CSCO优先级高于2025NCCN）

    如果没有相关的指南，请回复 "None"。

    仅返回最合适指南的 id 字段，不提供任何额外说明。
"""
    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3-flash-preview",
            contents=sys_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=guideline_selection_schema,
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level="low")
            ),
        )
        selected = json.loads(response.text)
        if not selected or (len(selected) == 1 and selected[0] == "None"):
            return []
        return [str(x) for x in selected]
    except Exception as e:
        logger.warning("select_guideline_ids_by_query failed: %s", e)
        return []


async def select_guidelines(q, guidelines, iit_text):
    guideline_titles = [{'id': g['id'], 'title': g['title_cn']} for g in guidelines] 
    logger.info("Guideline Titles for Selection: %s", guideline_titles)
    sys_prompt = f"""
    你是一名医学指南选择专家。你的任务是从搜索结果中选择最符合用户查询的最相关临床指南。

    你将获得：
    1. 原始查询：{q}
    2. 搜索结果指南：{json.dumps(guideline_titles, indent=2)}
    
    根据标题选择与查询相关性最高的三（3）条指南。
    其中一条指南必须基于查询中提到的适应症/疾病。（例如，如果查询提到"乳腺癌"，至少一条选定的指南应该以乳腺癌为主题）
    如果多条指南的相关性相同，按权威性和最新性优先级进行排序：
    1.肿瘤：CSCO>NCCN>中国其他指南>ESMO/ASCO； 非肿瘤：中华医学会>国家诊疗规范 / 专家共识>国际主流指南（ESC / AHA / KDIGO / GINA 等）
    2.同一个协会的指南，优先选择最新的版本，不同指南来源最重要，其次是年份（即2024的CSCO优先级高于2025NCCN）
    
    如果没有相关的指南，请回复 "None"。

    仅返回最合适指南的 id 字段，不提供任何额外说明。
"""
    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    response = await client.aio.models.generate_content(
        model="gemini-3-flash-preview",
        contents=sys_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=guideline_selection_schema,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_level="low")
        ),
    )

    selected_guideline_ids = json.loads(response.text)
    if not selected_guideline_ids:
        print("No relevant guidelines found.")
        return None
    print("Selected Guideline IDs:", selected_guideline_ids)
    logger.info("Selected Guideline IDs: %s", selected_guideline_ids)
    # guidelines = await fetch_guideline_by_ids(selected_guideline_ids)
    guidelines = sorted([g for g in guidelines if str(g['id']) in selected_guideline_ids], key=lambda g: selected_guideline_ids.index(str(g['id'])))

    tasks = []
    for guideline in guidelines[:4]:
        tasks.append(asyncio.create_task(select_sections(iit_text, guideline['toc'])))
    tasks_list = await asyncio.gather(*tasks)
    chunks = []
    total_tokens = 0
    for guideline, task in zip(guidelines, tasks_list):
        # print(f"Guideline ID: {guideline['id']}, Title: {guideline['title_cn']}")
        logger.info("Guideline ID: %s, Title: %s", guideline['id'], guideline['title_cn'])
        sections = []
        for section_range in task:
            # print("Sections to read:", section_range)
            logger.info("Sections to read: %s", section_range)
            try:
                page_range = section_range.pop('page_range')
                if '-' in page_range:
                    start_page, end_page = map(int, page_range.split('-'))
                    content = guideline['pages'][start_page-1:end_page]
                    tokens = await _count_tokens(content)
                    if total_tokens + tokens > 120000:
                        # print(f"Skipping section {section_range['section']} due to token limit. Current total: {total_tokens}, Section tokens: {tokens}")
                        logger.info(f"Skipping section {section_range['section']} due to token limit. Current total: {total_tokens}, Section tokens: {tokens}")
                        continue
                    total_tokens += tokens
                    section_range['content'] = content
                else:
                    page_num = int(page_range)
                    content = guideline['pages'][page_num-1]
                    tokens = await _count_tokens(content)
                    if total_tokens + tokens > 120000:
                        # print(f"Skipping section {section_range['section']} due to token limit. Current total: {total_tokens}, Section tokens: {tokens}")
                        logger.info(f"Skipping section {section_range['section']} due to token limit. Current total: {total_tokens}, Section tokens: {tokens}")
                        continue
                    total_tokens += tokens
                    section_range['content'] = content
                sections.append(section_range)
            except Exception as e:
                logger.error("Error processing section %s: %s", section_range, e)
                continue
            
        chunks.append(f"Guideline Title: {guideline['title_cn']}\nSections: {sections}")
        
    return "\n\n".join(chunks)

async def _count_tokens(text):
    encoding = tiktoken.get_encoding("cl100k_base") 
    if isinstance(text, str):
        tokens = encoding.encode(text)
        return len(tokens)
    elif isinstance(text, list):
        total_tokens = 0
        for idx, doc in enumerate(text):
            tokens = encoding.encode(doc)
            total_tokens += len(tokens)
        return total_tokens
    
if __name__ == "__main__":
    from agent.iit.v3.guidelines.prompt_test import test_prompt
    prompt = test_prompt

    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config={
            "temperature": 0,
        },
    )
    print(response.text)