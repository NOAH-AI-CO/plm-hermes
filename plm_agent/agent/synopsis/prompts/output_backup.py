synopsis_output_template_b_backup = '''
**1. Study Population**
-   **Inclusion Criteria**:
    -   Eligibility requirements (e.g.,
        -   "Subject is eligible for the study if all of the following
            apply: Institutional Review Board (IRB)-/Independent Ethics
            Committee (IEC)-approved written Informed Consent and
            privacy language as per national regulations must be
            obtained prior to any study-related procedures."
        -   "Subject is considered an adult according to local
            regulation (e.g., age ≥ 18 years old in China) at the time
            of signing informed consent."
        -   "Subject has a diagnosis of primary AML or AML secondary to
            myelodysplastic syndrome (MDS) according to World Health
            Organization classification.").

-   **Exclusion Criteria**:
    -   Conditions disqualifying participation (e.g.,
        -   "Subject will be excluded from participation if any of the
            following apply: Subject was diagnosed as acute
            promyelocytic leukemia."
        -   "Subject has BCR-ABL-positive leukemia (chronic myelogenous
            leukemia in blast crisis)."
        -   "Subject has a history of congestive heart failure New York
            Heart Association (NYHA) class 4 in the past.").
            
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
        have been searched. (e.g.,
        -   "Treatment with concomitant drugs that are strong inducers
            of CYP3A are prohibited."
        -   "Treatment with concomitant drugs that are strong inhibitors
            or inducers of P-gp and those targeting serotonin 5HT1R or
            5HT2BR are to be avoided with exceptions for essential
            care.").
            
**3. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms (e.g., CR, CRc, ECOG).
-   **References**:
    -   Citations for protocols, guidelines, and literature.
'''

