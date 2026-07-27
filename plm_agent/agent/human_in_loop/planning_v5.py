import asyncio
import io
import os
import hashlib
import copy

import shutil
import time
import traceback
import json
import logging

from dataclasses import dataclass
from functools import partial
from datetime import datetime
from enum import Enum
from typing import List, Optional

from agent.core.preset import AgentPreset
from i18n import translate, resolve_language, normalize_planning_tool_name
from i18n.languages import normalize as _norm, DEFAULT_CODE, detect_language
from agent.human_in_loop.query import run_query
from agent.human_in_loop.utils import *
from agent.human_in_loop.constants import search_routing
from agent.human_in_loop.prompt import generate_reflection_prompt, generate_summary_prompt
from agent.explore.mindsearch_refer_agent_v3 import MindSearchReferAgentV3
from agent.explore.mindsearch_rewrite_agent_v4 import MindSearchRewriteAgentV4
from agent.explore.mindsearch_hitl_agent import MindSearchWebHitlAgent
from agent.explore.schema import ProcessingType

from llm.base_model import BaseLLM
from llm.composite_models import SlotFillingModels
from llm.deepseek_models import CompositeDeepseekChat
from lite_llm.composite_models import CompositeModel
from lite_llm.azure_openai import AzureOpenAI52, AzureOpenAI5
from lite_llm.azure_claude import AzureClaudeSonnet45
from lite_llm.openai_models import OpenAI52
from lite_llm.google_models import Gemini31Pro
from lite_llm.vertex_claude import VertexClaude45Sonnet
from lite_llm.azure_claude import AzureClaudeSonnet46
from tools.human_in_loop.planning.schema import *
from tools.human_in_loop.planning.schema_cn import *
from tools.human_in_loop.planning.prompt import *
from utils.human_in_loop.helpers import *
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.scholar.citation_formatter import CitationFormatter
from utils.clinical_utils.clean_args_typesense import clean_args_typesense
from utils.utils.attachment import AttachmentManager
from utils.core.prompt_fetcher import PromptFetcher

pt_fetcher = PromptFetcher()

logger = logging.getLogger(__name__)


@dataclass
class ToolRunContext:
    ret: dict
    body: dict
    prev_tool_uses: List[dict]
    total_feedback: List
    state: dict
    final_question: str
    feedback: str
    hitl_mode: str
    download_link: bool
    object_path: str
    encoded_object_path: str
    attachments: List[dict]
    parent_id: str # 知识库文件夹id
    concurrent: bool = False
    commit_shared_state: bool = True
    base_prev_tool_uses: Optional[List[dict]] = None

class MessageType(str, Enum):
    """消息类型"""
    CHAT = 'chat'
    SIMPLE_THOUGHT = 'simpleThought'
    STATUS_UPDATE = 'statusUpdate'
    PLAN_UPDATE = 'planUpdate'
    THOUGHT = 'thought'
    SUMMARY = 'summary'
    REFERENCE = 'reference'

class TaskStatus(str, Enum):
    """任务状态"""
    TODO = 'todo'
    DOING = 'doing'
    DONE = 'done'
    ERROR = 'error'

class AgentStatus(str, Enum):
    """Agent状态"""
    RUNNING = 'running'
    WAITING = 'waiting'
    STOPPED = 'stopped'
    WAITING_FEEDBACK = 'waitingFeedback'

# 这些工具需要串行执行，因为它们之间有依赖关系，其他工具都可以并行
SERIAL_TOOL_NAMES = {'Plan-Sequence', 'Generate-Summary', 'Self-Reflection', 'General-Inference', 'Medical-Diagnosis'}
# SERIAL_TOOL_NAMES = {'Plan-Sequence', 'Generate-Summary', 'Self-Reflection', 'General-Inference', 'Medical-Diagnosis', "NCCN-Guidelines","Medical-Diagnosis","General-Inference","PubMed-Search","Medical-Search","Web-Search","Finance-Search","Patent-Search","News-Search","Drug-Manual-Search","Clinical-Guideline-Search","Clinical-Trial-Result-Analysis","Drug-Analysis","Catalyst-Event-Analysis","Document-Read","Sandbox-Execution"}
ENABLE_PARALLEL_PLANNING = True


def _group_into_batches(plan: List[dict], start_step: int) -> List[List[int]]:
    """Split the remaining plan into serial and parallel execution batches."""
    batches: List[List[int]] = []
    current_batch: List[int] = []

    for step_idx in range(max(start_step - 1, 0), len(plan)):
        tool_name = plan[step_idx].get('tool', '')
        if tool_name in SERIAL_TOOL_NAMES:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            batches.append([step_idx])
        else:
            current_batch.append(step_idx)

    if current_batch:
        batches.append(current_batch)

    return batches

_DEFAULT_MAX_STEPS_INCREMENT = 4
_DEFAULT_MAX_STEPS_SOFT_MAX = 11
_DEFAULT_MAX_STEPS_HARD_MAX = 14
_DEFAULT_REWRITE = True
tool_mapping = {
    # "NCCN-Guidelines": {"schema": NCCNGuidelinesInputSchema, "prompt": nccn_slot_filling_prompt},
    "Medical-Diagnosis": {"schema": GeneralInferenceInputSchema, "prompt": partial(pt_fetcher.get, 'general_inference_slot_filling_prompt', general_inference_slot_filling_prompt)},
    "General-Inference": {"schema": GeneralInferenceInputSchema, "prompt": partial(pt_fetcher.get, 'general_inference_slot_filling_prompt', general_inference_slot_filling_prompt)},
    # "PubMed-Search": {"schema": MedicalSearchInputSchema, "prompt": medical_search_slot_filling_prompt},
    "Medical-Search": {"schema": MedicalSearchInputSchema, "prompt": partial(pt_fetcher.get, 'medical_search_slot_filling_prompt', medical_search_slot_filling_prompt)},
    "Web-Search": {"schema": WebSearchInputSchema, "prompt": partial(pt_fetcher.get, 'web_search_slot_filling_prompt', web_search_slot_filling_prompt)},
    "Finance-Search": {"schema": FinanceSearchInputSchema, "prompt": partial(pt_fetcher.get, 'finance_search_slot_filling_prompt', finance_search_slot_filling_prompt)},
    "Patent-Search": {"schema": PatentSearchInputSchema, "prompt": partial(pt_fetcher.get, 'patent_search_slot_filling_prompt', patent_search_slot_filling_prompt)},
    "News-Search": {"schema": NewsSearchInputSchema, "prompt": partial(pt_fetcher.get, 'news_search_slot_filling_prompt', news_search_slot_filling_prompt)},
    "Drug-Manual-Search": {"schema": DrugManualSearchInputSchema, "prompt": partial(pt_fetcher.get, 'drug_manual_search_slot_filling_prompt', drug_manual_search_slot_filling_prompt)},
    "Clinical-Guideline-Search": {"schema": ClinicalGuidelineSearchInputSchema, "prompt": partial(pt_fetcher.get, 'clinical_guideline_search_slot_filling_prompt', clinical_guideline_search_slot_filling_prompt)},
    "Clinical-Trial-Result-Analysis": {"schema": ClinicalResultsInputSchema, "prompt": partial(pt_fetcher.get, 'clinical_trial_results_slot_filling_prompt', clinical_trial_results_slot_filling_prompt)},
    "Drug-Analysis": {"schema": DrugCompetitionLandscapeInputSchema, "prompt": partial(pt_fetcher.get, 'drug_competition_landscape_slot_filling_prompt', drug_competition_landscape_slot_filling_prompt)},
    "Catalyst-Event-Analysis": {"schema": CatalystSearchInputSchema, "prompt": partial(pt_fetcher.get, 'catalyst_search_slot_filling_prompt', catalyst_search_slot_filling_prompt)},
    "Document-Read": {"schema": DocumentSearchInputSchema, "prompt": partial(pt_fetcher.get, 'document_search_slot_filling_prompt', document_search_slot_filling_prompt)},
    # "Sandbox-Execution": {"schema": SandboxExecutionInputSchema, "prompt": partial(pt_fetcher.get, 'sandbox_execution_slot_filling_prompt', sandbox_execution_slot_filling_prompt)},
}

