# | **Secondary** (only if applicable) | |
# | - To evaluate the safety and tolerability of *DRUG* | - AEs/SAEs |
# | - To evaluate the efficacy of *DRUG* | - PFS, CR/CRc rate, EFS, ECOG performance status, ECGs, Vital signs, Clinical laboratory tests (CBC with differential, biochemistry, urinalysis, coags and thyroid panel) |
# | - To evaluate the PK of *DRUG* | - AUC14d, Cmax, Ctrough |
# | - To evaluate immunogenicity of *DRUG* | - Incidence of ADA positivity |
# | - To evaluate the changes in tumor microenvironment following treatment with *DRUG* | - Levels of tumor-infiltrating CD4/CD8 lymphocytes |
# | **Exploratory** (only if applicable) | |
# | - To evaluate changes in pharmacodynamics biomarkers in relation to treatment effect of *DRUG* | - Change in post-treatment biomarker levels compared to baseline |


synopsis_output_template_a_en = """
**1. Basic Information**

-   **Study Title**
    -   Full title of the study (*Informative title including a commonly
        used term indicating the study design and the Intervention/
        Expose*)

-   **Name and affiliation of main author**
    -   This content does not need to be generated. It is fixed as
        "Please fill in according to the requirements."

-   **Planned Study Start Date / End Date**
    -   {study_period_rule}
    
-   **Intervention/ Exposure**
    -   Name of the *Intervention/ Exposure*

**2. Background & Rationale**

-   **Background**
    -   Scientific background and rationale for conducting the study; include disease/condition overview, existing evidence gaps.

-   **Justification**
    -   Explain why the study is needed, potential impact on medical practice, regulatory or HTA value.

-   **Relevant Literature**
    -   Key references supporting the study rationale.

**3. Study Design Overview**

-   **Study Design Type**:
    -   Describe the study design. *This should include:*
        -   *The proposed study design (e.g. cross-sectional, (nested) case-control, cohort or case-crossover studies, other designs)*
        -   *Type of study (e.g. drug utilization study, drug- or disease-registries etc.)*
        -   *Any comparison groups and cohort definitions/description*
        -   *The endpoints and the main measure(s) of effect should be mentioned. The strength of the study design to answer the research question may be explained in this section.*

{setting_section}

**4. Appendices**
-   **Glossary of Terms（Output in tabular form）**:
    -   Three columns: Acronym, Full Name, and Definition.
-   **References**:
    -   Citations for protocols, guidelines, and literature.
"""

study_period_rule_en = """Please fill in according to the requirements of <Study Protocol Synopsis Specification>. If not provided, use the fixed text "Please fill in according to the requirements." """

setting_section_rule_1_en = """The time period during which the study is conducted; the end of the study period is typically the latest date of data availability."""
setting_section_rule_2_en = """Period during which patients, diseases or events of interest are identified, and the index date is determined."""
setting_section_rule_3_en = """Reference point for the analysis (e.g., in a cohort study, the date on or after which the event of interest is identified during the identification period)."""
setting_section_rule_4_en = """The pre-period refers to the (fixed) time period prior to the index date, used to identify baseline variables."""
setting_section_rule_5_en = """Time period including and following the index date; may be fixed or variable per subject."""

setting_section_en = """
-   **Setting**:
    -   Setting is defined in terms of relevant dates, including periods of identification, exposure, and follow-up. Additional information for different study designs may include:*
        -   *Study period: {setting_section_rule_1}*
        -   *Identification period: {setting_section_rule_2}*
        -   *Index date: {setting_section_rule_3}*
        -   *Pre-period: {setting_section_rule_4}*
        -   *Post-period: {setting_section_rule_5}*"""

synopsis_output_template_b_en = """**1. Study Population**

-   **Inclusion Criteria**:

-   **Exclusion Criteria**:

{special_considerations_section}

**2. Appendices**
-   **Glossary of Terms（Output in tabular form）**:
    -   Three columns: Acronym, Full Name, and Definition.
-   **References**:
    -   Citations for protocols, guidelines, and literature.
    
"""



