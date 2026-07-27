import asyncio
from pathlib import Path

from agent.human_in_loop.utils import download_attachments
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
from .utils.pickle import save_cached_results, load_cached_results
from .file_processing import process_csv_file, process_document_file
import logging
import json
import pandas as pd
from pathlib import Path

async def process_manuscript_outline(planning_agent, task_id, user):
    """测试完整的论文写作流程"""
    print("===== 开始测试完整论文写作流程 =====")
    print("如果有缓存将自动使用缓存")
    
    # Read all files from the test_data directory
    files = planning_agent.files
    test_data_dir_str = "agent/paper_writing/test_data"
    test_data_dir = Path(test_data_dir_str)
    if files:
    
        await download_attachments(files, "agent/paper_writing/test_data")
    # test_data_dir = Path(f"agent/paper_writing/{user}/{task_id}")
    file_paths = list(test_data_dir.glob("*"))
    print(f"Found {len(file_paths)} files in test data directory:")
    for file in file_paths:
        print(f"  - {file.name}")
        
    # file_paths = [
    #     Path("noah_agent/agent/paper_writing/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf"),
    #     Path("noah_agent/agent/paper_writing/test_data/sample_data.csv"),
    # ]
    
    # 初始化组件
    rag_client = RAGAssistantClient()
    manuscript_analyzer = ManuscriptProfileAnalyzer(rag_client)
    extractor_factory = DocumentExtractorFactory()
    document_analyzer = UploadedDocumentAnalyzer()
    manuscript_outline = None
    
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
    planning_agent.manuscript_profile = manuscript_profile
    
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
        document_analysis_tasks = []
        dataset_analysis_tasks = []
        for file_path in file_paths:
            print(f"\n----- 处理文件: {file_path.name} -----")
            
            if not file_path.exists():
                print(f"文件不存在: {file_path}")
                continue
            
            file_extension = file_path.suffix.lower()
            
            if file_extension == '.csv':
                print("文件类型: CSV - 使用 Dataset Analyzer")
                dataset_analysis_tasks.append(asyncio.create_task(process_csv_file(file_path, manuscript_profile, dataset_analysis_results)))
                # if dataset_result:
                #     dataset_analysis_results[str(file_path)] = dataset_result
                
            elif file_extension in ['.pdf', '.docx', '.txt', '.rtf']:
                print("文件类型: Document - 使用 Document Analyzer")
                document_analysis_tasks.append(asyncio.create_task(process_document_file(file_path, extractor_factory, document_analyzer, content_type_results, document_analysis_results)))
                # document_result = await process_document_file(file_path, extractor_factory, document_analyzer, content_type_results)
                # if document_result:
                #     document_analysis_results[str(file_path)] = document_result
                
            else:
                print(f"不支持的文件类型: {file_extension}")
        await asyncio.gather(*document_analysis_tasks, return_exceptions=False)
        await asyncio.gather(*dataset_analysis_tasks, return_exceptions=False)
        planning_agent.document_analysis_results = document_analysis_results
        planning_agent.dataset_analysis_results = dataset_analysis_results
        

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
    planning_agent.manuscript_outline = manuscript_outline
    
    print(f"Study Type: {manuscript_outline.study_type}")
    print(f"Publication Type: {manuscript_outline.publication_type}")
    print(f"Total Word Estimate: {manuscript_outline.total_word_estimate}")
    
    print("\n----- Outline Structure -----")
    for section in manuscript_outline.sections:
        indent = "  " * (section.level - 1)
        print(f"{indent}{section.title} ({section.word_estimate})")
    
    print("\n===== Step 4: 写作论文章节 =====")
    return manuscript_outline
    

    