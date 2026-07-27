import asyncio
from pathlib import Path
from .extractors.document_extractor_factory import DocumentExtractorFactory
from .analyzer.manuscript_profile_analyzer import ManuscriptProfileAnalyzer
from .analyzer.uploaded_document_analyzer import UploadedDocumentAnalyzer
from .analyzer.uploaded_dataset_analyzer import UploadedDatasetAnalyzer
from .writing.full_paper_workflow_agent import MedicalWritingAgent
from .clients.rag_assistant import RAGAssistantClient
from .schema.manuscript import ManuscriptOutline, OutlineSection
from .presets.template import MANUSCRIPT_STRUCTURE, WRITING_STRUCTURE
from .presets.enum import StudyType, PublicationType
from .utils.writing import create_manuscript_outline
import logging
import json
import pandas as pd
import pickle
from pathlib import Path

logging.basicConfig(level=logging.INFO)

def save_cached_results(results: dict, filename: str = "cached_analysis_results.pkl"):
    """保存分析结果到缓存文件"""
    try:
        with open(filename, 'wb') as f:
            pickle.dump(results, f)
        print(f"分析结果已保存到缓存文件: {filename}")
    except Exception as e:
        print(f"保存缓存失败: {e}")

def load_cached_results(filename: str = "cached_analysis_results.pkl"):
    """从缓存文件加载分析结果"""
    try:
        if Path(filename).exists():
            with open(filename, 'rb') as f:
                results = pickle.load(f)
            print(f"从缓存文件加载结果: {filename}")
            return results
        else:
            print(f"缓存文件不存在: {filename}")
            return None
    except Exception as e:
        print(f"加载缓存失败: {e}")
        return None

async def test_full_paper_workflow():
    """测试完整的论文写作流程"""
    print("===== 开始测试完整论文写作流程 =====")
    print("如果有缓存将自动使用缓存")
    
    # 测试文件
    file_paths = [
        Path("agent/paper_bot_new/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf"),
        Path("agent/paper_bot_new/test_data/sample_data.csv"),
    ]
    
    # 初始化组件
    rag_client = RAGAssistantClient()
    manuscript_analyzer = ManuscriptProfileAnalyzer(rag_client)
    extractor_factory = DocumentExtractorFactory()
    document_analyzer = UploadedDocumentAnalyzer()
    
    # 尝试加载缓存的分析结果
    cached_results = load_cached_results()
    if cached_results:
        print("找到缓存结果，使用缓存数据")
        manuscript_profile = cached_results.get('manuscript_profile')
        content_type_results = cached_results.get('content_type_results', [])
        document_analysis_results = cached_results.get('document_analysis_results', {})
        dataset_analysis_results = cached_results.get('dataset_analysis_results', {})
        manuscript_outline = cached_results.get('manuscript_outline')
        print("成功加载缓存的分析结果")
    else:
        print("未找到缓存结果，执行完整分析流程")
        print("\n===== Step 1: 分析 Manuscript Profile =====")
        
        # 1. 分析manuscript profile和content type
        manuscript_profile, content_type_results = await manuscript_analyzer.analyze_files_comprehensive(file_paths)
    
    print(f"Study Type: {manuscript_profile.study_type}")
    print(f"Publication Type: {manuscript_profile.publication_type}")
    print(f"Writing Purpose: {manuscript_profile.writing_purpose.primary_purpose}")
    print(f"Content Type Results: {content_type_results}")
    
    # 保存或更新缓存结果
    if not cached_results:
        cached_results = {
            'manuscript_profile': manuscript_profile,
            'content_type_results': content_type_results
        }
        save_cached_results(cached_results)
    else:
        # 更新缓存中的大纲
        cached_results['manuscript_outline'] = manuscript_outline
        save_cached_results(cached_results)
    
    # 如果没有缓存，执行文件处理步骤
    if not cached_results:
        print("\n===== Step 2: 处理文件 =====")
        
        # 存储分析结果
        document_analysis_results = {}
        dataset_analysis_results = {}
    
    # 2. 处理文件（只有在没有缓存时才执行）
    if not cached_results:
        for file_path in file_paths:
            print(f"\n----- 处理文件: {file_path.name} -----")
            
            if not file_path.exists():
                print(f"文件不存在: {file_path}")
                continue
            
            file_extension = file_path.suffix.lower()
            
            if file_extension == '.csv':
                print("文件类型: CSV - 使用 Dataset Analyzer")
                dataset_result = await process_csv_file(file_path, manuscript_profile)
                if dataset_result:
                    dataset_analysis_results[str(file_path)] = dataset_result
                
            elif file_extension in ['.pdf', '.docx', '.txt', '.rtf']:
                print("文件类型: Document - 使用 Document Analyzer")
                document_result = await process_document_file(file_path, extractor_factory, document_analyzer, content_type_results)
                if document_result:
                    document_analysis_results[str(file_path)] = document_result
                
            else:
                print(f"不支持的文件类型: {file_extension}")
    else:
        print("使用缓存的文件分析结果，跳过文件处理步骤")
    
    print("\n===== Step 3: 生成 Manuscript Outline =====")
    
    # 3. 生成manuscript outline（只有在没有缓存时才执行）
    if not cached_results:
        manuscript_outline = create_manuscript_outline(manuscript_profile)
    else:
        print("使用缓存的大纲")
        # 如果缓存中没有大纲，重新生成
        if manuscript_outline is None:
            print("缓存中没有大纲，重新生成")
            manuscript_outline = create_manuscript_outline(manuscript_profile)
    
    print(f"Study Type: {manuscript_outline.study_type}")
    print(f"Publication Type: {manuscript_outline.publication_type}")
    print(f"Total Word Estimate: {manuscript_outline.total_word_estimate}")
    
    print("\n----- Outline Structure -----")
    for section in manuscript_outline.sections:
        indent = "  " * (section.level - 1)
        print(f"{indent}{section.title} ({section.word_estimate})")
    
    print("\n===== Step 4: 写作论文章节 =====")
    
    # 4. 基于分析结果进行写作
    if document_analysis_results or dataset_analysis_results:
        completed_sections = await write_paper_sections(manuscript_profile, document_analysis_results, dataset_analysis_results, manuscript_outline)
        
        print(f"\n===== 写作完成 =====")
        print(f"完成的章节: {list(completed_sections.keys()) if completed_sections else '无'}")
        
        # 保存结果
        if completed_sections:
            save_writing_results(completed_sections, manuscript_outline)
    else:
        print("没有可用的分析结果进行写作")

