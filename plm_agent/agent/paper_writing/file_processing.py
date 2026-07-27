from pathlib import Path
from .extractors.document_extractor_factory import DocumentExtractorFactory
from .analyzer.uploaded_document_analyzer import UploadedDocumentAnalyzer
from .analyzer.uploaded_dataset_analyzer import UploadedDatasetAnalyzer
import pandas as pd
from pathlib import Path

async def process_csv_file(file_path: Path, manuscript_profile, results_dict):
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
        results_dict[str(file_path)] = dataset_analysis.model_dump()
        return dataset_analysis
        
    except Exception as e:
        print(f"处理CSV文件错误 {file_path}: {e}")
        return None

async def process_document_file(file_path: Path, extractor_factory: DocumentExtractorFactory, 
                              document_analyzer: UploadedDocumentAnalyzer, content_type_results, results_dict):
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
        results_dict[str(file_path)] = document_analysis
        return document_analysis
        
    except Exception as e:
        print(f"处理文档文件错误 {file_path}: {e}")
        return None