import asyncio
from pathlib import Path
from .extractors.document_extractor_factory import DocumentExtractorFactory
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    # 测试extractor功能
    file_paths = [
        Path("agent/paper_bot_new/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf"),
        Path("agent/paper_bot_new/test_data/sample_data.csv"),
        Path("agent/paper_bot_new/test_data/Paper-Figures-Data_2025.03_Noah.txt"),
    ]
    
    extractor_factory = DocumentExtractorFactory()
    
    for file_path in file_paths:
        print(f"\n===== Extracting: {file_path.name} =====")
        
        # 检查文件是否存在
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue
            
        try:
            # 获取合适的extractor
            extractor = extractor_factory.get_extractor(file_path)
            if extractor:
                print(f"Using extractor: {type(extractor).__name__}")
                
                # 提取内容
                extraction_result = extractor.extract(file_path)
                
                # 处理结果（支持新的schema格式和旧的dict格式）
                if hasattr(extraction_result, 'content'):
                    # 新的schema格式
                    content = extraction_result.content
                    file_type = extraction_result.file_extension
                    tables_count = len(extraction_result.tables)
                    images_count = len(extraction_result.images)
                    extraction_method = extraction_result.extraction_metadata.extraction_method.value if extraction_result.extraction_metadata else "unknown"
                else:
                    # 旧的dict格式
                    content = extraction_result.get('content', '')
                    file_type = extraction_result.get('file_type', 'unknown')
                    tables_count = len(extraction_result.get('tables', []))
                    images_count = len(extraction_result.get('images', []))
                    extraction_method = extraction_result.get('extraction_method', 'unknown')
                
                print(f"File type: {file_type}")
                print(f"Extraction method: {extraction_method}")
                print(f"Content length: {len(content)}")
                print(f"Tables count: {tables_count}")
                print(f"Images count: {images_count}")
                
                # 显示内容预览
                if content:
                    preview = content[:200] + "..." if len(content) > 200 else content
                    print(f"Content preview: {preview}")
                
                # 显示表格信息
                if tables_count > 0:
                    print(f"Tables found:")
                    if hasattr(extraction_result, 'tables'):
                        for i, table in enumerate(extraction_result.tables[:3]):  # 只显示前3个
                            print(f"  Table {i+1}: {table.title} ({table.row_count} rows, {table.column_count} cols)")
                    else:
                        tables = extraction_result.get('tables', [])
                        for i, table in enumerate(tables[:3]):
                            print(f"  Table {i+1}: {table.get('title', 'Unknown')} ({len(table.get('rows', []))} rows)")
                
            else:
                print(f"No extractor found for {file_path}")
                print(f"Supported extensions: {extractor_factory.get_supported_extensions()}")
                
        except Exception as e:
            print(f"Error extracting {file_path}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 