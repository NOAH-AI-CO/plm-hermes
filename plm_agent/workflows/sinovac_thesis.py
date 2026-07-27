import asyncio
import os 
import re
import unicodedata

from pydantic import BaseModel, Field

from llm.gcp_models import CompositeClaude, ClaudeSonnet45
from llm.composite_models import CompositeGPT5, CompositeGPT5Mini
from utils.pubmed_opt.pubmed_search import PubMedSearch
from workflows.sinovac_thesis_prompt import citation_cleanup_prompt, citation_reorganization_prompt_v1, gen_abstract_and_conclusion_prompt, gen_abstract_and_conclusion_prompt_v2, gen_abstract_prompt, gen_conclusion_prompt, gen_thesis_from_outline_section_prompt_v3, gen_thesis_from_outline_section_prompt_v4, gen_thesis_from_outline_section_prompt_v5, hallucination_check_prompt, hallucination_check_prompt_v2, thesis_prompt, gen_thesis_from_outline_prompt, gen_thesis_from_outline_section_prompt, gen_thesis_from_outline_section_prompt_v2, thesis_prompt_v2, thesis_prompt_v3, thesis_prompt_v4, thesis_prompt_v41, thesis_translate_prompt, citation_reorganization_prompt, thesis_translate_prompt_v2, gen_thesis_from_outline_section_prompt_v6

from workflows.analyze_target import save_to_file, run_pubmed_agent
from workflows.sinovac_thesis_data import test_thesis_data, thesis1_section1_data_list, thesis10_section_data_list, thesis11_section_data_list, thesis13_section_data_list, thesis12_section_data_list
from utils.hallucination.vectara import VectaraHallucination
from utils.hallucination.parser import parse_blocks, merge_blocks
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import build_search_prompt, function_call_with_retry
# from agent.explore.mindsearch_agent_v3 import MindSearchPubMedHitlAgent
from agent.explore.schema import MindSearchResponse


# async def run_pubmed_agent_with_tool_result(user_prompt: str, language: str = 'en') -> str:
#     agent = MindSearchPubMedHitlAgent()

#     async for chunk in agent.start_wo_dump(
#         user_prompt=user_prompt,
#         history_messages=[],
#         language=language,            
#         prompt_template="",       
#         template_kwargs={},       
#     ):
#         yield chunk


# async def gen_thesis_outline(file_name: str, thesis_data, language: str = 'en') -> str:
#     thesis_data_list = THESIS_DATA_MAPPING.get(thesis_data, [])
#     for thesis_data in thesis_data_list:
#         prompt = gen_thesis_from_outline_section_prompt_v6.format(thesis_outline=thesis_data.get('outline_section', ''), title=thesis_data.get('title', ''), outline_section=thesis_data.get('outline_section', ''))
#         async for chunk in run_pubmed_agent_with_tool_result(prompt, language=language):
#             yield chunk



THESIS_DATA_MAPPING = {
    "thesis1_section1": thesis1_section1_data_list,
    "thesis10": thesis10_section_data_list,
    "thesis11": thesis11_section_data_list,
    "thesis12": thesis12_section_data_list,
    "thesis13": thesis13_section_data_list,
    "test_thesis": test_thesis_data,
}

async def generate_thesis_from_file(file_path, llm, thesis_prompt, full_text, abstract_and_conclusion, language: str = 'en'):
    """
    读取文件内容，使用thesis_prompt作为prompt，并调用llm生成学术论文格式内容

    :param file_path: 待读取的文件路径
    :param llm: LLM对象(必须有__call__方法或者chat/completion接口)
    :param thesis_prompt: 论文格式的prompt字符串，需包含{document}占位符
    :param language: 语言，默认英语
    :return: LLM生成的学术论文格式内容
    """
    # dir_path = "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/"
    # with open(os.path.join(dir_path, file_path), "r", encoding="utf-8") as f:
    #     document = f.read()

    filled_prompt = thesis_prompt.format(document=full_text, abstract=abstract_and_conclusion.get('abstract', ''), conclusion=abstract_and_conclusion.get('conclusion', ''), language=language)
    async for chunk in llm.stream_call(user_prompt=filled_prompt):
        yield chunk


