import json
import asyncio
import logging
import os
import time
import traceback
import zipfile
from typing import Any, Callable, List, Type, TypedDict
from i18n.languages import normalize as _norm

import aiohttp
from docx import Document
from docx.shared import Inches, Pt
import requests
import tiktoken
from pydantic import BaseModel

from config import settings
from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.composite_models import (
    BetterIITReviewModels,
    IITReviewModels,
)
from agent.explore.mindsearch_clinical_guidance_agent import MindSearchClinicalGuideline
from agent.policy.drug_policy_elastic_search import DrugPolicyElasticSearch
from agent.iit.utils.pubmed.utils import pubmed_analysis, run_pubmed_agent
from agent.human_in_loop.utils import convert_md_to_docx
from agent.iit.utils.db import write_iit_context
from agent.iit.v3.guidelines.selection import select_guidelines
from agent.iit.utils.md2word import md_to_word
from utils.sql_client import get_connection_user, text
from utils.scholar import PubMedSearch
from utils.drug_manuals.drug_manuals_elastic_search import DrugManualsElasticSearch
from agent.iit.prompt.util_prompt import (
    get_queries_prompt,
    check_policy_prompt,
    drug_judgement_prompt,
    is_rct_prompt,
    expand_drug_prompt,
    translate_iit_prompt
)
from agent.iit.prompt.formal_prompt import (
    formal_summarize_prompt,
    formal_integrity_prompt,
    formal_consistency_prompt,
    formal_appendix_prompt,
    formal_drug_manuals_prompt,
    get_summary_prompt,
    get_start_prompt,
    compare_summry_main_prompt,
    process_formal_report_prompt
)
from agent.iit.prompt.scientific_prompt import (
    scientific_drug_manuals_prompt,
    scientific_objective_and_hypothesis_prompt,
    scientific_necessity_and_innovation_prompt,
    scientific_summarize_prompt,
    scientific_general_analysis_prompt,
    process_scientific_report_prompt
)
from agent.iit.utils.html2pdf import convert_md_to_pdf_iit
from agent.iit.constants import IITTaskStatus
from dotenv import load_dotenv
from utils.redis_client import create_engines
from datetime import datetime, timezone, timedelta
from utils.utils.attachment import AttachmentManager

cache = create_engines(decode_responses=False)


load_dotenv()

logger = logging.getLogger(__name__)

class IITReviewContext(BaseModel):
    iit_id: int = 0
    processing_status: str = ""
    content: str = ""
    html: str = ""
    queries: str = ""
    drug_manuals_result: str = ""
    pubmed_result: str = ""
    clinical_guidance_result: str = ""
    policy_result: str = ""
    formal_integrity_result: str = ""
    formal_consistency_result: str = ""
    formal_appendix_result: str = ""
    scientific_analysis_result: str = ""
    formal_compare_summary_main_result: str = ""
    status: str = ""
    url: str = ""
    progress: int = 0
    title: str = ""
    category: str = ""

class IsRCTResult(TypedDict):
    reasoning: str
    is_rct: bool

class DrugJudgementResult(TypedDict):
    reasoning: str
    primary_intervention_type: str
    is_drug_intervention: bool
    target_drugs: list[str]
    drug_usage_evidence: List[str]

