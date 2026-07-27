#!/usr/bin/env python3
"""
独立的写作测试脚本
可以直接测试写作功能，使用已有的分析结果
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入必要的模块
from schema.writing import WritingInput, SectionSpecificationManager
from schema.manuscript import ManuscriptProfile, WritingPurposeDetail, ManuscriptOutline
from schema.data_insight import DatasetAnalysisResult
from schema.document_insight import DocumentContentType
from writing.full_paper_workflow_agent import MedicalWritingAgent
from presets.enum import StudyType, PublicationType, WritingPurpose

async def create_mock_analysis_results():
    """创建模拟的分析结果，用于测试写作功能"""
    
    # 创建手稿配置
    manuscript_profile = ManuscriptProfile(
        study_type=StudyType.RANDOMIZED_CONTROLLED_TRIAL,
        publication_type=PublicationType.PROTOCOL,
        writing_purpose=WritingPurposeDetail(
            purpose=WritingPurpose.PROTOCOL_DEVELOPMENT,
            description="开发一个随机对照试验的研究方案"
        ),
        target_journal="BMJ Open",
        language="zh"
    )
    
    # 创建手稿大纲
    manuscript_outline = ManuscriptOutline(
        title="随机对照试验研究方案",
        sections=[
            {
                "name": "Methods",
                "subsections": [
                    {
                        "title": "研究设计",
                        "word_estimate": "300-500字",
                        "key_points": ["随机对照设计", "双盲", "多中心"]
                    },
                    {
                        "title": "研究对象",
                        "word_estimate": "400-600字", 
                        "key_points": ["纳入标准", "排除标准", "样本量计算"]
                    },
                    {
                        "title": "干预措施",
                        "word_estimate": "300-500字",
                        "key_points": ["实验组干预", "对照组干预", "干预时间"]
                    }
                ]
            },
            {
                "name": "Introduction", 
                "subsections": [
                    {
                        "title": "研究背景",
                        "word_estimate": "400-600字",
                        "key_points": ["疾病负担", "现有治疗局限性", "研究必要性"]
                    },
                    {
                        "title": "研究目的",
                        "word_estimate": "200-300字",
                        "key_points": ["主要目的", "次要目的"]
                    }
                ]
            },
            {
                "name": "Abstract",
                "subsections": [
                    {
                        "title": "摘要",
                        "word_estimate": "250-300字",
                        "key_points": ["背景", "方法", "预期结果"]
                    }
                ]
            }
        ]
    )
    
    # 创建模拟的数据集分析结果
    dataset_analyses = [
        {
            "file_path": "mock_data.csv",
            "analysis_result": {
                "data_preview": [
                    {"id": 1, "group": "A", "age": 45, "score": 75},
                    {"id": 2, "group": "B", "age": 52, "score": 68},
                    {"id": 3, "group": "A", "age": 38, "score": 82}
                ],
                "data_structure": {
                    "id": "int64",
                    "group": "object", 
                    "age": "int64",
                    "score": "int64"
                },
                "analysis_summaries": [
                    "样本量：150例，实验组75例，对照组75例",
                    "年龄分布：35-65岁，平均年龄48.5岁",
                    "基线评分：实验组平均75.2分，对照组平均72.8分"
                ],
                "key_findings": [
                    "两组基线特征基本平衡",
                    "年龄分布符合预期",
                    "评分分布正常"
                ],
                "statistical_methods": [
                    "t检验用于连续变量比较",
                    "卡方检验用于分类变量比较",
                    "ANOVA用于多组比较"
                ]
            }
        }
    ]
    
    # 创建模拟的文档分析结果
    document_contents = [
        {
            "file_path": "protocol_draft.docx",
            "content_type": DocumentContentType.PROTOCOL,
            "extracted_content": {
                "title": "某药物疗效的随机对照试验研究方案",
                "abstract": "本研究旨在评估某药物在治疗特定疾病中的疗效和安全性...",
                "keywords": ["随机对照试验", "药物疗效", "安全性"],
                "authors": ["张三", "李四", "王五"],
                "raw_content": "完整的研究方案内容..."
            }
        }
    ]
    
    return {
        "manuscript_profile": manuscript_profile,
        "manuscript_outline": manuscript_outline,
        "dataset_analyses": dataset_analyses,
        "document_contents": document_contents
    }

async def test_writing_from_step(step_name: str = "Methods"):
    """从指定步骤开始测试写作"""
    
    logger.info(f"开始测试写作功能，从步骤 '{step_name}' 开始")
    
    # 创建模拟的分析结果
    analysis_results = await create_mock_analysis_results()
    
    # 创建写作代理
    writing_agent = MedicalWritingAgent()
    
    # 准备写作输入
    writing_input = WritingInput(
        writing_purpose=analysis_results["manuscript_profile"].writing_purpose,
        study_type=analysis_results["manuscript_profile"].study_type.value,
        publication_type=analysis_results["manuscript_profile"].publication_type.value,
        target_journal=analysis_results["manuscript_profile"].target_journal,
        outline=analysis_results["manuscript_outline"],
        dataset_info=analysis_results["dataset_analyses"],
        document_info=analysis_results["document_contents"],
        completed_sections={}  # 从指定步骤开始，没有已完成的章节
    )
    
    # 初始化写作计划，但只执行指定步骤
    writing_agent.writing_steps = writing_agent._initialize_writing_plan(analysis_results["manuscript_profile"])
    
    # 找到指定步骤的索引
    target_step_index = None
    for i, step in enumerate(writing_agent.writing_steps):
        if step.tool == step_name:
            target_step_index = i
            break
    
    if target_step_index is None:
        logger.error(f"未找到步骤 '{step_name}'")
        return
    
    # 设置从指定步骤开始
    writing_agent.current_step = target_step_index
    writing_agent.writing_steps[target_step_index].status = "doing"
    
    # 执行写作
    try:
        async for result in writing_agent.use_tool(
            user_prompt=f"请写作 {step_name} 章节",
            profile=analysis_results["manuscript_profile"],
            outline=analysis_results["manuscript_outline"],
            dataset_analyses=analysis_results["dataset_analyses"],
            document_contents=analysis_results["document_contents"],
            start_from_step=step_name
        ):
            if result.get('type') == 'chat' and result.get('message'):
                section_name = result.get('section_name', 'unknown')
                word_count = result.get('word_count', 0)
                logger.info(f"  {section_name} 章节完成 - {word_count} 字")
                
            elif result.get('type') == 'statusUpdate':
                status = result.get('agentStatus')
                if status == 'completed':
                    logger.info("  写作工作流完成")
                    break
                elif status == 'stopped':
                    logger.info("  写作工作流被停止")
                    break
                    
            elif result.get('error'):
                logger.error(f"  写作错误: {result['error']}")
                break
        
        # 获取完成的章节
        sections = writing_agent.get_completed_sections()
        logger.info(f"完成的章节: {[s.name for s in sections]}")
        
        # 保存结果
        for section in sections:
            output_file = f"output_{section.name.lower()}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"章节: {section.name}\n")
                f.write(f"字数: {section.word_count}\n")
                f.write("="*50 + "\n")
                f.write(section.content)
            logger.info(f"章节内容已保存到: {output_file}")
            
    except Exception as e:
        logger.error(f"写作过程错误: {e}")
        import traceback
        traceback.print_exc()

async def test_single_section_writer(section_name: str = "Methods"):
    """测试单个章节的写作器"""
    
    logger.info(f"测试单个章节写作器: {section_name}")
    
    # 创建模拟的分析结果
    analysis_results = await create_mock_analysis_results()
    
    # 获取章节配置
    section_spec = SectionSpecificationManager.get_section_specification(
        section_name=section_name,
        writing_llm=MedicalWritingAgent.writing_llm,
        polishing_llm=MedicalWritingAgent.polishing_llm
    )
    
    # 导入对应的写作器
    from writing.section_writers import (
        MethodsWriter, ResultsWriter, IntroductionWriter, DiscussionWriter,
        AbstractWriter, BackgroundWriter, ConclusionsWriter, MainTopicsWriter
    )
    
    writer_mapping = {
        "Methods": MethodsWriter,
        "Results": ResultsWriter,
        "Introduction": IntroductionWriter,
        "Discussion": DiscussionWriter,
        "Abstract": AbstractWriter,
        "Background": BackgroundWriter,
        "Conclusions": ConclusionsWriter,
        "Main-Topics": MainTopicsWriter,
    }
    
    if section_name not in writer_mapping:
        logger.error(f"未找到章节 '{section_name}' 对应的写作器")
        return
    
    writer_class = writer_mapping[section_name]
    writer = writer_class(section_spec)
    
    # 准备写作输入
    writing_input = WritingInput(
        writing_purpose=analysis_results["manuscript_profile"].writing_purpose,
        study_type=analysis_results["manuscript_profile"].study_type.value,
        publication_type=analysis_results["manuscript_profile"].publication_type.value,
        target_journal=analysis_results["manuscript_profile"].target_journal,
        outline=analysis_results["manuscript_outline"],
        dataset_info=analysis_results["dataset_analyses"],
        document_info=analysis_results["document_contents"],
        completed_sections={}
    )
    
    try:
        # 执行写作
        section = await writer.write_section(writing_input)
        
        logger.info(f"章节 '{section_name}' 写作完成")
        logger.info(f"字数: {section.word_count}")
        logger.info(f"内容预览: {section.content[:200]}...")
        
        # 保存结果
        output_file = f"output_{section_name.lower()}_single.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"章节: {section.name}\n")
            f.write(f"字数: {section.word_count}\n")
            f.write("="*50 + "\n")
            f.write(section.content)
        logger.info(f"章节内容已保存到: {output_file}")
        
    except Exception as e:
        logger.error(f"写作错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        step_name = sys.argv[1]
        if len(sys.argv) > 2 and sys.argv[2] == "single":
            # 测试单个章节写作器
            asyncio.run(test_single_section_writer(step_name))
        else:
            # 从指定步骤开始测试
            asyncio.run(test_writing_from_step(step_name))
    else:
        # 默认测试 Methods 章节
        print("使用方法:")
        print("  python test_writing_only.py Methods          # 从 Methods 步骤开始测试")
        print("  python test_writing_only.py Methods single   # 测试 Methods 单个章节写作器")
        print("  python test_writing_only.py Introduction     # 从 Introduction 步骤开始测试")
        asyncio.run(test_single_section_writer("Methods")) 