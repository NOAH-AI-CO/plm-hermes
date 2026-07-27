"""
Document content type identification prompts
"""

from pathlib import Path
from typing import List


class DocumentContentTypePrompts:
    """Prompts for document content type identification"""
    
    @staticmethod
    def get_content_type_identification_prompt(file_name: str) -> str:
        """
        Create prompt for identifying content type of a single document file
        
        Args:
            file_name: Name of the file to analyze
            
        Returns:
            Prompt string for content type identification
        """
        return f"""
You are a professional academic document analysis assistant. 

Please identify the content type of this document file: {file_name}

**IMPORTANT**: You must return ONLY one of these exact content types:
- protocol
- case_report  
- literature_review
- original_research
- meta_analysis
- editorial
- manuscript
- unknown

**IMPORTANT**: Return the results in JSON format:
{{
    "content_type": "protocol",
    "confidence": 0.95
}}

Rules:
1. content_type must be exactly one of the 8 types listed above
2. confidence must be a number between 0.0 and 1.0
3. Do not include any other fields or text outside the JSON
4. If you cannot determine the type, use "unknown" with low confidence
""" 