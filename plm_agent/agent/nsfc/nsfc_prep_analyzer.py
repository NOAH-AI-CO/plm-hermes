from __future__ import annotations
from abc import ABC
from typing import List, Dict, Any, Optional, Tuple
import re
import json
import io
import os
from collections import Counter, defaultdict
from datetime import datetime
import logging
import numpy as np
from typing import AsyncIterator
from pydantic import BaseModel, ConfigDict
from llm.base_model import BaseLLM
from llm.composite_models import SlotFillingModels
from llm.azure_models import GPT4o  # 用于JSON生成任务
from lite_llm.azure_openai import AzureOpenAI52
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from agent.nsfc.nsfc_query_database import vector_search_pubmed, keyword_search_nsfc, rank_pubmed_records_with_if, search_pubmed_by_keywords
from agent.nsfc.schema import UserInputTranslationSchema, UserInputKeywordExtractionSchema, UserInputKeywordTranslationSchema
from agent.nsfc import prompts
from agent.nsfc.citation import parse_citation_numbers, _extract_citation_order, _renumber_text_with_map, _reorder_literature
from utils.scholar.citation_formatter_v2 import vancouver_format_one, vancouver_format_list, bibtex_export, ris_export, csljson_export
from i18n.languages import normalize as _norm

logger = logging.getLogger(__name__)


# 国自然「写作大纲」JSON 生成
class ProposalOutlineNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None
    level: int | None
    bullets: list[str] | None
    children: list[ProposalOutlineNode] | None