async def output_the_thesis(file_path: str, file_name, timestr, full_text, abstract_and_conclusion, language: str = 'en'):
    result = str()  

    # file_path = "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/test.md"
    # file_path1 = "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/outputs_test_thesis_from_outline_20251105.md.md"
    llm = ClaudeSonnet45()
    
    async for chunk in generate_thesis_from_file(file_path, llm, thesis_prompt_v41, full_text, abstract_and_conclusion, language):
        result += chunk
        yield result
    # save_to_file(f"{file_name}_{timestr}_output", result)
    

async def hallucination_check():
    """
    幻觉检查 v1 用vectara方案，暂时废弃，日后调查开源或付费
    """
    origin_document = str()
    llm_output_docuemtn = str()
    origin_file = "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/thesis10_20251106_155830.md"
    llm_output_file = "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/thesis10_20251106_155830_output.md"
    with open(origin_file, "r", encoding="utf-8") as f:
        origin_document = f.read()
    with open(llm_output_file, "r", encoding="utf-8") as f:
        llm_output_document = f.read()

    vectara: VectaraHallucination = VectaraHallucination()
    # blocks = parse_blocks(llm_output_document)
    #result = await vectara.vectara_hhme(generated_text, [source_texts])
    result = await vectara.summary(llm_output_document, [origin_document])
    print(result)
    yield result 



async def generate_thesis_from_outline_parallel(sections: list[dict], language: str = 'en', concurrency_limit: int = 3) -> list[dict]:
    """
    并发跑每个章节，收集各章节的最终输出（最后一个chunk），
    并按原始顺序返回 [{'title': str, 'content': str}, ...]
    """
    semaphore = asyncio.Semaphore(concurrency_limit)

    async def generate_one(idx: int, sec: dict) -> tuple[int, str]:
        async with semaphore:
            last_chunk = ""
            async for chunk in run_pubmed_agent(
                query="",
                language=language,
                prompt_template=gen_thesis_from_outline_section_prompt_v6,
                template_kwargs={
                    "thesis_outline": sec["outline_section"].strip(),
                    "title": sec["title"].strip(),
                    "outline_section": sec["outline_section"].strip()
                }
            ):
                last_chunk = chunk or ""
            return idx, last_chunk

    tasks = [asyncio.create_task(generate_one(i, sec)) for i, sec in enumerate(sections)]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    results.sort(key=lambda x: x[0])

    ordered = [
        {
            "title": sections[i]["title"].strip(),
            "content": content
        }
        for i, content in results
    ]
    return ordered

# 示例：获取列表后再拼成整篇文章
async def build_full_thesis_from_parallel(file_name: str, thesis_data, language: str = 'en') -> str:
    thesis_data_list = THESIS_DATA_MAPPING.get(thesis_data, [])
    sections = await generate_thesis_from_outline_parallel(thesis_data_list, language)
    full_text = ""
    for sec in sections:
        full_text += f"\n\n## {sec['title']}\n\n{sec['content']}"
    # 测试用
    # full_text = ""
    # with open(f"/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/VP_20251113_210747_full_text.md", "r", encoding="utf-8") as f:
    #     full_text = f.read()
    
    import datetime
    timestr = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    yield full_text
    save_to_file(f"{file_name}_{timestr}_full_text", full_text)
    # 生成摘要和总结
    abstract_dict = await gen_abstract(full_text, language)
    conclusion_dict = await gen_conclusion(full_text, language)
    abstract_and_conclusion = {
        "abstract": abstract_dict.get("abstract", ""),
        "conclusion": conclusion_dict.get("conclusion", "")
    }
    yield abstract_and_conclusion
    # 原始文章
    origin_document = full_text + "\n\n摘要：" + abstract_and_conclusion.get('abstract', "") + "\n\n结论：" + abstract_and_conclusion.get('conclusion', "")
    save_to_file(f"{file_name}_{timestr}_origin", origin_document)

    # 可能具有幻觉的输出内容
    llm_output_document = str()
    # 调用输出output_the_thesis 传入文件名 输出文件
    async for content in output_the_thesis(f"{file_name}_{timestr}.md", file_name, timestr, full_text, abstract_and_conclusion, language):
        llm_output_document = content
        yield content
    save_to_file(f"{file_name}_{timestr}_llm_output", llm_output_document)
    
    """
    # 幻觉检查
    # 1. 拆分可能有幻觉的内容 blocks 两种格式，一种是文字，有text字段  一种是table table里面没有text只有table_row的rows字段 是一个列表，列表里面是字符串
    # 2. llm检查幻觉，输出[{"hallucination_check_chunk": str, "hallucination_check_chunk_result": str}] 检查前内容，检查后结果（直接返回结果）
    check_blocks_list = await hallucination_check_all(origin_document, llm_output_document)
    print("check_blocks_list:", check_blocks_list)
    yield check_blocks_list
    """
    """
    # 3. 拼起来
    result = merge_blocks(check_blocks_list)
    # save幻觉检查后的文章
    save_to_file(f"{file_name}_{timestr}_hallucination_check_result", result)
    yield result
    """

