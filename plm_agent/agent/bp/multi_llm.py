import re
import json
import pytz
from datetime import datetime
import asyncio
import io
import logging
import time
import traceback
from typing import Any, Callable, List, Type

from agent.core.preset import AgentPreset
from llm.gcp_models import ClaudeSonnet46, Gemini25Pro, Gemini3Flash, Gemini31Pro, ClaudeSonnet45
from llm.azure_models import GPT52, GPT5, GPT54
from llm.deepseek_models import DeepseekChat
from llm.moonshot_models import KimiK2Thinking
from llm.base_model import BaseLLM
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from i18n import translate, resolve_language
from agent.bp.pp import fetch_context, fetch_context_single, get_genai_client
from agent.bp.bp_analysis import bp_extraction_schema
from google.genai import types
from agent.human_in_loop.utils import call_index_api, extract_page_number_from_response
from utils.core.exception import UnexpectedException
from agent.human_in_loop.utils import *
from utils.utils.attachment import AttachmentManager
from utils.sensitive_check.diting import DitingSensitiveChecker
from utils.sensitive_check.llm_moderator import political_topic_filter
from agent.core.exceptions import ModerationFailure
import agent.explore.constants as constants
from agent.bp.evaluate import structure_evaluation_result
from config import settings, api_config
from agent.knowledge.summary import search_and_selection

logger = logging.getLogger(__name__)


