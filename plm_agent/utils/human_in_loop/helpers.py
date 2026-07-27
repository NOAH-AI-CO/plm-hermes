import asyncio
import copy
import csv
import io
import json
import re
import traceback
import urllib.parse
from typing import Callable
import logging
import os
from datetime import datetime
from config import settings

from pandas.core.base import NoNewAttributesMixin
from i18n import planning_tool_names_table, resolve_language
from agent.explore.helper import MindSearchHelper
from agent.human_in_loop.constants import (
    background_prefix_map, data_empty_prompt, data_empty_prompt_cn,
)
from tools.human_in_loop.planning.prompt import (
    planning_final_template_cn, planning_final_template_en, 
    planning_input_prompt, replanning_input_prompt, 
    planning_input_prompt_cn, replanning_input_prompt_cn, 
    example, tools_description, tools_description_cn,
    planning_final_template_v2, tools_description_v2,
    claude_plan_system_prompt,
    inference_template_v2, inference_input_prompt_v2,
)
import pandas as pd
from utils.core.formatting import escape_md_filename, unescape_md_filename
from utils.core.prompt_fetcher import PromptFetcher

pt_fetcher = PromptFetcher()

logger = logging.getLogger(__name__)

async def function_call_with_retry(f: Callable, *args, **kwargs):
    latest_exc = Exception("Function call failed after all retries")
    planning = kwargs.pop('planning', False)
    for attempt in range(5):
        try:
            function_call_response = await f(*args, **kwargs)
            if hasattr(function_call_response, 'tool_calls') and function_call_response.tool_calls and len(function_call_response.tool_calls) > 0:
                arguments = function_call_response.tool_calls[0].function.arguments
            else:
                try:
                    arguments = function_call_response.content
                except:
                    arguments = function_call_response[0]['arguments']
            # Handle case where arguments is a string (containing JSON)
            if isinstance(arguments, str):
                # Find the content between first { and last }
                # Try to find JSON enclosed in ```json{...}``` format
                if '```json' in arguments:
                    match = arguments.split('```json')[1].split('```')[0].strip()
                    arguments = match
                # Otherwise continue with the original approach
                start_idx = arguments.find('{')
                end_idx = arguments.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    arguments = arguments[start_idx:end_idx+1]
            arguments = json.loads(arguments)
            while type(arguments) == list and arguments:
                arguments = arguments[0]
            while type(arguments) == dict and 'arguments' in arguments:
                arguments = arguments['arguments']
            if type(arguments) != dict:
                raise Exception("Invalid arguments format, should be dict")
            if planning and ('planned_sequence' not in arguments or not arguments['planned_sequence']) and ('additional_steps' not in arguments or not arguments['additional_steps']):
                raise Exception("Empty planned sequence")
            return arguments
        except Exception as e:
            latest_exc = e
            logger.error(f"Function call failed: {e}", stack_info=True)
            await asyncio.sleep(1)
            print('tool_slot_filling failed, retrying....')
            if hasattr(f, '_try_next_model') and callable(getattr(f, '_try_next_model')) and attempt % 2 == 1:
                if not f._try_next_model():
                    logger.error("No more models to try, giving up.")
                    break
    if str(latest_exc) == "Empty planned sequence":
        return {}
    raise latest_exc

async def stream_function_call_with_retry(f: Callable, *args, **kwargs):
    latest_exc = Exception("Function call failed after all retries")
    for attempt in range(5):
        try:
            tool_call_accumulator = {
                "name": None,  # 函数名
                "arguments": ""  # 函数参数（增量拼接）
            }
            
            kwargs.pop('language', None)
            async for chunk in f(*args, stream=True, **kwargs):
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # 1. 判断是否是自然语言输出：输出 delta.content
                if delta.content is not None:
                    yield {
                        "type": "chat",
                        "content": delta.content,
                        "is_end": False,
                    }

                # 2. 判断是否是工具调用：累积 tool_calls 信息
                if delta.tool_calls is not None:
                    for tool_call in delta.tool_calls:
                        # 累积函数名（首次出现时记录）
                        if tool_call.function.name is not None:
                            tool_call_accumulator["name"] = tool_call.function.name
                        # 累积函数参数（增量拼接）
                        if tool_call.function.arguments is not None:
                            tool_call_accumulator["arguments"] += tool_call.function.arguments
                    yield {
                        "type": "tool",
                        "name": tool_call_accumulator["name"],
                        "arguments": tool_call_accumulator["arguments"],
                        "is_end": False,
                    }
                # 3. 判断工具调用是否完成：当 finish_reason 为 tool_calls 时，获取完整信息
                if finish_reason == "tool_calls":
                    try:
                        tool_arguments = json.loads(tool_call_accumulator["arguments"])
                        task_description = tool_arguments.pop("task_description", None)
                        if type(tool_arguments) != dict:
                            raise Exception("Invalid arguments format, should be dict")
                        yield {
                            "type": "tool",
                            "name": tool_call_accumulator["name"],
                            "arguments": tool_arguments,
                            "task_description": task_description,
                            "is_end": True,
                        }
                    except json.JSONDecodeError:
                        print("参数解析失败")
                if finish_reason == "stop":
                    yield {
                        "type": "chat",
                        "content": "",
                        "is_end": True
                    }
            break
        except Exception as e:
            latest_exc = e
            logger.error(f"Function call {f} failed: {e}")
            await asyncio.sleep(1)
            print('tool_slot_filling failed, retrying....')
            if hasattr(f, '_try_next_model') and callable(getattr(f, '_try_next_model')) and attempt % 2 == 1:
                if not f._try_next_model():
                    logger.error("No more models to try, giving up.")


