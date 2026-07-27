import re
import pytz
from datetime import datetime
import json
import shutil
import os
import asyncio
import io
import logging
import time
import traceback
import httpx
from typing import Any, Callable, List, Type

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from llm.composite_models import CompositeHitlFinal, Compositeo3, DeepseekClaude, LowEffortSlotFillingModels, DeepseekChatModels
from agent.explore.mindsearch_hitl_agent import MindSearchMedicalHitlAgent
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from agent.policy.schema import PolicyRegionSchema, FurtherSearchSchema, WebSearchSchema
from agent.policy.prompt import region_selection_prompt, further_search_prompt, summary_prompt, web_search_prompt, web_search_content_prompt
from utils.core.exception import UnexpectedException
from llm.deepseek_models import CompositeDeepseekChat, CompositeDeepseekReasoner
from llm.gcp_models import ClaudeSonnet4, CompositeClaude
from config import settings

logger = logging.getLogger(__name__)


class PolicyAgentV2(AgentPreset):
    llm: BaseLLM = DeepseekChatModels()
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    language: str = "zh-CN"
    error: bool = False
    response: MindSearchResponse = None
    policy_rag_url: str = ""
    output_dir: str = ""
    buffer: str = ""
    web_search_content: str = ""
    
    def __init__(self, query_params={}, **kwargs):
        super().__init__()
        self.policy_rag_url = f"{settings.PGRAG_HOST}/query/stream"
        self.output_dir = f"outputs/policy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    async def use_tool(self, user_prompt: str = "", **kwargs):
        try:
            self.response = self.mindsearch_helper.init_response(self)
            yield self.response
            self.response.search_graph = self.init_search_graph()
            self.response.processing_type = ProcessingType.PROCESSING
            yield self.response

            region_schema = get_openai_json_schema_v3(PolicyRegionSchema)
            region_tool_choice = {"type": "function", "function": {"name": region_schema[0]['function']['name']}}
            region_arguments = await function_call_with_retry(self.llm, tools=region_schema, tool_choice=region_tool_choice, user_prompt=region_selection_prompt.format(user_prompt=user_prompt), temperature=0.3)
            region = region_arguments.get('region', '')

            self.response.search_graph.children[0].thought_process += f"调用地区知识库: {region}\n"
            # self.response.search_graph.children[0].summary = "DONE"
            
            yield self.response
            
            region_mapping = {
                "安徽": "ah",
                "北京": "bj",
                "重庆": "cq",
                "福建": "fj",
                "广东": "gd",
                "国家": "gj",
                "甘肃": "gs",
                "广西": "gx",
                "贵州": "gz",
                "海南": "hai",
                "河北": "hb",
                "黑龙江": "hlj",
                "河南": "hn",
                "湖北": "hub",
                "湖南": "hun",
                "吉林": "jl",
                "江苏": "js",
                "江西": "jx",
                "辽宁": "ln",
                "内蒙古": "nmg",
                "宁夏": "nx",
                "青海": "qh",
                "四川": "sc",
                "山东": "sd",
                "上海": "sh",
                "陕西": "sn",
                "山西": "sx",
                "天津": "tj",
                "新疆": "xj",
                "西藏": "xz",
                "云南": "yn"
            }

            
            # policy_rag_url = "http://localhost:9622/query/stream"
            body = {"mode":"mix",
                    "workspace": region_mapping.get(region, "gj") if region else "gj",
                    "response_type":"Multiple Paragraphs",
                    "top_k":10,
                    "chunk_top_k":30,
                    "max_entity_tokens":3000,
                    "max_relation_tokens":4000,
                    "max_total_tokens":30000,
                    "only_need_context":False,
                    "only_need_prompt":False,
                    "stream":True,
                    "history_turns":0,
                    "user_prompt":"",
                    "enable_rerank":True,
                    "query":user_prompt,
                    "conversation_history":[]}
            
            async for _ in self._task_with_heartbeat(self.call_rag_api, body=body):
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content
                yield self.response
                
            self.response.search_graph.children[0].processing_type = ProcessingType.DONE
            
            current_answer = [f"提问：{user_prompt}，查询" + region + "医保知识库返回结果:\n" + self.response.content]
            self.response.search_graph = self.append_search_graph(self.response.search_graph, "是否需要网络搜索获取最新信息" if self.language == 'zh-CN' else "Web Search for Latest Information")
            web_search_count = 0
            web_search_schema = get_openai_json_schema_v3(WebSearchSchema)
            web_tool_choice = {"type": "function", "function": {"name": web_search_schema[0]['function']['name']}}
            web_arguments = await function_call_with_retry(self.llm, tools=web_search_schema, tool_choice=web_tool_choice, user_prompt=web_search_prompt.format(user_prompt=user_prompt, current_answer='\n\n'.join(current_answer), current_date=datetime.now().strftime('%Y-%m-%d')), temperature=0.3)
            self.response.search_graph.children[1].thought_process =  f"是否需要网络搜索: {web_arguments.get('needs_web_search', False)}\n" if self.language == 'zh-CN' else f"Needs Web Search: {web_arguments.get('needs_web_search', False)}\n"
            self.response.search_graph.children[1].processing_type = ProcessingType.DONE
            if web_arguments.get('needs_web_search', False):
                self.response.search_graph = self.append_search_graph(self.response.search_graph, "通过网络搜索获取最新信息" if self.language == 'zh-CN' else "Web Search for Latest Information")
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content
                agent, agent_name = MindSearchMedicalHitlAgent, "mindsearchofficialsite"
                agent = agent()
                step_body = {
                    "user_prompt": web_search_content_prompt.format(search_content=self.response.content, user_prompt=user_prompt, current_date=datetime.now().strftime('%Y-%m-%d')),
                    "history_messages": [],
                    "agent": agent_name,
                    "skip_followup": True,
                    "params":{
                        "language": self.language,
                        "model": "",
                        "enable_rag": True,
                        "is_hitl": True,
                        }
                }
                generator = agent.start_wo_dump(**step_body)
                final_content = ''
                async for chunk in generator:
                    if type(chunk) == dict:
                        search_graph = chunk.get('search_graph', {}) or {}
                        graph_children = search_graph.get('children', []) or []
                        content = "\n-------\n".join(child.get('query', '') for child in graph_children) or ''
                        final_content = chunk.get('content', '') or ''
                        if final_content:
                            content = content + "\n-------\n" + final_content
                        self.response.search_graph.children[2].thought_process = content
                        _content = self.response.content
                        self.response.content = ''
                        yield self.response
                        self.response.content = _content
                        yield self.response
                self.response.search_graph.children[2].summary = "DONE"
                self.response.search_graph.children[2].processing_type = ProcessingType.DONE
                yield self.response
                current_answer.append(f"提问：{user_prompt}\n , 网络搜索返回结构化结果:\n" + self.response.search_graph.children[2].thought_process)
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content
                yield self.response
                web_search_count += 1
            further_search_count = 0
            while not self.error and further_search_count < 1:
                
                self.response.search_graph = self.append_search_graph(self.response.search_graph, "判断是否需要额外查询" if self.language == 'zh-CN' else "Decide if further search is needed")
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content

                further_search_schema = get_openai_json_schema_v3(FurtherSearchSchema)
                further_tool_choice = {"type": "function", "function": {"name": further_search_schema[0]['function']['name']}}
                further_arguments = await function_call_with_retry(self.llm, tools=further_search_schema, tool_choice=further_tool_choice, 
                                                                   user_prompt=further_search_prompt.format(user_prompt=user_prompt, 
                                                                                                            current_answer='\n\n'.join(current_answer), 
                                                                                                            current_date=datetime.now().strftime('%Y-%m-%d')))
                if not further_arguments.get('needs_further_search', False):
                    further_arguments = {'needs_further_search': False}
                self.response.search_graph.children[-1].summary = "DONE"
                self.response.search_graph.children[-1].thought_process = "\n".join(f"{''.join(k.capitalize() for k in key.split('_'))}: {further_arguments[key].capitalize() if type(further_arguments[key]) == str else further_arguments[key]}" for key in further_arguments)
                self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content
                
                if further_arguments.get('needs_further_search', False):
                    self.response.search_graph.children[0].thought_process += '\n' + self.response.content
                    question = further_arguments.get('question', '')
                    region = further_arguments.get('region', '国家')
                    body['workspace'] = region_mapping.get(region, "gj") if region else "gj"
                    body['query'] = question
                    self.response.search_graph = self.append_search_graph(self.response.search_graph, "查询知识库" if self.language == 'zh-CN' else "Knowledge Base Query")
                    yield self.response
                    _content = self.response.content
                    self.response.content = ''
                    async for _ in self._task_with_heartbeat(self.call_rag_api, body=body, hide=True):
                        yield self.response
                    self.response.content = _content
                    current_answer.append(f"提问：{question}，查询" + region + "医保知识库返回结果:\n" + self.buffer)
                    self.response.search_graph.children[-1].summary = "DONE"
                    self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
                    yield self.response
                    further_search_count += 1
                else:
                    break
            if further_search_count > 0 or web_search_count > 0:
                self.response.search_graph = self.append_search_graph(self.response.search_graph, "最终答案生成" if self.language == 'zh-CN' else "Final answer generation")
                async for _ in self._task_with_heartbeat(self.summarize, user_prompt=user_prompt, current_answer=current_answer):
                    _content = self.response.content
                    self.response.content = ''
                    yield self.response
                    self.response.content = _content
                    yield self.response
            else:
                pass
            self.response.search_graph.children[-1].summary = "最终答案生成完成" if self.language == 'zh-CN' else "Final answer generation completed"
            self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
            yield self.response
            
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.summary = "DONE"
            
            _content = self.response.content
            self.response.content = ''
            yield self.response
            self.response.content = _content
            yield self.response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
    
    def init_search_graph(self):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Agentic insurance policy query",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        root.thought_process = "智能医保查询即将执行" if self.language == 'zh-CN' else "Agentic Query will commence shortly"
        
        steps = ["Knowledge Base Query"]
        steps_chinese = ["查询知识库"]

        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            
            node = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="",
                    processing_type=ProcessingType.THINKING)
            root.add_child(node)
        
        return root
    
    def append_search_graph(self, root: SearchNode, subtitle: str) -> SearchNode:
        child = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="",
                    processing_type=ProcessingType.THINKING)
        root.children.append(child)
        return root
    
    async def call_rag_api(self, body, hide=False):
        headers = {'Content-Type': 'application/json'}
        buffer = ""
        stream = body.get("stream", True)
        try:
            prev_thought_process = self.response.search_graph.children[-1].thought_process
            if stream:
                async with httpx.AsyncClient() as client:
                    async with client.stream('POST', self.policy_rag_url, data=json.dumps(body), headers=headers, timeout=900) as r:
                        async for line in r.aiter_lines():
                            if line.strip():  # Skip empty lines
                                try:
                                    # Parse each line as JSON (NDJSON format)
                                    json_data = json.loads(line)
                                    # Extract text content from the JSON response
                                    if 'response' in json_data:
                                        buffer += json_data['response']
                                    elif 'content' in json_data:
                                        buffer += json_data['content']
                                    elif 'text' in json_data:
                                        buffer += json_data['text']
                                    else:
                                        # If the entire response is the text content
                                        buffer += str(json_data)
                                    if not hide:
                                        self.response.content = buffer
                                    else:
                                        self.response.search_graph.children[-1].thought_process = prev_thought_process + '\n' + buffer
                                    self.buffer = buffer
                                except json.JSONDecodeError:
                                    # If it's not JSON, treat as plain text
                                    print("error line", line, type(line))
                                    buffer += line
                                    self.response.content = buffer
            else:
                with httpx.Client() as client:
                    r = client.post(self.policy_rag_url, data=json.dumps(body), headers=headers, timeout=900)
                    if r.status_code == 200:
                        json_data = r.json()
                        if 'response' in json_data:
                            buffer += json_data['response']
                        elif 'content' in json_data:
                            buffer += json_data['content']
                        elif 'text' in json_data:
                            buffer += json_data['text']
                        else:
                            # If the entire response is the text content
                            buffer += str(json_data)
                        self.response.content = buffer
                    else:
                        self.response.content += f"\n调用RAG接口失败，状态码: {r.status_code}, 响应内容: {r.text}"
                        self.error = True
        except Exception as e:
            logger.error(f"调用RAG接口异常: {str(e)}")
            self.response.content += f"\n调用RAG接口异常: {str(e)}"
            self.error = True
            
    async def summarize(self, user_prompt: str, current_answer: List[str]):
        summary_gen = self.llm.stream_call(user_prompt=summary_prompt.format(user_prompt=user_prompt, current_answer='\n\n'.join(current_answer)), temperature=0.3)
        buffer = ''
        async for chunk in summary_gen:
            buffer += chunk
            self.response.content = buffer
        self.buffer = buffer
    
    async def _task_with_heartbeat(self, func: Callable, buffer: io.StringIO = None, interval: float = 0.3, **kwargs):
        r"""
        Since fetch web page contents may cost very long time. Send heartbeat at the same time to avoid connection close.
        """
        try:
            start_time = time.time()
            async def write_buffer():
                f = func(**kwargs)
                if asyncio.iscoroutine(f):
                    await f
                    return
                async for item in f:
                    if not buffer or not item:
                        continue
                    buffer.write(item)
            task = asyncio.create_task(write_buffer())
            shielded = asyncio.shield(task)

            while not task.done():
                yield None
                await asyncio.sleep(interval)
            
            await shielded
            end_time = time.time()
            logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
            yield None
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Task {func.__name__} with heartbeat failed: {str(e)}")