consideration_rule_1_en = """Source of participants, recruitment methods, follow-up approach"""
consideration_rule_2_en = """provide number of controls per case; provide inclusion and exclusion criteria, sources and methods of selection of participants separately for cases and controls"""
consideration_rule_3_en = """Sampling strategy and participant selection methods"""

special_considerations_section_en = """-   **Special Considerations**: (If applicable)
    -   {consideration_rule}"""

synopsis_output_template_c_en = """**1. Variables**

### Exposure Variables

| **Exposure variables** | **Definition and measurement(s)** |
|------------------------|-----------------------------------|
| *For example*<br>Siponimod treatment | *For example*<br><br>Initial dose, dose reduction or escalations, prescribed frequency, start date, date of discontinuation and reason(s) for treatment discontinuation (if applicable) |
| *For example*<br><br>MS treatment following discontinuation of siponimod | *For example*<br><br>Type of treatment, start date and stop date, reason for stopping treatment (if applicable) |
| *For example*<br><br>Concomitant medications including treatment for MS relapse | *For example*<br><br>Type of treatment, prescribed dose, dosing frequency, indication, start and stop dates reason(s) for discontinuation (if applicable) |

### Outcome(s) Variables

| **Outcome variables** | **Definition and measurement(s)** |
|----------------------|---------------------------------------|
| *For example*<br>**MS clinical relapse information following index date** | *For example*<br>**Number of relapses, onset date of relapse, hospitalization, treatments for relapse (e.g., steroid, other acute treatment)**<br><br>**Note: Relapse status will be determined as documented in the patient's medical records.** |
| *For example*<br>**Brain MRI outcome following index date** | *For example*<br>**Dates and brain MRI results**<br><br>**Note: MRI activity status will be determined as documented in the patient's medical records.** |
| *For example*<br>**Laboratory assessment** | *For example*<br>**Selected notable abnormal laboratory data including complete blood count (CBC) with differential (lymphocyte count in particular) and liver function tests (LFTs); date of specimen collection, results, units, if the laboratory results supported an AE (Yes/No; if Yes, the laboratory abnormalities must be recorded as AEs)** |
| *For example*<br>**AEs, SAEs, and AESIs*** | *For example*<br>**Event term, start and end dates, severity, relationship to intervention, action taken, outcome, seriousness, event leading to discontinuation, and fatal events, as reported in medical records.** |

### Demographic and Baseline Characteristics

*List of required demographic and baseline characteristics to be collected at baseline or index date (e.g., age, sex, height, weight, relevant medical history; output in tabular format if applicable).*

{covariate_section}

{effect_modifier_section}

**2. Data sources**

### Source Type(s)

*electronic medical (health) records, administrative claims data, hospital discharge files, abstracts of primary clinical records, ad hoc clinical databases, prescription drug files, etc. (Specify for each variable the data source, coding/terminology used, and assessment method)*

{database_section}

**3. Statistical Methods**

### Data management

*Provide information on data management (if applicable) and statistical software(s) to be used in the study, including procedures for data collection, retrieval, collection and preparation.*

### Data analysis

-   Methods for descriptive analysis
-   Approaches for confounding control (e.g., regression, stratification, propensity scores)
{subgroup_section}
{interaction_section}
{data_missing_section}
{sensitivity_section}
{loss_to_followup_section}
{matching_section}
{sampling_section}
{multiplicity_section}

**4. Appendices**
-   **Glossary of Terms（Output in tabular form）**:
    -   Three columns: Acronym, Full Name, and Definition.
-   **References**:
    -   Citations for protocols, guidelines, and literature.
    
"""

subgroup_section_en = """-   Planned subgroup analyses"""
interaction_section_en = """-   Planned interaction analyses"""
data_missing_section_en = """-   Handling of missing data"""
sensitivity_section_en = """-   Sensitivity analyses"""
loss_to_followup_section_en = """-   Handling of loss to follow-up (if applicable)"""
matching_section_en = """-   Handling of matching (if applicable)"""
sampling_section_en = """-   Sampling strategy (if applicable)"""

