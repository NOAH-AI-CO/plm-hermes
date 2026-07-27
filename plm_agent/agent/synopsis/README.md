# synopsis_query_trials


## 通用 trial 搜索

```{python}
search_trials(indication str = None,
              phase: str = None,
              treatment_line: str = None,
              health_condition: str = None,
              sex: str = None,
              age: str = None,
              intervention_model: str = None,
              masking: str = None,
              outcome: str = None,
              location: str = None)
```

- indication: text
  - [protocolSection.conditionsModule.conditions](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Condition)
- phase: text
  - 对 phase 进行搜索：[protocolSection.designModule.phases](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Phase)
  - 可选值如下：
    - '1': 实际搜索仅是PHASE1的trial
    - '1/2': 实际搜索同时是PHASE1和PHASE2的trial
    - '2': 实际搜索仅是PHASE2的trial
    - '2/3': 实际搜索同时是PHASE2和PHASE3的trial
    - '3': 实际搜索仅是PHASE3的trial
    - '4': 实际搜索仅是PHASE4的trial
- treatment_line: text
  - 主要对 title 进行搜索:
    - [protocolSection.identificationModule.officialTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=OfficialTitle)
    - [protocolSection.identificationModule.briefTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefTitle)
  - 可选值如下：
    - first-line：First-Line Treatment, Newly Diagnosed, Treatment-Naïve, Initial Therapy, De Novo
    - second-line：Second-Line Treatment, Post First-Line Therapy
    - later-line：Later-Line Treatment, Advanced, Multiple Prior Lines of Therapy
    - rr：Relapsed/Refractory (R/R), Recurrent, Progressive Disease
- health_condition: text
  - 主要对 title 进行搜索
    - [protocolSection.identificationModule.officialTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=OfficialTitle)
    - [protocolSection.identificationModule.briefTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefTitle)
  - 可选值如下
    - healthy volunteers
    - hiv-positive
    - diabetic
    - hypertensive
    - obese
    - hepatic/renal impairment
    - liver/kidney dysfunction
- sex: text
  - 对 [protocolSection.eligibilityModule.sex](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Sex) 进行查询
  - 可选值如下:
    - FEMALE - Female
    - MALE - Male
    - ALL - All
    - BOTH - All