def save_to_file(data: dict, output_dir, file_name: str):
    os.makedirs(output_dir, exist_ok=True)
    file_path = os.path.join(output_dir, file_name)
    if type(data) == str:
        # Check if data has line with only "---" in it and remove it
        data = re.sub(r'^---\s*$', '', data, flags=re.MULTILINE)
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            f.write(data)
    else:
        with open(file_path, 'w', encoding='utf-8') as f:
            try: json.dump(data, f, indent=4, ensure_ascii=False)
            except: f.write(data)
    print(f"- {file_path} saved successfully.")

def format_database_tool_citation(tool_use: dict) -> str:
    citation_base_url = {
        'Drug-Analysis': 'tool/drug-compete/',
        'Catalyst-Event-Analysis': 'tool/catalyst/',
        'Clinical-Trial-Result-Analysis': 'tool/clinical-result/'
    }.get(tool_use['tool'], 'hitl')
    params = json.dumps(tool_use.get('params', {}))
    encoded_params = urllib.parse.quote(params, safe='')
    citation_url = f"{citation_base_url}?search_param={encoded_params}"
    return citation_url  
    
def tool_history_to_prompt(prior_tool_use, is_plan=False, is_summary=False) -> str:
    if not prior_tool_use:
        return ""
    url_map = {} # url -> id to make sure llm get sequence reference
    prompt = "Tool use results:\n"
    number = 1
    for _, tool_use in enumerate(prior_tool_use):
        tool_use_result = ""
        if not tool_use.get('result', None):
            continue
        try:
            if tool_use['tool'] == "User-Question" and tool_use.get('question', None):
                prompt += f"{number}: User asked question: {tool_use['question']}\n"
                number += 1
                continue
            if not is_plan and tool_use['tool'] in ['Self-Reflection', 'Plan-Sequence']:
                continue
            if type(tool_use['result']) == str:
                tool_use_result = tool_use['result']
            else:
                tool_use_result = str(tool_use['result'].get('content', '') or tool_use['result'])
            
            # Add citation comment at the end of the Drug-Analysis, Catalyst-Event-Analysis, Clinical-Trial-Result-Analysis, for summary llm citation display.
            if is_summary and tool_use['tool'] in ['Drug-Analysis', 'Catalyst-Event-Analysis', 'Clinical-Trial-Result-Analysis']:
                citation_url = format_database_tool_citation(tool_use)
                citation_url = f"https://www.noahai.co/{citation_url}"
                tool_use_result += f"\n\n# Reference:\n All above content are from [1]({citation_url})\n\n"

        except Exception as e:
            trace = traceback.format_exc()
            logger.info(f"Error parsing tool use result: {e}, Trace: {trace}")
        # update reference id
        tool_use_result = format_prompt_reference(tool_use_result, url_map)
        # format tool result
        # tool_prompt = f"#{number}. Used tool:\n {tool_use['tool']}\n #Result:\n {tool_use_result}\n"
        tool_prompt = f"Used tool:\n {tool_use['tool']}\n #Result:\n {tool_use_result}\n"
        if 'params' in tool_use and tool_use['params']:
            tool_prompt += f"#Params used:\n {tool_use['params']}"
        prompt += f"<tool>{tool_prompt}</tool>\n\n"
        number += 1
    return prompt

