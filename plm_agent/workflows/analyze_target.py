import json
import asyncio
import logging
from datetime import datetime
from pathlib import Path
import re
import requests

from pydantic import BaseModel, Field
from typing import Optional, AsyncGenerator, Any
import contextlib

from agent.human_in_loop.constants import search_routing
from agent.explore.mindsearch_agent_v3_pubmed import MindSearchPubMedHitlAgent
from llm.gcp_models import CompositeClaude
from config import api_config
from agent.explore.mindsearch_clinical_guidance_agent import MindSearchClinicalGuideline
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import build_search_prompt, function_call_with_retry
from workflows.analyze_target_prompt import horizontal_comparison_of_indications_pubmed_prompt, catalyst_news_prompt, catalyst_news_prompt_v2, catalyst_news_prompt_v4, catalyst_news_prompt_v5, catalyst_news_prompt_v6, catalyst_news_prompt_v7, catalyst_news_prompt_v8,  catalyst_news_prompt_v9, catalyst_news_prompt_10, trial_result_prompt, trial_result_prompt_v2, combined_table_to_markdown_prompt, epidemiology_and_gold_standard_of_treatment_pubmed_prompt, extract_top_10_drug_and_top_5_indication_prompt, extract_top_relevant_indications_prompt, guide_kwargs, prohibited_prompt, pubmed_biological_function_translational_medicine_prompt, pubmed_depth_analysis_of_drugs_prompt, pubmed_depth_analysis_of_drugs_prompt_v2, pubmed_mechanism_of_action_of_target_biology_prompt, pubmed_within_6_months_prompt, split_table_prompt, summary_epidemiology_and_gold_standard_of_treatment_prompt, target_news_search_prompt, trial_comparison_prompt, trial_comparison_prompt_v3, trial_comparison_prompt_v4, trial_comparison_prompt_v5, trial_comparison_prompt_v6, web_search_prompt, news_search_prompt, medical_search_prompt, extract_indications_prompt, target_in_indication_prompt, drug_prompt, summarize_for_indications_prompt, merge_recent_progresses_prompt, trial_comparison_prompt_v7


INDICATION_CONCURRENCY = 5  # 控制同时跑多少个 indication 子任务

def _retry_request_post(url, data_json: dict=None, retry=3, timeout=2, headers=None):
    latest_e = Exception("Request timed out")
    for _ in range(retry):
        try:
            if data_json:
                response = requests.post(
                    url, json=data_json, headers=headers, timeout=timeout,
                )
            else:
                response = requests.post(url, timeout=timeout)
            break
        except requests.exceptions.Timeout as e:
            pass
    else:
        raise latest_e
    try:
        return response.json()
    except:
        return response


def _unwrap_data_access(response, version: str):
    """v2 wraps payload as {code, message, data}; v1 returns flat. Return flat dict either way."""
    if version == 'v2' and isinstance(response, dict) and 'data' in response:
        if response.get('code', 0) != 0:
            logging.getLogger(__name__).warning(
                f"data_access v2 error: code={response.get('code')} msg={response.get('message')}"
            )
        return response.get('data') or {}
    return response

async def search_clinical_trial(filters, version: str = 'v1'):
    """
    搜索临床试验

    filters: json格式，示例如下
        {
            "filters": {
                "drug_modality": {
                    "data": [],
                    "logic": "or"
                },
                "target": {
                    "data": [
                        "SCA-1"
                    ],
                    "logic": "or"
                }
            },
            "page": 1,
            "limit": 10,
            "event_id": null
        }
    """
    # noah_access_token = '29a976517bc211e1e69fe106e5b6560dced14b72'
    # headers = {
    #     'Authorization': f'Token {noah_access_token}',
    #     'Content-Type': 'application/json'
    # }
    noah_data_access_host = api_config.NOAH_DATA_ACCESS_HOST
    clinical_trial_url = f"{noah_data_access_host}/api/{version}/items/clinical_trial/"
    # clinical_trial_url = 'https://test.noahai.co/api/workflow/clinical-trial/'
    response = _retry_request_post(
        url=clinical_trial_url,
        data_json=filters,
        # headers=headers
    )
    return _unwrap_data_access(response, version)


async def search_drug(filters, version: str = 'v1'):
    """
    药物管线搜索

    {
        "filters": {
            "location": [
                "USA",
                "China"
            ],
            "drug_modality": {
                "data": [],
                "logic": "or"
            },
            "target": {
                "data": [
                    "ALK receptor tyrosine kinase(CD246, ALK, NBLST3, ALK1)"
                ],
                "logic": "or"
            }
        },
        "page": 1,
        "limit": 10,
        "event_id": null
    }
    """
    
    noah_data_access_host = api_config.NOAH_DATA_ACCESS_HOST
    clinical_trial_url = f"{noah_data_access_host}/api/{version}/items/drug/"
    response = _retry_request_post(
        url=clinical_trial_url,
        data_json=filters
    )
    return _unwrap_data_access(response, version)


class ExtractIndicationsSchema(BaseModel):
    indications: list[str] = Field(description="List of indications, At most five")

class ExtractTop10DrugAndTop5IndicationSchema(BaseModel):
    top10_drug: list[str] = Field(description="List of top 10 drug")
    top5_indication: list[str] = Field(description="List of top 5 indication")

def get_extract_top_relevant_indications_schema(target):
    """
    返回包含target变量的Schema
    """
    class ExtractTopRelevantIndicationsSchema(BaseModel):
        indications: list[str] = Field(
            description=f"请输出与指定**药物作用靶点（{target}）**最相关的五个适应症，列表形式，只输出疾病名称，不要输出与靶点的简要关联理由。"
        )
    return ExtractTopRelevantIndicationsSchema

async def run_agent_generic(
    tool_name: str,
    query: str,
    *,
    language: str = 'en',
    prompt_template: Optional[str] = None,          # 例如 "Query The latest progress of {target} in the news."
    use_build_prompt: bool = True,                  # 是否用 build_search_prompt 包装
    agent_cls_override: Optional[type] = None,      # 指定 Agent 类（如 PubMed 临时 Agent）
    agent_name_override: Optional[str] = None,      
    enable_rag: bool = True,
    is_hitl: bool = True,
    agent_init_kwargs: Optional[dict] = None,        # 添加有控制器的类的参数
    template_kwargs: dict = None,  # 新增参数
) -> str:
    if agent_cls_override:
        agent_cls = agent_cls_override
        agent_name = agent_name_override or ''
    else:
        agent_cls, agent_name = search_routing.get(tool_name)

    agent = agent_cls(**(agent_init_kwargs or {}))

    current_tool = {'tool': tool_name, 'params': {'question': query}}
    if template_kwargs:
        base = prompt_template.format(**template_kwargs) if prompt_template else query
    else:
        base = prompt_template.format(target=query) if prompt_template else query
    # print('base', base)
    user_prompt = build_search_prompt(base, current_tool, prior_tool_use=[]) if use_build_prompt else base
    print('user_prompt', user_prompt)
    step_body = {
        "user_prompt": user_prompt,
        "history_messages": [],
        "agent": agent_name,
        "skip_followup": True,
        "params": {
            "language": language,
            "model": "",
            "enable_rag": enable_rag,
            "is_hitl": is_hitl
        }
    }

    async for chunk in agent.start_wo_dump(**step_body):
        if isinstance(chunk, dict):
            content = chunk.get('content') or ''
            if content:
                yield content


async def run_drug_agent(query: str, language: str = 'en') -> str:
    # Drug-Analysis
    async for content in run_agent_generic(
        'Drug-Analysis',
        query,
        language=language,
        prompt_template=drug_prompt
    ):
        yield content

async def run_clinical_trial_result_analysis_agent(query: str, language: str = 'en') -> str:
    # Clinical-Trial-Result-Analysis
    async for content in run_agent_generic(
        'Clinical-Trial-Result-Analysis',
        query,
        language=language,
    ):
        yield content

async def run_news_agent(query: str, language: str = 'en', prompt_template: str = '') -> str:
    # News-Search
    async for content in run_agent_generic(
        'News-Search',
        query,
        language=language,
        # prompt_template="Query The latest progress of {target} in the news."
        prompt_template=prompt_template
    ):
        yield content


async def run_web_agent(query: str, language: str = 'en', prompt_template: str = '') -> str:
    # Web-Search
    async for content in run_agent_generic(
        'Web-Search', 
        query,
        language=language,
        # prompt_template="Query {target} bd licensing deals"
        prompt_template=prompt_template
    ):
        yield content

async def run_medical_search_agent(query: str, language: str = 'en', prompt_template: str = '') -> str:
    # Medical-Search
    async for content in run_agent_generic(
        'Medical-Search',
        query,
        language=language,
        use_build_prompt=False,
        prompt_template=prompt_template
    ):
        yield content

async def run_pubmed_agent(query: str, language: str = 'en', prompt_template: str = '', template_kwargs: dict = dict()) -> str:
    # Pubmed-Search
    async for content in run_agent_generic(
        'MindSearchPubMedHitlAgent',
        query,
        language=language,
        prompt_template=prompt_template,
        use_build_prompt=False,
        agent_cls_override=MindSearchPubMedHitlAgent,
        agent_name_override='',
        # agent_init_kwargs={'use_super_fetch': True},
        template_kwargs=template_kwargs
    ):
        yield content



async def target_for_indications(text: str, language: str = 'en') -> list:
    """抽取适应症列表"""
    llm = CompositeClaude()
    schema = get_openai_json_schema_v3(ExtractIndicationsSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=extract_indications_prompt.format(text=text),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3
        )
        
        return result.get("indications")
    except Exception as e:
        raise Exception(f"靶点分析服务异常: {str(e)}")


async def target_for_indications_v2(target: str, language: str = 'en') -> list:
    """抽取适应症列表"""
    llm = CompositeClaude()
    schema = get_openai_json_schema_v3(ExtractIndicationsSchema)
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=extract_indications_prompt.target(text=target),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3
        )
        
        return result.get("indications")
    except Exception as e:
        raise Exception(f"靶点分析服务异常: {str(e)}")


async def summarize_for_indications(
    query: str,
    language: str,
    done: dict[str, asyncio.Event],
    queue: asyncio.Queue,
    results: dict[str, str],
    producer
):
    """
    为适应症提取提供LLM总结
    """
    
    try:
        # 依赖医学搜索和临床试验结果
        await asyncio.gather(
            done["run_medical_search_agent_result"].wait(),
            done["run_clinical_trial_result_analysis_agent_result"].wait()
        )
        
        medical_result = results.get("run_medical_search_agent_result", "")
        clinical_result = results.get("run_clinical_trial_result_analysis_agent_result", "")
        
        llm = CompositeClaude()
        summarize_prompt = summarize_for_indications_prompt.format(
            target=query,
            medical_result=medical_result,
            clinical_result=clinical_result
        )
        # 构造全量流
        async def summarize_generator():
            result = str()
            async for chunk in llm.stream_call(sys_prompt=summarize_prompt):
                result += chunk
                yield result
        
        await producer("clincial_results", summarize_generator())
        
    except Exception as e:
        await queue.put({"type": "error", "task": "clincial_results", "error": str(e)})

async def extract_indications_task(
    query: str,
    language: str,
    done: dict[str, asyncio.Event],
    queue: asyncio.Queue,
    results: dict[str, str],
    indications_ready: asyncio.Event
) -> list[str]:
    """
    indications 任务：依赖LLM总结完成才启动
    返回提取的适应症列表
    """
    indications = []
    try:
        # 等待临床试验和医学搜索总结完成
        await done["clincial_results"].wait()
        
        summary_result = results.get("clincial_results", "")
        
        # 提取适应症
        lst = await target_for_indications(text=summary_result, language=language)
        indications = lst or []
                
        await queue.put({"type": "partial", "task": "indications", "data": json.dumps(indications, ensure_ascii=False)})
    except Exception as e:
        await queue.put({"type": "error", "task": "indications", "error": str(e)})
        indications = []
    finally:
        indications_ready.set()
        await queue.put({"type": "end", "task": "indications"})
    
    return indications

async def launch_indication_jobs(
    query: str,
    language: str,
    indications: list[str],
    indications_ready: asyncio.Event,
    queue: asyncio.Queue,
    running_labels: set[str],
    producer,
    done: dict[str, asyncio.Event],
    results: dict[str, str]
):
    """
    启动适应症子任务
    """
    await indications_ready.wait()
    
    if not indications:
        return

    sem = asyncio.Semaphore(INDICATION_CONCURRENCY)

    # 动态添加每个适应症子任务到 running_labels
    for ind in indications:
        label = f"indication::{ind}"
        running_labels.add(label)
        done[label] = asyncio.Event()

    async def run_one_indication(indication: str):
        # 启动单个适应症llm总结
        label = f"indication::{indication}"
        
        async def agen():
            async for chunk in run_medical_search_agent(
                query=target_in_indication_prompt.format(target=query, indication=indication) + '\n' + prohibited_prompt,
                language=language,
            ):
                yield chunk
                
        async with sem:
            await queue.put({"type": "partial", "task": label, "data": ""})
            try:
                await producer(label, agen())
            except Exception as e:
                await queue.put({"type": "error", "task": label, "error": str(e)})

    tasks = [asyncio.create_task(run_one_indication(ind)) for ind in indications]
    await asyncio.gather(*tasks, return_exceptions=True)


def _find_or_create_outputs_dir() -> Path:
    """寻找或创建 outputs 目录（向上递归查找；找不到就创建）。"""
    here = Path(__file__).resolve()
    # 从当前文件向上查找已存在的 outputs
    for p in here.parents:
        c = p / "outputs"
        if c.exists() and c.is_dir():
            return c
    try_root = here.parents[2] if len(here.parents) >= 3 else Path.cwd()
    out = try_root / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    return out

def _build_results_markdown(target: str, results: dict, summary_text: str, language: str = 'zh-CN') -> str:
    """把顶层任务 + 动态适应症 + 最终总结 组织成 Markdown 文本。"""
    title_map = {
        "run_news_agent_result": "【新闻/资讯综述】（已合并【最新进展综合报告】）",
        "run_medical_search_agent_result": "【靶点与机制综述】（已合并进【临床结果】）",
        "run_web_agent_result": "【网页搜索综述】",
        "run_clinical_trial_result_analysis_agent_result": "【临床试验结果综述】（已合并进【临床结果】）",
        "drug_result": "【药物管线综述】",
        "pubmed_biological_function_translational_medicine_result": "【作用机制】",
        "pubmed_within_6_months_result": "【近6个月PubMed最新进展】（已合并【最新进展综合报告】）",
        "clincial_results": "【临床结果】",  # 合并任务：医学搜索 + 临床试验结果
        "recent_progresses_merged": "【最新进展综合报告】",  # 合并任务：新闻 + PubMed近6个月
    }
    preface = f"# {target} 综合报告\n\n"
    preface += """- 输出语言: 中文\n- 请按章节阅读；末尾附"最终总结："\n\n"""

    parts = [preface]

    # 包含所有任务：3个保留的原始任务 + 4个已合并的原始任务 + 2个合并任务
    for key in [
        "drug_result",
        "pubmed_biological_function_translational_medicine_result",
        "run_web_agent_result",
        "run_medical_search_agent_result",  # 已合并
        "run_clinical_trial_result_analysis_agent_result",  # 已合并
        "clincial_results",  # 合并任务：医学搜索 + 临床试验结果
        "run_news_agent_result",  # 已合并
        "pubmed_within_6_months_result",  # 已合并
        "recent_progresses_merged",  # 合并任务：新闻 + PubMed近6个月
    ]:
        content = results.get(key, "")
        if content:
            parts.append(f"## {title_map[key]}\n\n{content}\n")

    # 动态适应症
    indication_results = {}
    for k, v in results.items():
        if k.startswith("indication::"):
            name = k.split("::", 1)[1]
            indication_results[name] = v
    
    for name in sorted(indication_results.keys()):
        content = indication_results[name]
        if content:
            parts.append(f"## 适应症：{name}\n\n以下是适应症「{name}」的医学搜索结果：\n\n{content}\n")

    # 最终总结
    parts.append(f"## 最终总结\n\n最终总结：\n{summary_text}\n")
    return "\n".join(parts)

