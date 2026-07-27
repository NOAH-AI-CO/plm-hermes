import asyncio
import io
import json
import logging
import time
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Type, AsyncGenerator
from dataclasses import dataclass

from agent.paper_writing.writing.base_writer import BaseWriter

from ..schema.document_insight import OrganizedData
from ..schema.data_insight import DatasetAnalysisResult
from ..schema.writing import WritingInput, SectionSpecificationManager
from ..schema.manuscript import Section, ManuscriptStatus, ManuscriptProfile, ManuscriptOutline
from ..utils.writing import create_writing_input
from ..presets.template import WRITING_ORDER

from .section_writers import (
    MethodsWriter, ResultsWriter, IntroductionWriter, DiscussionWriter,
    AbstractWriter, BackgroundWriter, ConclusionsWriter, MainTopicsWriter
)

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.composite_models import MedicalPaperWritingModels
# from utils.core.standardize import standardize_yield  # 移除这个导入

logger = logging.getLogger(__name__)

# 写作工具映射
WRITING_TOOL_MAPPING = {
    "Methods": MethodsWriter,
    "Results": ResultsWriter,
    "Introduction": IntroductionWriter,
    "Discussion": DiscussionWriter,
    "Abstract": AbstractWriter,
    "Background": BackgroundWriter,
    "Conclusions": ConclusionsWriter,
    "Main-Topics": MainTopicsWriter,
}

# 写作状态
WRITING_STATUS = {
    "todo": "待写作",
    "doing": "写作中", 
    "done": "已完成",
    "error": "错误"
}

@dataclass
class WritingStep:
    tool: str
    status: str = "todo"
    started_at: int = 0
    reason: str = ""
    result: str = ""
    params: Optional[Dict[str, Any]] = None
    word_count: int = 0
    section_name: str = ""
    
    def __post_init__(self):
        if self.params is None:
            self.params = {}