def _normalize_citation_url(url: str) -> str:
    """Strip query params from Azure Blob URLs so the same file gets one citation ID."""
    if 'blob.core.windows.net' in url:
        return url.split('?')[0]
    return url


def format_prompt_reference(prompt: str, url_map: dict, is_summary=False) -> str:

    r"Since each tool's reference starts from 1, we sort reference index"

    url_pattern = r'\[(\d+)\]\(([\w+.-]+:[^\s\)]+)\)'

    def replace_func(match):
        url = match.group(2)
        key = _normalize_citation_url(url)
        if key not in url_map:
            url_map[key] = len(url_map.items()) + 1
        id = url_map[key]
        return f"[citation:{id}]"

    return re.sub(url_pattern, replace_func, prompt)

def format_source(prior_tool_use: list[dict], is_summary: bool = True) -> list:
    """Build citation source list from prior tool uses.

    IMPORTANT: The skip conditions and text extraction logic here MUST stay
    aligned with tool_history_to_prompt(is_summary=True) so that the global
    citation IDs assigned by format_prompt_reference() are identical in both
    functions.  Any divergence causes [citation:N] markers in the summary
    to reference the wrong (or missing) source entry.
    """
    source = []
    source_url_map = {}
    url_map = {}
    DATABASE_TOOLS = ['Drug-Analysis', 'Catalyst-Event-Analysis', 'Clinical-Trial-Result-Analysis']

    for tool_use in prior_tool_use:

        # --- Skip: no result (matches tool_history_to_prompt line 191) ---
        if not tool_use.get('result', None):
            continue

        tool_use_result = ""
        try:
            # --- Skip: User-Question with question (matches line 194) ---
            if tool_use['tool'] == "User-Question" and tool_use.get('question', None):
                continue
            # --- Skip: Self-Reflection / Plan-Sequence (matches line 198, is_plan=False) ---
            if tool_use['tool'] in ['Self-Reflection', 'Plan-Sequence']:
                continue

            # --- Extract text (matches lines 200-203) ---
            if type(tool_use['result']) == str:
                tool_use_result = tool_use['result']
            else:
                tool_use_result = str(tool_use['result'].get('content', '') or tool_use['result'])

            # --- Database tools (matches lines 206-209, only when is_summary=True) ---
            if is_summary and tool_use['tool'] in DATABASE_TOOLS:
                citation_url = format_database_tool_citation(tool_use)
                # tool_history_to_prompt hardcodes www.noahai.co (line 208).
                # Use the same URL for matching; keep env-specific URL for display only.
                match_url = f"https://www.noahai.co/{citation_url}"
                domain = "https://www.noahai.co"
                if settings.ENV == 'staging':
                    domain = "https://staging.noahai.co"
                elif settings.ENV == 'test':
                    domain = "https://test.noahai.co"
                display_url = f"{domain}/{citation_url}"
                source_url_map[_normalize_citation_url(match_url)] = {
                    'id': 0,
                    'url': display_url,
                    'title': tool_use['tool'],
                    'site_name': "noahai.co",
                    'summary': tool_use['tool'],
                }
                tool_use_result += f"\n\n# Reference:\n All above content are from [1]({match_url})\n\n"
        except Exception as e:
            trace = traceback.format_exc()
            logger.info(f"Error in format_source parsing tool use result: {e}, Trace: {trace}")

        # --- Extract citation URLs — always runs, even after exception (matches line 215) ---
        format_prompt_reference(tool_use_result, url_map)

        # --- Collect search_graph.source ---
        if isinstance(tool_use.get('result'), dict):
            search_graph = tool_use['result'].get('search_graph', {})
            if search_graph:
                tool_source = search_graph.get('source', [])
                for link in tool_source:
                    if type(link) != dict:
                        continue
                    url = link.get('url', '')
                    url = url.replace("(", "%28").replace(")", "%29")
                    source_url_map[_normalize_citation_url(url)] = link

    for url, id in url_map.items():
        if url in source_url_map:
            link = source_url_map[url]
            link['id'] = id
            source.append(link)

    source.sort(key=lambda x: x['id'])
    return source

def format_content_citation(prior_tool_use: list[dict], content: str, is_summary: bool = True) -> tuple[str, list]:
    source = format_source(prior_tool_use, is_summary=is_summary)
    content = MindSearchHelper.format_citation(content=content)
    content = MindSearchHelper.convert_citation(url_list=source, content=content)
    content = format_content(content=content)
    return content, source

