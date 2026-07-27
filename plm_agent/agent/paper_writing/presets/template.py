"""
写作模板和结构定义

包含基于研究类型和发表类型的写作大纲模板
"""

from typing import List, Dict, Union
from .enum import StudyType, PublicationType


# 研究类型到发表类型的映射
STUDY_PUBLICATION_MAP = {
    StudyType.RCT: [PublicationType.ORIGINAL_RESEARCH, PublicationType.PROTOCOL],
    StudyType.NON_RANDOMIZED_INTERVENTION: [PublicationType.ORIGINAL_RESEARCH, PublicationType.PROTOCOL],
    StudyType.COHORT: [PublicationType.ORIGINAL_RESEARCH, PublicationType.PROTOCOL],
    StudyType.CASE_CONTROL: [PublicationType.ORIGINAL_RESEARCH, PublicationType.BRIEF_REPORT],
    StudyType.CROSS_SECTIONAL: [PublicationType.ORIGINAL_RESEARCH],
    StudyType.CASE_OBSERVATION: [PublicationType.CASE_REPORT, PublicationType.CASE_SERIES],
    StudyType.PROGNOSTIC: [PublicationType.ORIGINAL_RESEARCH],
    StudyType.DIAGNOSTIC: [PublicationType.ORIGINAL_RESEARCH],
    StudyType.SYSTEMATIC_REVIEW: [PublicationType.REVIEW],
    StudyType.NARRATIVE_REVIEW: [PublicationType.REVIEW],
    StudyType.META_ANALYSIS: [PublicationType.REVIEW],
}

StudyTypeKey = Union[StudyType, str]

# 手稿结构模板
MANUSCRIPT_STRUCTURE = {
    # ------------------------ Intervention Studies ------------------------ #
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.RCT, PublicationType.PROTOCOL): [
        "Title", "Abstract", "Introduction", "Methods", "Ethics and Dissemination", "References"
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.PROTOCOL): [
        "Title", "Abstract", "Introduction", "Methods", "Ethics and Dissemination", "References"
    ],

    # ------------------------ Observational Studies ------------------------ #
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.COHORT, PublicationType.BRIEF_REPORT): [
        "Title", "Abstract", "Background", "Methods", "Results", "Conclusions", "References"
    ],
    (StudyType.CASE_CONTROL, PublicationType.BRIEF_REPORT): [
        "Title", "Abstract", "Background", "Methods", "Results", "Conclusions", "References"
    ],

    # ------------------------ Case Observations ------------------------ #
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT): [
        "Title", "Abstract", "Introduction", "Case Presentation", "Discussion", "References"
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES): [
        "Title", "Abstract", "Introduction", "Case Series", "Discussion", "References"
    ],

    # ------------------------ Diagnostic / Prognostic ------------------------ #
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],

    # ------------------------ Reviews ------------------------ #
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW): [
        "Title", "Abstract", "Introduction", "Main Topics", "Discussion", "References"
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW): [
        "Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"
    ],

    # ------------------------ Special Types ------------------------ #
    (StudyType.COHORT, PublicationType.DATA_NOTE): [
        "Title", "Abstract", "Introduction", "Methods", "Applications", "Data Availability", "References"
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT): [
        "Title", "Abstract", "Introduction", "Methods", "Evaluation", "Applications", "Discussion", "References"
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT): [
        "Title", "Abstract", "Introduction", "Methods", "Evaluation", "Applications", "Discussion", "References"
    ],
    ("ANY", PublicationType.OPINION): [
        "Title", "Abstract", "Perspective / Commentary Body", "References"
    ],
    ("ANY", PublicationType.LETTER): [
        "Title", "Body Text", "References"
    ]
}