async def process_csv_file(file_path: Path, manuscript_profile):
    """处理CSV文件"""
    try:
        print("1. 加载CSV数据...")
        df = pd.read_csv(file_path)
        print(f"   数据加载: {df.shape[0]} 行, {df.shape[1]} 列")
        
        file_dataset_analyzer = UploadedDatasetAnalyzer(
            file_path=str(file_path),
            file_id=file_path.name
        )
        
        print("2. 运行数据集分析...")
        dataset_analysis = await file_dataset_analyzer.analyze_data(df, manuscript_profile)
        
        print(f"   数据集分析完成")
        return dataset_analysis
        
    except Exception as e:
        print(f"处理CSV文件错误 {file_path}: {e}")
        return None

async def process_document_file(file_path: Path, extractor_factory: DocumentExtractorFactory, 
                              document_analyzer: UploadedDocumentAnalyzer, content_type_results):
    """处理文档文件"""
    try:
        print(f"   调试: 查找文件 {file_path.name} 的内容类型")
        print(f"   调试: content_type_results 长度: {len(content_type_results)}")
        
        # 找到对应的content type
        content_type = None
        confidence = 0.0
        for result in content_type_results:
            result_path = result.get('file_path', '')
            print(f"   调试: 比较 {result_path} vs {file_path.name}")
            
            # 处理 PosixPath 对象
            if hasattr(result_path, 'name'):
                result_path_str = result_path.name
            else:
                result_path_str = str(result_path)
            
            # 更灵活的路径匹配
            if (result_path_str == file_path.name or 
                str(result_path) == str(file_path) or
                file_path.name in result_path_str):
                content_type = result.get('content_type', 'unknown')
                confidence = result.get('confidence', 0.0)
                print(f"   找到内容类型: {content_type} (置信度: {confidence})")
                break
        
        if content_type is None:
            print(f"   未找到内容类型，使用默认值")
            return None
        
        # 降低置信度阈值，让更多文档能够被处理
        if content_type == 'unknown' or confidence < 0.1:
            print(f"跳过 - 内容类型是 {content_type} 或置信度 {confidence} 太低")
            return None
        
        print("3. 提取内容...")
        extractor = extractor_factory.get_extractor(file_path)
        if not extractor:
            print(f"未找到提取器: {file_path}")
            return None
            
        extraction_result = extractor.extract(file_path)
        print(f"   提取完成: {len(extraction_result.content)} 字符")
        
        print("4. 运行文档内容分析...")
        document_analysis = await document_analyzer.analyze_document_content(
            extraction_result, content_type
        )
        
        print(f"   文档分析完成")
        return document_analysis
        
    except Exception as e:
        print(f"处理文档文件错误 {file_path}: {e}")
        return None