class GenAbstractSchema(BaseModel):
    """
    论文摘要 Schema
    """
    abstract: str = Field(description="The abstract of the thesis, 200-300 words")
    # conclusion: str = Field(description="The conclusion of the thesis, 350-400 words")

class GenConclusionSchema(BaseModel):
    """
    论文结论 Schema
    """
    # abstract: str = Field(description="The abstract of the thesis, 150-200 words")
    conclusion: str = Field(description="The conclusion of the thesis, 350-400 words")

async def gen_abstract(thesis_data: str, language: str = 'en') -> str:
    """
    论文的摘要生成
    """

    llm = CompositeGPT5Mini()
    schema = get_openai_json_schema_v3(GenAbstractSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=gen_abstract_prompt.format(thesis_data=thesis_data, language=language),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3,
            # language=language
        )
        return result
    except Exception as e:
        raise Exception(f"论文的摘要生成失败: {str(e)}")

async def gen_conclusion(thesis_data: str, language: str = 'en') -> str:
    """
    论文的结论生成
    """

    llm = CompositeGPT5Mini()
    schema = get_openai_json_schema_v3(GenConclusionSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=gen_conclusion_prompt.format(thesis_data=thesis_data, language=language),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3,
            # language=language
        )
        return result
    except Exception as e:
        raise Exception(f"论文结论的生成失败: {str(e)}")


class GenHallucinationCheckSchema(BaseModel):
    """
    幻觉检查 Schema
    """
    is_hallucination: bool = Field(description="是否存在幻觉，True或False，True表示存在幻觉，False表示不存在幻觉")
    hallucination_result: str = Field(description="幻觉检查的结果，说明一下幻觉原因，并给出修改建议，如果不需要修改，则返回空字符串")


async def hallucination_check(origin_document, llm_output_document_chunk: str, ) -> str:
    """
    单chunk幻觉检查
    """
    llm = CompositeClaude()
    schema = get_openai_json_schema_v3(GenHallucinationCheckSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=hallucination_check_prompt_v2.format(origin_data=origin_document, section_data=llm_output_document_chunk),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3,
        )
        return result
    except Exception as e:
        raise Exception(f"幻觉检查失败: {str(e)}")

async def hallucination_check_all(origin_document, llm_output_document: str) -> list[dict]:
    blocks = parse_blocks(llm_output_document)
    if not blocks:
        return []

    semaphore = asyncio.Semaphore(3)  # 并发上限，可根据配额调节
    tasks: list[asyncio.Task] = []
    text_blocks: list[dict] = []

    async def check_with_limit(block: dict, text: str) -> tuple[dict, str]:
        async with semaphore:
            result = await hallucination_check(origin_document, text)
            return block, result

    for block in blocks:
        if block.get("type") == "table_row":
            continue

        text = block.get("text")
        if text:
            text_blocks.append(block)
            tasks.append(asyncio.create_task(check_with_limit(block, text)))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=False)
        for block, check_result in results:
            block["is_hallucination"] = check_result.get("is_hallucination", False)
            block["hallucination_result"] = check_result.get("hallucination_result", "")

    blocks.sort(key=lambda b: b.get("id", 0))
    return blocks


async def reorganization_of_citations(file_path: str) -> str:
    """
    引用的重新组织：删除正文中未引用的参考文献并按正文引用顺序重新编号
    """
    llm = CompositeClaude()
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        thesis_data = f.read()

    prompt = citation_cleanup_prompt.format(thesis_data=thesis_data)

    try:
        result = ""
        async for chunk in llm.stream_call(user_prompt=prompt, temperature=0.1):
            result += chunk
            yield result
    except Exception as e:
        raise Exception(f"引用的重新组织失败: {str(e)}")


