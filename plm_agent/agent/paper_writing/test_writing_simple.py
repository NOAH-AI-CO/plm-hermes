#!/usr/bin/env python3
"""
简单的写作测试脚本
专门用于测试写作功能，不依赖复杂的分析流程
"""

import asyncio
import logging
from pathlib import Path

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_methods_writing():
    """测试 Methods 章节的写作"""
    
    logger.info("开始测试 Methods 章节写作")
    
    try:
        # 导入必要的模块
        from writing.section_writers import MethodsWriter
        from schema.writing import SectionSpecificationManager
        from schema.manuscript import ManuscriptProfile, WritingPurposeDetail, ManuscriptOutline
        from schema.writing import WritingInput
        from presets.enum import StudyType, PublicationType, WritingPurpose
        from writing.full_paper_workflow_agent import MedicalWritingAgent
        
        # 创建简单的测试数据
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
        
        # 创建简单的大纲
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
                        }
                    ]
                }
            ]
        )
        
        # 创建模拟的数据集信息
        dataset_info = [
            {
                "data_preview": [
                    {"id": 1, "group": "A", "age": 45, "score": 75},
                    {"id": 2, "group": "B", "age": 52, "score": 68}
                ],
                "data_structure": {
                    "id": "int64",
                    "group": "object", 
                    "age": "int64",
                    "score": "int64"
                },
                "analysis_summaries": [
                    "样本量：150例，实验组75例，对照组75例"
                ],
                "key_findings": [
                    "两组基线特征基本平衡"
                ],
                "statistical_methods": [
                    "t检验用于连续变量比较"
                ]
            }
        ]
        
        # 创建写作输入
        writing_input = WritingInput(
            writing_purpose=manuscript_profile.writing_purpose,
            study_type=manuscript_profile.study_type.value,
            publication_type=manuscript_profile.publication_type.value,
            target_journal=manuscript_profile.target_journal,
            outline=manuscript_outline,
            dataset_info=dataset_info,
            document_info=[],
            completed_sections={}
        )
        
        # 获取 Methods 章节配置
        section_spec = SectionSpecificationManager.get_section_specification(
            section_name="Methods",
            writing_llm=MedicalWritingAgent.writing_llm,
            polishing_llm=MedicalWritingAgent.polishing_llm
        )
        
        # 创建 Methods 写作器
        methods_writer = MethodsWriter(section_spec)
        
        # 执行写作
        logger.info("开始执行 Methods 章节写作...")
        section = await methods_writer.write_section(writing_input)
        
        logger.info(f"Methods 章节写作完成!")
        logger.info(f"字数: {section.word_count}")
        logger.info(f"内容预览: {section.content[:200]}...")
        
        # 保存结果
        output_file = "test_methods_output.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"章节: {section.name}\n")
            f.write(f"字数: {section.word_count}\n")
            f.write("="*50 + "\n")
            f.write(section.content)
        logger.info(f"结果已保存到: {output_file}")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_writing_agent():
    """测试写作代理"""
    
    logger.info("开始测试写作代理")
    
    try:
        from writing.full_paper_workflow_agent import MedicalWritingAgent
        from schema.manuscript import ManuscriptProfile, WritingPurposeDetail, ManuscriptOutline
        from schema.writing import WritingInput
        from presets.enum import StudyType, PublicationType, WritingPurpose
        
        # 创建简单的测试数据
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
        
        # 创建简单的大纲
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
                        }
                    ]
                }
            ]
        )
        
        # 创建模拟的数据集信息
        dataset_analyses = [
            {
                "file_path": "mock_data.csv",
                "analysis_result": {
                    "data_preview": [
                        {"id": 1, "group": "A", "age": 45, "score": 75}
                    ],
                    "data_structure": {
                        "id": "int64",
                        "group": "object", 
                        "age": "int64",
                        "score": "int64"
                    },
                    "analysis_summaries": [
                        "样本量：150例，实验组75例，对照组75例"
                    ],
                    "key_findings": [
                        "两组基线特征基本平衡"
                    ],
                    "statistical_methods": [
                        "t检验用于连续变量比较"
                    ]
                }
            }
        ]
        
        # 创建写作代理
        writing_agent = MedicalWritingAgent()
        
        # 执行写作
        logger.info("开始执行写作代理...")
        
        async for result in writing_agent.use_tool(
            user_prompt="请写作 Methods 章节",
            profile=manuscript_profile,
            outline=manuscript_outline,
            dataset_analyses=dataset_analyses,
            document_contents=[]
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
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
        if test_type == "methods":
            success = asyncio.run(test_methods_writing())
        elif test_type == "agent":
            success = asyncio.run(test_writing_agent())
        else:
            print("未知的测试类型")
            success = False
    else:
        print("使用方法:")
        print("  python test_writing_simple.py methods  # 测试 Methods 章节写作器")
        print("  python test_writing_simple.py agent    # 测试写作代理")
        success = asyncio.run(test_methods_writing())
    
    if success:
        print("测试成功!")
    else:
        print("测试失败!") 