def _safe_filename(name: str) -> str:
    return "".join(ch if ch not in r'\/:*?"<>|' else "_" for ch in name)


async def merge_recent_progresses_task(
    query: str,
    language: str,
    done: dict[str, asyncio.Event],
    queue: asyncio.Queue,
    results: dict[str, str],
    producer
):
    """
    合并新闻搜索和PubMed近6个月搜索的结果
    """
    
    try:
        # 依赖新闻搜索和pubmed
        await asyncio.gather(
            done["run_news_agent_result"].wait(),
            done["pubmed_within_6_months_result"].wait()
        )
        
        news_result = results.get("run_news_agent_result", "")
        pubmed_result = results.get("pubmed_within_6_months_result", "")
                
        llm = CompositeClaude()
        merge_prompt = merge_recent_progresses_prompt.format(
            target=query,
            news_result=news_result,
            pubmed_result=pubmed_result
        )
        
        async def merge_generator():
            result = str()
            async for chunk in llm.stream_call(sys_prompt=merge_prompt):
                result += chunk
                yield result
        
        await producer("recent_progresses_merged", merge_generator())
        
    except Exception as e:
        await queue.put({"type": "error", "task": "recent_progresses_merged", "error": str(e)})

 

def build_target_workflow_prompt(target: str, results: dict, language: str = 'zh-CN') -> str:
    """
    构造"顶层任务 + 动态适应症"的综合总结提示词。
    - target: 研究靶点（如 "ALK"）
    - results: 运行结束后收集的结果字典（包含顶层任务与 indication::xxx 的内容）
    - language: 'cn' | 'en' 等
    返回：单一字符串，用于喂给 LLM（建议作为 user_prompt）。
    """
    # 顶层任务 -> 显示标题 的映射
    title_map = {
        "run_web_agent_result": "【网页搜索综述】",
        "drug_result": "【药物管线综述】",
        "pubmed_biological_function_translational_medicine_result": "【作用机制】",
        "clincial_results": "【临床结果】",  # 合并任务：医学搜索 + 临床试验结果
        "recent_progresses_merged": "【最新进展综合报告】",  # 合并任务：新闻 + PubMed近6个月
    }

    # 输出语言与风格指令（可按需简化）
    if language == 'zh-CN':
        preface = (
            f"你是一名医疗研究分析员，请基于以下关于靶点\"{target}\"的多源材料，产出面向专业人士的综合报告。\n"
            "- 要求：分章节清晰、逻辑自洽、观点有证据支撑；尽量保留原始段落中的链接/引用标识；必要时列出表格；中文输出。\n"
            "- 重点：先给整体结论，再分适应症（indication）展开，适应症下需包含\"结论—关键依据—证据来源—局限与下一步\"。\n"
        )
    else:
        preface = (
            f"You are a medical research analyst. Based on the following multi-source materials about target \"{target}\", "
            "produce a professional synthesis with structured sections, evidence-backed claims, preserved citations/links where possible."
        )

    sections = [preface]

    # 1) 顶层任务：只包含保留的3个原始任务 + 2个合并任务
    for key in [
        "run_web_agent_result",
        "drug_result",
        "pubmed_biological_function_translational_medicine_result",
        "clincial_results",  # 合并任务
        "recent_progresses_merged",  # 合并任务
    ]:
        content = results.get(key, "")
        if content:
            sections.append(f"{title_map[key]}\n{content}")

    # 2) 动态适应症：把 indication::XXXX 拆成【适应症：XXXX】并加前缀语句
    for k, v in results.items():
        if not k.startswith("indication::"):
            continue
        name = k.split("::", 1)[1]
        sections.append(
            f"【适应症：{name}】\n"
            f"以下是适应症「{name}」的医学搜索结果：\n{v}"
        )

    # 3) 综合任务要求（促使 LLM 统一提炼）
    tail = (
        "【请输出】\n"
        "一、总体结论（3-6条，覆盖疗效格局、关键证据、未满足需求）\n"
        "二、适应症分章（逐一）\n"
        "三、耐药与序贯策略（若与靶点密切相关）\n"
        "四、建议补充的检索方向（若存在证据空白）\n"
    )
    sections.append(tail)

    return "\n\n".join(sections)


def remove_think_tags(text: str) -> str:
    """
    删除文本中所有的 <think>...</think> 标签及其内容
    """
    if not text:
        return text
    
    # 使用正则表达式匹配 <think>...</think> 标签及其内容
    # re.DOTALL 让 . 匹配包括换行符在内的所有字符
    pattern = r'<think>.*?</think>'
    cleaned_text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # 清理多余的空行（连续的空行合并为一个）
    cleaned_text = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned_text)
    
    return cleaned_text.strip()

def clean_results_for_output(results: dict[str, str]) -> dict[str, str]:
    """
    清理 results 字典中所有文本的 <think> 标签
    """
    cleaned_results = {}
    for key, value in results.items():
        if isinstance(value, str):
            cleaned_results[key] = remove_think_tags(value)
        else:
            cleaned_results[key] = value
    return cleaned_results

def save_to_file(filename: str, content: str, ext: str = "md") -> str:
    """
    通用写文件：写入到 outputs 目录下
    返回写入后的绝对路径字符串
    """
    output_dir = _find_or_create_outputs_dir()
    safe_name = _safe_filename(filename)
    file_path = output_dir / f"{safe_name}.{ext}"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content or "")
    return str(file_path)


def save_markdown_report(target: str, results: dict[str, str], summary_text: str, language: str = 'en') -> str:
    """
    将工作流结果写成 Markdown 文件，路径与命名保持与 run_target_analysis_stream 一致：
    文件名：{_safe_filename(target)}测试.md
    返回写入后的绝对路径字符串
    """
    # 1) 清理 <think> 标签，保持现有行为一致
    cleaned_results = clean_results_for_output(results)

    # 2) 构建 Markdown 文本
    md = _build_results_markdown(
        target=target,
        results=cleaned_results,
        summary_text=summary_text,
        language=language
    )

    # 3) 写入文件
    output_dir = _find_or_create_outputs_dir()
    filename = f"{_safe_filename(target)}测试.md"
    file_path = output_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md or "")

    return str(file_path)


async def run_target_analysis_stream(query: str, language: str = 'en') -> AsyncGenerator[str, None]:
    """靶点分析主函数v1"""
    queue: asyncio.Queue = asyncio.Queue()
    results: dict[str, str] = {}
    done: dict[str, asyncio.Event] = {}
    indications_ready = asyncio.Event()

    # 7个顶层任务
    jobs = [
        ("run_medical_search_agent_result", run_medical_search_agent(query=query, language=language, prompt_template=medical_search_prompt)),
        ("run_clinical_trial_result_analysis_agent_result", run_clinical_trial_result_analysis_agent(query=query, language=language)),
        ("run_news_agent_result", run_news_agent(query=query, language=language, prompt_template=news_search_prompt)),
        ("pubmed_within_6_months_result", run_pubmed_agent(query=query, language=language, prompt_template=pubmed_within_6_months_prompt)),
        ("run_web_agent_result", run_web_agent(query=query, language=language, prompt_template=web_search_prompt)),
        ("drug_result", run_drug_agent(query=query, language=language)),
        ("pubmed_biological_function_translational_medicine_result", run_pubmed_agent(query=query, language=language, prompt_template=pubmed_biological_function_translational_medicine_prompt)),
    ]
    
    # 为所有任务创建完成事件
    for label, _ in jobs:
        done[label] = asyncio.Event()
    
    # 为额外的任务创建完成事件，两个合并任务
    done["clincial_results"] = asyncio.Event()
    done["recent_progresses_merged"] = asyncio.Event()

    # 添加适应症总结任务和合并任务到running_labels
    running_labels: set[str] = {label for label, _ in jobs} | {"indications", "clincial_results", "recent_progresses_merged"}

    async def producer(label: str, agen):
        """生产者函数，用于处理任务的输出"""
        last = ""
        try:
            async for chunk in agen:
                if chunk:
                    last = chunk
                    await queue.put({"type": "partial", "task": label, "data": chunk})
            results[label] = last
            if label in done:
                done[label].set()
            await queue.put({"type": "end", "task": label})
        except asyncio.CancelledError:
            await queue.put({"type": "error", "task": label, "error": "cancelled"})
            if label in done:
                done[label].set()
            raise
        except Exception as e:
            await queue.put({"type": "error", "task": label, "error": str(e)})
            if label in done:
                done[label].set()

    async def summarize_for_indications_wrapper():
        """创建包装函数 合并医学搜索和临床试验结果"""
        await summarize_for_indications(
            query=query,
            language=language,
            done=done,
            queue=queue,
            results=results,
            producer=producer
        )

    async def indications_pipeline():
        """先提取适应症，然后启动适应症总结子任务"""
        
        # 第一步：提取适应症
        extracted_indications = await extract_indications_task(
            query=query,
            language=language,
            done=done,
            queue=queue,
            results=results,
            indications_ready=indications_ready
        )
        
        # 第二步：启动适应症总结子任务
        if extracted_indications:
            await launch_indication_jobs(
                query=query,
                language=language,
                indications=extracted_indications,
                indications_ready=indications_ready,
                queue=queue,
                running_labels=running_labels,
                producer=producer,
                done=done,
                results=results
            )
        else:
            pass

    async def merge_recent_progresses_wrapper():
        """创建包装函数 合并新闻和pubmed"""
        await merge_recent_progresses_task(
            query=query,
            language=language,
            done=done,
            queue=queue,
            results=results,
            producer=producer
        )

    tasks = [asyncio.create_task(producer(label, agen)) for label, agen in jobs]
    tasks.append(asyncio.create_task(indications_pipeline()))
    tasks.append(asyncio.create_task(summarize_for_indications_wrapper()))
    tasks.append(asyncio.create_task(merge_recent_progresses_wrapper()))

    try:
        while True:
            event = await queue.get()
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if event["type"] in ("end", "error"):
                task = event.get("task")
                if task in running_labels:
                    running_labels.remove(task)
                    if not running_labels:
                        break
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
    

    # 生成最终总结
    summary_result = str()
    llm = CompositeClaude()
    try:
        summary_prompt = build_target_workflow_prompt(target=query, results=results, language=language)
        async for chunk in llm.stream_call(sys_prompt=summary_prompt):
            summary_result += chunk
            yield json.dumps({"type": "summary", "summary": summary_result}, ensure_ascii=False) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "task": "llm_summary", "error": str(e)}, ensure_ascii=False) + "\n"

    cleaned_results = clean_results_for_output(results)
    
    # 写入 Markdown 文件
    try:
        output_dir = _find_or_create_outputs_dir()
        filename = f"{_safe_filename(query)}测试.md"
        file_path = output_dir / filename
        md = _build_results_markdown(target=query, results=cleaned_results, summary_text=summary_result, language=language)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md)
    except Exception as e:
        yield json.dumps({"type": "error", "task": "write_file", "error": str(e)}, ensure_ascii=False) + "\n"

    yield json.dumps({"type": "done", "summary": summary_result, "file_path": str(file_path)}, ensure_ascii=False) + "\n"


async def test_pubmed_or_medical_agent(query, language):
    # 
    import asyncio, contextlib

    queue = asyncio.Queue()
    done = 0
    last_pubmed = ''
    last_medical = ''

    async def pump(label, agen):
        nonlocal done, last_pubmed, last_medical
        try:
            async for content in agen:
                if content:
                    if label == "PubMed":
                        last_pubmed = content
                    else:
                        last_medical = content
                # 保持原有“全量流式返回”
                await queue.put(f"[{label}] {content}")
        finally:
            done += 1

    pubmed_gen = run_pubmed_agent(
        query=query,
        language=language,
        prompt_template=pubmed_mechanism_of_action_of_target_biology_prompt
    )
    medical_gen = run_medical_search_agent(
        query=query,
        language=language,
        prompt_template=pubmed_mechanism_of_action_of_target_biology_prompt
    )

    t1 = asyncio.create_task(pump("PubMed", pubmed_gen))
    t2 = asyncio.create_task(pump("Medical", medical_gen))

    try:
        # 持续从队列取并向外流式返回，直到两个源都结束且队列清空
        while done < 2 or not queue.empty():
            item = await queue.get()
            yield item
    finally:
        # 结束后仅写“最后一次内容”到两个文件
        # 同文件已有写文件函数，假设为 save_to_file(name: str, content: str)
        try:
            if last_pubmed:
                save_to_file(f"Pubmed {query}", last_pubmed)
            if last_medical:
                save_to_file(f"Medical {query}", last_medical)
        except Exception:
            pass
        for t in (t1, t2):
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t


async def test_drug_pubmed_agent(query, language):
    """药品深度分析v1"""
    last_chunk = ''

    async for chunk in run_pubmed_agent(
        query=query,
        language=language,
        prompt_template=pubmed_depth_analysis_of_drugs_prompt
    ):
        yield chunk
        last_chunk = chunk

    save_to_file(f"drug {query}", last_chunk)
    
async def epidemiology_and_gold_standard_of_treatment_v2(target, indication, language):
    """
    适应症 靶点 pubmed
    """
    last_chunk = ''
    async for chunk in run_pubmed_agent(
        query=target,
        language=language,
        prompt_template=epidemiology_and_gold_standard_of_treatment_pubmed_prompt,
        template_kwargs={'target': target, 'indication': indication}
    ):
        yield chunk
    #     last_chunk = chunk

    # save_to_file(f"pubmed 靶点适应症 {target} {indication}", last_chunk)

async def test_guideline_agent(target, indication, language):
    """
    指南
    """
    last_chunk = ''
    user_prompt = epidemiology_and_gold_standard_of_treatment_pubmed_prompt.format(target=target, indication=indication)
    agent = MindSearchClinicalGuideline()
    async for chunk in agent.start_wo_dump(user_prompt=user_prompt, **guide_kwargs):
        if isinstance(chunk, dict):
            content = chunk.get('content') or ''
            if content:
                yield content
    #             last_chunk = content
    # last_chunk = remove_think_tags(last_chunk)
    # save_to_file(f"guideline 靶点适应症 {target} {indication}", last_chunk)

async def test_aggregate_epidemiology_and_gold_standard_of_treatment_and_summarize(target, indication, language):
    """
    汇总流行病学、治疗的金标准并进行总结
    """
    import asyncio
    
    pubmed_last = ''
    guideline_last = ''
    
    # 创建队列用于输出
    output_queue = asyncio.Queue()
    
    async def run_pubmed():
        nonlocal pubmed_last
        # await output_queue.put("## 正在分析 PubMed 文献...\n\n")
        async for chunk in epidemiology_and_gold_standard_of_treatment_v2(target, indication, language):
            pubmed_last = chunk
            await output_queue.put({'type': 'epidemiology_and_gold_standard_of_treatment', 'summary': chunk})
        await output_queue.put({'type': 'epidemiology_and_gold_standard_of_treatment_done', 'summary': pubmed_last})
    
    async def run_guideline():
        nonlocal guideline_last
        await output_queue.put("## 正在分析临床指南...\n\n")
        async for chunk in test_guideline_agent(target, indication, language):
            guideline_last = chunk
            await output_queue.put({'source': 'guideline', 'content': chunk})
        await output_queue.put({'source': 'guideline', 'status': 'done'})
    
    async def output_consumer():
        completed = set()
        while len(completed) < 2:
            item = await output_queue.get()
            
            if isinstance(item, dict) and item.get('status') == 'done':
                completed.add(item['source'])
            else:
                yield item
    
    # 并行执行
    asyncio.create_task(run_pubmed())
    asyncio.create_task(run_guideline())
    
    # 输出结果
    async for item in output_consumer():
        if isinstance(item, str):
            yield item
        else:
            yield item.get('content', '')
    
    # 生成总结
    yield "\n\n## 正在生成综合总结...\n\n"
    
    summary_result = str()
    llm = CompositeClaude()
    try:
        summary_prompt = summary_epidemiology_and_gold_standard_of_treatment_prompt.format(
            pubmed_last=pubmed_last, 
            guideline_last=guideline_last
        )
        async for chunk in llm.stream_call(sys_prompt=summary_prompt):
            summary_result += chunk
            yield json.dumps({"type": "summary", "summary": summary_result}, ensure_ascii=False) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "task": "llm_summary", "error": str(e)}, ensure_ascii=False) + "\n"
    save_to_file(f"流行病学和治疗金标准 靶点适应症 {target} {indication}", summary_result)


