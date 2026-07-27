"""
Simplified Organized Data Schemas

A more streamlined approach without unnecessary sections layering
"""

from typing import List, Dict, Any, Optional, Union
from enum import Enum
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from pathlib import Path

class DocumentCategory(Enum):
    """Main document categories"""
    DATA_FILE = "data_file"           # Structured data files
    DOCUMENT_FILE = "document_file"    # Text-based documents
    IMAGE_FILE = "image_file"          # Visual content files
    UNKNOWN = "unknown"                # Unclassified files


class FileFormat(Enum):
    """File formats (technical format)"""
    # Data files
    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    TSV = "tsv"
    TXT_TABULAR = "txt_tabular"
    
    # Document files
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    RTF = "rtf"
    HTML = "html"
    
    # Image files
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    TIFF = "tiff"
    BMP = "bmp"
    SVG = "svg"
    
    # Unknown
    UNKNOWN = "unknown"


class DocumentContentType(Enum):
    """Content types for document files"""
    PROTOCOL = "protocol"              # Clinical protocols, study designs
    CASE_REPORT = "case_report"        # Case reports
    LITERATURE_REVIEW = "literature_review"  # Literature reviews
    ORIGINAL_RESEARCH = "original_research"  # Original research papers
    META_ANALYSIS = "meta_analysis"    # Meta-analyses
    EDITORIAL = "editorial"            # Editorials, commentaries
    MANUSCRIPT = "manuscript"          # General manuscripts
    UNKNOWN = "unknown"                # Unknown content type