- age: text
  - 查询 [protocolSection.eligibilityModule.stdAges](https://clinicaltrials.gov/api/v2/stats/field/values?fields=StdAge)
  - 可选值如下:
    - CHILD - Child
    - ADULT - Adult
    - OLDER_ADULT - Older Adult
- intervention_model: text, default is None
  - 查询 [protocolSection.designModule.designInfo.interventionModel](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignInterventionModel)
  - 可选值如下:
    - SINGLE_GROUP - Single Group Assignment
    - PARALLEL - Parallel Assignment
    - CROSSOVER - Crossover Assignment
    - FACTORIAL - Factorial Assignment
    - SEQUENTIAL - Sequential Assignment
- masking: text, default is None
  - 查询 [protocolSection.designModule.designInfo.maskingInfo.masking](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignMasking)
  - 可选值如下:
    - NONE - None (Open Label)
    - SINGLE - Single
    - DOUBLE - Double
    - TRIPLE - Triple
    - QUADRUPLE - Quadruple
- outcome: text
  - 查询:
    - protocolSection.outcomesModule.primaryOutcomes.measure
    - protocolSection.outcomesModule.primaryOutcomes.description
    - protocolSection.outcomesModule.secondaryOutcomes.measure
    - protocolSection.outcomesModule.secondaryOutcomes.description
    - protocolSection.outcomesModule.otherOutcomes.measure
    - protocolSection.outcomesModule.otherOutcomes.description
- location: text
  - 查询 [protocolSection.contactsLocationsModule.locations.country](https://clinicaltrials.gov/api/v2/stats/field/values?fields=LocationCountry)
  - 可选值如下：
    - CN: China, including HK, TW, MO
    - US: United Status
    - EU: European Union countries, including: AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK
    - JP: Japan
    - Other
- size: int, default is 500 (total data size, not sample count)

## Roche 项目 Phase 4 trial 搜索

针对Roche项目开发的 phase 4 搜索

```{python}
search_trials_phase4(study_type: str=None,
                     indication: str = None,
                     phase: str = '4',
                     treatment_line: str = None,
                     health_condition: str = None,
                     sex: str = None,
                     age: str = None,
                     intervention_type: str = None,
                     intervention_query: str = None,
                     masking: str = None,
                     outcome: str = None,
                     location: str = None)
```


- study_type: text
  - 可选值为
    - COHORT
    - CASE_CONTROL
    - CROSS_SECTIONAL
    - SINGLE_GROUP
    - PARALLEL
    - CROSSOVER
    - FACTORIAL
    - SEQUENTIAL
  - 当值为 COHORT，CASE_CONTROL 时，会搜索 observational clinical trial
    - [protocolSection.designModule.designInfo.observationalModel](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignObservationalModel)
  - 当值为 CROSS_SECTIONAL 时，也被归为 observational，但会搜索 time perspective 和 title，description等
    - [protocolSection.designModule.designInfo.timePerspective](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignTimePerspective)
    - [protocolSection.identificationModule.officialTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=OfficialTitle)
    - [protocolSection.identificationModule.briefTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefTitle)
    - [protocolSection.descriptionModule.briefSummary](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefSummary)
    - [protocolSection.descriptionModule.detailedDescription](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DetailedDescription)
  - 当值为 SINGLE_GROUP, PARALLEL, CROSSOVER, FACTORIAL, SEQUENTIAL 会搜索 intervention clinical trial
    - [protocolSection.designModule.designInfo.interventionModel](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignInterventionModel)
- indication: text
  - [protocolSection.conditionsModule.conditions](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Condition)
- phase: text
  - 对 phase 进行搜索：[protocolSection.designModule.phases](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Phase)
  - 虽然可以有不同的值，但是默认值是 4
  - 只有在 study_type 为 [CROSS_SECTIONAL, SINGLE_GROUP, PARALLEL, CROSSOVER, FACTORIAL, SEQUENTIAL] 才会用于做 filter
- treatment_line: text
  - 主要对 title 进行搜索:
    - [protocolSection.identificationModule.officialTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=OfficialTitle)
    - [protocolSection.identificationModule.briefTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefTitle)
  - 可选值如下：
    - first-line：First-Line Treatment, Newly Diagnosed, Treatment-Naïve, Initial Therapy, De Novo
    - second-line：Second-Line Treatment, Post First-Line Therapy
    - later-line：Later-Line Treatment, Advanced, Multiple Prior Lines of Therapy
    - rr：Relapsed/Refractory (R/R), Recurrent, Progressive Disease
- health_condition: text
  - 主要对 title 进行搜索
    - [protocolSection.identificationModule.officialTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=OfficialTitle)
    - [protocolSection.identificationModule.briefTitle](https://clinicaltrials.gov/api/v2/stats/field/values?fields=BriefTitle)
  - 可选值如下
    - healthy volunteers
    - hiv-positive
    - diabetic
    - hypertensive
    - obese
    - hepatic/renal impairment
    - liver/kidney dysfunction
- sex: text
  - 对 [protocolSection.eligibilityModule.sex](https://clinicaltrials.gov/api/v2/stats/field/values?fields=Sex) 进行查询
  - 可选值如下:
    - FEMALE - Female
    - MALE - Male
    - ALL - All
    - BOTH - All
- age: text
  - 查询 [protocolSection.eligibilityModule.stdAges](https://clinicaltrials.gov/api/v2/stats/field/values?fields=StdAge)
  - 可选值如下:
    - CHILD - Child
    - ADULT - Adult
    - OLDER_ADULT - Older Adult
- intervention_type: text
  - 查询 [protocolSection.armsInterventionsModule.interventions.type](https://clinicaltrials.gov/api/v2/stats/field/values?fields=InterventionType)
  - 可选值如下：
    - DRUG
    - OTHER
    - DEVICE
    - BEHAVIORAL
    - PROCEDURE
    - BIOLOGICAL
    - DIAGNOSTIC_TEST
    - DIETARY_SUPPLEMENT
    - RADIATION
    - COMBINATION_PRODUCT
    - GENETIC
- intervention_query: text
  - 查询 [protocolSection.armsInterventionsModule.interventions.name](https://clinicaltrials.gov/api/v2/stats/field/values?fields=InterventionName)
  - 查询 [protocolSection.armsInterventionsModule.interventions.description](https://clinicaltrials.gov/api/v2/stats/field/values?fields=InterventionDescription)
- masking: text, default is None
  - 查询 [protocolSection.designModule.designInfo.maskingInfo.masking](https://clinicaltrials.gov/api/v2/stats/field/values?fields=DesignMasking)
  - 可选值如下:
    - NONE - None (Open Label)
    - SINGLE - Single
    - DOUBLE - Double
    - TRIPLE - Triple
    - QUADRUPLE - Quadruple
- outcome: text
  - 查询:
    - protocolSection.outcomesModule.primaryOutcomes.measure
    - protocolSection.outcomesModule.primaryOutcomes.description
    - protocolSection.outcomesModule.secondaryOutcomes.measure
    - protocolSection.outcomesModule.secondaryOutcomes.description
    - protocolSection.outcomesModule.otherOutcomes.measure
    - protocolSection.outcomesModule.otherOutcomes.description
- location: text
  - 查询 [protocolSection.contactsLocationsModule.locations.country](https://clinicaltrials.gov/api/v2/stats/field/values?fields=LocationCountry)
  - 可选值如下：
    - CN: China, including HK, TW, MO
    - US: United Status
    - EU: European Union countries, including: AT, BE, BG, CY, CZ, DE, DK, EE, EL, ES, FI, FR, HR, HU, IE, IT, LT, LU, LV, MT, NL, PL, PT, RO, SE, SI, SK
    - JP: Japan
    - Other