# 写作顺序映射 - 定义章节的实际写作顺序（不是阅读顺序）
WRITING_ORDER = {
    # ------------------------ 研究论文 ------------------------ #
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    
    # ------------------------ 协议论文 ------------------------ #
    (StudyType.RCT, PublicationType.PROTOCOL): [
        "Methods", "Introduction", "Ethics and Dissemination", "Abstract", "Title"
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.PROTOCOL): [
        "Methods", "Introduction", "Ethics and Dissemination", "Abstract", "Title"
    ],
    
    # ------------------------ 病例报告 ------------------------ #
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT): [
        "Case Presentation", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES): [
        "Case Series", "Discussion", "Introduction", "Abstract", "Title"
    ],
    
    # ------------------------ 综述论文 ------------------------ #
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW): [
        "Main Topics", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW): [
        "Methods", "Results", "Discussion", "Introduction", "Abstract", "Title"
    ],
    
    # ------------------------ 简报 ------------------------ #
    (StudyType.COHORT, PublicationType.BRIEF_REPORT): [
        "Methods", "Results", "Background", "Conclusions", "Abstract", "Title"
    ],
    (StudyType.CASE_CONTROL, PublicationType.BRIEF_REPORT): [
        "Methods", "Results", "Background", "Conclusions", "Abstract", "Title"
    ],
    
    # ------------------------ 技术报告 ------------------------ #
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT): [
        "Methods", "Evaluation", "Applications", "Discussion", "Introduction", "Abstract", "Title"
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT): [
        "Methods", "Evaluation", "Applications", "Discussion", "Introduction", "Abstract", "Title"
    ],
    
    # ------------------------ 数据说明 ------------------------ #
    (StudyType.COHORT, PublicationType.DATA_NOTE): [
        "Methods", "Applications", "Data Availability", "Introduction", "Abstract", "Title"
    ],
    
    # ------------------------ 其他类型 ------------------------ #
    ("ANY", PublicationType.OPINION): [
        "Perspective / Commentary Body", "Abstract", "Title"
    ],
    ("ANY", PublicationType.LETTER): [
        "Body Text", "Title"
    ]
}

