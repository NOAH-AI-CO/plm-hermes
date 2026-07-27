"""
Document Content Organizer

Uses LLM to organize and extract structured content from document files
"""

import logging
import json
import re
import asyncio
import time
import sys
import os
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field, fields
from pathlib import Path

# Import NoahAgent models
from llm.azure_models import GPT41

from ..schema.extraction_result import ExtractionResult
from ..schema.document_insight import (
    ProtocolContent, CaseReportContent, LiteratureReviewContent,
    OriginalResearchContent, MetaAnalysisContent, EditorialContent,
    ManuscriptContent, DataFileContent, ImageFileContent, GeneralDocumentContent,
    DocumentContentType
)


@dataclass
class ExtractedField:
    """Represents an extracted field"""
    value: str
    confidence: float
    field_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class ProgressBar:
    """Simple progress bar for chunk processing"""
    
    def __init__(self, total: int, description: str = "Processing"):
        self.total = total
        self.current = 0
        self.description = description
        self.start_time = time.time()
    
    def update(self, n: int = 1):
        """Update progress by n steps"""
        self.current += n
        self._display()
    
    def _display(self):
        """Display current progress"""
        if self.total == 0:
            return
            
        percentage = (self.current / self.total) * 100
        elapsed = time.time() - self.start_time
        
        # Calculate ETA
        if self.current > 0:
            eta = (elapsed / self.current) * (self.total - self.current)
            eta_str = f"ETA: {eta:.1f}s"
        else:
            eta_str = "ETA: --"
        
        # Create progress bar
        bar_length = 30
        filled_length = int(bar_length * self.current // self.total)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Format output
        output = f"\r{self.description}: [{bar}] {self.current}/{self.total} ({percentage:.1f}%) | {elapsed:.1f}s elapsed | {eta_str}"
        print(output, end='', flush=True)
    
    def finish(self):
        """Finish the progress bar"""
        total_time = time.time() - self.start_time
        print(f"\n✅ {self.description} completed in {total_time:.2f}s")


class UploadedDocumentAnalyzer:
    """Analyzer for document files only (PDF, DOCX, etc.)"""
    
    def __init__(self, llm=None):
        self.llm = llm or GPT41()
        self.logger = logging.getLogger(__name__)
        
        # Configuration - Optimized for better performance
        self.max_tokens = 8000
        self.chunk_size = 8000  # Increased from 4000 to reduce chunk count
        self.chunk_overlap = 1000  # Increased overlap for better context
        self.min_confidence = 0.7
        self.max_retries = 3
        self.max_concurrency = 8  # Increased from 5 to 8 for better throughput
        
        # Content type to schema mapping
        self.content_schemas = {
            DocumentContentType.PROTOCOL: ProtocolContent,
            DocumentContentType.CASE_REPORT: CaseReportContent,
            DocumentContentType.LITERATURE_REVIEW: LiteratureReviewContent,
            DocumentContentType.ORIGINAL_RESEARCH: OriginalResearchContent,
            DocumentContentType.META_ANALYSIS: MetaAnalysisContent,
            DocumentContentType.EDITORIAL: EditorialContent,
            DocumentContentType.MANUSCRIPT: ManuscriptContent,
        }
    
    async def analyze_document_content(self, extraction_result: ExtractionResult, 
                                      content_type_str: str) -> Any:
        """
        Analyze document file content using string content type
        
        Args:
            extraction_result: ExtractionResult from document extraction
            content_type_str: Content type as string (protocol, case_report, etc.)
            
        Returns:
            Extracted content object (ProtocolContent, CaseReportContent, etc.)
        """
        content_type = string_to_content_type(content_type_str)
        return await self.process_document(extraction_result, content_type)
    
    async def analyze_content(self, extraction_result: ExtractionResult, 
                             content_type: DocumentContentType) -> Any:
        """Analyze document file content using enum type (legacy method)"""
        return await self.process_document(extraction_result, content_type)
    
    async def process_document(self, extraction_result: ExtractionResult, 
                             content_type: DocumentContentType) -> Any:
        """Process document content using LLM"""
        
        content = extraction_result.content
        file_name = extraction_result.file_name
        
        self.logger.info(f"Processing document: {file_name} with type {content_type}")
        self.logger.info(f"  - Content length: {len(content):,} characters")
        self.logger.info(f"  - Tables found: {extraction_result.table_count}")
        self.logger.info(f"  - Images found: {extraction_result.image_count}")
        
        # Check content length and decide strategy
        estimated_tokens = len(content) * 1.3
        self.logger.info(f"  - Estimated tokens: {estimated_tokens:,.0f}")
        
        processing_start_time = asyncio.get_event_loop().time()
        
        if estimated_tokens <= self.max_tokens * 4:
            self.logger.info(f"  - Using single-pass processing (estimated tokens: {estimated_tokens:,.0f})")
            result = await self._process_single_pass(content, content_type, file_name)
        else:
            self.logger.info(f"  - Using chunked processing (estimated tokens: {estimated_tokens:,.0f})")
            result = await self._process_chunked(content, content_type, file_name)
        
        processing_time = asyncio.get_event_loop().time() - processing_start_time
        self.logger.info(f"  - Document processing completed in {processing_time:.2f} seconds")
        
        return result
    
    async def _process_single_pass(self, content: str, content_type: DocumentContentType, 
                                 file_name: str) -> Any:
        """Process content in a single LLM call"""
        
        schema_class = self.content_schemas.get(content_type, GeneralDocumentContent)
        
        try:
            self.logger.info(f"  - Making single LLM call for {file_name}")
            self.logger.info(f"  - Using schema: {schema_class.__name__}")
            
            response = await self.llm.client.beta.chat.completions.parse(
                model=self.llm.model,
                messages=[
                    {"role": "system", "content": self._get_system_prompt(content_type)},
                    {"role": "user", "content": self._create_extraction_prompt(content, content_type, file_name)}
                ],
                response_format=schema_class
            )
            
            # Log the raw LLM response
            self.logger.info(f"  - LLM Response received for {file_name}")
            self.logger.info(f"  - Response model: {response.model}")
            self.logger.info(f"  - Response usage: {response.usage}")
            
            extracted_data = response.choices[0].message.parsed
            self.logger.info(f"  - Extracted data type: {type(extracted_data)}")
            self.logger.info(f"  - Extracted data fields: {list(extracted_data.__dict__.keys()) if hasattr(extracted_data, '__dict__') else 'No __dict__'}")
            
            # Log some key fields to see if content was extracted
            if hasattr(extracted_data, 'raw_content'):
                self.logger.info(f"  - Raw content length: {len(extracted_data.raw_content) if extracted_data.raw_content else 0}")
            if hasattr(extracted_data, 'abstract'):
                self.logger.info(f"  - Abstract length: {len(extracted_data.abstract) if extracted_data.abstract else 0}")
            if hasattr(extracted_data, 'introduction'):
                self.logger.info(f"  - Introduction length: {len(extracted_data.introduction) if extracted_data.introduction else 0}")
            
            extracted_data.raw_content = content
            
            return extracted_data
            
        except Exception as e:
            self.logger.error(f"Error in single pass processing: {e}")
            self.logger.error(f"  - Exception type: {type(e)}")
            self.logger.error(f"  - Exception details: {str(e)}")
            return self._create_fallback_content(content_type, content)
    
    async def _process_chunked(self, content: str, content_type: DocumentContentType, 
                             file_name: str) -> Any:
        """Process content using chunking strategy with concurrent processing"""
        
        self.logger.info(f"  - Starting chunked processing for {file_name}")
        
        # Add debug logging for chunk creation
        self.logger.info(f"  - Creating content chunks...")
        chunk_creation_start = asyncio.get_event_loop().time()
        
        chunks = self._create_content_chunks(content)
        
        chunk_creation_time = asyncio.get_event_loop().time() - chunk_creation_start
        self.logger.info(f"  - Created {len(chunks)} chunks in {chunk_creation_time:.2f}s")
        
        # Process chunks concurrently with semaphore
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async def process_chunk_with_semaphore(chunk, chunk_index):
            async with semaphore:
                self.logger.info(f"  - Processing chunk {chunk_index + 1}/{len(chunks)}")
                return await self._extract_from_chunk(chunk, content_type)
        
        # Create tasks for all chunks
        tasks = [process_chunk_with_semaphore(chunk, i) for i, chunk in enumerate(chunks)]
        
        # Process chunks with progress bar
        progress_bar = ProgressBar(len(chunks), f"Processing {file_name}")
        chunk_results = []
        
        for i, task in enumerate(asyncio.as_completed(tasks)):
            try:
                result = await task
                if result:
                    chunk_results.append(result)
                progress_bar.update(1)
            except Exception as e:
                self.logger.error(f"Error processing chunk {i}: {e}")
                progress_bar.update(1)
        
        progress_bar.finish()
        
        # Merge results
        self.logger.info(f"  - Merging {len(chunk_results)} chunk results...")
        merged_data = self._merge_chunk_results(chunk_results, content)
        
        # Create final content object
        result = self._create_content_object(merged_data, content_type, content)
        
        return result
    
    def _create_content_chunks(self, content: str) -> List[Dict[str, Any]]:
        """Create content chunks for processing"""
        chunks = []
        content_length = len(content)
        
        if content_length <= self.chunk_size:
            # Single chunk
            chunks.append({
                'chunk_id': 1,
                'content': content,
                'start_position': 0,
                'end_position': content_length
            })
        else:
            # Multiple chunks with overlap
            chunk_id = 1
            start_pos = 0
            
            while start_pos < content_length:
                end_pos = min(start_pos + self.chunk_size, content_length)
                
                # Extract chunk content
                chunk_content = content[start_pos:end_pos]
                
                chunks.append({
                    'chunk_id': chunk_id,
                    'content': chunk_content,
                    'start_position': start_pos,
                    'end_position': end_pos
                })
                
                chunk_id += 1
                start_pos = end_pos - self.chunk_overlap
                
                # Ensure we don't go backwards
                if start_pos >= end_pos:
                    break
        
        # Log chunk statistics
        chunk_sizes = [len(chunk['content']) for chunk in chunks]
        avg_size = sum(chunk_sizes) / len(chunk_sizes) if chunk_sizes else 0
        min_size = min(chunk_sizes) if chunk_sizes else 0
        max_size = max(chunk_sizes) if chunk_sizes else 0
        self.logger.info(f"    - Chunk size stats: min={min_size:,}, avg={avg_size:,.0f}, max={max_size:,}")
        
        return chunks
    
    async def _extract_from_chunk(self, chunk: Dict[str, Any], 
                                content_type: DocumentContentType) -> Optional[Any]:
        """Extract information from a single chunk"""
        
        schema_class = self.content_schemas.get(content_type, GeneralDocumentContent)
        
        try:
            self.logger.info(f"    - Extracting from chunk {chunk['chunk_id']} with schema {schema_class.__name__}")
            self.logger.info(f"    - Chunk content preview: {chunk['content'][:200]}...")
            
            # Use parse function with Pydantic BaseModel
            response = await self.llm.client.beta.chat.completions.parse(
                model=self.llm.model,
                messages=[
                    {"role": "system", "content": self._get_chunk_system_prompt(content_type, chunk)},
                    {"role": "user", "content": chunk['content']}
                ],
                response_format=schema_class
            )
            
            # Log the raw LLM response
            self.logger.info(f"    - LLM Response received for chunk {chunk['chunk_id']}")
            self.logger.info(f"    - Response model: {response.model}")
            self.logger.info(f"    - Response usage: {response.usage}")
            
            extracted_data = response.choices[0].message.parsed
            self.logger.info(f"    - Extracted data type: {type(extracted_data)}")
            self.logger.info(f"    - Extracted data fields: {list(extracted_data.__dict__.keys()) if hasattr(extracted_data, '__dict__') else 'No __dict__'}")
            
            # Log some key fields to see if content was extracted
            if hasattr(extracted_data, 'raw_content'):
                self.logger.info(f"    - Raw content length: {len(extracted_data.raw_content) if extracted_data.raw_content else 0}")
            if hasattr(extracted_data, 'abstract'):
                self.logger.info(f"    - Abstract length: {len(extracted_data.abstract) if extracted_data.abstract else 0}")
            if hasattr(extracted_data, 'introduction'):
                self.logger.info(f"    - Introduction length: {len(extracted_data.introduction) if extracted_data.introduction else 0}")
            
            # Don't set metadata on the LLM response object since schema doesn't have this field
            # Metadata will be handled separately in the merging process
            
            self.logger.info(f"    - Successfully extracted data from chunk {chunk['chunk_id']}")
            return extracted_data
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            self.logger.error(f"Error extracting from chunk {chunk['chunk_id']}: {error_type}: {error_msg}")
            self.logger.error(f"  - Exception type: {type(e)}")
            self.logger.error(f"  - Exception details: {str(e)}")
            
            # Log additional details for debugging
            if "rate limit" in error_msg.lower():
                self.logger.error(f"  - Rate limit error detected")
            elif "timeout" in error_msg.lower():
                self.logger.error(f"  - Timeout error detected")
            elif "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                self.logger.error(f"  - Authentication error detected")
            elif "model" in error_msg.lower():
                self.logger.error(f"  - Model-related error detected")
            elif "response_format" in error_msg.lower():
                self.logger.error(f"  - Response format error detected")
            
            return None
    
    def _merge_chunk_results(self, chunk_results: List[Any], 
                           full_content: str) -> Dict[str, Any]:
        """Merge results from multiple chunks"""
        
        if not chunk_results:
            return {}
        
        merged_data = {}
        base_result = chunk_results[0]
        
        # Get field names from Pydantic BaseModel
        if hasattr(base_result, 'model_fields'):
            # Pydantic v2
            schema_fields = list(base_result.model_fields.keys())
        elif hasattr(base_result, '__fields__'):
            # Pydantic v1
            schema_fields = list(base_result.__fields__.keys())
        else:
            # Fallback: get all attributes
            schema_fields = [attr for attr in dir(base_result) if not attr.startswith('_') and not callable(getattr(base_result, attr))]
        
        for field_name in schema_fields:
            if field_name in ['raw_content', 'metadata']:
                continue
                
            field_values = []
            for result in chunk_results:
                value = getattr(result, field_name, None)
                if value and value != "":
                    field_values.append(value)
            
            if field_name in ['title', 'abstract']:
                merged_data[field_name] = max(field_values, key=len) if field_values else ""
            elif field_name in ['keywords', 'authors', 'references']:
                all_items = []
                for value in field_values:
                    if isinstance(value, list):
                        all_items.extend(value)
                    elif isinstance(value, str):
                        items = re.split(r'[,;]', value)
                        all_items.extend([item.strip() for item in items if item.strip()])
                
                seen = set()
                unique_items = []
                for item in all_items:
                    if item not in seen:
                        seen.add(item)
                        unique_items.append(item)
                
                merged_data[field_name] = unique_items
            else:
                merged_data[field_name] = next((v for v in field_values if v), "")
        
        return merged_data
    
    def _create_extraction_prompt(self, content: str, content_type: DocumentContentType, 
                                file_name: str) -> str:
        """Create extraction prompt for the content"""
        return f"""
Please extract structured information from the following {content_type.value} document.

Document: {file_name}
Content:
{content[:6000]}

Extract all relevant information according to the specified schema. If a field is not found in the document, leave it empty or use appropriate default values.
"""
    
    def _get_system_prompt(self, content_type: DocumentContentType) -> str:
        """Get system prompt for content type"""
        base_prompt = "You are a research assistant specialized in extracting structured data from academic literature."
        
        content_type_prompts = {
            DocumentContentType.PROTOCOL: "Focus on extracting protocol-specific information including study design, eligibility criteria, interventions, and outcome measures.",
            DocumentContentType.CASE_REPORT: "Focus on extracting case-specific information including patient details, clinical presentation, diagnosis, treatment, and outcomes.",
            DocumentContentType.LITERATURE_REVIEW: "Focus on extracting review-specific information including scope, methodology, key findings, and synthesis of literature.",
            DocumentContentType.ORIGINAL_RESEARCH: "Focus on extracting research-specific information including objectives, methods, results, and conclusions.",
            DocumentContentType.META_ANALYSIS: "Focus on extracting meta-analysis-specific information including inclusion criteria, statistical methods, effect sizes, and heterogeneity analysis.",
            DocumentContentType.EDITORIAL: "Focus on extracting editorial-specific information including perspective, commentary, and recommendations.",
            DocumentContentType.MANUSCRIPT: "Focus on extracting general manuscript information including structure, content, and key elements.",
        }
        
        specific_prompt = content_type_prompts.get(content_type, "")
        return f"{base_prompt} {specific_prompt}"
    
    def _get_chunk_system_prompt(self, content_type: DocumentContentType, chunk: Dict[str, Any]) -> str:
        """Get system prompt for chunk extraction"""
        base_prompt = self._get_system_prompt(content_type)
        return f"{base_prompt} You are analyzing chunk {chunk['chunk_id']} (position {chunk['start_position']}-{chunk['end_position']}) of the document. Extract information from this chunk only. If a field is not present in this chunk, leave it empty."
    
    def _create_content_object(self, extracted_data: Dict[str, Any], 
                             content_type: DocumentContentType, raw_content: str) -> Any:
        """Create content object from extracted data"""
        if content_type in self.content_schemas:
            schema_class = self.content_schemas[content_type]
            extracted_data['raw_content'] = raw_content
            
            # Log extracted data for debugging
            self.logger.info(f"  - Creating {schema_class.__name__} with extracted data:")
            for key, value in extracted_data.items():
                if key != 'raw_content':  # Skip raw_content to avoid log spam
                    if isinstance(value, str) and len(value) > 100:
                        self.logger.info(f"    {key}: {value[:100]}...")
                    else:
                        self.logger.info(f"    {key}: {value}")
            
            try:
                result = schema_class(**extracted_data)
                self.logger.info(f"  - Successfully created {schema_class.__name__}")
                return result
            except Exception as e:
                self.logger.error(f"Error creating content object: {e}")
                self.logger.error(f"  - Extracted data keys: {list(extracted_data.keys())}")
                return self._create_fallback_content(content_type, raw_content)
        else:
            self.logger.warning(f"  - No schema found for content type: {content_type}")
            return self._create_fallback_content(content_type, raw_content)
    
    def _create_fallback_content(self, content_type: DocumentContentType, raw_content: str) -> Any:
        """Create fallback content object when extraction fails"""
        fallback_data = {
            'title': f"Extracted {content_type.value}",
            'abstract': raw_content[:500] + "..." if len(raw_content) > 500 else raw_content,
            'keywords': [],
            'content_summary': "Content extraction failed, using fallback",
            'raw_content': raw_content
        }
        
        if content_type in self.content_schemas:
            schema_class = self.content_schemas[content_type]
            try:
                return schema_class(**fallback_data)
            except:
                pass
        
        return GeneralDocumentContent(**fallback_data)


def string_to_content_type(content_type_str: str) -> DocumentContentType:
    """Convert string content type to DocumentContentType enum"""
    mapping = {
        'protocol': DocumentContentType.PROTOCOL,
        'case_report': DocumentContentType.CASE_REPORT,
        'literature_review': DocumentContentType.LITERATURE_REVIEW,
        'original_research': DocumentContentType.ORIGINAL_RESEARCH,
        'meta_analysis': DocumentContentType.META_ANALYSIS,
        'editorial': DocumentContentType.EDITORIAL,
        'manuscript': DocumentContentType.MANUSCRIPT,
        'unknown': DocumentContentType.UNKNOWN
    }
    
    normalized = content_type_str.lower().strip()
    return mapping.get(normalized, DocumentContentType.UNKNOWN) 