async def write_paper_sections(manuscript_profile, document_analysis_results, dataset_analysis_results, manuscript_outline):
    """使用MedicalWritingAgent进行论文写作"""
    try:
        print("开始论文写作过程...")
        
        # 准备数据
        dataset_analyses = list(dataset_analysis_results.values())
        document_contents = list(document_analysis_results.values())
        
        print(f"写作输入准备完成:")
        print(f"  研究类型: {manuscript_profile.study_type}")
        print(f"  发表类型: {manuscript_profile.publication_type}")
        print(f"  目标期刊: {manuscript_profile.writing_purpose.target_journal}")
        print(f"  文档信息: {len(document_contents)} 个文档")
        print(f"  数据集信息: {len(dataset_analyses)} 个数据集")
        
        # 创建MedicalWritingAgent
        writing_agent = MedicalWritingAgent()
        
        # 定义进度回调函数
        def progress_callback(progress):
            print(f"  进度: {progress['completed_sections']}/{progress['total_steps']} - 当前章节: {progress['current_section']}")
        
        # 执行写作工作流
        print("\n----- 开始写作工作流 -----")
        completed_sections = {}
        
        async for result in writing_agent.use_tool(
            user_prompt="Write a complete academic paper based on the provided data and documents",
            profile=manuscript_profile,
            outline=manuscript_outline,
            dataset_analyses=dataset_analyses,
            document_contents=document_contents,
            progress_callback=progress_callback
        ):
            # 处理写作结果
            if result.get('type') == 'chat' and result.get('message'):
                section_name = result.get('section_name', 'unknown')
                word_count = result.get('word_count', 0)
                print(f"  {section_name} 章节完成 - {word_count} 字")
                
                # 这里可以保存章节内容
                # 由于MedicalWritingAgent返回的是流式结果，我们需要收集完整内容
                
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
        for section in sections:
            completed_sections[section.name.lower()] = section
        
        print(f"\n----- 写作完成 -----")
        print(f"完成的章节: {list(completed_sections.keys())}")
        
        return completed_sections
        
    except Exception as e:
        print(f"写作过程错误: {e}")
        import traceback
        traceback.print_exc()
        return None



def save_writing_results(completed_sections, manuscript_outline):
    """保存写作结果"""
    try:
        # 保存outline
        outline_file = "generated_manuscript_outline.json"
        with open(outline_file, 'w', encoding='utf-8') as f:
            json.dump(manuscript_outline.dict(), f, indent=2, ensure_ascii=False)
        print(f"论文大纲已保存到: {outline_file}")
        
        # 保存各个章节
        for section_name, section in completed_sections.items():
            section_file = f"generated_{section_name}_section.json"
            with open(section_file, 'w', encoding='utf-8') as f:
                json.dump(section.dict(), f, indent=2, ensure_ascii=False)
            print(f"{section_name.capitalize()} 章节已保存到: {section_file}")
            
            # 同时保存纯文本版本
            text_file = f"generated_{section_name}_section.txt"
            with open(text_file, 'w', encoding='utf-8') as f:
                f.write(f"# {section_name.capitalize()} Section\n\n")
                if section.content:
                    f.write(section.content)
                if section.subsections:
                    for subsection in section.subsections:
                        f.write(f"\n## {subsection.title}\n\n")
                        if subsection.content:
                            f.write(subsection.content)
            print(f"{section_name.capitalize()} 章节文本已保存到: {text_file}")
            
    except Exception as e:
        print(f"保存结果时出错: {e}")

if __name__ == "__main__":
    print("使用方法:")
    print("  python test_full_paper_workflow.py  # 完整流程（自动使用缓存）")
    print("注意：如果有缓存将自动使用缓存，没有缓存则执行完整分析")
    
    asyncio.run(test_full_paper_workflow()) 