class MultiLLMAgent(AgentPreset):
    llm: BaseLLM = Gemini31Pro()
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    response: MindSearchResponse = None
    attachment_manager: AttachmentManager = AttachmentManager()
    sensitive_checker: DitingSensitiveChecker = DitingSensitiveChecker()
    language: str = 'zh-CN'
    model_id: str = 'gemini-3'
    sensitive_check: bool = False

    def format_sensitive_content(self, language: str) -> str:
        return translate("ui.sensitive_response", resolve_language(language))
    
    def __init__(self, query_params={}, **kwargs):
        super().__init__()
        if 'params' in kwargs and 'language' in kwargs['params']:
            from i18n.languages import normalize as _norm
            self.language = _norm(kwargs['params']['language'])
        if 'language' in query_params:
            self.language = _norm(query_params.pop('language', ''))
        if 'model_id' in kwargs.get('params', {}):
            model_id = kwargs['params'].get('model_id')
            self.sensitive_check = True
            self.model_id = model_id
            if model_id in ("gemini-3", "gemini-3.1"):
                self.llm = Gemini31Pro()
            elif model_id == "gpt-5-4":
                self.llm = GPT54()
            elif model_id in ("gpt-5-2", "gpt-5"):
                self.llm = GPT52()
            elif model_id in ("claude-sonnet-4-6", "claude-sonnet-4-5"):
                self.llm = ClaudeSonnet46()
            elif model_id == "deepseek":
                self.llm = DeepseekChat(model=api_config.DEEPSEEK_API_CHAT_MODEL)
            elif model_id == "kimi":
                self.llm = KimiK2Thinking()
            else:
                self.llm = Gemini31Pro()

    async def bp_structurize(self, user_prompt: str):
        try:
            self.response = self.mindsearch_helper.init_response(self)
            
            self.response.search_graph = self.init_search_graph(["结构化评估结果"])
            yield self.response
            self.response.processing_type = ProcessingType.PROCESSING
            
            self.response.search_graph.children[0].thought_process = "正在结构化评估结果...\n"
            yield self.response

            # self.response.content = json.dumps(res, ensure_ascii=False, indent=2)
            res = await structure_evaluation_result(prompt_override=user_prompt)
            
            key_mapping = {
                "team_ai_analysis": "团队-AI分析",
                "team_ai_summary": "团队-AI评估（一句话）",
                "tech_ai_analysis": "技术平台-AI分析",
                "tech_ai_summary": "技术-AI评估（一句话）",
                "pipeline_ai_analysis": "管线情况-AI分析",
                "pipeline_ai_summary": "管线-AI评估（一句话）",
                "financing_ai_analysis": "融资情况-AI分析",
                "financing_ai_summary": "融资情况-AI评估（一句话）",
                "risk_ai_analysis": "风险提示-AI分析",
                "overall_ai_analysis": "综合评估-AI分析",
                "overall_ai_summary": "综合评估-AI评估",
                "followup_ai_advice": "跟进建议-AI评估",
                "followup_ai_summary": "跟进建议-AI评估（一句话）"
            }

            formatted_res = []
            for k, v in res.items():
                display_key = key_mapping.get(k, k)
                formatted_res.append(f"**{display_key}**:\n{v}")
            self.response.content = "\n\n---\n\n".join(formatted_res)
            yield self.response
            self.response.search_graph.children[0].thought_process += "结构化完成。"
            self.response.search_graph.children[0].processing_type = ProcessingType.DONE
            yield self.response
            
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.summary = "DONE"
            yield self.response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))

    async def bp_eval(self, user_prompt: str):
        try:
            self.response = self.mindsearch_helper.init_response(self)
            self.response.search_graph = self.init_search_graph(["生成评估报告"])
            
            yield self.response
            self.response.processing_type = ProcessingType.PROCESSING
            
            self.response.search_graph.children[0].thought_process = "正在生成评估报告...\n"
            yield self.response

            async for chunk in self.llm.stream_call(user_prompt=user_prompt, temperature=0):
                self.response.content += chunk
                yield self.response

            self.response.search_graph.children[0].thought_process += "评估完成。"
            self.response.search_graph.children[0].processing_type = ProcessingType.DONE
            yield self.response
            
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.summary = "DONE"
            yield self.response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
        
    async def use_tool(self, user_prompt: str = "", **kwargs):
        try:
            if kwargs.get('bp_structurize', False):
                async for chunk in self.bp_structurize(user_prompt):
                    yield chunk
                return
            elif kwargs.get('bp_eval', False):
                async for chunk in self.bp_eval(user_prompt):
                    yield chunk
                return
            elif kwargs.get('bp_extract', False):
                files = kwargs.get('files', []) or kwargs.get('params', {}).get('files', [])
                detail_level = kwargs.get('detail_level', 2)
                async for chunk in self.bp_extract(user_prompt, files=files, detail_level=detail_level):
                    yield chunk
                return
            steps = ["调用所选大模型"]
            files = kwargs.get('files', []) or kwargs.get('params', {}).get('files', [])
            params = kwargs.get('params', {})
            history_attachments = params.get('history_files', [])
            parent_id = params.get('parent_id', None)
            user_email = params.get('user', None)
            should_search = False

            if files:
                steps.insert(0, "处理用户上传的附件")
            elif not files and not any(history_attachments) and parent_id:
                steps.insert(0, "选取文档")
                should_search = True
            
            self.response = self.mindsearch_helper.init_response(self)
            yield self.response
            self.response.processing_type = ProcessingType.PROCESSING
            self.response.search_graph = self.init_search_graph(steps)
            yield self.response

            if should_search:
                self.response.search_graph.children[0].thought_process = f"正在根据问题选取文档......"
                yield self.response
                files = await search_and_selection(user_query=user_prompt, parent_id=parent_id if parent_id!='root' else None, user_email=user_email)

                if not files:
                    self.response.search_graph.children[0].thought_process = f"未找到相关文档。"
                    self.response.search_graph.children[0].processing_type = ProcessingType.DONE
                    yield self.response
                    return
                
                self.response.search_graph.children[0].thought_process = f"选取文档完成，共找到 {len(files)} 个相关文档。"
                self.response.search_graph.children[0].processing_type = ProcessingType.DONE
                yield self.response

            if files:
                
                attachments = self.attachment_manager.fetch_attachments(files, False)
                contexts_map = {}

                async def _fetch_attachment_context(att, current_query):
                    url = att.get('url', '')
                    name = att.get('name', "Untitled")
                    attachment_id = str(att.get('id', ''))
                    if not url or not (url.startswith('http://') or url.startswith('https://')):
                        return attachment_id, ""
                    context_text = await fetch_context_single(
                        url, name, attachment_id, query=current_query, detailed=1
                    )
                    return attachment_id, context_text

                results = await asyncio.gather(*[
                    _fetch_attachment_context(att, user_prompt) for att in attachments
                ])
                for attachment_id, context_text in results:
                    contexts_map[attachment_id] = context_text
                
                reflection_llm = Gemini31Pro()
                for i in range(3):
                    self.response.search_graph.children[0].thought_process = f"正在进行第 {i+1} 次内容验证与补充提取...\n"
                    yield self.response
                    
                    combined_current_context = "\n\n".join([f"文档 {k} 的当前提取内容:\n{v}" for k, v in contexts_map.items()])
                    reflection_prompt = f"Original Query: {user_prompt}\n\nCurrent Extracted Information:\n{combined_current_context}\n\nTask:\nBased strictly on the Original Query, is there any missing information that requires further deep diving into the documents?\nIf everything required by the Original Query is already extracted or there is clearly no gap, reply with EXACTLY 'NO_GAP'.\nOtherwise, provide a concise search query that focuses exclusively on the missing information (the gap) to search the document again."
                    
                    gap_analysis = await reflection_llm(user_prompt=reflection_prompt, temperature=0.1)
                    
                    if "NO_GAP" in gap_analysis:
                        self.response.search_graph.children[0].thought_process = f"经过验证，信息提取已充分，无须再次提取。\n"
                        yield self.response
                        break
                        
                    self.response.search_graph.children[0].thought_process = f"发现遗漏信息，正在补充提取...\n"
                    yield self.response
                    
                    new_query = f"Original Query: {user_prompt}\nMissing Information to Search For: {gap_analysis.strip()}"
                    new_results = await asyncio.gather(*[
                        _fetch_attachment_context(att, new_query) for att in attachments
                    ])
                    
                    for attachment_id, additional_text in new_results:
                        if additional_text:
                            contexts_map[attachment_id] += f"\n\n[补充提取 - 轮次 {i+1}]\n" + additional_text
                    
                # chunks_map = call_index_api(attachment_ids=files, query=user_prompt, pages=None)
                chunks_map = {}
                # print(f"通过知识库拿到：{chunks_map}\n\n")
                
                final_context_list = []
                final_knowledge_chunks = []

                for file_id in files:
                    file_id_str = str(file_id)
                    
                    curr_context = contexts_map.get(file_id_str, "")
                    curr_chunks = chunks_map.get(file_id_str, [])

                    filtered_curr_chunks = self.filter_chunks_by_context(curr_context, curr_chunks)
                    
                    if curr_context:
                        final_context_list.append(curr_context)
                    if filtered_curr_chunks:
                        final_knowledge_chunks.extend(filtered_curr_chunks)

                combined_context_str = "\n\n".join(final_context_list)
                
                # print(f"过滤后合并的 knowledge_chunks：{final_knowledge_chunks}\n\n")
                knowledge_chunks_str = json.dumps(final_knowledge_chunks, ensure_ascii=False, indent=2)

                if self.language == 'en-US':
                    attachments_chunk = (
                        "Heres a list of documents, their TOCs and selected relevant content:\n\n" +
                        "<User Provided Attachments>\n" + 
                        combined_context_str + 
                        "\n</User Provided Attachments>\n\n " +
                        "<User Knowledge Base Chunks>" + 
                        knowledge_chunks_str + 
                        "</User Knowledge Base Chunks>\n\n"
                    )
                    footer = f"Provide an answer for the following query based on the relevant content from the documents.\n\n"
                    user_prompt = attachments_chunk + footer + '<Question>' + user_prompt + '\n</Question>\nPlease answer in English.'
                else:
                    attachments_chunk = (
                        "以下是文档列表、其目录以及选取的相关内容：\n\n" +
                        "<用户附件>\n" + 
                        combined_context_str + 
                        "\n</用户附件>\n\n " +
                        "<用户知识库相关内容>" + 
                        knowledge_chunks_str + 
                        "</用户知识库相关内容>\n"
                    )
                    footer = f"请基于文档中的相关内容，为以下查询提供回答。\n\n"
                    user_prompt = attachments_chunk + footer + '<用户问题>' + user_prompt + '\n</用户问题>\n请用中文回答。' 
                
                self.response.search_graph.children[0].thought_process += f"处理附件......"
                self.response.search_graph.children[0].processing_type = ProcessingType.DONE
                self.response.search_graph.children[0].thought_process += f"完毕。"
                yield self.response   
            else:
                user_prompt = user_prompt + ("\n\nPlease respond in English." if self.language == 'en-US' else "\n\n请用中文回答。")

            # yield self.response
            self.response.search_graph.children[-1].thought_process += f"生成回答中......"
            self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
            yield self.response        

            async for _ in self._task_with_heartbeat(self.summarize, interval=0.3, user_prompt=user_prompt):
                yield self.response            
                
            self.response.search_graph.children[-1].thought_process += f"完毕。"
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.children[-1].processing_type = ProcessingType.DONE
            self.response.search_graph.summary = "DONE"
            prev_content = self.response.content
            self.response.content = ''
            yield self.response
            self.response.content = prev_content
            yield self.response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))

    async def bp_extract(self, extraction_prompt: str, files: list = [], detail_level=2):
        try:
            self.response = self.mindsearch_helper.init_response(self)
            self.response.search_graph = self.init_search_graph(["提取信息"])
            yield self.response
            self.response.processing_type = ProcessingType.PROCESSING
            
            self.response.search_graph.children[0].thought_process = "正在获取文件内容...\n"
            yield self.response

            if not files:
                 self.response.content = "No files provided."
                 yield self.response
                 return

            attachments = self.attachment_manager.fetch_attachments(files, False)
            
            urls = [att.get('url', '') for att in attachments]
            names = [att.get('name', "Untitled") for att in attachments]
            ids = [str(att.get('id', '')) for att in attachments]
            
            detail_level = detail_level
            
            context = await fetch_context(urls, names, ids, include_toc=True, detailed=detail_level)
            
            if not context:
                 self.response.content = "Failed to fetch context."
                 yield self.response
                 return
            
            # Using the first file
            content, toc = context[0]
            pages = content if isinstance(content, list) else [content]
            full_text = "\n".join(pages) if isinstance(content, list) else pages[0]
            
            self.response.search_graph.children[0].thought_process += "内容获取完成，正在执行提取...\n"
            yield self.response
            
            llm = Gemini31Pro()
            
            if "{markdown_text}" in extraction_prompt:
                final_prompt = extraction_prompt.replace("{markdown_text}", full_text)
            else:
                final_prompt = f"{extraction_prompt}\n\n## BP文本内容：\n\n{full_text}"
            
            response_text = await llm(
                user_prompt=final_prompt,
                temperature=0,
                thinking_budget="low",
                response_mime_type="application/json",
                response_schema=bp_extraction_schema
            )
            
            json_content = json.loads(response_text)
            
            key_mapping = {
                "company_name": "公司名称",
                "company_intro": "公司简介",
                "team_info": "团队情况",
                "tech_platform": "技术平台",
                "pipeline_info": "管线情况",
                "financing_info": "融资情况"
            }

            formatted_res = []
            for k, v in json_content.items():
                display_key = key_mapping.get(k, k)
                formatted_res.append(f"**{display_key}**:\n{v}")
            self.response.content = "\n\n---\n\n".join(formatted_res)
            
            self.response.search_graph.children[0].thought_process += "提取完成。"
            self.response.search_graph.children[0].processing_type = ProcessingType.DONE
            yield self.response
            
            self.response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            self.response.search_graph.summary = "DONE"
            yield self.response

        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
    
    def init_search_graph(self, steps = ["调用所选大模型"]):
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="LLM API",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        root.thought_process = "LLM API call will commence shortly"
        
        for subtitle in steps:
            
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
    
            
    async def summarize(self, user_prompt: str):
        extra_params = {}
        if 'gemini' in self.model_id:
            extra_params['thinking_budget'] = 'low'

        # Input moderation: simple check first, then topic filter if simple check passes
        if self.sensitive_check:
            input_is_sensitive = not (await self.sensitive_checker.simple_check(user_prompt, chunk_size=150, only_politics=True, min_ratio=0.2))
            logger.info(f"[summarize] Input simple check sensitive: {input_is_sensitive}")
            if not input_is_sensitive:
                context = f"<user_question>{user_prompt}</user_question>"
                input_is_sensitive = await political_topic_filter(context)
                logger.info(f"[summarize] Input topic filter sensitive: {input_is_sensitive}")
            if input_is_sensitive:
                logger.warning("[summarize] User prompt contains sensitive content, blocking.")
                self.response.content = self.format_sensitive_content(self.language)
                return

        if self.language == 'en-US':
            user_prompt = "Current date: " + time.strftime("%Y-%m-%d") + "\n\n" + user_prompt
        elif self.language == 'zh-CN':
            user_prompt = "当前日期: " + time.strftime("%Y-%m-%d") + "\n\n" + user_prompt
            
        summary_gen = self.llm.stream_call(user_prompt=user_prompt, temperature=0, **extra_params)
        buffer = ''
        async for chunk in summary_gen:
            buffer += chunk
            self.response.content = buffer
    
    async def _task_with_heartbeat(self, func: Callable, buffer: io.StringIO = None, interval: float = 0.6, **kwargs):
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

    def filter_chunks_by_context(self, context: str, chunks: list[str]) -> list[str]:
        filtered_chunks = []
        for chunk in chunks:
            if chunk.startswith("Content from page "):
                end_index = chunk.find("\n")
                page_info = chunk[:end_index] if end_index != -1 else chunk
                if page_info in context:
                    continue
            filtered_chunks.append(chunk)
        return filtered_chunks