class MedicalWritingAgent(AgentPreset):
    # Class-level default configurations
    writing_llm: BaseLLM = MedicalPaperWritingModels
    polishing_llm: BaseLLM = MedicalPaperWritingModels
    language: str = "en-US"
    max_steps: int = 10
    enable_reflection: bool = True
    output_dir: str = "outputs/"
    
    # 实例状态属性
    sections: List[Section] = []
    writing_steps: List[dict] = []
    current_step: int = 0
    stopped: bool = False
    
    def _initialize_writing_plan(self, profile: ManuscriptProfile):
        study_type = profile.study_type
        publication_type = profile.publication_type
        writing_order = WRITING_ORDER.get((study_type, publication_type), [])
        
        section_names = [name for name in writing_order if name not in ["Title", "References"]]
        
        writing_steps = []
        for i, section_name in enumerate(section_names):
            step = {
                'tool': section_name,
                'status': "todo",
                'started_at': 0,
                'reason': self._get_section_reason(section_name),
                'section_name': section_name
            }
            writing_steps.append(step)
        
        if writing_steps:
            writing_steps[0]['status'] = "doing"
            writing_steps[0]['started_at'] = int(time.time())

        logger.info(f"Initialized {len(writing_steps)} writing steps: {[step['tool'] for step in writing_steps]}")
        return writing_steps
    
    def _get_section_reason(self, section_name: str) -> str:
        if self.language == "zh-CN":
            reasons = {
                "Introduction": "介绍研究背景、目的和意义",
                "Methods": "详细描述研究方法和实验设计",
                "Results": "客观呈现研究结果和数据分析",
                "Discussion": "深入讨论结果意义和与文献的对比",
                "Abstract": "简洁概括整个研究内容",
                "Background": "简要介绍研究背景和问题",
                "Conclusions": "总结主要发现和研究意义",
                "Main-Topics": "系统梳理研究领域的主要主题"
            }
        else:
            reasons = {
                "Introduction": "Introduce research background, objectives and significance",
                "Methods": "Detail research methods and experimental design", 
                "Results": "Objectively present research results and data analysis",
                "Discussion": "Deeply discuss result significance and literature comparison",
                "Abstract": "Concisely summarize the entire research content",
                "Background": "Briefly introduce research background and problems",
                "Conclusions": "Summarize main findings and research significance",
                "Main-Topics": "Systematically review main topics in the research field"
            }
        
        return reasons.get(section_name, f"Write {section_name} section")
    
    async def use_tool(self, user_prompt: str, **kwargs):
        """
        执行写作工作流
        
        Args:
            user_prompt: 用户提示
            **kwargs: 包含 profile, outline, dataset_analyses, document_contents, progress_callback 等
        """
        logger.info("Starting full paper writing workflow...")

        # 从kwargs中提取参数
        profile = kwargs.get('profile')
        outline = kwargs.get('outline')
        dataset_analyses = kwargs.get('dataset_analyses', [])
        document_contents = kwargs.get('document_contents', [])
        progress_callback = kwargs.get('progress_callback')
        # language使用类级别配置，但可以通过kwargs覆盖
        language = kwargs.get('language', self.language)
        
        # 验证必需参数
        if not profile:
            raise ValueError("profile is required")
        if not outline:
            raise ValueError("outline is required")
        
        # 初始化状态（使用实例属性）
        self.sections = []
        self.writing_steps = []
        self.current_step = 0
        version: int = 0
        self.stopped = False
        
        if profile:
            self.writing_steps = self._initialize_writing_plan(profile)
            logger.info(f"Medical Writing Agent initialized for {profile.study_type.value} - {profile.publication_type.value}")
        
        # 初始化返回数据
        ret = {
            'type': 'writing',
            'agent': 'full_paper_workflow',
            'sender': 'assistant',
            'current_step': self.current_step,
            'writing_steps': self.writing_steps,
            'version': version,
            'language': language
        }
        
        # 发送初始状态
        yield ret
        
        # 执行写作步骤
        while self.current_step < len(self.writing_steps) and not self.stopped:
            current_step_obj = self.writing_steps[self.current_step]
            
            # 更新状态
            ret['current_step'] = self.current_step
            ret['current_tool'] = {
                'tool': current_step_obj['tool'],
                'status': current_step_obj['status'],
                'reason': current_step_obj['reason'],
                'section_name': current_step_obj['section_name']
            }

            yield ret
            
            try:
                # 执行当前写作步骤
                async for step_result in self._execute_writing_step(current_step_obj, profile, outline, dataset_analyses, document_contents, self.sections):
                    ret.update(step_result)
                    yield ret
                
                # 标记步骤完成
                current_step_obj['status'] = "done"
                current_step_obj['result'] = ret.get('message', '')
                
                # 更新进度
                self.current_step += 1
                if self.current_step < len(self.writing_steps):
                    self.writing_steps[self.current_step]['status'] = "doing"
                    self.writing_steps[self.current_step].started_at = int(time.time())
                
                # 发送步骤完成状态
                ret['writing_steps'] = self.writing_steps
                yield ret
                
                # 调用进度回调
                if progress_callback:
                    progress_callback({
                        'current_step': self.current_step,
                        'total_steps': len(self.writing_steps),
                        'completed_sections': self.current_step,
                        'current_section': current_step_obj['section_name']
                    })
                
            except Exception as e:
                logger.error(f"Error in writing step {current_step_obj['tool']}: {e}")
                current_step_obj['status'] = "error"
                current_step_obj['result'] = str(e)
                ret['error'] = str(e)
                yield ret
                break
        
        # 发送完成状态
        ret['type'] = 'statusUpdate'
        ret['agentStatus'] = 'completed' if not self.stopped else 'stopped'
        yield ret
        
        logger.info("Full paper writing workflow completed")
    
    async def _execute_writing_step(self, step: dict, profile: ManuscriptProfile, outline: ManuscriptOutline, dataset_analyses: List[DatasetAnalysisResult], document_contents: List[Dict[str, Any]], sections: List[Section]) -> AsyncGenerator[Dict[str, Any], None]:
        logger.info(f"Executing writing step: {step['tool']}")
        
        try:
            writing_input = create_writing_input(profile, outline, dataset_analyses, document_contents)
        except Exception as e:
            logger.error(f"Failed to create writing input: {e}")
            # 手动转换数据集格式
            from ..utils.writing import convert_dataset_for_writing
            writing_datasets = [convert_dataset_for_writing(dataset) for dataset in dataset_analyses]
            
            writing_input = WritingInput(
                writing_purpose=profile.writing_purpose,
                study_type=profile.study_type.value,
                publication_type=profile.publication_type.value,
                target_journal=profile.writing_purpose.target_journal,
                outline=outline,
                dataset_info=writing_datasets or [],
                document_info=document_contents or [])

        completed_sections = {}
        for section in sections:
            if section.status == ManuscriptStatus.FINAL:
                completed_sections[section.name] = {
                    "content": section.content,
                    "status": section.status.value
                }
            
        writing_input.completed_sections = completed_sections

        section_settings = SectionSpecificationManager.get_section_specification(section_name=step['section_name'], writing_llm=self.writing_llm, polishing_llm=self.polishing_llm)
        
        # 创建对应的写作器
        writer_class = WRITING_TOOL_MAPPING.get(step['tool'])
        if not writer_class:
            logger.error(f"No writer found for section: {step['tool']}")
            yield {'error': f"No writer found for section: {step['tool']}"}
            return
        
        writer: BaseWriter = writer_class(section_settings)
        
        try:
            async for section_in_progress in writer.write_section(writing_input):
                yield {
                    'type': 'chat',
                    'message': section_in_progress.content,
                    'section_name': step['section_name'],
                    'word_count': section_in_progress.word_count,
                    'status': 'doing'
                }

            sections.append(section_in_progress)
            
            word_count = self._count_words(section_in_progress.content)
            step['word_count'] = word_count
            
            yield {
                'type': 'chat',
                'message': section_in_progress.content,
                'section_name': step['section_name'],
                'word_count': word_count,
                'status': 'done'
            }
            
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error writing section {step['tool']}: {e}")
            yield {'error': str(e)}
    
    def _count_words(self, content: str) -> int:
        """计算字数"""
        if not content:
            return 0
        words = content.split()
        return len(words)
    
    async def stop_writing(self):
        self.stopped = True
        logger.info("Writing workflow stopped by user")
    
    def get_writing_progress(self) -> Dict[str, Any]:
        """获取写作进度"""
        completed = sum(1 for step in self.writing_steps if step['status'] == "done")
        total = len(self.writing_steps)
        
        return {
            'total_steps': total,
            'completed_steps': completed,
            'current_step': self.current_step,
            'progress_percentage': (completed / total * 100) if total > 0 else 0,
            'current_section': self.writing_steps[self.current_step]['section_name'] if self.current_step < len(self.writing_steps) else None,
            'completed_sections': [step['section_name'] for step in self.writing_steps if step['status'] == "done"]
        }
    
    def get_completed_sections(self) -> List[Section]:
        """获取已完成的章节"""
        return self.sections.copy()
    
    def get_full_manuscript(self) -> str:
        """获取完整手稿"""
        if not self.sections:
            return ""
        
        manuscript_parts = []
        for section in self.sections:
            manuscript_parts.append(f"# {section.title}\n\n{section.content}")
        
        return "\n\n".join(manuscript_parts)
    
    async def _task_with_heartbeat(self, gen, interval: float = 0.3, stream=False):
        """
        带心跳的任务执行器，参考PlanningAgent的实现
        """
        buffer = io.StringIO()
        newest_chunk = None
        start_time = time.time()
        
        async def write_buffer():
            nonlocal newest_chunk
            async for chunk in gen:
                if not chunk:
                    continue
                if stream:
                    buffer.write(chunk)
                else:
                    if isinstance(chunk, str):
                        newest_chunk = chunk
                    elif isinstance(chunk, dict):
                        newest_chunk = chunk
        
        task = asyncio.create_task(write_buffer())
        
        while not task.done():
            if self.stopped:
                task.cancel()
                logger.info("Task cancelled due to stop signal.")
                break
            if stream:
                yield buffer.getvalue()
            elif newest_chunk:
                yield newest_chunk
            await asyncio.sleep(interval)
        
        await task
        end_time = time.time()
        
        if stream:
            yield buffer.getvalue()
        elif newest_chunk:
            yield newest_chunk
        
        logger.info(f"[_task_with_heartbeat] cost time total {end_time - start_time}s") 