async def target_for_clinical_trial_comparison(table_data: str, language: str = 'en') -> list:
    """临床试验表对比"""
    summary_result = str()
    llm = CompositeClaude()
    try:
        prompt = trial_comparison_prompt_v7.format(table_data=table_data)
        async for chunk in llm.stream_call(sys_prompt=prompt):
            summary_result += chunk
            yield {"type": "trial_comparison", "summary": summary_result}
        yield {"type": "trial_comparison_done", "summary": summary_result}
    except Exception as e:
        yield {"type": "error", "task": "trial_comparison", "error": str(e)}


async def split_table(target):
    """target 靶点 临床试验查询分析大步骤v3，已暂停，要切换成v4"""
    table_result = str()
    import json
    all_ct_results = []
    ct_filters = {
        "filters": {
            "drug_modality": {"data": [], "logic": "or"},
            "target": {
                "data": ["FLT3"],
                "logic": "or"
            }
        },
        'from_n': 0,
        'size': 1000,
    }
    
    # raw_ct_results = await search_clinical_trial(ct_filters)
    # 分页获取10000条数据，每次1000条
    for page in range(10):  # 10页 * 1000条 = 10000条
        ct_filters['from_n'] = page * 1000
                
        raw_ct_results = await search_clinical_trial(ct_filters)
        results = raw_ct_results.get('results')
        
        if results:
            all_ct_results.extend(results)

    # results = raw_ct_results.get('results')
    # 过滤数据：只保留 drug 不为空列表的记录
    filter_notnone_results = list()
    if all_ct_results:
        for record in all_ct_results:
            # 检查 drug 字段是否存在且不为空列表
            if record.get('drug') and isinstance(record.get('drug'), list) and len(record.get('drug')) > 0:
                filter_notnone_results.append(record)
    else:
        print('未获取到任何数据')
    print(len(filter_notnone_results))
    save_to_file('filter_notnone_results', str(filter_notnone_results))
    print(111)
    def get_phase_priority(record):
        """获取phase优先级，数值越小优先级越高"""
        drug_list = record.get('drug', [])
        if not drug_list:
            return 999  # 没有drug的记录放到最后
        
        # 获取所有drug中的最高phase
        max_priority = 999
        for drug in drug_list:
            phase = drug.get('phase', '').lower()
            
            # 定义phase优先级映射
            phase_priority_map = {
                'approved': 0, 'Approved': 0,
                'phase iv': 1, 'phase4': 1, 'iv': 1, 'IV': 1,
                'phase iii': 2, 'phase3': 2, 'iii': 2, 'III': 2,
                'phase ii': 3, 'phase2': 3, 'ii': 3, 'II': 3,
                'phase i': 4, 'phase1': 4, 'i': 4,'PHASE1': 4, 'I': 4,
                'preclinical': 5, 'Preclinical': 5
            }
            
            # 查找匹配的phase
            priority = 999  # 默认最低优先级
            for key, value in phase_priority_map.items():
                if key in phase:
                    priority = value
                    break
            
            # 取最高优先级（数值最小）
            max_priority = min(max_priority, priority)
        
        return max_priority

    # 按phase优先级排序
    all_ct_results.sort(key=get_phase_priority)
    
    # 4. 排序后数据取top10药
    # 按照排好序的数据取前十个不同的药品
    top10_drug_names = []
    seen_drugs = set()

    for record in all_ct_results:  # 使用已经按phase排序的数据
        drug_list = record.get('drug', [])
        for drug in drug_list:
            drug_name = drug.get('name', '')
            if drug_name and drug_name not in seen_drugs:
                top10_drug_names.append(drug_name)
                seen_drugs.add(drug_name)
                
                # 取到10个不同的药品就停止
                if len(top10_drug_names) >= 10:
                    break
        
        # 如果已经取够10个药品，跳出外层循环
        if len(top10_drug_names) >= 10:
            break

    print(f"Top10药品: {top10_drug_names}")
    
    # 5. 补充top10药品所有trial，每组药为一组
    # 按药品分组，每个药品一个组
    drug_groups = {}
    for record in all_ct_results:
        drug_list = record.get('drug', [])
        for drug in drug_list:
            drug_name = drug.get('name', '')
            if drug_name in top10_drug_names:
                if drug_name not in drug_groups:
                    drug_groups[drug_name] = []
                drug_groups[drug_name].append(record)
    
    # 6. 对每一组进行phase排序
    def sort_group_by_phase(group_records):
        """对组内记录按phase排序"""
        def get_record_phase_priority(record):
            drug_list = record.get('drug', [])
            if not drug_list:
                return 999
            
            min_priority = 999
            for drug in drug_list:
                phase = drug.get('phase', '').lower()
                phase_priority_map = {
                'approved': 0, 'Approved': 0,
                'phase iv': 1, 'phase4': 1, 'iv': 1, 'IV': 1,
                'phase iii': 2, 'phase3': 2, 'iii': 2, 'III': 2,
                'phase ii': 3, 'phase2': 3, 'ii': 3, 'II': 3,
                'phase i': 4, 'phase1': 4, 'i': 4,'PHASE1': 4, 'I': 4,
                'preclinical': 5, 'Preclinical': 5
            }
                
                priority = 999
                for key, value in phase_priority_map.items():
                    if key in phase:
                        priority = value
                        break
                
                min_priority = min(min_priority, priority)
            
            return min_priority
        
        return sorted(group_records, key=get_record_phase_priority)

    # 对每个药品组进行排序
    sorted_drug_groups = {}
    for drug_name, group_records in drug_groups.items():
        sorted_drug_groups[drug_name] = sort_group_by_phase(group_records)
    
    # 按top10药品的顺序重新组织数据
    final_results = []
    for drug_name in top10_drug_names:
        if drug_name in sorted_drug_groups:
            final_results.extend(sorted_drug_groups[drug_name])
    
    ct_results = json.dumps(final_results, ensure_ascii=False)
    save_to_file(f"总表", ct_results)
    build_split_table_prompt = split_table_prompt.replace('{table_data}', ct_results)
    llm = CompositeClaude()
    async for chunk in llm.stream_call(sys_prompt=build_split_table_prompt):
        table_result += chunk
        yield table_result
    save_to_file(f"拆表", table_result)
    
    async def run_parallel_analysis(table_data: str, language: str = 'en'):
        # 存储最终结果
        final_results = {
            "top10_analysis": None,
            "trial_comparison": None
        }
        
        # 1. 产品管线表 拿出top10 drug 和 top5 indication
        async def target_for_top_10_drug_and_top_5_indication(table_data: str, language: str = 'en') -> list:
            """抽取适应症列表"""
            llm = CompositeClaude()
            schema = get_openai_json_schema_v3(ExtractTop10DrugAndTop5IndicationSchema)
            tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
            try:
                result = await function_call_with_retry(
                    llm,
                    user_prompt=extract_top_10_drug_and_top_5_indication_prompt.format(text=table_data),
                    tools=schema,
                    tool_choice=tool_choice,
                    temperature=0.3
                )
                
                return result
            except Exception as e:
                raise Exception(f"靶点分析服务异常: {str(e)}")
        
        # 2. 临床试验表对比
        async def target_for_clinical_trial_comparison(table_data: str, language: str = 'en') -> list:
            """临床试验表对比"""
            summary_result = str()
            llm = CompositeClaude()
            try:
                prompt = trial_comparison_prompt.format(table_data=table_data)
                async for chunk in llm.stream_call(sys_prompt=prompt):
                    summary_result += chunk
                    yield json.dumps({"type": "trial_comparison", "summary": summary_result}, ensure_ascii=False) + "\n"
            except Exception as e:
                yield json.dumps({"type": "error", "task": "trial_comparison", "error": str(e)}, ensure_ascii=False) + "\n"

        top10_task = asyncio.create_task(target_for_top_10_drug_and_top_5_indication(table_data))
        
        # 实时输出临床试验对比结果，并记录最后一次结果
        async for trial_result in target_for_clinical_trial_comparison(table_data):
            yield trial_result
            # 解析并保存最后一次结果
            try:
                result_data = json.loads(trial_result.strip())
                if result_data.get("type") == "trial_comparison":
                    final_results["trial_comparison"] = result_data.get("summary")
            except:
                pass
        
        # 等待并输出top10分析结果
        try:
            top10_result = await top10_task
            final_results["top10_analysis"] = top10_result
            yield json.dumps({
                "type": "top10_drug_analysis", 
                "result": top10_result
            }, ensure_ascii=False) + "\n"
        except Exception as e:
            final_results["top10_analysis"] = str(e)
            yield json.dumps({
                "type": "error", 
                "task": "top10_analysis", 
                "error": str(e)
            }, ensure_ascii=False) + "\n"
        
        # 输出最终汇总结果
        yield json.dumps({
            "type": "final_results",
            "data": final_results
        }, ensure_ascii=False) + "\n"
        
    
    # 执行并行分析
    final_results = None
    async for result in run_parallel_analysis(table_result):
        yield result
        # 检查是否是最终结果
        try:
            result_data = json.loads(result.strip())
            if result_data.get("type") == "final_results":
                final_results = result_data.get("data")
        except:
            pass
    
    if final_results:
        # print("最终结果:")
        # print(f"Top10分析: {final_results['top10_analysis']}")
        # print(f"临床试验对比: {final_results['trial_comparison']}")
        save_to_file("top10分析", str(final_results["top10_analysis"]))
        save_to_file("临床试验对比", str(final_results["trial_comparison"]))

    """
    final_results["top10_analysis"]
    {
        'top10_drug': ['talquetamab', 'fluocinolone acetonide', 'SEL-068', 'MK-6913', 'fimasartan', 'TAT-4', 'octreotide', 'C1-INH', 'DTaP-HepB-IPV-Hib hexavalent vaccine', 'glepaglutide'], 
        'top5_indication': ['multiple myeloma', 'diabetic complications', 'hypertension', 'hereditary angioedema', 'acromegaly']
    }
    """
    # 1. 药物分析
    # 2. 适应症分析

from datetime import datetime, timedelta
from typing import Dict, List, Any