# 写作结构模板
WRITING_STRUCTURE = {
    # ------------------------ Intervention Studies ------------------------ #
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Background", "200-300 words"),
        ("Rationale and Knowledge Gap", "150-250 words"),
        ("Objective and Hypothesis", "100-150 words")
    ],
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design", "150-200 words"),
        ("Participants and Setting", "200-300 words"),
        ("Randomization and Allocation Concealment", "150-200 words"),
        ("Blinding", "100-150 words"),
        ("Intervention Details", "200-300 words"),
        ("Outcome Measures", "150-250 words"),
        ("Sample Size Calculation", "100-150 words"),
        ("Statistical Analysis", "200-300 words")
    ],
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Participant Flow", "150-200 words"),
        ("Baseline Characteristics", "200-300 words"),
        ("Primary Outcome Results", "250-400 words"),
        ("Secondary Outcome Results", "200-350 words"),
        ("Adverse Events", "150-250 words"),
        ("Subgroup and Sensitivity Analyses", "150-250 words")
    ],
    (StudyType.RCT, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Summary of Findings", "200-300 words"),
        ("Comparison with Prior Studies", "250-400 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Clinical and Research Implications", "200-300 words"),
        ("Future Directions", "100-150 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Scientific Background", "200-300 words"),
        ("Rationale for Non-Randomization", "150-250 words"),
        ("Study Objective or Hypothesis", "100-150 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design and Setting", "150-250 words"),
        ("Participant Selection", "200-300 words"),
        ("Intervention or Exposure Description", "200-300 words"),
        ("Outcome Measures", "150-250 words"),
        ("Bias and Confounding Control", "200-300 words"),
        ("Sample Size Justification (if applicable)", "100-150 words"),
        ("Statistical Methods", "200-300 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Participant Flow", "150-200 words"),
        ("Baseline Characteristics", "200-300 words"),
        ("Main Findings (Primary and Secondary Outcomes)", "300-500 words"),
        ("Subgroup or Sensitivity Analyses (if any)", "150-250 words"),
        ("Adverse Events / Safety", "150-250 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Key Findings Summary", "200-300 words"),
        ("Comparison with Existing Literature", "250-400 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Implications for Practice or Research", "200-300 words")
    ],
    (StudyType.RCT, PublicationType.PROTOCOL, "Introduction"): [
        ("Scientific Background", "200-300 words"),
        ("Knowledge Gap", "150-250 words"),
        ("Study Objectives or Hypothesis", "100-150 words")
    ],
    (StudyType.RCT, PublicationType.PROTOCOL, "Methods"): [
        ("Study Design (e.g., Parallel, Crossover)", "150-200 words"),
        ("Eligibility Criteria (Inclusion / Exclusion)", "200-300 words"),
        ("Randomization and Blinding", "150-200 words"),
        ("Intervention Details", "200-300 words"),
        ("Comparator or Control", "150-200 words"),
        ("Outcome Measures (Primary / Secondary)", "200-300 words"),
        ("Sample Size and Power Calculation", "150-200 words"),
        ("Statistical Analysis Plan", "200-300 words")
    ],
    (StudyType.RCT, PublicationType.PROTOCOL, "Ethics and Dissemination"): [
        ("Ethical Approval and Consent", "150-200 words"),
        ("Data Privacy and Confidentiality", "100-150 words"),
        ("Dissemination Plan and Trial Registration", "150-200 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.PROTOCOL, "Introduction"): [
        ("Scientific Background", "200-300 words"),
        ("Rationale for Non-Randomized Design", "150-250 words"),
        ("Study Objectives or Hypothesis", "100-150 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.PROTOCOL, "Methods"): [
        ("Study Design and Setting", "150-250 words"),
        ("Eligibility Criteria (Inclusion / Exclusion)", "200-300 words"),
        ("Intervention Description", "200-300 words"),
        ("Comparator (if applicable)", "150-200 words"),
        ("Outcome Measures", "200-300 words"),
        ("Sample Size Estimation", "150-200 words"),
        ("Statistical Analysis Plan", "200-300 words"),
        ("Bias and Confounding Control", "200-300 words")
    ],
    (StudyType.NON_RANDOMIZED_INTERVENTION, PublicationType.PROTOCOL, "Ethics and Dissemination"): [
        ("Ethical Considerations", "150-200 words"),
        ("Informed Consent", "100-150 words"),
        ("Data Sharing and Publication Plan", "150-200 words")
    ],
    
    # ------------------------ Observational Studies ------------------------ #
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Scientific Background", "200-300 words"),
        ("Rationale for Cohort Design", "150-250 words"),
        ("Study Objectives or Hypothesis", "100-150 words")
    ],
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design and Setting", "150-250 words"),
        ("Participant Selection and Follow-up", "200-300 words"),
        ("Exposure Definition (if applicable)", "150-200 words"),
        ("Outcome Measures", "150-250 words"),
        ("Confounding Control and Bias Mitigation", "200-300 words"),
        ("Sample Size Justification", "100-150 words"),
        ("Statistical Analysis", "200-300 words")
    ],
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Participant Flow and Characteristics", "200-300 words"),
        ("Exposure / Outcome Incidence", "200-300 words"),
        ("Main Findings", "300-500 words"),
        ("Subgroup or Sensitivity Analyses", "200-300 words"),
        ("Missing Data and Limitations", "150-250 words")
    ],
    (StudyType.COHORT, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Key Findings Summary", "200-300 words"),
        ("Comparison with Prior Studies", "250-400 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Implications for Practice and Research", "200-300 words")
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Scientific Background", "200-300 words"),
        ("Justification for Case-Control Design", "150-250 words"),
        ("Study Objectives or Hypothesis", "100-150 words")
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design", "150-200 words"),
        ("Case and Control Definitions", "200-300 words"),
        ("Matching Criteria (if any)", "150-200 words"),
        ("Exposure Assessment", "200-300 words"),
        ("Confounding and Bias Considerations", "200-300 words"),
        ("Statistical Methods", "200-300 words")
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Participant Characteristics", "200-300 words"),
        ("Exposure Frequencies", "200-300 words"),
        ("Primary Associations (Odds Ratios etc.)", "250-400 words"),
        ("Stratified / Sensitivity Analyses", "200-300 words")
    ],
    (StudyType.CASE_CONTROL, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Main Findings", "200-300 words"),
        ("Interpretation and Context", "250-400 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Public Health or Clinical Relevance", "200-300 words")
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Background and Rationale", "200-300 words"),
        ("Study Aims", "100-150 words")
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Design and Setting", "150-200 words"),
        ("Sample Selection", "200-300 words"),
        ("Measurement Tools", "150-250 words"),
        ("Variables and Definitions", "150-250 words"),
        ("Statistical Analysis", "200-300 words")
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Descriptive Statistics", "200-300 words"),
        ("Associations and Correlations", "250-400 words"),
        ("Subgroup Analyses (if any)", "150-250 words")
    ],
    (StudyType.CROSS_SECTIONAL, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Summary of Findings", "200-300 words"),
        ("Interpretation", "250-400 words"),
        ("Limitations", "150-250 words"),
        ("Implications", "150-250 words")
    ],
    (StudyType.COHORT, PublicationType.BRIEF_REPORT, "Background"): [
        ("Study Rationale", "150-200 words"),
        ("Epidemiological Context", "150-200 words"),
        ("Objective or Research Question", "100-150 words")
    ],
    (StudyType.COHORT, PublicationType.BRIEF_REPORT, "Methods"): [
        ("Study Design and Setting", "150-200 words"),
        ("Participants and Follow-up", "150-250 words"),
        ("Exposure or Group Definition", "150-200 words"),
        ("Outcome Measures", "150-200 words"),
        ("Statistical Analysis", "150-200 words")
    ],
    (StudyType.COHORT, PublicationType.BRIEF_REPORT, "Results"): [
        ("Baseline Characteristics", "150-200 words"),
        ("Main Findings", "200-300 words"),
        ("Effect Estimates and Confidence Intervals", "150-200 words")
    ],
    (StudyType.COHORT, PublicationType.BRIEF_REPORT, "Conclusions"): [
        ("Summary of Key Findings", "100-150 words"),
        ("Public Health or Clinical Relevance", "100-150 words")
    ],
    
    # ------------------------ Case Observations ------------------------ #
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT, "Introduction"): [
        ("Background of the Condition", "150-200 words"),
        ("Uniqueness or Rarity of the Case", "100-150 words"),
        ("Purpose of the Report", "100-150 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT, "Case Presentation"): [
        ("Patient Demographics", "100-150 words"),
        ("Medical History", "150-200 words"),
        ("Symptoms and Clinical Findings", "200-300 words"),
        ("Diagnostic Evaluation", "200-300 words"),
        ("Treatment or Intervention", "200-300 words"),
        ("Outcome and Follow-up", "150-200 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT, "Discussion"): [
        ("Interpretation of Findings", "200-300 words"),
        ("Comparison with Similar Cases", "200-300 words"),
        ("Clinical Implications", "150-250 words"),
        ("Lessons Learned or Recommendations", "150-200 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_REPORT, "Conclusion"): [
        ("Summary of Key Takeaways", "100-150 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES, "Introduction"): [
        ("Clinical Background", "150-200 words"),
        ("Gap in the Literature", "150-200 words"),
        ("Objective of the Series", "100-150 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES, "Case Series"): [
        ("Patient Characteristics Overview", "150-200 words"),
        ("Individual Case Descriptions", "300-500 words"),
        ("Common Patterns Observed", "200-300 words"),
        ("Treatment Approaches", "200-300 words"),
        ("Outcomes Summary", "150-200 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES, "Discussion"): [
        ("Synthesis of Observations", "200-300 words"),
        ("Comparison with Prior Literature", "200-300 words"),
        ("Limitations of the Series", "150-200 words"),
        ("Practice or Research Implications", "150-200 words")
    ],
    (StudyType.CASE_OBSERVATION, PublicationType.CASE_SERIES, "Conclusion"): [
        ("Consolidated Summary", "100-150 words"),
        ("Clinical Relevance", "100-150 words")
    ],
    
    # ------------------------ Diagnostic / Prognostic ------------------------ #
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Background and Clinical Need", "200-300 words"),
        ("Existing Diagnostic Approaches", "200-300 words"),
        ("Objective of the Diagnostic Study", "100-150 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design", "150-200 words"),
        ("Population and Setting", "200-300 words"),
        ("Index Test Description", "200-300 words"),
        ("Reference Standard", "150-200 words"),
        ("Statistical Methods (e.g., Sensitivity, Specificity, AUC)", "200-300 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Participant Flow and Characteristics", "200-300 words"),
        ("Test Performance Metrics", "250-400 words"),
        ("Comparative Analysis (if applicable)", "200-300 words"),
        ("Subgroup or Sensitivity Analyses", "150-250 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Principal Findings", "200-300 words"),
        ("Clinical Interpretation", "250-400 words"),
        ("Comparison with Existing Literature", "200-300 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Clinical or Policy Implications", "200-300 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Conclusion"): [
        ("Diagnostic Value Summary", "100-150 words"),
        ("Recommendations or Next Steps", "100-150 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Introduction"): [
        ("Disease Background", "200-300 words"),
        ("Prognostic Importance", "150-200 words"),
        ("Study Objective", "100-150 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Methods"): [
        ("Study Design and Cohort Description", "200-300 words"),
        ("Predictors and Outcome Definition", "200-300 words"),
        ("Data Collection and Follow-up", "150-200 words"),
        ("Statistical Modeling / Risk Score Development", "250-400 words"),
        ("Validation Methods", "200-300 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Results"): [
        ("Cohort Description", "200-300 words"),
        ("Predictor Associations", "250-400 words"),
        ("Prognostic Model Performance", "250-400 words"),
        ("Validation Results", "200-300 words"),
        ("Sensitivity or Subgroup Analyses", "150-250 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Discussion"): [
        ("Summary of Key Findings", "200-300 words"),
        ("Clinical Utility of Prognostic Model", "250-400 words"),
        ("Comparison with Existing Models", "200-300 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Implications for Future Research or Practice", "200-300 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.ORIGINAL_RESEARCH, "Conclusion"): [
        ("Overall Prognostic Value", "100-150 words"),
        ("Recommendations", "100-150 words")
    ],
    
    # ------------------------ Reviews ------------------------ #
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW, "Introduction"): [
        ("Topic Background", "200-300 words"),
        ("Rationale for the Review", "150-250 words"),
        ("Review Objectives", "100-150 words")
    ],
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW, "Methods"): [
        ("Protocol and Registration", "100-150 words"),
        ("Eligibility Criteria", "200-300 words"),
        ("Information Sources", "150-200 words"),
        ("Search Strategy", "200-300 words"),
        ("Study Selection", "150-200 words"),
        ("Data Extraction and Management", "150-200 words"),
        ("Quality Assessment / Risk of Bias", "200-300 words"),
        ("Data Synthesis Methods", "200-300 words")
    ],
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW, "Results"): [
        ("Study Selection and Flow Diagram", "150-200 words"),
        ("Study Characteristics", "200-300 words"),
        ("Risk of Bias Summary", "200-300 words"),
        ("Synthesis of Results", "300-500 words"),
        ("Subgroup or Sensitivity Analyses", "200-300 words")
    ],
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW, "Discussion"): [
        ("Summary of Main Findings", "200-300 words"),
        ("Comparison with Existing Literature", "250-400 words"),
        ("Limitations of Evidence", "200-300 words"),
        ("Implications for Practice and Research", "200-300 words")
    ],
    (StudyType.SYSTEMATIC_REVIEW, PublicationType.REVIEW, "Conclusion"): [
        ("Overall Summary", "100-150 words"),
        ("Recommendations", "100-150 words")
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW, "Introduction"): [
        ("Overview of the Topic", "200-300 words"),
        ("Scope and Objectives of the Review", "150-200 words")
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW, "Main Topics"): [
        ("Thematic Area 1", "300-500 words"),
        ("Thematic Area 2", "300-500 words"),
        ("Thematic Area 3", "300-500 words"),
        ("Recent Advances", "200-300 words"),
        ("Controversies or Debates", "200-300 words")
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW, "Discussion"): [
        ("Synthesis of Key Points", "200-300 words"),
        ("Author Interpretation", "250-400 words"),
        ("Limitations of the Narrative Review", "150-200 words"),
        ("Future Directions", "150-200 words")
    ],
    (StudyType.NARRATIVE_REVIEW, PublicationType.REVIEW, "Conclusion"): [
        ("Summary of Insights", "100-150 words"),
        ("Takeaway Messages", "100-150 words")
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW, "Introduction"): [
        ("Clinical or Scientific Background", "200-300 words"),
        ("Justification for Meta-Analysis", "150-250 words"),
        ("Study Objectives", "100-150 words")
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW, "Methods"): [
        ("Search Strategy and Sources", "200-300 words"),
        ("Inclusion and Exclusion Criteria", "200-300 words"),
        ("Data Extraction Process", "150-200 words"),
        ("Risk of Bias Assessment", "200-300 words"),
        ("Statistical Analysis and Effect Measures", "250-400 words"),
        ("Heterogeneity Assessment", "150-200 words"),
        ("Publication Bias Evaluation", "150-200 words")
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW, "Results"): [
        ("Study Selection and Characteristics", "200-300 words"),
        ("Pooled Effect Estimates", "250-400 words"),
        ("Forest Plot and Heterogeneity", "200-300 words"),
        ("Subgroup Analyses", "200-300 words"),
        ("Sensitivity Analyses", "150-250 words"),
        ("Funnel Plot / Bias Detection", "150-200 words")
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW, "Discussion"): [
        ("Summary of Key Findings", "200-300 words"),
        ("Biological or Clinical Interpretation", "250-400 words"),
        ("Limitations of Included Studies", "200-300 words"),
        ("Strengths and Limitations of Meta-analysis", "200-300 words"),
        ("Implications for Guidelines or Practice", "200-300 words")
    ],
    (StudyType.META_ANALYSIS, PublicationType.REVIEW, "Conclusion"): [
        ("Final Summary Statement", "100-150 words"),
        ("Evidence-Based Recommendation", "100-150 words")
    ],
    
    # ------------------------ Special Types ------------------------ #
    (StudyType.COHORT, PublicationType.DATA_NOTE, "Introduction"): [
        ("Background and Context", "150-200 words"),
        ("Purpose of the Dataset", "150-200 words"),
        ("Relevance to the Research Community", "100-150 words")
    ],
    (StudyType.COHORT, PublicationType.DATA_NOTE, "Methods"): [
        ("Data Collection Process", "200-300 words"),
        ("Inclusion and Exclusion Criteria", "150-200 words"),
        ("Variables and Definitions", "200-300 words"),
        ("Data Cleaning and Quality Control", "150-200 words")
    ],
    (StudyType.COHORT, PublicationType.DATA_NOTE, "Applications"): [
        ("Example Use Cases", "200-300 words"),
        ("Potential Research Questions", "150-200 words"),
        ("Limitations of the Dataset", "150-200 words")
    ],
    (StudyType.COHORT, PublicationType.DATA_NOTE, "Data Availability"): [
        ("Access Procedures", "150-200 words"),
        ("Data Format and Storage", "100-150 words"),
        ("Licensing and Restrictions", "100-150 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT, "Introduction"): [
        ("Clinical or Technical Background", "200-300 words"),
        ("Problem Statement", "150-200 words"),
        ("Innovation or Novelty", "150-200 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT, "Methods"): [
        ("Study Design", "150-200 words"),
        ("Description of Diagnostic Technique or System", "250-400 words"),
        ("Implementation Details", "200-300 words"),
        ("Data Sources and Preprocessing", "200-300 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT, "Evaluation"): [
        ("Performance Metrics", "250-400 words"),
        ("Validation Datasets", "200-300 words"),
        ("Comparison with Existing Methods", "200-300 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT, "Applications"): [
        ("Intended Use Cases", "200-300 words"),
        ("Real-World Deployment", "150-200 words"),
        ("Scalability and Usability", "150-200 words")
    ],
    (StudyType.DIAGNOSTIC, PublicationType.TECHNICAL_REPORT, "Discussion"): [
        ("Interpretation of Results", "200-300 words"),
        ("Technical and Clinical Implications", "200-300 words"),
        ("Limitations and Future Work", "200-300 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT, "Introduction"): [
        ("Background on Prognostic Models", "200-300 words"),
        ("Clinical Relevance of the Prediction Task", "150-200 words"),
        ("Prior Work or Existing Models", "200-300 words"),
        ("Objective of This Report", "100-150 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT, "Methods"): [
        ("Data Sources and Population", "200-300 words"),
        ("Feature Selection and Engineering", "200-300 words"),
        ("Model Development (e.g., Cox, ML, DL)", "250-400 words"),
        ("Handling of Missing Data", "150-200 words"),
        ("Validation Strategy (e.g., cross-validation, temporal split)", "200-300 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT, "Evaluation"): [
        ("Performance Metrics (e.g., C-index, AUC, Calibration)", "250-400 words"),
        ("Internal vs External Validation Results", "200-300 words"),
        ("Subgroup Performance (if applicable)", "150-200 words"),
        ("Comparison with Baseline Models", "200-300 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT, "Applications"): [
        ("Clinical Use Cases or Decision Support", "200-300 words"),
        ("Integration in Workflow or Systems", "150-200 words"),
        ("Limitations of Deployment", "150-200 words")
    ],
    (StudyType.PROGNOSTIC, PublicationType.TECHNICAL_REPORT, "Discussion"): [
        ("Key Findings", "200-300 words"),
        ("Strengths and Limitations", "200-300 words"),
        ("Implications for Clinical Practice", "200-300 words"),
        ("Future Work and Generalizability", "200-300 words")
    ]
}