async def translate_thesis_chunked(file_path: str, language: str = 'en', chunk_size: int = 3000) -> str:
    """
    分块翻译大文件
    
    Args:
        file_path: 文件路径
        language: 目标语言
        chunk_size: 每个块的最大字符数（默认3000，可根据模型上下文窗口调整）
    
    Yields:
        翻译后的内容（流式输出）
    """
    import datetime
    import re
    timestr = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # reorganized_thesis = str()
    # # 调用引用重组函数重新编辑引文
    # async for chunk in reorganization_of_citations(file_path):
    #     reorganized_thesis = chunk
    #     yield reorganized_thesis
    # save_to_file(f"reorganized_thesis_{timestr}", reorganized_thesis)
        
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        thesis_data = f.read()

    heading_pattern = re.compile(r'^(##\s+[^\n]+)', re.MULTILINE)  # 只匹配 “## 标题”
    matches = list(heading_pattern.finditer(thesis_data))

    chunks = []
    if matches:
        # 如果开头在第一个 “## ” 之前还有内容，作为前导块
        if matches[0].start() > 0:
            lead_text = thesis_data[:matches[0].start()].strip()
            if lead_text:
                chunks.append(lead_text)

        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(thesis_data)
            block = thesis_data[start:end].strip()

            if len(block) <= chunk_size:
                chunks.append(block)
            else:
                # 太长则按段落拆分
                paragraphs = block.split('\n\n')
                current = ""
                for para in paragraphs:
                    if len(current) + len(para) + 2 > chunk_size and current:
                        chunks.append(current.strip())
                        current = para
                    else:
                        current += '\n\n' + para if current else para
                if current.strip():
                    chunks.append(current.strip())
    else:
        # 无任何 “## ” 标题，直接按段落拆
        paragraphs = thesis_data.split('\n\n')
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 > chunk_size and current:
                chunks.append(current.strip())
                current = para
            else:
                current += '\n\n' + para if current else para
        if current.strip():
            chunks.append(current.strip())
    
    # 逐块翻译
    llm = ClaudeSonnet45()
    translated_parts = []
    
    for idx, chunk in enumerate(chunks):
        # 构建翻译提示词，包含上下文信息
        context_info = ""
        if idx > 0:
            context_info = f"\n\n[上一段结尾]: {chunks[idx-1][-200:]}"  # 提供前一段结尾作为上下文
        
        prompt = thesis_translate_prompt_v2.format(
            language=language,
            thesis_data=chunk,
            context=context_info,
            chunk_index=idx + 1,
            total_chunks=len(chunks)
        )
        
        chunk_result = ""
        async for chunk_translated in llm.stream_call(user_prompt=prompt):
            chunk_result += chunk_translated
            yield chunk_translated  # 流式输出
        
        translated_parts.append(chunk_result)
    
    # 保存完整翻译结果
    full_result = '\n\n'.join(translated_parts)
    save_to_file(f'translate-{timestr}', full_result)


async def extract_unique_bracket_numbers(text: str) -> list:
    """
    提取文本中方括号里的数字编号，支持逗号分隔，按出现顺序去重。
    """
    seen = set()
    ordered = []
    # 先拿到每个方括号内的完整内容
    for block in re.findall(r'\[([^\]]+)\]', text):
        # 按逗号拆分，每个子串清理空格
        for token in block.split(','):
            token = token.strip()
            if token.isdigit() and token not in seen:
                seen.add(token)
                ordered.append(token)
    return ordered

async def extract_unique_pmid_all(text: str) -> dict:
    """
    查询pmid 
    """
    pmid_info_list = []
    pmid_list = await extract_unique_bracket_numbers(text)
    for pmid in pmid_list:
        pmid_info = await get_pmid_info(pmid)
        pmid_info_list.append(pmid_info)
    return pmid_info_list

def format_authors(authors):
    """
    authors: List[str]
    返回：
      - 少于或等于 4 人：用逗号连接全部名字
      - 多于 4 人：列前三个作者，再加 "et al."
    """
    authors = [a for a in authors if a and a.strip()]
    if len(authors) <= 4:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + ", et al."