class IITAgent(AgentPreset):
    llm: BaseLLM = IITReviewModels
    better_llm: BaseLLM = BetterIITReviewModels
    drug_manuals_elastic_search: DrugManualsElasticSearch = DrugManualsElasticSearch()
    pubmed_search_client: PubMedSearch = PubMedSearch()
    attachment_manager: AttachmentManager = AttachmentManager()
    mindsearch_clinical_guidance_agent: MindSearchClinicalGuideline = None
    drug_policy_elastic_search: DrugPolicyElasticSearch = None
    iit_requests: List[dict] = []
    cache_key: str = ""
    _http_session: aiohttp.ClientSession = None

    def __init__(self, file=None, **kwargs):
        super().__init__()
        self.iit_requests = kwargs.get("iit_requests", [])
        self.mindsearch_clinical_guidance_agent = MindSearchClinicalGuideline()
        self.cache_key = kwargs.get("cache_key", "default_iit_agent_lock_key")
        self.drug_policy_elastic_search = DrugPolicyElasticSearch()

    async def get_http_session(self):
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def close(self):
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()

    @staticmethod
    def _halve_text_if_tokens_exceed_limit(text: str, max_tokens: int = 400000, encoding_name: str = "cl100k_base") -> str:
        if not text:
            return text
        encoding = tiktoken.get_encoding(encoding_name)
        logger.info(f"Original text length: {len(text)}, Token count: {len(encoding.encode(text))}, Max tokens allowed: {max_tokens}")
        while len(encoding.encode(text)) > max_tokens and len(text) > 1:
            text = text[: len(text) // 2]
            logger.info(f"Text length after halving: {len(text)}, Token count: {len(encoding.encode(text))}")
        return text
    
    async def use_tool(self, review_type="formal", language="en", **kwargs):
        language = _norm(language)
        files = [f["file"] for f in self.iit_requests]
        iit_ids = [f["iit_id"] for f in self.iit_requests]
        file_contents = []
        coroutines = []
        try:
            file_contents = self.attachment_manager.fetch_attachments(files, True)
            for i, f in enumerate(file_contents):
                raw_content=f.get('content', {}).get('raw_content')
                logger.info(f"iit content preview: {str(raw_content)[:1000]}")
                coroutines.append(asyncio.create_task(self._use_tool(content=f.get('content', {}).get('raw_content'), iit_id=iit_ids[i], review_type=review_type, language=language, name=f.get("name", ""))))
            await asyncio.gather(*coroutines)
            cache.delete(f"{self.cache_key}")

        except Exception as e:
            cache.delete(f"{self.cache_key}")
            logger.warning(traceback.format_exc())
            raise e
        yield True
    
    async def _use_tool(self, content=None, iit_id=None, review_type="formal", language="en", **kwargs):
        ctx = IITReviewContext()
        ctx.iit_id = iit_id
        ctx.title = kwargs.get("name", "")
        ctx.category = review_type
        ctx.status = IITTaskStatus.RUNNING

        async def formal_analysis(content, ctx):
            formal_drug_manuals_analysis_work = self.formal_drug_manuals_analysis(ctx=ctx, iit_text=content)
            formal_integrity_work = self.formal_integrity_analysis(ctx=ctx, iit_text=content)
            formal_consistency_work = self.formal_consistency_analysis(ctx, iit_text=content)
            formal_appendix_work = self.formal_appendix_analysis(ctx=ctx, iit_text=content)
            formal_compare_summary_main_work = self.formal_compare_summary_main(ctx=ctx, iit_text=content)
            formal_drug_manuals_result, formal_integrity_result, formal_consistency_result, formal_appendix_result, formal_compare_summary_main_result  = await asyncio.gather(formal_drug_manuals_analysis_work, formal_integrity_work, formal_consistency_work, formal_appendix_work, formal_compare_summary_main_work)

            ctx.formal_integrity_result = formal_integrity_result
            ctx.formal_consistency_result = formal_consistency_result
            ctx.formal_appendix_result = formal_appendix_result
            ctx.drug_manuals_result = formal_drug_manuals_result
            ctx.formal_compare_summary_main_result = formal_compare_summary_main_result

        async def scientific_analysis(
            content,
            ctx,
            pubmed_query,
            clinical_guidance_query,
            policy_query,
        ):
            from agent.iit.v3.guidelines.analysis import guidelines_analysis
            # 调用查询工具
            ctx.processing_status = "临床指南，pubmed，政策查询开始"
            await write_iit_context(ctx)
            clinical_guidance_query_task = asyncio.create_task(
                guidelines_analysis(clinical_guidance_query, ctx, iit_protocol=content))
            pubmed_search_task = asyncio.create_task(
                run_pubmed_agent(ctx, pubmed_query, content))
            policy_search_task = asyncio.create_task(
                self.policy_search(ctx=ctx, policy_query=policy_query)
            )
            ctx.processing_status = "科学审查开始"
            await write_iit_context(ctx)
            scientific_general_analysis_task = asyncio.create_task(self.scientific_general_analysis(ctx, content, policy_search_task))
            scientific_necessity_and_innovation_analysis_task = asyncio.create_task(self.scientific_necessity_and_innovation_analysis(ctx, content, clinical_guidance_query_task, pubmed_search_task))
            scientific_objective_and_hypothesis_analysis_task = asyncio.create_task(self.scientific_objective_and_hypothesis_analysis(ctx, content, pubmed_search_task))
            scientific_drug_manuals_analysis_task = asyncio.create_task(self.scientific_drug_manuals_analysis(ctx, content, pubmed_search_task))
            results = await asyncio.gather(
                scientific_general_analysis_task, 
                scientific_necessity_and_innovation_analysis_task, 
                scientific_objective_and_hypothesis_analysis_task, 
                scientific_drug_manuals_analysis_task
                )

            scientific_analysis_result = await self.scientific_summarize(ctx, results)
            ctx.content = scientific_analysis_result
            ctx.processing_status = "科学审查结束"
            ctx.scientific_analysis_result = scientific_analysis_result
            await write_iit_context(ctx)
            
        try:
            is_rct_task = asyncio.create_task(self.is_rct(content))
            ctx.processing_status = "正在进行文档初始化"
            await write_iit_context(ctx)
            ctx.processing_status = "正在获取查询工具参数"
            await write_iit_context(ctx)
            ctx.queries = await self._get_queries(content)
            json_queries = json.loads(ctx.queries)
            ctx.progress += 10
            await write_iit_context(ctx)
            # 获得三个查询工具的参数
            pubmed_query = json_queries.get("pubmed_query")
            clinical_guidance_query = json_queries.get("clinical_guidance_query")
            policy_query = json_queries.get("policy_query")
            indication_query = json_queries.get("indication_query")
            clinical_guidance_query = [clinical_guidance_query, indication_query]
            ctx.processing_status = "查询工具参数获取完成"
            await write_iit_context(ctx)
            if review_type == "formal":
                await formal_analysis(content, ctx)
                # 结果整合
                ctx.processing_status = "正在进行最终的结果整合"
                await write_iit_context(ctx)
                result = await self.formal_summarize(
                    ctx, ctx.formal_integrity_result, ctx.formal_consistency_result, ctx.formal_appendix_result, ctx.drug_manuals_result, ctx.formal_compare_summary_main_result
                )
                ctx.content = result
                ctx.processing_status = "结果整合完毕，形式审查完成"
                await write_iit_context(ctx)
            elif review_type == "scientific":
                await scientific_analysis(content, ctx, pubmed_query=pubmed_query, clinical_guidance_query=clinical_guidance_query, policy_query=policy_query)
            else:
                pass
            upload_result_dir = f"outputs/iit_review_{iit_id}_{int(time.time())}"
            is_rct = await is_rct_task
            if not is_rct:
                if review_type == "formal":
                    await self.process_formal_report(ctx)
                else:
                    await self.process_scientific_report(ctx)
            await self.translate(ctx, language)
            await upload_result(upload_result_dir, language, ctx=ctx)
            ctx.status = IITTaskStatus.SUCCESS
            await write_iit_context(ctx)
        except Exception as e:
            logger.error(f"[IITAgent] use_tool error: {str(e)}\n{traceback.format_exc()}", stacklevel=2, stack_info=True)
            ctx.processing_status = "审查过程中出现错误"
            ctx.status = IITTaskStatus.FAILED
            await write_iit_context(ctx)
            raise e
            # await write_iit_context(ctx)
    
    async def translate(self, ctx, language):
        if language == "zh-CN":
            return
        else:
            task = self.llm().stream_call(sys_prompt=translate_iit_prompt.format(iit_review_result=ctx.content), thinking_budget='low')
            translated_content = ""
            async for chunk in task:
                translated_content += chunk
            ctx.content = translated_content

    async def is_rct(self, content):
        fallback_result = {"reasoning": "LLM解析异常或返回非JSON内容，默认跳过优化", "is_rct": True}
        
        try:
            task = self.llm().stream_call(
                sys_prompt=is_rct_prompt.format(iit_text=content), 
                response_schema=IsRCTResult, 
                temperature=0,
                thinking_budget='low' 
            )
            
            is_rct_json = ""
            async for chunk in task:
                if chunk:
                    is_rct_json += chunk
            
            cleaned_json_str = is_rct_json.replace("```json", "").replace("```", "").strip()

            if not cleaned_json_str:
                is_rct_result = fallback_result
            else:
                start_idx = cleaned_json_str.find('{')
                end_idx = cleaned_json_str.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    cleaned_json_str = cleaned_json_str[start_idx : end_idx + 1]
                    is_rct_result = json.loads(cleaned_json_str)
                else:
                    raise json.JSONDecodeError("No JSON brackets found", cleaned_json_str, 0)

        except (json.JSONDecodeError, Exception) as e:
            is_rct_result = fallback_result

        return is_rct_result.get('is_rct', True)
            

    
    async def process_formal_report(self, ctx):
        md_content = ctx.content
        task = self.better_llm().stream_call(sys_prompt=process_formal_report_prompt.format(original_report=md_content), thinking_budget='low')
        final_md_content = ""
        async for chunk in task:
            final_md_content += chunk
        ctx.content = final_md_content

    async def process_scientific_report(self, ctx):
        md_content = ctx.content
        task = self.better_llm().stream_call(sys_prompt=process_scientific_report_prompt.format(original_report=md_content), thinking_budget='low')
        final_md_content = ""
        async for chunk in task:
            final_md_content += chunk
        ctx.content = final_md_content

    async def scientific_summarize(self, ctx, results):
        ctx.processing_status = "科学审查结果总结开始"
        await write_iit_context(ctx)
        scientific_general_analysis_result = results[0]
        scientific_necessity_and_innovation_analysis_result = results[1]
        scientific_objective_and_hypothesis_analysis_result = results[2]
        scientific_drug_manuals_analysis_result = results[3]
        task = self.better_llm().stream_call(sys_prompt=scientific_summarize_prompt, 
                             user_prompt=f"大体审查结果：{scientific_general_analysis_result}\n必要性与创新性审查结果:{scientific_necessity_and_innovation_analysis_result}\n目标与假设审查结果:{scientific_objective_and_hypothesis_analysis_result}\n超说明书审查结果:{scientific_drug_manuals_analysis_result}", thinking_budget='low', temperature=0)
        scientific_analysis_result = ""
        async for chunk in task:
            scientific_analysis_result += chunk
        ctx.processing_status = "科学审查总结结束"
        ctx.progress += 10
        await write_iit_context(ctx)
        return scientific_analysis_result

    async def policy_search(self, ctx, policy_query):
        ctx.processing_status = "查询政策法规开始"
        await write_iit_context(ctx)
        policy_result1 = await self.drug_policy_elastic_search.search_drug_policy(query=policy_query,index="drug_policy_china", size=3)
        policy_result2 = await self.drug_policy_elastic_search.search_drug_policy(query=policy_query, index="drug_policy_global", size=3)
        policy_result = policy_result1 + policy_result2
        policy_result_content = str(policy_result)
        policy_result = await self._check_policy(policy_query, policy_result_content)
        ctx.processing_status = "查询政策法规结束"
        ctx.policy_result = policy_result
        await write_iit_context(ctx)
        return policy_result

    async def scientific_necessity_and_innovation_analysis(self, ctx, iit_text, clinical_guidance_query_task, pubmed_search_task):
        ctx.processing_status = "方案必要性与创新性审查开始"
        await write_iit_context(ctx)
        clinical_guidance_query_result = await clinical_guidance_query_task
        pubmed_search_result = await pubmed_search_task

        safe_iit_text = "\n".join(iit_text) if isinstance(iit_text, list) else str(iit_text)

        if isinstance(pubmed_search_result, (list, dict)):
            safe_pubmed_result = json.dumps(pubmed_search_result, ensure_ascii=False)
        else:
            safe_pubmed_result = str(pubmed_search_result)

        safe_prompt = scientific_necessity_and_innovation_prompt \
            .replace("iit_text", safe_iit_text) \
            .replace("clinical_guidance_query_result", str(clinical_guidance_query_result)) \
            .replace("pubmed_search_result", safe_pubmed_result)

        task = self.better_llm().stream_call(
            sys_prompt=safe_prompt, 
            thinking_budget='low'
        )
        result = ""
        async for chunk in task:
            result += chunk
        ctx.processing_status = "方案必要性与创新性审查结束"
        ctx.clinical_guidance_result = clinical_guidance_query_result
        ctx.pubmed_result = pubmed_search_result
        ctx.progress += 10
        await write_iit_context(ctx)
        return result
    
    async def scientific_objective_and_hypothesis_analysis(self, ctx, iit_text, pubmed_search_task):
        ctx.processing_status = "方案目标与假设审查开始"
        await write_iit_context(ctx)
        pubmed_search_result = await pubmed_search_task
        task = self.llm().stream_call(sys_prompt=scientific_objective_and_hypothesis_prompt.format(iit_text=iit_text, pubmed_search_result=pubmed_search_result), thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        ctx.processing_status = "方案目标与假设审查结束"
        ctx.pubmed_result = pubmed_search_result
        ctx.progress += 10
        await write_iit_context(ctx)
        return result

    async def scientific_drug_manuals_analysis(self, ctx, iit_text, pubmed_search_task):
        ctx.processing_status = "开始用药审查"
        await write_iit_context(ctx)
        task = self.llm().stream_call(sys_prompt=drug_judgement_prompt.format(iit_text=iit_text),response_schema=DrugJudgementResult, thinking_budget='low')
        drug_judgement_json = ""
        async for chunk in task:
            drug_judgement_json += chunk
        cleaned_json_str = drug_judgement_json.replace("```json", "").replace("```", "").strip()
        drug_judgement_result = json.loads(cleaned_json_str)
        if not drug_judgement_result['is_drug_intervention']:
            ctx.processing_status = "用药审查完成"
            ctx.progress += 10
            return ""

        drugs_list = drug_judgement_result['target_drugs']
        drug_usage_evidence = drug_judgement_result.get("drug_usage_evidence", [])
        expand_drug_tasks = [
            self.expand_drug_name(drug)
            for drug in drugs_list
        ]

        expand_drug_tasks_results = await asyncio.gather(*expand_drug_tasks)
        logger.info(f"Expand drug tasks results: {expand_drug_tasks_results}")
        expanded_drug_manuals_result = []
        for expand_drug_tasks_result in expand_drug_tasks_results:
            drug_manuals_result = await self.drug_manuals_elastic_search.search_single_drug_by_aliases(aliases=expand_drug_tasks_result)
            expanded_drug_manuals_result.append(drug_manuals_result)
        
        logger.info(f"Expanded drug manuals result: {json.dumps(expanded_drug_manuals_result, ensure_ascii=False)}")
        pubmed_search_result = await pubmed_search_task
        drug_manuals_analysis_result = ""
        task = self.better_llm().stream_call(sys_prompt=scientific_drug_manuals_prompt.format(drug_manuals_result=json.dumps(expanded_drug_manuals_result, ensure_ascii=False), drug_usage_evidence=drug_usage_evidence, pubmed_search_result=pubmed_search_result), thinking_budget='low')
        async for chunk in task:
            drug_manuals_analysis_result += chunk
        
        logger.info(f"scientific_drug_manuals_analysis_result:\n{drug_manuals_analysis_result}")
        ctx.processing_status = "用药审查完成"
        ctx.progress += 10
        await write_iit_context(ctx)
        return drug_manuals_analysis_result

    async def scientific_general_analysis(self, ctx, iit_text, policy_search_task):
        ctx.processing_status = "方案科学总体审查开始"
        await write_iit_context(ctx)
        policy_search_result = await policy_search_task
        task = self.llm().stream_call(sys_prompt=scientific_general_analysis_prompt, user_prompt=f"iit方案:{iit_text}\n政策查询结果:{policy_search_result}", thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        ctx.processing_status = "方案科学总体审查结束"
        ctx.progress += 10
        await write_iit_context(ctx)
        return result

    async def formal_compare_summary_main(self, ctx, iit_text):
        try:
            ctx.processing_status = "摘要与正文比较开始"
            if type(iit_text) == list:
                iit_text = "\n".join(iit_text)
            await write_iit_context(ctx)
            pre = (int)(len(iit_text)/4)
            logger.info(f"Preliminary text length for summary: {pre}")
            summary_text = self._halve_text_if_tokens_exceed_limit(iit_text[:pre])
            logger.info(f"Processed text length for summary: {pre}")
            
            summary_work = self.formal_get_summary(summary_text)
            start_work = self.formal_get_start(summary_text)
            iit_summary, iit_start = await asyncio.gather(summary_work, start_work)
            iit_main = iit_start + iit_text[pre:]
            task = self.llm().stream_call(sys_prompt=compare_summry_main_prompt.format(iit_main=iit_main, iit_summary=iit_summary), thinking_budget='low')
            summary_main_result = ""
            async for chunk in task:
                summary_main_result += chunk
            logger.info("formal_compare_summary_main_result:\n")
            # logger.info(summary_main_result)
            ctx.processing_status = "摘要与正文比较结束"
            ctx.progress += 10
            await write_iit_context(ctx)
            
            return summary_main_result
        except Exception as e:
            logger.error(f"Error in formal_compare_summary_main: {e}")
            logger.error(traceback.format_exc())

    async def formal_get_start(self, summary_text):
        task = self.llm().stream_call(sys_prompt=get_start_prompt.format(summary_text=summary_text), thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        logger.info("formal_get_start_result:\n")
        # logger.info(result)
        return result

    async def formal_get_summary(self, summary_text):
        task = self.llm().stream_call(sys_prompt=get_summary_prompt.format(summary_text=summary_text), thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        logger.info("formal_get_summary_result:\n")
        # logger.info(result)
        return result

    async def formal_drug_manuals_analysis(self, ctx, iit_text):
        ctx.processing_status = "开始用药审查"
        await write_iit_context(ctx)
        task = self.llm().stream_call(sys_prompt=drug_judgement_prompt.format(iit_text=iit_text),response_schema=DrugJudgementResult, thinking_budget='low')
        drug_judgement_json = ""
        async for chunk in task:
            drug_judgement_json += chunk
        cleaned_json_str = drug_judgement_json.replace("```json", "").replace("```", "").strip()
        drug_judgement_result = json.loads(cleaned_json_str)
        if not drug_judgement_result['is_drug_intervention']:
            ctx.processing_status = "用药审查完成"
            ctx.progress += 10
            return ""

        drugs_list = drug_judgement_result['target_drugs']
        drug_usage_evidence = drug_judgement_result.get("drug_usage_evidence", [])
        expand_drug_tasks = [
            self.expand_drug_name(drug)
            for drug in drugs_list
        ]

        expand_drug_tasks_results = await asyncio.gather(*expand_drug_tasks)
        logger.info(f"Expand drug tasks results: {expand_drug_tasks_results}")
        expanded_drug_manuals_result = []
        for expand_drug_tasks_result in expand_drug_tasks_results:
            drug_manuals_result = await self.drug_manuals_elastic_search.search_single_drug_by_aliases(aliases=expand_drug_tasks_result)
            expanded_drug_manuals_result.append(drug_manuals_result)
        
        logger.info(f"Expanded drug manuals result: {json.dumps(expanded_drug_manuals_result, ensure_ascii=False)}")
        drug_manuals_analysis_result = ""
        task = self.better_llm().stream_call(sys_prompt=formal_drug_manuals_prompt.format(drug_usage_evidence=drug_usage_evidence, drug_manuals_result=json.dumps(expanded_drug_manuals_result, ensure_ascii=False)), thinking_budget='low')
        async for chunk in task:
            drug_manuals_analysis_result += chunk
        
        logger.info(f"formal_drug_manuals_analysis_result:\n{drug_manuals_analysis_result}")
        ctx.processing_status = "用药审查完成"
        ctx.progress += 10
        await write_iit_context(ctx)
        return drug_manuals_analysis_result

    async def formal_integrity_analysis(self, ctx, iit_text):
        ctx.processing_status = "开始完整性审查"
        await write_iit_context(ctx)
        task = self.llm().stream_call(sys_prompt=formal_integrity_prompt.format(iit_text=iit_text), thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        logger.info("formal_integrity_result:\n")
        # logger.info(result)
        ctx.processing_status = "完整性审查完成"
        ctx.progress += 10
        await write_iit_context(ctx)
        return result
    
    async def formal_consistency_analysis(self, ctx, iit_text):
        ctx.processing_status = "开始一致性审查"
        await write_iit_context(ctx)
        task = self.llm().stream_call(
            sys_prompt=formal_consistency_prompt.format(iit_text=iit_text), thinking_budget='low')
        result = ""
        async for chunk in task:
            result += chunk
        logger.info("formal_consistency_result:\n")
        # logger.info(result)
        ctx.processing_status = "一致性审查完成"
        ctx.progress += 10
        await write_iit_context(ctx)
        return result
    
    async def formal_appendix_analysis(self, ctx, iit_text):
        ctx.processing_status = "开始附录审查"
        await write_iit_context(ctx)
        formal_analysis_extra_task = self.llm().stream_call(
            sys_prompt=formal_appendix_prompt.format(iit_text=iit_text),
            temperature=0.1,
            thinking_budget='low'
        )
        result = ""
        async for chunk in formal_analysis_extra_task:
            result += chunk
        logger.info("formal_appendix_result:\n")
        # logger.info(result)
        ctx.processing_status = "附录审查完成"
        ctx.progress += 10
        await write_iit_context(ctx)
        return result
    
    async def formal_summarize(self, ctx, formal_integrity_result, formal_consistency_result, formal_appendix_result, formal_drug_manuals_result, formal_compare_summary_main_result):
        ctx.processing_status = "形式审查结果总结开始"
        await write_iit_context(ctx)
        summary_task = self.better_llm().stream_call(sys_prompt=formal_summarize_prompt.format(
            formal_appendix_result=formal_appendix_result,
            formal_integrity_result=formal_integrity_result,
            formal_consistency_result=formal_consistency_result,
            formal_drug_manuals_result=formal_drug_manuals_result,
            formal_compare_summary_main_result=formal_compare_summary_main_result
        ), thinking_budget='low', temperature=0)
        result = ""
        async for chunk in summary_task:
            result += chunk
        ctx.processing_status = "形式审查结果总结结束"
        ctx.progress += 10
        await write_iit_context(ctx)
        return result

    async def _check_policy(self, policy_query, policy_result_content):
        task = self.llm().stream_call(
            sys_prompt=check_policy_prompt.format(policy_query=policy_query, policy_result_content=policy_result_content), thinking_budget='low'
        )
        result = ""
        async for chunk in task:
            result += chunk
        return result

    async def _get_queries(self, content):
        queries_schema = {
            "type": "OBJECT",
            "properties": {
                "pubmed_query": {
                    "type": "STRING",
                    "description": "提取方案摘要中体现该方案的价值或意义的描述，并形成相关查询"
                },
                "clinical_guidance_query": {
                    "type": "STRING",
                    "description": "提取IIT文档中的主题或疾病名称，特别是疾病分类、治疗方法等"
                },
                "policy_query": {
                    "type": "STRING",
                    "description": "提取文档在什么情况下用什么药物对什么疾病展开试验的完整信息"
                },
                "indication_query": {
                    "type": "STRING",
                    "description": "提取文档中提到的基础适应症名称"
                }
            },
            "required": [
                "pubmed_query",
                "clinical_guidance_query",
                "policy_query",
                "indication_query"
            ]
        }
        result = await self.llm()(
            sys_prompt=get_queries_prompt.replace("iit_text", str(content)),
            response_schema=queries_schema,
            response_mime_type="application/json",
            thinking_budget='low',
            temperature=0
        )
        return result
    
    async def expand_drug_name(self, drug: str) -> list:
        url = "http://172.188.121.85:7000/api/v1/alias/drug/"

        query_params = {
            "q": drug,
            "size": "1" 
        }

        headers = {
            "accept": "application/json"
        }

        print(f"正在发送 GET 请求到: {url} 参数: {query_params}")
        
        try:
            session = await self.get_http_session()
            async with session.get(url, params=query_params, headers=headers) as response:
                
                response.raise_for_status()
                
                response_data = await response.json()
                
                print(f"\n=== [{drug}] 接口返回结果 ===")
                print(json.dumps(response_data, indent=2, ensure_ascii=False))
                
                if response_data.get("code") == 0 and response_data.get("data") and response_data["data"][0].get("alias", []):
                    return response_data["data"][0].get("alias", [])
                else:
                    logger.warning(f"未找到别名，code: {response_data.get('code')}, message: {response_data.get('message')}, data: {response_data.get('data')}")
                    task = self.llm().stream_call(sys_prompt=expand_drug_prompt.format(missing_drug=drug), thinking_budget='low')
                    drug_list = ""
                    async for chunk in task:
                        drug_list += chunk
                    return [drug.strip() for drug in drug_list.split(",") if drug.strip()]

        except aiohttp.ClientError as e:
            raise Exception(f"接口请求失败: {str(e)}")
        except json.JSONDecodeError:
            raise Exception("接口返回的内容不是有效的JSON格式")
        except Exception as e:
            raise Exception(f"未知错误: {str(e)}")
    
async def upload_result(output_dir, language, ctx):
    from utils.azure.blob_client import upload_file
    review_type_cn = "形式审查" if ctx.category == "formal" else "科学审查" if ctx.category == "scientific" else "综合审查"
    review_type_en = "Administrative_Review" if ctx.category == "formal" else "Scientific_Review" if ctx.category == "scientific" else "General_Review"
    review_type = review_type_cn if language == "zh-CN" else review_type_en
    datetime_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d%H%M")
    title_str = ctx.title[:5]+'~'
    file_name = f"{output_dir}/{review_type}-{title_str}-{datetime_str}"
    md_content = ctx.content
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    md_path = f"{file_name}.md"
    docx_path = f"{file_name}.docx"
    pdf_path = f"{file_name}.pdf"
    zip_path = f"{file_name}.zip"
    logo_path="static/roche-logo.png"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    try:
        md_to_word(
            input_file_path=md_path,
            output_file_path=docx_path,
            logo_path=logo_path,
            format_type="chinese" if language == "zh-CN" else "english",
        )
        convert_md_to_pdf_iit(review_type=ctx.category, md_path=md_path, pdf_path=pdf_path, logo_path=logo_path)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(docx_path, arcname=os.path.basename(docx_path))
            z.write(pdf_path, arcname=os.path.basename(pdf_path))
    except Exception as e:
        logger.info(f"Failed to convert file: {str(e)}")
    logger.info(f"Output saved to {zip_path}")
    
    for attempt in range(3):
        try:
            # bucket temp
            res = upload_file(bucket="", object_key=f"{file_name}.zip", file_path=zip_path)
            if res: 
                logger.info(f"File {zip_path} uploaded successfully")
                ctx.url = f"https://noahdata.blob.core.windows.net/nudata/{file_name}.zip"
                break
        except (OSError, IOError, BlockingIOError) as e:
            logger.warning(f"Upload attempt {attempt + 1} failed with error: {str(e)}")
            if attempt < 2:  # Don't sleep on last attempt
                await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff: 5s, 10s
        except Exception as e:
            logger.error(f"Unexpected error during upload attempt {attempt + 1}: {str(e)}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    else:
        logger.error(f"Failed to upload {zip_path} after 3 attempts")
    if os.path.exists(docx_path):
        try:
            os.remove(docx_path)
            print(f"Successfully deleted the original docx file: {docx_path}")
        except Exception as delete_error:
            print(f"Warning: Failed to delete {docx_path}: {str(delete_error)}")
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            print(f"Successfully deleted the original pdf file: {pdf_path}")
        except Exception as delete_error:
            print(f"Warning: Failed to delete {pdf_path}: {str(delete_error)}")
    if os.path.exists(md_path):
        try:
            os.remove(md_path)
            print(f"Successfully deleted the original md file: {md_path}")
        except Exception as delete_error:
            print(f"Warning: Failed to delete {md_path}: {str(delete_error)}")

