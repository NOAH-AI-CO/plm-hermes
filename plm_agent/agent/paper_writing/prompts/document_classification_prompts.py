"""
Document classification prompts

Prompts for classifying documents using RAG assistant
"""


class DocumentClassificationPrompts:
    """Prompts for document classification"""
    
    @staticmethod
    def get_classification_prompt() -> str:
        """Get the main classification prompt"""
        return """
        You are a file classifier. Analyze the uploaded file and return ONLY a JSON response.

        **OUTPUT FORMAT: You must respond with ONLY a valid JSON object.**

        **CLASSIFICATION RULES:**
        - category: Main file type (must be one of: DATA_FILE, DOCUMENT_FILE, IMAGE_FILE)
        - file_format: File format
        - content_type: Only for DOCUMENT_FILE
        - confidence: Confidence score (0.0 to 1.0)

        **CATEGORIES (enum - choose exactly one):**
        - DATA_FILE: Structured data files (tables, spreadsheets)
        - DOCUMENT_FILE: Text-based documents (reports, papers)
        - IMAGE_FILE: Visual content files (photos, diagrams)

        **FILE FORMATS:**
        - Data: csv, excel, json, tsv, txt_tabular
        - Documents: pdf, docx, pptx, txt, rtf, html
        - Images: png, jpg, jpeg, tiff, bmp, svg

        **CONTENT TYPES:**
        - protocol: Clinical protocols, study designs
        - case_report: Case reports
        - literature_review: Literature reviews
        - original_research: Original research papers
        - meta_analysis: Meta-analyses
        - editorial: Editorials, commentaries
        - manuscript: General manuscripts

        **NOTE:** If file was converted (e.g., Excel to txt), use the original format.

        **REQUIRED JSON RESPONSE:**
        {
            "category": "DOCUMENT_FILE",
            "file_format": "pdf",
            "content_type": "protocol",
            "confidence": 0.95
        }

        **IMPORTANT:**
        - Use double quotes for JSON
        - Do not include any text before or after the JSON
        - Return ONLY the JSON object
        - Use ONLY the exact enum values listed above
        """
    
    @staticmethod
    def get_content_analysis_prompt() -> str:
        """Get content analysis prompt for determining category and content_type based on file content"""
        return """
        You are a content analyzer. Analyze the uploaded file content and return ONLY a JSON response.
        
        **OUTPUT FORMAT: You must respond with ONLY a valid JSON object.**
        
        **ANALYSIS RULES:**
        - category: Main content type (must be one of: DATA_FILE, DOCUMENT_FILE, IMAGE_FILE)
        - content_type: Only for DOCUMENT_FILE (can be null for other categories)
        - confidence: Confidence score (0.0 to 1.0)
        - reasoning: Brief explanation of why you chose this classification (for debugging)
        
        **CATEGORIES:**
        
        **DATA_FILE:** 
        - Contains mostly tables, numbers, structured data
        - Raw data without much text explanation
        
        **DOCUMENT_FILE:**
        - Contains mostly text content, articles, reports
        - Narrative content with explanations
        
        **IMAGE_FILE:**
        - Contains mostly visual content, pictures, diagrams
        
        **CONTENT TYPES (only for DOCUMENT_FILE):**
        - protocol: Clinical protocols, study designs
        - case_report: Case reports, patient cases
        - literature_review: Literature reviews, review articles
        - original_research: Research papers, experimental studies
        - meta_analysis: Meta-analyses, statistical analyses
        - editorial: Editorials, commentaries
        - manuscript: General manuscripts, drafts
        
        **REQUIRED JSON RESPONSE:**
        {
            "category": "DOCUMENT_FILE",
            "content_type": "protocol",
            "confidence": 0.95,
            "reasoning": "Contains clinical protocol text with study design sections"
        }
        
        **IMPORTANT:**
        - Use double quotes for JSON
        - Return ONLY the JSON object
        - content_type can be null for DATA_FILE and IMAGE_FILE
        - reasoning field is for debugging purposes
        """ 