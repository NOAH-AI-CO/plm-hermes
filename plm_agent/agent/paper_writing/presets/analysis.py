from .enum import StudyType

DATA_ANALYSIS_GUIDE_WITH_STUDY_TYPE = {
    StudyType.RCT: {
        "description": "This dataset is derived from a randomized controlled trial aiming to estimate treatment effect by comparing intervention vs control groups",
        "key_analyses": [
            "Baseline characteristics comparison between groups",
            "Primary outcome analysis with effect size and confidence intervals",
            "Secondary outcomes and safety analysis",
            "Intention-to-treat and per-protocol analysis"
        ],
        "statistical_methods": [
            "t-test or ANOVA for group comparisons",
            "Effect size calculation (risk ratio, odds ratio, Cohen's d)",
            "95% confidence intervals and p-values",
            "Subgroup analysis with interaction tests"
        ],
        "expected_variable_roles": {
            "treatment_group": "Column indicating group assignment (e.g., treatment vs control)",
            "primary_outcome": "Main outcome variable to evaluate intervention effect",
            "secondary_outcome": "Additional outcomes, e.g., biomarkers or quality of life",
            "baseline_vars": "Subject characteristics at baseline, such as age, sex, or BMI"
        }
    },
    StudyType.COHORT: {
        "description": "This dataset is derived from a cohort study aiming to identify association between exposure and outcome over time",
        "key_analyses": [
            "Baseline characteristics by exposure groups",
            "Exposure-outcome association with confounder adjustment",
            "Dose-response and temporal pattern analysis",
            "Effect modification assessment"
        ],
        "statistical_methods": [
            "Logistic regression for binary outcomes",
            "Cox proportional hazards regression for time-to-event",
            "Adjusted hazard ratios and odds ratios",
            "Stratified analysis for effect modification"
        ],
        "expected_variable_roles": {
            "exposure": "Exposure factor hypothesized to influence the outcome",
            "outcome": "Target variable reflecting disease occurrence or other events",
            "confounders": "Covariates that might confound the exposure-outcome relationship"
        }
    },
    StudyType.CASE_CONTROL: {
        "description": "This dataset is derived from a case-control study aiming to estimate odds of exposure among cases vs controls",
        "key_analyses": [
            "Case-control exposure comparison",
            "Odds ratio estimation with confounder adjustment",
            "Dose-response and effect modification analysis",
            "Matching quality assessment"
        ],
        "statistical_methods": [
            "Odds ratio estimation (crude and adjusted)",
            "Logistic regression with confounder adjustment",
            "Conditional logistic regression for matched designs",
            "Effect modification analysis"
        ],
        "expected_variable_roles": {
            "case_control_status": "Binary variable indicating whether the subject is a case or a control",
            "exposure": "Key exposure variable hypothesized to be associated with case status",
            "confounders": "Covariates to adjust for potential confounding"
        }
    },
    StudyType.SYSTEMATIC_REVIEW: {
        "description": "This dataset is derived from a systematic review aiming to synthesize and summarize findings across multiple studies",
        "key_analyses": [
            "Study-level effect size synthesis",
            "Heterogeneity assessment across studies",
            "Publication bias evaluation",
            "Subgroup and sensitivity analyses"
        ],
        "statistical_methods": [
            "Meta-analysis (fixed and random effects)",
            "Heterogeneity analysis (I², Q-statistic)",
            "Forest plot and funnel plot analysis",
            "Meta-regression for subgroup analysis"
        ],
        "expected_variable_roles": {
            "effect_sizes": "Collection of effect size measures extracted from primary studies",
            "study_identifiers": "Labels or IDs for individual studies included in the review"
        }
    },
    StudyType.CASE_OBSERVATION: {
        "description": "This dataset is derived from a case report aiming to describe individual clinical trajectories and compare with literature",
        "key_analyses": [
            "Detailed case description and timeline",
            "Clinical feature analysis and pattern recognition",
            "Treatment response and outcome assessment",
            "Literature comparison and synthesis"
        ],
        "statistical_methods": [
            "Descriptive statistics for case characteristics",
            "Temporal pattern and trajectory analysis",
            "Qualitative comparison with literature",
            "Visual timeline representation"
        ],
        "expected_variable_roles": {
            "case_features": "Clinical observations and characteristics of the reported case",
            "timeline": "Sequence of events or time-stamped clinical changes"
        }
    },
    StudyType.CROSS_SECTIONAL: {
        "description": "This dataset is derived from a cross-sectional study aiming to estimate prevalence and identify associations at a single time point",
        "key_analyses": [
            "Prevalence estimation with confidence intervals",
            "Association analysis between variables",
            "Subgroup comparisons and effect modification",
            "Data quality and measurement validation"
        ],
        "statistical_methods": [
            "Prevalence estimation with 95% CI",
            "Logistic regression for binary outcomes",
            "Linear regression for continuous outcomes",
            "Chi-square tests and t-tests for group comparisons"
        ],
        "expected_variable_roles": {
            "exposure": "Predictor or independent variable measured at a single time point",
            "outcome": "Health status or condition assessed in the same cross-section",
            "subgroups": "Variables used to stratify analysis into relevant subpopulations"
        }
    }
}
