import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple

from ..clients.rag_assistant import RAGAssistantClient
from ..prompts.manuscript_profile_prompts import ManuscriptProfilePrompts
from ..prompts.document_content_type_prompts import DocumentContentTypePrompts
from ..schema.manuscript import ManuscriptProfile, WritingPurposeDetail
from ..presets.enum import StudyType, PublicationType, WritingPurpose

import logging
logging.basicConfig(level=logging.INFO)


class ManuscriptProfileAnalyzer:
    """Analyzer for providing manuscript profile using RAG assistant"""
    
    def __init__(self, rag_client: RAGAssistantClient):
        self.rag_client = rag_client
    
    async def analyze_files_comprehensive(self, file_paths: List[Path]) -> Tuple[ManuscriptProfile, List[Dict[str, Any]]]:
        """Upload files and analyze them for manuscript profile and document content types"""
        try:
            logging.info(f"Starting analysis of {len(file_paths)} files")
            
            file_ids = self.rag_client.upload_files(file_paths)
            if not file_ids:
                raise ValueError("No valid files were uploaded")
            
            # Analyze uploaded files
            manuscript_profile = await self.get_manuscript_profile(file_ids)
            document_content_types = await self.identify_document_content_types(file_ids)
            return manuscript_profile, document_content_types
            
        except Exception as e:
            logging.error(f"Error during file analysis: {str(e)}")
            manuscript_profile = self._create_error_manuscript_profile(file_paths, str(e))
            document_content_types = self._create_error_document_content_types() # TODO: empty list, can be modified later
            return manuscript_profile, document_content_types
    
    async def get_manuscript_profile(self, file_ids: List[str]) -> ManuscriptProfile:
        logging.info(f"Analyzing {len(file_ids)} uploaded files")

        file_paths = []
        for file_id in file_ids:
            uploaded_file = self.rag_client.get_file_by_id(file_id)
            if uploaded_file:
                file_paths.append(uploaded_file.file_path)
        
        if not file_paths:
            raise ValueError("No valid uploaded files found")
        try:
            prompt = ManuscriptProfilePrompts.get_comprehensive_analysis_prompt(file_paths)
            logging.info("Sending analysis request to RAG assistant")
            response = await self.rag_client.send_message_with_files(prompt, file_ids)
            
            analysis_data = self._parse_response(response)
            result = self._convert_to_enum_result(analysis_data, file_paths)
            
            logging.info("Analysis completed successfully")
            return result
            
        except Exception as e:
            logging.error(f"Error during analysis: {str(e)}")
            return self._create_error_manuscript_profile(file_paths, str(e))

    async def identify_document_content_types(self, file_ids: List[str]) -> List[Dict[str, Any]]:
        """Identify content types for document files"""
        file_paths = []
        for file_id in file_ids:
            uploaded_file = self.rag_client.get_file_by_id(file_id)
            if uploaded_file:
                file_paths.append(uploaded_file.file_path)

        results = []
        
        for i, file_path in enumerate(file_paths):
            uploaded_file = self.rag_client.get_file_by_id(file_ids[i])
            if not uploaded_file:
                continue
                
            # 检查原始文件类型，如果是数据文件就跳过
            original_file_type = uploaded_file.original_file_type
            if original_file_type in ['.csv', '.xlsx', '.xls', '.json', '.tsv']:
                logging.info(f"Skipping content type analysis for data file: {Path(file_path).name} (original type: {original_file_type})")
                continue
                
            file_extension = Path(file_path).suffix.lower()

            if file_extension in ['.pdf', '.docx', '.pptx', '.txt', '.rtf', '.html']:
                logging.info(f"Identifying content type for: {Path(file_path).name}")
                
                try: 
                    content_type_result = await self._identify_single_file_content_type(
                        file_ids[i], Path(file_path)
                    )
                
                    results.append({
                        'file_path': file_path,
                        'file_id': file_ids[i],
                        'content_type': content_type_result['content_type'],
                        'confidence': content_type_result['confidence'],
                        'error_message': content_type_result.get('error_message', None)
                    })
                
                except Exception as e:
                    logging.error(f"Error during content type identification: {str(e)}")
                    results.append({
                        'file_path': file_path,
                        'file_id': file_ids[i],
                        'content_type': 'unknown',
                        'confidence': 0.0,
                        'error_message': str(e)
                    })
                
            elif file_extension in ['.csv', '.xlsx', '.xls', '.json', '.tsv']:
                # This is a data file, no content type needed
                continue
    
        return results
    
    async def _identify_single_file_content_type(self, file_id: str, file_path: Path) -> Dict[str, Any]:
        """Identify content type for a single document file"""
        try:
            prompt = DocumentContentTypePrompts.get_content_type_identification_prompt(file_path.name)
            response = await self.rag_client.send_message_with_files(prompt, [file_id])
            data = self._parse_single_content_type_response(response)
            
            return {
                'content_type': data.get('content_type', 'unknown'),
                'confidence': data.get('confidence', 0.0),
                'error_message': data.get('error_message', None)
            }
            
        except Exception as e:
            logging.error(f"Error identifying content type for {file_path.name}: {e}")
            return {
                'content_type': 'unknown',
                'confidence': 0.0,
                'error_message': str(e)
            }

    def _parse_single_content_type_response(self, response: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Parse single file content type response with validation"""
        try:
            raw_response = response if isinstance(response, str) else str(response)
            
            if isinstance(response, dict):
                data = response
            else:
                if "```json" in response:
                    json_start = response.find("```json") + 7
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                elif "```" in response:
                    json_start = response.find("```") + 3
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                else:
                    json_str = response.strip()

                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON parsing failed for content type response: {e}")
                    return {
                        "content_type": "unknown",
                        "confidence": 0.0,
                        "error_message": f"JSON parsing failed: {e}"
                    }
            
            # Validate and normalize the parsed data
            content_type = self._validate_content_type(data.get('content_type', 'unknown'))
            confidence = self._validate_confidence(data.get('confidence', 0.0))
            
            return {
                'content_type': content_type,
                'confidence': confidence,
                'error_message': None
            }
            
        except Exception as e:
            logging.error(f"Error parsing content type response: {e}")
            return {
                'content_type': 'unknown',
                'confidence': 0.0,
                'error_message': f"Parsing error: {e}"
            }
    
    def _parse_response(self, response: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Parse RAG assistant response into structured data"""
        try:
            raw_response = response if isinstance(response, str) else str(response)
            
            if isinstance(response, dict):
                data = response
            else:
                if "```json" in response:
                    json_start = response.find("```json") + 7
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                elif "```" in response:
                    json_start = response.find("```") + 3
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                else:
                    json_str = response.strip()

                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError as e:
                    logging.warning(f"JSON parsing failed: {e}")
                    logging.info(f"Raw AI response: {raw_response}")

                    return {
                        "error": f"JSON parsing failed: {e}",
                        "raw_response": raw_response,
                        "study_type": {"type": "Unknown", "confidence": 0.0, "reasoning": "JSON parsing failed"},
                        "publication_type": {"type": "Unknown", "confidence": 0.0, "reasoning": "JSON parsing failed"},
                        "writing_purpose": {"primary_purpose": "Unknown", "confidence": 0.0, "reasoning": "JSON parsing failed"}
                    }
            
            # Validate required fields
            required_fields = ["study_type", "publication_type", "writing_purpose"]
            for field in required_fields:
                if field not in data:
                    logging.warning(f"Missing required field: {field}")
                    data[field] = {"type": "Unknown", "confidence": 0.0, "reasoning": f"Missing field: {field}"}

            data["raw_response"] = raw_response
            
            return data
            
        except Exception as e:
            logging.error(f"Error parsing response: {e}")
            logging.error(f"Raw response: {response}")
            raise
    
    def _convert_to_enum_result(self, analysis_data: Dict[str, Any], file_paths: List[Path]) -> ManuscriptProfile:
        """Convert parsed analysis data to ManuscriptProfile with enum types"""
        #study type
        study_type_data = analysis_data.get("study_type", {})
        study_type_str = study_type_data.get("type", "Unknown")
        study_type = self._map_to_study_type(study_type_str)
        
        #publication type
        publication_type_data = analysis_data.get("publication_type", {})
        publication_type_str = publication_type_data.get("type", "Unknown")
        publication_type = self._map_to_publication_type(publication_type_str)
        
        #writing purpose
        writing_purpose_data = analysis_data.get("writing_purpose", {})
        writing_purpose = self._create_writing_purpose_detail(writing_purpose_data)
        
        #confidence scores
        confidence_scores = {
            "study_type": study_type_data.get("confidence", 0.0),
            "publication_type": publication_type_data.get("confidence", 0.0),
            "writing_purpose": writing_purpose_data.get("confidence", 0.0)
        }
        
        #reasoning
        reasoning = {
            "study_type": study_type_data.get("reasoning", ""),
            "publication_type": publication_type_data.get("reasoning", ""),
            "writing_purpose": writing_purpose_data.get("reasoning", "")
        }
        
        #supporting evidence
        supporting_evidence = {
            "study_type": study_type_data.get("supporting_evidence", []),
            "publication_type": publication_type_data.get("supporting_evidence", []),
            "writing_purpose": writing_purpose_data.get("supporting_evidence", [])
        }
        
        #raw AI response
        raw_ai_response = analysis_data.get("raw_response", "")
        
        # Create ManuscriptProfile
        return ManuscriptProfile(
            study_type=study_type,
            publication_type=publication_type,
            writing_purpose=writing_purpose,
            confidence_scores=confidence_scores,
            reasoning=reasoning,
            supporting_evidence=supporting_evidence,
            file_paths=[str(path) for path in file_paths],
            analysis_metadata={
                "analysis_method": "RAG Assistant",
                "parsing_errors": analysis_data.get("error", None)
            },
            raw_ai_response=raw_ai_response
        )
    
    def _create_writing_purpose_detail(self, writing_purpose_data: Dict[str, Any]) -> WritingPurposeDetail:
        """Create WritingPurposeDetail from parsed data"""
        primary_purpose_str = writing_purpose_data.get("primary_purpose", "Unknown")
        primary_purpose = self._map_to_writing_purpose(primary_purpose_str)
        
        # Map secondary purposes
        secondary_purposes = []
        for purpose_str in writing_purpose_data.get("secondary_purposes", []):
            secondary_purposes.append(self._map_to_writing_purpose(purpose_str))
        
        return WritingPurposeDetail(
            primary_purpose=primary_purpose,
            secondary_purposes=secondary_purposes,
            summary=writing_purpose_data.get("summary", "Writing purpose analysis"),
            target_journal=writing_purpose_data.get("target_journal", "BMJ"),
            key_messages=writing_purpose_data.get("key_messages", []),
            writing_style=writing_purpose_data.get("writing_style", "formal academic"),
            tone=writing_purpose_data.get("tone", "objective"),
            focus_areas=writing_purpose_data.get("focus_areas", []),
            emphasis_points=writing_purpose_data.get("emphasis_points", [])
        )
    
    def _map_to_study_type(self, study_type_str: str) -> StudyType:
        """Map string to StudyType enum"""
        mapping = {
            "Randomized Controlled Trial": StudyType.RCT,
            "RCT": StudyType.RCT,
            "Cohort Study": StudyType.COHORT,
            "Case-Control Study": StudyType.CASE_CONTROL,
            "Cross-Sectional Study": StudyType.CROSS_SECTIONAL,
            "Case Report": StudyType.CASE_OBSERVATION,
            "Systematic Review": StudyType.SYSTEMATIC_REVIEW,
            "Meta-Analysis": StudyType.META_ANALYSIS,
            "Narrative Review": StudyType.NARRATIVE_REVIEW
        }
        return mapping.get(study_type_str, StudyType.COHORT)  # Default fallback
    
    def _map_to_publication_type(self, publication_type_str: str) -> PublicationType:
        """Map string to PublicationType enum"""
        mapping = {
            "Original Research": PublicationType.ORIGINAL_RESEARCH,
            "Review": PublicationType.REVIEW,
            "Case Report": PublicationType.CASE_REPORT,
            "Protocol": PublicationType.PROTOCOL,
            "Brief Report": PublicationType.BRIEF_REPORT
        }
        return mapping.get(publication_type_str, PublicationType.ORIGINAL_RESEARCH)  # Default fallback
    
    def _map_to_writing_purpose(self, writing_purpose_str: str) -> WritingPurpose:
        """Map string to WritingPurpose enum"""
        mapping = {
            "Original Research": WritingPurpose.ORIGINAL_RESEARCH,
            "Literature Review": WritingPurpose.LITERATURE_REVIEW,
            "Methodology": WritingPurpose.METHODOLOGY,
            "Case Study": WritingPurpose.CASE_STUDY,
            "Meta-Analysis": WritingPurpose.META_ANALYSIS,
            "Systematic Review": WritingPurpose.SYSTEMATIC_REVIEW,
            "Protocol": WritingPurpose.PROTOCOL
        }
        return mapping.get(writing_purpose_str, WritingPurpose.ORIGINAL_RESEARCH)  # Default fallback
    
    def _create_error_manuscript_profile(self, file_paths: List[Path], error_message: str) -> ManuscriptProfile:
        """Create a simple error manuscript profile"""
        return ManuscriptProfile(
            study_type=StudyType.COHORT,
            publication_type=PublicationType.ORIGINAL_RESEARCH,
            writing_purpose=WritingPurposeDetail(
                primary_purpose=WritingPurpose.ORIGINAL_RESEARCH,
                secondary_purposes=[],
                summary=f"Error in analysis: {error_message}",
                target_journal="BMJ",
                key_messages=["Analysis failed"],
                writing_style="formal academic",
                tone="objective",
                focus_areas=["methods", "results"],
                emphasis_points=["methodological rigor"]
            ),
            confidence_scores={"study_type": 0.0, "publication_type": 0.0, "writing_purpose": 0.0},
            reasoning={"study_type": f"Error: {error_message}", "publication_type": f"Error: {error_message}", "writing_purpose": f"Error: {error_message}"},
            supporting_evidence={"study_type": [], "publication_type": [], "writing_purpose": []},
            file_paths=[str(path) for path in file_paths],
            analysis_metadata={"error": error_message}
        )

    def _create_error_document_content_types(self) -> List[Dict[str, Any]]:
        """Create a simple error document content types"""
        return []
    
    def _validate_content_type(self, content_type: str) -> str:
        """Validate and normalize content type"""
        valid_types = {
            'protocol', 'case_report', 'literature_review', 'original_research',
            'meta_analysis', 'editorial', 'manuscript', 'unknown'
        }
        
        # Normalize common variations
        type_mapping = {
            'case report': 'case_report',
            'case study': 'case_report',
            'literature review': 'literature_review',
            'review': 'literature_review',
            'original research': 'original_research',
            'research': 'original_research',
            'meta analysis': 'meta_analysis',
            'meta-analysis': 'meta_analysis',
            'editorial': 'editorial',
            'commentary': 'editorial',
            'manuscript': 'manuscript',
            'paper': 'manuscript',
            'protocol': 'protocol',
            'study protocol': 'protocol'
        }
        
        # Normalize the input
        normalized = content_type.lower().strip()
        
        # Check direct mapping first
        if normalized in type_mapping:
            return type_mapping[normalized]
        
        # Check if it's already a valid type
        if normalized in valid_types:
            return normalized
        
        # If not recognized, return unknown
        logging.warning(f"Unknown content type: {content_type}, defaulting to 'unknown'")
        return 'unknown'
    
    def _validate_confidence(self, confidence: Any) -> float:
        """Validate and normalize confidence score"""
        try:
            conf = float(confidence)
            # Clamp between 0.0 and 1.0
            return max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            logging.warning(f"Invalid confidence value: {confidence}, defaulting to 0.0")
            return 0.0 