async def get_pmid_info(pmid: str) -> dict:
    """
    查询pmid信息
    {作者、title、出版社、时间、页码、pmid}

    """
    pubmed_search = PubMedSearch()
    results_dict = await pubmed_search.es_search.query_by_pmid(pmid)
    if not results_dict.get('total_count') >=1:
        return {}
    result = results_dict.get("results", [])[0]

    author_list = result.get("author", [])
    author_list_result = format_authors(author_list)
    # filter field
    result_filter = {
        "title": result.get("title", ""),
        "journal": result.get("journal", ""),
        "authors": author_list_result,
        # "pubdate": results_dict.get("pubdate", ""),
        "year_of_publication": result.get("year_of_publication", ""),
        'pmid': pmid,
        "abstract": result.get("abstract", ""),
        'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}", 
    }
    return result_filter

async def get_pmid_info_by_title(title: str) -> dict:
    """
    查询title信息
    """
    def toggle_dot(s):
        if s.endswith('.'):
            return s[:-1]
        else:
            return s + '.'
    pubmed_search = PubMedSearch()
    results_dict = await pubmed_search.es_search.query_by_title(title)
    if not results_dict.get('total_count') >=1:
        temp_title = f"[{title}]"
        results_dict = await pubmed_search.es_search.query_by_title(temp_title)
        if not results_dict.get('total_count') >=1:
            temp_title = toggle_dot(temp_title)
            results_dict = await pubmed_search.es_search.query_by_title(temp_title)
    if not results_dict.get('total_count') >=1:
        title = toggle_dot(title)
        results_dict = await pubmed_search.es_search.query_by_title(title)
        if not results_dict.get('total_count') >=1:
            return {}
    results_dict = results_dict.get("results", [])[0]
    author_list = results_dict.get("author", [])
    author_list_result = format_authors(author_list)
    # filter field
    result_filter = {
        "title": results_dict.get("title", ""),
        "journal": results_dict.get("journal", ""),
        "authors": author_list_result,
        "abstract": results_dict.get("abstract", ""),
        "year_of_publication": results_dict.get("year_of_publication", ""),
        'pmid': results_dict.get("pmid"),
        "abstract": results_dict.get("abstract", ""),
        'url': f"https://pubmed.ncbi.nlm.nih.gov/{results_dict.get("pmid")}", 
    }
    return result_filter

async def get_pmid_info_by_title_all() -> list[dict]:
    pmid_info_list = []
    with open('/Users/shey/Documents/论文/1. Daniel O’Connor, Valentina Moschese, Fernando M', 'r', encoding='utf-8') as f:
        for idx, line in enumerate(f, start=1):
            raw = line.strip()
            if not raw:
                continue

            # 1) Unicode 规范化
            norm = unicodedata.normalize("NFKC", raw)
            # 2) 空白统一
            norm = re.sub(r"[\u00A0\u2007\u202F\u2009\u200A\u200B]", " ", norm)
            norm = re.sub(r"\s+", " ", norm).strip()

            # 先截到 '[' 之前（没有 '[' 就用整行）
            left_bracket_pos = norm.find('[')
            before_bracket = norm if left_bracket_pos == -1 else norm[:left_bracket_pos]

            # 在 '[' 之前的部分里，找“最后一个句号+空格”，后面就是 title
            last_dot_space = before_bracket.rfind('. ')
            if last_dot_space != -1:
                title = before_bracket[last_dot_space + 2 :].strip()
            else:
                # 找不到就退化为整段（去掉编号）
                title = before_bracket.strip()

            pmid_info = await get_pmid_info_by_title(title)
            pmid_info.setdefault("idx", idx)
            pmid_info_list.append(pmid_info)

    json_to_csv(pmid_info_list, "/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/pmid_info_list260211.csv")
    return pmid_info_list

def json_to_csv(data, output_path):
    """
    data: 可以是 JSON 字符串、dict（含 pmid_info_list）或 list
    output_path: 输出 CSV 文件路径
    """
    import csv, json
    if isinstance(data, str):
        data = json.loads(data)
    if isinstance(data, dict) and "pmid_info_list" in data:
        entries = data["pmid_info_list"]
    elif isinstance(data, list):
        entries = data
    else:
        entries = []

    if not entries:
        return

    fieldnames = ["idx", "pmid", "title", "journal", "authors", "year_of_publication", "abstract", "url"]
    
    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            row = {field: entry.get(field, "") for field in fieldnames}
            writer.writerow(row)