tool_mapping_cn = {
    # "NCCN-Guidelines": {"schema": NCCNGuidelinesInputSchema, "prompt": nccn_slot_filling_prompt},
    "Medical-Diagnosis": {"schema": GeneralInferenceInputSchemaCn, "prompt": partial(pt_fetcher.get, 'general_inference_slot_filling_prompt', general_inference_slot_filling_prompt)},  # Translated from "诊疗问题"
    "General-Inference": {"schema": GeneralInferenceInputSchemaCn, "prompt": partial(pt_fetcher.get, 'general_inference_slot_filling_prompt', general_inference_slot_filling_prompt)},
    # "PubMed-Search": {"schema": MedicalSearchInputSchemaCn, "prompt": medical_search_slot_filling_prompt},
    "Medical-Search": {"schema": MedicalSearchInputSchemaCn, "prompt": partial(pt_fetcher.get, 'medical_search_slot_filling_prompt', medical_search_slot_filling_prompt)},
    "Web-Search": {"schema": WebSearchInputSchemaCn, "prompt": partial(pt_fetcher.get, 'web_search_slot_filling_prompt', web_search_slot_filling_prompt)},
    "Finance-Search": {"schema": FinanceSearchInputSchema, "prompt": partial(pt_fetcher.get, 'finance_search_slot_filling_prompt', finance_search_slot_filling_prompt)},
    "Patent-Search": {"schema": PatentSearchInputSchema, "prompt": partial(pt_fetcher.get, 'patent_search_slot_filling_prompt', patent_search_slot_filling_prompt)},
    "News-Search": {"schema": NewsSearchInputSchema, "prompt": partial(pt_fetcher.get, 'news_search_slot_filling_prompt', news_search_slot_filling_prompt)},
    "Drug-Manual-Search": {"schema": DrugManualSearchInputSchemaCn, "prompt": partial(pt_fetcher.get, 'drug_manual_search_slot_filling_prompt', drug_manual_search_slot_filling_prompt)},
    "Clinical-Guideline-Search": {"schema": ClinicalGuidelineSearchInputSchemaCn, "prompt": partial(pt_fetcher.get, 'clinical_guideline_search_slot_filling_prompt', clinical_guideline_search_slot_filling_prompt)},
    "Clinical-Trial-Result-Analysis": {"schema": ClinicalResultsInputSchemaCn, "prompt": partial(pt_fetcher.get, 'clinical_trial_results_slot_filling_prompt', clinical_trial_results_slot_filling_prompt)},
    "Drug-Analysis": {"schema": DrugCompetitionLandscapeInputSchemaCn, "prompt": partial(pt_fetcher.get, 'drug_competition_landscape_slot_filling_prompt', drug_competition_landscape_slot_filling_prompt)},
    "Catalyst-Event-Analysis": {"schema": CatalystSearchInputSchemaCn, "prompt": partial(pt_fetcher.get, 'catalyst_search_slot_filling_prompt', catalyst_search_slot_filling_prompt)},
    "Document-Read": {"schema": DocumentSearchInputSchema, "prompt": partial(pt_fetcher.get, 'document_search_slot_filling_prompt', document_search_slot_filling_prompt)},
    # "Sandbox-Execution": {"schema": SandboxExecutionInputSchemaCn, "prompt": partial(pt_fetcher.get, 'sandbox_execution_slot_filling_prompt', sandbox_execution_slot_filling_prompt)},
}

class PlanningAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekChat(max_retries=0, timeout=15, first_chunk_timeout=10)
    plan_llm: BaseLLM = CompositeModel([VertexClaude45Sonnet(), AzureClaudeSonnet45(), AzureOpenAI52(), AzureOpenAI5()])
    summary_llm: BaseLLM = CompositeModel([AzureClaudeSonnet46(), AzureClaudeSonnet45(), AzureOpenAI52(), AzureOpenAI5()])
    gpt_llm: CompositeModel = CompositeModel([AzureOpenAI52(), OpenAI52(), AzureOpenAI5()])
    plan_extraction_llm: BaseLLM = SlotFillingModels(max_retries=0, timeout=45, first_chunk_timeout=10)
    slot_filling_llm: BaseLLM = SlotFillingModels(max_retries=0, timeout=45, first_chunk_timeout=10)
    citation_formatter: CitationFormatter = CitationFormatter()
    attachment_manager: AttachmentManager = AttachmentManager()
    backup_llms: List[BaseLLM] = []
    output_dir: str = "outputs/"
    two_step: bool = True
    language: str = 'en-US'
    thread_id: str = ''
    stopped: bool = False
    auto_run_stopped: bool = False
    database_rl: bool = False
    api_mode: bool = False
    max_steps_increment: int = _DEFAULT_MAX_STEPS_INCREMENT
    max_steps_soft_max: int = _DEFAULT_MAX_STEPS_SOFT_MAX
    max_steps_hard_max: int = _DEFAULT_MAX_STEPS_HARD_MAX
    rewrite: bool = _DEFAULT_REWRITE
    history_attachments: list = []

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], planning_task: dict = {}, feedback: str = '', hitl_mode:str='', **kwargs):
        self.max_steps_increment = _DEFAULT_MAX_STEPS_INCREMENT
        self.max_steps_soft_max = _DEFAULT_MAX_STEPS_SOFT_MAX
        self.max_steps_hard_max = _DEFAULT_MAX_STEPS_HARD_MAX
        self.rewrite = _DEFAULT_REWRITE
        original_question = planning_task.get('question', user_prompt) or '' # 用户原始问题，没经过rewrite
        rewrite_question = planning_task.get('rewrite_question', '') # 被 LLM 重写后的问题
        rewrite_results = planning_task.get("rewrite_results", []) # 重写的结果
        final_question = rewrite_question or original_question # 最终问题，可能是原始问题，也可能是被 LLM 重写后的问题
        # 给用户问题添加附件
        self.api_mode = kwargs.get('api_mode', False)
        files = planning_task.get('files', []) # 用户上传的文件
        parent_id = planning_task.get('parent_id', '') # 知识库文件夹id
        self.history_attachments = kwargs.get('history_files', [])
        # 合并用户上传的文件和知识库文件
        attachments = []
        if files:
            attachments = self.attachment_manager.fetch_attachments(files, False)
        folders = []
        if parent_id:
            folders = self.attachment_manager.fetch_folders([parent_id])

        if self.api_mode:
            self.rewrite = False
            self.max_steps_soft_max = 10
            self.max_steps_hard_max = 12
        if not self.rewrite:
            rewrite_question = final_question
        body = {
            "history_messages": history_messages,
            "user_prompt": final_question
        }
        download_link = kwargs.get('download_link', True)
        user = planning_task.get('user', 'unknown')
        task_id = planning_task.get('id', 'unknown')
        self.thread_id = planning_task.get('thread_id', 'unknown')
        question_prefix = ''.join(c if not c.isascii() else (c if c.isalnum() or c in ['_', '-', '.'] else '_') for c in original_question[:10])
        editable = planning_task.get('editable', None)
        
        safe_prefix = urllib.parse.quote(question_prefix)
        object_path = f"planning/{user}/{task_id}/{question_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        encoded_object_path = f"planning/{user}/{task_id}/{safe_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        self.output_dir = f"outputs/" + object_path
        approve = kwargs.get('approve', None)
        should_replan = (approve is False)
        past_feedback = planning_task.get('feedback', [])
        total_feedback = past_feedback + [feedback] if feedback else past_feedback
        if total_feedback or should_replan:
            replan_feedback = ['User wants to replan'] if should_replan else []
            combo_prompt = {'original_user_prompt': final_question, 'additional_user_prompt': total_feedback + replan_feedback}
            body['user_prompt'] = json.dumps(combo_prompt, separators=(',', ': '), ensure_ascii=False)
        self.language = _norm(planning_task.get('language', '') or kwargs.get('language', '')
                              or kwargs.get('params', {}).get('language', ''))
        if not self.language or self.language == DEFAULT_CODE:
            self.language = detect_language(original_question)
        plan = planning_task.get('plan', [])
        current_tool = {}
        current_step = planning_task.get('current_step', 0)
        if not current_step and plan:
            current_step = 1
        hitl_mode = hitl_mode or planning_task.get('hitl_mode', '') or 'never'
        prev_tool_uses = planning_task.get('tool_uses', [])
        if prev_tool_uses and not prev_tool_uses[-1].get('result', '') and prev_tool_uses[-1].get('tool', '') != 'User-Question':
            current_tool = prev_tool_uses[-1]
        if not current_tool:
            if plan and current_step <= len(plan):
                current_tool = plan[current_step-1].copy()
        should_run = bool(plan and not should_replan) # user confirmation of tool use
        ret = {'tool_uses': [], 'type': MessageType.CHAT, "agent": "planning", "hitl_mode": hitl_mode, 'sender': 'assistant',
               "current_step": current_step, "current_tool": current_tool, 'feedback': total_feedback}
        if 'language' not in planning_task:
            ret['language'] = self.language
        if current_tool and current_tool.get('status', TaskStatus.ERROR) != TaskStatus.ERROR:
            async for _ret in send_confirm_tool(ret, feedback, should_run):
                yield _ret
        elif not plan:
            if feedback != '' and editable is not False:
                # use same chunk id
                ret['chunkIdx'] = len(rewrite_results) - 1
                ret['message'] = feedback
                ret['stepQuestion'] = rewrite_results[-1]
                async for _ret in send_agent_status_update(ret, AgentStatus.RUNNING):
                    yield _ret
                ret.pop('stepQuestion')

            elif editable is None:
                ret['chunkIdx'] = len(rewrite_results) - 1
                async for _ret in send_user_message(ret, final_question, attachments, folders):
                    yield _ret
            ret.pop('message', None)
        if hitl_mode == 'never':
            should_run = True
        ret['saveChat'] = False
        
        if self.language == 'zh-CN':
            planning_schema = PlanningInputSchemaCn
            tool_sequence_extraction_template = pt_fetcher.get('tool_sequence_extraction_template_cn', tool_sequence_extraction_template_cn)
        else:
            planning_schema = PlanningInputSchema
            tool_sequence_extraction_template = pt_fetcher.get('tool_sequence_extraction_template_en', tool_sequence_extraction_template_en)

        if not plan or len(plan) <= 1: # if current_tool != plan[0].get('tool')
            # try rewrite user original question, first rewrite

            chunk_idx = len(rewrite_results)

            if not rewrite_question:
                rewrite_body = {
                    "user_prompt": final_question,
                    "history_messages": copy.deepcopy(history_messages),
                    "agent": "mindsearchrewrite",
                    "params": {
                        "language": self.language,
                        "feedbacks": total_feedback,
                        "rewrites": rewrite_results,
                        #"tool_use_context": tool_history_to_prompt(prev_tool_uses),
                        "files": files,
                        "parent_id": parent_id,
                    }
                }
                agent = MindSearchRewriteAgentV4()
                generator = agent.start(**rewrite_body)
                ret['type'] = MessageType.SIMPLE_THOUGHT
                ret['chunkIdx'] = chunk_idx
                async for chunk in generator:
                    if not chunk:
                        continue
                    if type(chunk) == dict:
                        latest_chunk = chunk.get('content', '')
                    elif type(chunk) == str:
                        latest_chunk = chunk
                    ret['message'] = latest_chunk
                    yield ret
                if self.stopped:
                    return

                # Debug log to capture the actual structure of ret before accessing 'message'
                logger.info(f"DEBUG: ret keys before accessing 'message': {ret.keys()}, ret.get('message'): {ret.get('message', 'KEY_NOT_FOUND')}")
                if 'message' not in ret:
                    logger.error(f"DEBUG: Full ret object before error: {json.dumps(ret, default=str, ensure_ascii=False)}")
                
                rewrite_result = json.loads(ret['message'])
                ret['chunkIdx'] = chunk_idx
                if rewrite_result['processing_type'] == ProcessingType.REWRITE.value:
                    rewrite_question = rewrite_result['content']
                    body['user_prompt'] = rewrite_question
                    ret['rewrite_question'] = rewrite_question
                    total_feedback = ret['feedback'] = []
                    # Rewrite Hide: If we want to hide rewrite result, we need to wait one second for frontend udate.
                    # await asyncio.sleep(1) 
                    async for _ret in send_editable_rewrite_question(ret, rewrite_question, True):
                        yield _ret
                    return
                else:
                    ret['rewrite_result'] = rewrite_result['content']
                    ret['message'] = rewrite_result['content']
                    ret['type'] = MessageType.STATUS_UPDATE
                    ret['agentStatus'] = AgentStatus.WAITING_FEEDBACK
                    async for _ret in send_message_and_save(ret):
                        yield _ret

            if rewrite_question:
                logger.info(f'Feedback rewrite question: {rewrite_question}')
                # Rewrite Hide: this condition is to display rewrite result
                ret.pop('chunkIdx', None)
                ret['type'] = MessageType.PLAN_UPDATE
                ret['current_step'] = current_step = 1
                plan_reason = translate("planning.plan_reason", resolve_language(self.language))
                ret['current_tool'] = {"tool": "Plan-Sequence", 'status': TaskStatus.DOING, 'startedAt': int(time.time()), "reason": plan_reason}
                ret['plan'] = plan = [ret['current_tool']]
                async for _ret in send_message_and_save(ret):
                    yield _ret

                if approve is not True or not prev_tool_uses or prev_tool_uses[-1]['tool'] != 'Plan-Sequence' or not prev_tool_uses[-1]['result']:
                    ret['type'] = MessageType.CHAT
                    #planning_prompt = build_planning_prompt(self.language, body['user_prompt'], prev_tool_uses, plan, total_feedback, MAX_STEPS=MAX_STEPS_INCREMENT)
                    claude_plan_system_prompt, planning_prompt = build_planning_prompt_v2(self.language, body['user_prompt'], MAX_STEPS=self.max_steps_increment)
                    # tanght-learn-llm 让AI生成Plan文本
                    # response_stream = self.plan_llm.stream_call(user_prompt=planning_prompt)
                    input = history_messages + [{"role": "user", "content": planning_prompt}]
                    response_stream = self.plan_llm.stream_generate(
                        input=input,
                        sys_prompt=claude_plan_system_prompt,
                        reasoning={"effort": "medium"},
                    )
                    async for chunk in self._task_with_heartbeat(response_stream, interval=1, stream=True):
                        if not chunk: continue
                        ret['message'] = chunk
                        yield ret
                    tool_use = ret['current_tool'].copy()
                    tool_use['result'] = ret['message']
                    if prev_tool_uses: 
                        if prev_tool_uses[-1]['tool'] != 'Plan-Sequence':
                            prev_tool_uses.append(tool_use)
                        else:
                            prev_tool_uses[-1]['result'] = ret['message']
                        ret['tool_uses'] = prev_tool_uses
                    else:
                        prev_tool_uses.append(tool_use)
                        ret['tool_uses'] = prev_tool_uses
                    async for _ret in send_message_and_save(ret):
                        yield _ret
                        
                    ret.pop('message', None)
                    ret.pop('chunkIdx', '')
                
                noah_plan = chunk if approve is not True else prev_tool_uses[-1]['result']
                save_to_file(noah_plan, self.output_dir + "/process", f"{current_step-1}_Plan-Sequence_NoahAI.md")
                planning_text = tool_sequence_extraction_template.format(noah_plan=noah_plan)
                planning_format = get_openai_json_schema_v3(planning_schema)
                plan[current_step-1]['status'] = TaskStatus.DONE
                current_step += 1
                # tanght-learn-llm 根据plan文本，提取工具使用步骤、选择该工具背后的原因以及相应的查询参数描述 输入“文本” 返回 [{'tool': 'ToolName', 'reason': 'Reason', 'query_params': 'QueryParams'}]
                plan += (await self.extract_plan(planning_text, current_step, planning_format))
                ret['current_step'] = current_step
                current_tool = plan[current_step-1]
                ret['plan'] = plan
                ret['type'] = MessageType.PLAN_UPDATE
                prev_tool_uses[-1]['status'] = TaskStatus.DONE
                ret['tool_uses'] = prev_tool_uses
                async for _ret in send_message_and_save(ret):
                    yield _ret
            
        ret.pop("plan", None)
        
        if not rewrite_question:
            # just rewrite and need user waiting
            return

        if not plan:
            ret["error"] = "Planning failed"
            yield ret
            return
        
        if current_step-1 >= len(plan):
            ret["error"] = "All steps completed"
            yield ret
            return
        
        if not current_tool:
            current_tool = plan[current_step-1].copy()
        
        if 'params' not in current_tool and current_tool['tool'] not in ['Generate-Summary', 'Self-Reflection', 'User-Question', 'Plan-Sequence', 'General-Inference']:
            await self._fill_and_clean_tool_params(body, current_tool, prev_tool_uses, feedback, final_question, current_step)
        
        ret.pop('rewrite_question', None)
        ret.pop('rewrite_result', None)
        ret['current_tool'] = current_tool
        
        # 以上是 问题重写 的逻辑，大概是吧...，等我搞定并发逻辑再处理上面的代码
        
        # 准备在这里进行并发
        # Plan: [Plan-Sequence] → [Tool1, Tool2, Tool3] → [Self-Reflection] → [Tool4, Tool5] → [Generate-Summary]
        #        ↓                ↓                         ↓                   ↓                  ↓
        # 执行:  串行批次1        并行批次2                 串行批次3           并行批次4          串行批次5

        try:
            while should_run:
                batches = _group_into_batches(plan, current_step)
                if not batches:
                    break

                for batch in batches:
                    if ENABLE_PARALLEL_PLANNING and len(batch) > 1:
                        state = {
                            'current_step': current_step,
                            'current_tool': current_tool,
                            'plan': plan,
                            'should_run': should_run,
                            'approve': approve,
                        }
                        context = ToolRunContext(
                            ret=ret,
                            body=body,
                            prev_tool_uses=prev_tool_uses,
                            total_feedback=total_feedback,
                            state=state,
                            final_question=final_question,
                            feedback=feedback,
                            hitl_mode=hitl_mode,
                            download_link=download_link,
                            object_path=object_path,
                            encoded_object_path=encoded_object_path,
                            attachments=attachments,
                            parent_id=parent_id,
                            concurrent=True,
                        )
                        async for _ret in self._run_concurrent_batch(batch, context):
                            yield _ret
                        current_step = state['current_step']
                        current_tool = state['current_tool']
                        plan = state['plan']
                        should_run = state['should_run']
                        if state.get('exit'):
                            should_run = False
                            break
                        if not should_run:
                            break
                        continue

                    hit_self_reflection = False
                    while should_run and (current_step - 1) in batch:
                        running_tool_name = current_tool.get('tool', '')
                        async for _ret in send_agent_status_update(ret, AgentStatus.RUNNING):
                            yield _ret
                        state = {
                            'current_step': current_step,
                            'current_tool': current_tool,
                            'plan': plan,
                            'should_run': should_run,
                            'approve': approve,
                        }
                        context = ToolRunContext(
                            ret=ret,
                            body=body,
                            prev_tool_uses=prev_tool_uses,
                            total_feedback=total_feedback,
                            state=state, # 为了在 _run_single_tool 中能修改 state，所以把这些变量包裹在 state中，仅此而已，没有其他意义
                            final_question=final_question,
                            feedback=feedback,
                            hitl_mode=hitl_mode,
                            download_link=download_link,
                            object_path=object_path,
                            encoded_object_path=encoded_object_path,
                            attachments=attachments,
                            parent_id=parent_id,
                        )
                        async for _ret in self._run_single_tool(context):
                            yield _ret
                        current_step = state['current_step']
                        current_tool = state['current_tool']
                        plan = state['plan']
                        should_run = state['should_run']
                        if state.get('exit'):
                            should_run = False
                            break
                        if running_tool_name == 'Self-Reflection':
                            hit_self_reflection = True
                            break
                    if hit_self_reflection or not should_run:
                        break
                if not should_run:
                    break
        finally:
            has_error = any(s.get('status') == TaskStatus.ERROR for s in plan)
            if has_error or current_step-1 >= len(plan):
                ret['type'] = MessageType.STATUS_UPDATE
                ret['agentStatus'] = AgentStatus.STOPPED
                if 'taskStart' in planning_task:
                    ret['taskStart'] = planning_task['taskStart']
                ret.pop('current_tool', None)
            else:
                ret['type'] = MessageType.STATUS_UPDATE
                ret['agentStatus'] = AgentStatus.WAITING
            async for _ret in send_message_and_save(ret):
                yield _ret

    async def _fill_and_clean_tool_params(self, body, current_tool, prev_tool_uses, feedback, final_question, current_step):
        """填充并清理工具参数"""
        # tanght-learn-llm 将 current_tool 的 query_params(这是一个文本) 转换为 dict (每个tool有自己需要的dict结构)
        # current_tool['query_params'] 是文本
        # current_tool['params'] 是一个dict对象
        # 让 AI 从 current_tool['query_params'] 生成 current_tool['params']
        tool_filling_msg_json = await function_call_with_retry(
            self.tool_slot_filling, body, current_tool, 
            data=prev_tool_uses, feedback=feedback
        )
        
        params_dict = {"original_params": tool_filling_msg_json.copy()}
        tool_filling_msg_json_cleaned = None
        default_location = False
        
        if current_tool['tool'] in ["Clinical-Trial-Result-Analysis", "Catalyst-Event-Analysis"]:
            tool_filling_msg_json_cleaned = clean_args_typesense(tool_filling_msg_json, tool=current_tool['tool'])
        elif current_tool['tool'] == "Drug-Analysis":
            if not tool_filling_msg_json.get('location', []):
                default_location = True
            tool_filling_msg_json_cleaned = clean_args_typesense(tool_filling_msg_json, citeline=True, tool=current_tool['tool'])
        
        params_dict["matched_params"] = tool_filling_msg_json_cleaned or tool_filling_msg_json
        
        try:
            irrelevant_values = await self.llm_clean(params_dict["matched_params"], final_question)
            for iv in irrelevant_values:
                param = iv.get('param_name', '')
                value = iv.get('value', '')
                if param in ['location', 'locations', 'id']:
                    continue
                if param in params_dict["matched_params"] and value in params_dict["matched_params"][param]:
                    print('removed irrelevant value:', param, value)
                    if type(params_dict["matched_params"][param]) == list:
                        params_dict["matched_params"][param].remove(value)
                    if not params_dict["matched_params"][param]:
                        params_dict["matched_params"].pop(param, None)
        except Exception as e:
            logger.error(f"Error occurred while cleaning params: {e}")
        
        if default_location:
            logger.info(f"default_location: {default_location}")
            params_dict['matched_params']['default_location'] = True
        
        save_to_file(params_dict, self.output_dir + '/process', f"{current_step-1}_{current_tool['tool']}_params.json")
        current_tool['params'] = params_dict["matched_params"]

    async def tool_slot_filling(self, body, current_tool, data=None, feedback=""):
        tool_map = tool_mapping_cn if self.language.lower() == 'zh-CN' else tool_mapping
        tool_name = current_tool['tool']
        tool_info = tool_map[tool_name]
        original_question_and_feedback = body['user_prompt']
        tool_info_prompt = tool_info.get('prompt', partial(lambda x: x, ''))()
        planning_format = get_openai_json_schema_v3(tool_info['schema'])
        previous_tool_result = ''
        if data:
            if type(data) == list:
                result = data[-1].get('result','')
                if type(result) == dict and 'content' in result and result['content']:
                    result = result['content']
            previous_tool_result = result
        current_tool_query_params = f"{query_params}" if (query_params:=current_tool.get('query_params','')) else ''
        current_tool_reason = ''
        original_question_prompt = ''
        if 'reason' in current_tool and current_tool['reason'] and current_tool['tool'] not in ['Drug-Analysis', 'Catalyst-Event-Analysis', 'Clinical-Trial-Result-Analysis']:
            # remove previous tool result
            previous_tool_result = ''
            current_tool_reason = f"The goal/reason for choosing this tool: {current_tool['reason']}"
            if not feedback: 
                original_question_prompt = f'(to answer the original user question: {original_question_and_feedback})'
        feedback_prompt = f'Consider the user feedback: {feedback}' if feedback else ''
        tool_slot_filling_prompt = tool_slot_filling_template.format(
            tool_info_prompt=tool_info_prompt,
            previous_tool_result=previous_tool_result,
            current_tool_query_params=current_tool_query_params,
            current_tool_reason=current_tool_reason,
            original_question_prompt=original_question_prompt,
            feedback_prompt=feedback_prompt,
        )
        function_name = planning_format[0]['function']['name']
        # tanght-learn-llm 将 query_params 字符串变成 dict （planning_format）
        response = await self.slot_filling_llm(user_prompt=tool_slot_filling_prompt, tools=planning_format, tool_choice={"type": "function", "function": {"name": function_name}}, temperature=0.3, max_tokens=8192)
        return response
        
    async def extract_plan(self, planning_text, current_step = 0, planning_format = None):
        kwargs = {}
        if planning_format:
            function_name = planning_format[0]['function']['name']
            kwargs['tool_choice'] = {"type": "function", "function": {"name": function_name}}
            # tanght-learn-llm 根据plan文本，提取工具使用步骤、选择该工具背后的原因以及相应的查询参数描述 输入“文本” 返回 [{'tool': 'ToolName', 'reason': 'Reason', 'query_params': 'QueryParams'}]
            result = await function_call_with_retry(self.plan_extraction_llm, user_prompt=planning_text, tools=planning_format, planning=True, temperature=0.3, max_tokens=8192, **kwargs)
        sequence = result.get('planned_sequence', [])[:self.max_steps_increment+1]
        # Normalize tool names: extraction LLM may output translated names
        # (e.g. "의학 검색") instead of English identifiers ("Medical-Search")
        for step in sequence:
            step['tool'] = normalize_planning_tool_name(step.get('tool', ''))
        if self.max_steps_increment>1 and sequence and sequence[-1].get('tool', '') not in ['Self-Reflection', 'Generate-Summary', 'General-Inference', 'Medical-Diagnosis']:
            reflection_reason = translate("planning.reflection_reason", resolve_language(self.language))
            sequence.append({'tool': 'Self-Reflection', 'status': TaskStatus.TODO, 'startedAt': int(time.time()), 'reason': reflection_reason})
        for step in sequence:
            step['status'] = TaskStatus.TODO
            step['startedAt'] = int(time.time())
        if sequence:
            sequence[0]['status'] = TaskStatus.DOING
        return sequence
    
    async def _task_with_heartbeat(self, gen, interval: float = 0.3, stream=False):
        r"""
        Since fetch web page contents may cost very long time. Only yield when new data is available to avoid unnecessary returns.
        """
        buffer = io.StringIO()
        newest_chunk = None
        start_time = time.time()
        last_pos = 0  # 记录上次已返回的 buffer 位置
        # 记录上一次的hash值，兼容增量，全量返回
        newest_hash = hashlib.sha256("".encode()).hexdigest()  
        async def write_buffer():
            nonlocal newest_chunk
            async for chunk in gen:
                if not chunk:
                    continue
                if stream:
                    buffer.write(chunk)
                else:
                    if type(chunk) == str:
                        newest_chunk = chunk
                    elif type(chunk) == dict:
                        newest_chunk = chunk
        task = asyncio.create_task(write_buffer())
        # shielded = asyncio.shield(task)

        while not task.done():
            if self.stopped:
                task.cancel()
                logger.info("Task cancelled due to stop signal.")
                break
            if stream:
                current_value = buffer.getvalue()
                if len(current_value) > last_pos:
                    yield current_value
                    last_pos = len(current_value)
            elif newest_chunk:
                temp_newest_str = str(newest_chunk)
                temp_newest_hash = hashlib.sha256(temp_newest_str.encode()).hexdigest()
                if temp_newest_hash != newest_hash:
                    newest_hash = temp_newest_hash
                    yield newest_chunk
            await asyncio.sleep(interval)
        # await shielded
        await task
        end_time = time.time()
        if stream:
            current_value = buffer.getvalue()
            if len(current_value) > last_pos:
                yield current_value
        elif newest_chunk:
            temp_newest_str = str(newest_chunk)
            temp_newest_hash = hashlib.sha256(temp_newest_str.encode()).hexdigest()
            if temp_newest_hash != newest_hash:
                yield newest_chunk
        logger.info(f"[_task_with_heartbeat]{callable} cost time total {end_time - start_time}s")
    
    async def _run_single_tool(self, context: ToolRunContext):
        """执行单个工具"""
        ret = context.ret # 读写
        body = context.body
        prev_tool_uses = context.prev_tool_uses # 读写
        total_feedback = context.total_feedback
        state = context.state # 读写
        final_question = context.final_question
        feedback = context.feedback
        hitl_mode = context.hitl_mode
        download_link = context.download_link
        object_path = context.object_path
        encoded_object_path = context.encoded_object_path
        attachments = context.attachments
        parent_id = context.parent_id
        current_step = state['current_step'] # 读写
        current_tool = state['current_tool'] # 读写
        plan = state['plan'] # 读写
        approve = state['approve']
        tool_name = current_tool.get('tool', '')
        if not tool_name:
            state['should_run'] = False
            return

        ret['type'] = MessageType.CHAT

        try:
            # 填写 current_tool['params'] 字段, 并发的时候 current_tool 没有 params 字段，所以要在这里 fill
            if 'params' not in current_tool and tool_name not in ['Generate-Summary', 'Self-Reflection', 'User-Question', 'Plan-Sequence', 'General-Inference']:
                await self._fill_and_clean_tool_params(body, current_tool, prev_tool_uses, feedback, final_question, current_step)
        except Exception as e:
            logger.error(f'noahai_et_PV9bO2mgTQ {str(e)}')

        if tool_name == 'Self-Reflection':
            async for _ret in self.self_reflection(ret, final_question, prev_tool_uses, current_tool, current_step, plan, total_feedback, approve):
                yield _ret
            if self.auto_run_stopped:
                state.update({
                    'plan': plan,
                    'current_tool': current_tool,
                    'current_step': current_step,
                    'should_run': False,
                    'exit': True,
                })
                return
            plan = ret['plan']
        else:
            stream = False
            file_map = {}  # sandbox file markers for Generate-Summary
            if tool_name == 'Generate-Summary':
                summary_prompt = build_summary_prompt(body['user_prompt'], current_tool, prev_tool_uses)
                tool_results = tool_history_to_prompt(prev_tool_uses, is_summary=True)
                tool_results, file_map = extract_sandbox_file_markers(tool_results)
                summary_prompt = generate_summary_prompt(
                    final_question, tool_results, file_map=file_map
                )
                # tanght-learn-llm 总结
                # generator = self.summary_llm.stream_call(user_prompt=summary_prompt)
                input = body['history_messages'] + [{"role": "user", "content": summary_prompt}]
                generator = self.summary_llm.stream_generate(
                    input=input,
                    sys_prompt="You are a helpful assistant.",
                    reasoning={"effort": "medium"},
                    max_tokens=32 * 1024,
                    temperature=1,
                )
                stream = True
            elif tool_name in ['General-Inference', 'Medical-Diagnosis']:
                inference_prompt = build_inference_prompt(body['user_prompt'], current_tool, prev_tool_uses)
                instruction, inference_prompt = build_inference_prompt_v2(body['user_prompt'], current_tool, self.language, prev_tool_uses)
                input = body['history_messages'] + [{"role": "user", "content": inference_prompt}]
                generator = self.gpt_llm.stream_generate(
                    input=input,
                    sys_prompt=instruction,
                    reasoning={"effort": "high"},
                )
                stream = True
            elif tool_name in ['Medical-Search', 'Web-Search', 'Finance-Search', 'Patent-Search', 'News-Search', 'Drug-Manual-Search', 'Clinical-Guideline-Search', 'Document-Read']:
                search_prompt = build_search_prompt(body['user_prompt'], current_tool, [])
                agent, agent_name = search_routing.get(tool_name, (MindSearchWebHitlAgent, "mindsearch"))
                agent = agent(thread_id=self.thread_id)
                step_body = {
                    "user_prompt": search_prompt,
                    "history_messages": [],
                    "agent": agent_name,
                    "skip_followup": True,
                    "params": {
                        "language": self.language,
                        "model": "",
                        "enable_rag": True,
                        "is_hitl": True,
                        "history_files": self.history_attachments,
                    }
                }
                # All search sub-agents need file access for AgentRunSandbox
                files = [attachment['id'] for attachment in attachments if 'id' in attachment and attachment['id']]
                if files:
                    step_body['params']['files'] = files
                # parent_id triggers heavy knowledge-base vector search, keep for Document-Read only
                if tool_name == 'Document-Read' and parent_id:
                    step_body['params']['parent_id'] = parent_id

                generator = agent.start_wo_dump(**step_body)
                ret['type'] = MessageType.THOUGHT
            else:
                context_data, condition_or = await run_query(current_tool, self.output_dir, current_step, self.language, body['user_prompt'], api_mode=self.api_mode)
                logger.info(f'Context data: {str(context_data)[:200]}')
                logger.info(f'Condition or: {condition_or}')
                if condition_or:
                    ret['current_tool']['params']['condition_or'] = True
                    ret['current_tool']['params']['id'] = [d['id'] for d in context_data]
                    ret['current_tool']['params']['step_no'] = current_step
                    async for _ret in send_agent_status_update(ret, AgentStatus.RUNNING):
                        yield _ret
                    ret['current_tool']['params'].pop('condition_or', None)
                    ret['current_tool']['params'].pop('id', None)
                    # ret['current_tool']['params'].pop('step_no', None)
                    
                step_body = await build_workflow_prompt(context_data, current_tool, self.language, self.output_dir, current_step, final_question, prev_tool_uses, plan)
                agent = MindSearchReferAgentV3()
                generator = agent.start_wo_dump(**step_body)

            buffer = io.StringIO()
            chunk_idx = 0
            ret['current_tool'] = current_tool
            ret['chunkIdx'] = chunk_idx
            async for chunk in self._task_with_heartbeat(generator, interval=1, stream=stream):
                try:
                    if await wait_for_interrupt_input(self, self.thread_id):
                        if ret['type'] == MessageType.THOUGHT and ret.get('message'):
                            try:
                                thought = json.loads(ret['message'])
                                thought['content'] = thought.get('content', '') + '\nInterrupted by user input.'
                                ret['message'] = json.dumps(thought)
                            except Exception:
                                pass
                        else:
                            ret['message'] = ret.get('message', '') + '\nInterrupted by user input.'
                        async for _ret in send_message_and_save(ret):
                            yield _ret
                        break
                    if not chunk:
                        continue
                    current_tool['result'] = chunk
                    if isinstance(chunk, dict):
                        content = chunk.get('content', '')
                    else:
                        content = chunk
                    if ret['type'] == MessageType.THOUGHT and isinstance(chunk, dict) and content:
                        async for _ret in send_message_and_save(ret):
                            yield _ret
                        ret['type'] = MessageType.CHAT
                    if ret['type'] == MessageType.THOUGHT:
                        latest_content = json.dumps(chunk, ensure_ascii=False)
                    else:
                        latest_content = content
                    # Ensure message is always a string for frontend compatibility
                    if latest_content and not isinstance(latest_content, str):
                        latest_content = json.dumps(latest_content, ensure_ascii=False)
                    ret['message'] = latest_content or ''
                    if ret.get('message'):
                        yield ret
                except Exception:
                    trace = traceback.format_exc()
                    logger.info(f"Error in chunk processing: {trace}")
            buffer.close()

            if self.stopped:
                if context.commit_shared_state:
                    plan[-1]['status'] = TaskStatus.ERROR
                    plan[-1]['result'] = ret.get('message', '')
                    ret['plan'] = plan
                    prev_tool_uses.append(plan[-1])
                    ret['tool_uses'] = prev_tool_uses
                    async for _ret in send_plan_update(ret):
                        yield _ret
                current_tool['status'] = TaskStatus.ERROR
                if ret.get('message'):
                    current_tool['result'] = ret.get('message', '')
                state.update({
                    'plan': plan,
                    'current_tool': current_tool,
                    'current_step': current_step,
                    'should_run': False,
                    'exit': True,
                })
                return

            result_content = isinstance(current_tool.get('result'), dict) and 'content' in current_tool['result']

            citation_source = []
            if tool_name in ['Generate-Summary', 'General-Inference', 'Medical-Diagnosis']:
                content = current_tool['result']['content'] if result_content else current_tool['result']
                content, citation_source = format_content_citation(prev_tool_uses, content, is_summary=(tool_name == 'Generate-Summary'))
                if file_map:
                    content = resolve_file_markers(content, file_map)
                if result_content:
                    current_tool['result']['content'] = content
                else:
                    current_tool['result'] = content

            source = []
            if isinstance(current_tool.get('result'), dict):
                source = current_tool['result'].get('search_graph', {}).get('source', [])
            if tool_name in ['Generate-Summary', 'General-Inference', 'Medical-Diagnosis']:
                source = citation_source

            citation_str = ""
            if source:
                tmp_source = copy.deepcopy(source)
                tmp_source.sort(key=lambda x: x['id'])
                citation_str = ("\n").join([
                    "- " + self.citation_formatter.vancouver(link)
                    for link in tmp_source if 'id' in link and 'url' in link
                ])

            save_content = current_tool['result']['content'] if result_content else current_tool['result']
            if citation_str:
                save_content += f"\n\n## Reference\n\n{citation_str}\n\n"
            save_to_file(save_content, self.output_dir, f"{current_step-1}_{current_tool['tool']}_NoahAI.md")

            if context.commit_shared_state and current_step == len(plan) and download_link:
                if self.api_mode:
                    yield {'type': MessageType.SUMMARY, 'message': ret.get('message', '')}
                    await asyncio.sleep(0.5)
                    state.update({
                        'plan': plan,
                        'current_tool': current_tool,
                        'current_step': current_step,
                        'should_run': False,
                        'exit': True,
                    })
                    return
                try:
                    # if file_map:
                    #     await download_sandbox_files(file_map, self.output_dir)
                    STORAGE_DEST = 'azure'
                    bucket_name = "noahai-userdata-test" if STORAGE_DEST == 'hw' else 'nudata'
                    await self.upload_archive(f"{object_path}.zip", bucket_name, STORAGE_DEST)
                    ret['attachments_key'] = f"{self.output_dir}.zip"
                    dl_label = translate("planning.download_link", resolve_language(self.language))
                    if STORAGE_DEST == 'hw':
                        download_msg = "\n\n" + dl_label + f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{encoded_object_path}.zip)"
                    else:
                        download_msg = "\n\n" + dl_label + f"(https://noahdata.blob.core.windows.net/{bucket_name}/{encoded_object_path}.zip)"
                    if result_content:
                        current_tool['result']['content'] += download_msg
                    else:
                        current_tool['result'] += download_msg
                except Exception:
                    trace = traceback.format_exc()
                    logger.info(f"Error in data upload: {trace}")

            current_tool['status'] = TaskStatus.DONE
            if isinstance(current_tool['result'], str):
                full_result = current_tool['result']
            else:
                full_result = str(current_tool['result'].get('content', ''))
            ret['message'] = full_result
            async for _ret in send_message_and_save(ret):
                yield _ret

            if source:
                async for _ret in send_message_and_save(ret):
                    _ret['type'] = MessageType.REFERENCE
                    _ret['message'] = json.dumps(source, ensure_ascii=False)
                    chunk_idx += 1
                    _ret['chunkIdx'] = chunk_idx
                    yield _ret

        ret.pop('chunkIdx', '')
        ret.pop('message', '')
        if not context.commit_shared_state:
            state.update({
                'plan': plan,
                'current_tool': current_tool,
                'current_step': current_step,
                'should_run': False,
            })
            return
        async for _ret in self._commit_single_tool_result(
            ret=ret,
            body=body,
            prev_tool_uses=prev_tool_uses,
            state=state,
            current_tool=current_tool,
            current_step=current_step,
            plan=plan,
            feedback=feedback,
            final_question=final_question,
            hitl_mode=hitl_mode,
        ):
            yield _ret

    async def _commit_single_tool_result(
        self,
        ret: dict,
        body: dict,
        prev_tool_uses: List[dict],
        state: dict,
        current_tool: dict,
        current_step: int,
        plan: List[dict],
        feedback: str,
        final_question: str,
        hitl_mode: str,
    ):
        """Commit one finished tool into the shared planning state."""
        ret['type'] = MessageType.PLAN_UPDATE
        if prev_tool_uses and (prev_tool_uses[-1]['tool'] == 'Self-Reflection' or not prev_tool_uses[-1].get('result', '')):
            prev_tool_uses[-1] = current_tool.copy()
        else:
            prev_tool_uses.append(current_tool.copy())
        ret["tool_uses"] = prev_tool_uses
        ret.pop('attachments_key', '')

        plan[current_step-1]['status'] = TaskStatus.DONE
        if len(plan) > current_step:
            plan[current_step]['status'] = TaskStatus.DOING
            plan[current_step]['startedAt'] = int(time.time())
        ret['plan'] = plan
        async for _ret in send_message_and_save(ret):
            yield _ret

        current_step += 1
        ret['current_step'] = current_step

        if current_step-1 >= len(plan):
            state.update({
                'plan': plan,
                'current_tool': current_tool,
                'current_step': current_step,
                'should_run': False,
            })
            return

        next_tool = plan[current_step-1].copy()
        # 给下一个 tool 准备 ['params'] 字段
        if 'params' not in next_tool and next_tool['tool'] not in ['Generate-Summary', 'Self-Reflection', 'User-Question', 'Plan-Sequence', 'General-Inference']:
            await self._fill_and_clean_tool_params(body, next_tool, prev_tool_uses, feedback, final_question, current_step)
        ret['current_tool'] = next_tool

        should_continue = hitl_mode != 'always'
        state.update({
            'plan': plan,
            'current_tool': next_tool,
            'current_step': current_step,
            'should_run': should_continue,
        })

    async def _run_single_tool_to_queue(self, context: ToolRunContext, queue: asyncio.Queue, step_idx: int):
        """Run one isolated tool and forward its streamed messages into a queue."""
        try:
            async for _ret in send_agent_status_update(context.ret, AgentStatus.RUNNING):
                payload = copy.deepcopy(_ret)
                payload['concurrent_stream'] = True
                payload['tool_step'] = step_idx + 1
                await queue.put(("message", step_idx, payload))
            async for _ret in self._run_single_tool(context):
                payload = copy.deepcopy(_ret)
                payload['concurrent_stream'] = True
                payload['tool_step'] = step_idx + 1
                await queue.put(("message", step_idx, payload))
            return copy.deepcopy(context.state['current_tool'])
        except Exception as exc:
            tool_name = (context.state.get('current_tool') or {}).get('tool', '?')
            logger.exception(
                f"[_run_single_tool_to_queue] step {step_idx} ({tool_name}) raised {type(exc).__name__}"
            )
            await queue.put(("error", step_idx, exc))
            raise
        finally:
            await queue.put(("done", step_idx, None))

    async def _run_concurrent_batch(self, batch: List[int], context: ToolRunContext):
        """Execute one batch of independent tools concurrently and commit once at the end."""
        ret = context.ret
        body = context.body
        prev_tool_uses = context.prev_tool_uses
        total_feedback = context.total_feedback
        state = context.state
        final_question = context.final_question
        feedback = context.feedback
        hitl_mode = context.hitl_mode
        download_link = context.download_link
        object_path = context.object_path
        encoded_object_path = context.encoded_object_path
        attachments = context.attachments
        parent_id = context.parent_id
        plan = state['plan']
        current_step = state['current_step']
        current_tool = state['current_tool']
        approve = state['approve']

        started_at = int(time.time())
        for step_idx in batch:
            plan[step_idx]['status'] = TaskStatus.DOING
            plan[step_idx]['startedAt'] = started_at

        ret['type'] = MessageType.PLAN_UPDATE
        ret['plan'] = plan
        ret['tool_uses'] = prev_tool_uses
        ret.pop('message', None)
        ret.pop('chunkIdx', None)
        ret.pop('attachments_key', None)
        async for _ret in send_message_and_save(ret):
            yield _ret

        base_prev_tool_uses = copy.deepcopy(prev_tool_uses)

        async def _prepare_child_context(step_idx: int):
            current_tool_copy = plan[step_idx].copy()
            if 'params' not in current_tool_copy and current_tool_copy['tool'] not in ['Generate-Summary', 'Self-Reflection', 'User-Question', 'Plan-Sequence', 'General-Inference']:
                await self._fill_and_clean_tool_params(
                    body,
                    current_tool_copy,
                    copy.deepcopy(base_prev_tool_uses),
                    feedback,
                    final_question,
                    step_idx + 1,
                )

            child_ret = copy.deepcopy(ret)
            child_ret.pop('plan', None)
            child_ret.pop('tool_uses', None)
            child_ret.pop('message', None)
            child_ret.pop('chunkIdx', None)
            child_ret.pop('attachments_key', None)
            child_ret['current_step'] = step_idx + 1
            child_ret['current_tool'] = current_tool_copy
            child_ret['concurrent_stream'] = True
            child_ret['tool_step'] = step_idx + 1

            child_state = {
                'current_step': step_idx + 1,
                'current_tool': current_tool_copy,
                'plan': copy.deepcopy(plan),
                'should_run': False,
                'approve': approve,
            }
            return (
                step_idx,
                ToolRunContext(
                    ret=child_ret,
                    body=body,
                    prev_tool_uses=copy.deepcopy(base_prev_tool_uses),
                    total_feedback=total_feedback,
                    state=child_state,
                    final_question=final_question,
                    feedback=feedback,
                    hitl_mode=hitl_mode,
                    download_link=download_link,
                    object_path=object_path,
                    encoded_object_path=encoded_object_path,
                    attachments=attachments,
                    parent_id=parent_id,
                    concurrent=True,
                    commit_shared_state=False,
                    base_prev_tool_uses=copy.deepcopy(base_prev_tool_uses),
                )
            )

        child_contexts = list(await asyncio.gather(*[
            _prepare_child_context(step_idx) for step_idx in batch
        ]))

        queue: asyncio.Queue = asyncio.Queue()
        tasks = [
            asyncio.create_task(self._run_single_tool_to_queue(child_context, queue, step_idx))
            for step_idx, child_context in child_contexts
        ]

        done_count = 0
        batch_error = None
        while done_count < len(tasks):
            kind, step_idx, payload = await queue.get()
            if kind == "message":
                yield payload
            elif kind == "error":
                if batch_error is None:
                    batch_error = payload
                for task in tasks:
                    if not task.done():
                        task.cancel()
            elif kind == "done":
                done_count += 1

            if self.stopped and batch_error is None:
                batch_error = RuntimeError("Concurrent batch interrupted by stop signal")
                for task in tasks:
                    if not task.done():
                        task.cancel()

        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        if batch_error is None:
            for (step_idx, _), task_result in zip(child_contexts, task_results):
                if isinstance(task_result, BaseException) and not isinstance(task_result, asyncio.CancelledError):
                    batch_error = task_result
                    tool_name = plan[step_idx].get('tool', '?')
                    logger.error(
                        f"[_run_concurrent_batch] step {step_idx} ({tool_name}) failed: "
                        f"{type(task_result).__name__}: {task_result}",
                        exc_info=(type(task_result), task_result, task_result.__traceback__),
                    )
                    break

        if batch_error is not None or self.stopped:
            for step_idx in batch:
                plan[step_idx]['status'] = TaskStatus.ERROR
            ret['type'] = MessageType.PLAN_UPDATE
            ret['plan'] = plan
            ret['tool_uses'] = prev_tool_uses
            ret.pop('attachments_key', None)
            ret.pop('message', None)
            ret.pop('chunkIdx', None)
            async for _ret in send_message_and_save(ret):
                yield _ret
            state.update({
                'plan': plan,
                'current_tool': current_tool,
                'current_step': current_step,
                'should_run': False,
                'exit': True,
            })
            return

        batch_results = {}
        for (step_idx, _), task_result in zip(child_contexts, task_results):
            batch_results[step_idx] = copy.deepcopy(task_result)

        for step_idx in batch:
            plan[step_idx]['status'] = TaskStatus.DONE
            prev_tool_uses.append(copy.deepcopy(batch_results[step_idx]))

        next_step = batch[-1] + 2
        ret['type'] = MessageType.PLAN_UPDATE
        ret['tool_uses'] = prev_tool_uses
        ret['plan'] = plan
        ret.pop('attachments_key', None)
        ret.pop('message', None)
        ret.pop('chunkIdx', None)
        ret['current_step'] = next_step

        if next_step - 1 >= len(plan):
            state.update({
                'plan': plan,
                'current_tool': batch_results[batch[-1]],
                'current_step': next_step,
                'should_run': False,
            })
            async for _ret in send_message_and_save(ret):
                yield _ret
            return

        plan[next_step - 1]['status'] = TaskStatus.DOING
        plan[next_step - 1]['startedAt'] = int(time.time())
        next_tool = plan[next_step - 1].copy()
        if 'params' not in next_tool and next_tool['tool'] not in ['Generate-Summary', 'Self-Reflection', 'User-Question', 'Plan-Sequence', 'General-Inference']:
            await self._fill_and_clean_tool_params(body, next_tool, prev_tool_uses, feedback, final_question, next_step)
        ret['current_tool'] = next_tool
        ret['plan'] = plan
        async for _ret in send_message_and_save(ret):
            yield _ret

        state.update({
            'plan': plan,
            'current_tool': next_tool,
            'current_step': next_step,
            'should_run': hitl_mode != 'always',
        })
        
    async def upload_archive(self, object_path, bucket_name, source='azure'):
        if source == 'hw':
            from utils.obs.client import upload_file
        else:
            from utils.azure.blob_client import upload_file
        # Save report and outputs to zip file
        zip_path = f"{self.output_dir}.zip"
        try:
            convert_md_to_docx(self.output_dir)
        except:
            pass
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        shutil.make_archive(self.output_dir, 'zip', self.output_dir)
        logger.info(f"Output saved to {zip_path}")
        
        for _ in range(3):
            res = upload_file(bucket_name, object_path, zip_path)
            if res: 
                logger.info(f"File {zip_path} uploaded successfully")
                # Delete zip and original folder when upload is successful
                try:
                    os.remove(zip_path)  # Delete the zip file
                    shutil.rmtree(self.output_dir)  # Delete the original folder
                    logger.info(f"Cleaned up {zip_path} and {self.output_dir}")
                except Exception as e:
                    logger.error(f"Failed to clean up files: {str(e)}")
                break
            await asyncio.sleep(3)
        else:
            logger.error(f"Failed to upload {zip_path}")
        
    async def self_reflection(self, ret, user_question, prev_tool_uses, current_tool, current_step, plan, feedback, approve=None):
        for step in plan:
            step.pop('result', None)
            step.pop('params', None)
        chunk = ''
        if approve is not True or not prev_tool_uses or prev_tool_uses[-1]['tool'] != 'Self-Reflection':
            instructions = pt_fetcher.get('reflection_instructions_cn', reflection_instructions_cn) if self.language == 'zh-CN' else pt_fetcher.get('reflection_instructions', reflection_instructions)

            tools_description_pt = pt_fetcher.get('tools_description_cn', tools_description_cn) if self.language == 'zh-CN' else pt_fetcher.get('tools_description', tools_description)
            reflection_instructions_prompt = instructions.format(additional_step_count=min(4, max(3, self.max_steps_soft_max-len(plan))), noah_tools=tools_description_pt, output_language=self.language)
            if prev_tool_uses[-1]['tool'] == 'Self-Reflection':
                prior_knowledge = tool_history_to_prompt(prev_tool_uses[-1:], is_plan=True)
            else:
                prior_knowledge = tool_history_to_prompt(prev_tool_uses, is_plan=True)
            
            
            reflection_prompt = reflection_template.format(
                current_date=datetime.now().strftime('%B %d, %Y'),
                instructions_prompt=reflection_instructions_prompt,
                user_prompt=user_question,
                current_plan=json.dumps(plan, ensure_ascii=False),
                prior_knowledge=prior_knowledge,
                user_feedback=feedback,
                output_language=self.language,
            )
            reflection_round = sum(1 for s in plan[:current_step-1] if s.get('tool') == 'Self-Reflection' and s.get('status') == TaskStatus.DONE)
            reflection_prompt = generate_reflection_prompt(user_question, json.dumps(plan, ensure_ascii=False), prior_knowledge, tools_description_pt, self.get_language(), reflection_round=reflection_round)
            
            ret['type'] = MessageType.CHAT
            # tanght-learn-llm 让AI生成反思文本
            # response_stream = self.plan_llm.stream_call(user_prompt=reflection_prompt)
            response_stream = self.summary_llm.stream_generate(
                input=[{"role": "user", "content": reflection_prompt}],
                sys_prompt="You are a helpful assistant.",
                reasoning={"effort": "medium"},
                temperature=1,
                max_tokens=8 * 1024,
            )
            async for chunk in task_with_heartbeat(response_stream, interval=1, stream=True):
                if chunk is None:
                    yield ret
                    continue
                if not chunk: continue
                ret['message'] = chunk
                yield ret

            tool_use = ret['current_tool'].copy()
            tool_use['result'] = ret['message']
            if prev_tool_uses: 
                if prev_tool_uses[-1]['tool'] != 'Self-Reflection':
                    prev_tool_uses.append(tool_use)
                else:
                    prev_tool_uses[-1]['result'] = ret['message']
            else:
                prev_tool_uses.append(tool_use)
            ret['tool_uses'] = prev_tool_uses

            async for _ret in send_message_and_save(ret):
                yield _ret
                
            ret.pop('message', None)
            ret.pop('chunkIdx', '')
        current_tool['result'] = reflection_message = chunk or (prev_tool_uses[-1]['result'] if prev_tool_uses else '')
        save_to_file(current_tool['result'], self.output_dir + '/process', f"{current_step-1}_{current_tool['tool']}_NoahAI.md")

        reflection_extraction_template = pt_fetcher.get('reflection_extraction_template_cn', reflection_extraction_template_cn) if self.language == 'zh-CN' else pt_fetcher.get('reflection_extraction_template_en', reflection_extraction_template_en)
        reflection_extraction_prompt = reflection_extraction_template.format(reflection=reflection_message)
        
        reflection_schema = get_openai_json_schema_v3(ReflectionSchema)
        tool_choice = {"type": "function", "function": {"name": reflection_schema[0]['function']['name']}}
        # tanght-learn-llm 让AI根据反思文本生成 额外的 Plan 计划 [{'tool': '', 'reason': '', 'query_params': ''}]
        # 如果 AI 觉得已经 ok 了，AI 就会让 additional_steps 为 []
        slot_fill_result = await function_call_with_retry(self.slot_filling_llm, user_prompt=reflection_extraction_prompt, tools=reflection_schema, tool_choice=tool_choice, planning=True, temperature=0.3, max_tokens=8192)

        additional_steps = slot_fill_result.get('additional_steps', [])[:min(4, max(3, self.max_steps_soft_max-len(plan)))]
        # Normalize tool names from reflection extraction
        for step in additional_steps:
            step['tool'] = normalize_planning_tool_name(step.get('tool', ''))
        if not additional_steps:
            summary_tool = {'tool': 'Generate-Summary', 'status': TaskStatus.TODO, 'startedAt': int(time.time())}
            summary_tool['reason'] = translate("planning.summary_reason", resolve_language(self.language))
            additional_steps = [summary_tool]
        elif additional_steps[-1].get('tool', '') not in ['Generate-Summary', 'Self-Reflection', 'General-Inference', 'Medical-Diagnosis']:
            reflection_reason = translate("planning.reflection_reason", resolve_language(self.language))
            reflection_tool = {'tool': 'Self-Reflection', 'status': TaskStatus.TODO, 'startedAt': int(time.time()), 'reason': reflection_reason}
            additional_steps.append(reflection_tool)

        if len(additional_steps) + current_step >= self.max_steps_hard_max and additional_steps[-1].get('tool', '') != 'Generate-Summary':
            summary_reason = translate("planning.summary_reason", resolve_language(self.language))
            additional_steps[-1] = {'tool': 'Generate-Summary', 'status': TaskStatus.TODO, 'startedAt': int(time.time()), 'reason': summary_reason}
        for step in additional_steps:
            step['status'] = TaskStatus.TODO
            step['startedAt'] = int(time.time())

        plan = plan[:current_step] + additional_steps
        ret['plan'] = plan
        current_tool['status'] = TaskStatus.DONE
        
    async def llm_clean(self, params, user_prompt):
        params = params.copy()
        for field in ['phase', 'location', 'locations', 'id']:
            if field in params:
                params.pop(field, None)
        prompt = f"""Identify irrelevant parameter values for our database query based on the user's question.

    <User Question>
    {user_prompt}
    </User Question>

    <Query Parameters>
    {params}
    </Query Parameters>

    Instructions:
    - Only flag values that are semantically irrelevant to the user's question
    - Keep values that are related even if they're broader than what was requested
    - Return an array of objects with irrelevant param_name/value pairs
    - If all values seem relevant, return an empty array

    Example:
    User Question: "Develop a comprehensive global competitive landscape analysis of platinum-resistant ovarian cancer (PROC) as of today."
    Parameters: {{"indication_name": ["Small cell lung cancer recurrent", "Ovarian cancer"], "drug_modality": ["Small Molecule", "Monoclonal Antibodies", "Antibody-Drug Conjugates, ADCs", "Vaccine", "Cell-based Therapies"]}}
    Expected Output: {{"irrelevant_values":[{{"param_name":"indication_name","value":"Small cell lung cancer recurrent"}}]}}
    """
        schema = get_openai_json_schema_v3(IrrelevantParamValueList)
        tool_choice = {"type": "function", "function": {"name": schema[0]['function']['name']}}
        # tanght-learn-llm 让AI识别查询参数中与用户问题语义无关的参数值 输入"用户问题+查询参数" 返回 [{'param_name': 'xxx', 'value': 'yyy'}]
        # 例如：用户问"卵巢癌"，但参数里有"小细胞肺癌"，则AI会识别出"小细胞肺癌"是不相关的
        irrelevant_values = await function_call_with_retry(self.slot_filling_llm, user_prompt=prompt, tools=schema, tool_choice=tool_choice)
        return irrelevant_values['irrelevant_values']
    
    def get_language(self):
        """Return the normalized BCP-47 language code."""
        return self.language

    async def inhouse_parsing(self, files, user_prompt, final_question):
        attachment_manager = AttachmentManager()
        attachment_records = attachment_manager.fetch_attachments(files, False)
        contexts_map = {}

        async def _fetch_attachment_context(att):
            url = att.get('url', '')
            name = att.get('name', "Untitled")
            attachment_id = str(att.get('id', ''))
            context_text = await fetch_context_single(
                url, name, attachment_id, query=user_prompt, detailed=1
            )
            return attachment_id, context_text

        results = await asyncio.gather(*[
            _fetch_attachment_context(att) for att in attachment_records
        ])
        for attachment_id, context_text in results:
            contexts_map[attachment_id] = context_text

        final_context_list = []

        for file_id in files:
            file_id_str = str(file_id)

            curr_context = contexts_map.get(file_id_str, "")

            if curr_context:
                final_context_list.append(curr_context)

        combined_context_str = "\n\n".join(final_context_list)

        if self.language != 'zh-CN':
            attachments_chunk = (
                "<User Provided Attachments>\n" +
                combined_context_str +
                "\n</User Provided Attachments>\n\n "
            )
        else:
            attachments_chunk = (
                "<用户附件>\n" +
                combined_context_str +
                "\n</用户附件>\n\n "
            )
            encoding = tiktoken.get_encoding("cl100k_base")
            total_tokens = len(encoding.encode(attachments_chunk))
        return attachments_chunk, total_tokens

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