synopsis_output_template_c_backup = '''
**1. Study Population**
-   **Number of Subjects to be Enrolled/Randomized**:
    -   Total sample size and allocation to arms (e.g., "318 subjects
        will be randomized").

**2. Study Interventions**
-   **Investigational Product**:
    -   Dose, administration route, and schedule (e.g., "ASP2215 tablets
        containing 40 mg of active ingredient administered orally once
        daily at 120 mg").

-   **Comparative Drugs (if applicable)**:
    -   Standard chemotherapy regimens and dosing based on background
        information or knowledge. (e.g.,
        -   "Low-dose cytarabine (LoDAC): 20 mg cytarabine administered
            twice daily by SC or IV for 10 days."
        -   "Mitoxantrone, etoposide, and intermediate-dose cytarabine
            (MEC): Mitoxantrone 6 mg/m²/day IV for 5 days, etoposide 100
            mg/m²/day IV for 5 days, cytarabine 1000 mg/m²/day IV for 5
            days.").
            
**3. Statistical Methods**
-   **1. Key Parameters and Rationale**

  **If the Primary Endpoint is not a Hazard Ratio (HR):**

-   **Identify reference studies from Noah Data that include the
    specified primary endpoint and use the same control group drug,
    regardless of whether the endpoint is labeled as primary, secondary,
    or exploratory.**

-   **Perform a meta-analysis on the eligible studies to calculate the
    pooled effect size and its 95% confidence interval as the expected
    value for the control group.**

-   **If the Synopsis Specification provides an estimated primary
    endpoint value for the study group, use it directly.**

-   **If not provided, select the highest study group endpoint value
    among the reference studies as the expected value.**

  **If the Primary Endpoint is HR:**

-   **Identify reference studies from Noah Data that report the
    specified HR endpoint and include the same control group drug,
    regardless of the endpoint type (primary, secondary, or
    exploratory).**

-   **Perform a meta-analysis on the eligible studies to calculate the
    pooled HR between the control and comparable study groups.**

-   **Use the median of the pooled HR values as the expected HR.**

-   **Data Source:**
+-----------------------+----------------------+-----------------------+
| **Parameter**         | **Value**            | **Supporting          |
|                       |                      | Evidence**            |
+=======================+======================+=======================+
| **experimental group  | **___ ± ___**        | **- NCTXXXXXX (**     |
| expected mean**       |                      | arm ** =___ ±         |
|                       |                      | ___)**                |
|                       |                      |                       |
|                       |                      | **- NCTXXXXXX (**     |
|                       |                      | arm ** =___ ±         |
|                       |                      | ___), etc**           |
+-----------------------+----------------------+-----------------------+
| **Control arm**       | **___ ± ___**        | **- NCTXXXXXX (**     |
| **expected mean**     |                      | arm **                |
|                       |                      | rate=____%)**         |
|                       |                      |                       |
|                       |                      | **- NCTXXXXXX (**     |
|                       |                      | arm **                |
|                       |                      | rate=____%),          |
|                       |                      | etc**                 |
+-----------------------+----------------------+-----------------------+

-   **Or**

+-----------------------+----------------------+-----------------------+
| **Parameter**         | **Value**            | **Supporting          |
|                       |                      | Evidence**            |
+=======================+======================+=======================+
| **experimental group  | **___** **%**     | **- NCTXXXXXX**          |
| rate**                |                      | **(**** **arm**       |
|                       |                      | ****                  |
|                       |                      | rate=____%)**         |
|                       |                      |                       |
|                       |                      | **- NCTXXXXXX (**     |
|                       |                      | arm **                |
|                       |                      | rate=____%),          |
|                       |                      | etc**                 |
+-----------------------+----------------------+-----------------------+
| **Control arm rate**  | **___** **%**     | **- NCTXXXXXX (**        |
|                       |                      | arm **                |
|                       |                      | rate=____%)**         |
|                       |                      |                       |
|                       |                      | **- NCTXXXXXX (**     |
|                       |                      | arm **                |
|                       |                      | rate=____%),          |
|                       |                      | etc**                 |
+-----------------------+----------------------+-----------------------+

-   **Or**

-   **HR = ___，-NCTXXXXXX HR=____**

-   **Based on pilot data/literature \[cite reference\], control group
    mean = ___ ± ___, experimental group expected mean = ___ ±
    ___ (or control group rate = ___%, experimental group =
    ___%; hazard ratio HR = ___)**

-   **​Effect Size: Expected difference (e.g., mean difference = ___
    or rate difference = ___%), justification (clinical
    relevance/prior studies, cite literature)**

-   **​Statistical Significance (α): Two-sided α = 0.05 (or one-sided α =
    0.025 for non-inferiority trials)**

-   **​Statistical Power: 1-β = ___% (typically ≥80%)**

-   **​Allocation Ratio: Control:Experimental = *:***

-   **​Attrition Rate Adjustment: Estimated dropout rate = ___%,
    rationale (cite prior studies or conservative estimate)**

-   **2. Formula and Calculation Process**

-   **The sample size estimation depends on the type of primary endpoint
    selected for the study. Two common scenarios are considered:**

-   **1. Continuous Endpoint (e.g., difference in means between two
    groups):**

-   **When the primary endpoint is a continuous variable, the required
    sample size per group is calculated using the formula for a
    two-sample t-test:**

    **n = \[2 × σ² × (Zα/2 + Zβ)²\] / d²**

-   **Where:**

-   **σ is the assumed standard deviation of the endpoint,**

-   **d is the expected difference in means between the study and
    control groups (effect size),**

-   **Zα/2 is the standard normal value corresponding to the desired
    significance level (e.g., 1.96 for a two-sided α = 0.05),**

-   **Zβ is the standard normal value corresponding to the desired power
    (e.g., 0.84 for 80% power).**

-   **Example:\
    Assuming a standard deviation (σ) of 8, a mean difference (d) of 5,
    α = 0.05 (Zα/2 = 1.96), and power = 80% (Zβ = 0.84),**

    **n = \[2 × 64 × (1.96 + 0.84)²\] / 25**

    **= \[2 × 64 × 7.84\] / 25**

    **= 1003.52 / 25**

    **≈ 40.14 subjects per group**

-   **To account for a 10% dropout rate:**

    **Event count = \[(Zα/2 + Zβ)²\] / \[(ln(HR))² × π × (1 - π)\]**

-   **Where:**

-   **ln(HR) is the natural logarithm of the expected hazard ratio
    between the two groups,**

-   **π is the allocation ratio for one of the groups (e.g., 0.5 for
    equal allocation),**

-   **Zα/2 and Zβ are defined as above.**

-   **The total sample size can then be estimated by dividing the
    required number of events by the assumed event rate during the study
    period, taking into account follow-up time and censoring. An
    adjustment for anticipated dropout should also be applied.**

-   **3. Software Validation**

-   **Verified using \[software name, e.g., PASS v2023 or
    R pwr package\], with output summary/code snippet (optional).**

-   **4. Sensitivity Analysis (Optional)**

-   **Assess sample size range under varying effect sizes (e.g., d =
    4--6): ___ to ___**

-   **5. Ethical Justification**

-   **Minimize sample size while ensuring power, per ICH E9
    guidelines.**
    

-   **Example Template (English):**

-   **​Sample Size Calculation\
    This randomized double-blind controlled trial uses blood pressure
    reduction (continuous variable) as the primary endpoint.**

+-----------------------+----------------------+-----------------------+
| **Parameter**         | **Value**            | **Supporting          |
|                       |                      | Evidence**            |
+=======================+======================+=======================+
| **experimental        | **15 ± 8 mmHg**      | **-** **NCT03151408** |
| group** **blood       |                      | **(ABC arm 20** **± 8 |
| pressure reduction**  |                      | mmHg,)**              |
|                       |                      |                       |
|                       |                      | **-** **NCT03701308** |
|                       |                      | **(CDE** **10 ± 8     |
|                       |                      | mmHg), etc**          |
+-----------------------+----------------------+-----------------------+
| **Control arm**       | **10 ± 8 mmHg**      | **-** **NCT03151408** |
| **blood pressure      |                      | **(BC** **arm** **7 ± |
| reduction**           |                      | 7 mmHg)**             |
|                       |                      |                       |
|                       |                      | **-** **NCT03151408** |
|                       |                      | **(CD** **arm** **13  |
|                       |                      | ± 9 mmHg), etc**      |
+-----------------------+----------------------+-----------------------+

-   **(mean difference *d*=5, Cohen's *d*=0.625).**

-   **Parameters: two-sided α = 0.05, power = 80% (β = 0.2), allocation
    ratio 1:1.\
    Using the two-sample t-test formula:**

-   ***n*per group​=52(1.96+0.84)2×2×82​=64**

-   **With a 10% attrition rate, the adjusted sample size is 72 per
    group (total *N*=144). Results were validated using PASS software.
    Sensitivity analysis indicates that if *d*=4--6, the required sample
    size ranges from 90 to 200, confirming the conservatism of the
    current design.**

-   **Interim Analysis(if applicable)**:
    -   Plan for interim evaluation and criteria for early termination
        (e.g.,
        -   "A formal interim analysis is planned when approximately 50%
            of the planned death events have occurred. The IDMC may
            recommend terminating the trial for favorable or unfavorable
            results.").

**4. Study Assessments and Procedures**
-   **Efficacy Assessments**
    -   Planned timepoints for all \[efficacy and/or immunogenicity\]
        assessments all interventions in the platform study are provided
        in the SoA.

-   **Safety Assessments**:
    -   Adverse events, lab tests, vital signs, ECGs, and performance
        scores (e.g.,
        -   "The Safety Analysis Set (SAS) is defined as all subjects
            who received at least one dose of study treatment."
        -   "Safety data will be summarized using descriptive statistics
            and MedDRA coding.").

-   **Pharmacokinetic Analysis(if applicable)**:
    -   Methods for PK modeling and covariate analysis (e.g.,
        -   "Population pharmacokinetic modeling will be conducted using
            nonlinear mixed effects methodology."
        -   "Plasma concentrations and PK parameters will be summarized
            using descriptive statistics.").

**5. Exploratory Analyses(if applicable)**
-   **Biomarkers**:
    -   Evaluation of mutation status and other biomarkers (e.g.,
        -   "An exploratory analysis of FLT3 mutation status and
            clinical efficacy will be conducted."
        -   "Pharmacogenomics (PGx) and FLT3 gene mutation status will
            be analyzed in subgroups.").

-   **Resource Utilization**:
    -   Analysis of hospitalization, transfusions, and medication use
        (e.g.,
        -   "An exploratory analysis will use CMH method for resource
            utilization status and ANOVA for resource utilization
            counts.").

-   **Patient-Reported Outcomes (PROs)**:
    -   Tools used and analysis methods (e.g.,
        -   "Functional Assessment of Cancer Therapy-Leukemia
            (FACT-Leu), Brief Fatigue Inventory (BFI), EuroQol Group-5
            Dimension-5 Level Instrument (EQ-5D-5L) will be used.").

**6. Post-Treatment Follow-Up**
-   **Long-Term Follow-Up**:
    -   Schedule and duration (e.g., "every 3 months for up to 3 years
        from the subject's end of treatment visit").

-   **Endpoints Collected**:
    -   Survival, subsequent AML treatments, remission status, and cause
        of death.

**7. Appendices**
-   **Glossary of Terms** (Output in tabular form):
    -   Definitions of acronyms and key terms (e.g., CR, CRc, ECOG).
-   **References**:
    -   Citations for protocols, guidelines, and literature.
'''

