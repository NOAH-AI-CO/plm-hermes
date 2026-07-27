import asyncio
from pathlib import Path
from .extractors.document_extractor_factory import DocumentExtractorFactory
from .analyzer.manuscript_profile_analyzer import ManuscriptProfileAnalyzer
from .analyzer.uploaded_document_analyzer import UploadedDocumentAnalyzer
from .analyzer.uploaded_dataset_analyzer import UploadedDatasetAnalyzer
from .clients.rag_assistant import RAGAssistantClient
from .schema.manuscript import ManuscriptOutline, OutlineSection
from .presets.template import MANUSCRIPT_STRUCTURE, WRITING_STRUCTURE
from .presets.enum import StudyType, PublicationType
from .utils.writing import create_manuscript_outline
import logging
import json
import pandas as pd

logging.basicConfig(level=logging.INFO)

async def main():
    # 测试完整的分析流程，生成manuscript outline
    file_paths = [
        Path("agent/paper_bot_new/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf"),
        Path("agent/paper_bot_new/test_data/sample_data.csv"),
        # 可以添加更多文档文件
    ]
    
    # 初始化组件
    rag_client = RAGAssistantClient()
    manuscript_analyzer = ManuscriptProfileAnalyzer(rag_client)
    extractor_factory = DocumentExtractorFactory()
    document_analyzer = UploadedDocumentAnalyzer()
    
    print("===== Step 1: Analyzing Manuscript Profile and Content Types =====")
    
    # 1. 先分析manuscript profile和content type
    manuscript_profile, content_type_results = await manuscript_analyzer.analyze_files_comprehensive(file_paths)
    
    print("\n----- Manuscript Profile -----")
    print(f"Type: {type(manuscript_profile)}")
    print(f"Study Type: {manuscript_profile.study_type}")
    print(f"Publication Type: {manuscript_profile.publication_type}")
    print(f"Writing Purpose: {manuscript_profile.writing_purpose.primary_purpose}")
    print(f"Confidence Scores: {manuscript_profile.confidence_scores}")
    print(f"File Paths: {manuscript_profile.file_paths}")
    
    print("\n----- Content Type Results -----")
    print(f"Type: {type(content_type_results)}")
    print(f"Length: {len(content_type_results)}")
    for i, result in enumerate(content_type_results):
        print(f"\nResult {i+1}:")
        print(f"  Type: {type(result)}")
        print(f"  Raw content: {result}")
        print(f"  File path: {result.get('file_path', 'N/A')}")
        print(f"  Content type: {result.get('content_type', 'N/A')}")
        print(f"  Confidence: {result.get('confidence', 'N/A')}")
        print(f"  Error message: {result.get('error_message', 'N/A')}")
    
    print("\n===== Step 2: Processing Files =====")
    
    # 存储分析结果
    document_analysis_results = {}
    dataset_analysis_results = {}
    
    # 2. 处理文件 - 分别处理文档和数据文件
    for file_path in file_paths:
        print(f"\n----- Processing: {file_path.name} -----")
        
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue
        
        # 检查文件类型
        file_extension = file_path.suffix.lower()
        
        if file_extension == '.csv':
            # 处理CSV文件 - 使用dataset analyzer
            print("File type: CSV - Using Dataset Analyzer")
            dataset_result = await process_csv_file(file_path, manuscript_profile)
            if dataset_result:
                dataset_analysis_results[str(file_path)] = dataset_result
            
        elif file_extension in ['.pdf', '.docx', '.txt', '.rtf']:
            # 处理文档文件 - 使用document analyzer
            print("File type: Document - Using Document Analyzer")
            document_result = await process_document_file(file_path, extractor_factory, document_analyzer, content_type_results)
            if document_result:
                document_analysis_results[str(file_path)] = document_result
            
        else:
            print(f"Unsupported file type: {file_extension}")
    
    print("\n===== Step 3: Generating Manuscript Outline =====")
    
    # 3. 生成manuscript outline
    if manuscript_profile:
        manuscript_outline = create_manuscript_outline(manuscript_profile)
        
        print("\n----- Generated Manuscript Outline -----")
        print(f"Study Type: {manuscript_outline.study_type}")
        print(f"Publication Type: {manuscript_outline.publication_type}")
        print(f"Target Journal: {manuscript_outline.target_journal}")
        print(f"Total Word Estimate: {manuscript_outline.total_word_estimate}")
        print(f"Main Sections Count: {manuscript_outline.main_sections_count}")
        print(f"Subsections Count: {manuscript_outline.subsections_count}")
        print(f"Writing Style: {manuscript_outline.writing_style}")
        print(f"Tone: {manuscript_outline.tone}")
        
        print("\n----- Outline Structure -----")
        for section in manuscript_outline.sections:
            indent = "  " * (section.level - 1)
            print(f"{indent}{section.title} ({section.word_estimate})")
        
        # 保存outline到文件
        outline_file = "generated_manuscript_outline.json"
        with open(outline_file, 'w', encoding='utf-8') as f:
            json.dump(manuscript_outline.dict(), f, indent=2, ensure_ascii=False)
        print(f"\nManuscript outline saved to: {outline_file}")
        
        return manuscript_outline
    else:
        print("No manuscript profile available for outline generation")