def format_content(content: str) -> str:
    """If content is wrapped in ```markdown ... ```, strip the opening and closing code fence with regex."""
    if not content or not content.strip():
        return content
    # Match content wrapped with ``` or ```markdown at start and ``` at end
    match = re.match(r"^\s*```(?:markdown)?\s*\n?(.*?)\n?```\s*$", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content


# Sandbox file download link markers (similar to citation system)
_SANDBOX_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^\s\)]*project-sandbox\.oss[^\s\)]*)\)')
_SANDBOX_OUTPUT_HEADER_RE = re.compile(r'\*\*📦 输出文件 / Output Files:\*\*\s*\n?')


def extract_sandbox_file_markers(text: str) -> tuple[str, dict]:
    """Replace sandbox download links with [file:N] markers for summary LLM.

    Returns (processed_text, file_map) where file_map is {N: {'name': str, 'url': str}}.
    """
    file_map = {}

    def _replacer(match):
        n = len(file_map) + 1
        name = match.group(1).lstrip('📎').strip()
        name = unescape_md_filename(name)
        file_map[n] = {'name': name, 'url': match.group(2)}
        return f'[file:{n}]'

    text = _SANDBOX_LINK_RE.sub(_replacer, text)
    if file_map:
        text = _SANDBOX_OUTPUT_HEADER_RE.sub('', text)
    return text, file_map

def resolve_file_markers(content: str, file_map: dict) -> str:
    """Replace [file:N] markers in LLM output with actual download links."""
    if not file_map:
        return content

    def _replacer(match):
        n = int(match.group(1))
        if n in file_map:
            f = file_map[n]
            display = escape_md_filename(f["name"])
            return f'[📎 {display}]({f["url"]})'
        return match.group(0)

    content = re.sub(r'\[file:(\d+)\]', _replacer, content)

    # The prompt instructs the LLM to use [file:N] markers without the filename,
    # but LLMs sometimes append the name anyway. Strip it to avoid duplicates.
    # e.g. "[📎 gene_stats.csv](url) gene_stats.csv" -> "[📎 gene_stats.csv](url)"
    for f in file_map.values():
        raw = re.escape(f["name"])
        esc = re.escape(escape_md_filename(f["name"]))
        name_pat = f"(?:{raw}|{esc})" if raw != esc else raw
        content = re.sub(
            r'(\[📎\s[^\]]*\]\([^\)]+\))\s*' + name_pat,
            r'\1',
            content,
        )

    return content


async def download_sandbox_files(file_map: dict, output_dir: str) -> None:
    """Download sandbox files from presigned URLs into output_dir/sandbox_files/."""
    if not file_map:
        return
    sandbox_dir = os.path.join(output_dir, "sandbox_files")
    os.makedirs(sandbox_dir, exist_ok=True)

    from utils.core.httpx_client import HttpxClientSingleton
    client = HttpxClientSingleton.get_asynclient()

    async def _download_one(entry):
        # Strip description suffix (e.g., "file.csv — 样本QC统计" → "file.csv")
        m = re.match(r'^(.+\.[a-zA-Z0-9]{2,5})(?=[^a-zA-Z0-9.]|$)', entry['name'])
        name = m.group(1) if m else entry['name']
        name = os.path.basename(name.strip()) or f"file_{id(entry)}"
        try:
            resp = await client.get(entry['url'], timeout=60)
            if resp.status_code == 200:
                with open(os.path.join(sandbox_dir, name), 'wb') as fp:
                    fp.write(resp.content)
            else:
                logger.info(f"Failed to download sandbox file {name}: HTTP {resp.status_code}")
        except Exception as e:
            logger.info(f"Error downloading sandbox file {name}: {e}")

    await asyncio.gather(*[_download_one(f) for f in file_map.values()])