def group_and_sort_catalyst_data(catalyst_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    按照时间范围对catalyst数据进行分组和排序
    
    Args:
        catalyst_data: catalyst数据列表，每个元素包含catalyst_expected_date_end字段（字符串格式，如"2013-12-10"）
    
    Returns:
        dict: 按时间范围分组的数据，结构如下：
        {
            "未来3年": [按时间由近及远排序的事件],
            "过去1年": [按时间由近及远排序的事件],
            "过去5年": [按时间由近及远排序的事件],
            "过去10年": [按时间由近及远排序的事件],
            "其他时间": [catalyst_expected_date_end缺失或超出范围的事件]
        }
    """
    current_time = datetime.now()
    
    # 定义时间边界
    one_year_ago = current_time - timedelta(days=365)
    five_years_ago = current_time - timedelta(days=365*5)
    ten_years_ago = current_time - timedelta(days=365*10)
    three_years_future = current_time + timedelta(days=365*3)
    
    # 初始化分组
    groups = {
        "未来3年": [],
        "过去1年内": [],
        "过去1年到5年": [],
        "过去5年到10年": [],
        "其他时间": []
    }
    def parse_date_string(date_str: str) -> datetime:
        """
        解析日期字符串，支持多种格式
        """
        if not date_str or date_str.strip() == '':
            return None
            
        # 支持的日期格式
        date_formats = [
            '%Y-%m-%d',      # 2013-12-10
            '%Y/%m/%d',      # 2013/12/10
            '%Y-%m-%d %H:%M:%S',  # 2013-12-10 10:30:00
            '%Y/%m/%d %H:%M:%S',  # 2013/12/10 10:30:00
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        
        return None
    
    for item in catalyst_data:
        catalyst_date_str = item.get('catalyst_expected_date_end', '')
        
        # 解析日期
        catalyst_date = parse_date_string(catalyst_date_str)
        
        # 处理无效日期
        if catalyst_date is None:
            groups["其他时间"].append(item)
            continue
    # 根据时间范围分组
        if catalyst_date > current_time and catalyst_date <= three_years_future:
            groups["未来3年"].append(item)
        elif catalyst_date >= one_year_ago and catalyst_date <= current_time:
            groups["过去1年内"].append(item)
        elif catalyst_date >= five_years_ago and catalyst_date < one_year_ago:
            groups["过去1年到5年"].append(item)
        elif catalyst_date >= ten_years_ago and catalyst_date < five_years_ago:
            groups["过去5年到10年"].append(item)
        else:
            groups["其他时间"].append(item)
    
    # 对每个分组内的数据进行排序（时间由近及远）
    def sort_by_date_desc(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """按catalyst_expected_date_end降序排序（时间由近及远）"""
        def get_sort_key(item):
            date_str = item.get('catalyst_expected_date_end', '')
            parsed_date = parse_date_string(date_str)
            if parsed_date is None:
                return datetime.min  # 无效日期排在最后
            return parsed_date
        
        return sorted(items, key=get_sort_key, reverse=True)
    
    # 对每个分组进行排序
    for group_name in groups:
        groups[group_name] = sort_by_date_desc(groups[group_name])
    
    return groups

async def test_target_news_search(target, language):
    async for content in run_news_agent(target, language, target_news_search_prompt):
        yield content

async def news_and_catalyst_agent(target, language):
    last_news_content = str()
    # async for content in run_news_agent(target, language, news_search_prompt):
    #     yield content
    #     last_news_content = content
    from workflows.temp_target_data import FR1N1_catalyst_list
    group_catalyst_data = group_and_sort_catalyst_data(FR1N1_catalyst_list)
    llm = CompositeClaude()
    catalyst_news_result = str()
    try:
        prompt = catalyst_news_prompt_10.format(catalyst_data=str(group_catalyst_data), news_data=str(last_news_content))
        async for chunk in llm.stream_call(sys_prompt=prompt):
            catalyst_news_result += chunk
            yield json.dumps({"type": "catalyst_news", "summary": catalyst_news_result}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "catalyst_news_done", "summary": catalyst_news_result}, ensure_ascii=False) + "\n"
    except Exception as e:
        yield json.dumps({"type": "error", "task": "catalyst_news", "error": str(e)}, ensure_ascii=False) + "\n"
    save_to_file(f"news {target}", last_news_content)
    save_to_file(f"catalyst news {target}", catalyst_news_result)


def extract_indication_leaf_names(indication_dict):
    """
    从indication字典中提取所有叶子节点的name，用逗号拼接
    
    参数:
        indication_dict: indication字典，包含soc, hlgt, hlt, pt等层级
    
    返回:
        str: 用逗号分隔的所有叶子节点name
    """
    leaf_names = []
    
    def find_leaf_nodes(node, level_key):
        """递归查找叶子节点"""
        if not node:
            return
        
        if isinstance(node, list):
            for item in node:
                find_leaf_nodes(item, level_key)
            return
        
        if isinstance(node, dict):
            next_levels = {
                'soc': 'hlgt',
                'hlgt': 'hlt',
                'hlt': 'pt'
            }
            
            next_level = next_levels.get(level_key)
            
            if next_level and next_level in node and node[next_level]:
                find_leaf_nodes(node[next_level], next_level)
            else:
                # 没有下一层级或下一层级为空，这是叶子节点
                if 'name' in node:
                    leaf_names.append(node.get('name'))
    
    if indication_dict and 'soc' in indication_dict:
        find_leaf_nodes(indication_dict['soc'], 'soc')
    return ', '.join(leaf_names)

def extract_study_design_desc(arm_list):
    """
    提取研究设计描述，格式化为字符串
    
    参数:
        arm_list: arms列表数据
    
    返回:
        str: 格式化的研究设计描述字符串
    """
    if not arm_list:
        return ""
    
    arm_descriptions = []
    
    for arm in arm_list:
        title = arm.get('title', '')
        doses = arm.get('doses', [])
        
        if doses:
            dose_strings = []
            for dose in doses:
                name = dose.get('name', '') or ''
                dose_amount = dose.get('dose', '') or ''
                how = dose.get('how', '') or ''
                frequent = dose.get('frequent', '') or ''
                duration = dose.get('duration', '') or ''
                
                # 构建剂量字符串：name+dose+how+frequent+duration（即使为空也显示）
                dose_str = f"{name}+{dose_amount}+{how}+{frequent}+{duration}"
                dose_strings.append(dose_str)
            
            arm_desc = f"{title}：dose[{'; '.join(dose_strings)}]"
        else:
            arm_desc = f"{title}：dose[]"
        
        arm_descriptions.append(arm_desc)
    
    return '\n'.join(arm_descriptions)

def convert_clinical_data_to_dict(drug_list):
    """
    将临床试验数据转换为两个字典列表，并替换每个药品的data字段
    
    参数:
        drug_list: 包含药品临床试验数据的列表,每个元素包含 drug_name, nctid_list, data
    
    返回:
        None (直接修改传入的drug_list)
    """
    for drug_info in drug_list:
        drug_table_data = []  # 产品管线表
        trial_table_data = []  # 临床结果表
        
        data_list = drug_info.get('data', [])
        
        for trial in data_list:
            # 只保留有drug字段且不为空的记录
            if not (trial.get('drug') and isinstance(trial.get('drug'), list) and len(trial.get('drug')) > 0):
                continue
            
            # 提取drug相关信息 提取第一个药品
            drug_list_field = trial.get('drug', []) or []
            the_drug = drug_list_field[0]
            drug_names = the_drug.get('name', '')
            drug_phases = the_drug.get('phase', '')
            administration_routes = ', '.join(the_drug.get('administration_route', []))
            
            # 提取company信息 提取所有公司
            company_list = trial.get('company', []) or []
            company_names = ', '.join([c.get('name', '') for c in company_list if c.get('name')])
            
            # 提取location信息
            location_list = trial.get('location', []) or []
            countries = ', '.join([loc.get('region', '') for loc in location_list if loc.get('region')])
            
            # 提取适应症 提取第一个适应症
            indication_specific = extract_indication_leaf_names(trial.get('indication', {}))
            
            # 提取其他字段
            nct_id = trial.get('nct_id', '') or ''
            status = trial.get('status', '') or ''
            start_date = trial.get('start_date', '') or ''
            primary_completion_date = trial.get('primary_completion_date', '') or ''
            # description = trial.get('description', '') or ''
            
            # 研究设置概述
            arm_list = trial.get('arms', []) or []
            study_design_desc = extract_study_design_desc(arm_list)
            
            # 提取患者人数
            design_obj = trial.get('design', {}) or {}
            enrollment_number = design_obj.get('enrollment_number', '')
            patient_count = str(enrollment_number) if enrollment_number else '人数未知'
            enrollment_number_type = design_obj.get('enrollment_number_type', '')
            phase = design_obj.get('phases', []) or []
            
            # 提取有效性和安全性总结
            result_summary = trial.get('result_summary', {})
            # 有效性
            efficacy_summary = result_summary.get('efficacy_summary', '')
            # 安全性
            safety_summary = result_summary.get('safety_summary', '')
            
            # 构建产品管线表字典
            pipeline_dict = {
                'id': nct_id,
                'drug_name': drug_names,
                'company': company_names,
                'phase': str(phase),
                'country': countries,
                'status': str(drug_phases) + ',' + status,
                'indication': indication_specific,
                'route_of_administration': administration_routes,
                'study_design': study_design_desc,
                # 主要终点暂时不要
                # 'Primary_Endpoint': primary_endpoint,
                'start_date': start_date,
                'primary_completion_date': primary_completion_date
            }
            drug_table_data.append(pipeline_dict)
            
            # 构建临床结果表字典
            results_dict = {
                'id': nct_id,
                'drug_name': drug_names,
                'company': company_names,
                'patient_count': patient_count + ' ' + '(' + enrollment_number_type + ')',
                'indication': indication_specific,
                'efficacy_summary': efficacy_summary,
                'safety_summary': safety_summary,
                'country': countries
            }
            trial_table_data.append(results_dict)
        
        # 替换data字段为包含两个列表的字典
        drug_info['data'] = {
            'drug_list': drug_table_data,
            'trial_list': trial_table_data
        }

def convert_clinical_data_to_dict_v2(drug_data):
    """
    将临床试验数据转换为全量数据（包含产品管线表字段和临床试验结果表字段）
    
    参数:
        drug_data: 单个药品数据，包含 name, phase, trial_list 等字段
    
    返回:
        v2版本返回：全量数据
    """
    all_pipline_and_trial_list = []  # 临床结果表列表
    
    # 从传入数据中提取基本信息
    drug_name = drug_data.get('name', '')
    drug_phase = drug_data.get('phase', '')
    trial_list = drug_data.get('trial_list', [])
    
    if not trial_list:
        return {}, all_pipline_and_trial_list
    
    # 处理所有trials用于trial_table
    for trial in trial_list:
        # 只保留有drug字段且不为空的记录
        if not (trial.get('drug') and isinstance(trial.get('drug'), list) and len(trial.get('drug')) > 0):
            continue
        
        # 提取company信息
        company_list = trial.get('company', []) or []
        company_names = ', '.join([c.get('name', '') for c in company_list if c.get('name')])
        
        # 提取location信息
        location_list = trial.get('location', []) or []
        countries = ', '.join([loc.get('region', '') for loc in location_list if loc.get('region')])
        
        # 提取适应症
        indication_specific = extract_indication_leaf_names(trial.get('indication', {}))
        
        # 提取其他字段
        nct_id = trial.get('nct_id', '') or ''

        status = trial.get('status', '') or ''
        start_date = trial.get('start_date', '') or ''
        primary_completion_date = trial.get('primary_completion_date', '') or ''

        arm_list = trial.get('arms', []) or []
        study_design_desc = extract_study_design_desc(arm_list)
        
        # 提取第一个trial的drug相关信息
        drug_list_field = trial.get('drug', []) or []
        if drug_list_field:
            the_drug = drug_list_field[0]
            administration_routes = ', '.join(the_drug.get('administration_route', []))
        else:
            administration_routes = ''

        # 提取患者人数
        design_obj = trial.get('design', {}) or {}
        enrollment_number = design_obj.get('enrollment_number', '')
        patient_count = str(enrollment_number) if enrollment_number else '人数未知'
        enrollment_number_type = design_obj.get('enrollment_number_type', ' ') or ' '
        design_phases = design_obj.get('phases', []) or []
        if design_phases:
            design_phase = design_phases[-1]
        else:
            design_phase = 'Unknown'
        # 提取有效性和安全性总结
        result_summary = trial.get('result_summary', {})
        if result_summary:
            efficacy_summary = result_summary.get('efficacy', '')
            safety_summary = result_summary.get('safety', '')
        else:
            efficacy_summary = '未知'
            safety_summary = '未知'
        
        # 全量数据表
        result_dict = {
            'id': nct_id,
            'drug_name': drug_name,  # 使用传入的name
            'company': company_names,
            'design_phase': design_phase,  # 直接使用传入的phase
            'country': countries,
            'status': status + ',' + drug_phase,
            'indication': indication_specific,
            'route_of_administration': administration_routes,
            'study_design': study_design_desc,
            'start_date': start_date,
            'primary_completion_date': primary_completion_date,
            'patient_count': patient_count + ' ' + '(' + enrollment_number_type + ')',
            'efficacy_summary': efficacy_summary,
            'safety_summary': safety_summary,
        }
        all_pipline_and_trial_list.append(result_dict)
    
    return all_pipline_and_trial_list


def sort_trial_table_list(trial_table_list):
    """
    对trial_table_list进行分组和组内排序
    按适应症分组，也就是indication相同的为一组，按适应症排序，组内排序为 design_phase 顺序是 Approved>PHASE3>PHASE2>PHASE1>Unknown
    分组完成后，最终返回合并后排好序的列表
    """
    # 新的排序规则需包含Unknown
    from collections import defaultdict

    def get_design_phase_priority(phase):
        """
        定义phase优先级，数字小优先级高
        """
        phase_map = {
            "Approved": 0, "approved": 0, "APPROVED": 0,
            "PHASE3": 1, "Phase 3": 1, "phase iii": 1, "phase3": 1, "iii": 1, "III": 1,
            "PHASE2": 2, "Phase 2": 2, "phase ii": 2, "phase2": 2, "ii": 2, "II": 2,
            "PHASE1": 3, "Phase 1": 3, "phase i": 3, "phase1": 3, "i": 3, "I": 3,
            "Unknown": 4, "unknown": 4, "": 4, None: 4  # 未知为最后
        }
        key = str(phase or '').strip()
        return phase_map.get(key, 4)  # 默认Unknown优先级为4

    # 1. 按indication分组
    group_by_indication = defaultdict(list)
    for trial in trial_table_list:
        indication = trial.get('indication', '') or ''
        group_by_indication[indication].append(trial)

    # 2. 组内排序 design_phase，顺序为 Approved > PHASE3 > PHASE2 > PHASE1 > Unknown
    sorted_groups = []
    for indication, trials in group_by_indication.items():
        sorted_list = sorted(
            trials,
            key=lambda x: get_design_phase_priority(x.get('design_phase'))
        )
        sorted_groups.append((indication, sorted_list))

    # 3. 组排序：按每组(trials)数量逆序，数量多的indication排前面
    sorted_groups.sort(key=lambda tup: len(tup[1]), reverse=True)

    # 4. 合并所有排序后的trial
    merged_sorted_list = []
    for _, trials in sorted_groups:
        merged_sorted_list.extend(trials)
    return merged_sorted_list


async def test_split_table_v4(target):
    """临时用，志恒给的十个药品和nctid去组成 管线表和临床实验表"""
    
    from workflows.temp_target_data import demo_temp_target_drug_list
    temp_target_drug_list = demo_temp_target_drug_list.copy()
    drug_list = list()
    for drug in temp_target_drug_list:
        drug_name = drug.get('drug_name')
        nctid_list = drug.get('nctid_list')
        drug_list.append(drug_name)
        ct_filters = {
        "nctid": nctid_list, 'from_n': 0, "size": 100
    }
        raw_ct_results = await search_clinical_trial(ct_filters)
        results = raw_ct_results.get('results')
        if results:
            drug['data'] = results
    save_to_file('drug_data', str(temp_target_drug_list))
    yield 1 

    # 每个drug的data按照phase去排序
    for drug in temp_target_drug_list:
    # 按照phase优先级字典进行排序（参考split_table中的get_phase_priority逻辑）
        def get_phase_priority(record):
            """获取phase优先级，数值越小优先级越高"""
            drug_list = record.get('drug', [])
            if not drug_list:
                return 999
            
            # 获取所有drug中的最高phase优先级
            max_priority = 999
            for drug in drug_list:
                phase = drug.get('phase', '').lower()
                
                phase_priority_map = {
                    'approved': 0, 'Approved': 0,
                    'phase iv': 1, 'phase4': 1, 'iv': 1, 'IV': 1,
                    'phase iii': 2, 'phase3': 2, 'iii': 2, 'III': 2,
                    'phase ii': 3, 'phase2': 3, 'ii': 3, 'II': 3,
                    'phase i': 4, 'phase1': 4, 'i': 4, 'PHASE1': 4, 'I': 4,
                    'preclinical': 5, 'Preclinical': 5
                }
                
                priority = 999
                for key, value in phase_priority_map.items():
                    if key in phase:
                        priority = value
                        break
                
                max_priority = min(max_priority, priority)
            
            return max_priority

        drug_data = drug.get('data', [])
        drug_name = drug.get('drug_name')
        if drug_data:
            # 对data列表按照phase优先级进行排序
            drug['data'] = sorted(drug_data, key=get_phase_priority)
            print(f"药品 {drug_name}: {len(drug['data'])} 条数据已排序")
        else:
            print(f"药品 {drug_name}: 无数据")
    save_to_file('drug_data_sorted', str(temp_target_drug_list))
    yield 2

    # 构造temp_target_drug_list
    convert_clinical_data_to_dict(temp_target_drug_list)
    
    save_to_file(f"1015 拆表", str(temp_target_drug_list))
    yield 3

    # 在 analyze_target.py 文件的 1444 行开始位置，替换整个代码块：

    from workflows.analyze_target_prompt import combined_table_to_markdown_prompt, merge_tables_prompt

    # 并行处理每个药品，生成表格
    queue = asyncio.Queue()
    table_results = {}  # 存储每个药品的表格结果
    completed_count = 0
    total_drugs = len([d for d in temp_target_drug_list if d.get('data')])

    async def process_single_drug_table(drug_info):
        """处理单个药品的表格生成"""
        drug_name = drug_info.get('drug_name')
        drug_data_dict = drug_info.get('data')
        
        if not drug_data_dict:
            await queue.put({"type": "skip", "drug_name": drug_name})
            return
        
        trial_data = drug_data_dict.get('trial_list', [])
        
        if not trial_data:
            await queue.put({"type": "skip", "drug_name": drug_name})
            return
        
        try:
            # 生成提示词
            prompt = combined_table_to_markdown_prompt.format(
                table_data=json.dumps(trial_data, ensure_ascii=False, indent=2)
            )
            
            llm = CompositeClaude()
            table_result = str()
            
            async for chunk in llm.stream_call(sys_prompt=prompt):
                table_result += chunk
                await queue.put({"type": "progress", "drug_name": drug_name, "data": table_result})
            
            # 保存结果
            table_results[drug_name] = table_result
            await queue.put({"type": "complete", "drug_name": drug_name})
            
        except Exception as e:
            await queue.put({"type": "error", "drug_name": drug_name, "error": str(e)})

    # 设置并发限制，避免超过API速率限制
    MAX_CONCURRENT_REQUESTS = 5
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def process_with_semaphore(drug_info):
        """带并发控制的处理函数"""
        async with sem:
            await process_single_drug_table(drug_info)
            # 添加延迟，避免请求过于频繁
            await asyncio.sleep(2)

    # 启动所有任务
    tasks = [asyncio.create_task(process_with_semaphore(drug_info)) for drug_info in temp_target_drug_list]

    # 实时消费结果
    while completed_count < total_drugs or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            
            if item["type"] == "progress":
                # 实时输出进度
                yield item["data"]
            elif item["type"] == "complete":
                completed_count += 1
                print(f"✓ {item['drug_name']}: 表格生成完成 ({completed_count}/{total_drugs})")
            elif item["type"] == "error":
                completed_count += 1
                print(f"✗ {item['drug_name']}: 处理失败 - {item.get('error', 'Unknown')}")
            elif item["type"] == "skip":
                print(f"⚠️  {item['drug_name']}: 无数据，跳过")
        except asyncio.TimeoutError:
            # 检查是否所有任务都完成
            if all(task.done() for task in tasks):
                break

    # 等待所有任务完成
    await asyncio.gather(*tasks, return_exceptions=True)

    # 保存每个药品的单独表格
    for drug_name, content in table_results.items():
        save_to_file(f"1015_表格_{drug_name}", content)

    print(f"\n=== 开始汇总所有表格 ===")

    # 用LLM汇总所有表格
    # 拼接所有表格
    all_tables_text = '\n\n---\n\n'.join([f"### {drug_name}\n{content}" for drug_name, content in table_results.items()])

    # 生成汇总提示词
    merge_prompt = merge_tables_prompt.format(all_tables=all_tables_text)

    # 用LLM汇总
    llm = CompositeClaude()
    final_result = str()
    async for chunk in llm.stream_call(sys_prompt=merge_prompt):
        final_result += chunk
        yield chunk

    # 保存最终汇总结果
    save_to_file(f"1015_汇总表格_{datetime.now().strftime('%Y%m%d_%H%M%S')}", final_result)

    print(f"\n=== 表格汇总完成 ===")
    print(f"共处理: {len(table_results)} 个药品")

    yield 4

    last_drug_content = str()
    # 十个药对比
    # async for content in test_drug_pubmed_agent(drug_list, 'en'):
    #     yield content
    #     last_drug_content = content
    # save_to_file(f"1015 drug {target}", last_drug_content)
    # yield 4
    

    
    # n个药的试验数据组做对比
    # for drug_data in temp_target_drug_list:
    #     drug_data = drug_data.get('data')
    #     drug_name = drug_data.get('drug_name')
    #     last_trial_comaprison_content = str()

    #     async for content in target_for_clinical_trial_comparison(drug_data, 'en'):
    #         yield content
    #         last_trial_comaprison_content = content
    #     save_to_file(f"1015 试验数据对比 {drug_name}", last_trial_comaprison_content)

    # 替换最后的 for 循环部分：

# n个药的试验数据组做对比（并行处理，实时返回结果）
    queue = asyncio.Queue()
    results = {}
    completed_count = 0
    total_drugs = len([d for d in temp_target_drug_list if d.get('data')])

    async def process_single_drug(drug_info):
        """处理单个药品的试验数据对比"""
        drug_name = drug_info.get('drug_name')
        drug_data_dict = drug_info.get('data')  # 这是包含 drug_list 和 trial_list 的字典
        
        if not drug_data_dict:
            await queue.put({"type": "skip", "drug_name": drug_name})
            return
        
        # 提取 trial_list 用于处理
        trial_data = drug_data_dict.get('trial_list', [])
        
        if not trial_data:
            await queue.put({"type": "skip", "drug_name": drug_name})
            return
        
        try:
            content = ""
            async for chunk in target_for_clinical_trial_comparison(trial_data, 'en'):
                content = chunk
                await queue.put({"type": "progress", "drug_name": drug_name, "data": chunk})
            
            results[drug_name] = content
            await queue.put({"type": "complete", "drug_name": drug_name})
        except Exception as e:
            await queue.put({"type": "error", "drug_name": drug_name, "error": str(e)})

    # 启动所有任务
    tasks = [asyncio.create_task(process_single_drug(drug_info)) for drug_info in temp_target_drug_list]

    # 实时消费结果
    while completed_count < total_drugs or not queue.empty():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            
            if item["type"] == "progress":
                # 实时输出进度
                yield item["data"]
            elif item["type"] == "complete":
                completed_count += 1
                print(f"✓ {item['drug_name']}: 试验数据对比完成 ({completed_count}/{total_drugs})")
            elif item["type"] == "error":
                completed_count += 1
                print(f"✗ {item['drug_name']}: 处理失败 - {item.get('error', 'Unknown')}")
            elif item["type"] == "skip":
                print(f"⚠️  {item['drug_name']}: 无数据，跳过")
        except asyncio.TimeoutError:
            # 检查是否所有任务都完成
            if all(task.done() for task in tasks):
                break

    # 等待所有任务完成
    await asyncio.gather(*tasks, return_exceptions=True)

    # 保存结果
    for drug_name, content in results.items():
        save_to_file(f"1015 试验数据对比 {drug_name}", content)

    # 保存汇总文件
    summary_dict = {drug_name: content for drug_name, content in results.items()}
    save_to_file(
        f"1015_试验数据对比_汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}", 
        json.dumps(summary_dict, ensure_ascii=False, indent=2)
    )

    print(f"\n=== 试验数据对比处理完成 ===")
    print(f"成功处理: {len(results)} 个药品")

    yield json.dumps({
        "type": "trial_comparison_done",
        "message": "所有药品试验数据对比完成",
        "total": len(results)
    }, ensure_ascii=False) + "\n"


def generate_markdown_tables(drug_sort_dict_list):
    """
    生成两个Markdown表格：drug表格和trial表格
    
    参数:
        drug_sort_dict_list: 包含多个drug_sort_dict的列表，每个dict包含drug_table和trial_table_list
    
    返回:
        tuple: (drug_table_md, trial_table_md) 两个Markdown表格字符串
    """
    
    # Drug表格的中文表头
    drug_headers = [
        "ID", "药品", "公司", "研究阶段", "国家", "状态",
        "适应症", "给药方式", "研究设置概述",
        "开始时间", "预计完成时间"
    ]
    
    # Trial表格的中文表头
    trial_headers = [
        "ID", "药品", "公司", "患者人数", "适应症",
        "有效性总结", "安全性总结", "国家", "临床试验阶段"
    ]
    
    # 收集所有drug数据
    all_drug_data = []
    all_trial_data = []
    
    for drug_sort_dict in drug_sort_dict_list:
        # 提取drug_table数据
        drug_table = drug_sort_dict.get('drug_table', {})
        if drug_table:
            all_drug_data.append(drug_table)
        
        # 提取trial_table_list数据
        trial_table_list = drug_sort_dict.get('trial_table_list', [])
        all_trial_data.extend(trial_table_list)
    
    # 生成Drug表格
    drug_table_md = generate_single_markdown_table(all_drug_data, drug_headers)
    
    # 生成Trial表格
    trial_table_md = generate_single_markdown_table(all_trial_data, trial_headers)
    
    return drug_table_md, trial_table_md

def generate_drug_markdown_table(drug_data_list):
    """
    生成Drug Markdown表格
    
    参数:
        drug_data_list: 包含多个drug数据的列表，每个元素是一个字典
    
    返回:
        str: Drug Markdown表格字符串
    """
    # Drug表格的中文表头
    drug_headers = [
        "ID", "药品", "公司", "研究阶段", "国家", "状态",
        "适应症", "给药方式", "研究设置概述",
        "开始时间", "预计完成时间"
    ]
    
    # 生成Drug表格
    drug_table_md = generate_single_markdown_table(drug_data_list, drug_headers)
    
    return drug_table_md

def generate_trial_markdown_table(trial_data_list):
    """
    生成Trial Markdown表格
    
    参数:
        trial_data_list: 包含多个trial数据的列表，每个元素是一个字典
    
    返回:
        str: Trial Markdown表格字符串
    """
    # Trial表格的中文表头
    trial_headers = [
        "ID", "药品", "公司", "患者人数", "适应症",
        "有效性总结", "安全性总结", "国家", "临床试验阶段", "临床试验分析结果"
    ]
    
    # 生成Trial表格
    trial_table_md = generate_single_markdown_table(trial_data_list, trial_headers)
    
    return trial_table_md

def generate_single_markdown_table(data_list, headers):
    """
    生成单个Markdown表格
    
    参数:
        data_list: 数据列表
        headers: 表头列表
    
    返回:
        str: Markdown表格字符串
    """
    if not data_list:
        empty_row = ["无数据"] * len(headers)
        return "| " + " | ".join(headers) + " |\n|" + "---|".join(["-" * max(3, len(h)) for h in headers]) + "|\n| " + " | ".join(empty_row) + " |"
    
    # 表头
    header_line = "| " + " | ".join(headers) + " |"
    
    # 分隔线
    separator_line = "|" + "---|".join(["-" * max(3, len(h)) for h in headers]) + "|"
    
    # 数据行
    rows = [header_line, separator_line]
    
    for data in data_list:
        row_values = []
        for header in headers:
            # 根据中文表头映射到英文字段名
            field_name = get_field_mapping(header)
            value = str(data.get(field_name, ''))
            # 清洗数据，避免Markdown表格分隔符
            cleaned_value = sanitize_for_markdown_table(value)
            row_values.append(cleaned_value)
        rows.append("| " + " | ".join(row_values) + " |")
    
    return "\n".join(rows)


def sanitize_for_markdown_table(text):
    """
    对字符串进行清理，使其适合Markdown表格单元格
    """
    if not isinstance(text, str):
        return str(text)
    
    # 替换Markdown表格分隔符
    text = text.replace('|', '&#124;')
    
    # 将换行符替换为空格
    text = text.replace('\n', ' ')
    text = text.replace('\r', ' ')
    
    # 移除多余的空格
    text = ' '.join(text.split())
    
    # 转义其他Markdown特殊字符
    text = text.replace('[', '&#91;')
    text = text.replace(']', '&#93;')
    text = text.replace('*', '&#42;')
    text = text.replace('_', '&#95;')
    
    return text

def get_field_mapping(chinese_header):
    """
    将中文表头映射到英文字段名
    
    参数:
        chinese_header: 中文表头
    
    返回:
        str: 对应的英文字段名
    """
    mapping = {
        "ID": "id",
        "药品": "drug_name",
        "公司": "company",
        "研究阶段": "design_phase",
        "国家": "country",
        "状态": "status",
        "适应症": "indication",
        "给药方式": "route_of_administration",
        "研究设置概述": "study_design",
        "开始时间": "start_date",
        "预计完成时间": "primary_completion_date",
        "患者人数": "patient_count",
        "适应症": "indication",
        "有效性总结": "efficacy_summary",
        "安全性总结": "safety_summary",
        "临床试验阶段": "design_phase",
        "临床试验分析结果": "trial_result_analysis"
    }
    return mapping.get(chinese_header, chinese_header.lower())

def group_by_indication_and_phase(trial_table_list):
    """
    按照 indication 和 design_phase 对临床试验列表进行分组
    
    Args:
        trial_table_list: 临床试验列表，每个元素是包含 'indication' 和 'design_phase' 的字典
    
    Returns:
        dict: 按 indication 分组，每个 indication 下按 design_phase 分组的嵌套字典
              结构: {
                  "indication_name": {
                      "Phase1": [trial1, trial2, ...],
                      "Phase2": [trial3, trial4, ...],
                      ...
                  },
                  ...
              }
    """
    grouped_data = {}
    
    for trial in trial_table_list:
        indication = trial.get('indication', '未知')
        design_phase = trial.get('design_phase', '未知')
        
        # 如果 indication 还未在字典中，创建新的
        if indication not in grouped_data:
            grouped_data[indication] = {}
        
        # 如果 design_phase 还未在该 indication 下创建，创建新的列表
        if design_phase not in grouped_data[indication]:
            grouped_data[indication][design_phase] = []
        
        # 将 trial 添加到对应的分组中
        grouped_data[indication][design_phase].append(trial)
    
    return grouped_data


def group_by_indication_and_phase_and_drug_v1(trial_table_list):
    """
    按照 indication、design_phase 和 drug_name 对临床试验列表进行分组
    只保留Phase 1、2、3，过滤掉数量小于2的列表
    
    Args:
        trial_table_list: 临床试验列表，每个元素是包含 'indication'、'design_phase' 和 'drug_name' 的字典
    
    Returns:
        dict: 按 indication 分组，每个 indication 下按 design_phase 分组，每个 phase 下按 drug_name 分组的嵌套字典
              结构: {
                  "indication_name": {
                      "Phase1": {
                          "drug_name1": [trial1, trial2, ...],  # 只保留数量>=2的
                          "drug_name2": [trial3, trial4, ...],
                          ...
                      },
                      "Phase2": {
                          "drug_name1": [trial5, trial6, ...],
                          ...
                      },
                      "Phase3": {
                          "drug_name1": [trial7, trial8, ...],
                          ...
                      }
                  },
                  ...
              }
    """
    grouped_data = {}
    
    # 定义允许的phase
    allowed_phases = {'PHASE1', 'PHASE2', 'PHASE3'}
    
    for trial in trial_table_list:
        indication = trial.get('indication', '未知')
        design_phase = trial.get('design_phase', '未知')
        drug_name = trial.get('drug_name', '未知')
        
        # 只处理允许的phase
        if design_phase not in allowed_phases:
            continue
        # 如果 indication 还未在字典中，创建新的
        if indication not in grouped_data:
            grouped_data[indication] = {}
        
        # 如果 design_phase 还未在该 indication 下创建，创建新的字典
        if design_phase not in grouped_data[indication]:
            grouped_data[indication][design_phase] = {}
        
        # 如果 drug_name 还未在该 phase 下创建，创建新的列表
        if drug_name not in grouped_data[indication][design_phase]:
            grouped_data[indication][design_phase][drug_name] = []
        
        # 将 trial 添加到对应的分组中
        grouped_data[indication][design_phase][drug_name].append(trial)
    
    # 过滤掉数量小于2的列表
    filtered_data = {}
    for indication, phases in grouped_data.items():
        filtered_indication = {}
        
        for phase, drugs in phases.items():
            filtered_drugs = {}
            
            for drug_name, trials in drugs.items():
                # 只保留数量>=2的列表
                if len(trials) >= 2:
                    filtered_drugs[drug_name] = trials
            
            # 只保留有药物的phase
            if filtered_drugs:
                filtered_indication[phase] = filtered_drugs
        
        # 只保留有phase的indication
        if filtered_indication:
            filtered_data[indication] = filtered_indication
    
    return filtered_data
    
def filter_groups_with_multiple_drugs(data):
    """
    过滤数据，只保留大于等于两种药的组
    
    Args:
        data: 嵌套字典，结构为 {
            "indication_name": {
                "PHASE1": {
                    "drug_name1": [trial1, trial2, ...],
                    "drug_name2": [trial3, trial4, ...],
                    ...
                },
                "PHASE2": {...},
                "PHASE3": {...}
            }
        }
    
    Returns:
        dict: 处理后的数据，只保留大于等于两种药的组
    """
    result = {}
    
    for indication, phases in data.items():
        result[indication] = {}
        
        for phase, drugs in phases.items():
            # 检查该phase下有多少种不同的药品
            drug_count = len(drugs)
            
            # 只保留大于等于两种药的组
            if drug_count >= 2:
                result[indication][phase] = drugs
    
    # 清理空的适应症（如果某个适应症下所有phase都被过滤掉了）
    result = {indication: phases for indication, phases in result.items() if phases}
    
    return result

def collect_all_nct_ids(drug_dict, unique=True, keep_empty=False):
    """
    从drug_list中收集所有clinical_trials的nct_id

    参数:
        drug_list: List[dict]  # 外层药物数据列表
        unique: bool           # 是否去重(保持顺序)
        keep_empty: bool       # 是否保留空/缺失的nct_id(以空字符串表示)

    返回:
        List[str]: nct_id列表
    """
    nct_ids = []
    for trial in (drug_dict.get('clinical_trials') or []):
        nct = trial.get('nct_id')
        if nct:
            nct_ids.append(nct)
        elif keep_empty:
            nct_ids.append('')

    if unique:
        seen = set()
        ordered = []
        for n in nct_ids:
            if n not in seen:
                seen.add(n)
                ordered.append(n)
        return ordered
    return nct_ids

import asyncio
from asyncio import Semaphore

async def parallel_drug_and_trial_comparison(drug_name_list, drug_sort_dict_list):
    """
    并行运行药物对比和临床试验对比
    
    参数:
        drug_name_list: 药物名称列表
        drug_sort_dict_list: 药物排序字典列表
    
    返回:
        异步生成器，yield对比分析结果
    """
    queue = asyncio.Queue()
    completed_count = 0
    final_results = {
        "drug_comparison_done": str(),
        "trial_comparison_done": list()
    }  # 保存所有分析的最终结果
    semaphore = Semaphore(5)  # 最多同时处理5个临床试验对比
    
    async def process_drug_comparison():
        """处理药物对比"""
        nonlocal completed_count
        try:
            async for chunk in test_drug_pubmed_agent_v2(drug_name_list, 'zh-CN'):
                if chunk.get('type') == 'drug_comparison_done':
                    completed_count += 1
                    final_results['drug_comparison_done'] = chunk.get('summary', '')
                await queue.put(chunk)
        except Exception as e:
            await queue.put({
                'type': 'error',
                'summary': f"药物对比出错: {str(e)}"
            })
    
    async def process_single_trial_comparison(drug_dict):
        """处理单个药物的临床试验对比"""
        drug_name = drug_dict.get('name', '')
        trial_table_list = drug_dict.get('trial_table_list')
        
        if not trial_table_list:
            return
            
        async with semaphore:  # 限制并发数量
            try:
                async for chunk in target_for_clinical_trial_comparison(trial_table_list, 'zh-CN'):
                    # 修改type，加入药物名称
                    if chunk.get('type') == 'trial_comparison_done':
                        key_name = f'trial_comparison_{drug_name}' if drug_name else f'trial_comparison_{id(drug_dict)}'
                        final_results['trial_comparison_done'].append({key_name: chunk.get('summary', '')})
                        await queue.put({
                            'type': f'trial_comparison_{drug_name}_done',
                            'summary': chunk.get('summary', '')
                        })
                    else:
                        await queue.put({
                            'type': f'trial_comparison_{drug_name}',
                            'summary': chunk.get('summary', '')
                        })
            except Exception as e:
                await queue.put({
                    'type': 'error',
                    'summary': f"药物 {drug_name} 临床试验对比出错: {str(e)}"
                })
    
    async def process_all_clinical_trials():
        """处理所有临床试验对比 - 并行处理"""
        nonlocal completed_count
        
        # 创建所有临床试验对比任务
        trial_tasks = []
        for drug_dict in drug_sort_dict_list:
            trial_table_list = drug_dict.get('trial_table_list')
            if trial_table_list:
                task = asyncio.create_task(process_single_trial_comparison(drug_dict))
                trial_tasks.append(task)
        
        # 等待所有临床试验对比完成
        if trial_tasks:
            await asyncio.gather(*trial_tasks, return_exceptions=True)
        
        # 所有临床试验对比完成
        completed_count += 1
    
    # 启动两个主要任务
    tasks = [
        asyncio.create_task(process_drug_comparison()),
        asyncio.create_task(process_all_clinical_trials())
    ]
    
    # 持续输出结果
    while completed_count < 2:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            yield item
            queue.task_done()
        except asyncio.TimeoutError:
            if all(task.done() for task in tasks):
                break
            continue
    
    # 等待所有任务完成
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 发送最终完成信号，包含所有分析的结果
    yield {
        'type': 'all_comparisons_done',
        'summary': final_results
    }

async def parallel_drug_and_trial_comparison_v2(drug_name_list, grouped_data):
    """
    并行运行药物对比和临床试验对比
    v2变化，临床试验数据进行了分组和排序和过滤
    参数:
        drug_name_list: 药物名称列表
        grouped_data: 按适应症-阶段-药品分组的数据
    
    返回:
        异步生成器，yield对比分析结果
    """
    queue = asyncio.Queue()
    completed_count = 0
    final_results = {
        "drug_comparison_done": str(),
        "trial_comparison_done": list()
    }  # 保存所有分析的最终结果
    semaphore = Semaphore(5)  # 最多同时处理5个临床试验对比
    
    async def process_drug_comparison():
        """处理药物对比"""
        nonlocal completed_count
        try:
            async for chunk in test_drug_pubmed_agent_v2(drug_name_list, 'zh-CN'):
                if chunk.get('type') == 'drug_comparison_done':
                    completed_count += 1
                    final_results['drug_comparison_done'] = chunk.get('summary', '')
                await queue.put(chunk)
        except Exception as e:
            await queue.put({
                'type': 'error',
                'summary': f"药物对比出错: {str(e)}"
            })
    
    async def process_single_group_comparison(indication_name, phase, drug_name, trial_list):
        """处理单个适应症-阶段-药品的临床试验对比"""
        if not trial_list or len(trial_list) < 2:
            return
            
        async with semaphore:  # 限制并发数量
            try:
                # 构建type标识：适应症-phase-药品名字
                type_prefix = f"{indication_name}-{phase}-{drug_name}"
                
                async for chunk in target_for_clinical_trial_comparison(trial_list, 'zh-CN'):
                    # 修改type，加入适应症-phase-药品名字
                    if chunk.get('type') == 'trial_comparison_done':
                        key_name = f'trial_comparison_{type_prefix}'
                        final_results['trial_comparison_done'].append({key_name: chunk.get('summary', '')})
                        save_to_file(f"{type_prefix}_trial_comparison_done", chunk.get('summary', ''))
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison_done',
                            'summary': chunk.get('summary', '')
                        })
                    else:
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison',
                            'summary': chunk.get('summary', '')
                        })
            except Exception as e:
                await queue.put({
                    'type': 'error',
                    'summary': f"{indication_name}-{phase}-{drug_name} 临床试验对比出错: {str(e)}"
                })
    
    async def process_all_clinical_trials():
        """处理所有临床试验对比 - 并行处理"""
        nonlocal completed_count
        
        # 创建所有临床试验对比任务
        trial_tasks = []
        
        # 按照数据结构进行for循环
        for indication_name, phases in grouped_data.items():
            for phase, drugs in phases.items():
                for drug_name, trial_list in drugs.items():
                    # 为每个适应症-阶段-药品组合创建任务
                    if trial_list and len(trial_list) >= 2:
                        task = asyncio.create_task(
                            process_single_group_comparison(indication_name, phase, drug_name, trial_list)
                        )
                        trial_tasks.append(task)
        
        # 等待所有临床试验对比完成
        if trial_tasks:
            await asyncio.gather(*trial_tasks, return_exceptions=True)
        
        # 所有临床试验对比完成
        completed_count += 1
    
    # 启动两个主要任务
    tasks = [
        asyncio.create_task(process_drug_comparison()),
        asyncio.create_task(process_all_clinical_trials())
    ]
    
    # 持续输出结果
    while completed_count < 2:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            yield item
            queue.task_done()
        except asyncio.TimeoutError:
            if all(task.done() for task in tasks):
                break
            continue
    
    # 等待所有任务完成
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 发送最终完成信号，包含所有分析的结果
    yield {
        'type': 'all_comparisons_done',
        'summary': final_results
    }

def keep_highest_phase_only(data):
    """
    按照 indication 分组，每个适应症只保留最高的phase
    
    Args:
        data: 嵌套字典，结构为 {
            "indication_name": {
                "PHASE1": {...},
                "PHASE2": {...},
                "PHASE3": {...}
            }
        }
    
    Returns:
        dict: 处理后的数据，每个适应症只保留最高的phase
    """
    result = {}
    
    # 定义phase的优先级（数字越大优先级越高）
    phase_priority = {
        'PHASE1': 1,
        'PHASE2': 2,
        'PHASE3': 3
    }
    
    for indication, phases in data.items():
        result[indication] = {}
        
        # 找到最高优先级的phase
        highest_phase = None
        highest_priority = 0
        
        for phase in phases.keys():
            if phase in phase_priority:
                priority = phase_priority[phase]
                if priority > highest_priority:
                    highest_priority = priority
                    highest_phase = phase
        
        # 只保留最高优先级的phase
        if highest_phase:
            result[indication][highest_phase] = phases[highest_phase]
    
    return result

def clean_trial_data(data):
    """
    清洗临床试验数据，只保留指定的字段
    
    Args:
        data: 嵌套字典，结构为 {
            "indication_name": {
                "PHASE1": {
                    "drug_name1": [trial1, trial2, ...],
                    "drug_name2": [trial3, trial4, ...],
                    ...
                },
                "PHASE2": {...},
                "PHASE3": {...}
            }
        }
    
    Returns:
        dict: 清洗后的数据，只保留指定字段
    """
    # 定义要保留的字段
    fields_to_keep = {
        'id',
        'drug_name',
        'company',
        'design_phase',
        'country',
        'indication',
        'patient_count',
        'efficacy_summary',
        'safety_summary'
    }
    
    def clean_single_trial(trial):
        """清洗单个试验数据"""
        cleaned_trial = {}
        for field in fields_to_keep:
            if field in trial:
                cleaned_trial[field] = trial[field]
        return cleaned_trial
    
    def clean_drug_trials(drug_trials):
        """清洗某个药品的所有试验数据"""
        return [clean_single_trial(trial) for trial in drug_trials]
    
    def clean_phase_data(phase_data):
        """清洗某个phase下的所有药品数据"""
        cleaned_phase = {}
        for drug_name, trials in phase_data.items():
            cleaned_phase[drug_name] = clean_drug_trials(trials)
        return cleaned_phase
    
    def clean_indication_data(indication_data):
        """清洗某个适应症下的所有phase数据"""
        cleaned_indication = {}
        for phase, phase_data in indication_data.items():
            cleaned_indication[phase] = clean_phase_data(phase_data)
        return cleaned_indication
    
    # 清洗整个数据结构
    result = {}
    for indication, indication_data in data.items():
        result[indication] = clean_indication_data(indication_data)
    
    return result

def extract_drugs_by_indication(data):
    """
    从嵌套的适应症-phase-药品结构中提取每个适应症下的所有药品
    
    Args:
        data: 嵌套字典，结构为 {
            "适应症": {
                "PHASE1": {"药品1": [...], "药品2": [...], ...},
                "PHASE2": {"药品3": [...], "药品4": [...], ...},
                ...
            }
        }
    
    Returns:
        dict: {适应症: 药物列表}
        例如: {
            "Renal cell carcinoma": ["cabozantinib", "sunitinib", "sorafenib"],
            "Prostate cancer": ["cabozantinib", "dovitinib lactate"],
            ...
        }
    """
    result = {}
    
    for indication, phases in data.items():
        drug_set = set()  # 使用set去重
        
        # 遍历该适应症下的所有phase
        for phase, drugs in phases.items():
            # 添加该phase下的所有药品名
            drug_set.update(drugs.keys())
        
        result[indication] = sorted(list(drug_set))
    
    return result


async def split_table_v5(target, language: str = 'zh-CN'):
    """查drug表，排序+filter，再查Trial表，排序+filter，再组成管线表和临床实验表"""

    # drug查询，查四次 approved＞III＞II＞I
    
    phase_list = ["approved", "iii", "ii", "i"]
    origin_drug_dict = dict()
    for phase in phase_list:
        drug_filters = {
            "company": [],
            "drug_feature": {},
            "drug_modality": {},
            "drug_name": {},
            "indication": [],
            "location": [],
            "phase": [phase],
            "target": {
                "data": [
                    target
                ],
                "logic": "or"
            },
            "route_of_administration": {},
            "from_n": 0,
            "size": 10000
        }
        raw_drug_results = await search_drug(drug_filters)
        results = raw_drug_results.get('results')
        # 每个phase的drug列表
        origin_drug_dict[phase] = results

    # 对所有phase的药物组，进去trial数量的排序，并且取i，ii，iii三个的top10和approved的全部
    # 1.取所有的nct_id组成nct_id_list，数据只保留name，phase，nct_id_list
    # 2.对药物组进行trial数量的排序，并且取i，ii，iii三个的top10和approved的全部
    drug_sort_dict = dict()
    for phase, origin_drug_dict_list in origin_drug_dict.items():
        drug_sort_dict[phase] = []
        for origin_drug_dict_item in origin_drug_dict_list:
            ctid_list = collect_all_nct_ids(origin_drug_dict_item)
            sort_drug_dict = {
                "name": origin_drug_dict_item.get('name'),
                "phase": origin_drug_dict_item.get('phase'),
                "nct_id_list": ctid_list
            }
            drug_sort_dict[phase].append(sort_drug_dict)
    yield drug_sort_dict

    # 排序，取top10
    for phase, drug_list in drug_sort_dict.items():
        if phase == "approved":
            top10_drug_list = drug_list
        else:
            drug_list.sort(key=lambda x: len(x.get('nct_id_list')), reverse=True)
            top10_drug_list = drug_list[:10]
        drug_sort_dict[phase] = top10_drug_list
    """ drug_sort_dict目前数据结构
    {
        "approved": [
            {
                "name": "gilteritinib",
                "phase": "Approved",
                "nct_id_list": [
                    "NCT04240002",
                    "NCT05028751",
                    "NCT02421939",
                    "NCT02014558",
                    ...
        "i"
            {
                "name": "gilteritinib",
                "phase": "III",
                "nct_id_list": [
                    "NCT04240002",
                    "NCT05028751",
                    "NCT02421939",
                    "NCT02014558",
                    ...
        "ii": [
            {
                "name": "gilteritinib",
                "phase": "II",
                "nct_id_list": [
                    "NCT04240002",
                    "NCT05028751",
        ...
    }
    """
    # yield drug_sort_dict

    # 对药物phase组进行排序，trial数量逆向排序，过滤没有trial的药物组
    for phase, drug_list in drug_sort_dict.items():
        drug_list.sort(key=lambda x: len(x.get('nct_id_list')), reverse=True)
        drug_list = [drug for drug in drug_list if len(drug.get('nct_id_list')) > 0]
        drug_sort_dict[phase] = drug_list
    # yield drug_sort_dict
    
    # 对每个药物的trial组进行查询 30+n个（3个top10，和一个已获批）
    for phase, drug_list in drug_sort_dict.items():
        for drug in drug_list:  
            nct_id_list = drug.get('nct_id_list')
            ct_filters = {
                "nctid": nct_id_list,
                "from_n": 0,
                "size": 50
            }
            raw_ct_results = await search_clinical_trial(ct_filters)
            results = raw_ct_results.get('results')
            if results:
                drug['trial_list'] = results
            else:
                drug['trial_list'] = []
    # yield drug_sort_dict

    # 对drug_sort_dict进行适应症分组 组内排序用design.phases[0] 顺序是approved>iii>ii>i    
    # 构造药物管线表 和 临床试验表
    for phase, drug_list in drug_sort_dict.items():
        for drug_dict in drug_list:
            all_pipline_and_trial_list = convert_clinical_data_to_dict_v2(drug_dict)
            drug_dict['all_pipline_and_trial_list'] = all_pipline_and_trial_list
            # drug_dict['drug_table'] = drug_table 之前返回的产品管线表
            # drug_dict['trial_table_list'] = trial_table_list 之前返回的临床试验数据表
    
    
    # 对临床试验表进行分组排序
    for phase, drug_list in drug_sort_dict.items():
        for drug_dict in drug_list:
            trial_table_list = drug_dict.get('all_pipline_and_trial_list')
            sorted_trial_table_list = sort_trial_table_list(trial_table_list)
            drug_dict['all_pipline_and_trial_list'] = sorted_trial_table_list

    """ v1 目前drug_sort_dict的两个key，drug_table和trial_table_list数据结构 已废弃
        drug_sort_dict 有以下的key name phase nct_id trial_list drug_table trial_table_list

        "drug_table": {
            "id": "NCT04310007",
            "drug_name": "cabozantinib",
            "company": "Exelixis, Inc., Bristol-Myers Squibb, GSK, Ipsen Pharma, Sobi, Takeda",
            "phase": "Approved",
            "country": "United States",
            "status": "ACTIVE_NOT_RECRUITING",
            "indication": "Non-small cell lung cancer",
            "route_of_administration": "Oral (PO)",
            "study_design": "Step 2, Arm Z (cabozantinib S-malate, nivolumab)：dose[Cabozantinib S-malate++PO+QD+21-day cycle; Nivolumab++IV++21-day cycle]\nStep 1, Arm C (standard chemotherapy)：dose[Ramucirumab++IV++21-day cycle; Docetaxel++IV++21-day cycle; Docetaxel++IV++21-day cycle; Gemcitabine Hydrochloride++IV++21-day cycle; Paclitaxel++IV++21-day cycle; Nab-paclitaxel++IV++21-day cycle]\nStep 1, Arm A (cabozantinib S-malate)：dose[Cabozantinib S-malate++PO+QD+21-day cycle]\nStep 1, Arm B (cabozantinib S-malate, nivolumab)：dose[Cabozantinib S-malate++PO+QD+21-day cycle; Nivolumab++IV++21-day cycle]",
            "start_date": "2020-07-13",
            "primary_completion_date": "2026-12-31"
        }, 
        "trial_table_list": [
            {
                "id": "NCT04091750",
                "drug_name": "cabozantinib",
                "company": "Exelixis, Inc., Bristol-Myers Squibb, GSK, Ipsen Pharma, Sobi, Takeda",
                "patient_count": "27 (ESTIMATED)",
                "indication": "Malignant melanoma",
                "efficacy_summary": "未知",
                "safety_summary": "未知",
                "country": "United States",
                "design_phase": "Phase1"
            }, {
                "id": "NCT04878029",
                "drug_name": "cabozantinib",
                "company": "Exelixis, Inc., Bristol-Myers Squibb, GSK, Ipsen Pharma, Sobi, Takeda",
                "patient_count": "32 (ESTIMATED)",
                "indication": "Bladder cancer",
                "efficacy_summary": "- Primary Endpoint (Safety and Tolerability) <2024-06-02>: Data indicates safety and tolerability with a manageable AE profile ([1](https://meetings.asco.org/abstracts-presentations/231911))\n- Secondary Endpoint (ORR per RECIST v1.1) <2024-06-02>: ORR of 88.9% with 7 PR, 1 CR, 1 SD with 18.94% target lesion reduction, median target lesion reduction of 52.51% (18.94-100) ([1](https://meetings.asco.org/abstracts-presentations/231911))",
                "safety_summary": "- Adverse Events <2024-06-02>: Fatigue (55.6%), skin rash, hand-foot syndrome, anorexia (44.4%), hyponatremia, hypophosphatemia, mucositis, ALT elevation, peripheral sensory neuropathy (33.3%) ([1](https://meetings.asco.org/abstracts-presentations/231911))\n- Grade ≥ 3 AEs <2024-06-02>: Neutropenia, hyponatremia, AKI, fatigue (22.2%) ([1](https://meetings.asco.org/abstracts-presentations/231911))",
                "country": "United States"
                "design_phase": "Phase3"
            },
            {...
        ]

    """

    """ v2 全量trial数据 ，筛选字段变成产品管线表  要去筛选最高phase的，变成trial表
    result_dict = {
            'id': nct_id,
            'drug_name': drug_name,  # 使用传入的name
            'company': company_names,
            'design_phase': design_phase,  # 直接使用传入的phase
            'country': countries,
            'status': status + ',' + drug_phase,
            'indication': indication_specific,
            'route_of_administration': administration_routes,
            'study_design': study_design_desc,
            'start_date': start_date,
            'primary_completion_date': primary_completion_date,
            'patient_count': patient_count + ' ' + '(' + enrollment_number_type + ')',
            'efficacy_summary': efficacy_summary,
            'safety_summary': safety_summary,
        }
    """
    # yield drug_sort_dict
    
    # 把所有drug_sort_dict的all_pipline_and_trial_list放进一个list中，
    drug_sort_dict_list = list()
    for phase, drug_list in drug_sort_dict.items():
        for drug_dict in drug_list:
            drug_sort_dict_list.append(drug_dict)
    
    # drug_table_md, trial_table_md = generate_markdown_tables(drug_sort_dict_list)
    # save_to_file(f"1025 drug v4", drug_table_md)
    # save_to_file(f"1025 trial v4", trial_table_md)

    # 1.筛选十个药，十个药进行对比
    # 1.1 从drug_sort_dict_list中获取所有的药品name，构造drug_name_list，为药物深度对比做准备
    drug_name_list = list()
    for drug_dict in drug_sort_dict_list:
        drug_name_list.append(drug_dict.get('name'))
    
    # 2.临床试验对比
    # 每个药的临床试验进行横向对比
    # 对临床试验进行分组，对适应症和phase分组
    # group_by_indication_and_phase
    # 构造临床试验列表
    all_trial_compare_list = list()
    group_trial_compare_list = list()
    trial_compare_list = list()    
    for drug_dict in drug_sort_dict_list:
        trial_table_list = drug_dict.get('all_pipline_and_trial_list')
        all_trial_compare_list.extend(trial_table_list)
    # 按适应症 phase 去分组
    group_trial_compare_dict = group_by_indication_and_phase_and_drug_v1(all_trial_compare_list)
    # 按适应症提取所有的药物
    indication_drug_dict = extract_drugs_by_indication(group_trial_compare_dict)
    # 分组之后只保留最高phase
    phase_group_trial_compare_dict = keep_highest_phase_only(group_trial_compare_dict)
    # 保留每组大于等于两个药的组 keep_highest_phase_only
    multiple_drug_group_trial_compare_dict = filter_groups_with_multiple_drugs(phase_group_trial_compare_dict)

    pipline_table_list = list()
    for drug_dict in drug_sort_dict_list:
        all_pipline_and_trial_list = drug_dict.get('all_pipline_and_trial_list')
        pipline_table_list.extend(all_pipline_and_trial_list)
    # ## 生成产品管线表
    drug_table_md = generate_drug_markdown_table(pipline_table_list)
    # save_to_file("pipline_table_md", drug_table_md)


    # target和indications横向对比 （成熟度和开发风险） 上接临床实验组对比分析 调用pubmed 提示词horizontal_comparison_of_indications_pubmed_prompt
    # 1.1 multiple_drug_group_trial_compare_dict提取indications
    # 他是这个结构的，每个key是indication  
    indications = list(multiple_drug_group_trial_compare_dict.keys())
    # 1.2 所有适应症横向对比 （成熟度和开发风险）
    last_horizontal_comparison_of_indications_chunk = str()
    async for chunk in run_pubmed_agent(
        query=target,
        language=language,
        prompt_template=horizontal_comparison_of_indications_pubmed_prompt,
        template_kwargs={'target': target, 'indications': indications}
    ):
        last_horizontal_comparison_of_indications_chunk = chunk
        yield {"type": 'horizontal_comparison_of_indications', "summary": last_horizontal_comparison_of_indications_chunk}
    yield {"type": 'horizontal_comparison_of_indications_done', "summary": last_horizontal_comparison_of_indications_chunk}
    # save_to_file("1027 last_horizontal_comparison_of_indications_chunk", str(last_horizontal_comparison_of_indications_chunk))

    # 1、药物深度分析 drug_name_list
    last_drug_chunk = ''
    async for chunk in test_drug_pubmed_agent_v2(drug_name_list, 'zh-CN'):
        last_drug_chunk = chunk.get('summary', '')
        yield {"type": 'drug_depth_analysis', "summary": last_drug_chunk}
    yield {"type": 'drug_depth_analysis_done', "summary": last_drug_chunk}
    # save_to_file("1024 last_drug_chunk", str(last_drug_chunk))
    # 2、临床试验对比 multiple_drug_group_trial_compare_dict
    """
    {'Renal cell carcinoma': 
        {'PHASE3': 
            {药品名字：[pipline_trial_dict1, ....]},
    'Prostate cancer': {'PHASE2': {...}},
    'Ovarian cancer': {'PHASE2': {...}},
    'Neoplasm': {'PHASE1': {...}},
    'Glioblastoma multiforme': {'PHASE2': {...}},
    'Breast cancer': {'PHASE2': {...}},
    'Acute myeloid leukaemia': {'PHASE3': {...}},
    'Myelofibrosis': {'PHASE3': {...}}
    """
    # 2.1、先把数据洗一遍，过滤掉不用的字段
    """{    只保留着几个字段就可以
            'id': nct_id,
            'drug_name': drug_name,  # 使用传入的name
            'company': company_names,
            'design_phase': design_phase,  # 直接使用传入的phase
            'country': countries,
            'indication': indication_specific,
            'patient_count': patient_count + ' ' + '(' + enrollment_number_type + ')',
            'efficacy_summary': efficacy_summary,
            'safety_summary': safety_summary,
        }
    """
    # 清洗数据
    multiple_drug_group_trial_compare_result_dict = dict()
    multiple_drug_group_trial_compare_result_dict = clean_trial_data(multiple_drug_group_trial_compare_dict)
    
    
    
    # 对需要分析的临床试验 添加 所有药品 以便再最后的时候分析(BIC)
    multiple_drug_list_group_trial_compare_result_dict = dict()
    for indication, phase_drug_dict in multiple_drug_group_trial_compare_result_dict.items():
        multiple_drug_list_group_trial_compare_result_dict[indication] = {
            "phase_data": phase_drug_dict,
            "drug_list": indication_drug_dict.get(indication)
        }



    # 2.2、并行进行临床试验数据对比，包括 1.制作临床试验数据表 2.临床试验结果分析 3.临床试验对比。
    last_clinical_trial_chunk = ''
    async for chunk in parallel_clinical_trial_comparison_v4(multiple_drug_list_group_trial_compare_result_dict):
        last_clinical_trial_chunk = chunk
        yield chunk
    save_to_file("1024 last_clinical_trial_chunk", str(last_clinical_trial_chunk))
    """ 最终临床试验结果的数据结构
    {
    'type': 'parallel_clinical_trial_comparison_done',
    'trial_comparison_done': [
        { 以下代表每一个临床试验对比表 和 对比结果
            'trial_comparison_Prostate cancer-PHASE2-[cabozantinib,dovitinib lactate]': '## Prostate cancer-PHASE2...'
        },
        {
            'trial_comparison_Ovarian cancer-PHASE2-[cabozantinib,sorafenib]': '## Ovarian cancer-PHASE2-[cabozan...'
        }
    ]
    """
    # 构造result结构
    drug_trial_comparison_summary = dict()
    drug_trial_comparison_summary.update({'pipline_table': drug_table_md, 'drug_depth_analysis': last_drug_chunk})
    drug_trial_comparison_summary.update({'horizontal_comparison_of_indications': last_horizontal_comparison_of_indications_chunk})
    drug_trial_comparison_summary.update(last_clinical_trial_chunk)
    yield {'type': 'parallel_drug_and_trial_comparison_done', 'summary': drug_trial_comparison_summary}


# workflow target -> indication_list -> llm适应症  治疗金标准和流行病学
async def target_for_indications_and_epidemiology_and_gold_standard(target: str, language: str = 'en'):
    """
    根据target生成indication列表，然后对每个indication并发调用pubmed大模型输出【治疗金标准和流行病学】相关的总结。
    """
    indications = list()
    # 第一步：通过target抽取indication列表
    SchemaClass = get_extract_top_relevant_indications_schema(target)
    schema = get_openai_json_schema_v3(SchemaClass)
    
    tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
    llm = CompositeClaude()
    try:
        result = await function_call_with_retry(
            llm,
            user_prompt=extract_top_relevant_indications_prompt.format(target=target),
            tools=schema,
            tool_choice=tool_choice,
            temperature=0.3
        )
        
        indications = result.get("indications")
    except Exception as e:
        raise Exception(f"靶点分析服务异常: {str(e)}")
    
    if not indications:
        return
    
    # 第二步：并发处理每个indication
    queue = asyncio.Queue()
    active_tasks = 0
    final_results = {}  # 保存每个适应症的最后一次返回结果
    
    async def analyze_indication(indication):
        """分析单个适应症"""
        nonlocal active_tasks
        last_chunk = None  # 保存最后一次的chunk
        
        try:
            async for chunk in epidemiology_and_gold_standard_of_treatment_v2(target, indication, language):
                last_chunk = chunk  # 更新最后一次的chunk
                await queue.put({
                    'type': f'{indication}+分析',
                    'summary': chunk
                })
            
            # 保存最后一次的结果到字典
            if last_chunk is not None:
                final_results[indication] = last_chunk
                
        except Exception as e:
            error_msg = f"分析适应症 {indication} 时出错: {str(e)}"
            await queue.put({
                'type': 'error',
                'summary': error_msg
            })
            # 保存错误信息到字典
            final_results[indication] = error_msg
        finally:
            active_tasks -= 1
    
    # 启动所有适应症分析任务
    tasks = []
    for indication in indications:
        active_tasks += 1
        task = asyncio.create_task(analyze_indication(indication))
        tasks.append(task)
    
    # 持续从队列中获取结果，直到所有任务完成
    while active_tasks > 0 or not queue.empty():
        try:
            # 等待队列中的项目，设置超时
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
            yield item
            queue.task_done()
        except asyncio.TimeoutError:
            # 超时继续检查
            continue
    
    # 确保所有任务完成
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 最后返回所有适应症的最后一次结果
    if final_results:
        yield {
            'type': 'target_for_indications_done',
            'summary': final_results
        }

async def test_drug_pubmed_agent_v2(query, language):
    # 药物横向对比
    last_chunk = ''

    async for chunk in run_pubmed_agent(
        query=query,
        language=language,
        prompt_template=pubmed_depth_analysis_of_drugs_prompt_v2
    ):
        yield {"type": 'drug_comparison', "summary": chunk}
        last_chunk = chunk
    yield {"type": 'drug_comparison_done', "summary": last_chunk}


async def parallel_clinical_trial_comparison_v2(grouped_data):
    """
    并行处理临床试验对比 v2
    
    参数:
        grouped_data: 按适应症-阶段-药品分组的数据，结构为 {
            "indication_name": {
                "PHASE1": {
                    "drug_name1": [trial1, trial2, ...],
                    "drug_name2": [trial3, trial4, ...],
                    ...
                },
                "PHASE2": {...},
                "PHASE3": {...}
            }
        }
    
    返回:
        异步生成器，yield对比分析结果
    """
    import asyncio
    from asyncio import Semaphore
    
    queue = asyncio.Queue()
    completed_count = 0
    final_results = {
        "trial_comparison_done": list()
    }  # 保存所有分析的最终结果
    semaphore = Semaphore(5)  # 最多同时处理5个临床试验对比
    
    async def process_single_group_comparison(indication_name, phase, drug_name, trial_list):
        """处理单个适应症-阶段-药品的临床试验对比"""
        nonlocal completed_count
        if not trial_list or len(trial_list) < 2:
            completed_count += 1
            return
            
        async with semaphore:  # 限制并发数量
            try:
                # 构建type标识：适应症-phase-药品名字
                type_prefix = f"{indication_name}-{phase}-{drug_name}"

                async for chunk in target_for_clinical_trial_comparison(trial_list, 'zh-CN'):
                    
                    # 修改type，加入适应症-phase-药品名字
                    if chunk.get('type') == 'trial_comparison_done':
                        key_name = f'trial_comparison_{type_prefix}'
                        final_results['trial_comparison_done'].append({key_name: chunk.get('summary', '')})
                        save_to_file(f"{type_prefix}_trial_comparison_done", chunk.get('summary', ''))
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison_done',
                            'summary': chunk.get('summary', '')
                        })
                    else:
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison',
                            'summary': chunk.get('summary', '')
                        })
            except Exception as e:
                await queue.put({
                    'type': 'error',
                    'summary': f"{indication_name}-{phase}-{drug_name} 临床试验对比出错: {str(e)}"
                })
            finally:
                completed_count += 1
    
    async def pump():
        """从队列中取出结果并yield"""
        while completed_count < total_tasks:
            try:
                result = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield result
            except asyncio.TimeoutError:
                continue
    
    # 计算总任务数
    total_tasks = 0
    tasks = []
    
    # 遍历所有适应症-阶段-药品组合
    for indication_name, phases in grouped_data.items():
        for phase, drugs in phases.items():
            for drug_name, trial_list in drugs.items():
                if trial_list and len(trial_list) >= 2:
                    total_tasks += 1
                    task = asyncio.create_task(
                        process_single_group_comparison(indication_name, phase, drug_name, trial_list)
                    )
                    tasks.append(task)
    
    # 启动pump任务
    pump_task = asyncio.create_task(pump())
    
    try:
        # 等待所有任务完成
        await asyncio.gather(*tasks)
        
        # 等待pump任务完成
        await pump_task
        
        # 返回最终结果
        yield {
            'type': 'parallel_clinical_trial_comparison_done',
            'trial_comparison_done': final_results['trial_comparison_done']
        }
        
    finally:
        # 清理任务
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        if not pump_task.done():
            pump_task.cancel()
            try:
                await pump_task
            except asyncio.CancelledError:
                pass

async def parallel_clinical_trial_comparison_v3(grouped_data):
    """
    并行处理临床试验对比 v3 - 对比每个适应症下第一个phase的所有药品
    """
    import asyncio
    from asyncio import Semaphore
    
    queue = asyncio.Queue()
    completed_count = 0
    final_results = {
        "trial_comparison_done": list()
    }
    semaphore = Semaphore(5)
    
    async def process_indication_comparison(indication_name, phase, all_drugs_trials):
        """处理单个适应症下第一个phase的所有药品对比"""
        nonlocal completed_count
        
        # 提前定义变量，避免作用域问题
        drug_names_str = ""
        type_prefix = ""
        
        try:
            if len(all_drugs_trials) < 2:
                completed_count += 1
                return
                
            async with semaphore:
                drug_names = list(all_drugs_trials.keys())
                drug_names_str = ','.join(drug_names)
                type_prefix = f"{indication_name}-{phase}-[{drug_names_str}]"
                
                combined_trial_list = []
                for drug_name, trial_list in all_drugs_trials.items():
                    combined_trial_list.extend(trial_list)
                
                # 将combined_trial_list转换为md表格字符串
                combined_trial_list_md = generate_trial_markdown_table(combined_trial_list)
                trial_table_header = f'## {type_prefix} \n' + combined_trial_list_md
                
                async for chunk in target_for_clinical_trial_comparison(combined_trial_list, 'zh-CN'):
                    summary = trial_table_header + '\n' + chunk.get('summary', '')
                    if chunk.get('type') == 'trial_comparison_done':
                        key_name = f'trial_comparison_{type_prefix}'
                        final_results['trial_comparison_done'].append({key_name: summary})
                        save_to_file(f"{type_prefix}_trial_comparison_done", summary)
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison_done',
                            'summary': summary
                        })
                    else:
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison',
                            'summary': summary
                        })
        except Exception as e:
            # 使用安全的错误信息
            error_prefix = type_prefix if type_prefix else f"{indication_name}-{phase}"
            await queue.put({
                'type': 'error',
                'summary': f"{error_prefix} 临床试验对比出错: {str(e)}"
            })
        finally:
            completed_count += 1
    
    # 计算总任务数并准备数据
    total_tasks = 0
    tasks = []
    
    for indication_name, phases in grouped_data.items():
        if phases:
            first_phase = list(phases.keys())[0]
            first_phase_drugs = phases[first_phase]
            
            if len(first_phase_drugs) >= 2:
                total_tasks += 1
                task = asyncio.create_task(
                    process_indication_comparison(indication_name, first_phase, first_phase_drugs)
                )
                tasks.append(task)
    
    if total_tasks == 0:
        yield {
            'type': 'parallel_clinical_trial_comparison_done',
            'trial_comparison_done': final_results['trial_comparison_done']
        }
        return
    
    # 等待所有任务完成
    try:
        # 使用asyncio.gather等待所有任务
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理队列中所有剩余结果
        while not queue.empty():
            try:
                result = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield result
            except asyncio.TimeoutError:
                break
        
        # 返回最终结果
        yield {
            'type': 'parallel_clinical_trial_comparison_done',
            'trial_comparison_done': final_results['trial_comparison_done']
        }
        
    finally:
        # 清理未完成的任务
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

async def analyze_trial_result(trial_dict, language='zh-CN'):
    """分析单个临床试验的结果
    
    Args:
        trial_dict: 单个临床试验的字典数据
        language: 语言
    
    Yields:
        分析结果
    """
    trial_result = str()
    llm = CompositeClaude()
    prompt = trial_result_prompt_v2.format(table_dict=trial_dict)
    async for chunk in llm.stream_call(sys_prompt=prompt):
        trial_result += chunk
        yield {"type": "trial_result", "summary": trial_result}
    yield {"type": "trial_result_done", "summary": trial_result}


async def analyze_trials_in_parallel(trial_list):
    """
    并行分析多个临床试验，将分析结果添加到每个试验数据中
    
    Args:
        trial_list: 临床试验列表，每个元素是一个字典
    
    Returns:
        list: 添加了analysis_result字段的临床试验列表
    """
    import asyncio
    from asyncio import Semaphore
    
    semaphore = Semaphore(5)  # 限制并发数量
    
    async def analyze_single_trial_with_result(trial):
        """分析单个临床试验并返回结果"""
        async with semaphore:
            analysis_result = ''
            
            # 调用analyze_trial_result函数
            async for chunk in analyze_trial_result(trial, 'zh-CN'):
                if chunk.get('type') == 'trial_result_done':
                    analysis_result = chunk.get('summary', '')
                    break
            
            # 将分析结果添加到原字典中
            trial_with_analysis = trial.copy()
            trial_with_analysis['trial_result_analysis'] = analysis_result
            
            return trial_with_analysis
    
    # 创建所有分析任务
    tasks = [analyze_single_trial_with_result(trial) for trial in trial_list]
    
    # 并行执行所有任务
    analyzed_trials = await asyncio.gather(*tasks)
    
    return list(analyzed_trials)


async def parallel_clinical_trial_comparison_v4(grouped_data):
    """

    参数:
    grouped_data: {
        "适应症": {
            "phase_data": {
                "阶段名称(PHASE1, PHASE2, PHASE3, PHASE4)":
                    "药品1": [临床试验1, 临床试验2, ...],
                    "药品2": [临床试验3, 临床试验4, ...],
                    ...
            },
            "drug_list": [药品1, 药品2, ...],
        }
    }

    并行处理临床试验对比 v4
    1.对所有临床试验的结果进行分析（好/坏，原因，如不好，有无联用药物机会）
    2.制作所有临床试验对比组的表（添加临床试验结果分析列）
    3.对比每个适应症下第一个phase的所有药品
    4.对比每个适应症下所有药品

    输出：
    1.临床试验结果表
    2.临床试验结果对比
    3.临床试验药品分析（BIC...） TODO
    """
    import asyncio
    from asyncio import Semaphore
    
    queue = asyncio.Queue()
    completed_count = 0
    final_results = {
        "trial_comparison_done": list()
    }
    semaphore = Semaphore(5)
    
    async def process_indication_comparison(indication_name, phase, all_drugs_trials):
        """处理单个适应症下第一个phase的所有药品对比"""
        nonlocal completed_count
        
        # 提前定义变量，避免作用域问题
        drug_names_str = ""
        type_prefix = ""
        
        try:
            if len(all_drugs_trials) < 2:
                completed_count += 1
                return
                
            async with semaphore:
                drug_names = list(all_drugs_trials.keys())
                drug_names_str = ','.join(drug_names)
                type_prefix = f"{indication_name}-{phase}-[{drug_names_str}]"
                
                combined_trial_list = []
                for drug_name, trial_list in all_drugs_trials.items():
                    combined_trial_list.extend(trial_list)

                # 对combined_trial_list进行llm输出临床试验结果分析，然后添加到trial表中 并行处理
                append_result_trial_list = await analyze_trials_in_parallel(combined_trial_list)
                
                # 将combined_trial_list转换为md表格字符串
                combined_trial_list_md = generate_trial_markdown_table(append_result_trial_list)
                trial_table_header = f'## {type_prefix} \n' + combined_trial_list_md

                
                async for chunk in target_for_clinical_trial_comparison(append_result_trial_list, 'zh-CN'):
                    summary = trial_table_header + '\n\n' + chunk.get('summary', '')
                    if chunk.get('type') == 'trial_comparison_done':
                        key_name = f'trial_comparison_{type_prefix}'
                        final_results['trial_comparison_done'].append({key_name: summary})
                        save_to_file(f"1027_{type_prefix}_trial_comparison_done", summary)
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison_done',
                            'summary': summary
                        })
                    else:
                        await queue.put({
                            'type': f'{type_prefix}_trial_comparison',
                            'summary': summary
                        })
        except Exception as e:
            # 使用安全的错误信息
            error_prefix = type_prefix if type_prefix else f"{indication_name}-{phase}"
            await queue.put({
                'type': 'error',
                'summary': f"{error_prefix} 临床试验对比出错: {str(e)}"
            })
        finally:
            completed_count += 1
    
    # 计算总任务数并准备数据
    total_tasks = 0
    tasks = []
    
    for indication_name, data in grouped_data.items():  
        phases = data.get("phase_data")
        drug_list = data.get("drug_list")
        if phases:
            first_phase = list(phases.keys())[0]
            first_phase_drugs = phases[first_phase]
            
            if len(first_phase_drugs) >= 2:
                total_tasks += 1
                task = asyncio.create_task(
                    process_indication_comparison(indication_name, first_phase, first_phase_drugs)
                )
                tasks.append(task)
    
    if total_tasks == 0:
        yield {
            'type': 'parallel_clinical_trial_comparison_done',
            'trial_comparison_done': final_results['trial_comparison_done']
        }
        return
    
    # 等待所有任务完成
    try:
        # 使用asyncio.gather等待所有任务
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理队列中所有剩余结果
        while not queue.empty():
            try:
                result = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield result
            except asyncio.TimeoutError:
                break
        
        # 返回最终结果
        yield {
            'type': 'parallel_clinical_trial_comparison_done',
            'trial_comparison_done': final_results['trial_comparison_done']
        }
        
    finally:
        # 清理未完成的任务
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass



async def pubmed_mechanism_of_action_of_target_biology_agent(query, language):
    """靶点生物学v2"""
    last_pubmed = ''
    
    pubmed_gen = run_pubmed_agent(
        query=query,
        language=language,
        prompt_template=pubmed_mechanism_of_action_of_target_biology_prompt
    )
    
    try:
        # 直接流式返回PubMed结果
        async for content in pubmed_gen:
            if content:
                last_pubmed = content
            yield {'type': 'pubmed_mechanism_of_action_of_target_biology', 'summary': content}
        yield {'type': 'pubmed_mechanism_of_action_of_target_biology_done', 'summary': last_pubmed}
    except Exception as e:
        raise Exception(f"靶点生物学分析服务异常: {str(e)}")

def generate_comprehensive_report(query, target_biology, drug_analysis, indications_epidemiology, news_catalyst):
    """生成综合报告"""
    report = f"# {query} 靶点分析报告\n\n"
    
    # 一、作用机制
    report += "## 一、作用机制\n\n"
    
    # 1. 靶点生物学基础
    if target_biology:
        report += "### 1. 靶点生物学基础\n\n"
        report += str(target_biology) + "\n\n"
    
    # 2. 药物深度分析
    if drug_analysis and isinstance(drug_analysis, dict):
        drug_comparison = drug_analysis.get("drug_comparison_done", "")
        if drug_comparison:
            report += "### 2. 药物深度分析\n\n"
            report += str(drug_comparison) + "\n\n"
    
    # 二、产品管线
    if drug_analysis and isinstance(drug_analysis, dict):
        drug_table = drug_analysis.get("drug_table", "")
        if drug_table:
            report += "## 二、产品管线\n\n"
            report += str(drug_table) + "\n\n"
    
    # 三、临床结果表和临床结果横向分析
    if drug_analysis and isinstance(drug_analysis, dict):
        trial_table = drug_analysis.get("trial_table", "")
        trial_comparison = drug_analysis.get("trial_comparison_done", [])
        
        # 三.1 临床结果表
        if trial_table:
            report += "## 三、临床结果表\n\n"
            report += str(trial_table) + "\n\n"
        
        # 三.2 临床结果横向分析
        if trial_comparison:
            report += "## 三、临床结果横向分析\n\n"
            if isinstance(trial_comparison, list):
                for comparison_item in trial_comparison:
                    if isinstance(comparison_item, dict):
                        for drug_name, comparison_result in comparison_item.items():
                            report += f"### {drug_name} 临床试验对比\n\n"
                            report += str(comparison_result) + "\n\n"
            else:
                # 如果不是列表，直接作为字符串处理
                report += str(trial_comparison) + "\n\n"
    
    # 四、适应症市场
    if indications_epidemiology and isinstance(indications_epidemiology, dict):
        report += "## 四、适应症市场\n\n"
        for indication_name, indication_summary in indications_epidemiology.items():
            report += f"### {indication_name}\n\n"
            report += str(indication_summary) + "\n\n"
    
    # 五、近期进展
    if news_catalyst:
        report += "## 五、近期进展\n\n"
        report += str(news_catalyst) + "\n\n"
    
    return report

def generate_comprehensive_report_v2(query, target_biology, drug_analysis, indications_epidemiology, news_catalyst):
    """生成综合报告"""
    report = f"# {query} 靶点分析报告\n\n"
    
    # 一、作用机制
    report += "## 一、作用机制\n\n"
    
    # 1. 靶点生物学基础
    if target_biology:
        report += "### 1. 靶点生物学基础\n\n"
        report += str(target_biology) + "\n\n"
    
    # 2. 药物深度分析
    if drug_analysis and isinstance(drug_analysis, dict):
        drug_comparison_done = drug_analysis.get('drug_depth_analysis', '')
        if drug_comparison_done:
            report += "### 2. 药物深度分析\n\n"
            report += str(drug_comparison_done) + "\n\n"
    
    # 二、产品管线
    if drug_analysis and isinstance(drug_analysis, dict):
        pipeline_table = drug_analysis.get('pipline_table', '')
        if pipeline_table:
            report += "## 二、产品管线\n\n"
            report += str(pipeline_table) + "\n\n"
    
    # 三、临床结果表和临床结果横向分析
    if drug_analysis and isinstance(drug_analysis, dict):
        trial_comparison_done = drug_analysis.get('trial_comparison_done', [])
        if trial_comparison_done:
            report += "## 三、临床结果表和临床结果分析\n\n"
            
            for trial_comparison in trial_comparison_done:
                if isinstance(trial_comparison, dict):
                    for key, value in trial_comparison.items():
                        # 去掉trial_comparison_前缀
                        if key.startswith('trial_comparison_'):
                            clean_key = key.replace('trial_comparison_', '')
                            # 添加临床试验对比标题
                            report += f"### {clean_key} 临床试验对比\n\n"
                            report += str(value) + "\n\n"
    
    # 三、1.适应症市场横向分析
    if drug_analysis and isinstance(drug_analysis, dict):
        horizontal_comparison_of_indications = drug_analysis.get('horizontal_comparison_of_indications', '')
        if horizontal_comparison_of_indications:
            report += "### 3.1 临床结果适应症市场横向分析\n\n"
            report += str(horizontal_comparison_of_indications) + "\n\n"
        
    # 四、适应症市场
    if indications_epidemiology:
        report += "## 四、适应症市场\n\n"
        if isinstance(indications_epidemiology, dict):
            for indication, summary in indications_epidemiology.items():
                report += f"### {indication}\n\n"
                report += str(summary) + "\n\n"
        else:
            report += str(indications_epidemiology) + "\n\n"
    
    # 五、近期进展
    if news_catalyst:
        report += "## 五、近期进展\n\n"
        report += str(news_catalyst) + "\n\n"
    
    return report


async def drug_target_analysis_stream(query, language):
    """ 
    @summary: 医学靶点分析
    1.靶点生物学    pubmed_mechanism_of_action_of_target_biology_agent
    2.药品分析和临床结果对比  split_table_v5
    3.适应症的流行病学和治疗金标准   target_for_indications_and_epidemiology_and_gold_standard
    4.靶点催化剂事件与新闻   news_and_catalyst_agent
    """

    import asyncio, contextlib, json

    # 四个任务并行 用queue并行抛出
    queue = asyncio.Queue()
    done = 0
    last_results = {
        "target_biology": '',
        "drug_analysis": '',
        "indications_epidemiology": '',
        "news_catalyst": ''
    }
    
    # 映射每个任务的完成类型key
    done_type_mapping = {
        "target_biology": "pubmed_mechanism_of_action_of_target_biology_done",
        "drug_analysis": "parallel_drug_and_trial_comparison_done",
        "indications_epidemiology": "target_for_indications_done",
        "news_catalyst": "catalyst_news_done"
    }

    async def pump(label, agen, result_key):
        nonlocal done
        try:
            async for content in agen:
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except:
                        pass
                
                if isinstance(content, dict):
                    content_type = content.get('type', '')
                    # 检查是否是该任务的完成标记
                    if content_type == done_type_mapping[result_key]:
                        # 保存最终结果
                        last_results[result_key] = content.get('summary', '')
                    # 流式返回所有内容
                    await queue.put(f"[{label}] {json.dumps(content, ensure_ascii=False)}")
                else:
                    await queue.put(f"[{label}] {content}")
        finally:
            done += 1

    # 创建四个任务的生成器
    target_biology_gen = pubmed_mechanism_of_action_of_target_biology_agent(query, language)
    drug_analysis_gen = split_table_v5(query)
    indications_gen = target_for_indications_and_epidemiology_and_gold_standard(query, language)
    news_catalyst_gen = news_and_catalyst_agent(query, language)

    # 创建四个任务
    t1 = asyncio.create_task(pump("Target Biology", target_biology_gen, "target_biology"))
    t2 = asyncio.create_task(pump("Drug Analysis", drug_analysis_gen, "drug_analysis"))
    t3 = asyncio.create_task(pump("Indications & Epidemiology", indications_gen, "indications_epidemiology"))
    t4 = asyncio.create_task(pump("News & Catalyst", news_catalyst_gen, "news_catalyst"))

    try:
        # 持续从队列取并向外流式返回，直到四个源都结束且队列清空
        while done < 4 or not queue.empty():
            item = await queue.get()
            yield item
    finally:
        # 清理任务
        for t in (t1, t2, t3, t4):
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        
        # 生成综合报告
        try:
            if any([last_results["target_biology"], last_results["drug_analysis"], 
                   last_results["indications_epidemiology"], last_results["news_catalyst"]]):
                
                report_content = generate_comprehensive_report_v2(
                    query, 
                    last_results["target_biology"], 
                    last_results["drug_analysis"], 
                    last_results["indications_epidemiology"], 
                    last_results["news_catalyst"]
                )
                save_to_file(f"Target Analysis Report - {query} {datetime.now().strftime('%Y%m%d_%H%M%S')}", report_content)
        except Exception as e:
            logging.error(f"Error generating comprehensive report: {e}")