multiplicity_section_en = """-   Multiplicity Adjustment (if applicable)"""

extra_covariate_rule_en = """*If the user provides Confounders, please ensure that the Covariates include the content of the Confounders, and list the content of the Confounders separately.*"""
covariate_section_en = """### Covariates/Confounders

*List relevant covariates and how they will be measured*

{extra_covariate_rule}
"""
database_section_en = """**Database Description (if applicable)**

-   Display database info below if provided; otherwise, leave blank.
    -   *Name and owner of database*
    -   *Coverage period*
    -   *Data validity/quality considerations*
    -   *Known limitations and mitigation strategies*

-   *If the data source for the same variable differs across multiple groups, specify the source of the data for each group separately.*
"""


effect_modifier_section_en = """### Effect Modifiers (if applicable)

*Definition and measurement*

"""

synopsis_output_template_d_en = """**1. Limitations of the research methods**

*Any potential limitations of the study design, data sources, and
analytic methods, including issues relating to confounding, bias (e.g.
selection bias), exposure misclassification, outcome misclassification,
generalizability, and random error. Discuss both direction and magnitude
of potential bias, as well as likely success of efforts taken to reduce
errors.*

**2. Appendices**
-   **Glossary of Terms (tabular form)**:
    -   Three columns: Acronym, Full Name, and Definition.
-   **References**:
    -   Citations for protocols, guidelines, and literature.
    
"""

synopsis_output_template_order_en = '''Order:
1. Basic Information
2. Background & Rationale
3. Study Design Overview
4. Study Population
5. Variables
6. Data sources
7. Statistical Methods
8. Limitations of the research methods
9. Appendices
'''

expansion_prompt = """Please expand a single indication into a list of related terms to increase search coverage.
<Indication> is the indication to be expanded.
<Indication>
{indication}
</Indication>
Add related terms based on common mappings, synonyms, and other relevant terms.
Examples:
"Type 2 diabetes with hypertension and high cholesterol": ["Type 2 diabetes", "Diabetes", "Hypertension", "High cholesterol", "Metabolic syndrome"]
"Breast cancer, HER2 positive with lymph node metastasis": ["HER2 positive breast cancer", "Breast cancer with lymph node metastasis", "Invasive breast cancer", "Breast cancer"]
"Acute myeloid leukemia, M2 type": ["AML-M2", "Acute myeloblastic leukemia with maturation", "AML"]
"diabetes": ["T1DM", "T2DM", "diabetes mellitus", "type 1 diabetes", "type 2 diabetes", "gestational diabetes"]
"hypertension": ["high blood pressure", "HTN", "elevated blood pressure"]
"cancer": ["malignancy", "tumor", "neoplasm", "carcinoma"]
"COPD": ["chronic obstructive pulmonary disease", "chronic bronchitis", "emphysema"]
"asthma": ["reactive airway disease", "bronchial asthma"]
"arthritis": ["rheumatoid arthritis", "RA", "osteoarthritis", "OA", "joint inflammation"]
"depression": ["major depressive disorder", "MDD", "depressive disorder"]
"anxiety": ["anxiety disorder", "GAD", "generalized anxiety disorder"]
"HIV": ["human immunodeficiency virus", "AIDS", "HIV/AIDS"]
"hepatitis": ["HBV", "HCV", "viral hepatitis", "hepatitis B", "hepatitis C"]
"Type 2 diabetes with hypertension and high cholesterol": ["Type 2 diabetes", "Diabetes", "Hypertension", "High cholesterol", "Metabolic syndrome"]
"Breast cancer, HER2 positive with lymph node metastasis": ["HER2 positive breast cancer", "Breast cancer with lymph node metastasis", "Invasive breast cancer", "Breast cancer"]
"Acute myeloid leukemia, M2 type": ["AML-M2", "Acute myeloblastic leukemia with maturation", "AML"]
"""

age_group_matching_prompt = """Please match the user provided age term to the best fitting age group.
The age group should be one of 'CHILD', 'ADULT', 'OLDER_ADULT'.
<Age term> is the user provided age term.
<Age term>
{age_term}
</Age term>
"""