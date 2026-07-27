import os
import io
import json
import shutil
import asyncio
import hashlib
import logging
import time
import traceback
import aiohttp
import tempfile
import urllib.parse
from datetime import datetime
from typing import Any, List, Type, Dict

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.gcp_models import Gemini25Flash
from llm.composite_models import NSFCWritingModels
from agent.nsfc.nsfc_prep_analyzer import NSFCPrepAnalyzer
from agent.nsfc.nsfc_docs_analyzer import NSFCDocsAnalyzer
from agent.human_in_loop.utils import (
    send_confirm_tool,
    send_message_and_save,
    send_agent_status_update,
    send_plan_update,
    convert_md_to_docx
)
from utils.utils.attachment import AttachmentManager
from i18n.languages import normalize as _norm

logger = logging.getLogger(__name__)


class NSFCPlanningAgent(AgentPreset):
    llm: BaseLLM = NSFCWritingModels()
    output_dir: str = "outputs/"
    language: str = 'zh-CN'
    thread_id: str = ''
    stopped: bool = False
    
    # NSFC specific analyzers
    prep_analyzer_class: Type[NSFCPrepAnalyzer] = NSFCPrepAnalyzer
    docs_analyzer_class: Type[NSFCDocsAnalyzer] = NSFCDocsAnalyzer
    nsfc_prep_analyzer: NSFCPrepAnalyzer = None
    nsfc_docs_analyzer: NSFCDocsAnalyzer = None
    
    # State variables
    query_params: dict = {}
    summarized_docs: List[Dict[str, Any]] = []
    nsfc_project_preview: str = ""
    nsfc_proposal_outline: List[Dict] = []

    # utils
    attachment_manager: AttachmentManager = AttachmentManager()
    
    def __init__(self, query_params={}, gemini_mode=False, model=None, **kwargs):
        super().__init__()
        
        params = kwargs.get('params', {})
        self.language = _norm(params.get('language', ''))
        
        # 处理用户输入
        query_params.update(params.get('raw_data', {}))
        title = query_params.get("user_title", "") or ""
        query = query_params.get("user_query", "") or ""
        if title or query:
            query_params["user_input"] = f"{title}\n\n{query}".strip()
        else:
            query_params["user_input"] = kwargs.get('user_prompt', '')
        
        self.query_params = query_params
        logger.info(f"NSFC Planning query_params: {query_params}")
        
        # 允许传入自定义模型
        if model is None:
            model = Gemini25Flash() if gemini_mode else NSFCWritingModels()
        
        # 初始化分析器
        self.nsfc_prep_analyzer = self.prep_analyzer_class(
            model=model, 
            query_params=query_params, 
            language=self.language
        )
        self.nsfc_docs_analyzer = self.docs_analyzer_class(
            model=model, 
            language=self.language
        )
    
    def _initialize_nsfc_plan(self) -> List[dict]:
        """初始化NSFC写作计划"""
        if self.language == 'zh-CN':
            steps = [
                {"tool": "translate_extract", "reason": "翻译、概念提炼与关键词抽取", "status": "pending", "estimated_time": "~30秒"},
                {"tool": "search_nsfc", "reason": "搜索近年相关国家自然科学基金项目", "status": "pending", "estimated_time": "~30秒"},
                {"tool": "analyze_nsfc_overview", "reason": "归纳领域研究格局、热点方向与典型模型", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "analyze_nsfc_mechanism", "reason": "提炼主要研究路径、关键机制与常用技术路线", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "analyze_nsfc_gap", "reason": "识别研究空白、薄弱环节与潜在科学问题", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "search_pubmed", "reason": "检索近年国际相关文献", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "analyze_pubmed", "reason": "提取国际研究结构、前沿机制与典型研究链条", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "generate_titles", "reason": "输出3个候选项目题目及核心研究思路", "status": "pending", "estimated_time": "~2分钟"},
                {"tool": "generate_outline", "reason": "基于题目构建完整章节结构与科学问题链", "status": "pending", "estimated_time": "~1分钟"},
                {"tool": "write_lixiang_part1", "reason": "撰写立项依据（部分1）— 背景、意义与现状分析", "status": "pending", "estimated_time": "~3分钟"},
                {"tool": "write_lixiang_other", "reason": "撰写立项依据（部分2–5）— 内容、目标、方案、创新与可行性", "status": "pending", "estimated_time": "~3分钟"},
                {"tool": "write_research_basis", "reason": "整理研究基础 — 总结前期工作、团队积累与支撑条件", "status": "pending", "estimated_time": "~2分钟"},
                {"tool": "write_other_info", "reason": "补充说明 — 完成'其他需要说明的情况'部分", "status": "pending", "estimated_time": "~1分钟"},
            ]
        else:
            steps = [
                {"tool": "translate_extract", "reason": "Translation, concept extraction, and keyword generation", "status": "pending", "estimated_time": "~30s"},
                {"tool": "search_nsfc", "reason": "Retrieve recent NSFC projects related to the topic", "status": "pending", "estimated_time": "~30s"},
                {"tool": "analyze_nsfc_overview", "reason": "Summarize research landscape, hotspots, and common models", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "analyze_nsfc_mechanism", "reason": "Extract key mechanisms, research pathways, and technical routes", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "analyze_nsfc_gap", "reason": "Identify research gaps, weak links, and potential scientific questions", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "search_pubmed", "reason": "Retrieve recent international publications", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "analyze_pubmed", "reason": "Extract global research structure, frontier mechanisms", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "generate_titles", "reason": "Produce three candidate project titles with core research ideas", "status": "pending", "estimated_time": "~2 min"},
                {"tool": "generate_outline", "reason": "Build a complete proposal outline based on the selected title", "status": "pending", "estimated_time": "~1 min"},
                {"tool": "write_lixiang_part1", "reason": "Writing the Proposal (Part I) — background, significance, and current progress", "status": "pending", "estimated_time": "~3 min"},
                {"tool": "write_lixiang_other", "reason": "Writing the Proposal (Parts II–V) — aims, methodology, innovation, and feasibility", "status": "pending", "estimated_time": "~3 min"},
                {"tool": "write_research_basis", "reason": "Research foundation — summarize previous work, team strengths", "status": "pending", "estimated_time": "~2 min"},
                {"tool": "write_other_info", "reason": "Additional statements — complete the 'Other Information' section", "status": "pending", "estimated_time": "~1 min"},
            ]
        
        return steps
    
    async def _execute_nsfc_step(self, step: dict, nsfc_vars: dict) -> dict:
        """执行单个NSFC步骤"""
        tool_name = step['tool']
        sa = self.nsfc_prep_analyzer
        result = {"content": "", "status": "done"}
        
        try:
            if tool_name == "translate_extract":
                # 翻译并提取关键词
                await sa.translate_user_input()
                logger.info(f"翻译完成: CN={sa.query_params.get('user_input_cn', '')}, EN={sa.query_params.get('user_input_en', '')}")
                
                await sa.extract_and_expand_keywords()
                keywords = sa.query_params.get('keywords', [])
                logger.info(f"关键词提取及扩写完成: {len(keywords)} 个关键词")
                
                result['content'] = ("## 写作意图解析已完成\n\n"
                                   f"- 根据您的描述，系统提炼出的核心主题/关键词：{', '.join(keywords)}\n")
                nsfc_vars['keywords'] = keywords
                
            elif tool_name == "search_nsfc":
                # 国自然项目检索
                nsfc_projects = sa.run_search_nsfc(start_year=2019, end_year=2024, top_k=50)
                project_count = len(nsfc_projects)
                logger.info(f"相关基金项目已检索完成，共 {project_count} 项")
                
                projects_preview = self._build_nsfc_preview(nsfc_projects, max_items=5)
                result['content'] = projects_preview
                nsfc_vars['nsfc_projects'] = nsfc_projects
                nsfc_vars['project_count'] = project_count
                
            elif tool_name == "analyze_nsfc_overview":
                # 国自然项目分析 - 整体研究格局
                nsfc_projects = nsfc_vars.get('nsfc_projects', [])
                nsfc_statistics = sa.prepare_nsfc_projects_statistics(score_threshold=15.0)
                nsfc_statistics_json = json.dumps(nsfc_statistics, ensure_ascii=False, indent=2)
                nsfc_sample_projects = sa.prepare_related_nsfc_projects(max_projects_for_llm=30)
                nsfc_sample_projects_json = json.dumps(nsfc_sample_projects, ensure_ascii=False, indent=2)
                
                nsfc_overview = await sa.generate_nsfc_overview_insights(nsfc_statistics_json, nsfc_sample_projects_json)
                result['content'] = "## 相关基金项目分布\n\n" + nsfc_overview
                
                nsfc_vars['nsfc_statistics_json'] = nsfc_statistics_json
                nsfc_vars['nsfc_sample_projects_json'] = nsfc_sample_projects_json
                nsfc_vars['nsfc_overview'] = nsfc_overview
                
            elif tool_name == "analyze_nsfc_mechanism":
                # 国自然项目分析 - 重点研究路径
                nsfc_statistics_json = nsfc_vars.get('nsfc_statistics_json', '')
                nsfc_sample_projects_json = nsfc_vars.get('nsfc_sample_projects_json', '')
                
                nsfc_mechanism = await sa.generate_nsfc_mechanism_insights(nsfc_statistics_json, nsfc_sample_projects_json)
                result['content'] = "## 相关基金项目重点研究路径\n\n" + nsfc_mechanism
                nsfc_vars['nsfc_mechanism'] = nsfc_mechanism
                
            elif tool_name == "analyze_nsfc_gap":
                # 国自然项目分析 - 研究空白与机会
                nsfc_statistics_json = nsfc_vars.get('nsfc_statistics_json', '')
                nsfc_sample_projects_json = nsfc_vars.get('nsfc_sample_projects_json', '')
                nsfc_overview = nsfc_vars.get('nsfc_overview', '')
                nsfc_mechanism = nsfc_vars.get('nsfc_mechanism', '')
                
                nsfc_gap = await sa.generate_nsfc_insights(
                    nsfc_statistics_json, nsfc_sample_projects_json, nsfc_overview, nsfc_mechanism
                )
                result['content'] = "## 相关基金项目研究空白与机会\n\n" + nsfc_gap
                nsfc_vars['nsfc_gap'] = nsfc_gap
                
            elif tool_name == "search_pubmed":
                # PubMed检索
                user_input_for_search = sa.query_params.get('user_input_en', '') or sa.query_params.get('user_input', '')
                pubmed_records = sa.run_search_pubmed(user_input=user_input_for_search, top_k=50)
                logger.info(f"PubMed检索完成: {len(pubmed_records)} 篇文献")
                
                pubmed_preview = self._build_pubmed_preview(pubmed_records, max_items=5)
                result['content'] = pubmed_preview
                nsfc_vars['pubmed_records'] = pubmed_records
                
            elif tool_name == "analyze_pubmed":
                # PubMed文献分析
                pubmed_records = nsfc_vars.get('pubmed_records', [])
                if pubmed_records:
                    pubmed_overview = await sa.generate_pubmed_overview_insights(pubmed_records)
                    result['content'] = "## PubMed文献分析\n\n" + pubmed_overview
                    sa.pubmed_insights = pubmed_overview
                else:
                    result['content'] = "未检索到PubMed文献，跳过分析。"
                    sa.pubmed_insights = "未检索到PubMed文献"
                
            elif tool_name == "generate_titles":
                # 生成候选题目及研究方案
                # 确保文档已解析（如果有的话）
                if not hasattr(sa, 'summarized_docs') or sa.summarized_docs is None:
                    sa.summarized_docs = nsfc_vars.get('summarized_docs_text', "用户未提供前期研究基础文档")
                
                blueprints = await sa.generate_nsfc_project_blueprints(summarized_docs=self.summarized_docs)
                blueprints_preview = self._build_blueprints_preview(blueprints)
                self.nsfc_project_preview = blueprints_preview
                
                # 自动选择第一个题目
                selected_blueprint_msg = sa.select_blueprint(0)
                result['content'] = blueprints_preview + f"\n\n{selected_blueprint_msg}\n"
                nsfc_vars['blueprints'] = blueprints
                
            elif tool_name == "generate_outline":
                # 生成申请书大纲
                outline = await sa.generate_nsfc_proposal_outline(model=sa.model)
                self.nsfc_proposal_outline = outline
                outline_preview = self._build_proposal_outline_preview(outline)
                result['content'] = outline_preview
                nsfc_vars['outline'] = outline
                
            elif tool_name == "write_lixiang_part1":
                # 立项依据撰写（第1部分）
                pubmed_records = sa.build_pubmed_pool()
                literature_snippets = sa.build_literature_snippets(pubmed_records)
                lixiang_yiju = await sa.generate_lixiang_yiju_parts(literature_snippets)
                sa.lixiang_yiju = lixiang_yiju
                
                lixiang_yiju_preview = sa._render_markdown(lixiang_yiju, root_title="1. 项目的立项依据")
                result['content'] = lixiang_yiju_preview
                nsfc_vars['lixiang_yiju'] = lixiang_yiju
                
            elif tool_name == "write_lixiang_other":
                # 立项依据后续章节（第2-5部分）
                lixiang_yiju_other = await sa.generate_lixiang_yiju_other_parts(model=sa.model)
                sa.lixiang_yiju_other = lixiang_yiju_other
                
                lixiang_yiju_other_preview = sa._render_markdown(lixiang_yiju_other)
                result['content'] = lixiang_yiju_other_preview
                nsfc_vars['lixiang_yiju_other'] = lixiang_yiju_other
                
            elif tool_name == "write_research_basis":
                # 研究基础撰写
                research_basis = await sa.generate_yanjiu_jichu_parts()
                sa.research_basis = research_basis
                
                research_basis_preview = sa._render_markdown(research_basis, root_title="二、研究基础与工作条件")
                result['content'] = research_basis_preview
                nsfc_vars['research_basis'] = research_basis
                
            elif tool_name == "write_other_info":
                # 其他说明撰写
                qita_shuoming = await sa.generate_qita_shuoming_parts()
                sa.qita_shuoming = qita_shuoming
                
                qita_shuoming_preview = sa._render_markdown(qita_shuoming, root_title="三、其他需要说明的情况")
                result['content'] = qita_shuoming_preview
                nsfc_vars['qita_shuoming'] = qita_shuoming
                
            else:
                result['status'] = 'error'
                result['content'] = f"未知的步骤: {tool_name}"
                
        except Exception as e:
            result['status'] = 'error'
            result['content'] = f"步骤执行失败: {str(e)}"
            logger.error(f"Step {tool_name} failed: {e}")
            logger.debug(traceback.format_exc())
        
        return result
    
    async def use_tool(self, user_prompt: str = "", history_messages: List[dict] = [], 
                       planning_task: dict = {}, feedback: str = '', hitl_mode: str = '', **kwargs):
        """
        主执行方法，按照 planning_paper.py 的风格重构
        """
        # 初始化参数
        question = planning_task.get('question', user_prompt) or ''
        user = planning_task.get('user', 'unknown')
        task_id = planning_task.get('id', 'unknown')
        self.thread_id = planning_task.get('thread_id', 'unknown')
        download_link = kwargs.get('download_link', True)
        
        # 获取或初始化 nsfc_vars
        nsfc_vars = planning_task.get('nsfc_vars', {})
        
        # 设置输出路径
        question_prefix = question[:20].replace(' ', '_')
        safe_prefix = urllib.parse.quote(question_prefix)
        object_path = f"nsfc/{user}/{task_id}/{question_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        encoded_object_path = f"nsfc/{user}/{task_id}/{safe_prefix}..._{datetime.now().strftime('%Y%m%d_%H%M')}_NoahAI"
        self.output_dir = f"outputs/" + object_path
        sa = self.nsfc_prep_analyzer
        sa.set_output_dir(self.output_dir)
        
        # 存储配置
        STORAGE_DEST = 'azure'
        bucket_name = "noahai-userdata-test" if STORAGE_DEST == 'hw' else 'nudata'
        
        # 获取审批状态
        approve = kwargs.get('approve', None)
        should_replan = (approve is False)
        
        # 处理反馈
        past_feedback = planning_task.get('feedback', [])
        total_feedback = past_feedback + [feedback] if feedback else past_feedback
        
        # 语言设置
        from i18n.languages import normalize as _norm
        self.language = _norm(kwargs.get('language', '') or planning_task.get('language', '') or 'zh-CN')
        
        # 获取计划和当前步骤
        plan = planning_task.get('plan', [])
        current_step = planning_task.get('current_step', 0)
        if not current_step and plan:
            current_step = 1
        
        # HITL 模式
        hitl_mode = hitl_mode or planning_task.get('hitl_mode', '') or 'never'
        
        # 获取当前工具
        current_tool = {}
        if plan and current_step <= len(plan):
            current_tool = plan[current_step - 1].copy()
        
        should_run = bool(plan and not should_replan)
        
        # 构建返回对象
        ret = {
            'tool_uses': [], 
            'type': 'chat', 
            'agent': 'nsfc_planning',
            'hitl_mode': hitl_mode,
            'sender': 'assistant',
            'current_step': current_step,
            'current_tool': current_tool,
            'feedback': total_feedback,
            'nsfc_vars': nsfc_vars
        }
        
        # 如果有当前工具且没有错误，发送确认
        if current_tool and current_tool.get('status', 'error') != 'error':
            async for _ret in send_confirm_tool(ret, feedback, should_run):
                yield _ret
        
        # 如果是 never 模式，直接运行
        if hitl_mode == 'never':
            should_run = True
        
        ret['saveChat'] = False
        
        # 首次执行：初始化计划
        if not plan or len(plan) <= 1:
            ret['type'] = 'planUpdate'
            ret['current_step'] = current_step = 1
            plan_reason = "初始化国自然申请书写作计划" if self.language == 'zh-CN' else "Initialize NSFC proposal writing plan"
            ret['current_tool'] = {
                "tool": "Initialize-Plan", 
                'status': 'doing', 
                'startedAt': int(time.time()), 
                "reason": plan_reason
            }
            ret['plan'] = plan = [ret['current_tool']]
            async for _ret in send_message_and_save(ret):
                yield _ret
            
            # 处理用户文档（如果有）
            params = kwargs.get('params', {})
            files = await self.get_raw_files(params.get('files', {}))
            if files:
                logger.info(f"开始处理用户文档，共 {len(files)} 个文件")
                try:
                    summarized_docs = await self._process_user_docs(files)
                    self.summarized_docs = summarized_docs
                    
                    # 将文档列表格式化为简短摘要字符串
                    brief_parts = []
                    for idx, doc in enumerate(summarized_docs[:5], 1):
                        name = doc.get('name', f'文档{idx}')
                        summary = doc.get('summary', '')
                        if summary:
                            summary_brief = summary[:300] + ('...' if len(summary) > 300 else '')
                            brief_parts.append(f"{idx}. {name}\n   {summary_brief}")
                    nsfc_vars['summarized_docs_text'] = "\n\n".join(brief_parts) if brief_parts else "用户提供了文档但摘要为空"
                    sa.summarized_docs = nsfc_vars['summarized_docs_text']
                except Exception as e:
                    logger.warning(f"用户文档解析失败: {e}")
                    nsfc_vars['summarized_docs_text'] = "用户未提供前期研究基础文档"
                    sa.summarized_docs = "用户未提供前期研究基础文档"
            else:
                nsfc_vars['summarized_docs_text'] = "用户未提供前期研究基础文档"
                sa.summarized_docs = "用户未提供前期研究基础文档"
            
            # 初始化 NSFC 写作步骤
            nsfc_steps = self._initialize_nsfc_plan()
            plan += nsfc_steps
            
            # 标记初始化完成
            plan[current_step - 1]['status'] = 'done'
            current_step += 1
            ret['current_step'] = current_step
            current_tool = plan[current_step - 1]
            ret['plan'] = plan
            ret['type'] = 'planUpdate'
            async for _ret in send_message_and_save(ret):
                yield _ret
        
        ret.pop("plan", None)
        
        # 验证计划
        if not plan:
            ret["error"] = "Planning failed"
            yield ret
            return
        
        if current_step - 1 >= len(plan):
            ret["error"] = "All steps completed"
            yield ret
            return
        
        if not current_tool:
            current_tool = plan[current_step - 1].copy()
        
        ret['current_tool'] = current_tool
        
        # 执行步骤循环
        while should_run:
            async for _ret in send_agent_status_update(ret, 'running'):
                yield _ret
            
            ret['type'] = 'chat'
            current_tool = plan[current_step - 1]
            
            try:
                # 执行当前步骤
                step_result = await self._execute_nsfc_step(current_tool, nsfc_vars)
                current_tool['result'] = step_result['content']
                current_tool['status'] = step_result['status']
                
                ret['message'] = step_result['content']
                ret['nsfc_vars'] = nsfc_vars
                async for _ret in send_message_and_save(ret):
                    yield _ret
                
                # 标记步骤完成
                if current_step < len(plan):
                    plan[current_step - 1]['status'] = "done"
                    plan[current_step - 1]['finishedAt'] = int(time.time())
                
                # 发送计划更新
                ret['plan'] = plan
                yield ret
                
            except Exception as e:
                traceback.print_exc()
                logger.error(f"Error in NSFC step {current_tool['tool']}: {e}")
                current_tool['status'] = "error"
                current_tool['result'] = str(e)
                ret['error'] = str(e)
                yield ret
                return
            
            # 检查停止信号
            if self.stopped:
                plan[-1]['status'] = 'error'
                plan[-1]['result'] = ret.get('message', '')
                ret['plan'] = plan
                async for _ret in send_plan_update(ret):
                    yield _ret
                return
            
            # 处理结果格式
            result_content = False
            if type(current_tool['result']) == dict and 'content' in current_tool['result']:
                result_content = True
            
            # 最后一步：导出并上传
            if current_step == len(plan):
                try:
                    # 导出完整申请书
                    await self._export_full_proposal(sa, nsfc_vars)
                    logger.info("申请书导出完成")
                    
                    if download_link:
                        await self.upload_archive(f"{object_path}.zip", bucket_name, STORAGE_DEST)
                        ret['attachments_key'] = f"{self.output_dir}.zip"
                        
                        if STORAGE_DEST == 'hw':
                            download_url = f"https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{encoded_object_path}.zip"
                        else:
                            download_url = f"https://noahdata.blob.core.windows.net/{bucket_name}/{encoded_object_path}.zip"
                        
                        download_text = "\n\n" + ("## 下载链接：[国自然申请书完整包]" if self.language == 'zh-CN' else "## Download link: [NSFC Application Package]") + f"({download_url})"
                        
                        if result_content:
                            current_tool['result']['content'] += download_text
                        else:
                            current_tool['result'] += download_text
                        
                except Exception as e:
                    trace = traceback.format_exc()
                    logger.error(f"Error in export/upload: {trace}")
            
            # 更新步骤状态
            current_tool['status'] = 'done'
            if isinstance(current_tool['result'], str):
                full_result = current_tool['result']
            else:
                full_result = str(current_tool['result'].get('content', ''))
            
            ret['message'] = full_result
            async for _ret in send_message_and_save(ret):
                yield _ret
            
            ret.pop('message', '')
            
            # 更新计划状态
            ret['type'] = 'planUpdate'
            ret.pop('attachments_key', '')
            plan[current_step - 1]['status'] = 'done'
            
            if len(plan) > current_step:
                plan[current_step]['status'] = 'doing'
                plan[current_step]['startedAt'] = int(time.time())
            
            ret['plan'] = plan
            async for _ret in send_message_and_save(ret):
                yield _ret
            
            # 移动到下一步
            current_step += 1
            ret['current_step'] = current_step
            
            if current_step - 1 >= len(plan):
                should_run = False
                break
            
            if hitl_mode == 'always':
                should_run = False
            
            current_tool = plan[current_step - 1].copy()
            ret['current_tool'] = current_tool
        
        # 发送最终状态
        if current_step - 1 < len(plan):
            ret['type'] = 'statusUpdate'
            ret['agentStatus'] = 'waiting'
        else:
            ret['type'] = 'statusUpdate'
            ret['agentStatus'] = 'stopped'
            if 'taskStart' in planning_task:
                ret['taskStart'] = planning_task['taskStart']
            ret.pop('current_tool', None)
        
        async for _ret in send_message_and_save(ret):
            yield _ret
    
    async def upload_archive(self, object_path, bucket_name, source='azure'):
        """上传压缩包到云存储"""
        if source == 'hw':
            from utils.obs.client import upload_file
        else:
            from utils.azure.blob_client import upload_file
        
        zip_path = f"{self.output_dir}.zip"
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        
        shutil.make_archive(self.output_dir, 'zip', self.output_dir)
        logger.info(f"Output saved to {zip_path}")
        
        for _ in range(3):
            res = upload_file(bucket_name, object_path, zip_path)
            if res:
                logger.info(f"File {zip_path} uploaded successfully")
                # 清理本地文件
                try:
                    os.remove(zip_path)
                    shutil.rmtree(self.output_dir)
                    logger.info(f"Cleaned up {zip_path} and {self.output_dir}")
                except Exception as e:
                    logger.error(f"Failed to clean up files: {str(e)}")
                break
            await asyncio.sleep(3)
        else:
            logger.error(f"Failed to upload {zip_path}")
    
    async def _export_full_proposal(self, sa, nsfc_vars):
        """导出完整的Markdown和Word文档"""
        markdown_parts = []
        
        # 标题和项目信息
        blueprint = getattr(sa, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "国自然申请书")
        markdown_parts.append(f"# {title}\n")
        
        # 添加项目基本信息
        fund_type = sa.query_params.get('fund_type', '面上项目')
        duration_years = sa.query_params.get('duration_years', 3)
        markdown_parts.append(f"**项目类型：** {fund_type}\n")
        markdown_parts.append(f"**研究期限：** {duration_years}年\n")
        markdown_parts.append(f"**生成时间：** {datetime.now().strftime('%Y年%m月%d日')}\n")
        markdown_parts.append("\n---\n\n")
        
        # 获取各章节内容
        lixiang_yiju = nsfc_vars.get('lixiang_yiju') or getattr(sa, "lixiang_yiju", None)
        lixiang_yiju_other = nsfc_vars.get('lixiang_yiju_other') or getattr(sa, "lixiang_yiju_other", None)
        research_basis = nsfc_vars.get('research_basis') or getattr(sa, "research_basis", None)
        qita_shuoming = nsfc_vars.get('qita_shuoming') or getattr(sa, "qita_shuoming", None)
        
        # 组装完整的Markdown
        full_markdown = "".join(markdown_parts)
        
        if lixiang_yiju:
            full_markdown += "\n\n" + sa._render_markdown(lixiang_yiju, root_title="1. 项目的立项依据")
        
        if lixiang_yiju_other:
            full_markdown += "\n\n" + sa._render_markdown(lixiang_yiju_other)
        
        if research_basis:
            full_markdown += "\n\n" + sa._render_markdown(research_basis, root_title="二、研究基础")
        
        if qita_shuoming:
            full_markdown += "\n\n" + sa._render_markdown(qita_shuoming, root_title="三、其他说明")
        
        # 保存Markdown文件
        markdown_path = os.path.join(self.output_dir, "国自然申请书.md")
        os.makedirs(self.output_dir, exist_ok=True)
        
        with open(markdown_path, 'w', encoding='utf-8') as f:
            f.write(full_markdown)
        
        logger.info(f"Markdown文件已保存: {markdown_path}")
        
        # 生成Word文档
        try:
            from agent.nsfc.nsfc_docx_exporter import NSFCDocxExporter
            
            # 智能检测并选择最匹配的模板
            template_path = NSFCDocxExporter.auto_select_template(markdown_path)
            
            if os.path.exists(template_path):
                exporter = NSFCDocxExporter(template_path=template_path)
                
                # 准备章节内容
                chapter1_parts = []
                if lixiang_yiju:
                    chapter1_parts.extend(lixiang_yiju if isinstance(lixiang_yiju, list) else [])
                if lixiang_yiju_other:
                    chapter1_parts.extend(lixiang_yiju_other if isinstance(lixiang_yiju_other, list) else [])
                
                chapter2_parts = research_basis if isinstance(research_basis, list) else []
                chapter3_parts = qita_shuoming if isinstance(qita_shuoming, list) else []
                
                # 填充各章节
                if chapter1_parts:
                    exporter.fill_chapter1(chapter1_parts)
                if chapter2_parts:
                    exporter.fill_chapter2(chapter2_parts)
                if chapter3_parts:
                    exporter.fill_chapter3(chapter3_parts)
                
                word_path = os.path.join(self.output_dir, "国自然申请书.docx")
                exporter.save(word_path)
                logger.info(f"Word文档已保存: {word_path}")
            else:
                logger.warning(f"Word模板不存在: {template_path}")
                
        except Exception as e:
            logger.warning(f"Word文档生成失败: {e}")
            logger.debug(traceback.format_exc())
    
    async def _process_user_docs(self, django_files):
        """处理用户上传的文档"""
        da = self.nsfc_docs_analyzer
        da.load_raw_files_from_request(django_files)
        
        await da.convert_documents()
        await da.batch_summarize_docs()
        
        return da.summarized_docs
    
    async def get_raw_files(self, files: list[str]) -> list:
        """从URL下载文件"""
        attachments = self.attachment_manager.fetch_attachments(files)
        downloaded_files = []
        
        for attachment in attachments:
            title = attachment.get('name', '')
            url = attachment.get('url', '')
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=title) as temp_file:
                    temp_path = temp_file.name
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        data = await response.read()
                        with open(temp_path, 'wb') as f:
                            f.write(data)
                
                downloaded_files.append((title, temp_path))
            except Exception as e:
                logger.warning(f"Load file failed: {e}")
        
        return downloaded_files
    
    # 以下是格式化预览方法（从原 nsfc_writing_agent.py 复用）
    def _build_nsfc_preview(self, nsfc_projects: List[Dict[str, Any]], max_items: int = 5):
        """构建国自然项目预览"""
        if not nsfc_projects:
            return "当前未检索到相关国自然基金项目。"
        
        total = len(nsfc_projects)
        show_n = min(max_items, total)
        lines: List[str] = []
        
        lines.append("## 相关国自然基金项目概览\n")
        lines.append(
            f"已根据您的研究主题检索到 {total} 项相关国自然基金项目。"
            f"下方优先展示前 {show_n} 项代表性项目，便于您快速了解该方向的资助布局和研究重点。\n"
        )
        
        for idx, project in enumerate(nsfc_projects[:show_n], start=1):
            project_name = project.get("projectName") or "未命名项目"
            project_admin = project.get("projectAdmin") or "未知负责人"
            keywords = project.get("keywordList") or []
            depend_unit = project.get("dependUnit") or "未知单位"
            approval_year = (str(project.get("researchTimeStart")).split("-")[0] if project.get("researchTimeStart") else "未知起始时间")
            completed_year = (str(project.get("researchTimeEnd")).split("-")[0] if project.get("researchTimeEnd") else "未知结束时间")
            abstract = project.get("projectAbstractC") or "暂无摘要信息"
            conclusion = project.get("conclusionAbstract") or "暂无结题摘要"
            
            if isinstance(keywords, (list, tuple)):
                kw_list = [str(k).strip() for k in keywords if k]
            else:
                kw_list = [str(keywords).strip()] if keywords else []
            
            lines.append(f"### {idx}）{project_name}")
            lines.append(f"- 负责人：{project_admin}")
            lines.append(f"- 立项年份：{approval_year}")
            lines.append(f"- 结题年份：{completed_year}")
            lines.append(f"- 依托单位：{depend_unit}")
            lines.append(f"- 关键词：{'；'.join(kw_list) if kw_list else '暂无关键词'}")
            lines.append("")
            lines.append(f"**项目摘要：**{abstract}")
            if conclusion and conclusion != "暂无结题摘要":
                lines.append("")
                lines.append(f"**结题摘要：**{conclusion}")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_pubmed_preview(self, pubmed_records: List[Dict[str, Any]], max_items: int = 5):
        """构建PubMed文献预览"""
        if not pubmed_records:
            return "当前未检索到相关PubMed文献。"
        
        total = len(pubmed_records)
        show_n = min(max_items, total)
        lines: List[str] = []
        
        lines.append("## 相关PubMed文献概览\n")
        lines.append(
            f"已根据您的研究主题检索到 {total} 篇相关PubMed文献。"
            f"下方优先展示前 {show_n} 篇代表性文献，便于您快速了解该方向的最新研究进展和热点。\n"
        )
        
        for idx, record in enumerate(pubmed_records[:show_n], start=1):
            pmid = record.get("pmid") or "未知PMID"
            title = record.get("title") or "未命名文献"
            journal = record.get("journal") or "未知期刊"
            year = record.get("year_of_publication") or "未知年份"
            abstract = record.get("abstract") or "暂无摘要信息"
            
            lines.append(f"### {idx}）{title} ({year})")
            lines.append(f"- PMID：{pmid}")
            lines.append(f"- 期刊：{journal}")
            lines.append("")
            lines.append(f"**摘要：**{abstract}")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_blueprints_preview(self, blueprints) -> str:
        """构建备选课题方案预览"""
        if not blueprints:
            return "当前未生成任何国自然备选课题方案"
        
        total = len(blueprints)
        lines = []
        lines.append("## 国自然备选课题方案预览\n")
        lines.append(
            f"已根据您的研究方向生成 {total} 个备选课题方案，"
            f"包含题目、立项理由、研究目标和创新点，便于您后续筛选和修改。\n"
        )
        
        for idx, bp in enumerate(blueprints, start=1):
            title = bp.get("title") or f"未命名备选课题方案 {idx}"
            rationale = (bp.get("rationale") or "").strip()
            objectives = bp.get("objectives") or []
            contents = bp.get("contents") or []
            methods = bp.get("methods") or []
            innovations = bp.get("innovations") or []
            
            lines.append(f"### {idx}）{title}")
            
            if rationale:
                lines.append(f"**立项理由：**{rationale}")
                lines.append("")
            
            if objectives:
                lines.append("**研究目标：**")
                for o in objectives:
                    lines.append(f"- {o}")
                lines.append("")
            
            if contents:
                lines.append("**研究内容：**")
                for c in contents:
                    lines.append(f"- {c}")
                lines.append("")
            
            if methods:
                lines.append("**拟采用方法：**")
                for m in methods:
                    lines.append(f"- {m}")
                lines.append("")
            
            if innovations:
                lines.append("**创新点：**")
                for inn in innovations:
                    lines.append(f"- {inn}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_proposal_outline_preview(self, outline: list, max_level: int = 4) -> str:
        """构建申请书大纲预览"""
        if not outline:
            return "当前尚未生成国自然写作大纲。"
        
        lines = []
        lines.append("## 国自然申请书写作大纲预览\n")
        
        def render_node(node: dict):
            title = node.get("title", "").strip()
            level = int(node.get("level", 1))
            bullets = node.get("bullets") or []
            children = node.get("children") or []
            
            if level > max_level:
                return
            
            if level == 1:
                lines.append(f"### {title}")
            elif level == 2:
                lines.append(f"#### {title}")
            elif level == 3:
                lines.append(f"##### {title}")
            else:
                lines.append(f"###### {title}")
            
            if bullets:
                for b in bullets:
                    b = str(b).strip()
                    if not b:
                        continue
                    lines.append(f"- {b}")
            
            for child in children:
                render_node(child)
            
            lines.append("")
        
        for root in outline:
            render_node(root)
        
        return "\n".join(lines)


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