def build_planning_prompt(language, user_prompt, prior_tool_use = [], plan = [], feedback=[], MAX_STEPS = 4):
    template = pt_fetcher.get('planning_final_template_cn', planning_final_template_cn) if language == 'zh-CN' else pt_fetcher.get('planning_final_template_en', planning_final_template_en)
    if language == 'zh-CN':
        instructions_prompt = pt_fetcher.get('replanning_input_prompt_cn', replanning_input_prompt_cn) if len(plan)>1 else pt_fetcher.get('planning_input_prompt_cn', planning_input_prompt_cn)
        tool_prompt = pt_fetcher.get('tools_description_cn', tools_description_cn)
    else:
        instructions_prompt = pt_fetcher.get('replanning_input_prompt', replanning_input_prompt) if len(plan)>1 else pt_fetcher.get('planning_input_prompt', planning_input_prompt)
        tool_prompt = pt_fetcher.get('tools_description', tools_description)
    prior_knowledge = tool_history_to_prompt(prior_tool_use, is_plan=True)
    tool_display_names = planning_tool_names_table(resolve_language(language))
    if len(plan)>1:
        instructions_prompt = instructions_prompt.format(
            noah_tools=tool_prompt,
            current_plan=str(plan),
            completed_steps=list({'tool':tool['tool']} for tool in prior_tool_use),
            output_language=language,
            tool_display_names=tool_display_names,
        )
    else:
        instructions_prompt = instructions_prompt.format(
            example=example,
            noah_tools=tool_prompt,
            output_language=language,
            tool_display_names=tool_display_names,
        )
        
    kwargs = {
        'current_date': datetime.now().strftime('%B %d, %Y'),
        'prior_tool_use': prior_tool_use,
        'user_prompt': user_prompt,
        'instructions_prompt': instructions_prompt,
        'prior_knowledge': prior_knowledge,
        'total_steps': MAX_STEPS,
        'user_feedback': feedback,
        'output_language': language,
    }
    filled_template = template.format(**kwargs)
    filled_template += '\n'
    filled_template += """
在规划包含“Self-Reflection”工具的任务计划时, 请严格遵循以下原则: 
Self-Reflection的目的是前瞻性地规划如何在未来评估信息的完整性, 并提出可能需要补充的下一步行动建议。它基于一个明确的前提: 在规划时, 所有工具都尚未执行, 因此绝对没有任何步骤的结果可供评估。
因此, Self-Reflection 步骤的思考逻辑必须是: 根据你目前制定的这个计划本身(即步骤1、2、3…的内容), 当这些工具未来执行后, 我应该从哪些维度去检查收集到的信息是否足够？如果不够, 后续可能需要调用哪些工具来补充？”
禁止你在Self-Reflection中假装已经拥有了信息并对其进行评估。不得使用“✅/已完成/已经覆盖/已收集/结果显示/我们已经获得”等完成态措辞。
    """
    return filled_template

def build_search_prompt(user_prompt, current_tool, prior_tool_use = []):
    users_question = user_prompt
    try:
        parsed = json.loads(user_prompt)
        if isinstance(parsed, dict) and 'original_user_prompt' in parsed:
            users_question = parsed['original_user_prompt']
    except (json.JSONDecodeError, TypeError):
        pass
    reason = current_tool.get('reason', '')
    if reason:
        user_prompt += f"Reason for performing search: {reason}\n"
    current_question = (current_tool.get('params', None) or {}).get('question','') or reason or user_prompt
    query_params = current_tool.get('query_params', '')
    user_prompt = f"{current_question}\n\n"
    if query_params:
        user_prompt += f"query_params: {query_params}\n"
    user_prompt += tool_history_to_prompt(prior_tool_use)
    user_prompt += "\nNote: Please don't make assumptions on data (especially data that can easily be verified such as stock price and NCT ids) and don't make up citations, only use whatever context/data has been provided to you.\n"
    user_prompt += f"\nUser's question:\n{users_question}\n"
    return user_prompt