async def process_csv_file(file_path: Path, manuscript_profile):
    """处理CSV文件"""
    try:
        print("1. Loading CSV data...")
        df = pd.read_csv(file_path)
        print(f"   Data loaded: {df.shape[0]} rows, {df.shape[1]} columns")
        print(f"   Columns: {list(df.columns)}")
        
        # 为当前文件创建新的analyzer实例，传入文件信息
        file_dataset_analyzer = UploadedDatasetAnalyzer(
            file_path=str(file_path),
            file_id=file_path.name
        )
        
        print("2. Running dataset analysis...")
        dataset_analysis = await file_dataset_analyzer.analyze_data(df, manuscript_profile)
        
        print(f"   Dataset analysis completed")
        print(f"   Analysis type: {type(dataset_analysis)}")
        
        # 显示dataset analysis的结构
        if hasattr(dataset_analysis, '__dict__'):
            print(f"   Dataset analysis attributes: {list(dataset_analysis.__dict__.keys())}")
            
            # 显示一些关键信息
            for attr_name in ['data_preview', 'analysis_results', 'key_findings', 'statistical_methods']:
                if hasattr(dataset_analysis, attr_name):
                    attr_value = getattr(dataset_analysis, attr_name)
                    if attr_value:
                        if attr_name == 'data_preview':
                            print(f"   {attr_name.capitalize()}: {type(attr_value)}")
                        elif attr_name == 'analysis_results':
                            print(f"   {attr_name.capitalize()}: {len(attr_value)} results")
                        else:
                            print(f"   {attr_name.capitalize()}: {len(attr_value) if hasattr(attr_value, '__len__') else 'N/A'}")
                    else:
                        print(f"   {attr_name.capitalize()}: None/Empty")
        
        return dataset_analysis
        
    except Exception as e:
        print(f"Error processing CSV file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None

async def process_document_file(file_path: Path, extractor_factory: DocumentExtractorFactory, 
                              document_analyzer: UploadedDocumentAnalyzer, content_type_results):
    """处理文档文件"""
    try:
        # 找到对应的content type
        content_type = None
        confidence = 0.0
        for result in content_type_results:
            result_path = result.get('file_path', '')
            # 简单的字符串匹配
            if (result_path == str(file_path) or 
                result_path == file_path.name or 
                (isinstance(result_path, str) and result_path.endswith(file_path.name))):
                content_type = result.get('content_type', 'unknown')
                confidence = result.get('confidence', 0.0)
                print(f"   Found content type: {content_type} (confidence: {confidence})")
                break
        
        if content_type is None:
            print(f"   No content type found in results")
            content_type = 'unknown'
        
        # 跳过没有content type或confidence太低的文件
        if content_type == 'unknown' or confidence < 0.5:
            print(f"Skipping - content type is {content_type} or confidence {confidence} too low")
            return None
        
        # 3. 提取内容
        print("3. Extracting content...")
        extractor = extractor_factory.get_extractor(file_path)
        if not extractor:
            print(f"No extractor found for {file_path}")
            return None
            
        extraction_result = extractor.extract(file_path)
        print(f"   Extraction completed: {len(extraction_result.content)} characters")
        
        # 4. 使用document analyzer进行详细分析
        print("4. Running document content analysis...")
        document_analysis = await document_analyzer.analyze_document_content(
            extraction_result, content_type
        )
        
        print(f"   Document analysis completed")
        print(f"   Analysis type: {type(document_analysis)}")
        
        # 显示一些关键信息
        for attr_name in ['title', 'abstract', 'introduction', 'methods', 'results', 'conclusion']:
            if hasattr(document_analysis, attr_name):
                attr_value = getattr(document_analysis, attr_name)
                if attr_value:
                    print(f"   {attr_name.capitalize()}: {len(attr_value)} characters")
                else:
                    print(f"   {attr_name.capitalize()}: None/Empty")
        
        return document_analysis
        
    except Exception as e:
        print(f"Error processing document file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(main()) 