synopsis_output_template_text = """
1. Document Header
· Sponsor Information
o This content does not need to be generated. It is fixed as “Please fill in according to the requirements.”
· Study Drug/Intervention
o Name of the investigational product (e.g., ASP2215).
o Phase of development (e.g., Phase 3).
· Study Title
o Full title of the study (e.g., “Phase 3 Open-Label, Multicenter, Randomized Study of ASP2215 versus Salvage Chemotherapy in Patients with Relapsed or Refractory Acute Myeloid Leukemia (AML) with FLT3 Mutation”).
o suggested text for study title: [A(n) [Platform Study Design] [primary purpose], [study phase], [blinding], [number or multi-arm] study to investigate [health measurement/outcome] with [study interventions] compared with [control/study intervention/placebo] [intervention form] in [male and/or female] participants [aged X to X years of age] with [condition/disease]
· Planned Study Period
o Anticipated start and end dates of the study (e.g., June 2017 to October 2022).

2. Study Objectives, Endpoints and Estimands:

Primary Objectives:
·To evaluate the safety and tolerability of *DRUG*
·To evaluate the efficacy of *DRUG*
·To determine the MTD and/or RP2D of *DRUG*

Primary Endpoints:
·AEs/SAEs
·OS, EFS
·MTD, RP2D

Secondary Objectives:
·To evaluate the safety and tolerability of *DRUG*
·To evaluate the efficacy of *DRUG*
·To evaluate the PK of *DRUG*
·To evaluate immunogenicity of *DRUG*
·To evaluate the changes in tumor microenvironment following treatment with *DRUG*

Secondary Endpoints:
·AEs/SAEs
·PFS, CR/CRc rate, EFS, ECOG performance status, ECGs, Vital signs
·Clinical laboratory tests (CBC with differential, biochemistry, urinalysis, coags and thyroid panel)
·AUC14d, Cmax, Ctrough
·Incidence of ADA positivity
· Levels of tumor-infiltrating CD4/CD8 lymphocytes

Exploratory Objectives:
· To evaluate changes in pharmacodynamics biomarkers in relation to treatment effect of *DRUG*

Exploratory Endpoints:
· Change in post-treatment biomarker levels compared to baselinee

3. Study Design Overview
· Study Design Type:
o Describe the study design (e.g., “This is a phase 3, open-label, multicenter, randomized study to compare the efficacy and safety of ASP2215 therapy to salvage chemotherapy in FLT3-mutated AML subjects who are refractory to or have relapsed after first-line AML therapy”).
· Randomization Ratio:
o Specify the ratio of participants to intervention arms (e.g., 1:1).
· Number of Study Centers:
o Total sites and locations (e.g., approximately 50 centers; China, Russia, Singapore, Thailand, and Malaysia).
· Pharmacokinetic (PK) Cohort (if applicable):
o Details on PK sample collection and participant allocation (e.g., “Two (or more) study sites in China will be designated as a ‘pharmacokinetic cohort site’ (PK cohort site) which will collect PK samples after single and multiple doses in Chinese subjects. The first 20 subjects (10 male and 10 female) randomized into the ASP2215 arm at PK cohort sites will participate in the PK cohort”).

4. Study Population
· Inclusion Criteria:
o Eligibility requirements (e.g.,
§ “Subject is eligible for the study if all of the following apply: Institutional Review Board (IRB)-/Independent Ethics Committee (IEC)-approved written Informed Consent and privacy language as per national regulations must be obtained prior to any study-related procedures.”
§ “Subject is considered an adult according to local regulation (e.g., age ≥ 18 years old in China) at the time of signing informed consent.”
§ “Subject has a diagnosis of primary AML or AML secondary to myelodysplastic syndrome (MDS) according to World Health Organization classification.”).
· Exclusion Criteria:
o Conditions disqualifying participation (e.g.,
§ “Subject will be excluded from participation if any of the following apply: Subject was diagnosed as acute promyelocytic leukemia.”
§ “Subject has BCR-ABL-positive leukemia (chronic myelogenous leukemia in blast crisis).”
§ “Subject has a history of congestive heart failure New York Heart Association (NYHA) class 4 in the past.”).
· Number of Subjects to be Enrolled/Randomized:
o Total sample size and allocation to arms 

5. Study Interventions
· Investigational Product:
o Dose, administration route, and schedule (e.g., “ASP2215 tablets containing 40 mg of active ingredient administered orally once daily at 120 mg”).
· Comparative Drugs (if applicable):
o Standard chemotherapy regimens and dosing based on background information or knowledge. (e.g.,
§ “Low-dose cytarabine (LoDAC): 20 mg cytarabine administered twice daily by SC or IV for 10 days.”
§ “Mitoxantrone, etoposide, and intermediate-dose cytarabine (MEC): Mitoxantrone 6 mg/m²/day IV for 5 days, etoposide 100 mg/m²/day IV for 5 days, cytarabine 1000 mg/m²/day IV for 5 days.”).
· Concomitant Medication Restrictions:
o Prohibited or allowed medications during the study: The prohibition and permission of concomitant medications include the allowed or prohibited concomitant medications for the study group, control group, and both groups. The requirements for concomitant medications in the study group alone or the control group alone should be based on background information or knowledge. If there is no relevant background information or knowledge available, please retain the subheading but display the content as “Please fill in according to your requirements.” The allowed and prohibited concomitant medications for the study group and control group are often related to the indication. Generally, medications that may affect efficacy are prohibited during the study period. However, for safety considerations, some special medications, although they may affect efficacy, may be exempted. This part can refer to other clinical studies that have been searched. (e.g.,
§ “Treatment with concomitant drugs that are strong inducers of CYP3A are prohibited.”
§ “Treatment with concomitant drugs that are strong inhibitors or inducers of P-gp and those targeting serotonin 5HT1R or 5HT2BR are to be avoided with exceptions for essential care.”).

6. Study Assessments and Discontinuation Criteria
· Schedule of Assessments:
o Timeline for efficacy, safety, PK, and PRO assessments (e.g.,
§ “Cycle 1: Day 1, 4 ± 1, 8 ± 1, 15 ± 1; Cycle 2: Day 1 ± 2, 15 ± 1; Subsequent cycles: Day 1 ± 2.”).
· Discontinuation Criteria:
o Discontinuation of Study Intervention: In rare instances, it may be necessary for a participant to permanently discontinue study   intervention. If study intervention is permanently discontinued, the participant [will/will not]   remain in the study to be evaluated for [X]. See the SoA for data to be collected at the time of discontinuation of study intervention and follow-up and for any further evaluations that need to be completed..
o Discontinuation of Study Intervention (e.g.,
§ “Subject declines further study participation (withdrawal of consent).”
§ “Subject develops an intolerable or unacceptable toxicity.”
§ “Subject receives any antileukemic therapy other than the assigned treatment.”).
o Participant Discontinuation/Withdrawal from the Study : Provide a list of reasons that may lead to the discontinuation of participants. It may be appropriate to have different discontinuation criteria for participants and the study cohort. If so, two separate sets of criteria should be listed, and the differences between them must be explained. Additionally, please note that participants may voluntarily withdraw from the study or discontinue the study intervention at any time. However, investigators should strive to minimize participant discontinuation/withdrawal from the study, unless it is due to safety reasons.
o (e.g.,
§ “Subject declines further study participation (withdrawal of consent).”
§ “Subject develops an intolerable or unacceptable toxicity.”
§ “Subject receives any antileukemic therapy other than the assigned treatment.”
§ “Investigator/sub-investigator determines that the continuation of the study treatment will be detrimental to the subject.”
§ “Death.”).
o Lost to Follow up (e.g.,
§ “Subject declines further study participation (withdrawal of consent).”
§ “Subject is lost to follow-up despite reasonable efforts by the investigator to locate the subject.”
§ “More than 3 years has passed from the subject’s end of treatment visit.”
§ “Death.”).


7. Statistical Methods
· Sample Size Justification:
o Rationale for sample size, power, and significance level (e.g.,
§ “The planned sample size of 318 subjects with 10% dropout rate and 230 events during the study will provide 90% power to detect a difference in OS between the ASP2215 arm (7.7 months) and salvage chemotherapy arm (5 months) at the 0.05 significance level.”).
· Randomization Stratification:
o Factors used for stratification (e.g., “response to first-line AML therapy and preselected salvage chemotherapy”).
· Primary and Secondary Efficacy Analyses:
o Statistical models and sets (e.g.,
§ “The primary efficacy endpoint of OS will be analyzed using the stratified Cox proportional hazard model on the Intention to Treat Set (ITT).”
§ “Key secondary efficacy endpoints will be analyzed using the Cochran-Mantel-Haenszel test.”).
· Interim Analysis(if applicable):
o Plan for interim evaluation and criteria for early termination (e.g.,
§ “A formal interim analysis is planned when approximately 50% of the planned death events have occurred. The IDMC may recommend terminating the trial for favorable or unfavorable results.”).

8. Safety and Pharmacokinetic Evaluations
· Safety Assessments:
o Adverse events, lab tests, vital signs, ECGs, and performance scores (e.g.,
§ “The Safety Analysis Set (SAS) is defined as all subjects who received at least one dose of study treatment.”
§ “Safety data will be summarized using descriptive statistics and MedDRA coding.”).
· Pharmacokinetic Analysis(if applicable):
o Methods for PK modeling and covariate analysis (e.g.,
§ “Population pharmacokinetic modeling will be conducted using nonlinear mixed effects methodology.”
§ “Plasma concentrations and PK parameters will be summarized using descriptive statistics.”).

9. Exploratory Analyses(if applicable)
· Biomarkers:
o Evaluation of mutation status and other biomarkers (e.g.,
§ “An exploratory analysis of FLT3 mutation status and clinical efficacy will be conducted.”
§ “Pharmacogenomics (PGx) and FLT3 gene mutation status will be analyzed in subgroups.”).
· Resource Utilization:
o Analysis of hospitalization, transfusions, and medication use (e.g.,
§ “An exploratory analysis will use CMH method for resource utilization status and ANOVA for resource utilization counts.”).
· Patient-Reported Outcomes (PROs):
o Tools used and analysis methods (e.g.,
§ “Functional Assessment of Cancer Therapy-Leukemia (FACT-Leu), Brief Fatigue Inventory (BFI), EuroQol Group-5 Dimension-5 Level Instrument (EQ-5D-5L) will be used.”).

10. Post-Treatment Follow-Up
· Long-Term Follow-Up:
o Schedule and duration (e.g., “every 3 months for up to 3 years from the subject’s end of treatment visit”).
· Endpoints Collected:
o Survival, subsequent AML treatments, remission status, and cause of death.

11. Appendices
· Glossary of Terms:
o Definitions of acronyms and key terms (e.g., CR, CRc, ECOG).
· References:
o Citations for protocols, guidelines, and literature.
"""