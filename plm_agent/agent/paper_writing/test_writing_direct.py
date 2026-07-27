#!/usr/bin/env python3
"""
直接测试写作功能
"""

import asyncio
import sys
import os

async def test_writing_direct():
    """直接测试写作功能"""
    
    print("===== 直接测试写作功能 =====")
    
    try:
        # 导入必要的模块
        from .writing.full_paper_workflow_agent import MedicalWritingAgent
        from .schema.manuscript import ManuscriptProfile, WritingPurposeDetail, ManuscriptOutline, OutlineSection
        from .schema.writing import WritingInput
        from .presets.enum import StudyType, PublicationType, WritingPurpose
        from .schema.data_insight import DatasetAnalysisResult, DataPreview, AnalysisResult
        
        # 首先测试LLM是否正常工作
        print("测试LLM连接...")
        from llm.composite_models import MedicalPaperWritingModels
        llm = MedicalPaperWritingModels()
        
        # 简单测试LLM调用
        try:
            print("开始LLM stream调用...")
            response_content = ""
            async for chunk in llm.stream_call(
                user_prompt="请简单回复'LLM测试成功'",
                temperature=0.1,
                max_tokens=50
            ):
                print(f"收到chunk: {chunk}")
                response_content += chunk
            
            print(f"完整响应: {response_content}")
            if response_content:
                print("LLM stream调用成功")
            else:
                print("警告: LLM stream调用返回空内容")
        except Exception as e:
            print(f"LLM stream测试失败: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # 创建简单的测试数据
        manuscript_profile = ManuscriptProfile(
            study_type=StudyType.RCT,
            publication_type=PublicationType.PROTOCOL,
            writing_purpose=WritingPurposeDetail(
                primary_purpose=WritingPurpose.PROTOCOL,
                summary="开发一个随机对照试验的研究方案"
            )
        )
        
        # 创建简单的大纲
        manuscript_outline = ManuscriptOutline(
            study_type=StudyType.RCT,
            publication_type=PublicationType.PROTOCOL,
            target_journal="BMJ Open",
            sections=[
                OutlineSection(
                    title="Introduction",
                    level=1,
                    word_estimate="800-1200",
                    content_hints=["研究背景", "问题陈述", "研究目的"],
                    key_points=["研究背景", "知识缺口", "研究假设"],
                    writing_guidance=["引用相关文献", "明确研究意义"]
                ),
                OutlineSection(
                    title="Methods",
                    level=1,
                    word_estimate="800-1200",
                    content_hints=["研究设计", "参与者", "干预措施", "结局指标"],
                    key_points=["随机对照设计", "双盲", "多中心"],
                    writing_guidance=["详细描述研究设计", "明确纳入排除标准"]
                ),
                OutlineSection(
                    title="研究设计",
                    level=2,
                    word_estimate="300-500",
                    content_hints=["随机化方法", "盲法", "样本量计算"],
                    key_points=["随机对照设计", "双盲", "多中心"],
                    writing_guidance=["详细描述随机化过程"]
                )
            ]
        )
        
        # 创建模拟的数据集信息
        dataset_analyses = [
            DatasetAnalysisResult(
                file_id="mock_001",
                file_path="mock_data.csv",
                file_name="mock_data.csv",
                data_preview=DataPreview(
                    data_preview=[
                        {"id": 1, "group": "A", "age": 45, "score": 75},
                        {"id": 2, "group": "B", "age": 42, "score": 78}
                    ],
                    data_structure={
                        "id": "int64",
                        "group": "object", 
                        "age": "int64",
                        "score": "int64"
                    }
                ),
                analysis_results=[
                    AnalysisResult(
                        id=1,
                        success=True,
                        type="with_tools",
                        summary="样本量：150例，实验组75例，对照组75例",
                        content="两组基线特征基本平衡，t检验用于连续变量比较"
                    )
                ],
                key_findings=["两组基线特征基本平衡"],
                statistical_methods_used=["t检验用于连续变量比较"]
            )
        ]
        
        # 创建写作代理
        writing_agent = MedicalWritingAgent()
        
        # 执行写作
        print("开始执行写作代理...")
        
        async for result in writing_agent.use_tool(
            user_prompt="请写作 Introduction 和 Methods 章节，需要检索相关文献",
            profile=manuscript_profile,
            outline=manuscript_outline,
            dataset_analyses=dataset_analyses,
            document_contents=[]
        ):
            if result.get('type') == 'chat' and result.get('message'):
                section_name = result.get('section_name', 'unknown')
                word_count = result.get('word_count', 0)
                print(f"  {section_name} 章节完成 - {word_count} 字")
                
            elif result.get('type') == 'statusUpdate':
                status = result.get('agentStatus')
                if status == 'completed':
                    print("  写作工作流完成")
                    break
                elif status == 'stopped':
                    print("  写作工作流被停止")
                    break
                    
            elif result.get('error'):
                print(f"  写作错误: {result['error']}")
                break
        
        # 获取完成的章节
        sections = writing_agent.get_completed_sections()
        print(f"完成的章节: {[s.name for s in sections]}")
        
        # 保存结果
        for section in sections:
            output_file = f"writing_output_{section.name.lower()}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"章节: {section.name}\n")
                f.write(f"字数: {section.word_count}\n")
                f.write("="*50 + "\n")
                f.write(section.content)
            print(f"章节内容已保存到: {output_file}")
        
        return True
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_literature_search():
    """专门测试文献检索功能"""
    
    print("===== 测试文献检索功能 =====")
    
    try:
        # 导入必要的模块
        from .clients.semantic_scholar import SemanticScholarClient
        from .clients.pubmed import PubMedClient
        
        # 测试Semantic Scholar客户端
        print("测试Semantic Scholar客户端...")
        ss_client = SemanticScholarClient()
        
        # 搜索相关文献
        query = "randomized controlled trial protocol design"
        print(f"搜索查询: {query}")
        
        try:
            # 使用lazy_search方法
            paper_count = 0
            for paper_item in ss_client.lazy_search(query):
                if paper_count >= 3:  # 只显示前3篇
                    break
                    
                metadata = ss_client.get_metadata(paper_item["uid"], paper_item["metadata"])
                print(f"论文 {paper_count+1}:")
                print(f"  标题: {metadata.get('title', 'No title')}")
                print(f"  期刊: {metadata.get('journal', 'Unknown journal')}")
                print(f"  年份: {metadata.get('year', 'Unknown year')}")
                print(f"  摘要: {metadata.get('abstract', 'No abstract')[:200] if metadata.get('abstract') else 'No abstract'}...")
                print()
                paper_count += 1
                
        except Exception as e:
            print(f"Semantic Scholar搜索失败: {e}")
        
        # 测试PubMed客户端
        print("测试PubMed客户端...")
        pubmed_client = PubMedClient()
        
        try:
            # 使用lazy_search方法
            paper_count = 0
            for paper_item in pubmed_client.lazy_search(query):
                if paper_count >= 3:  # 只显示前3篇
                    break
                    
                metadata = pubmed_client.get_metadata(paper_item["uid"], paper_item["webenv"])
                print(f"PubMed论文 {paper_count+1}:")
                print(f"  标题: {metadata.get('title', 'No title')}")
                print(f"  作者: {metadata.get('authors', [])[:3] if metadata.get('authors') else 'Unknown'}")
                print(f"  期刊: {metadata.get('journal', 'Unknown journal')}")
                print(f"  年份: {metadata.get('pub_date', 'Unknown year')}")
                print(f"  摘要: {metadata.get('abstract', 'No abstract')[:200] if metadata.get('abstract') else 'No abstract'}...")
                print()
                paper_count += 1
                
        except Exception as e:
            print(f"PubMed搜索失败: {e}")
        
        return True
        
    except Exception as e:
        print(f"文献检索测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 先测试文献检索
    print("开始文献检索测试...")
    lit_success = asyncio.run(test_literature_search())
    
    if lit_success:
        print("文献检索测试成功!")
    else:
        print("文献检索测试失败!")
    
    print("\n" + "="*50 + "\n")
    
    # 再测试写作功能
    print("开始写作测试...")
    writing_success = asyncio.run(test_writing_direct())
    
    if writing_success:
        print("写作测试成功!")
    else:
        print("写作测试失败!") 