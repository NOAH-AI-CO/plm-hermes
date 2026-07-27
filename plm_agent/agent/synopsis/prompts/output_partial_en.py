synopsis_output_template_a_en = '''
**1. Document Header**
-   **Sponsor Information**
    -   This content does not need to be generated. It is fixed as
        "Please fill in according to the requirements."

-   **Study Drug/Intervention**
    -   Name of the investigational product
    -   Phase of development

-   **Study Title**
    -   Full title of the study 
    -   suggested text for study title: [A(n) [Platform Study Design]
        [primary purpose], [study phase], [blinding], [number or
        multi-arm] study to investigate [health measurement/outcome]
        with [study interventions] compared with [control/study
        intervention/placebo] [intervention form] in [male and/or
        female] participants [aged X to X years of age] with
        [condition/disease]

-   **Planned Study Period**
    -   The duration of the study from enrollment to completion 

**2. Study Objectives, Endpoints and Estimands:**

**If the user specifies limitations on sample size or study duration:**

-   Identify several studies with sample sizes or study durations close
    to the user-specified ones.
-   Designate the primary endpoint that occurs most frequently among
    these studies as the primary endpoint for this study.

**If the user does not specify limitations on sample size or study
duration:**

-   Set the primary endpoint that appears most frequently in <Noah Data>
    as the endpoint for this study.

+-------------------------------+--------------------------------------+
| **Objectives**                | **Endpoints**                        |
+===============================+======================================+
| **Primary**                   |                                      |
+-------------------------------+--------------------------------------+
| -   To evaluate the safety    | -   AEs/SAEs                         |
|     and tolerability of       |                                      |
|     *DRUG*                    | -   OS, EFS                          |
|                               |                                      |
| -   To evaluate the efficacy  | -   MTD, RP2D                        |
|     of *DRUG*                 |                                      |
|                               |                                      |
| -   To determine the MTD      |                                      |
|     and/or RP2D of *DRUG*     |                                      |
+-------------------------------+--------------------------------------+
| **Secondary**                 |                                      |
+-------------------------------+--------------------------------------+
| -   To evaluate the safety    | -   AEs/SAEs                         |
|     and tolerability of       |                                      |
|     *DRUG*                    | -   PFS, CR/CRc rate, EFS, ECOG      |
|                               |     performance status, ECGs,Vital   |
| -   To evaluate the efficacy  |     signs, Clinical laboratory tests |
|     of *DRUG*                 |     (CBC with differential,          |
|                               |     biochemistry, urinalysis, coags  |
| -   To evaluate the PK of     |     and thyroid panel)               |
|     *DRUG*                    |                                      |
|                               | -   AUC14d, Cmax, Ctrough            |
| -   To evaluate               |                                      |
|     immunogenicity of *DRUG*  | -   Incidence of ADA positivity      |
|                               |                                      |
| -   To evaluate the changes   | -   Levels of tumor-infiltrating     |
|     in tumor microenvironment |     CD4/CD8 lymphocytes              |
|     following treatment with  |                                      |
|     *DRUG*                    |                                      |
+-------------------------------+--------------------------------------+
| **Exploratory**               |                                      |
+-------------------------------+--------------------------------------+
| -   To evaluate changes in    | -   Change in post-treatment         |
|     pharmacodynamics          |     biomarker levels compared to     |
|     biomarkers in relation to |     baseline                         |
|     treatment effect of       |                                      |
|     *DRUG*                    |                                      |
+-------------------------------+--------------------------------------+


**3. Study Design Overview**
-   **Study Design Type**:
    -   Describe the study design 

-   **Randomization Ratio**:
    -   Specify the ratio of participants to intervention arms (e.g.,
        1:1).

-   **Number of Study Centers**:
    -   Total sites and locations 
    -   Ideally, we should first calculate the average or median of
        **sample size / (duration × site count)** from reference
        studies, then use the sample size and duration of this study to
        determine the site count.

-   **Pharmacokinetic (PK) Cohort** **(if applicable)**:
    -   If there is no PK endpoint designed in <Noah Data>, this section does not need to be completed.
        
        
**4. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms
-   **References**:
    -   Citations for protocols, guidelines, and literature.

'''