def build_summary_prompt(user_prompt, current_tool, prior_tool_use=[], language='en-US'):
    if language == 'zh-CN':
        prompt = f'''现在日期：{datetime.now().strftime('%Y-%m-%d')}
请完整地总结全部工具的使用结果并回答用户的原始问题： {user_prompt}。对于引用，尽量保留工具使用结果中的参考链接。
- 引用格式为[citation:id],  id为引用链接id，例如[citation:1][citation:2], 同时使用多个引用的时候请单独列出，如：[citation:1][citation:2][citation:14]。id **必须**是正整数（1, 2, 3, …），严禁使用指南章节号（如 CSCO 5.4）、文档标识（如 pmid:39782672）或任何非数字字符串；若工具结果中出现非数字形式的 citation，请直接丢弃。
- 不要在结尾处集中添加引用，例如：参考资料（引用文献）[citation:1][citation:2][citation:14]
- 数据缺失或有限时，表述要强调搜索范围内：，例如，不要说"没有临床证据"，而是说："搜索的资料中没有找到临床证据"。
- 在必要时绘制表格，并配以详细解释。
- 请不要尝试绘制图表，包括mermaid，vega，graph td等。
**重要** 尽最大的力去包含工具使用结果中的详细信息和数据，使回应丰富且详尽。不要漏过任何重要信息。
'''
# - 在必要时绘制图表，并配以详细解释。使用mermaid或vega绘制图表。
    else:
        prompt = f'''Current date: {datetime.now().strftime('%Y-%m-%d')}
Please comprehensively summarize all tool use results and answer the user's original question: {user_prompt} based on the tool use results. For the citations, try to keep the refer link from the tool use results.
- The citation format is [citation:id], id is the original source id, i.e. [citation:1][citation:2]. For multi citations, please list them one by one, i.e. [citation:1][citation:2][citation:14]. The id MUST be a positive integer (1, 2, 3, …); never a guideline section number (e.g., CSCO 5.4), a document identifier (e.g., pmid:39782672), or any non-numeric string. If tool results contain non-numeric citations, drop them.
- Don't group citations at the end of final response, like: Reference (Future Reading) [citation:1][citation:2][citation:14]
- When data is missing or limited, emphasize the search scope, e.g., instead of saying "no clinical evidence", say: "no clinical evidence found in the searched materials"
- Draw tables wherever necessary, and pair them with detailed explanations.
- Don't try to draw graph, including mermaid, vega, graph td and so on.
**Important** Include as much detailed information and data from tool use results as possible and make the response as rich and lengthy as possible. Do not miss any important information.
'''
# - Draw graphs and tables wherever necessary, and pair them with detailed explanations. Use either mermaid or vega to draw graphs.
    
    prompt += tool_history_to_prompt(prior_tool_use, is_summary=True)
    return prompt

def build_inference_prompt(user_prompt, current_tool, prior_tool_use=[], language='en-US'):
    current_question = (current_tool.get('params', None) or {}).get('question','')

    if language == 'zh-CN':
        prompt = f'''您是"若生科技（Noah AI）"的医疗人工智能助手，擅长搜索和组织信息。您在医疗和金融领域拥有深厚的知识。
现在日期：{datetime.now().strftime('%Y-%m-%d')}
请根据目标：{current_tool.get("reason", "")}、工具使用历史、{f"用户现有问题：{current_question}、" if current_question else ""}用户的原始问题 {user_prompt} 生成回应。'''
    else:
        prompt = f'''You are a medical AI Assistant for `若生科技 (Noah AI)`, adept at searching for and organizing information. You possess profound knowledge in medical and finance fields.
Current date: {datetime.now().strftime('%Y-%m-%d')}
Generate a response considering the goal: {current_tool.get("reason", "")}, the tool use history, {f"the current question: {current_question}, " if current_question else ""}and the users original question {user_prompt}'''
    
    prompt += tool_history_to_prompt(prior_tool_use)
    return prompt

