"""
Main entry point for the NoahAgent Paper Bot

This script provides a complete workflow for:
1. Document analysis (PDF, DOCX, etc.)
2. Dataset analysis (CSV, Excel, etc.)
3. Manuscript profile analysis
4. Content type identification
5. Writing sections based on analysis results
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from .analyzer.manuscript_profile_analyzer import ManuscriptProfileAnalyzer
from .analyzer.uploaded_document_analyzer import UploadedDocumentAnalyzer
from .analyzer.uploaded_dataset_analyzer import UploadedDatasetAnalyzer
from .extractors.document_extractor_factory import DocumentExtractorFactory
from .schema.extraction_result import ExtractionResult
from .schema.document_insight import DocumentContentType
from .clients.rag_assistant import RAGAssistantClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/analysis.log')
    ]
)

logger = logging.getLogger(__name__)


class NoahAgentPaperBot:
    """Main class for the NoahAgent Paper Bot workflow"""
    
    def __init__(self):
        # Initialize RAG client and analyzers
        self.rag_client = RAGAssistantClient()
        self.manuscript_analyzer = ManuscriptProfileAnalyzer(self.rag_client)
        self.document_analyzer = UploadedDocumentAnalyzer()
        self.dataset_analyzer = UploadedDatasetAnalyzer()
        self.extractor_factory = DocumentExtractorFactory()
        
        # Ensure logs directory exists
        os.makedirs('logs', exist_ok=True)
    
    async def analyze_files(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Analyze uploaded files and return comprehensive results
        
        Args:
            file_paths: List of file paths to analyze
            
        Returns:
            Dictionary containing analysis results for each file
        """
        results = {}
        
        for file_path in file_paths:
            logger.info(f"Analyzing file: {file_path}")
            
            try:
                # Extract content from file
                extractor = self.extractor_factory.get_extractor(Path(file_path))
                if extractor:
                    extraction_result = extractor.extract(Path(file_path))
                    file_type = extraction_result.get('file_type', '')
                    
                    # Analyze based on file type
                    if file_type in ['csv', 'excel', 'xlsx', 'xls']:
                        # Dataset analysis
                        dataset_analysis = await self.dataset_analyzer.analyze_data(extraction_result.get('content', ''))
                        results[file_path] = {
                            'type': 'dataset',
                            'extraction': extraction_result,
                            'analysis': dataset_analysis
                        }
                    else:
                        # Document analysis - first identify content type
                        content_types = await self.manuscript_analyzer.identify_document_content_types([extraction_result])
                        content_type_info = self._find_content_type_info(content_types, file_path)
                        
                        if content_type_info and content_type_info.get('content_type') != 'unknown':
                            content_type = content_type_info.get('content_type', 'manuscript')
                            
                            # Analyze document content
                            document_analysis = await self.document_analyzer.analyze_document_content(
                                extraction_result, content_type
                            )
                            
                            results[file_path] = {
                                'type': 'document',
                                'extraction': extraction_result,
                                'content_type': content_type,
                                'content_type_info': content_type_info,
                                'analysis': document_analysis
                            }
                        else:
                            logger.warning(f"Failed to identify content type for {file_path}")
                            results[file_path] = {
                                'type': 'document',
                                'extraction': extraction_result,
                                'error': 'Content type identification failed'
                            }
                else:
                    logger.error(f"No extractor found for {file_path}")
                    results[file_path] = {
                        'type': 'error',
                        'error': 'No suitable extractor found'
                    }
                        
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")
                results[file_path] = {
                    'type': 'error',
                    'error': str(e)
                }
        
        return results
    
    def _find_content_type_info(self, content_types: List[Dict[str, Any]], file_path: str) -> Optional[Dict[str, Any]]:
        """Find content type info for a specific file path"""
        for content_type_info in content_types:
            if content_type_info.get('file_path') == file_path:
                return content_type_info
        return None
    
    async def analyze_files_comprehensive(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Comprehensive analysis including both manuscript profile and content type identification
        
        Args:
            file_paths: List of file paths to analyze
            
        Returns:
            Dictionary containing both manuscript profile and content type analysis
        """
        results = {}
        
        for file_path in file_paths:
            logger.info(f"Comprehensive analysis of file: {file_path}")
            
            try:
                # Extract content from file
                extractor = self.extractor_factory.get_extractor(Path(file_path))
                if extractor:
                    extraction_result = extractor.extract(Path(file_path))
                    file_type = extraction_result.get('file_type', '')
                    
                    # Analyze based on file type
                    if file_type in ['csv', 'excel', 'xlsx', 'xls']:
                        # Dataset analysis
                        dataset_analysis = await self.dataset_analyzer.analyze_data(extraction_result.get('content', ''))
                        results[file_path] = {
                            'type': 'dataset',
                            'extraction': extraction_result,
                            'analysis': dataset_analysis
                        }
                    else:
                        # Document analysis - get both manuscript profile and content type
                        manuscript_profile = await self.manuscript_analyzer.get_manuscript_profile([extraction_result])
                        content_types = await self.manuscript_analyzer.identify_document_content_types([extraction_result])
                        content_type_info = self._find_content_type_info(content_types, file_path)
                        
                        if content_type_info and content_type_info.get('content_type') != 'unknown':
                            content_type = content_type_info.get('content_type', 'manuscript')
                            
                            # Analyze document content
                            document_analysis = await self.document_analyzer.analyze_document_content(
                                extraction_result, content_type
                            )
                            
                            results[file_path] = {
                                'type': 'document',
                                'extraction': extraction_result,
                                'manuscript_profile': manuscript_profile,
                                'content_type': content_type,
                                'content_type_info': content_type_info,
                                'analysis': document_analysis
                            }
                        else:
                            logger.warning(f"Failed to identify content type for {file_path}")
                            results[file_path] = {
                                'type': 'document',
                                'extraction': extraction_result,
                                'manuscript_profile': manuscript_profile,
                                'error': 'Content type identification failed'
                            }
                else:
                    logger.error(f"No extractor found for {file_path}")
                    results[file_path] = {
                        'type': 'error',
                        'error': 'No suitable extractor found'
                    }
                        
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")
                results[file_path] = {
                    'type': 'error',
                    'error': str(e)
                }
        
        return results
    
    async def write_paper_sections(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Write paper sections based on analysis results
        
        Args:
            analysis_results: Results from analyze_files or analyze_files_comprehensive
            
        Returns:
            Dictionary containing written sections
        """
        logger.info("Starting paper section writing...")
        
        # For now, return a placeholder - writing functionality would be implemented separately
        sections = {
            'abstract': 'Abstract content would be generated here...',
            'introduction': 'Introduction content would be generated here...',
            'methods': 'Methods content would be generated here...',
            'results': 'Results content would be generated here...',
            'discussion': 'Discussion content would be generated here...',
            'conclusion': 'Conclusion content would be generated here...'
        }
        
        return sections
    
    async def run_complete_workflow(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Run the complete workflow: analysis + writing
        
        Args:
            file_paths: List of file paths to process
            
        Returns:
            Complete workflow results
        """
        logger.info(f"Starting complete workflow for {len(file_paths)} files")
        
        # Step 1: Analyze files
        analysis_results = await self.analyze_files_comprehensive(file_paths)
        
        # Step 2: Write paper sections
        writing_results = await self.write_paper_sections(analysis_results)
        
        return {
            'analysis': analysis_results,
            'writing': writing_results
        }


async def main():
    """Main function to run the NoahAgent Paper Bot"""
    
    # Example file paths - replace with your actual files
    file_paths = [
        "agent/paper_bot_new/test_data/for-test-CLO-SCB-1019-001_Protocol_v3.0_01Jul2024_signed.pdf",
        "agent/paper_bot_new/test_data/sample_data.csv",
        # Add more files as needed
    ]
    
    # Initialize the bot
    bot = NoahAgentPaperBot()
    
    try:
        # Run complete workflow
        results = await bot.run_complete_workflow(file_paths)
        
        # Print results summary
        print("\n" + "="*50)
        print("WORKFLOW RESULTS SUMMARY")
        print("="*50)
        
        for file_path, result in results['analysis'].items():
            print(f"\nFile: {file_path}")
            print(f"Type: {result['type']}")
            
            if result['type'] == 'document':
                if 'content_type' in result:
                    print(f"Content Type: {result['content_type']}")
                if 'manuscript_profile' in result:
                    print(f"Manuscript Profile: Available")
                if 'analysis' in result:
                    print(f"Document Analysis: Available")
            elif result['type'] == 'dataset':
                print(f"Dataset Analysis: Available")
            elif result['type'] == 'error':
                print(f"Error: {result['error']}")
        
        if results['writing']:
            print(f"\nWriting Results:")
            for section_name, content in results['writing'].items():
                print(f"  - {section_name}: {len(content)} characters")
        
        print("\n" + "="*50)
        print("WORKFLOW COMPLETED SUCCESSFULLY")
        print("="*50)
        
    except Exception as e:
        logger.error(f"Workflow failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main()) 