synopsis_output_template_b_en = '''
**1. Study Population**
Please refer to the eligibilityCriteria section in the given JSON and write a set of inclusion and exclusion criteria 
for a clinical study with the following properties: {query_params}, with the inclusion criteria and exclusion criteria separated.
            
**2. Study Interventions**
-   **Concomitant Medication Restrictions**:
    -   Prohibited or allowed medications during the study: The
        prohibition and permission of concomitant medications include
        the allowed or prohibited concomitant medications for the study
        group, control group, and both groups. The requirements for
        concomitant medications in the study group alone or the control
        group alone should be based on background information or
        knowledge. If there is no relevant background information or
        knowledge available, please retain the subheading but display
        the content as "Please fill in according to your requirements."
        The allowed and prohibited concomitant medications for the study
        group and control group are often related to the indication.
        Generally, medications that may affect efficacy are prohibited
        during the study period. However, for safety considerations,
        some special medications, although they may affect efficacy, may
        be exempted. This part can refer to other clinical studies that
        have been searched. 
            
**3. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms
-   **References**:
    -   Citations for protocols, guidelines, and literature.
'''

# Outcome, design, status, results

synopsis_output_template_c_en = '''
**1. Study Interventions**
-   **Investigational Product**:
    -   Dose, administration route, and schedule

-   **Comparative Drugs (if applicable)**:
    -   Standard chemotherapy regimens and dosing based on background
        information or knowledge.
            
**2. Statistical Methods**
1. Key Parameters and Rationale
•Data Source: 
Parameter	Value 	Supporting Evidence
experimental group expected mean	___ ± ___	- NCT****** (** arm ** =___ ± ___)<br>NCT****** (** arm ** =___ ± ___)<br>...
Control arm expected mean	___ ± ___	- NCT****** (** arm ** rate=____%)<br>...
 Or
Parameter	Value 	Supporting Evidence
experimental group rate	___ %	- NCT****** (** arm ** rate=____%)<br>...
Control arm rate	___ %	- NCT****** (** arm ** rate=____%)<br>- NCT****** (** arm ** rate=____%)<br>...
 Or
 HR = ___，- NCT****** (**A vs B** HR=___)<br>...

•Effect Size: Expected difference (e.g., mean difference = ___ or rate difference = ___%), justification (clinical relevance/prior studies, cite literature)
•Statistical Significance (α): Two-sided α = 0.05 (or one-sided α = 0.025 for non-inferiority trials)
•Statistical Power: 1-β = ___% (typically ≥80%)
•Allocation Ratio: Control:Experimental = :
•Attrition Rate Adjustment: Estimated dropout rate = ___%, rationale (cite prior studies or conservative estimate)
2. Interim Analysis(only if the {query_params} section explicitly mentions the need for interim analysis, please fill in the content; otherwise, not applicable and remove this part.)
3. Formula and Calculation Process(in detail)
4. Software Validation. Software Validation": ""


**3. Study Assessments and Procedures**
-   **Efficacy Assessments**
    -   Planned timepoints for all [efficacy and/or immunogenicity]
        assessments all interventions in the platform study are provided
        in the SoA.

-   **Safety Assessments**:
    -   Adverse events, lab tests, vital signs, ECGs, and performance
        scores

-   **Pharmacokinetic Analysis(if applicable)**:
    -   If there is no PK endpoint designed in <Noah Data>, this section does not need to be completed.

**4. Exploratory Analyses(if applicable)**
-   **Biomarkers**:
    -   Evaluation of mutation status and other biomarkers

-   **Resource Utilization**:
    -   Analysis of hospitalization, transfusions, and medication use

-   **Patient-Reported Outcomes (PROs)** (if applicable):
    -   Tools used and analysis methods 

**5. Post-Treatment Follow-Up**
-   **Long-Term Follow-Up**:
    -   Schedule and duration

-   **Endpoints Collected**:
    -   Survival, subsequent AML treatments, remission status, and cause
        of death.

**6. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms
-   **References**:
    -   Citations for protocols, guidelines, and literature.
'''

synopsis_output_template_d_en = '''
**1. Discontinuation Criteria**
-   **Discontinuation Criteria**:
    -   Discontinuation of Study Intervention

    -   Participant Discontinuation/Withdrawal from the Study
        
    -   Lost to Follow up 

**2. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms
-   **References**:
    -   Citations for protocols, guidelines, and literature.
'''