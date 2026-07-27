from pydantic import BaseModel, Field
from typing import List, Optional, Set, Literal
from enum import Enum
from dataclasses import dataclass, field

class AbstractKeywordsSchema(BaseModel):
    keywords_cn: List[str] = Field(description="Keywords in Chinese")
    keywords_en: List[str] = Field(description="Keywords in English")

class StudyType(str, Enum):
    STUDY_CHARACTERISTICS = "Study Characteristics"
    CASE_REPORTS = "Case Reports"
    CLINICAL_CONFERENCE = "Clinical Conference"
    CLINICAL_STUDY = "Clinical Study"
    CLINICAL_TRIAL = "Clinical Trial"
    CLINICAL_TRIAL_PROTOCOL = "Clinical Trial Protocol"
    CLINICAL_TRIAL_VETERINARY = "Clinical Trial, Veterinary"
    OBSERVATIONAL_STUDY = "Observational Study"
    OBSERVATIONAL_STUDY_VETERINARY = "Observational Study, Veterinary"
    COMPARATIVE_STUDY = "Comparative Study"
    EVALUATION_STUDY = "Evaluation Study"
    EVIDENCE_SYNTHESIS = "Evidence Synthesis"
    CONSENSUS_STATEMENT = "Consensus Statement"
    GUIDELINE = "Guideline"
    META_ANALYSIS = "Meta-Analysis"
    SCOPING_REVIEW = "Scoping Review"
    SYSTEMATIC_REVIEW = "Systematic Review"
    NETWORK_META_ANALYSIS = "Network Meta-Analysis"
    MULTICENTER_STUDY = "Multicenter Study"
    SCIENTIFIC_INTEGRITY_REVIEW = "Scientific Integrity Review"
    TWIN_STUDY = "Twin Study"
    VALIDATION_STUDY = "Validation Study"

class AbstractStudyTypeSchema(BaseModel):
    study_types: List[str] = Field(
        description="One or more study types selected from a controlled list",
        examples=[e.value for e in StudyType]
    )


STUDY_TYPE_PROPERTIES = {
    # ---------- Original research ----------
    StudyType.CLINICAL_STUDY: {"category": "original"},
    StudyType.CLINICAL_TRIAL: {"category": "original"},
    StudyType.CLINICAL_TRIAL_PROTOCOL: {"category": "protocol"},
    StudyType.OBSERVATIONAL_STUDY: {"category": "original"},
    StudyType.COMPARATIVE_STUDY: {"category": "original"},
    StudyType.EVALUATION_STUDY: {"category": "original"},
    StudyType.MULTICENTER_STUDY: {"category": "original"},
    StudyType.VALIDATION_STUDY: {"category": "original"},
    StudyType.TWIN_STUDY: {"category": "original"},
    StudyType.CLINICAL_CONFERENCE: {"category": "original"},
    StudyType.STUDY_CHARACTERISTICS: {"category": "original"},

    # ---------- Case ----------
    StudyType.CASE_REPORTS: {"category": "case"},

    # ---------- Review / synthesis ----------
    StudyType.EVIDENCE_SYNTHESIS: {"category": "review"},
    StudyType.SYSTEMATIC_REVIEW: {"category": "review"},
    StudyType.SCOPING_REVIEW: {"category": "review"},
    StudyType.META_ANALYSIS: {"category": "review"},
    StudyType.NETWORK_META_ANALYSIS: {"category": "review"},
    StudyType.SCIENTIFIC_INTEGRITY_REVIEW: {"category": "review"},

    # ---------- Guideline / consensus ----------
    StudyType.GUIDELINE: {"category": "guideline"},
    StudyType.CONSENSUS_STATEMENT: {"category": "guideline"},

    # ---------- Veterinary ----------
    StudyType.CLINICAL_TRIAL_VETERINARY: {"category": "veterinary"},
    StudyType.OBSERVATIONAL_STUDY_VETERINARY: {"category": "veterinary"},
}


@dataclass
class StudyJournalCompatibilityProfile:
    study_type: StudyType

    # hard constraints
    is_structurally_excluded: bool
    exclusion_reason: Optional[str]

    # evidence layers
    pubmed_supported: bool
    pubmed_count: int

    # WoS structural signals
    article_pct: float
    review_pct: float

    # final score
    compatibility_score: float

@dataclass
class StudyJournalCompatibilityResult:
    journal_id: str
    is_excluded: bool
    exclusion_reason: Optional[str]
    pubmed_count: int
    score: float

class JournalFitResult(BaseModel):
    area_fit: str = Field(
        description="How well the manuscript topic matches the journal's research areas. Must be one of: STRONG, MODERATE, WEAK"
    )

    area_fit_explanation: List[str] = Field(
        description="Reasons explaining the area fit judgment"
    )

    tier_alignment: str = Field(
        description="How the manuscript level aligns with the journal tier. Must be one of: WELL_MATCHED, SLIGHTLY_AMBITIOUS, OVERLY_AMBITIOUS, OVERQUALIFIED"
    )

    tier_alignment_explanation: List[str] = Field(
        description="Reasons explaining the tier alignment judgment"
    )
