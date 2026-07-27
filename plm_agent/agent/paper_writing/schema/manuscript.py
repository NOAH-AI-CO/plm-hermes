from pydantic import BaseModel, Field, root_validator
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum
import json
from ..presets.enum import StudyType, PublicationType, WritingPurpose, ConfidenceLevel


class ManuscriptStatus(str, Enum):
    """Manuscript status enum"""
    DRAFT = "draft"           # Draft, just generated content
    REVIEW = "review"         # Under review (LLM or user reviewing)
    REVISED = "revised"       # Revised based on review comments
    FINAL = "final"           # Final version, passed review
    APPROVED = "approved"     # Approved by user

class Subsection(BaseModel):
    """Subsection"""
    name: str
    content: str
    word_count: int = Field(ge=0)
    dataset_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of dataset information")
    document_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of document information")
    completed_sections_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of completed sections")
    literature_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of literature search results")
    status: ManuscriptStatus = ManuscriptStatus.DRAFT
    created_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    updated_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()))

class Section(BaseModel):
    """Section"""
    name: str
    content: str
    word_count: int = Field(ge=0)
    subsections: Optional[List[Subsection]] = None
    dataset_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of dataset information")
    document_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of document information")
    completed_sections_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of completed sections")
    literature_citations: Optional[List[str]] = Field(default_factory=list, description="Citations of literature search results")
    status: ManuscriptStatus = ManuscriptStatus.DRAFT
    created_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    updated_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()))


class WritingPurposeDetail(BaseModel):
    """Detailed writing purpose information"""
    primary_purpose: WritingPurpose
    secondary_purposes: List[WritingPurpose] = Field(default_factory=list)
    summary: str = ""
    target_journal: str = ""
    key_messages: List[str] = Field(default_factory=list)
    writing_style: str = ""
    tone: str = ""
    focus_areas: List[str] = Field(default_factory=list)
    emphasis_points: List[str] = Field(default_factory=list)


class ManuscriptProfile(BaseModel):
    """Profile of the overall manuscript/project based on uploaded documents."""
    study_type: StudyType
    publication_type: PublicationType
    writing_purpose: WritingPurposeDetail
    confidence_scores: Dict[str, float] = Field(default_factory=dict)
    reasoning: Dict[str, str] = Field(default_factory=dict)
    supporting_evidence: Dict[str, List[str]] = Field(default_factory=dict)
    file_paths: List[str] = Field(default_factory=list)
    analysis_metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_ai_response: str = ""  # 存储 AI 的原始返回内容


class OutlineSection(BaseModel):
    """Represents a section in the manuscript outline"""
    title: str
    level: int = Field(ge=1, le=2, description="1 for main section, 2 for subsection")
    word_estimate: str
    content_hints: List[str] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    writing_guidance: List[str] = Field(default_factory=list)
    section_id: str = ""
    
    @root_validator(pre=True)
    def set_section_id(cls, values):
        if not values.get('section_id'):
            title = values.get('title', '')
            level = values.get('level', 1)
            section_id = f"section_{level}_{title.lower().replace(' ', '_')}"
            values['section_id'] = section_id
        return values


class ManuscriptOutline(BaseModel):
    """Complete manuscript outline with all metadata"""
    # Basic information
    study_type: StudyType
    publication_type: PublicationType
    target_journal: str
    
    # Outline structure
    sections: List[OutlineSection] = Field(default_factory=list)
    
    # Word estimates
    total_word_estimate: str = ""
    main_sections_count: int = 0
    subsections_count: int = 0
    
    # Writing guidance
    writing_style: str = ""
    tone: str = ""
    focus_areas: List[str] = Field(default_factory=list)
    emphasis_points: List[str] = Field(default_factory=list)
    
    # Additional metadata
    outline_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @root_validator(pre=True)
    def calculate_counts(cls, values):
        sections = values.get('sections', [])
        values['main_sections_count'] = len([s for s in sections if s.level == 1])
        values['subsections_count'] = len([s for s in sections if s.level == 2])
        return values
    
    def get_main_sections(self) -> List[OutlineSection]:
        """Get all main sections (level 1)"""
        return [s for s in self.sections if s.level == 1]
    
    def get_subsections(self, main_section_title: str) -> List[OutlineSection]:
        """Get all subsections for a given main section"""
        main_sections = self.get_main_sections()
        main_section = next((s for s in main_sections if s.title == main_section_title), None)
        
        if not main_section:
            return []
        
        # Find the index of the main section
        main_index = self.sections.index(main_section)
        
        # Find all subsections until the next main section
        subsections = []
        for i in range(main_index + 1, len(self.sections)):
            section = self.sections[i]
            if section.level == 1:  # Next main section
                break
            if section.level == 2:  # Subsection
                subsections.append(section)
        
        return subsections
    
    def get_section_by_id(self, section_id: str) -> Optional[OutlineSection]:
        """Get a section by its ID"""
        return next((s for s in self.sections if s.section_id == section_id), None)
    
    def get_total_word_count(self) -> tuple[int, int]:
        """Get total word count as (min, max) tuple"""
        total_min = 0
        total_max = 0
        
        for section in self.sections:
            if section.word_estimate and section.word_estimate != "N/A" and section.word_estimate != "Variable":
                try:
                    if "-" in section.word_estimate:
                        parts = section.word_estimate.split("-")
                        min_words = int(parts[0].strip())
                        max_words = int(parts[1].split()[0].strip())
                        total_min += min_words
                        total_max += max_words
                    else:
                        # Single number like "500 words"
                        words = int(section.word_estimate.split()[0].strip())
                        total_min += words
                        total_max += words
                except (ValueError, IndexError):
                    continue
        
        return total_min, total_max
        
class WritingGuidance(BaseModel):
    """Writing guidance for a specific section or overall manuscript"""
    section_id: str = ""
    section_title: str = ""
    
    # Content guidance
    content_suggestions: List[str] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    common_mistakes: List[str] = Field(default_factory=list)
    
    # Style guidance
    writing_style: str = ""
    tone: str = ""
    language_tips: List[str] = Field(default_factory=list)
    
    # Structure guidance
    structure_tips: List[str] = Field(default_factory=list)
    flow_suggestions: List[str] = Field(default_factory=list)
    
    # Examples
    example_phrases: List[str] = Field(default_factory=list)
    example_sentences: List[str] = Field(default_factory=list)


class ManuscriptWritingPlan(BaseModel):
    """Complete writing plan combining profile, outline, and guidance"""
    # Analysis results
    profile: ManuscriptProfile
    
    # Generated outline
    outline: ManuscriptOutline
    
    # Writing guidance
    overall_guidance: WritingGuidance = Field(default_factory=WritingGuidance)
    section_guidance: Dict[str, WritingGuidance] = Field(default_factory=dict)
    
    # Writing progress
    writing_status: str = "planned"
    completion_percentage: float = Field(ge=0, le=100, default=0.0)
    
    # Metadata
    created_at: str = ""
    updated_at: str = ""
    plan_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def get_section_guidance(self, section_id: str) -> Optional[WritingGuidance]:
        """Get writing guidance for a specific section"""
        return self.section_guidance.get(section_id)
    
    def add_section_guidance(self, section_id: str, guidance: WritingGuidance):
        """Add writing guidance for a specific section"""
        self.section_guidance[section_id] = guidance
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """Get a summary of writing progress"""
        return {
            "status": self.writing_status,
            "completion_percentage": self.completion_percentage,
            "total_sections": len(self.outline.sections),
            "main_sections": self.outline.main_sections_count,
            "subsections": self.outline.subsections_count,
            "total_words": self.outline.get_total_word_count()
        }