class ProtocolContent(BaseModel):
    """Content extracted from protocol documents"""
    document_type: Optional[str] = Field(default="protocol", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    
    # Key protocol information (直接存储，不需要sections)
    study_design: Optional[str] = Field(default="", description="Study design information")
    participants: Optional[str] = Field(default="", description="Participant information")
    interventions: Optional[str] = Field(default="", description="Intervention details")
    outcomes: Optional[str] = Field(default="", description="Outcome measures")
    statistical_analysis: Optional[str] = Field(default="", description="Statistical analysis methods")
    ethics: Optional[str] = Field(default="", description="Ethics information")
    background: Optional[str] = Field(default="", description="Study background")
    objectives: Optional[str] = Field(default="", description="Study objectives")
    methodology: Optional[str] = Field(default="", description="Methodology details")
    safety_measures: Optional[str] = Field(default="", description="Safety measures")
    data_management: Optional[str] = Field(default="", description="Data management procedures")
    
    # Additional protocol metadata
    study_type: Optional[str] = Field(default="", description="Type of study")
    phase: Optional[str] = Field(default="", description="Study phase")
    primary_endpoint: Optional[str] = Field(default="", description="Primary endpoint")
    secondary_endpoints: Optional[List[str]] = Field(default_factory=list, description="Secondary endpoints")
    sample_size: Optional[str] = Field(default="", description="Sample size")
    duration: Optional[str] = Field(default="", description="Study duration")
    sites: Optional[List[str]] = Field(default_factory=list, description="Study sites")


class CaseReportContent(BaseModel):
    """Content extracted from case report documents"""
    document_type: Optional[str] = Field(default="case_report", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    
    # Key case report information
    case_presentation: Optional[str] = Field(default="", description="Case presentation")
    diagnosis: Optional[str] = Field(default="", description="Diagnosis")
    treatment: Optional[str] = Field(default="", description="Treatment details")
    outcome: Optional[str] = Field(default="", description="Treatment outcome")
    discussion: Optional[str] = Field(default="", description="Discussion")
    background: Optional[str] = Field(default="", description="Case background")
    clinical_history: Optional[str] = Field(default="", description="Clinical history")
    physical_examination: Optional[str] = Field(default="", description="Physical examination")
    laboratory_findings: Optional[str] = Field(default="", description="Laboratory findings")
    imaging_findings: Optional[str] = Field(default="", description="Imaging findings")
    follow_up: Optional[str] = Field(default="", description="Follow-up information")
    
    # Additional case metadata
    patient_age: Optional[str] = Field(default="", description="Patient age")
    patient_gender: Optional[str] = Field(default="", description="Patient gender")
    treatment_outcome: Optional[str] = Field(default="", description="Treatment outcome")
    follow_up_period: Optional[str] = Field(default="", description="Follow-up period")


class LiteratureReviewContent(BaseModel):
    """Content extracted from literature review documents"""
    document_type: Optional[str] = Field(default="literature_review", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    citations: Optional[List[str]] = Field(default_factory=list, description="Citations")
    
    # Key review information
    introduction: Optional[str] = Field(default="", description="Introduction")
    methods: Optional[str] = Field(default="", description="Review methods")
    results: Optional[str] = Field(default="", description="Review results")
    discussion: Optional[str] = Field(default="", description="Discussion")
    background: Optional[str] = Field(default="", description="Background")
    search_strategy: Optional[str] = Field(default="", description="Search strategy")
    inclusion_criteria: Optional[str] = Field(default="", description="Inclusion criteria")
    exclusion_criteria: Optional[str] = Field(default="", description="Exclusion criteria")
    data_extraction: Optional[str] = Field(default="", description="Data extraction methods")
    quality_assessment: Optional[str] = Field(default="", description="Quality assessment")
    synthesis: Optional[str] = Field(default="", description="Data synthesis")
    
    # Additional review metadata
    search_date: Optional[str] = Field(default="", description="Search date")
    databases_searched: Optional[List[str]] = Field(default_factory=list, description="Databases searched")
    studies_included: Optional[int] = Field(default=0, description="Number of studies included")
    studies_excluded: Optional[int] = Field(default=0, description="Number of studies excluded")
    quality_score: Optional[float] = Field(default=None, description="Quality score")


class OriginalResearchContent(BaseModel):
    """Content extracted from original research documents"""
    document_type: Optional[str] = Field(default="original_research", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    
    # Key research information
    abstract: Optional[str] = Field(default="", description="Abstract")
    introduction: Optional[str] = Field(default="", description="Introduction")
    methods: Optional[str] = Field(default="", description="Methods")
    results: Optional[str] = Field(default="", description="Results")
    discussion: Optional[str] = Field(default="", description="Discussion")
    background: Optional[str] = Field(default="", description="Background")
    objectives: Optional[str] = Field(default="", description="Objectives")
    materials: Optional[str] = Field(default="", description="Materials")
    procedures: Optional[str] = Field(default="", description="Procedures")
    statistical_analysis: Optional[str] = Field(default="", description="Statistical analysis")
    findings: Optional[str] = Field(default="", description="Findings")
    conclusions: Optional[str] = Field(default="", description="Conclusions")
    
    # Additional research metadata
    study_design: Optional[str] = Field(default="", description="Study design")
    population: Optional[str] = Field(default="", description="Study population")
    intervention: Optional[str] = Field(default="", description="Intervention")
    control: Optional[str] = Field(default="", description="Control group")
    primary_outcome: Optional[str] = Field(default="", description="Primary outcome")
    secondary_outcomes: Optional[List[str]] = Field(default_factory=list, description="Secondary outcomes")
    statistical_methods: Optional[str] = Field(default="", description="Statistical methods")
    sample_size_calculation: Optional[str] = Field(default="", description="Sample size calculation")


class DataFileContent(BaseModel):
    """Content extracted from data files"""
    document_type: Optional[str] = Field(default="data_file", description="Document type")
    data_type: Optional[str] = Field(default="structured_data", description="Data type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    table_count: Optional[int] = Field(default=0, description="Number of tables")
    data_summary: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Data summary")
    columns: Optional[List[str]] = Field(default_factory=list, description="Column names")
    row_count: Optional[int] = Field(default=0, description="Number of rows")
    data_types: Optional[Dict[str, str]] = Field(default_factory=dict, description="Data types")


class ImageFileContent(BaseModel):
    """Content extracted from image files"""
    document_type: Optional[str] = Field(default="image_file", description="Document type")
    image_type: Optional[str] = Field(default="visual_content", description="Image type")
    description: Optional[str] = Field(default="", description="Image description")
    file_format: Optional[str] = Field(default="", description="File format")
    content_length: Optional[int] = Field(default=0, description="Content length")
    image_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Image metadata")
    extracted_text: Optional[str] = Field(default="", description="Extracted text")
    chart_type: Optional[str] = Field(default=None, description="Chart type")
    data_points: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Data points")


class MetaAnalysisContent(BaseModel):
    """Content extracted from meta-analysis documents"""
    document_type: Optional[str] = Field(default="meta_analysis", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    citations: Optional[List[str]] = Field(default_factory=list, description="Citations")
    
    # Key meta-analysis information
    abstract: Optional[str] = Field(default="", description="Abstract")
    introduction: Optional[str] = Field(default="", description="Introduction")
    methods: Optional[str] = Field(default="", description="Methods")
    results: Optional[str] = Field(default="", description="Results")
    discussion: Optional[str] = Field(default="", description="Discussion")
    background: Optional[str] = Field(default="", description="Background")
    search_strategy: Optional[str] = Field(default="", description="Search strategy")
    inclusion_criteria: Optional[str] = Field(default="", description="Inclusion criteria")
    exclusion_criteria: Optional[str] = Field(default="", description="Exclusion criteria")
    data_extraction: Optional[str] = Field(default="", description="Data extraction")
    quality_assessment: Optional[str] = Field(default="", description="Quality assessment")
    statistical_methods: Optional[str] = Field(default="", description="Statistical methods")
    heterogeneity_analysis: Optional[str] = Field(default="", description="Heterogeneity analysis")
    publication_bias: Optional[str] = Field(default="", description="Publication bias")
    sensitivity_analysis: Optional[str] = Field(default="", description="Sensitivity analysis")
    conclusions: Optional[str] = Field(default="", description="Conclusions")
    
    # Additional meta-analysis metadata
    studies_included: Optional[int] = Field(default=0, description="Number of studies included")
    total_participants: Optional[int] = Field(default=0, description="Total participants")
    effect_size: Optional[float] = Field(default=None, description="Effect size")
    heterogeneity_i2: Optional[float] = Field(default=None, description="Heterogeneity I²")
    publication_bias_p_value: Optional[float] = Field(default=None, description="Publication bias p-value")


class EditorialContent(BaseModel):
    """Content extracted from editorial documents"""
    document_type: Optional[str] = Field(default="editorial", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    
    # Key editorial information
    introduction: Optional[str] = Field(default="", description="Introduction")
    main_arguments: Optional[str] = Field(default="", description="Main arguments")
    discussion: Optional[str] = Field(default="", description="Discussion")
    conclusions: Optional[str] = Field(default="", description="Conclusions")
    background: Optional[str] = Field(default="", description="Background")
    key_points: Optional[str] = Field(default="", description="Key points")
    recommendations: Optional[str] = Field(default="", description="Recommendations")
    future_directions: Optional[str] = Field(default="", description="Future directions")
    expert_opinion: Optional[str] = Field(default="", description="Expert opinion")
    policy_implications: Optional[str] = Field(default="", description="Policy implications")
    
    # Additional editorial metadata
    author_affiliation: Optional[str] = Field(default="", description="Author affiliation")
    target_audience: Optional[str] = Field(default="", description="Target audience")
    editorial_type: Optional[str] = Field(default="", description="Editorial type")


class ManuscriptContent(BaseModel):
    """Content extracted from general manuscript documents"""
    document_type: Optional[str] = Field(default="manuscript", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    
    # Key manuscript information
    abstract: Optional[str] = Field(default="", description="Abstract")
    introduction: Optional[str] = Field(default="", description="Introduction")
    methods: Optional[str] = Field(default="", description="Methods")
    results: Optional[str] = Field(default="", description="Results")
    discussion: Optional[str] = Field(default="", description="Discussion")
    conclusions: Optional[str] = Field(default="", description="Conclusions")
    background: Optional[str] = Field(default="", description="Background")
    objectives: Optional[str] = Field(default="", description="Objectives")
    materials: Optional[str] = Field(default="", description="Materials")
    procedures: Optional[str] = Field(default="", description="Procedures")
    findings: Optional[str] = Field(default="", description="Findings")
    limitations: Optional[str] = Field(default="", description="Limitations")
    future_work: Optional[str] = Field(default="", description="Future work")
    
    # Additional manuscript metadata
    study_type: Optional[str] = Field(default="", description="Study type")
    research_area: Optional[str] = Field(default="", description="Research area")
    methodology_type: Optional[str] = Field(default="", description="Methodology type")


class GeneralDocumentContent(BaseModel):
    """Content extracted from general document files"""
    document_type: Optional[str] = Field(default="general", description="Document type")
    raw_content: Optional[str] = Field(default="", description="Raw document content")
    tables: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Extracted tables")
    sections: Optional[Dict[str, str]] = Field(default_factory=dict, description="Document sections")
    document_structure: Optional[List[str]] = Field(default_factory=list, description="Document structure")
    
    # Generic content fields
    content_summary: Optional[str] = Field(default="", description="Content summary")
    main_sections: Optional[str] = Field(default="", description="Main sections")
    key_findings: Optional[str] = Field(default="", description="Key findings")
    conclusions: Optional[str] = Field(default="", description="Conclusions")
    document_structure_text: Optional[str] = Field(default="", description="Document structure text")


class OrganizedData(BaseModel):
    """Simplified organized data structure"""
    file_name: str = Field(..., description="File name")
    category: DocumentCategory = Field(..., description="Document category")
    content_type: Optional[DocumentContentType] = Field(default=None, description="Content type")
    content: Any = Field(..., description="Content object")  # One of the specific content types above


# File Classification Results
class FileClassificationResult(BaseModel):
    """Result of file classification"""
    file_id: str = Field(..., description="File ID")
    file_path: str = Field(..., description="File path")
    category: DocumentCategory = Field(..., description="Document category")
    file_format: FileFormat = Field(..., description="File format")
    content_type: Optional[DocumentContentType] = Field(default=None, description="Content type")
    confidence: float = Field(..., description="Classification confidence")
    is_protocol: bool = Field(default=False, description="Whether file is a protocol")
    processing_errors: List[str] = Field(default_factory=list, description="Processing errors")


class ClassificationSummary(BaseModel):
    """Summary of classification results"""
    total_documents: int = Field(..., description="Total number of documents")
    processing_errors: int = Field(..., description="Number of processing errors")
    average_confidence: float = Field(..., description="Average confidence score")
    by_category: Dict[str, int] = Field(default_factory=dict, description="Count by category")
    by_format: Dict[str, int] = Field(default_factory=dict, description="Count by format")
    by_content_type: Dict[str, int] = Field(default_factory=dict, description="Count by content type")
    protocol_files: int = Field(..., description="Number of protocol files")


class ComprehensiveAnalysisResult(BaseModel):
    """Complete analysis result including file classification and manuscript profile"""
    manuscript_profile: Any = Field(..., description="Manuscript profile")  # ManuscriptProfile from manuscript.py
    file_classifications: List[FileClassificationResult] = Field(..., description="File classification results")
    classification_summary: ClassificationSummary = Field(..., description="Classification summary")


# Legacy support - keep the old dataclass versions for backward compatibility
@dataclass
class ClassificationResult:
    """Result of document classification (legacy)"""
    category: DocumentCategory
    file_format: FileFormat
    content_type: Optional[DocumentContentType] = None
    confidence: float = 0.0


@dataclass
class ClassifiedDocument:
    """Classified document with metadata (legacy)"""
    file_path: Path
    classification: ClassificationResult
    file_id: Optional[str] = None
    processing_errors: List[str] = field(default_factory=list)
    
    @property
    def category(self) -> DocumentCategory:
        return self.classification.category
    
    @property
    def file_format(self) -> FileFormat:
        return self.classification.file_format
    
    @property
    def content_type(self) -> Optional[DocumentContentType]:
        return self.classification.content_type
    
    @property
    def confidence(self) -> float:
        return self.classification.confidence
    
    @property
    def is_protocol(self) -> bool:
        return (self.category == DocumentCategory.DOCUMENT_FILE and 
                self.content_type == DocumentContentType.PROTOCOL)


@dataclass
class DocumentCollection:
    """Collection of classified documents (legacy)"""
    documents: List[ClassifiedDocument] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    def get_by_category(self, category: DocumentCategory) -> List[ClassifiedDocument]:
        return [doc for doc in self.documents if doc.category == category]
    
    def get_by_format(self, file_format: FileFormat) -> List[ClassifiedDocument]:
        return [doc for doc in self.documents if doc.file_format == file_format]
    
    def get_by_content_type(self, content_type: DocumentContentType) -> List[ClassifiedDocument]:
        return [doc for doc in self.documents if doc.content_type == content_type]
    
    def get_data_files(self) -> List[ClassifiedDocument]:
        return self.get_by_category(DocumentCategory.DATA_FILE)
    
    def get_document_files(self) -> List[ClassifiedDocument]:
        return self.get_by_category(DocumentCategory.DOCUMENT_FILE)
    
    def get_protocol_files(self) -> List[ClassifiedDocument]:
        return self.get_by_content_type(DocumentContentType.PROTOCOL)
    
    def get_image_files(self) -> List[ClassifiedDocument]:
        return self.get_by_category(DocumentCategory.IMAGE_FILE)
    
    def get_files_with_errors(self) -> List[ClassifiedDocument]:
        return [doc for doc in self.documents if doc.processing_errors]
    
    def generate_summary(self) -> Dict[str, Any]:
        summary = {
            "total_documents": len(self.documents),
            "by_category": {},
            "by_format": {},
            "by_content_type": {},
            "protocol_files": len(self.get_protocol_files()),
            "processing_errors": len(self.get_files_with_errors()),
            "average_confidence": 0.0
        }
        
        for category in DocumentCategory:
            docs = self.get_by_category(category)
            summary["by_category"][category.value] = len(docs)
        
        for file_format in FileFormat:
            docs = self.get_by_format(file_format)
            if docs:
                summary["by_format"][file_format.value] = len(docs)
        
        for content_type in DocumentContentType:
            docs = self.get_by_content_type(content_type)
            if docs:
                summary["by_content_type"][content_type.value] = len(docs)
        
        if self.documents:
            total_confidence = sum(doc.confidence for doc in self.documents)
            summary["average_confidence"] = total_confidence / len(self.documents)
        
        return summary


# Content type mapping
CONTENT_TYPE_MAPPING = {
    DocumentContentType.PROTOCOL: ProtocolContent,
    DocumentContentType.CASE_REPORT: CaseReportContent,
    DocumentContentType.LITERATURE_REVIEW: LiteratureReviewContent,
    DocumentContentType.ORIGINAL_RESEARCH: OriginalResearchContent,
    DocumentContentType.META_ANALYSIS: MetaAnalysisContent,
    DocumentContentType.EDITORIAL: EditorialContent,
    DocumentContentType.MANUSCRIPT: ManuscriptContent,
    DocumentContentType.UNKNOWN: GeneralDocumentContent,
} 