class ProposalOutline(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outline: list[ProposalOutlineNode]


async def llm_call_for_nsfc_proposal_outline(prompt: str, temperature: float) -> List[Dict[str, Any]]:
    """
    输入：制作大纲的提示词
    输出：json 格式的大纲
    """
    # 测试，使用 openrouter 代替 lite_llm，因为 lite_llm 我这里连不上，昨天一下午都耗在这里了
    """
    from  agent.ppt.llm import LLMReq, async_chat
    model = 'openai/gpt-5.2'
    # model = 'google/gemini-3.1-pro-preview'
    req = LLMReq(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "outline",
                "schema": ProposalOutline.model_json_schema(),
                "strict": True,
            },
        },
        reasoning_effort="medium",
    )
    result = await async_chat(req)
    x = json.loads(result.choices[0].message.content)
    logger.info(f"llm_call_for_nsfc_proposal_outline result {result.choices[0].message.content}")
    return x['outline']
    """
    llm = AzureOpenAI52()
    parsed = await llm.structured_output(
        input=[{"role": "user", "content": prompt}],
        schema=ProposalOutline,
        temperature=temperature,
    )
    return [node.model_dump() for node in parsed.outline]
    

class NSFCPrepAnalyzer(ABC):
    slot_filling_llm: BaseLLM = SlotFillingModels(max_retries=0, timeout=15, first_chunk_timeout=10)

    def __init__(self, model, query_params={}, **kwargs):
        """Initialize NSFC prep analyzer with LLM model"""
        # 基础配置
        self.model = model
        self.json_model = kwargs.get('json_model', model)
        self.query_params = query_params.copy()
        self.original_params = query_params.copy()
        self.language = _norm(kwargs.get('language', ''))  # NSFC默认中文
        self.output_dir = './outputs'
        
        self.nsfc_insights = ""
        self.pubmed_insights = ""  # PubMed整体研究格局
        
        self.nsfc_overview_insights = ""  
        self.nsfc_mechanism_insights = ""  
        self.nsfc_gap_insights = ""  
        self.pubmed_overview_insights = ""  
        self.pubmed_mechanism_insights = "" 
        self.pubmed_vs_nsfc_insights = "" 
        
        self.nsfc_project_blueprints = []
        self.nsfc_selected_blueprint = {}
        self.nsfc_proposal_outline = []
        
        self.nsfc_rationale_sections = {}  
        self.nsfc_rationale_full = ""  
        self.nsfc_references = []  
        self.nsfc_research_foundation = ""  
        self.nsfc_work_conditions = ""
        self.qita_shuoming_parts = ""
        self.lixiang_yiju_other_parts = ""
        
        self.summarized_docs = []  # 用户文档的简要摘要
        
        self.chinese_user_input = False  

    def set_output_dir(self, output_dir: str):
        """Set output directory for NSFC results"""
        self.output_dir = output_dir

    async def slot_filling(self, schema, prompt):
        schema_format = get_openai_json_schema_v3(schema)
        function_name = schema_format[0]['function']['name']
        response = await self.slot_filling_llm(user_prompt=prompt, tools=schema_format, tool_choice={"type": "function", "function": {"name": function_name}}, temperature=0, max_tokens=8192)
        
        if hasattr(response, 'tool_calls') and response.tool_calls:
            args_str = response.tool_calls[0].function.arguments
            return json.loads(args_str)
        elif hasattr(response, 'function_call') and response.function_call:
            args_str = response.function_call.arguments
            return json.loads(args_str)
        else:
            logger.warning(f"无法从response中提取function call参数: response类型={type(response)}, tool_calls={getattr(response, 'tool_calls', None)}, function_call={getattr(response, 'function_call', None)}")
            return {}

    def is_chinese(self, text):
        """Check if text is predominantly Chinese"""
        if not text:
            return False
        # Check for Chinese character ranges
        chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u2f00-\u2fdf\u3000-\u303f\u31c0-\u31ef\u3200-\u32ff\u3300-\u33ff\ufe30-\ufe4f\ufe10-\ufe1f\uf900-\ufaff]')
        chinese_chars = len(chinese_pattern.findall(text))
        # If more than 15% of characters are Chinese, consider it Chinese
        print(f"Chinese characters found: {chinese_chars}, Total characters: {len(text)}")
        return chinese_chars / len(text) > 0.15

    async def translate_user_input(self):
        """Translate user input to English and Chinese"""

        if self.is_chinese(self.query_params['user_input']):
            self.chinese_user_input = True
            self.query_params['user_input_cn'] = self.query_params['user_input']
            tool_filling_msg_json = await self.slot_filling(
                schema=UserInputTranslationSchema, 
                prompt=f"Please translate {self.query_params['user_input']} into professional English\n")
            translated_text = tool_filling_msg_json.get('translated_text', '')
            self.query_params['user_input_en'] = translated_text if translated_text else self.query_params['user_input']
        else:
            self.chinese_user_input = False
            self.query_params['user_input_en'] = self.query_params['user_input']
            tool_filling_msg_json = await self.slot_filling( 
                schema=UserInputTranslationSchema, 
                prompt=f"请将{self.query_params['user_input']}翻译为专业的中文\n")
            translated_text = tool_filling_msg_json.get('translated_text', '')
            self.query_params['user_input_cn'] = translated_text if translated_text else self.query_params['user_input']

    async def extract_and_expand_keywords(self):
        """Extract & expand keywords from user input for NSFC project search (Chinese)"""
        user_input = self.query_params['user_input_cn']

        tool_filling_msg_json = await self.slot_filling(
            schema=UserInputKeywordExtractionSchema,
            prompt=(
                "请从以下中文文本中提取用于科研项目检索的关键词（名词/名词短语），并区分：\n"
                "1）keywords：表示研究主题/对象/疾病/指标等的检索关键词，按相关度由高到低返回3-12个；\n"
                "2）core_keywords：能显著限定研究方向/方法/人群/学科领域的核心关键词，"
                "   如果去掉这些词，检索结果会严重跑偏（如：中医/中医治疗、护理、老年人、儿童、随机对照试验等）。\n"
                "仅返回 JSON 字段。\n\n"
                f"{user_input}"
            ),
        )

        raw_keywords = tool_filling_msg_json.get("keywords") or []
        raw_core = tool_filling_msg_json.get("core_keywords") or []

        if not raw_keywords and isinstance(user_input, str) and user_input.strip():
            raw_keywords = [user_input.strip()]

        seen_kw = set()
        cleaned_keywords: list[str] = []
        for k in raw_keywords:
            if not k:
                continue
            kl = k.lower()
            if kl not in seen_kw:
                seen_kw.add(kl)
                cleaned_keywords.append(k)
        cleaned_keywords = cleaned_keywords[:12]

        seen_core = set()
        cleaned_core: list[str] = []
        for k in raw_core:
            if not k:
                continue
            kl = k.lower()
            if kl not in seen_core:
                seen_core.add(kl)
                cleaned_core.append(k)

        self.query_params["keywords"] = cleaned_keywords
        self.query_params["core_keywords"] = cleaned_core

        seed_keywords_str = "，".join(cleaned_keywords) if cleaned_keywords else user_input
        expanded_keywords: list[str] = []

        if seed_keywords_str.strip():
            expand_kw_json = await self.slot_filling(
                schema=UserInputKeywordExtractionSchema,
                prompt=(
                    "基于以下中文关键词，生成语义相关扩写词（针对研究主题/对象本身），"
                    "包括常见同义词、缩写、近义短语，但避免过宽泛和改变研究方法/领域。"
                    "不要在此处生成中医/护理/老年人等核心限定词。\n"
                    "只在 keywords 字段中返回扩展后的关键词列表，core_keywords 留空或忽略。\n"
                    "按相关度由高到低返回5-20个，仅返回 JSON 字段。\n\n"
                    f"{seed_keywords_str}"
                ),
            )
            expanded_keywords = expand_kw_json.get("keywords") or []

        expanded_core: list[str] = []
        if cleaned_core:
            seed_core_str = "，".join(cleaned_core)
            expand_core_json = await self.slot_filling(
                schema=UserInputKeywordExtractionSchema,
                prompt=(
                    "仅对下列代表研究方法/领域/人群的核心关键词做少量同义扩展，"
                    "例如：'中医治疗' → '中医药治疗','中医药干预' 等。"
                    "不要生成新的疾病名称或过于宽泛的词（如 '肿瘤'、'医学研究'）。\n"
                    "只在 keywords 字段中返回扩展后的核心关键词列表，core_keywords 留空或忽略。\n"
                    "按相关度由高到低返回3-10个，仅返回 JSON 字段。\n\n"
                    f"{seed_core_str}"
                ),
            )
            expanded_core = expand_core_json.get("keywords") or []

        seen_kw2 = set()
        keywords_final: list[str] = []

        for k in cleaned_keywords + expanded_keywords:
            if not k:
                continue
            kl = k.lower()
            if kl not in seen_kw2:
                seen_kw2.add(kl)
                keywords_final.append(k)
        keywords_final = keywords_final[:20]

        seen_core2 = set()
        core_final: list[str] = []
        for k in cleaned_core + expanded_core:
            if not k:
                continue
            kl = k.lower()
            if kl not in seen_core2:
                seen_core2.add(kl)
                core_final.append(k)

        self.query_params["keywords"] = keywords_final
        self.query_params["core_keywords"] = core_final

    async def translate_keywords_to_english(self, keywords_cn: list[str], core_keywords_cn: list[str]) -> tuple[list[str], list[str]]:
        def _normalize_keywords(raw_list: list) -> list[str]:
            cleaned: list[str] = []
            for item in raw_list or []:
                if item is None:
                    continue
                if isinstance(item, dict):
                    # Common shapes: {"keyword": "..."} or {"text": "..."}
                    val = item.get("keyword") or item.get("text") or ""
                    val = str(val).strip()
                    if val:
                        cleaned.append(val)
                else:
                    val = str(item).strip()
                    if val:
                        cleaned.append(val)
            return cleaned

        keywords_cn = _normalize_keywords(keywords_cn)
        core_keywords_cn = _normalize_keywords(core_keywords_cn)

        prompt = (
            "请将以下中文科研关键词翻译为英文专业术语，保持用于文献检索的简洁：\n"
            "1）keywords：疾病/研究对象/指标等\n"
            "2）core_keywords：方法/人群/领域等核心限定词\n"
            "用 JSON 返回 {\"keywords\": [...], \"core_keywords\": [...]}。\n\n"
            f"keywords（中文）：{', '.join(keywords_cn)}\n"
            f"core_keywords（中文）：{', '.join(core_keywords_cn)}\n"
        )

        result = await self.slot_filling(
            schema=UserInputKeywordTranslationSchema,
            prompt=prompt,
        )

        keywords_en = result.get("keywords") or []
        core_keywords_en = result.get("core_keywords") or []

        self.query_params["keywords_en"] = keywords_en
        self.query_params["core_keywords_en"] = core_keywords_en
        return keywords_en, core_keywords_en

    def run_search_pubmed(self,
                          user_input: str,
                          search_years: List[int] = [2020, 2021, 2022, 2023, 2024, 2025],
                          top_k: int = 50) -> List[Dict[str, Any]]:

        logger.info(f" PubMed搜索: {user_input[:100]}...")
        logger.info(f" 年份范围: {search_years}, top_k: {top_k}")
        
        try:
            records = vector_search_pubmed(inputs=[user_input],
                                           search_years=search_years,
                                           top_k=top_k) or []
            
            logger.info(f"初次搜索: {len(records)} 篇文献")
            
            # 如果结果太少，扩大年份范围
            if len(records) < max(5, top_k // 5):
                logger.info(f" 结果较少，扩大年份范围...")
                widen_years = list({*search_years, 2023, 2022})
                widen_years.sort(reverse=True)
                
                more = vector_search_pubmed(inputs=[user_input],
                                            search_years=widen_years,
                                            top_k=top_k) or []
                logger.info(f"扩大搜索: 额外 {len(more)} 篇文献")
                
                seen = set()
                merged = []
                for r in records + more:
                    pmid = str(r.get("pmid") or "")
                    if pmid and pmid not in seen:
                        seen.add(pmid)
                        merged.append(r)
                records = merged
                logger.info(f"合并去重后: {len(records)} 篇文献")

            if not records:
                logger.error("未找到符合条件的 PubMed 文献")
                logger.error(f"查询: {user_input}")
                logger.error(f"年份: {search_years}")
                raise Exception("未找到符合条件的 PubMed 文献")

            self.pubmed_records = records
            logger.info(f"PubMed搜索完成: {len(records)} 篇文献")
            return records
            
        except Exception as e:
            logger.error(f"PubMed搜索失败: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            raise

    async def run_search_pubmed_by_keywords(self, search_years: List[int] = [2020, 2021, 2022, 2023, 2024, 2025], top_k: int = 50) -> List[Dict[str, Any]]:
        core_keywords: List[str] = self.query_params.get("core_keywords", []) or []
        keywords: List[str] = self.query_params.get("keywords", []) or []

        keywords_en, core_keywords_en = await self.translate_keywords_to_english(keywords, core_keywords)

        records = await search_pubmed_by_keywords(core_keywords=core_keywords_en, keywords=keywords_en, years=search_years, top_k=top_k)
        return records

    def run_search_nsfc(self,
                        start_year: Optional[int] = None,
                        end_year: Optional[int] = None,
                        project_types: Optional[List[str]] = None,
                        codes: Optional[List[str]] = None,
                        top_k: int = 20) -> List[Dict[str, Any]]:

        core_keywords: List[str] = self.query_params.get("core_keywords", []) or []
        keywords: List[str] = self.query_params.get("keywords", []) or []

        ordered_keywords: List[str] = []
        seen = set()
        for k in core_keywords + keywords:
            if not k:
                continue
            kl = k.lower()
            if kl not in seen:
                seen.add(kl)
                ordered_keywords.append(k)

        if not ordered_keywords:
            raise Exception("未找到可用于检索的关键词")

        projects = keyword_search_nsfc(
            keywords=ordered_keywords,
            start_year=start_year,
            end_year=end_year,
            project_types=project_types,
            codes=codes,
            top_k=top_k,
        )

        if not projects:
            raise Exception("未找到符合条件的科研项目")

        self.nsfc_projects = projects
        return projects
        

    def _to_llm_pubmed_refs(self, pubmed_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将PubMed记录转换为适合LLM的格式"""
        seen = set()
        out = []
        for r in pubmed_records:
            pmid = str(r.get("pmid") or "")
            if not pmid or pmid in seen:
                continue
            seen.add(pmid)
            out.append({
                "pmid": pmid,
                "title": r.get("title") or "",
                "journal": r.get("journal_abbr") or r.get("journal") or "",
                "year": r.get("year_of_publication") or "",
                "abstract": r.get("abstract") or r.get("summary") or ""
            })
        return out

    def prepare_nsfc_projects_statistics(self, score_threshold: float = 15.0) -> Dict[str, Any]:
        if not hasattr(self, "nsfc_projects") or not self.nsfc_projects:
            raise Exception("请先调用 run_search_nsfc() 检索项目数据")

        projects: List[Dict[str, Any]] = self.nsfc_projects

        related_projects = [p for p in projects if float(p.get("_score", 0) or 0) >= score_threshold]
        related_projects = sorted(related_projects, key=lambda p: float(p.get("_score", 0) or 0), reverse=True)

        summary: Dict[str, Any] = {
            "total_projects": len(projects),
            "related_projects": len(related_projects),
            "related_projects_completed": 0,
            "related_projects_ongoing": 0,
            "related_projects_papers": 0,
            "related_projects_years": {},
            "related_projects_keywords": {},
            "score_threshold": score_threshold,
        }

        kw_counter = Counter()
        year_map = defaultdict(int)

        for p in related_projects:
            start = p.get("researchTimeStart") or ""
            conclusion = p.get("conclusionAbstract") or ""
            results = p.get("resultsList") or []
            keywords = p.get("keywordList") or []

            # 年份统计（取起始年份）
            if start:
                try:
                    year = datetime.strptime(start, "%Y-%m-%d").year
                    year_map[year] += 1
                except Exception:
                    pass

            # 结题 / 在研
            if conclusion.strip():
                summary["related_projects_completed"] += 1
            else:
                summary["related_projects_ongoing"] += 1

            # 论文成果
            summary["related_projects_papers"] += len(results)

            # 关键词
            kw_counter.update(keywords)

        summary["related_projects_keywords"] = dict(sorted(kw_counter.items(), key=lambda x: x[1], reverse=True))
        summary["related_projects_years"] = dict(sorted(year_map.items()))

        return summary

    def prepare_related_nsfc_projects(self, score_threshold: float = 15.0, max_projects_for_llm: int = 30) -> List[Dict[str, Any]]:
        if not hasattr(self, "nsfc_projects") or not self.nsfc_projects:
            raise Exception("请先调用 run_search_nsfc() 和保存 nsfc_projects")

        projects: List[Dict[str, Any]] = self.nsfc_projects
        related_projects = [p for p in projects if float(p.get("_score", 0) or 0) >= score_threshold]
        related_projects = sorted(related_projects, key=lambda p: float(p.get("_score", 0) or 0), reverse=True)

        sample_projects: List[Dict[str, Any]] = []
        for p in related_projects[:max_projects_for_llm]:
            sample_projects.append({
            "projectName": p.get("projectName"),
            "dependUnit": p.get("dependUnit"),
            "researchTimeStart": p.get("researchTimeStart"),
            "researchTimeEnd": p.get("researchTimeEnd"),
            "keywordList": p.get("keywordList") or [],
            "projectAbstractC": p.get("projectAbstractC") or "",
            "conclusionAbstract": p.get("conclusionAbstract") or "",
            "_score": p.get("_score"),
            })

        return sample_projects

    async def generate_nsfc_overview_insights(self, nsfc_statistics, nsfc_sample_projects, last_chunk=None, model=None, temperature: float = 0.2) -> AsyncIterator[Dict[str, Any]]:
        prompt = prompts.NSFC_PROJECTS_OVERVIEW_INSIGHTS_PROMPT.format(
            statistics=nsfc_statistics,
            sample_projects=nsfc_sample_projects,
        )

        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
   
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
                partial_text = string_buffer.getvalue()
                # remove think blocks
                partial_text = self._remove_think_blocks(partial_text)

                base = last_chunk or {}
                payload = {**base, "message": partial_text, "save": False}
                yield payload
        string_buffer.close()


    async def generate_nsfc_mechanism_insights(self, nsfc_statistics, nsfc_sample_projects, last_chunk=None, model=None, temperature: float = 0.2) -> AsyncIterator[Dict[str, Any]]:
        prompt = prompts.NSFC_PROJECTS_MECHANISM_INSIGHTS_PROMPT.format(
            statistics=nsfc_statistics,
            sample_projects=nsfc_sample_projects,
        )

        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
                partial_text = string_buffer.getvalue()
                # remove think blocks
                partial_text = self._remove_think_blocks(partial_text)
                base = last_chunk or {}
                payload = {**base, "message": partial_text, "save": False}  
                yield payload
        string_buffer.close()

    async def generate_nsfc_insights(self, nsfc_statistics, nsfc_sample_projects, previous_overview, previous_mechanism, last_chunk=None, model=None, temperature: float = 0.2) -> AsyncIterator[Dict[str, Any]]:
        prompt = prompts.NSFC_PROJECTS_INSIGHTS_PROMPT.format(
            statistics=nsfc_statistics,
            sample_projects=nsfc_sample_projects,
            previous_overview=previous_overview,
            previous_mechanism=previous_mechanism,
        )

        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
                partial_text = string_buffer.getvalue()
                # remove think blocks
                partial_text = self._remove_think_blocks(partial_text)
                base = last_chunk or {}
                payload = {**base, "message": partial_text, "save": False}  # streaming chunks 都不保存，由 agent 统一保存
                yield payload
        string_buffer.close()


    async def generate_pubmed_overview_insights(self, pubmed_records: List[Dict[str, Any]], last_chunk=None, model=None, temperature: float = 0.2, max_papers_for_llm: int = 50) -> AsyncIterator[Dict[str, Any]]:
        refs = self._to_llm_pubmed_refs(pubmed_records)
        sample_refs = refs[:max_papers_for_llm]

        pubmed_records_json = json.dumps(sample_refs, ensure_ascii=False, indent=2)

        prompt = prompts.PUBMED_RECORDS_OVERVIEW_INSIGHTS_PROMPT.format(
            pubmed_records=pubmed_records_json,
        )

        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
                partial_text = string_buffer.getvalue()
                # remove think blocks
                partial_text = self._remove_think_blocks(partial_text)
                base = last_chunk or {}
                payload = {**base, "message": partial_text, "save": False}
                yield payload
        string_buffer.close()
    
    # 流式输出备选课题方案（强制使用GPT-4o）
    async def stream_generate_nsfc_project_blueprints(self, 
                                                      summarized_docs: List[Dict[str, Any]] = [], 
                                                      num_blueprints: int = 3, 
                                                      last_chunk=None, 
                                                      temperature: float = 0.5, 
                                                      model=GPT4o()):
        
        # 构建提示词
        user_input_cn = self.query_params.get('user_input_cn', '')
        if summarized_docs:
            prompt = prompts.NSFC_PROJECT_BLUEPRINTS_WITH_DOCS_PROMPT.format(
                num_blueprints = num_blueprints,
                user_input_cn = user_input_cn,
                user_doc_summary = summarized_docs,
                nsfc_overview = self.nsfc_insights,
                pubmed_overview = self.pubmed_insights
            )
        else:
            prompt = prompts.NSFC_PROJECT_BLUEPRINTS_NO_DOCS_PROMPT.format(
                num_blueprints = num_blueprints,
                user_input_cn = user_input_cn,
                nsfc_overview = self.nsfc_insights,
                pubmed_overview = self.pubmed_insights
            )
        
        try:
            content_stream = model.stream_call(user_prompt=prompt, temperature=temperature, response_format={"type": "json_object"})
        except Exception as e:
            logger.error(f"蓝图生成API调用失败: {e}")
            self.nsfc_project_blueprints = []
            return

        string_buffer = io.StringIO()
        chunk_count = 0
        total_chars = 0
        
        async for chunk in content_stream:
            chunk_count += 1
            if not chunk:
                logger.debug(f"蓝图生成：收到空 chunk #{chunk_count}")
                continue
            chunk_len = len(chunk)
            total_chars += chunk_len
            logger.debug(f"蓝图生成：收到 chunk #{chunk_count}, 长度={chunk_len}, 累计={total_chars}")
            string_buffer.write(chunk)

        full_response = string_buffer.getvalue()
        string_buffer.close()
        
        if not full_response or not full_response.strip():
            logger.error(f"蓝图生成：LLM返回了空响应")
            if chunk_count > 0:
                logger.error(f"收到 {chunk_count} 个chunks但内容为空 - 可能是content filter或stream处理问题")
            else:
                logger.error(f"没有收到任何chunks - 可能是API超时、限流或prompt太长")
            self.nsfc_project_blueprints = []
            return

        try:
            parsed = json.loads(full_response)
            
            # Handle different response formats
            if isinstance(parsed, list):
                # Perfect - already a list
                logger.info(f"蓝图是标准数组格式，包含{len(parsed)}个元素")
                blueprints = parsed
            elif isinstance(parsed, dict):
                logger.info(f"蓝图是字典格式，尝试提取数组")
                # Try to extract list from common keys
                blueprints = None
                for key in ['blueprints', 'projects', 'items', 'data', 'results']:
                    if key in parsed and isinstance(parsed[key], list):
                        blueprints = parsed[key]
                        logger.info(f"提取项目蓝图从字典字段: {key}")
                        break
                
                # If dict looks like a single blueprint, wrap it in a list
                if blueprints is None and 'title' in parsed:
                    blueprints = [parsed]
                    logger.info("将单个蓝图字典包装为数组")
                
                # Last resort - empty list
                if blueprints is None:
                    logger.error(f"无法从字典中提取蓝图数组。字典keys: {list(parsed.keys())}")
                    logger.error(f"字典内容（前500字符）: {str(parsed)[:500]}")
                    blueprints = []
            else:
                logger.error(f"意外的JSON类型: {type(parsed)}")
                blueprints = []
            
            self.nsfc_project_blueprints = blueprints
            
            return blueprints
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.error(f"完整响应内容（前1000字符）: {full_response[:1000]}")
            
            # Try to fix common format errors
            fixed_response = self._try_fix_json_format(full_response)
            if fixed_response:
                try:
                    parsed = json.loads(fixed_response)
                    if isinstance(parsed, list):
                        self.nsfc_project_blueprints = parsed
                        logger.info(f"成功修复并解析JSON，获得 {len(parsed)} 个蓝图")
                        return
                except:
                    pass
            
            self.nsfc_project_blueprints = []
        except Exception as e:
            logger.error(f"解析项目蓝图失败: {e}")
            logger.error(f"完整响应内容（前1000字符）: {full_response[:1000]}")
            self.nsfc_project_blueprints = []
            return []

    async def generate_nsfc_project_blueprints(self, summarized_docs: List[Dict[str, Any]] = [], num_blueprints: int = 3, temperature: float = 0.5, model=None) -> List[Dict[str, Any]]:
        user_input_cn = self.query_params.get('user_input_cn', '')
        if summarized_docs:
            prompt = prompts.NSFC_PROJECT_BLUEPRINTS_WITH_DOCS_PROMPT.format(
                num_blueprints = num_blueprints,
                user_input_cn = user_input_cn,
                user_doc_summary = summarized_docs,
                nsfc_overview = self.nsfc_insights,
                pubmed_overview = self.pubmed_insights
            )
        else:
            prompt = prompts.NSFC_PROJECT_BLUEPRINTS_NO_DOCS_PROMPT.format(
                num_blueprints = num_blueprints,
                user_input_cn = user_input_cn,
                nsfc_overview = self.nsfc_insights,
                pubmed_overview = self.pubmed_insights
            )
        model = model or self.model
        model_name = getattr(model, "model", "unknown")
        logger.info(f"候选方案生成使用模型: {model.__class__.__name__} / {model_name}")
        if hasattr(model, "stream_call") and not hasattr(model, "generate_stream"):
            content_stream = model.stream_call(
                user_prompt=prompt,
                temperature=temperature
            )
        else:
            content_stream = model.generate_stream(prompt, temperature=temperature)
        buf = io.StringIO()
        async for chunk in content_stream:
            if not chunk:
                continue
            if isinstance(chunk, str):
                buf.write(chunk)
            elif hasattr(chunk, "content"):
                buf.write(chunk.content)

        response_text = buf.getvalue()
        buf.close()

        response_text = self._remove_think_blocks(response_text)
        logger.debug(f"候选方案原始响应（前2000字符）: {response_text[:2000]}")
        try:
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text

            blueprints = json.loads(json_str)
            self.nsfc_project_blueprints = blueprints
            return blueprints

        except Exception as e:
            logger.error(f"解析项目蓝图失败: {e}")
            logger.error(f"解析失败响应（前2000字符）: {response_text[:2000]}")
            return []
        
    #TODO: add user select blueprint method
    def select_blueprint(self, index: int = 0):
        blueprints = getattr(self, "nsfc_project_blueprints", []) or []
        total = len(blueprints)
        if 0 <= index < len(blueprints):
            self.nsfc_selected_blueprint = blueprints[index]
            title = self.nsfc_selected_blueprint.get('title', '')
            msg = ("### 已选定的备选课题方案\n\n"
                   f"当前系统默认选用第 **{index + 1}/{total}** 个方案：**{title}**，作为后续生成写作大纲和内容建议的基础方案。\n\n"
                   "如需更换方案，可在备选课题列表中重新指定。"
                   )
            logger.info(f"已选择备选课题方案（索引 {index}: {title}）")
            return msg
        else:
            logger.error(f"无效的备选课题方案索引: {index}")
            return ""
        
    async def generate_nsfc_proposal_outline(self, model=GPT4o(), last_chunk=None, temperature: float = 0.3) -> AsyncIterator[Dict[str, Any]]:
        
        fund_type = self.query_params.get('fund_type', '面上项目')
        duration_years = self.query_params.get('duration_years', 3)
        
        try:
            nsfc_selected_blueprint = json.dumps(self.nsfc_selected_blueprint, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(
                "序列化 nsfc_selected_blueprint 失败: %s, type=%s, preview=%s",
                e,
                type(self.nsfc_selected_blueprint).__name__,
                str(self.nsfc_selected_blueprint)[:500],
            )
            raise
        
        try:
            prompt = prompts.NSFC_PROPOSAL_OUTLINE_PROMPT.format(
                nsfc_selected_blueprint=nsfc_selected_blueprint,
                nsfc_insights_brief = self.nsfc_insights,
                pubmed_insights_brief = self.pubmed_insights,
                summarized_docs_brief = self.summarized_docs,
                fund_type = fund_type,
                duration_years = duration_years
            )
            logger.info("成功生成写作大纲提示词")
        except Exception as e:
            logger.error(f"生成写作大纲提示词失败: {e}")
            raise
        
        try:
            parsed = await llm_call_for_nsfc_proposal_outline(prompt, temperature)
        except Exception as e:
            logger.error(f"调用LLM生成写作大纲失败: {e}")
            self.nsfc_proposal_outline = []
            return

        if not parsed:
            logger.error("写作大纲 structured 输出为空")
            self.nsfc_proposal_outline = []
            return
        
        def normalize_outline(data):
            # 一级标题（固定）
            REQUIRED_TITLES = [
                "（一）立项依据（为什么要开展此项研究，研究的科学技术价值如何）",
                "（二）研究内容",
                "（三）研究基础",
                "（四）其他需要说明的情况"
            ]

            # 二级标题模板（仅用于缺失时填充）
            SECOND_LEVEL_TITLES = {
                "（三）研究基础": [
                    "1. 研究基础与可行性分析（与本项目相关的研究工作积累和已取得的研究工作成绩，研究风险的应对措施等）；",
                    "2. 工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；",
                    "3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）;",
                    "4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。",
                ],
                "（四）其他需要说明的情况": [
                    "1. 申请人同年申请不同类型的国家自然科学基金项目情况",
                    "2. 具有高级专业技术职务（职称）的申请人是否存在同年申请或者参与申请国家自然科学基金项目的单位不一致的情况",
                    "3. 具有高级专业技术职务（职称）的申请人是否存在与正在承担的国家自然科学基金项目的单位不一致的情况",
                    "4. 同年以不同专业技术职务（职称）申请或参与申请科学基金项目的情况",
                    "5. 申请人在撰写本申请书时使用生成式人工智能的情况",
                    "6. 其他"
                ],
            }

            outlines: dict[str, dict] = {}

            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    t = (item.get("title") or "").strip()
                    if t:
                        outlines[t] = item

            elif isinstance(data, dict):
                first_title = (data.get("title") or "").strip()
                if first_title:
                    outlines[first_title] = data
                for child in data.get("children", []):
                    if not isinstance(child, dict):
                        continue
                    t = (child.get("title") or "").strip()
                    if t:
                        outlines[t] = child
            else:
                return []

            complete_outline: list[dict] = []

            for title in REQUIRED_TITLES:
                if title in outlines:
                    node = outlines[title]
                    # 保留 LLM 生成的详细内容，不要强制覆盖
                    node.setdefault("level", 1)
                else:
                    print(f"自动补齐缺失一级章节：{title}")
                    node = {
                        "title": title,
                        "level": 1,
                        "children": [],
                    }

                # 只有在 LLM 没有生成内容且是固定模板章节时，才使用默认二级标题
                if title in SECOND_LEVEL_TITLES and (not node.get("children") or len(node.get("children", [])) == 0):
                    children = []
                    for sec_title in SECOND_LEVEL_TITLES[title]:
                        children.append({
                            "title": sec_title,
                            "level": 2,
                            "children": [],  # 按 NSFC 要求：这里不允许再扩展
                        })
                    node["children"] = children

                complete_outline.append(node)

            return complete_outline

        final_outline = normalize_outline(parsed)
        self.nsfc_proposal_outline = final_outline
        return final_outline
        
    def _build_lixiang_yiju_section(self) -> list[dict]:
        outline = getattr(self, "nsfc_proposal_outline", []) or []
        if not isinstance(outline, list) or not outline:
            return []

        lixiang_root = None
        for node in outline:
            title = str(node.get("title", "")).replace(" ", "")
            if "立项依据与研究内容" in title:
                lixiang_root = node
                break
        if lixiang_root is None:
            return []
        
        lixiang_node = None
        for child in (lixiang_root.get("children") or []):
            t = str(child.get("title", "")).replace(" ", "")
            if "项目的立项依据" in t:
                lixiang_node = child
                break
        if lixiang_node is None:
            return []

        sections: list[dict] = []

        def collect(node: dict):
            level = int(node.get("level", 0) or 0)
            title = str(node.get("title", "")).strip()
            bullets = node.get("bullets") or []
            children = node.get("children") or []
            
            if level >= 3:
                clean_bullets = [
                    str(b).strip()
                    for b in bullets
                    if str(b).strip()
                ]
                sections.append(
                    {
                        "title": title,
                        "level": level,
                        "bullets": clean_bullets,
                    }
                )

            for ch in children:
                collect(ch)

        children = lixiang_node.get("children") or []

        if children:
            for ch in children:
                collect(ch)
        else:
            bullets = lixiang_node.get("bullets") or []
            clean_bullets = [
                str(b).strip()
                for b in bullets
                if str(b).strip()
            ]
            sections.append(
                {
                    "title": str(lixiang_node.get("title", "")).strip(),
                    "level": int(lixiang_node.get("level", 2) or 2),
                    "bullets": clean_bullets,
                }
            )
        return sections

    def _build_pubmed_queries(self, max_sentences: int = 10) -> List[Dict[str, Any]]:
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}

        # 优先使用用户输入提取的关键词（更相关）
        user_keywords = self.query_params.get("keywords_en", []) or self.query_params.get("keywords", [])
        user_core_keywords = self.query_params.get("core_keywords_en", []) or self.query_params.get("core_keywords", [])

        if user_keywords or user_core_keywords:
            logger.info("使用用户输入提取的关键词构建PubMed查询结构")
            structured_queries: List[Dict[str, Any]] = []

            # 核心关键词组合普通关键词
            if user_core_keywords:
                for core_kw in user_core_keywords[:3]:
                    structured_queries.append({
                        "core_keywords": [core_kw],
                        "keywords": user_keywords[:3],
                        "display": f"{core_kw} + {', '.join(user_keywords[:2])}" if user_keywords else core_kw
                    })

            # 如果数量不足，用普通关键词补充
            if len(structured_queries) < max_sentences and user_keywords:
                for kw in user_keywords[:max_sentences - len(structured_queries)]:
                    structured_queries.append({
                        "core_keywords": [],
                        "keywords": [kw],
                        "display": kw
                    })

            if structured_queries:
                return structured_queries[:max_sentences]

        # 回退到blueprint内容
        if not blueprint:
            return []

        objectives = [str(o).strip() for o in (blueprint.get("objectives") or []) if str(o).strip()]
        contents   = [str(c).strip() for c in (blueprint.get("contents")   or []) if str(c).strip()]
        methods    = [str(m).strip() for m in (blueprint.get("methods")    or []) if str(m).strip()]

        blueprint_items = contents + objectives + methods
        
        structured_queries: List[Dict[str, Any]] = []
        seen_displays = set()
        
        for item in blueprint_items:
            if not item: continue
            # 对于长句子，提取前几个词或作为普通关键词以避免 phrase match 锁定
            display = item[:60] + "..." if len(item) > 60 else item
            if display in seen_displays: continue
            
            # 简单处理：将 blueprint 内容作为 keywords (不带引号)，这样 ES 会做分词匹配
            structured_queries.append({
                "core_keywords": [],
                "keywords": [item],
                "display": display
            })
            seen_displays.add(display)

        logger.info(f"基于blueprint构建了 {len(structured_queries)} 个PubMed查询")
        return structured_queries[:max_sentences]

    async def build_pubmed_pool(self,
                                max_queries: int = 10,
                                max_papers: int = 50,
                                search_years: Optional[List[int]] = None) -> List[Dict[str, Any]]:

        logger.info("=" * 60)
        logger.info("开始构建PubMed文献池 (hybrid_search)")
        logger.info("=" * 60)
        if search_years is None:
            search_years = self.query_params.get("search_years") or [2025, 2024, 2023, 2022, 2021]
            logger.info(f"使用默认检索年份: {search_years}")
        queries = self._build_pubmed_queries(max_sentences=max_queries)
        
        if not queries:
            # 回退到原始用户输入
            user_input = self.query_params.get('user_input_en', '') or self.query_params.get('user_input', '')
            if user_input:
                logger.info(f"使用用户输入作为兜底查询: {user_input[:100]}...")
                queries = [{
                    "core_keywords": [],
                    "keywords": [user_input],
                    "display": user_input[:60]
                }]
            else:
                logger.error("无法构建PubMed查询：缺少blueprint和用户输入")
                return []
        
        logger.info(f"生成了 {len(queries)} 个结构化查询")

        all_records: List[Dict[str, Any]] = []
        seen_pmids: set[str] = set()
        failed_queries: List[str] = []
        
        filtered_count = 0
        for i, q_struct in enumerate(queries, 1):
            display = q_struct.get("display", "unknown")
            logger.info(f"🔍 查询 {i}/{len(queries)}: {display}")
            
            try:
                records = await search_pubmed_by_keywords(
                    core_keywords=q_struct.get("core_keywords"),     
                    keywords=q_struct.get("keywords"),              
                    years=search_years,         
                    size=max_papers,           
                    fusion_method="rrf",
                    bm25_weight=0.3,
                    vector_weight=0.7,
                    min_score_threshold=0.0,
                )
                
                if not records:
                    logger.warning(f"查询无结果: {display}")
                    failed_queries.append(display)
                    continue
                
                added_count = 0
                for rec in records:
                    pmid = rec.get('pmid')
                    if pmid and pmid not in seen_pmids:
                        if self._is_low_value_pubmed_record(rec):
                            filtered_count += 1
                            continue
                        # 字段映射：PubMedSearch._formatter 返回格式 → vancouver_format_one 期待格式
                        mapped_rec = dict(rec)
                        
                        # 1. authors → author (字典列表 → 字符串列表)
                        if 'authors' in mapped_rec and not mapped_rec.get('author'):
                            authors = mapped_rec.get('authors', [])
                            if isinstance(authors, list):
                                mapped_rec['author'] = [a.get('name') if isinstance(a, dict) else str(a) for a in authors]
                        
                        # 2. fulljournalname → journal
                        if 'fulljournalname' in mapped_rec and not mapped_rec.get('journal'):
                            mapped_rec['journal'] = mapped_rec['fulljournalname']
                        
                        # 3. pubdate → journal_pub_date
                        if 'pubdate' in mapped_rec and not mapped_rec.get('journal_pub_date'):
                            mapped_rec['journal_pub_date'] = mapped_rec['pubdate']
                        
                        # 4. summary → abstract
                        if 'summary' in mapped_rec and not mapped_rec.get('abstract'):
                            mapped_rec['abstract'] = mapped_rec['summary']
                        
                        all_records.append(mapped_rec)
                        seen_pmids.add(pmid)
                        added_count += 1
                
                logger.info(f"   找到 {len(records)} 篇文献，新增 {added_count} 篇（去重后）")
                
            except Exception as e:
                logger.error(f"查询失败: {e}")
                import traceback
                logger.debug(traceback.format_exc())
                failed_queries.append(display)
                continue
        
        # 3. 汇总结果
        logger.info("=" * 60)
        logger.info("PubMed文献池构建完成")
        logger.info(f"总计：{len(all_records)} 篇文献（去重后）")
        if filtered_count:
            logger.info(f"已过滤低价值文献：{filtered_count} 篇（勘误/更正/撤稿等）")
        logger.info(f"成功查询：{len(queries) - len(failed_queries)}/{len(queries)}")
        
        if failed_queries:
            logger.warning(f"失败查询：{len(failed_queries)} 个")
            for fq in failed_queries[:3]:
                logger.warning(f"      - {fq[:60]}...")
        
        if not all_records:
            logger.error("=" * 60)
            logger.error("未检索到任何PubMed文献！")
            logger.error("=" * 60)
        
        logger.info("=" * 60)
        
        return all_records

    def _is_low_value_pubmed_record(self, rec: Dict[str, Any]) -> bool:
        """过滤勘误/更正/撤稿类文献，避免参考文献污染。"""
        title = str(rec.get("title") or "").strip().lower()
        if title.startswith("erratum") or title.startswith("correction") or title.startswith("corrigendum"):
            return True
        if "retraction" in title or "expression of concern" in title:
            return True

        pub_types = rec.get("publication_type") or rec.get("publication_types") or rec.get("pub_type")
        if isinstance(pub_types, str):
            pub_types = [pub_types]
        if isinstance(pub_types, list):
            lowered = [str(t).lower() for t in pub_types if t is not None]
            for t in lowered:
                if "erratum" in t or "correction" in t or "corrigendum" in t:
                    return True
                if "retraction" in t or "expression of concern" in t:
                    return True
        return False
        
    
    def build_literature_snippets(self, records: List[Dict[str, Any]], max_items: int = 40, max_abstract_len: int = 220, score_key: str = "_score", alpha: float = 3.0, if_cap: float = 20.0) -> str:
        if not records:
            logger.warning(" 未检索到PubMed文献，将生成提示信息")
            return """当前未检索到可用的 PubMed 文献。"""

        try:
            ranked = rank_pubmed_records_with_if(records, score_key=score_key, alpha=alpha, if_cap=if_cap, max_papers=max_items,)
            logger.info(f"文献排序完成，排序结果: {len(ranked)}")
        except Exception as e:
            logger.error(f"文献排序失败: {e}")
            ranked = records[:max_items]
        
        lines: List[str] = []
        for i, rec in enumerate(ranked[:max_items], start=1):
            # 使用 Vancouver 格式生成标准引用
            try:
                citation = vancouver_format_one(rec)
            except Exception as e:
                # 如果格式化失败，使用简化格式作为后备
                logger.warning(f"Vancouver 格式化失败 (PMID {rec.get('pmid')}): {e}")
                title = str(rec.get("title") or "").strip()
                journal = str(rec.get("journal") or rec.get("journal_abbr") or "").strip()
                year = str(rec.get("year_of_publication") or "").strip()
                citation = f"{title}. {journal}. {year}." if title else "引用信息缺失"

            # 摘要截断
            abstract = (rec.get("abstract") or "").strip()
            if abstract:
                abstract = abstract.replace('\n', ' ').replace('\r', ' ')
                if len(abstract) > max_abstract_len:
                    abstract_snippet = abstract[:max_abstract_len].rstrip("；，。,. ") + "..."
                else:
                    abstract_snippet = abstract
                abs_line = f"    摘要要点：{abstract_snippet}"
            else:
                abs_line = "    摘要要点：无可用摘要（仅供作为参考文献编号使用）"

            header = f"[{i}] {citation}"
            lines.append(header)
            lines.append(abs_line)
            lines.append("")  # 空行分隔

        return "\n".join(lines).strip()
    
    def export_references(self, records: List[Dict[str, Any]], format: str = "bibtex", filename: Optional[str] = None) -> str:  
        if not records:
            logger.warning("没有可导出的参考文献")
            return ""
        
        format_lower = format.lower()
        
        try:
            if format_lower == "bibtex":
                content = bibtex_export(records)
                ext = ".bib"
            elif format_lower == "ris":
                content = ris_export(records)
                ext = ".ris"
            elif format_lower == "csljson":
                content = json.dumps(csljson_export(records), ensure_ascii=False, indent=2)
                ext = ".json"
            elif format_lower == "vancouver":
                refs = vancouver_format_list(records)
                content = "\n".join([f"[{i}] {ref}" for i, ref in enumerate(refs, 1)])
                ext = ".txt"
            else:
                raise ValueError(f"不支持的导出格式: {format}. 支持的格式: bibtex, ris, csljson, vancouver")
            
            if filename:
                if not filename.endswith(ext):
                    filename = filename + ext
                
                os.makedirs(self.output_dir, exist_ok=True)
                filepath = os.path.join(self.output_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                logger.info(f"参考文献已导出到: {filepath}")
            
            return content
            
        except Exception as e:
            logger.error(f"导出参考文献失败 ({format}): {e}")
            raise
    
    
    async def generate_lixiang_yiju_parts(self, literature_snippets, model=None, temperature: float = 0.2) -> str:
        sections = self._build_lixiang_yiju_section()
        if not sections:
            return ""

        sections_json = json.dumps(sections, ensure_ascii=False, indent=2)
        
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}

        prompt = prompts.LIXIANG_YIJU_PROMPT.format(
            title = blueprint.get("title", ""),
            objectives = "\n".join([f"- {str(o).strip()}" for o in (blueprint.get("objectives") or []) if str(o).strip()]),
            contents = "\n".join([f"- {str(c).strip()}" for c in (blueprint.get("contents") or []) if str(c).strip()]),
            methods = "\n".join([f"- {str(m).strip()}" for m in (blueprint.get("methods") or []) if str(m).strip()]),
            nsfc_insights_brief = self.nsfc_insights,
            pubmed_insights_brief = self.pubmed_insights,
            summarized_docs_brief = self.summarized_docs,
            literature_snippets = literature_snippets,
            lixiang_yiju_sections = sections_json,
        )      
        logger.info("- 调用 AI 模型生成立项依据部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)

        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        try:
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', parts)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = parts

            # 清理非法控制字符
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            
            lixiang_yiju_parts = json.loads(json_str)
            if not isinstance(lixiang_yiju_parts, list):
                raise ValueError("LLM 输出不是 JSON 数组")
            
            citation_order: list[int] = []
            for sec in lixiang_yiju_parts:
                content = str(sec.get("content") or "")
                nums = parse_citation_numbers(content)
                for n in nums:
                    if n not in citation_order:
                        citation_order.append(n)
            if not citation_order:
                logger.info("立项依据中未检测到引用编号，不进行重排。")
                parts_with_ref = list(lixiang_yiju_parts)
                
                # 从literature_snippets中去掉"摘要要点"行
                if literature_snippets:
                    clean_refs = self._remove_abstract_points(literature_snippets)
                    parts_with_ref.append({
                        "title": "1.3 参考文献",
                        "level": 3,
                        "content": clean_refs,
                    })
                
                self.lixiang_yiju_parts = parts_with_ref
                return parts_with_ref

            id_map: dict[int, int] = {}
            for new_idx, old_idx in enumerate(citation_order, start=1):
                id_map[old_idx] = new_idx

            def _parse_block(block: str) -> list[int]:
                nums: list[int] = []
                parts = re.split(r'[，,]\s*', block)
                for p in parts:
                    p = p.strip()
                    if not p:
                        continue
                    m = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', p)
                    if m:
                        a, b = int(m.group(1)), int(m.group(2))
                        if a <= b:
                            nums.extend(range(a, b + 1))
                        else:
                            nums.extend(range(b, a + 1))
                    else:
                        if p.isdigit():
                            nums.append(int(p))
                # 去重保序
                seen = set()
                out = []
                for x in nums:
                    if x not in seen:
                        seen.add(x)
                        out.append(x)
                return out

            def _renumber_text(text: str) -> str:
                def repl(m: re.Match) -> str:
                    inner = m.group(1)  # [ ... ] 
                    olds = _parse_block(inner)
                    if not olds:
                        return m.group(0)

                    news = []
                    for o in olds:
                        news.append(id_map.get(o, o))
                    news = sorted(set(news))

                    if not news:
                        return m.group(0)
                    ranges: list[str] = []
                    start = news[0]
                    prev = news[0]
                    for x in news[1:]:
                        if x == prev + 1:
                            prev = x
                        else:
                            if start == prev:
                                ranges.append(str(start))
                            else:
                                ranges.append(f"{start}-{prev}")
                            start = x
                            prev = x
                    # 收尾
                    if start == prev:
                        ranges.append(str(start))
                    else:
                        ranges.append(f"{start}-{prev}")
                    return "[" + ",".join(ranges) + "]"

                return re.sub(r'\[([^\]]+)\]', repl, text)

            reordered_parts: list[dict] = []
            for sec in lixiang_yiju_parts:
                new_sec = dict(sec)
                content = str(sec.get("content") or "")
                new_sec["content"] = _renumber_text(content)
                reordered_parts.append(new_sec)

            def _split_lit(snips: str) -> list[dict]:
                if not snips:
                    return []
                lines = snips.splitlines()
                entries: list[dict] = []
                cur_idx = None
                cur_lines: list[str] = []
                for line in lines:
                    m = re.match(r'^\s*\[(\d+)\]', line)
                    if m:
                        if cur_idx is not None:
                            entries.append({"index": cur_idx, "text": "\n".join(cur_lines).rstrip()})
                        cur_idx = int(m.group(1))
                        cur_lines = [line]
                    else:
                        if cur_idx is not None:
                            cur_lines.append(line)
                if cur_idx is not None:
                    entries.append({"index": cur_idx, "text": "\n".join(cur_lines).rstrip()})
                return entries

            def _reorder_lit(snips: str) -> str:
                entries = _split_lit(snips)
                if not entries:
                    return snips
                # old idx -> entry
                by_old = {e["index"]: e for e in entries}
                
                # 按照citation_order重排序
                ordered_items = []
                for old_idx in citation_order:
                    if old_idx in by_old:
                        ordered_items.append(by_old[old_idx])
                
                out_lines: list[str] = []
                for new_idx, entry in enumerate(ordered_items, 1):
                    old_idx = entry["index"]
                    txt = entry["text"]
                    
                    new_txt = re.sub(r'^\s*\[' + str(old_idx) + r'\]', f"[{new_idx}]", txt, count=1)
                    out_lines.append(new_txt)
                    out_lines.append("")
                
                return "\n".join(out_lines).rstrip()

            # 从literature_snippets中去掉"摘要要点"行并重排序
            new_lit_snippets = _reorder_lit(literature_snippets)
            clean_refs = self._remove_abstract_points(new_lit_snippets)
            
            if clean_refs:
                reordered_parts.append({
                    "title": "1.3 参考文献",
                    "level": 3,
                    "content": clean_refs,
                })
            
            self.lixiang_yiju_parts = reordered_parts
            return reordered_parts

        except Exception as e:
            logger.error(f"解析立项依据 JSON 失败: {e}")
            return []

    async def generate_yanjiu_yiyi(self, literature_snippets, model=None, temperature: float = 0.2) -> str:
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}

        prompt = prompts.YANJIU_YIYI_PROMPT.format(
            title = blueprint.get("title", ""),
            objectives = "\n".join([
                f"- {str(o).strip()}"
                for o in (blueprint.get("objectives") or [])
                if str(o).strip()
            ]),
            contents = "\n".join([
                f"- {str(c).strip()}"
                for c in (blueprint.get("contents") or [])
                if str(c).strip()
            ]),
            methods = "\n".join([
                f"- {str(m).strip()}"
                for m in (blueprint.get("methods") or [])
                if str(m).strip()
            ]),
            literature_snippets = literature_snippets,
        )

        logger.info("调用 AI 生成 1.1 研究意义")
        model = model or self.model
        stream = model.generate_stream(prompt, temperature=temperature)

        buf = io.StringIO()
        async for chunk in stream:
            if chunk:
                buf.write(chunk)
        text = buf.getvalue()
        buf.close()

        text = self._remove_think_blocks(text)
        self.yanjiu_yiyi = text
        return text

    async def generate_yanjiu_xianzhuang(self, literature_snippets, model=None, temperature: float = 0.2) -> str:
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        yanjiu_yiyi = getattr(self, "yanjiu_yiyi", "")

        prompt = prompts.YANJIU_XIANZHUANG_PROMPT.format(
            title = blueprint.get("title", ""),
            objectives = "\n".join([
                f"- {str(o).strip()}"
                for o in (blueprint.get("objectives") or [])
                if str(o).strip()
            ]),
            contents = "\n".join([
                f"- {str(c).strip()}"
                for c in (blueprint.get("contents") or [])
                if str(c).strip()
            ]),
            methods = "\n".join([
                f"- {str(m).strip()}"
                for m in (blueprint.get("methods") or [])
                if str(m).strip()
            ]),
            yanjiu_yiyi = yanjiu_yiyi,    # 让 1.2 与 1.1 逻辑一致
            literature_snippets = literature_snippets or ""   # 用你上面 build_literature_snippets 的结果
        )

        logger.info("调用 AI 生成 1.2 国内外研究现状及发展动态")
        model = model or self.model
        stream = model.generate_stream(prompt, temperature=temperature)

        buf = io.StringIO()
        async for chunk in stream:
            if chunk:
                buf.write(chunk)
        text = buf.getvalue()
        buf.close()

        text = self._remove_think_blocks(text)
        self.research_status = text
        return text
    

    def _remove_abstract_points(self, snips: str) -> str:
        if not snips:
            return snips
        lines = snips.splitlines()
        keep = [ln for ln in lines if not ln.strip().startswith("摘要要点")]
        return "\n".join(keep).strip()

    def _renumber_lixiang_yiju_ref_parts(self, yiyi: str, xianzhuang: str, literature_snippets: str) -> Tuple[str, str, str]:
        citation_order = _extract_citation_order(yiyi, xianzhuang)

        if not citation_order:
            clean_refs = self._remove_abstract_points(literature_snippets) if literature_snippets else ""
            return yiyi, xianzhuang, clean_refs

        id_map = {old: i for i, old in enumerate(citation_order, start=1)}

        new_yiyi = _renumber_text_with_map(yiyi, id_map)
        new_xianzhuang = _renumber_text_with_map(xianzhuang, id_map)

        new_lit = _reorder_literature(literature_snippets, citation_order) if literature_snippets else ""
        clean_refs = self._remove_abstract_points(new_lit) if new_lit else ""

        return new_yiyi, new_xianzhuang, clean_refs

    async def new_generate_lixiang_yiju_parts(self, literature_snippets, model=None, temperature: float = 0.2) -> str:
        yiyi = await self.generate_yanjiu_yiyi(literature_snippets, model=model, temperature=temperature)
        xianzhuang = await self.generate_yanjiu_xianzhuang(literature_snippets, model=model, temperature=temperature)

        new_yiyi, new_xianzhuang, final_refs = self._renumber_lixiang_yiju_ref_parts(yiyi, xianzhuang, literature_snippets)

        lixiang_yiju_parts = [
            {
                "title": "1. 研究意义",
                "level": 3,
                "content": new_yiyi,
            },
            {
                "title": "2. 国内外研究现状及发展动态",
                "level": 3,
                "content": new_xianzhuang,
            },
            {
                "title": "3. 参考文献",
                "level": 3,
                "content": final_refs,
            }
        ]
        self.lixiang_yiju_parts = lixiang_yiju_parts
        return lixiang_yiju_parts
    
    async def _generate_yanjiu_yiju_brief(self, yanjiu_xianzhuang, model=None, temperature: float = 0.2) -> str:
        prompt = prompts.YANJIU_XIANZHUANG_BRIEF_PROMPT.format(
            yanjiu_xianzhuang = yanjiu_xianzhuang
        )
        logger.info("- 调用 AI 模型生成研究现状摘要")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.yanjiu_xianzhuang_brief = parts
        return parts

    async def _generate_kexue_wenti_parts(self, model=None, temperature: float = 0.2) -> str:
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        yanjiu_yiyi = getattr(self, "yanjiu_yiyi", "")
        yanjiu_xianzhuang_brief = getattr(self, "yanjiu_xianzhuang_brief", "")
        prompt = prompts.KEXUE_WENTI_PROMPT.format(
            title = title,
            yanjiu_yiyi = yanjiu_yiyi,
            yanjiu_xianzhuang_brief = yanjiu_xianzhuang_brief
        )
        logger.info("- 调用 AI 模型生成拟解决的关键科学问题")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.kexue_wenti = parts
        return parts

    async def _generate_yanjiu_mubiao_parts(self, model=None, temperature: float = 0.2) -> str:
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        objectives = [str(o).strip() for o in (blueprint.get("objectives") or []) if str(o).strip()]
        contents = [str(c).strip() for c in (blueprint.get("contents") or []) if str(c).strip()]
        methods = [str(m).strip() for m in (blueprint.get("methods") or []) if str(m).strip()]
        yanjiu_yiyi = getattr(self, "yanjiu_yiyi", "")
        kexue_wenti = getattr(self, "kexue_wenti", "")

        prompt = prompts.YANJIU_MUBIAO_PROMPT.format(
            title = title,
            objectives = objectives,
            contents = contents,
            methods = methods,
            yanjiu_yiyi = yanjiu_yiyi,
            kexue_wenti = kexue_wenti,
        )
        logger.info("- 调用 AI 模型生成研究目标部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()

        self.yanjiu_mubiao = parts
        return parts

    async def _generate_yanjiu_neirong_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_mubiao = getattr(self, "yanjiu_mubiao", "")
        prompt = prompts.YANJIU_NEIRONG_PROMPT.format(
            yanjiu_mubiao = yanjiu_mubiao
        )
        logger.info("- 调用 AI 模型生成研究内容部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.yanjiu_neirong = parts
        return parts

    def _build_lixiang_yiju_other_sections(self) -> list[dict]:
        outline = getattr(self, "nsfc_proposal_outline", []) or []
        if not isinstance(outline, list) or not outline:
            logger.warning("nsfc_proposal_outline 为空或格式异常")
            return []

        root = None
        for node in outline:
            title = str(node.get("title", "")).replace(" ", "")
            if "立项依据与研究内容" in title:
                root = node
                break
            
        if root is None:
            logger.warning("未找到『一、立项依据与研究内容』根节点")
            return []

        target_phrases = [
            "项目的研究内容、研究目标、以及拟解决的关键科学问题",
            "拟采取的研究方案及可行性分析",
            "本项目的特色与创新之处",
            "年度研究计划及预期研究结果",
        ]

        def is_target_second_level(t: str) -> bool:
            # 标准化标题：去除空格和标点符号差异
            t0 = t.replace(" ", "").replace("，", "、").replace("；", "").replace(":", "").replace("：", "")
            # 移除括号内的说明文字
            t0 = re.sub(r'[（(].*?[）)]', '', t0)
            
            for p in target_phrases:
                p0 = p.replace(" ", "").replace("，", "、")
                if p0 in t0:
                    logger.debug(f"匹配成功: '{t}' 匹配到 '{p}'")
                    return True
            
            # 额外的容错匹配：检查是否包含关键词组合
            if "研究内容" in t0 and "研究目标" in t0 and "关键科学问题" in t0:
                logger.debug(f"关键词匹配成功: '{t}' (研究内容+研究目标+关键科学问题)")
                return True
            
            return False

        sections: List[Dict[str, Any]] = []

        def collect(node: Dict[str, Any]):
            level = int(node.get("level", 0) or 0)
            title = str(node.get("title", "")).strip()
            bullets = node.get("bullets") or []
            children = node.get("children") or []

            if title:
                clean_bullets = [
                    str(b).strip()
                    for b in bullets
                    if str(b).strip()
                ]
                sections.append(
                    {
                        "title": title,
                        "level": level,
                        "bullets": clean_bullets,
                    }
                )

            for ch in children:
                collect(ch)

        # 在 root.children 里找 2–5 这几个二级节点
        all_second_level_titles = []
        matched_count = 0
        
        for child in (root.get("children") or []):
            t = str(child.get("title", "")).strip()
            all_second_level_titles.append(t)
            
            if is_target_second_level(t):
                collect(child)
                matched_count += 1
                logger.info(f"✓ 匹配到目标章节: {t}")
            else:
                logger.debug(f"✗ 跳过非目标章节: {t}")

        logger.info(f"2–5 部分大纲小节数：{len(sections)} (匹配到 {matched_count}/4 个目标章节)")
        
        # 如果匹配失败，输出诊断信息
        if matched_count < 4:
            logger.warning(f"⚠️  未完全匹配到所有目标章节！")
            logger.warning(f"找到的二级标题: {all_second_level_titles}")
            logger.warning(f"期望匹配的标题: {target_phrases}")
        
        return sections
    
    async def generate_lixiang_yiju_other_parts(self, model, temperature: float = 0.2) -> str:
        sections = self._build_lixiang_yiju_other_sections()
        if not sections:
            return []
        
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        lixiang_yiju_fulltext = self._render_markdown(getattr(self, "lixiang_yiju_parts", []) or [])

        prompt = prompts.LIXIANG_YIJU_OTHER_PARTS_PROMPT.format(
            lixiang_yiju_fulltext = lixiang_yiju_fulltext,
            title = blueprint.get("title", ""),
            objectives = "\n".join([f"- {str(o).strip()}" for o in (blueprint.get("objectives") or []) if str(o).strip()]),
            contents = "\n".join([f"- {str(c).strip()}" for c in (blueprint.get("contents") or []) if str(c).strip()]),
            methods = "\n".join([f"- {str(m).strip()}" for m in (blueprint.get("methods") or []) if str(m).strip()]),
            sections_2_5_outline_json = json.dumps(sections, ensure_ascii=False, indent=2)
        )      
        
        logger.info("- 调用 AI 模型生成立项依据其他部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)

        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        try:
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', parts)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = parts

            # 清理非法控制字符
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            
            lixiang_yiju_other_parts = json.loads(json_str)
            if not isinstance(lixiang_yiju_other_parts, list):
                raise ValueError("LLM 输出不是 JSON 数组")
            
            self.lixiang_yiju_other_parts = lixiang_yiju_other_parts
            return lixiang_yiju_other_parts

        except Exception as e:
            logger.error(f"解析立项依据其他部分 JSON 失败: {e}")
            return []

    async def _generate_yanjiu_fangan_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown
        if not yanjiu_neirong_breakdown:
            return []
        
        prompt = prompts.YANJIU_FANGAN_PROMPT.format(
            yanjiu_neirong_breakdown = yanjiu_neirong_breakdown,
        )
        logger.info("- 调用 AI 模型生成研究方案部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts
    
    async def _generate_jishu_luxian_parts(self, yanjiu_fangan, model=None, temperature: float = 0.2) -> str:
        prompt = prompts.JISHU_LUXIAN_PROMPT.format(
            yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown,
            yanjiu_fangan = yanjiu_fangan
        )
        logger.info("- 调用 AI 模型生成技术路线部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts

    async def _generate_guanjian_jishu_parts(self, yanjiu_fangan, model=None, temperature: float = 0.2) -> str:
        prompt = prompts.GUANJIAN_JISHU_PROMPT.format(
            yanjiu_fangan = yanjiu_fangan
        )
        logger.info("- 调用 AI 模型生成关键技术部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.guanjian_jishu = parts
        return parts

    async def _generate_kexingxing_parts(self, model=None, temperature: float = 0.2) -> str:
        summarized_docs = getattr(self, "summarized_docs", []) or []
        if not summarized_docs:
            prompt = prompts.KEXINGXING_NO_DOCS_PROMPT.format(
                yanjiu_mubiao = self.yanjiu_mubiao,
                yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown,
                guanjian_jishu = self.guanjian_jishu,
            )
        else:
            prompt = prompts.KEXINGXING_WITH_DOCS_PROMPT.format(
                yanjiu_mubiao = self.yanjiu_mubiao,
                yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown,
                guanjian_jishu = self.guanjian_jishu,
                summarized_docs_brief = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()]),
            )
        
        logger.info("- 调用 AI 模型生成可行性分析部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)

        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts

    async def generate_yanjiu_fangan_kexingxing_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_fangan_parts = await self._generate_yanjiu_fangan_parts(model=model, temperature=temperature)
        jishu_luxian_parts = await self._generate_jishu_luxian_parts(yanjiu_fangan=yanjiu_fangan_parts, model=model, temperature=temperature)
        guanjian_jishu_parts = await self._generate_guanjian_jishu_parts(yanjiu_fangan=yanjiu_fangan_parts, model=model, temperature=temperature)
        kexingxing_parts = await self._generate_kexingxing_parts(model=model, temperature=temperature)

        yanjiu_fangan_kexingxing_parts = [
            {
                "title": "3.1 技术路线",
                "level": 3,
                "content": jishu_luxian_parts,
            },
            {
                "title": "3.2 研究方案",
                "level": 3,
                "content": yanjiu_fangan_parts,
            },
            {
                "title": "3.3 关键技术",
                "level": 3,
                "content": guanjian_jishu_parts,
            },
            {
                "title": "3.4 可行性分析",
                "level": 3,
                "content": kexingxing_parts,
            },
        ]
        return yanjiu_fangan_kexingxing_parts

    async def generate_chuangxinxing_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_yiyi = getattr(self, "yanjiu_yiyi", "")
        yanjiu_xianzhuang_brief = getattr(self, "yanjiu_xianzhuang_brief", "")
        kexue_wenti = getattr(self, "kexue_wenti", "")
        guanjian_jishu = getattr(self, "guanjian_jishu", "")
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        prompt = prompts.CHUANGXINXING_PROMPT.format(
            title = title,
            yanjiu_yiyi = yanjiu_yiyi,
            yanjiu_xianzhuang_brief = yanjiu_xianzhuang_brief,
            kexue_wenti = kexue_wenti,
            guanjian_jishu = guanjian_jishu,
        )
        logger.info("- 调用 AI 模型生成本项目的特色与创新之处部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts

    async def _generate_yanjiu_jihua_parts(self, model=None, temperature: float = 0.2) -> str:
        duration_years = self.query_params.get('duration_years', 3)
        system_year = datetime.now().year
        start_year = system_year + 1

        prompt = prompts.YANJIU_JIHUA_PROMPT.format(
            duration_years = duration_years,
            yanjiu_mubiao = self.yanjiu_mubiao,
            yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown,
            system_year = system_year,
            start_year = start_year,
        )

        logger.info("- 调用 AI 模型生成年度研究计划部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts

    async def _generate_yuqi_chengguo_parts(self, model=None, temperature: float = 0.2) -> str:
        fund_type = self.query_params.get('fund_type', '青年基金')

        prompt = prompts.YUQI_CHENGGUO_PROMPT.format(
            fund_type = fund_type,
            yanjiu_mubiao = self.yanjiu_mubiao,
            yanjiu_neirong_breakdown = self.yanjiu_neirong_breakdown,
        )
        
        logger.info("- 调用 AI 模型生成预期成果部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        return parts

    async def generate_jihua_chengguo_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_jihua_parts = await self._generate_yanjiu_jihua_parts(model=model, temperature=temperature)
        yuqi_chengguo_parts = await self._generate_yuqi_chengguo_parts(model=model, temperature=temperature)

        jihua_chengguo_parts = [
            {
                "title": "5.1 年度研究计划",
                "level": 3,
                "content": yanjiu_jihua_parts,
            },
            {
                "title": "5.2 预期研究成果",
                "level": 3,
                "content": yuqi_chengguo_parts,
            }
        ]
        self.jihua_chengguo_parts = jihua_chengguo_parts
        return jihua_chengguo_parts
    
    def _build_yanjiu_jichu_section(self) -> list[dict]:
        outline = getattr(self, "nsfc_proposal_outline", []) or []
        if not isinstance(outline, list) or not outline:
            return []

        chapter2_root = None
        for node in outline:
            title = str(node.get("title", "")).replace(" ", "")
            if "研究基础与工作条件" in title:
                chapter2_root = node
                break

        if chapter2_root is None:
            return []

        sections: List[Dict] = []

        def collect(node: Dict):
            level = int(node.get("level", 0) or 0)
            title = str(node.get("title", "")).strip()
            bullets = node.get("bullets") or []
            children = node.get("children") or []

            # 收集level >= 2的节点（研究基础的标题是level=2）
            if level >= 2:
                clean_bullets = [
                    str(b).strip()
                    for b in bullets
                    if str(b).strip()
                ]
                # 将 level 减 1，这样大纲中的 level 3 在 parts 中变成 level 2
                # 渲染时会自动加上 chapter_level_offset=1，最终渲染为 ### (level 3)
                adjusted_level = level - 1 if level >= 3 else level
                sections.append(
                    {
                        "title": title,
                        "level": adjusted_level,
                        "bullets": clean_bullets,
                    }
                )

            for ch in children:
                collect(ch)

        children = chapter2_root.get("children") or []
        if children:
            for ch in children:
                collect(ch)
        else:
            bullets = chapter2_root.get("bullets") or []
            clean_bullets = [
                str(b).strip()
                for b in bullets
                if str(b).strip()
            ]
            sections.append(
                {
                    "title": str(chapter2_root.get("title", "")).strip(),
                    "level": int(chapter2_root.get("level", 2) or 2),
                    "bullets": clean_bullets,
                }
            )
        return sections
    
    
    async def generate_yanjiu_jichu_parts(self, model=None, temperature: float = 0.2) -> str:
        sections = self._build_yanjiu_jichu_section()
        if not sections:
            return []
        
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        summarized_docs = getattr(self, "summarized_docs", []) or []
        lixiang_yiju_fulltext = self._render_markdown(getattr(self, "lixiang_yiju_parts", []) or [])
        
        # 格式化 summarized_docs 为字符串
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else "无"

        prompt = prompts.YANJIU_JICHU_PROMPT.format(
            lixiang_yiju = lixiang_yiju_fulltext,
            summarized_docs = summarized_docs_str,
            title = blueprint.get("title", ""),
            objectives = "\n".join([f"- {str(o).strip()}" for o in (blueprint.get("objectives") or []) if str(o).strip()]),
            contents = "\n".join([f"- {str(c).strip()}" for c in (blueprint.get("contents") or []) if str(c).strip()]),
            methods = "\n".join([f"- {str(m).strip()}" for m in (blueprint.get("methods") or []) if str(m).strip()]),
            chapter2_outline_json = json.dumps(sections, ensure_ascii=False, indent=2)
        )      
        
        logger.info("- 调用 AI 模型生成研究基础部分内容")
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)

        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)

        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        try:
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', parts)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = parts

            # 清理非法控制字符
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            
            yanjiu_jichu_parts = json.loads(json_str)
            if not isinstance(yanjiu_jichu_parts, list):
                raise ValueError("LLM 输出不是 JSON 数组")
            
            self.yanjiu_jichu_parts = yanjiu_jichu_parts
            return yanjiu_jichu_parts

        except Exception as e:
            logger.error(f"解析研究基础部分 JSON 失败: {e}")
            return []
    
    async def _generate_yanjiu_jichu_parts(self, model=None, temperature: float = 0.2) -> str:
        summarized_docs = getattr(self, "summarized_docs", []) or []
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else ""

        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        yanjiu_neirong = getattr(self, "yanjiu_neirong", "")

        if summarized_docs_str:
            prompt = prompts.YANJIU_JICHU_WITH_USER_DOCS_PROMPT.format(
                summarized_docs = summarized_docs_str,
                title = title,
                yanjiu_neirong = yanjiu_neirong

            )
        else:
            prompt = prompts.YANJIU_JICHU_WITHOUT_USER_DOCS_PROMPT.format(
                title = title,
                yanjiu_neirong = yanjiu_neirong
            )
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.yanjiu_jichu_parts = parts
        return parts
    
    async def _generate_gongzuo_tiao_parts(self, model=None, temperature: float = 0.2) -> str:
        summarized_docs = getattr(self, "summarized_docs", []) or []
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else ""
        
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        yanjiu_neirong = getattr(self, "yanjiu_neirong", "")

        prompt = prompts.GONGZUO_TIAOJIAN_PROMPT.format(
            summarized_docs = summarized_docs_str,
            title = title,
            yanjiu_neirong = yanjiu_neirong
        )
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.gongzuo_tiao_parts = parts
        return parts

    async def _generate_keyan_xiangmu_qingkuang_parts(self, model=None, temperature: float = 0.2) -> str:
        summarized_docs = getattr(self, "summarized_docs", []) or []
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else ""

        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        yanjiu_neirong = getattr(self, "yanjiu_neirong", "")
        yanjiu_mubiao = getattr(self, "yanjiu_mubiao", "")
        
        prompt = prompts.KEYAN_XIANGMU_QINGKUANG_PROMPT.format(
            summarized_docs = summarized_docs_str,
            title = title,
            yanjiu_neirong = yanjiu_neirong,
            yanjiu_mubiao = yanjiu_mubiao
        )
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.keyan_xiangmu_qingkuang_parts = parts
        return parts

    async def _generate_nsfc_projects_qingkuang_parts(self, model=None, temperature: float = 0.2) -> str:
    
        summarized_docs = getattr(self, "summarized_docs", []) or []
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else ""
        
        blueprint = getattr(self, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "")
        yanjiu_neirong = getattr(self, "yanjiu_neirong", "")
        yanjiu_mubiao = getattr(self, "yanjiu_mubiao", "")
        
        prompt = prompts.NSFC_PROJECTS_QINGKUANG_PROMPT.format(
            summarized_docs = summarized_docs_str,
            title = title,
            yanjiu_neirong = yanjiu_neirong,
            yanjiu_mubiao = yanjiu_mubiao
        )
        model = model or self.model
        content_stream = model.generate_stream(prompt, temperature=temperature)
        string_buffer = io.StringIO()
        async for chunk in content_stream:
            if chunk:
                string_buffer.write(chunk)
        parts = string_buffer.getvalue()
        string_buffer.close()
        parts = self._remove_think_blocks(parts)
        parts = self._strip_md_fences(parts)
        parts = parts.strip()
        self.nsfc_projects_qingkuang_parts = parts
        return parts
    
    async def new_generate_yanjiu_jichu_parts(self, model=None, temperature: float = 0.2) -> str:
        yanjiu_jichu_parts = await self._generate_yanjiu_jichu_parts(model, temperature)
        gongzuo_tiaojian_parts = await self._generate_gongzuo_tiao_parts(model, temperature)
        keyan_xiangmu_qingkuang_parts = await self._generate_keyan_xiangmu_qingkuang_parts(model, temperature)
        nsfc_projects_qingkuang_parts = await self._generate_nsfc_projects_qingkuang_parts(model, temperature)
        parts = [
            {
                "title": "1. 研究基础（与本项目相关的研究工作积累和已取得的研究工作成绩）；",
                "level": 2,
                "content": yanjiu_jichu_parts,
            },
            {
                "title": "2. 工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；",
                "level": 2,
                "content": gongzuo_tiaojian_parts,
            },
            {
                "title": "3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；",
                "level": 2,
                "content": keyan_xiangmu_qingkuang_parts,
            },
            {
                "title": "4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。",
                "level": 2,
                "content": nsfc_projects_qingkuang_parts,
            },
        ]
        return parts

    async def generate_qita_shuoming_parts(self, model=None, temperature: float = 0.2) -> str:
        
        summarized_docs = getattr(self, "summarized_docs", []) or []
        
        # 格式化 summarized_docs 为字符串
        if isinstance(summarized_docs, list):
            summarized_docs_str = "\n\n".join([f"【文档 {i+1}】\n{str(doc).strip()}" for i, doc in enumerate(summarized_docs) if str(doc).strip()])
        else:
            summarized_docs_str = str(summarized_docs) if summarized_docs else "无"
        
        prompt = prompts.QITA_SHUOMING_PROMPT.format(
            summarized_docs = summarized_docs_str
        )
        
        model = model or self.model
        response = await model(user_prompt=prompt, temperature=temperature)

        if hasattr(response, "content"):
            response_text = response.content
        elif hasattr(response, "choices") and len(response.choices) > 0:
            response_text = response.choices[0].message.content
        else:
            response_text = str(response)

        response_text = self._remove_think_blocks(response_text)

        try:
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text

            # 清理非法控制字符
            json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            
            qita_shuoming_parts = json.loads(json_str)
            
            # 确保每个 part 都有 level=2（渲染时会自动加上 chapter_level_offset=1，最终为 level 3）
            if isinstance(qita_shuoming_parts, list):
                for part in qita_shuoming_parts:
                    if isinstance(part, dict) and "level" not in part:
                        part["level"] = 2
                
                # 固定第5条（索引4）的AI使用情况说明为标准模板
                if len(qita_shuoming_parts) >= 5:
                    ai_usage_template = (
                        "本申请书在文献综述、研究现状分析等部分使用了生成式人工智能工具（如DeepSeek、QWen等）"
                        "进行初步资料整理和语言表达优化。所有核心科学问题的凝练、研究内容设计、研究方案制定、"
                        "技术路线规划以及创新点阐述等学术内容均由申请人团队独立完成，AI工具仅作为辅助手段。"
                        "申请人对申请书全部内容的科学性、真实性和原创性负责。"
                    )
                    qita_shuoming_parts[4]["content"] = ai_usage_template
            
            self.qita_shuoming_parts = qita_shuoming_parts
            return qita_shuoming_parts

        except Exception as e:
            logger.error(f"解析其他说明部分 JSON 失败: {e}")
            return []
    

    def _normalize_qita_shuoming_section(self, outline: List[Dict]) -> List[Dict]:
        if not outline:
            return outline

        TARGET_TITLES = [
            "1. 申请人同年申请不同类型的国家自然科学基金项目情况",
            "2. 具有高级专业技术职务（职称）的申请人是否存在同年申请或者参与申请国家自然科学基金项目的单位不一致的情况",
            "3. 具有高级专业技术职务（职称）的申请人是否存在与正在承担的国家自然科学基金项目的单位不一致的情况",
            "4. 同年以不同专业技术职务（职称）申请或参与申请科学基金项目的情况",
            "5. 申请人在撰写本申请书时使用生成式人工智能的情况",
            "6. 其他需要说明的情况",
        ]

        def _normalize_others_node(node: Dict) -> Dict:
            children = node.get("children") or []
            clean_children: List[Dict] = []

            for ch in children:
                level = int(ch.get("level", 0) or 0)
                title = str(ch.get("title", "")).strip()
                if level == 2 and title in TARGET_TITLES:
                    ch["children"] = []  # 不允许再有下级
                    if "bullets" not in ch or ch["bullets"] is None:
                        ch["bullets"] = []
                    clean_children.append(ch)
                    
            exist_titles = {str(c.get("title", "")).strip() for c in clean_children}
            for t in TARGET_TITLES:
                if t not in exist_titles:
                    clean_children.append(
                        {
                            "title": t,
                            "level": 2,
                            "bullets": [],  # bullets 可在后续写作 prompt 中用默认说明
                            "children": [],
                        }
                    )

            title_index = {t: i for i, t in enumerate(TARGET_TITLES)}
            clean_children.sort(key=lambda x: title_index.get(str(x.get("title", "")).strip(), 999))

            node["children"] = clean_children
            return node

        for node in outline:
            title_norm = str(node.get("title", "")).replace(" ", "")
            if "其他需要说明的情况" in title_norm:
                node = _normalize_others_node(node)
                break

        return outline 
            
    def _fix_less_than_symbol(self, text: str) -> str:
        """将 < 转换为 &lt; 用于前端Markdown渲染，导出Word时会转换回来"""
        if not text:
            return text
        text = text.replace('<', '&lt;')
        return text
    
    def _render_markdown(self, parts: list[dict], root_title: str = None, level_offset: int = 0) -> str:
        """
        渲染parts为Markdown
        level_offset: 所有标题level增加的偏移量（用于调整层级）
        """
        if not parts:
            return "（当前尚未生成内容）"
        
        normal_sections: list[dict] = []
        ref_sections: list[dict] = []

        for sec in parts:
            title = str(sec.get("title") or "").strip()
            if title == "参考文献":
                ref_sections.append(sec)
            else:
                normal_sections.append(sec)

        lines: list[str] = []

        # 如果有root_title且是章节标题，其下的子标题需要提升一级
        chapter_level_offset = 0
        if root_title:
            # （一）（二）（三）（四）都应该是## level 2，子项为### level 3
            if root_title.startswith("二、") or root_title.startswith("三、") or \
               root_title.startswith("（一）") or root_title.startswith("（二）") or \
               root_title.startswith("（三）") or root_title.startswith("（四）"):
                lines.append(f"## {root_title}")
                # parts的level=2应该变成###（level=3）
                chapter_level_offset = 1
            else:
                lines.append(f"### {root_title}")
            lines.append("")

        for sec in normal_sections:
            title = str(sec.get("title") or "").strip()
            # 综合level_offset和chapter_level_offset
            level = int(sec.get("level") or 0) + level_offset + chapter_level_offset
            content = str(sec.get("content") or "").rstrip()

            if not title and not content:
                continue
            
            # 修复标题中的 < 符号
            title = self._fix_less_than_symbol(title)
            
            if level == 2:
                heading = f"## {title}"
            elif level == 3:
                heading = f"### {title}"
            elif level == 4:
                heading = f"#### {title}"
            elif level == 5:
                heading = f"##### {title}"
            elif level == 6:
                heading = f"###### {title}"
            else:
                heading = f"### {title}" if title else ""

            if heading:
                lines.append("")
                lines.append(heading)
                lines.append("")

            if content:
                # 修复内容中的 < 符号
                content = self._fix_less_than_symbol(content)
                lines.append(content)

        # 渲染参考文献部分
        if ref_sections:
            lines.append("")
            # 参考文献的层级需要考虑 level_offset 和 chapter_level_offset
            # ref_sections 中的 level 通常是 3，渲染时加上偏移量
            for sec in ref_sections:
                ref_level = int(sec.get("level") or 3) + level_offset + chapter_level_offset
                
                # 根据计算出的 level 渲染参考文献标题
                if ref_level == 2:
                    lines.append("## 参考文献")
                elif ref_level == 3:
                    lines.append("### 参考文献")
                elif ref_level == 4:
                    lines.append("#### 参考文献")
                elif ref_level == 5:
                    lines.append("##### 参考文献")
                else:
                    lines.append("#### 参考文献")  # 默认使用 level 3
                
                lines.append("")
                content = str(sec.get("content") or "").rstrip()
                if content:
                    # 修复参考文献中的 < 符号
                    content = self._fix_less_than_symbol(content)
                    lines.append(content)
                    lines.append("")

        return "\n".join(lines).strip()

    def _remove_abstract_points(self, literature_snippets: str) -> str:
        """
        从literature_snippets中删除"摘要要点："行
        """
        if not literature_snippets:
            return ""
        
        lines = literature_snippets.split('\n')
        clean_lines = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            # 跳过"摘要要点："开头的行
            if line.strip().startswith('摘要要点：') or line.strip().startswith('摘要要点:'):
                i += 1
                continue
            clean_lines.append(line)
            i += 1
        
        return '\n'.join(clean_lines)
    

    def _try_fix_json_format(self, text: str) -> str:
        if not text:
            return ""
        
        text = text.strip()
        
        # Step 1: Remove trailing garbage after last valid } or ]
        # Find the last occurrence of } or ]
        last_brace = max(text.rfind('}'), text.rfind(']'))
        if last_brace > 0 and last_brace < len(text) - 1:
            trailing = text[last_brace + 1:].strip()
            if trailing:
                logger.warning(f"检测到JSON尾部垃圾字符（长度={len(trailing)}），截断: {trailing[:100]}")
                text = text[:last_brace + 1]
        
        # Step 2: Fix: }{ -> },{
        if "}{" in text:
            logger.info("检测到 }{ 格式错误，尝试修复为 },{")
            text = text.replace("}{", "},{")
        
        # Step 3: If text starts with { and contains ,{ or }, wrap in array
        if text.startswith("{") and ("},{" in text or text.count("{") > 1):
            logger.info("检测到多个对象，尝试包装为数组")
            # Check if already wrapped
            if not (text.startswith("[") and text.endswith("]")):
                text = "[" + text + "]"
        
        # Step 4: Remove trailing commas before closing brackets
        text = re.sub(r',\s*]', ']', text)
        text = re.sub(r',\s*}', '}', text)
        
        return text
    
    def _remove_think_blocks(self, text: str) -> str:
        if not text:
            return text

        cleaned = text.strip()

        cleaned = re.sub(
            r"<think>[\s\S]*?</think>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"<reasoning>[\s\S]*?</reasoning>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

        for tag in ("think", "reasoning"):
            m = re.search(rf"<{tag}[^>]*>", cleaned, flags=re.IGNORECASE)
            if m:
                cleaned = cleaned[: m.start()] # 从标签开始到结尾全删
                cleaned = cleaned.rstrip()

        return cleaned.strip()

    def _strip_md_fences(self, text: str) -> str:
        if not text:
            return text
        text = text.strip()
        m = re.match(r"^```[a-zA-Z0-9_-]*\s*([\s\S]*?)\s*```$", text)
        if m:
            return m.group(1).strip()
        return text