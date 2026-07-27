from datetime import datetime
import json
import asyncio
import io
import logging
import time
import traceback
import httpx
from typing import Callable, List

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from llm.composite_models import DeepseekChatModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from agent.policy.schema import DrugFurtherSearchSchema, DrugPolicyRegionSchema
from agent.policy.prompt import drug_region_selection_prompt, summary_prompt , drug_further_search_prompt
from utils.core.exception import UnexpectedException
from config import settings

logger = logging.getLogger(__name__)


class DrugPolicyAgent(AgentPreset):
    llm: BaseLLM = DeepseekChatModels()
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    language: str = "zh-CN"
    error: bool = False
    response: MindSearchResponse = None
    drug_policy_rag_url: str = ""
    output_dir: str = ""
    buffer: str = ""
    buffer1: str = ""
    buffer2: str = ""

    def __init__(self, query_params={}, **kwargs):
        super().__init__()
        self.drug_policy_rag_url = f"{settings.DRUG_PGRAG_HOST}/query/stream"
        self.output_dir = f"outputs/drug_policy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    async def use_tool(self, user_prompt: str = "", **kwargs):
        try:
            print(f"DrugPolicyAgent received user prompt: {user_prompt}")
            self.response = self.mindsearch_helper.init_response(self)
            yield self.response
            self.response.search_graph = self.init_search_graph()
            self.response.processing_type = ProcessingType.PROCESSING
            yield self.response

            drug_region_schema = get_openai_json_schema_v3(DrugPolicyRegionSchema)
            drug_region_tool_choice = {"type": "function", "function": {"name": drug_region_schema[0]['function']['name']}}
            drug_region_arguments = await function_call_with_retry(self.llm, tools=drug_region_schema, tool_choice=drug_region_tool_choice, user_prompt=drug_region_selection_prompt.format(user_prompt=user_prompt), temperature=0.3)
            drug_region = drug_region_arguments.get('drug_region', '')

            print(f"DrugPolicyAgent selected region: {drug_region}")

            self.response.search_graph.children[0].thought_process += f"调用地区知识库: {drug_region}\n"
            # self.response.search_graph.children[0].summary = "DONE"
            
            yield self.response
            
            workspace_mapping = {
                "中国":['cn1','cn2'],
                "非中国":['global1','global2']
                }
            if drug_region not in workspace_mapping:
                raise UnexpectedException(f"不支持的地区: {drug_region}，请使用 中国 或 非中国 进行查询。")
            
            # drug_policy_rag_url = "http://localhost:19621/query/stream"
            body1 = {"mode":"mix",
                    "workspace": workspace_mapping.get(drug_region)[0],
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
            
            body2 = {"mode":"mix",
                    "workspace": workspace_mapping.get(drug_region)[1],
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
            
            print(f"DrugPolicyAgent body1: {body1}")
            print(f"DrugPolicyAgent body2: {body2}")
            async for response in self.parallel_rag_query(body1, body2):
                yield response
                
            self.response.search_graph.children[0].processing_type = ProcessingType.DONE
            
            current_answer = [f"提问：{user_prompt}，查询" + drug_region + "药物政策知识库返回结果:\n" + self.response.content]

            further_search_count = 0
            while not self.error and further_search_count < 1:
                
                self.response.search_graph = self.append_search_graph(self.response.search_graph, "判断是否需要额外查询" if self.language == 'zh-CN' else "Decide if further search is needed")
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content

                drug_further_search_schema = get_openai_json_schema_v3(DrugFurtherSearchSchema)
                drug_further_tool_choice = {"type": "function", "function": {"name": drug_further_search_schema[0]['function']['name']}}
                drug_further_arguments = await function_call_with_retry(self.llm, tools=drug_further_search_schema, tool_choice=drug_further_tool_choice, user_prompt=drug_further_search_prompt.format(user_prompt=user_prompt, current_answer='\n\n'.join(current_answer), current_date=datetime.now().strftime('%Y-%m-%d')), temperature=0.3)

                if not drug_further_arguments.get('needs_further_search', False):
                    drug_further_arguments = {'needs_further_search': False}
                self.response.search_graph.children[-1].summary = "DONE"
                self.response.search_graph.children[-1].thought_process = "\n".join(f"{''.join(k.capitalize() for k in key.split('_'))}: {drug_further_arguments[key].capitalize() if type(drug_further_arguments[key]) == str else drug_further_arguments[key]}" for key in drug_further_arguments)
                self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
                _content = self.response.content
                self.response.content = ''
                yield self.response
                self.response.content = _content
                
                if drug_further_arguments.get('needs_further_search', False):
                    self.response.search_graph.children[0].thought_process += '\n' + self.response.content
                    question = drug_further_arguments.get('question', '')
                    drug_region = drug_further_arguments.get('drug_region', '中国')
                    body1['workspace'] = workspace_mapping.get(drug_region)[0]
                    body1['query'] = question
                    body2['workspace'] = workspace_mapping.get(drug_region)[1]
                    body2['query'] = question
                    self.response.search_graph = self.append_search_graph(self.response.search_graph, "查询知识库" if self.language == 'zh-CN' else "Knowledge Base Query")
                    yield self.response
                    _content = self.response.content
                    self.response.content = ''
                    async for response in self.parallel_rag_query(body1, body2):
                        yield response
                    self.response.content = _content
                    current_answer.append(f"提问：{question}，查询" + drug_region + "药物政策知识库返回结果:\n" + self.buffer)
                    self.response.search_graph.children[-1].summary = "DONE"
                    self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
                    yield self.response
                    further_search_count += 1
                else:
                    break
            if further_search_count > 0:
                self.response.search_graph = self.append_search_graph(self.response.search_graph, "最终答案生成" if self.language == 'zh-CN' else "Final answer generation")
                async for _ in self._task_with_heartbeat(self.summarize, user_prompt=user_prompt, current_answer=current_answer):
                    _content = self.response.content
                    self.response.content = ''
                    yield self.response
                    self.response.content = _content
                    yield self.response
            else:
                pass
            self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
            yield self.response
            self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
            yield self.response
            
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.summary = "DONE"
            
            _content = self.response.content
            self.response.content = ''
            yield self.response
            self.response.content = _content
            logger.info(f"DrugPolicyAgent final content: {self.response.content}")
            print(f"11111111最终结果{self.response.content}")
            yield self.response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
    
    def init_search_graph(self):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="Agentic drug policy query",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        root.thought_process = "智能药物政策查询即将执行" if self.language == 'zh-CN' else "Agentic Query will commence shortly"
        
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
    # 在 use_tool 方法中替换串行查询部分

    # 修改 1: 添加并行查询的辅助方法
    async def call_rag_api_with_buffer(self, body, buffer_key, hide=False):
        """
        调用 RAG API 并将结果存储到独立的 buffer 中
        """
        headers = {'Content-Type': 'application/json'}
        buffer = ""
        stream = body.get("stream", True)
        
        try:
            prev_thought_process = self.response.search_graph.children[-1].thought_process
            if stream:
                async with httpx.AsyncClient() as client:
                    async with client.stream('POST', self.drug_policy_rag_url, data=json.dumps(body), headers=headers, timeout=900) as r:
                        async for line in r.aiter_lines():
                            if line.strip():
                                try:
                                    json_data = json.loads(line)
                                    
                                    # 提取内容
                                    if 'response' in json_data:
                                        buffer += json_data['response']
                                    elif 'content' in json_data:
                                        buffer += json_data['content']
                                    elif 'text' in json_data:
                                        buffer += json_data['text']
                                    else:
                                        buffer += str(json_data)
                                    
                                    # 存储到独立的 buffer
                                    setattr(self, buffer_key, buffer)
                                    
                                except json.JSONDecodeError:
                                    print(f"Error parsing line [{buffer_key}]:", line)
                                    buffer += line
                                    setattr(self, buffer_key, buffer)
            else:
                with httpx.Client() as client:
                    r = client.post(self.drug_policy_rag_url, data=json.dumps(body), headers=headers, timeout=900)
                    if r.status_code == 200:
                        json_data = r.json()
                        if 'response' in json_data:
                            buffer += json_data['response']
                        elif 'content' in json_data:
                            buffer += json_data['content']
                        elif 'text' in json_data:
                            buffer += json_data['text']
                        else:
                            buffer += str(json_data)
                        setattr(self, buffer_key, buffer)
                    else:
                        error_msg = f"\n调用RAG接口失败，状态码: {r.status_code}, 响应内容: {r.text}"
                        setattr(self, buffer_key, error_msg)
                        self.error = True
        except Exception as e:
            logger.error(f"调用RAG接口异常 [{buffer_key}]: {str(e)}")
            error_msg = f"\n调用RAG接口异常: {str(e)}"
            setattr(self, buffer_key, error_msg)
            self.error = True
        
        return buffer


    # 修改 2: 并行执行两个 RAG 查询的方法
    async def parallel_rag_query(self, body1, body2):
        """
        并行执行两个 RAG 查询，实时合并结果流
        """
        # 初始化两个独立的 buffer
        self.buffer1 = ""
        self.buffer2 = ""
        
        # 创建两个并行任务
        task1 = asyncio.create_task(self.call_rag_api_with_buffer(body1, "buffer1"))
        task2 = asyncio.create_task(self.call_rag_api_with_buffer(body2, "buffer2"))
        
        # 心跳间隔
        interval = 0.3
        
        # 持续监控两个任务，实时合并输出
        while not (task1.done() and task2.done()):
            # 合并两个 buffer 的内容
            combined_content = ""
            
            if self.buffer1:
                combined_content += f"## 知识库 1 结果\n\n{self.buffer1}\n\n"
            
            if self.buffer2:
                combined_content += f"## 知识库 2 结果\n\n{self.buffer2}\n\n"
            
            # 更新 response 并 yield
            if combined_content:
                _content = self.response.content
                self.response.content = combined_content
                yield self.response
                self.response.content = _content
            
            await asyncio.sleep(interval)
        
        # 等待所有任务完成
        await asyncio.gather(task1, task2)
        
        # 最终合并结果
        final_content = ""
        if self.buffer1:
            final_content += f"## 知识库 1 结果\n\n{self.buffer1}\n\n"
        if self.buffer2:
            final_content += f"## 知识库 2 结果\n\n{self.buffer2}\n\n"
        
        # 更新最终内容
        self.response.content = final_content
        self.buffer = final_content
        
        yield self.response
                
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
