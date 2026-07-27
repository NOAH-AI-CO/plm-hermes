"""
Journal and Writing Style Templates

Templates for medical journals and their associated writing styles
"""

from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class JournalTemplate:
    """Template for a medical journal's writing requirements"""
    journal_name: str
    impact_factor: str
    writing_style: str
    tone: str
    target_audience: List[str]
    typical_sections: List[str]
    word_limit: str
    key_requirements: List[str]
    example_phrases: List[str]


class MedicalJournalTemplates:
    """Collection of medical journal templates"""
    
    @staticmethod
    def get_journal_templates() -> Dict[str, JournalTemplate]:
        """Get all available journal templates"""
        return {
            "NEJM": JournalTemplate(
                journal_name="New England Journal of Medicine",
                impact_factor="176.079",
                writing_style="formal academic, clinical focus",
                tone="authoritative, evidence-based",
                target_audience=["clinicians", "researchers", "policymakers"],
                typical_sections=["Abstract", "Introduction", "Methods", "Results", "Discussion", "References"],
                word_limit="3000-4000 words",
                key_requirements=[
                    "Clear clinical relevance",
                    "Strong statistical analysis",
                    "Concise writing",
                    "Clinical implications clearly stated"
                ],
                example_phrases=[
                    "This study demonstrates that...",
                    "The clinical implications of these findings are...",
                    "Our results suggest that..."
                ]
            ),
            
            "Lancet": JournalTemplate(
                journal_name="The Lancet",
                impact_factor="168.9",
                writing_style="formal academic, global health focus",
                tone="authoritative, international perspective",
                target_audience=["global health professionals", "researchers", "policymakers"],
                typical_sections=["Summary", "Introduction", "Methods", "Findings", "Interpretation", "References"],
                word_limit="3500-4500 words",
                key_requirements=[
                    "Global health implications",
                    "Clear methodology",
                    "Robust statistical analysis",
                    "Policy recommendations"
                ],
                example_phrases=[
                    "Our findings have important implications for global health...",
                    "This study provides evidence that...",
                    "Policy makers should consider..."
                ]
            ),
            
            "JAMA": JournalTemplate(
                journal_name="Journal of the American Medical Association",
                impact_factor="157.3",
                writing_style="formal academic, clinical research",
                tone="objective, evidence-based",
                target_audience=["physicians", "researchers", "medical students"],
                typical_sections=["Abstract", "Introduction", "Methods", "Results", "Discussion", "Conclusions"],
                word_limit="3000-4000 words",
                key_requirements=[
                    "Clear clinical question",
                    "Rigorous methodology",
                    "Clinical significance",
                    "Limitations acknowledged"
                ],
                example_phrases=[
                    "This randomized clinical trial shows...",
                    "The findings suggest that...",
                    "Clinical implications include..."
                ]
            ),
            
            "BMJ": JournalTemplate(
                journal_name="British Medical Journal",
                impact_factor="105.7",
                writing_style="accessible academic, practical focus",
                tone="clear, practical, evidence-based",
                target_audience=["general practitioners", "clinicians", "researchers"],
                typical_sections=["Abstract", "Introduction", "Methods", "Results", "Discussion", "What is already known", "What this study adds"],
                word_limit="2500-3500 words",
                key_requirements=[
                    "Clear practical implications",
                    "Accessible writing style",
                    "Clinical relevance",
                    "What is already known vs new findings"
                ],
                example_phrases=[
                    "What is already known on this topic...",
                    "What this study adds...",
                    "How this study might affect research, practice, or policy..."
                ]
            ),
            
            "Nature Medicine": JournalTemplate(
                journal_name="Nature Medicine",
                impact_factor="87.241",
                writing_style="formal academic, translational focus",
                tone="scientific, innovative",
                target_audience=["basic scientists", "clinicians", "translational researchers"],
                typical_sections=["Abstract", "Introduction", "Results", "Discussion", "Methods", "References"],
                word_limit="4000-6000 words",
                key_requirements=[
                    "Novel mechanistic insights",
                    "Translational relevance",
                    "Rigorous experimental design",
                    "Clear clinical implications"
                ],
                example_phrases=[
                    "Our mechanistic studies reveal...",
                    "These findings provide a foundation for...",
                    "The translational implications include..."
                ]
            ),
            
            "Cell": JournalTemplate(
                journal_name="Cell",
                impact_factor="66.85",
                writing_style="formal academic, mechanistic focus",
                tone="scientific, detailed",
                target_audience=["basic scientists", "researchers", "graduate students"],
                typical_sections=["Highlights", "Summary", "Introduction", "Results", "Discussion", "Star Methods"],
                word_limit="5000-8000 words",
                key_requirements=[
                    "Novel mechanistic insights",
                    "Comprehensive experimental approach",
                    "Clear conceptual advance",
                    "Detailed methodology"
                ],
                example_phrases=[
                    "Our findings establish a new paradigm...",
                    "These results demonstrate that...",
                    "This work reveals a previously unknown mechanism..."
                ]
            ),
            
            "Science": JournalTemplate(
                journal_name="Science",
                impact_factor="56.9",
                writing_style="formal academic, broad impact",
                tone="scientific, accessible to broad audience",
                target_audience=["scientists across disciplines", "policymakers", "educated public"],
                typical_sections=["Abstract", "Introduction", "Materials and Methods", "Results", "Discussion", "References"],
                word_limit="4000-6000 words",
                key_requirements=[
                    "Broad scientific impact",
                    "Clear significance",
                    "Rigorous methodology",
                    "Accessible to non-specialists"
                ],
                example_phrases=[
                    "This work has broad implications for...",
                    "Our findings suggest a new approach to...",
                    "These results advance our understanding of..."
                ]
            ),
            
            "PLOS Medicine": JournalTemplate(
                journal_name="PLOS Medicine",
                impact_factor="15.8",
                writing_style="accessible academic, open access",
                tone="clear, evidence-based, accessible",
                target_audience=["researchers", "clinicians", "public health professionals"],
                typical_sections=["Abstract", "Introduction", "Methods", "Results", "Discussion", "Supporting Information"],
                word_limit="3000-5000 words",
                key_requirements=[
                    "Open access publication",
                    "Clear methodology",
                    "Public health relevance",
                    "Accessible writing"
                ],
                example_phrases=[
                    "This study provides evidence that...",
                    "Our findings suggest that...",
                    "These results have implications for public health..."
                ]
            ),
            
            "Clinical Trials": JournalTemplate(
                journal_name="Clinical Trials",
                impact_factor="2.4",
                writing_style="formal academic, methodological focus",
                tone="technical, precise",
                target_audience=["clinical trialists", "methodologists", "researchers"],
                typical_sections=["Abstract", "Introduction", "Methods", "Results", "Discussion", "References"],
                word_limit="3000-5000 words",
                key_requirements=[
                    "Clear trial methodology",
                    "Statistical rigor",
                    "Protocol adherence",
                    "Methodological innovation"
                ],
                example_phrases=[
                    "This trial demonstrates the feasibility of...",
                    "Our methodological approach shows...",
                    "The trial design addresses..."
                ]
            )
        }
    
    @staticmethod
    def get_journal_by_name(journal_name: str) -> JournalTemplate:
        """Get journal template by name"""
        templates = MedicalJournalTemplates.get_journal_templates()
        # Case-insensitive search
        for key, template in templates.items():
            if journal_name.lower() in template.journal_name.lower():
                return template
        # Return default if not found
        return templates["BMJ"]  # Default to BMJ
    
    @staticmethod
    def get_writing_style_guide(journal_name: str) -> Dict[str, Any]:
        """Get writing style guide for a specific journal"""
        template = MedicalJournalTemplates.get_journal_by_name(journal_name)
        return {
            "journal_name": template.journal_name,
            "writing_style": template.writing_style,
            "tone": template.tone,
            "target_audience": template.target_audience,
            "key_requirements": template.key_requirements,
            "example_phrases": template.example_phrases
        }
    
    @staticmethod
    def suggest_journal(study_type: str, publication_type: str, impact_level: str = "high") -> List[str]:
        """Suggest appropriate journals based on study characteristics"""
        suggestions = {
            "high_impact": ["NEJM", "Lancet", "JAMA", "Nature Medicine"],
            "medium_impact": ["BMJ", "PLOS Medicine", "Science"],
            "specialized": ["Clinical Trials", "Cell"]
        }
        
        # Basic suggestions based on impact level
        if impact_level == "high":
            return suggestions["high_impact"]
        elif impact_level == "medium":
            return suggestions["medium_impact"]
        else:
            return suggestions["specialized"] 