async def build_workflow_prompt(context_data, current_tool, language='en', output_dir='', current_step=0, final_question="", prev_tool_uses=None, plan=[]):
    
    current_tool = copy.deepcopy(current_tool)
    plan = copy.deepcopy(plan)
    for step in plan:
        step.pop('result', None)
        step.pop('params', None)
    
    # Convert the JSON data to Excel format for easier viewing
    if isinstance(context_data, list) and context_data and isinstance(context_data[0], dict):
        # Handle case where the data is a list of dictionaries
        df = pd.DataFrame(context_data)
        # Convert lists to strings for better display in Excel
        for column in df.columns:
            if df[column].apply(lambda x: isinstance(x, list)).any():
                df[column] = df[column].apply(lambda x: ', '.join(x) if isinstance(x, list) and all(isinstance(item, str) for item in x) else x)
        
        if current_tool['tool'] == "Drug-Analysis":
            # Drop 'partner_companies' column if it exists
            if 'partner_companies' in df.columns:
                df = df.drop(columns=['partner_companies'])
                        
            # Rename 'lead_company' to 'company' if it exists
            if 'lead_company' in df.columns:
                df = df.rename(columns={'lead_company': 'company'})
        # Convert column names from snake_case to Title Case With Spaces
        df.columns = [' '.join(word.capitalize() for word in col.split('_')) for col in df.columns]
        
        # Create Excel writer with xlsxwriter engine
        excel_path = os.path.join(output_dir, f"{current_step}_{current_tool['tool']}_data.xlsx")
        os.makedirs(output_dir, exist_ok=True)
        
        with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
            # Write dataframe starting from row 3 (appears as 4th row)
            df.to_excel(writer, index=False, startrow=6)
            
            # Get the xlsxwriter workbook and worksheet objects
            workbook = writer.book
            worksheet = writer.sheets['Sheet1']
            
            # Insert logo in the first cell
            logo_path = 'static/logo-middle.png'
            if os.path.exists(logo_path):
                options = {'x_scale': 0.7, 'y_scale': 0.65, 'x_offset': 50, 'y_offset': 10}  # Scale to 90% of original size
                worksheet.insert_image('A1', logo_path, options)
            else:
                print(f"Warning: Logo file not found at {logo_path}")
                
            arial_format = workbook.add_format({'font_name': '等线'})
            worksheet.set_column(0, 100, None, arial_format)  # Apply Arial to all columns
            # Set the width of the first column to be 6 times the default width
            worksheet.set_column(0, 0, 66, arial_format)  # Default Excel column width is about 8.43 characters (64 pixels)
                                            # so 6x would be around 90 characters wide
            # worksheet.set_column(1, 1, 43, arial_format)  # Default Excel column width is about 8.43 characters (64 pixels)
                                        # so 6x would be around 90 characters wide

            text = "Noah AI-AI Agent Specialized in Life Science"
            text_2 = "https://www.noahai.co/about"
            # Add formatted text headers in rows 2 and 3
            text_format = workbook.add_format({
                'bold': False,
                'font_size': 12,
                'align': 'left',
                'font_name': '等线',
                'valign': 'vcenter'
            })
            url_format = workbook.add_format({
                'bold': False,
                'underline': True,  # Underline the text to indicate it's a URL
                'font_size': 12,
                'align': 'left',
                'valign': 'vcenter',
                'font_name': '等线',
                'font_color': '#467886'
            })

            # Insert the text into cell A2 (row 1, col 0 in zero-based indexing)
            worksheet.write(1, 3, text, text_format)

            # Insert the second text into cell A3 (row 2, col 0 in zero-based indexing)
            worksheet.write(2, 3, text_2, url_format)
            for col_num, column in enumerate(df.columns):
                if col_num < 3:
                    worksheet.set_column(col_num, col_num, 22, arial_format)
                if col_num >= 3:  # Column 3 is index 2 (zero-based)
                    # Get the maximum length in this column
                    # Handle NaN and float values by filling NaN and converting to string first
                    column_str = df[column].fillna('').astype(str)
                    max_length = column_str.map(len).max() if len(column_str) > 0 else 0
                    column_width = min(
                        22,
                        max(max_length, len(column))
                    )
                    # Add some padding
                    column_width += 2
                    worksheet.set_column(col_num, col_num, column_width, arial_format)

        
        print(f"- {excel_path} saved successfully.")
    # save_to_file(context_data, output_dir, f"{current_step}_{current_tool['tool']}_data.json")
    tag_mapping = {"Drug-Analysis": "drug_data>", "Clinical-Trial-Result-Analysis": "clinical_trial_data>", "Catalyst-Event-Analysis":"catalyst_event_data>"}
    drug_tool_prompt = 'Try to list out all the drug names provided where appropriate. ' if current_tool['tool'] == "Drug-Analysis" else ''
    drug_tool_prompt = ''
    extra_explanation = f'(Please note the data selected is limited due to token limit, so the tool may not be able to answer the question completely. Take into account this limitation when generating the response.' 
    if current_tool['tool'] == "Drug-Analysis" and current_tool['params'].get('location', []):
        extra_explanation += f" Also, the location is limited to {current_tool['params']['location']})"
    else: 
        extra_explanation += ')'
    
    background_prefix = background_prefix_map[current_tool['tool']] if current_tool['tool'] in background_prefix_map else ''
    background = f"""
{background_prefix}{extra_explanation}
<{tag_mapping[current_tool['tool']]}
{context_data}
</{tag_mapping[current_tool['tool']]}
{drug_tool_prompt if drug_tool_prompt else ''}""" if context_data else data_empty_prompt_cn if language == 'zh-CN' else data_empty_prompt
    body_user_prompt = f"""
<Original Prompt>
{final_question}
</Original Prompt>
<Tool Purpose>
We are using tool {current_tool['tool']} for the purpose of: {current_tool.get('reason', '')}
</Tool Purpose>
"""
    requirements_prompt = """Requirements:
1. Your goal is not to answer the users original question directly, but rather try to satisfy the <Tool Purpose>.
2. Do not make assumptions on data or make up data, only use whatever context/data has been provided to you.
3. State the limitations of the data provided if there are any."""
    # plan_prompt = f"Current plan: {json.dumps(plan, separators=(',', ':'), ensure_ascii=False)}\n\n" if plan else ''
    step_body = {
        "user_prompt": f"{body_user_prompt}{requirements_prompt}",
        "history_messages": [],
        "agent":"mindsearchworkflowrefer",
        "skip_followup": True,
        "params":{
            "language": language,
            "model": "",
            "enable_rag": False,
            "background": background,
            },
        "is_hitl": True
    }
    if prev_tool_uses and context_data:
        pattern = r'(?:[#]+\s+[^\n]+\s*)?```vega[\s\S]*?```'
        # Replace all occurrences with an empty string
        text = tool_history_to_prompt(prev_tool_uses)
        cleaned_text = re.sub(pattern, '', text)
        step_body['params']['background'] += f'\n{cleaned_text}'
    return step_body

