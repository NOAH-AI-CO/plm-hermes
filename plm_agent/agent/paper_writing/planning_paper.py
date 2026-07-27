import asyncio
from dataclasses import asdict
from datetime import datetime
import io
import os
import hashlib
import shutil
import time
import traceback
from typing import Callable, List, Type
from agent.human_in_loop.utils import *
from agent.paper_writing.writing.full_paper_workflow_agent import MedicalWritingAgent
from agent.paper_writing.schema.data_insight import DatasetAnalysisResult
from utils.human_in_loop.helpers import *
import urllib.parse

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.deepseek_models import ClaudeThenDeepseekChat, CompositeDeepseekChat, CompositeDeepseekReasoner, ClaudeThenDeepseekChat2
from llm.composite_models import CompositeHitlFinal
import json
import logging
from utils.core.prompt_fetcher import PromptFetcher
from agent.paper_writing.process_manuscript import process_manuscript_outline
from agent.paper_writing.schema.manuscript import ManuscriptOutline, ManuscriptProfile, Section


pt_fetcher = PromptFetcher()

logger = logging.getLogger(__name__)

class PlanningAgent(AgentPreset):
    llm: BaseLLM = CompositeDeepseekChat(max_retries=0, timeout=15, first_chunk_timeout=10)
    plan_llm: BaseLLM = ClaudeThenDeepseekChat(max_retries=0, timeout=15, first_chunk_timeout=10)
    plan_llm_2: BaseLLM = ClaudeThenDeepseekChat2(max_retries=0, timeout=15, first_chunk_timeout=10)
    summary_llm: BaseLLM = CompositeHitlFinal()
    output_dir: str = "outputs/"
    language: str = 'en-US'
    thread_id: str = ''
    stopped: bool = False
    auto_run_stopped: bool = False 
    manuscript_profile: ManuscriptProfile = None
    document_analysis_results: dict = {}
    dataset_analysis_results: dict = {}
    manuscript_outline: ManuscriptOutline = None
    writing_agent: MedicalWritingAgent = MedicalWritingAgent()
    sections: List[Section] = []
    
    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], planning_task: dict = {}, feedback: str = '', hitl_mode:str='', **kwargs):
        question = planning_task.get('question', user_prompt) or ''
        body = {
            "user_prompt": question
        }
        user = planning_task.get('user', 'unknown')
        task_id = planning_task.get('id', 'unknown')
        self.thread_id = planning_task.get('thread_id', 'unknown')
        download_link = kwargs.get('download_link', True)
        writing_vars = planning_task.get('writing_vars', {})
        if writing_vars:
            self.manuscript_profile = ManuscriptProfile.model_validate(writing_vars.get('manuscript_profile', {}))
            self.manuscript_outline = ManuscriptOutline.model_validate(writing_vars.get('manuscript_outline', {}))
            self.document_analysis_results = writing_vars.get('document_analysis_results', {})
            self.dataset_analysis_results = writing_vars.get('dataset_analysis_results', {})
            self.sections = [Section.model_validate(s) for s in writing_vars.get('sections', [])]
            
        question_prefix = question[:20].replace(' ', '_')
        safe_prefix = urllib.parse.quote(question_prefix)
        object_path = f"paper/{user}/{task_id}/{question_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        encoded_object_path = f"paper/{user}/{task_id}/{safe_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        self.output_dir = f"outputs/" + object_path
        STORAGE_DEST = 'azure'
        bucket_name = "noahai-userdata-test" if STORAGE_DEST =='hw' else 'nudata'
        approve = kwargs.get('approve', None)
        should_replan = (approve is False)
        past_feedback = planning_task.get('feedback', [])
        total_feedback = past_feedback + [feedback] if feedback else past_feedback
        from i18n.languages import normalize as _norm
        self.language = _norm(kwargs.get('language', '') or planning_task.get('language', ''))
        plan = planning_task.get('plan', []) 
        current_tool = {}
        current_step = planning_task.get('current_step', 0)
        if not current_step and plan:
            current_step = 1
        hitl_mode = hitl_mode or planning_task.get('hitl_mode', '') or 'never'
        if not current_tool:
            if plan and current_step <= len(plan):
                current_tool = plan[current_step-1].copy()
        should_run = bool(plan and not should_replan) # user confirmation of tool use
        ret = {'tool_uses': [], 'type': 'chat', "agent": "planning", "hitl_mode": hitl_mode, 'sender': 'assistant',
               "current_step": current_step, "current_tool": current_tool, 'feedback': total_feedback, 'writing_vars': writing_vars}
        if current_tool and current_tool.get('status', 'error') != 'error':
            async for _ret in send_confirm_tool(ret, feedback, should_run):
                yield _ret
        if hitl_mode == 'never':
            should_run = True
        ret['saveChat'] = False
        
        if not plan or len(plan) <= 1: # if current_tool != plan[0].get('tool')
            # try rewrite user original question, first rewrite

            ret['type'] = 'planUpdate'
            ret['current_step'] = current_step = 1
            plan_reason = "设计工具序列以处理用户请求" if self.language == 'zh-CN' else "Design tool sequence to handle user prompt"
            ret['current_tool'] = {"tool": "Plan-Sequence", 'status': 'doing', 'startedAt': int(time.time()), "reason": plan_reason}
            ret['plan'] = plan = [ret['current_tool']]
            async for _ret in send_message_and_save(ret):
                yield _ret
            if not writing_vars:
                await process_manuscript_outline(self, task_id, user)
                ret['writing_vars'] = {
                    'manuscript_profile': self.manuscript_profile.model_dump(),
                    'manuscript_outline': self.manuscript_outline.model_dump(),
                    'document_analysis_results': self.document_analysis_results,
                    'dataset_analysis_results': self.dataset_analysis_results,
                    'sections': [s.model_dump() for s in self.sections]
                }
            writing_steps = self.writing_agent._initialize_writing_plan(self.manuscript_profile)
            plan += writing_steps

            # ret['type'] = 'chat'
            # ret['message'] = f"## 论文写作任务：{question}\n\n" + (f"### 研究类型：{self.manuscript_profile.study_type}\n\n" if self.manuscript_profile.study_type else '') + \
            plan[current_step-1]['status'] = 'done'
            current_step += 1
            ret['current_step'] = current_step
            current_tool = plan[current_step-1]
            ret['plan'] = plan 
            ret['type'] = 'planUpdate'
            async for _ret in send_message_and_save(ret):
                yield _ret
            
        ret.pop("plan", None)
        
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
        
        ret['current_tool'] = current_tool
                
        while should_run:
            async for _ret in send_agent_status_update(ret, 'running'):
                yield _ret
            ret['type'] = 'chat'
            # Run the query first to get potential context to select from
            current_tool = plan[current_step-1]
            
            try:
                # 执行当前写作步骤
                data_analyses = list(DatasetAnalysisResult.model_validate(v) for v in self.dataset_analysis_results.values())
                async for step_result in self.writing_agent._execute_writing_step(
                    current_tool, self.manuscript_profile, self.manuscript_outline, data_analyses, list(self.document_analysis_results.values()), self.sections):
                    ret.update(step_result)
                    yield ret
                    
                async for _ret in send_message_and_save(ret):
                    _ret['sections'] = [s.model_dump() for s in self.sections]
                    yield _ret

                # 标记步骤完成
                current_tool['status'] = "done"
                current_tool['result'] = ret.get('message', '')
                
                # # 更新进度
                if current_step < len(plan):
                    plan[current_step-1]['status'] = "done"
                    plan[current_step-1]['started_at'] = int(time.time())

                # 发送步骤完成状态
                ret['plan'] = plan
                yield ret
                
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in writing step {current_tool['tool']}: {e}")
                current_tool['status'] = "error"
                current_tool['result'] = str(e)
                ret['error'] = str(e)
                yield ret
                return
            
            # buffer.close()
            if self.stopped:
                plan[-1]['status'] = 'error'
                plan[-1]['result'] = ret.get('message', '')
                ret['plan'] = plan
                async for _ret in send_plan_update(ret):
                    yield _ret
                return
            
            result_content = False
            if type(current_tool['result']) == dict and 'content' in current_tool['result']:
                result_content = True
            
            if current_step == len(plan) and download_link:
                try:
                    await self.upload_archive(f"{object_path}.zip", bucket_name, STORAGE_DEST)
                    ret['attachments_key'] = f"{self.output_dir}.zip"
                    if STORAGE_DEST == 'hw':
                        download_link = "\n\n" + ("## 下载链接：[结果与数据]" if self.language.lower() == 'zh-CN' else "## Download link: [Results & Data]") + f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{encoded_object_path}.zip)"
                    else:
                        download_link = "\n\n" + ("## 下载链接：[结果与数据]" if self.language.lower() == 'zh-CN' else "## Download link: [Results & Data]") + f"(https://noahdata.blob.core.windows.net/{bucket_name}/{encoded_object_path}.zip)"
                    
                    if result_content:
                        current_tool['result']['content'] += download_link
                    else:
                        current_tool['result'] += download_link
                except:
                    trace = traceback.format_exc()
                    logger.info(f"Error in data upload: {trace}")
            # TODO: remove later
            current_tool['status'] = 'done'
            if isinstance(current_tool['result'], str):
                full_result = current_tool['result']
            else:
                full_result = str(current_tool['result'].get('content', ''))
            ret['message'] = full_result
            async for _ret in send_message_and_save(ret):
                yield _ret

            ret.pop('message', '')
            
            ret['type'] = 'planUpdate'
            ret.pop('attachments_key', '')
            # ret['current_tool'] = {}
            plan[current_step-1]['status'] = 'done'
            if len(plan) > current_step:
                plan[current_step]['status'] = 'doing'
                plan[current_step]['startedAt'] = int(time.time())
            ret['plan'] = plan
            async for _ret in send_message_and_save(ret):
                yield _ret
            current_step += 1
            ret['current_step'] = current_step
            if current_step-1 >= len(plan):
                should_run = False
                break
            if hitl_mode == 'always':
                should_run = False
            current_tool = plan[current_step-1].copy()
            ret['current_tool'] = current_tool
            
        if current_step-1 < len(plan):
            ret['type'] = 'statusUpdate'
            ret['agentStatus'] = 'waiting'
        else:
            # extra message to update plan
            ret['type'] = 'statusUpdate'
            ret['agentStatus'] = 'stopped'
            if 'taskStart' in planning_task:
                ret['taskStart'] = planning_task['taskStart']
            ret.pop('current_tool', None)
        async for _ret in send_message_and_save(ret):
            yield _ret


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
        