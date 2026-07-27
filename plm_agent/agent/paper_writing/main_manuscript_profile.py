import asyncio
from pathlib import Path
from .analyzer.manuscript_profile_analyzer import ManuscriptProfileAnalyzer
from .clients.rag_assistant import RAGAssistantClient
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    # 只分析manuscript profile
    file_paths = [
        Path("agent/paper_bot_new/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf"),
        Path("agent/paper_bot_new/test_data/sample_data.csv"),
        # 可以添加更多文件
    ]
    rag_client = RAGAssistantClient()
    analyzer = ManuscriptProfileAnalyzer(rag_client)
    manuscript_profile, content_type_results = await analyzer.analyze_files_comprehensive(file_paths)
    print("\n===== Manuscript Profile =====")
    print(manuscript_profile)
    print(type(manuscript_profile))
    print("\n===== Content Type Results =====")
    for result in content_type_results:
        print(result)
        print(type(result))

    print(type(content_type_results))

if __name__ == "__main__":
    asyncio.run(main()) 