async def construct_the_citations(pmid_info_list: list) -> str:
    """
    构造参考文献
    """
    citations = []
    for idx, pmid_info in enumerate(pmid_info_list, start=1):
        citations.append(
            f"{idx}. {pmid_info['authors']}. {pmid_info['title']} "
            f"{pmid_info['journal']}. {pmid_info['year_of_publication']}. "
            f"PMID: {pmid_info['pmid']}."
        )
    return "\n".join(citations)

async def construct_the_citations_all(text: str) -> str:
    """
    构造参考文献
    """
    pmid_info_list = await extract_unique_pmid_all(text)
    citations = await construct_the_citations(pmid_info_list)
    return citations


def compress_indices(indices: list[int]) -> str:
    """把升序序列压缩成 1-3, 5 这种文本"""
    if not indices:
        return ""
    indices = sorted(set(indices))
    ranges = []
    start = prev = indices[0]
    for num in indices[1:]:
        if num == prev + 1:
            prev = num
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = num
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)

async def replace_pmids_with_refs(text: str, pmid_info_list: list[dict]) -> str:
    """
    - `pmid_info_list` 是已有的文献信息列表，其顺序即引用编号 1, 2, 3...
    - 文本中 `[16005552]`、`[16005552, 17714837]` 等会被替换成 `[1]`、`[1-2]` 之类
    """
    pmid_to_index = {info['pmid']: idx for idx, info in enumerate(pmid_info_list, start=1)}

    def repl(match: re.Match) -> str:
        block = match.group(1)
        indices = []
        for token in block.split(','):
            token = token.strip()
            if not token:
                continue
            idx = pmid_to_index.get(token)
            if idx is not None:
                indices.append(idx)
        if not indices:
            return match.group(0)  # 保留原样
        formatted = compress_indices(indices)
        return f"[{formatted}]"

    return re.sub(r'\[([^\]]+)\]', repl, text)


async def test_replace_pmids_with_refs():
    with open("/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/pubmed号生成文献_20251121_151832_origin.md", "r", encoding="utf-8") as f:
        
        original_text = f.read()

    pmid_info_list = await extract_unique_pmid_all(original_text)
    rewritten = await replace_pmids_with_refs(original_text, pmid_info_list)


    # 构造文献
    citations = await construct_the_citations_all(original_text)
    
    thesis_data = rewritten + "\n\n" + "\n\n" + " " + "## 参考文献" + "\n\n" + citations
    # 写回新文件
    with open("/Users/shey/workspace/NoahServer/NoahAgent/noah_agent/outputs/pubmed号生成文献后12.md", "w", encoding="utf-8") as f:
        f.write(thesis_data)


async def load_pmids_and_fetch_infos(file_path: str, dedup: bool = True) -> list:
    """
    从文件读取PMID（每行一个），调用 get_pmid_info 获取详情并返回列表。
    :param file_path: 包含PMID的文本文件路径
    :param dedup: 是否对PMID去重
    :return: 每个PMID的 get_pmid_info 返回结果列表
    """
    import re

    def extract_pmid(text):
        """
        从文本中提取 PMID 后面的数字
        
        示例:
            text = "PMID: 20074976. URL:(https://...)"
            返回: "20074976"
        """
        match = re.search(r'PMID:\s*(\d+)', text)
        if match:
            return match.group(1)
        return text.strip()
    results = []
    seen = set()

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            pmid_line = line.strip()
            
            if not pmid_line:
                continue
            pmid = extract_pmid(pmid_line)
            if not pmid:
                continue
            if dedup and pmid in seen:
                continue
            seen.add(pmid)

            try:
                info = await get_pmid_info(pmid)
                results.append(info)
            except Exception as e:
                # 视需要记录日志或收集失败的pmid
                print(f"获取 PMID {pmid} 失败: {e}")
    # 保存 results 到文件
    try:
        import csv
        import os
        out_file = file_path + "_infos.csv"
        # 提取所有可能出现的字段，确保每一列都能写出来
        fieldnames = set()
        for item in results:
            if isinstance(item, dict):
                fieldnames.update(item.keys())
        fieldnames = list(fieldnames)
        # 写csv
        with open(out_file, "w", encoding="utf-8", newline="") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=fieldnames)
            writer.writeheader()
            for item in results:
                if isinstance(item, dict):
                    writer.writerow(item)
    except Exception as e:
        print(f"写入文件失败: {e}")

    return results

