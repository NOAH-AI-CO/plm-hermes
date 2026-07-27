import asyncio
from pathlib import Path
from .analyzer.manuscript_profile_analyzer import ManuscriptProfileAnalyzer
from .analyzer.uploaded_dataset_analyzer import UploadedDatasetAnalyzer
from .clients.rag_assistant import RAGAssistantClient
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO)

async def main():
    # 测试dataset analyzer功能
    file_paths = [
        Path("agent/paper_bot_new/test_data/sample_data.csv"),
        # 可以添加更多CSV文件
    ]
    
    # 初始化组件
    rag_client = RAGAssistantClient()
    manuscript_analyzer = ManuscriptProfileAnalyzer(rag_client)
    dataset_analyzer = UploadedDatasetAnalyzer()  # 这里先不传参数，在处理文件时再传
    
    print("===== Step 1: Analyzing Manuscript Profile =====")
    
    # 1. 先分析manuscript profile
    manuscript_profile, content_type_results = await manuscript_analyzer.analyze_files_comprehensive(file_paths)
    
    print("\n----- Manuscript Profile -----")
    print(f"Type: {type(manuscript_profile)}")
    print(f"Study Type: {manuscript_profile.study_type}")
    print(f"Publication Type: {manuscript_profile.publication_type}")
    print(f"Writing Purpose: {manuscript_profile.writing_purpose.primary_purpose}")
    print(f"Confidence Scores: {manuscript_profile.confidence_scores}")
    print(f"File Paths: {manuscript_profile.file_paths}")
    
    # 显示manuscript profile的详细结构
    if hasattr(manuscript_profile, '__dict__'):
        print(f"Manuscript Profile attributes: {list(manuscript_profile.__dict__.keys())}")
        
        # 显示writing purpose的详细结构
        if hasattr(manuscript_profile.writing_purpose, '__dict__'):
            print(f"Writing Purpose attributes: {list(manuscript_profile.writing_purpose.__dict__.keys())}")
    
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
    
    print("\n===== Step 2: Processing CSV Files =====")
    
    # 2. 处理CSV文件
    for file_path in file_paths:
        print(f"\n----- Processing CSV: {file_path.name} -----")
        
        if not file_path.exists():
            print(f"File not found: {file_path}")
            continue
        
        # 检查文件类型
        file_extension = file_path.suffix.lower()
        if file_extension != '.csv':
            print(f"Not a CSV file: {file_extension}")
            continue
        
        try:
            # 3. 加载CSV数据
            print("3. Loading CSV data...")
            df = pd.read_csv(file_path)
            print(f"   Data loaded: {df.shape[0]} rows, {df.shape[1]} columns")
            print(f"   Columns: {list(df.columns)}")
            print(f"   Data types: {df.dtypes.to_dict()}")
            
            # 显示数据预览
            print(f"   First 5 rows:")
            print(df.head())
            
            # 显示基本统计信息
            print(f"   Basic statistics:")
            print(df.describe())
            
            # 4. 运行dataset analysis
            print("4. Running dataset analysis...")
            dataset_analysis = await process_csv_file(file_path, dataset_analyzer, manuscript_profile)
            
            print(f"   Dataset analysis completed")
            print(f"   Analysis type: {type(dataset_analysis)}")
            
            # 显示dataset analysis的结构
            if hasattr(dataset_analysis, '__dict__'):
                print(f"   Dataset analysis attributes: {list(dataset_analysis.__dict__.keys())}")
                
                # 详细显示每个属性
                for attr_name, attr_value in dataset_analysis.__dict__.items():
                    print(f"\n   ----- {attr_name.capitalize()} -----")
                    print(f"   Type: {type(attr_value)}")
                    
                    if attr_name == 'data_preview':
                        if hasattr(attr_value, '__dict__'):
                            print(f"   Data preview attributes: {list(attr_value.__dict__.keys())}")
                            for dp_attr_name, dp_attr_value in attr_value.__dict__.items():
                                print(f"     {dp_attr_name}: {type(dp_attr_value)}")
                                if isinstance(dp_attr_value, dict):
                                    print(f"       Keys: {list(dp_attr_value.keys())}")
                                elif isinstance(dp_attr_value, list):
                                    print(f"       Length: {len(dp_attr_value)}")
                                else:
                                    print(f"       Value: {dp_attr_value}")
                    
                    elif attr_name == 'analysis_results':
                        print(f"   Number of analysis results: {len(attr_value) if hasattr(attr_value, '__len__') else 'N/A'}")
                        for i, result in enumerate(attr_value[:3]):  # 只显示前3个
                            print(f"     Result {i+1}: {type(result)}")
                            if hasattr(result, '__dict__'):
                                print(f"       Result attributes: {list(result.__dict__.keys())}")
                                for res_attr_name, res_attr_value in result.__dict__.items():
                                    print(f"         {res_attr_name}: {type(res_attr_value)}")
                                    if isinstance(res_attr_value, dict):
                                        print(f"           Keys: {list(res_attr_value.keys())}")
                                    elif isinstance(res_attr_value, list):
                                        print(f"           Length: {len(res_attr_value)}")
                                    else:
                                        print(f"           Value: {res_attr_value}")
                    
                    elif attr_name in ['key_findings', 'statistical_methods']:
                        if hasattr(attr_value, '__len__'):
                            print(f"   Length: {len(attr_value)}")
                            for i, item in enumerate(attr_value[:5]):  # 只显示前5个
                                print(f"     Item {i+1}: {item}")
                        else:
                            print(f"   Value: {attr_value}")
                    
                    else:
                        print(f"   Value: {attr_value}")
            
            print("\n----- Final Dataset Analysis Result -----")
            print(f"Type: {type(dataset_analysis)}")
            print(f"Raw content: {dataset_analysis}")
            
        except Exception as e:
            print(f"Error processing CSV file {file_path}: {e}")
            import traceback
            traceback.print_exc()

async def process_csv_file(file_path: Path, dataset_analyzer: UploadedDatasetAnalyzer, manuscript_profile):
    """处理CSV文件"""
    try:
        print("1. Loading CSV data...")
        df = pd.read_csv(file_path)
        print(f"   Data loaded: {df.shape[0]} rows, {df.shape[1]} columns")
        print(f"   Columns: {list(df.columns)}")
        print(f"   Data types: {df.dtypes.to_dict()}")
        
        # 显示数据预览
        print(f"   First 5 rows:")
        print(df.head())
        
        # 显示基本统计信息
        print(f"   Basic statistics:")
        print(df.describe())
        
        # 为当前文件创建新的analyzer实例，传入文件信息
        file_dataset_analyzer = UploadedDatasetAnalyzer(
            file_path=str(file_path),
            file_id=file_path.name
        )
        
        print("2. Running dataset analysis...")
        dataset_analysis = await file_dataset_analyzer.analyze_data(df, manuscript_profile)
        
        return dataset_analysis
        
    except Exception as e:
        print(f"Error processing CSV file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(main()) 