# async def perform_search(user_prompt, current_tool, prior_tool_use = [], language='en'):
#     search_prompt = build_search_prompt(user_prompt, {})
#     step_body = {
#         "user_prompt": search_prompt,
#         "history_messages": [],
#         "agent": "mindsearch",
#         "skip_followup": True,
#         "params":{
#             "language": language,
#             "model": "",
#             "enable_rag": True,
#             }
#     }
#     agent = MindSearchAgent()
#     generator = agent.start_wo_dump(**step_body)   
#     latest_chunk = ''
#     async for chunk in generator:
#         if not chunk:
#             continue
#         if type(chunk) == dict:
#             latest_chunk = chunk.get('content', '')
#         elif type(chunk) == str:
#             latest_chunk = chunk
#     return latest_chunk

async def detect_computation_intent() -> dict:
    from llm.composite_models import Compositeo3
    from pydantic import BaseModel, Field
    from utils.core.get_json_schema import get_openai_json_schema_v3

    class IntentInputSchema(BaseModel):
        """意图识别输入参数"""
        needs_computation: bool = Field(description="是否需要复杂计算")
        computation_type: str = Field(description="计算类型，如数学计算/数据可视化/算法实现/统计分析/金融建模")
        computation_task: str = Field(description="具体的计算任务描述和任务的参数,任务参数是必须存在的，如果没有请再仔细查看搜索结果摘要")
        reasoning: str = Field(description="判断理由")
        params: str = Field(description="基于用户问题，在搜索结果提取代码运行所必须的参数，参数为具体的数据，以便代码执行，此字段禁止为空")

    intent_prompt = f"""
        # 你是一个意图识别专家。请分析用户问题和搜索结果，判断是否需要复杂计算，请以中文回答。

        ## 用户问题分析
        请仔细分析以下用户问题和搜索结果，判断是否需要复杂计算：
        **用户问题**: 我想计算一下5年的利率

        **搜索结果摘要**:5年的利率是5%"
        """
    schema = get_openai_json_schema_v3(IntentInputSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    intent_result = await function_call_with_retry(Compositeo3(), user_prompt=intent_prompt, tools=schema, tool_choice=tool_choice)
    print(intent_result)
    return intent_result

def build_inference_prompt_v2(
    user_prompt: str,
    current_tool,
    language: str,
    prior_tool_use=[],
    attachment_chunk: str = '',
) -> tuple[str, str]:

    final_user_prompt = inference_input_prompt_v2.format(
        tool_use_history=tool_history_to_prompt(prior_tool_use),
        attachments=attachment_chunk,
        current_datetime=datetime.now().strftime('%Y-%m-%d'),
        output_langauge=language,  # 注意：模板中使用的是 output_langauge（拼写错误）
        goal=current_tool.get('reason', '') if isinstance(current_tool, dict) else '',
        user_prompt=user_prompt,
    )
    return inference_template_v2, final_user_prompt

def build_planning_prompt_v2(
    language: str,
    user_prompt: str,
    MAX_STEPS: int = 4
) -> tuple[str, str]:
    r"""
    Build planning prompt for planning agent v5.
    Deprecate prior_tool_use, plan, feedback, since they are designed for human-in-loop mode. So far we don't allow user interaction in planning agent v5.
    """

    tool_display_names = planning_tool_names_table(resolve_language(language))
    plan_prompt = planning_final_template_v2.format(
        total_steps=MAX_STEPS,
        tools=tools_description_v2,
        examples=example,
        current_datetime=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        output_langauge=language,
        user_prompt=user_prompt,
        tool_display_names=tool_display_names,
    )
    return claude_plan_system_prompt, plan_prompt
    

if __name__ == "__main__":
    asyncio.run(detect_computation_intent())

