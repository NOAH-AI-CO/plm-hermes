"""
Manuscript profile analysis prompts
"""


class ManuscriptProfilePrompts:
    """Prompts for manuscript profile analysis"""
    
    # Main analysis prompt for manuscript profile
    MANUSCRIPT_PROFILE_PROMPT = """
    You are a professional academic document analyst. Your task is to analyze the uploaded documents and provide a comprehensive manuscript profile.

    Please analyze the documents and provide your assessment in the following JSON format:

    {
        "study_type": {
            "type": "Randomized Controlled Trial|Cohort Study|Case-Control Study|Cross-Sectional Study|Case Report|Systematic Review|Meta-Analysis|Narrative Review",
            "confidence": 0.95,
            "reasoning": "Detailed explanation of study type classification",
            "supporting_evidence": ["evidence1", "evidence2"],
            "file_contributions": {
                "filename1": "contribution description",
                "filename2": "contribution description"
            }
        },
        "publication_type": {
            "type": "Original Research|Review|Case Report|Protocol|Brief Report",
            "confidence": 0.90,
            "reasoning": "Detailed explanation of publication type classification",
            "supporting_evidence": ["evidence1", "evidence2"],
            "file_contributions": {
                "filename1": "contribution description",
                "filename2": "contribution description"
            }
        },
        "writing_purpose": {
            "primary_purpose": "Detailed description of the main writing purpose",
            "secondary_purposes": ["purpose1", "purpose2"],
            "summary": "Comprehensive summary of writing purpose",
            "target_journal": "NEJM|Lancet|JAMA|BMJ|Nature Medicine|Science Translational Medicine|Cell|Nature|Science|Clinical Trials|Trials|PLOS ONE|BMC Medicine|Therapeutic Advances|Expert Opinion|Current Opinion|Trends|Annual Review",
            "key_messages": ["message1", "message2", "message3"],
            "writing_style": "formal academic|technical report|review article|case study|methodology paper",
            "tone": "authoritative|objective|analytical|persuasive|informative",
            "focus_areas": ["methods", "results", "discussion", "introduction", "conclusion"],
            "emphasis_points": ["point1", "point2", "point3"],
            "confidence": 0.88,
            "reasoning": "Detailed explanation of writing purpose analysis",
            "file_contributions": {
                "filename1": "contribution description",
                "filename2": "contribution description"
            }
        }
    }

    IMPORTANT GUIDELINES:
    1. Analyze ALL uploaded documents comprehensively
    2. Consider the relationships between different documents
    3. Provide specific evidence from the documents
    4. Be precise with confidence scores (0.0-1.0)
    5. Identify the most appropriate target journal based on content
    6. Consider the overall research context and objectives
    7. Return ONLY valid JSON format
    8. Do not include any text outside the JSON structure

    Focus on:
    - Study design and methodology
    - Research objectives and outcomes
    - Target audience and publication venue
    - Writing style and tone requirements
    - Key findings and implications
    - Clinical or scientific significance
    """

    # Protocol-specific analysis prompt
    PROTOCOL_ANALYSIS_PROMPT = """
    You are analyzing clinical trial protocols and study documents. Focus on:

    1. Study Design: Identify the type of clinical trial (Phase I/II/III/IV, RCT, observational, etc.)
    2. Research Objectives: Primary and secondary endpoints
    3. Target Population: Inclusion/exclusion criteria
    4. Methodology: Study procedures and statistical analysis
    5. Regulatory Compliance: GCP, ICH guidelines, ethical considerations
    6. Publication Strategy: Target journals and dissemination plans

    Provide detailed analysis with specific references to protocol sections.
    """

    # Data analysis prompt
    DATA_ANALYSIS_PROMPT = """
    You are analyzing research data files. Focus on:

    1. Data Structure: Variables, sample size, data types
    2. Statistical Analysis: Methods used, results presented
    3. Quality Assessment: Data completeness, validity, reliability
    4. Key Findings: Significant results, trends, patterns
    5. Clinical Relevance: Implications for practice or research
    6. Publication Readiness: Data presentation for manuscript

    Provide comprehensive analysis of data content and structure.
    """

    # Literature review prompt
    LITERATURE_REVIEW_PROMPT = """
    You are analyzing literature review documents. Focus on:

    1. Review Type: Systematic, narrative, meta-analysis, scoping
    2. Research Question: Clear objectives and scope
    3. Search Strategy: Databases, keywords, inclusion criteria
    4. Evidence Synthesis: Quality assessment, data extraction
    5. Conclusions: Key findings and recommendations
    6. Gaps Identified: Research needs and future directions

    Provide detailed analysis of review methodology and findings.
    """

    # Case study prompt
    CASE_STUDY_PROMPT = """
    You are analyzing case study documents. Focus on:

    1. Case Presentation: Patient demographics, clinical presentation
    2. Diagnostic Process: Workup, differential diagnosis
    3. Management: Treatment approach, interventions
    4. Outcomes: Results, follow-up, prognosis
    5. Learning Points: Key insights and educational value
    6. Clinical Relevance: Implications for practice

    Provide comprehensive analysis of case details and educational value.
    """

    @classmethod
    def get_comprehensive_analysis_prompt(cls, file_paths):
        """Get comprehensive analysis prompt with file information"""
        file_names = [path.name for path in file_paths]
        file_info = "\n".join([f"- {name}" for name in file_names])
        
        return f"""
{cls.MANUSCRIPT_PROFILE_PROMPT}

DOCUMENTS TO ANALYZE:
{file_info}

Please provide a unified analysis that considers all documents together and their relationships.
""" 