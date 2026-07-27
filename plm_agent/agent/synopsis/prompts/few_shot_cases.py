input_1 = """{
    "Study Category": "Observational Study", "Cohort study (prospective/retrospective/ambispective)"
    "Study Objective": "To describe hepatitis A vaccination coverage (first and second doses) among adults with chronic liver disease (CLD) in the RSC network in England, and to compare uptake across different population and etiological groups; to estimate transition probabilities using a multi-state survival model (CLD diagnosis → first dose → second dose → death as competing absorbing state)."
  },
  "PICO": {
    "Population": {
      "Disease": {
        "Indication": "Adults with chronic liver disease (CLD) including ALD, HBV, HCV, MASLD, Wilson’s disease, haemochromatosis, autoimmune hepatitis, PSC, PBC, etc."
      },
      "Age Range": "≥18 years",
      "Sex": "Unrestricted",
      "Additional Information": "Data from the Oxford–RCGP Research & Surveillance Centre (RSC) Primary Care Sentinel Cohort (PCSC); electronic health records between Jan 1, 2012 and Dec 31, 2022; de-identified and extracted within the ORCHID secure environment; nationally representative sample.",
      "Inclusion Criteria": [
        "Adults (≥18 years) registered in practices within the RSC network",
        "First recorded CLD diagnosis during 2012–2022",
        "CLD etiology including ALD, HBV, HCV, MASLD, Wilson’s disease, haemochromatosis, autoimmune hepatitis, PSC, PBC"
      ],
      "Exclusion Criteria": [
        "Contraindications to hepatitis A vaccination (e.g., confirmed allergic reaction to a previous dose or vaccine component)",
        "Receipt of immunoglobulin for post-exposure or infection prophylaxis"
      ]
    },
    "Intervention/Exposure": {
      "Study Group Characteristics": [
        "Hepatitis A vaccination status (first dose, second dose, vaccine type, dates); booster recommended at 6–12 months after first dose (sensitivity analysis extended to 3 years)",
        "Sociodemographic characteristics (age, sex, ethnicity, region, urban/rural, socioeconomic status via IMD, obesity, alcohol, smoking)",
        "Comorbidities and complications (based on CMMS and coded in SNOMED CT/ICD)"
      ],
      "Covariates": "Age, sex, ethnicity, urban/rural classification, region, socioeconomic status (IMD), obesity, alcohol, smoking, comorbidities and complications (10-year lookback, including osteoporosis, cholangiocarcinoma/colorectal cancer, renal disease/stones, ascites, hepatic failure/transplant, cardiometabolic diseases, etc.)",
      "Confounders": "Same as covariates",
    },
    "Outcomes": {
      "Outcome Variables": [
        "Coverage of first hepatitis A dose (by age, sex, ethnicity, IMD, BMI, smoking, alcohol, CLD etiology, complications, etc.)",
        "Coverage of second hepatitis A dose (full course, baseline 12-month window, sensitivity 3-year window)",
        "Transition probabilities in multi-state survival model: CLD → first dose → second dose → death (death as competing absorbing state)"
      ]
    }
  },
  "Additional": {
    "Data Collection": {
      "Data Sources": {
        "Electronic Medical Records",
        "Registry system",
        "Research database",
        "Variables from this source (text box, optional)": "Sociodemographics, CLD diagnosis and etiology, comorbidities/complications, vaccination dates and products, mortality (coded in SNOMED CT/ICD and vaccine product codes)",
        "Database information (text box, optional)": "Oxford–RCGP RSC Primary Care Sentinel Cohort (PCSC); ORCHID secure environment; nationally representative"
      }
    },
    "Statistical Methods": {
      "Statistical Method Configuration": [
        {
          "Variable name": "Baseline characteristics and coverage rates",
          "Variable type": "Categorical/Continuous",
          "Detailed description": "Stratified by age, sex, ethnicity, region, IMD, BMI, alcohol, smoking, CLD etiology, complications; coverage estimated with CLD cohort denominator",
          "Statistical method": "Descriptive statistics (mean/SD/median/IQR); group comparisons by chi-square/Fisher’s exact test, t-test or Wilcoxon; multiple groups by Kruskal–Wallis/chi-square with post-hoc tests"
        },
        {
          "Variable name": "State transitions (first dose/second dose/death)",
          "Variable type": "Time-to-event (multi-state)",
          "Detailed description": "Transitions CLD→first dose→second dose→death; second dose window modeled as 12 months and 3 years",
          "Statistical method": "Multi-state survival model with death as competing risk"
        }
      ],
      "Subgroup/Interaction Analysis": {
        "Subgroup Analysis",
        "Subgroup variables (text box)": "Age, sex, ethnicity, region, urban/rural, IMD, BMI, smoking, alcohol, CLD etiology and complications",
      },
      "Sensitivity Analysis": "Second dose time window sensitivity (12 months vs 3 years)",
      }
    }
  }
}
"""

input_2 = """
{
  "Study Category": "Observational Study", "Cohort study (prospective/retrospective/ambispective)"
  "Study Objective": "This study aims to evaluate the incidence and clinical characteristics of second primary cancers (SPCs) among thoracic malignancy survivors in Spain, based on the TTR registry."
  "PICO": {
    "Population": {
      "Inclusion Criteria": [
        "Patients with thoracic disease, treated with an active treatment or not treated (only palliative care)"
      ],
      "Exclusion Criteria": [
        "Patients with other type of tumours"
      ]
    },
  },
    },
    "Statistical Methods": {
      "Subgroup/Interaction Analysis": "Interaction Exploration"
    }
}
"""

input_2_full = """
{
    "Study Category": "Observational Study", "Cohort study (prospective/retrospective/ambispective)"
    "Study Objective": "This study aims to evaluate the incidence and clinical characteristics of second primary cancers (SPCs) among thoracic malignancy survivors in Spain, based on the TTR registry."
    "PICO": {
        "Population": {
            "Disease": {
                "Indication": "Thoracic malignancy survivors (NSCLC, SCLC, other thoracic primary tumours)"
            },
            "Age Range": "Adults (≥18 years)",
            "Sex": "Unrestricted",
            "Additional Information": "Multicentre Spanish registry (>80 hospitals across Spain), prospective and retrospective data from 2006 onwards.",
            "Inclusion Criteria": [
                "Adults (≥18 years old)",
                "Histologically confirmed thoracic malignancy (including NSCLC, SCLC, other thoracic primary tumours)",
                "Achieved remission after oncological treatment (chemotherapy, immunotherapy, targeted therapy, radiotherapy, or surgery)",
                "Availability of complete baseline and follow-up data",
                "Provided informed consent"
            ],
            "Exclusion Criteria": [
                "First primary tumour outside the thoracic region",
                "Second primary cancer diagnosed before or at the same time as the first primary cancer",
                "Incomplete baseline data preventing classification of treatment exposure"
            ]
        },
        "Intervention/Exposure": {
            "Study Group Characteristics": [
                "Systemic treatment type: chemotherapy, immunotherapy (ICI), targeted therapy (EGFR-TKI, ALK-TKI, etc.), with dates and treatment lines",
                "Treatment combinations (monotherapy or combination: chemo+ICI, ICI+targeted, targeted+chemo)",
                "Radiotherapy history (type, date)",
                "Surgery (resection; type, date)",
                "Smoking history (never/former/current; pack-years)"
            ],
            "Covariates": "Smoking status, age, sex, histological subtype, tumour stage, radiotherapy history, personal/family cancer history",
            "Confounders": "Same as covariates",
            "Effect Modifiers": "Smoking status; histological type (NSCLC vs SCLC); treatment modality"
        },
        "Comparator": {
            "Comparator Type": "Historical control",
            "Comparator Group Characteristics": []
        },
        "Outcomes": {
            "Outcome Variables": [
                "Incidence of second primary cancer (SPC), pathologically confirmed",
                "Time to SPC diagnosis from index date",
                "SPC type (anatomical site classification, ICD-O-3)",
                "All-cause mortality"
            ]
        }
    },
    "Additional": {
        "Data Collection": {
            "Data Sources": {
                "Electronic Medical Records",
                "Registry system",
                "Variables from this source (text box, optional)": "Treatment exposures, comorbidities, SPC diagnosis, mortality",
                "Database information (text box, optional)": "Spanish Thoracic Tumour Registry (TTR)"
            }
        },
        "Statistical Methods": {
            "Statistical Software": ["R", "Stata"],
            "Statistical Method Configuration": [
                {
                    "Variable name": "Baseline demographics and tumour characteristics",
                    "Variable type": "Categorical/Continuous",
                    "Detailed description": "Summarised using counts, percentages, means/medians",
                    "Statistical method": "Descriptive statistics"
                },
                {
                    "Variable name": "SPC incidence",
                    "Variable type": "Time-to-event",
                    "Detailed description": "Cumulative incidence functions",
                    "Statistical method": "CIF"
                },
                {
                    "Variable name": "Association with SPC occurrence",
                    "Variable type": "Time-to-event",
                    "Detailed description": "Adjusted for age, sex, histology, smoking, treatment, history variables",
                    "Statistical method": "Multivariable Cox proportional hazards model"
                }
            ],
            "Subgroup/Interaction Analysis": {
                "Subgroup Analysis",
                "Subgroup variables (text box)": "Smoking status, treatment modality, histology",
                "Interaction Exploration"
            },
            "Missing Data Handling": "Variables with <5% missing: included in reference category; otherwise missing as separate category; complete-case sensitivity analysis planned",
            "Sensitivity Analysis": "Excluding prior cancer history; <1 year follow-up; restricting to prospective cases",
            "Multiplicity Adjustment": "False discovery rate (FDR) using Benjamini–Hochberg",
            "Study Type–Specific Methods": {
                "Cohort Study": {
                    "Loss to follow-up handling": ["Right censoring"]
                }
            }
        }
    }
}
"""

input_3 = """
研究类型选择
- 研究分期：空
- 研究类别：观察性研究 → 横断面研究
研究目的
探索拇指腕掌关节骨关节炎（CMC OA）的生物力学、神经肌肉及躯体感觉机制。
PICO - 研究人群
- 适应症：拇指腕掌关节骨关节炎（CMC OA）
- 年龄范围：18–90 岁
  - CMC OA 与年龄匹配对照：40–90 岁
  - 年轻健康对照：18–39 岁
- 性别：女性
- 补充信息：仅纳入女性以减少性别差异。
入选标准
- CMC OA 组：女性，40–90 岁，经认证临床医生诊断为末期拇指 CMC OA。
- 年龄匹配对照：女性，40–90 岁，无手/腕关节或肌肉疼痛。
- 年轻健康对照：女性，18–39 岁，无手/腕关节或肌肉疼痛。
排除标准
- 未成年人（<18 岁）
- 孕妇
- 精神障碍者
- 被监禁、假释或候审人员
- 伴有手/腕肌肉骨骼疾病（桡骨远端骨折、挛缩、扳机指、腕管综合征）
- 有无法控制的糖尿病、类风湿关节炎、肌肉功能障碍或神经疾病史

---
PICO - 干预/暴露
- CMC OA 组：女性，40–90 岁，末期 CMC OA。
- 年龄匹配健康对照：女性，40–90 岁，无手/腕疼痛。
- 年轻健康对照：女性，18–39 岁，无手/腕疼痛。
- 协变量：年龄、BMI、心理状态、疼痛表型（QST）、功能评分
- 混杂因素：心理状态、日常活动水平、应对方式
- 效应修饰因素：疼痛敏化表型（中枢 vs 外周）、功能能力、影像学严重度
PICO - 比较组
- 类型：同时对照
- 特征：
  - 年龄匹配健康对照
  - 年轻健康对照
PICO - 结局
- 实验性疼痛敏感性（QST）
- 临床疼痛（GCPS、BPI、AUSCAN、OPTIMIZE）
- 心理学测量（PROMIS、CES-D、BDI、PSS、MoCA、CSQ-R、SWLS、LOT-R、PANAS）
- 功能结局（拇指活动度、握力/捏力、Jebsen、DASH）
- 疾病严重度（X 线 Eaton 分级）

---
附加信息
- 研究周期：
  - 索引期：首次实验测试时间
  - 观察期：单次横断面评估，最多三次实验室/影像学会话
- 数据收集：
  - 来源：现场访视、其他
  - 描述：实验室（肌电、运动捕捉、QST）、临床（病史、体检、问卷）、影像（X 光）
  - 数据库：UF REDCap 与 HIPAA 合规服务器
- 统计方法：
  - 软件：SPSS、SAS、R
  - 方法：单因素方差分析或非参数检验
  - 亚组/交互：有（疼痛表型、疼痛与功能关系）
  - 缺失值：完全病例分析
  - 敏感性分析：排除无症状但有影像退变者
  - 多重性：Bonferroni 或 FDR
  - 抽样策略：分层与调整以保证可比性
"""

few_shot_cases_a = """
Example 1:
Input:
{input_1}
Output: 
1. 基本信息
- 研究标题
 英格兰初级保健中慢性肝病成人的甲型肝炎疫苗接种覆盖：基于 RSC 门诊网络的回顾性队列研究
- 主要作者及单位
 请按要求填写。
- 计划研究开始日期 / 结束日期
 请按要求填写。
- 干预/暴露
 甲肝疫苗接种状态（首剂、第二剂），并收集社会人口学因素、肝病病因学、合并症、吸烟状态及既往流感疫苗接种史作为协变量。
 
 2. 背景与研究依据
- 背景
 慢性肝病（Chronic Liver Disease, CLD）是全球公共卫生负担重大的疾病。CLD 患者若感染甲型肝炎（HAV），其临床过程更严重，急性肝衰竭及死亡风险增加。英国指南建议对 CLD 人群进行两剂甲肝疫苗接种，但甲肝疫苗并非英国全民免疫计划的一部分，主要在旅行接种门诊和部分初级保健机构完成。
 现有研究提示高危人群的甲肝疫苗覆盖率普遍较低，且接种与社会人口学因素（年龄、性别、族裔、社会经济水平）、临床因素（肝病病因学、合并症）、健康行为（吸烟、既往流感疫苗接种）有关。缺乏全国性、代表性的大规模真实世界数据对 CLD 人群的甲肝疫苗接种情况进行系统评估。
- 研究必要性
 本研究基于 Oxford–RCGP Research & Surveillance Centre (RSC) 网络的大规模电子健康记录数据，能够：
  1. 量化 CLD 人群甲肝疫苗首剂和全程接种覆盖率；
  2. 识别接种差异和潜在的不平等（如族裔、社会经济地位）；
  3. 为初级保健提供基于证据的改进策略，例如提醒系统和与流感疫苗接种的联合策略；
  4. 为公共卫生政策和健康技术评估（HTA）提供真实世界证据。
- 相关文献
  1. Meza-Torres B, et al. JMIR Res Protoc. 2023;12(1):e51861. （研究 protocol，提出多状态生存模型和四状态设计）
  2. Oxford–RCGP RSC 网络相关方法学文献（网络代表性和数据质量）
  3. UK Health Security Agency. Hepatitis A vaccination guidelines.
  4. NICE Guidance on immunisation for high-risk groups.
  
3. 研究设计临床方案
- 研究设计类型
 观察性、回顾性队列研究。数据来源为 Oxford–RCGP Research & Surveillance Centre (RSC) 网络的初级保健计算机化医疗记录（CMR）。
 使用多状态生存模型，将患者状态建模为：
  1. 慢性肝病诊断；
  2. 甲肝疫苗首剂；
  3. 甲肝疫苗第二剂；
  4. 死亡（竞争风险吸收状态）。
  - 研究类型：真实世界疫苗利用与覆盖研究。
  - 比较与分层：对比接种与未接种人群，分层因素包括年龄、性别、族裔、社会经济水平、肝病病因学、合并症、吸烟及既往流感疫苗接种史。
  - 主要测量指标：甲肝疫苗覆盖率（首剂与全程），状态转移强度（由诊断到接种的概率），以及协变量与接种行为之间的关系。
- Setting
  - 研究期：2012–2022 年
  - 索引日：个体首次被记录为慢性肝病诊断之日
  - 识别期：研究期内首次确诊 CLD 且此前未接种甲肝疫苗的患者
  - 前期（回溯期）：索引日前收集基线变量（如 BMI、吸烟）
  - 后期（随访期）：从索引日起，直至接种首剂/第二剂、死亡或研究期结束（右删失）
  
Example 2:
Input: 
{input_2}
Output:
1. 基本信息
- 研究标题
 西班牙胸部肿瘤登记（TTR）队列研究：胸部恶性肿瘤的发生情况、治疗特征及第二原发癌风险——基于全国性前瞻性与回顾性队列的研究
- 主要作者姓名及单位
 请按要求填写。
- 计划研究开始/结束日期
 开始日期：2016-07-21
 结束日期：2030-12-30
- 干预/暴露
 暴露：胸部肿瘤患者接受的肿瘤治疗类型（化疗、免疫治疗、靶向治疗、手术、放疗或姑息治疗等），重点分析系统治疗（化疗、免疫治疗、靶向治疗）。

2. 背景与研究依据
背景
胸部恶性肿瘤，尤其是肺癌，是全球发病率和死亡率最高的癌种之一。随着诊断技术和系统治疗的进步（如免疫检查点抑制剂、靶向治疗），患者生存期显著延长，长期生存者数量不断增加。然而，这些患者仍面临**第二原发癌（SPC）**的风险。该风险受到既往治疗（如细胞毒性化疗、胸部放疗）、生活方式（如吸烟）、遗传易感性等多因素影响。
 目前，关于免疫治疗和靶向治疗对 SPC 风险的长期影响的证据有限且结果不一致。西班牙缺乏大规模、前瞻性、真实世界的数据来系统评估胸部肿瘤患者在不同治疗模式下 SPC 的发生情况及相关危险因素。
研究必要性
本研究依托西班牙胸部肿瘤登记（TTR），将提供全国范围内的流行病学与临床数据，用于：
- 明确不同治疗方式对 SPC 风险的影响
- 为临床随访与筛查策略提供依据
- 指导临床治疗决策
- 为公共卫生（特别是戒烟干预）和卫生技术评估（HTA）提供证据
相关文献
- Heudel P, et al. ESMO Open. 2021;6(1):100044.
- Su VYF, et al. Target Oncol. 2017;12(2):219–227.
- Howlader N, et al. N Engl J Med. 2020;383(7):640–649.
- Bhatia S, Sklar C. Nat Rev Cancer. 2002;2(2):124–132.

---
3. 研究设计概述
- 研究设计类型
 本研究为观察性、多中心、全国性队列研究，结合前瞻性与回顾性数据，基于西班牙胸部肿瘤登记（TTR）实施。
- 患者按主要接受的全身治疗方式分组：
  1. 化疗组（未接受免疫或靶向治疗）
  2. 免疫治疗组（免疫单药或联合化疗/靶向治疗）
  3. 靶向治疗组（靶向药单用或联合化疗）
- 主要终点：SPC 发生率（需病理学确诊，与首发肿瘤为不同实体）。
次要终点：SPC 发生时间、SPC 类型分布、相关危险因素分析、全因死亡。
- 研究场景
  - 研究周期：2016 年 8 月至 2030 年 12 月
  - 索引日期：首次原发胸部肿瘤治疗达到缓解的日期（对于回顾性入组患者，索引日期可早于 2016 年 8 月）
  - 识别期：2016 年 8 月至 2023 年 3 月；回顾性纳入 2006 年后诊断的患者
  - 前期数据：索引日前的临床史（吸烟、合并症、既往肿瘤史、家族肿瘤史等）
  - 随访期：索引日起至 SPC 诊断、死亡、失访或研究结束
  
Example 3:
Input: 
{input_3}
Output:
1. 基本信息（Basic Information）
- 研究标题（Study Title）
 《拇指腕掌关节骨关节炎：探索生物力学、神经肌肉与躯体感觉机制的横断面研究（NCT04104477）》
- 主要作者及机构（Name and affiliation of main author）
 Please fill in according to the requirements.
- 计划研究开始/结束日期（Planned Study Start Date / End Date）
 Please fill in according to the requirements.
- 干预/暴露（Intervention / Exposure）
  - 研究对象暴露因素：拇指腕掌关节骨关节炎（CMC OA）
  - 比较组：年龄匹配对照组、年轻健康对照组
  - 本研究无药物或器械干预，属于观察性横断面研究

---
2. 背景与研究理由（Background & Rationale）
- 背景（Background）
  - 在美国，超过 1300 万人患有手部骨关节炎，其中拇指腕掌关节（CMC 关节）的累及尤为致残，可导致手功能损失高达 50%。
  - 现有保守治疗（物理治疗、矫形器、抗炎药、局部类固醇注射）仅能短期缓解疼痛，对恢复功能帮助有限；手术虽能止痛，但往往降低关节活动度与力量，且存在多种手术方式而缺乏统一最佳方案。
  - 疼痛是患者就诊的主要原因，但影像学严重程度与症状并不完全对应。例如，约 33% 的绝经后女性有影像学 CMC OA 表现，但仅 5% 因疼痛就诊。
  - 这提示存在不同疼痛表型，其机制可能包括中枢敏化与外周敏化。已有研究显示 CMC OA 患者常出现痛觉过敏（hyperalgesia），但机制尚未明确。
  - 既往研究多关注关节稳定性，而未充分探讨肌肉活动模式与疼痛机制的关系。已有证据表明，肌肉协调可能在缓解或加重症状中发挥关键作用。
- 研究必要性（Justification）
  - 当前缺乏能够长期缓解疼痛并恢复精细/粗大功能的有效治疗。
  - 研究 CMC OA 的生物力学、神经肌肉及躯体感觉机制，有助于明确症状异质性的根源，并为未来设计更具靶向性的治疗提供科学依据。
- 相关文献（Relevant Literature）
  - Ladd AL, Messana JM, Berger AJ, Weiss AP. J Hand Surg Am. 2015;40(3):474-82.
  - Vermeulen GM, Slijper H, Feitz R, Hovius SE, Moojen TM, Selles RW. J Hand Surg Am. 2011;36(1):157-69.
  - Wolf JM, Turkiewicz A, Atroshi I, Englund M. Arthritis Care Res. 2014;66(6):961-5.
  - Haara MM, Heliovaara M, Kroger H, et al. J Bone Joint Surg Am. 2004;86-A(7):1452-7.
  - Chiarotto A, Fernandez-de-Las-Penas C, Castaldo M, Villafane JH. Pain Med. 2013;14(10):1585-92.
  - Wajed J, Ejindu V, Heron C, Hermansson M, Kiely P, Sofat N. Int J Rheumatol. 2012:703138.
  - Cruz-Almeida Y, Fillingim RB. Pain Med. 2014;15(1):61-72.

3. 研究设计概述（Study Design Overview）
- 研究设计类型（Study Design Type）
  - 研究类型：横断面观察研究（cross-sectional study）
  - 研究目的：探索拇指腕掌关节骨关节炎（CMC OA）的生物力学、神经肌肉和躯体感觉机制
  - 研究性质：疾病机制研究，非药物/器械干预型
  - 研究比较组：
    1. CMC OA组（终末期CMC OA，40–90岁女性）
    2. 年龄匹配健康对照组（40–90岁女性，无手/腕关节或肌肉疼痛）
    3. 年轻健康对照组（18–39岁女性，无手/腕关节或肌肉疼痛）
  - 主要测量指标：
    - 生物力学：肌肉活动（EMG）、关节运动学、关节稳定性
    - 疼痛：运动诱发性疼痛（VAS）、定量感觉测试（QST）
    - 功能：手功能测试、捏力/握力
    - 影像学：拇指X光片（Eaton分级）
- 研究场景（Setting）
  - 研究周期（Study period）：Please fill in according to the requirements.
  - 索引日期（Index date）：受试者首次参与实验测试日期
  - 识别期（Identification period）：患者/对照受试者招募与筛选阶段
  - 回顾期（Pre-period）：不设固定回顾期，仅采集病史与基线数据
  - 随访期（Post-period）：单次横断面评估（最多三次实验室或影像学会话），无长期随访
  
"""

few_shot_cases_b = """
Example 1:
Input: 
{input_1}
Output:
1. 研究人群
- 入选标准
  1. 年龄 ≥18 岁；
  2. 注册于 RSC 网络初级保健诊所；
  3. 在研究期内首次确诊慢性肝病（CLD）；
  4. 索引日前未接种过甲肝疫苗；
  5. 电子病历信息完整，满足数据使用与隐私合规要求。
- 排除标准
  1. 对甲肝疫苗或其成分有禁忌症（严重过敏反应等）；
  2. 接受过免疫球蛋白用于暴露后或感染后预防；
  3. 关键时间记录不合理（如死亡日期早于 CLD 诊断）；
  4. 在 CLD 诊断前已接种甲肝疫苗。
- 特殊说明
  - 来源：Oxford–RCGP RSC 网络，覆盖全英格兰和威尔士，数百万注册人群，数据代表性强；
  - 招募方式：基于电子健康记录的回顾性识别，无额外招募；
  - 随访方式：依赖 RSC 数据的持续更新，失访个体在最后一次记录时右删失；
  - 本研究人群不包括儿童和青少年，仅限 ≥18 岁成年人。


Example 2:
Input: 
{input_2}
Output:
4. 研究人群
- 入选标准
  1. 诊断时年龄 ≥18 岁
  2. 组织学确诊胸部恶性肿瘤（包括肺癌及其他胸部原发肿瘤）
  3. 接受过抗肿瘤治疗并达到缓解（化疗、免疫、靶向、放疗或手术）
  4. 有完整的基线与随访数据
  5. 签署知情同意
- 排除标准
  1. 首发肿瘤为非胸部恶性肿瘤
  2. 首发癌诊断前或同期已存在 SPC
  3. 无法确认治疗方式或关键基线数据缺失
- 特殊说明
  - 队列研究设计，患者来源于 TTR 并长期随访
  - 多中心 (>80 家西班牙医院)
  - SPC 需病理学确证

Example 3:
Input: 
{input_3}
Output:
4. 研究人群（Study Population）
- 纳入标准（Inclusion Criteria）
  - CMC OA组
    - 女性，40–90岁
    - 经认证临床医生确诊为终末期拇指CMC OA
  - 年龄匹配对照组
    - 女性，40–90岁
    - 无手/腕关节或肌肉疼痛
  - 年轻健康对照组
    - 女性，18–39岁
    - 无手/腕关节或肌肉疼痛
- 排除标准（Exclusion Criteria）
  - <18岁未成年人
  - 孕妇
  - 精神障碍患者
  - 在押、缓刑、候审人员
  - 伴有手/腕其他肌肉骨骼疾病（如远端桡骨骨折、挛缩、扳机指、腕管综合征）
  - 有不受控的糖尿病、类风湿关节炎、肌肉功能障碍或神经系统疾病病史
- 特别考虑事项（Special Considerations）
  - 来源与招募方式
    - CMC OA患者：由佛罗里达大学矫形运动医学门诊（OSMI）直接推荐
    - 对照组：通过校园与社区招募（张贴传单、实验室网站公告、学术与社区活动口碑传播）
  - 随访与观察方式
    - 仅进行一次性或短期实验室/影像学测试，无长期随访
  - 研究对象特征
    - 仅招募女性，以减少性别差异影响
    
"""

few_shot_cases_c = """
Example 1:
Input: 
{input_1}
Output:
1. 变量
暴露变量
| 暴露变量 | 定义与测量 |
|---------|-----------|
| 社会人口学特征 | 年龄（连续变量及分组）、性别、族裔、城乡属性、社会经济水平（IMD十分位，合并为高/低类别） |
| 慢性肝病病因学 | 病因分型：酒精相关、病毒性（乙/丙肝）、MASLD、自身免疫、肝硬化、其他（如PBC/PSC/遗传性疾病等） |
| 合并症 | 索引日前记录的合并症，包括：恶性肿瘤、糖尿病、心力衰竭、慢性肾病（3-5期）、慢性呼吸疾病、肥胖（BMI>30）、高血压、精神障碍、缺脾等 |
| 行为与接种史 | 吸烟状态（现吸烟/既往/从不/缺失单独类别）；既往流感疫苗接种情况（是/否） |

| 结局变量 | 定义与测量 |
|---------|-----------|
| 甲肝疫苗首剂接种 | 任一含甲肝抗原制剂的首次接种（包括单价或联合疫苗），记录接种日期 |
| 甲肝疫苗第二剂接种 | 在首剂>6个月后完成的加强剂记录 |
| 死亡（竞争风险） | 随访期间的全因死亡，作为竞争风险吸收状态纳入多状态模型 |

人口学/基线特征
- 年龄、性别、族裔
- 城乡属性
- 社会经济水平（IMD）
- BMI（索引日前最近记录）
- 登记诊所的地理位置

---
协变量/混杂因素
- 年龄
- 性别
- 族裔
- 社会经济水平
- 城乡属性
- 吸烟状态
- 既往流感疫苗接种
- 肝病病因学
- 合并症负担

---
效应修饰因素（如适用）
- 年龄分组（如 18–39 岁，40–64 岁，≥65 岁）
- 肝病病因学（病毒性 vs 非病毒性，MASLD vs 非 MASLD）
- 社会经济水平（高 vs 低）
- 城乡属性（城市 vs 农村）
- 吸烟状态（吸烟 vs 不吸烟）

2. 数据来源
- 来源类型
  - Oxford–Royal College of General Practitioners Research & Surveillance Centre (RSC) 数据库
  - 初级保健电子病历（Computerised Medical Record, CMR）
  - 门诊疫苗接种记录
  - 诊断和治疗编码（SNOMED CT, ICD）
  - 社会经济与地域数据（Index of Multiple Deprivation, ONS 农村/城市分类）

---
- 变量与来源对应示例

| 变量 | 数据源 | 编码/术语 | 评估方法 |
|------|--------|-----------|----------|
| 甲肝疫苗接种 | RSC 接种记录 | 药物/疫苗代码 | 接种日期和制剂类型识别首剂/第二剂 |
| CLD 诊断与病因学 | RSC 电子病历 | SNOMED CT/ICD | 首次诊断日期为索引日；病因学分型 |
| 合并症 | RSC 电子病历 | SNOMED CT/ICD | 索引日前的记录 |
| 行为因素 | RSC 电子病历 | SNOMED CT | 吸烟状态、BMI |
| 既往接种史 | RSC 接种记录 | 药物/疫苗代码 | 是否接种过流感疫苗 |
| 社会经济/地域 | IMD/ONS | IMD 十分位、城乡分类 | 注册地映射到 IMD 分组和城乡属性 |

- 数据库描述
  - 名称：Oxford–Royal College of General Practitioners Research & Surveillance Centre (RSC)
  - 所有者：牛津大学，英国皇家全科医师学院 (RCGP)
  - 覆盖期：2006 年起，持续更新
  - 数据代表性：涵盖英格兰和威尔士 >80 家全科诊所，数百万注册人口，具有全国代表性
  - 数据质量：标准化录入，定期质量控制和审计，接种日期记录精确
  - 局限性：部分变量缺失（如族裔、吸烟强度、BMI）；女性和少数族裔人群可能代表性不足

---
3. 统计学方法
- 数据管理
  - 数据伪匿名化处理，使用统一代码本从 CMR 提取
  - 数据清洗与质控流程：包括一致性检查、缺失值审查
  - 统计分析软件：R（使用最新稳定版本）

---
- 数据分析计划
  - 描述性分析：
    - 连续变量：均值、标准差、中位数、四分位数
    - 分类变量：频数与百分比
    - 组间比较：卡方检验或合适的参数/非参数方法
  - 核心模型：
    - 多状态生存模型（四状态：CLD 诊断 → 首剂 → 二剂；死亡为竞争风险吸收状态）
    - 使用 R 的 msm 包 或同类工具进行拟合
  - 混杂控制：
    - 在模型中纳入年龄、性别、族裔、社会经济、城乡属性、吸烟状态、合并症、肝病病因学等协变量
    - 死亡作为竞争风险在模型结构中处理，而非独立结局
  - 缺失数据处理：
    - <5% 缺失时并入参照组
- 5% 缺失时设置“缺失”类别
    - 同时进行完全病例敏感性分析
  - 亚组/交互分析：
    - 按年龄分组（如 <40 岁、40–64 岁、≥65 岁）
    - 按肝病病因学分层（病毒性 vs 非病毒性）
    - 按社会经济水平、城乡属性、吸烟状态
    - 必要时探索交互作用
  - 敏感性分析：
    - 完全病例分析
    - 排除特定人群（如 MASLD）
    - 限定 ≥65 岁人群
    - 变更变量分类方法以检验稳健性
  - 研究类型特定方法（队列研究）：
    - 对失访进行右删失处理
    - 队列定义为研究期内首次 CLD 诊断个体
  - 多重性调整：
    - 若有多重比较，使用 Benjamini–Hochberg 方法控制假发现率（FDR）

Example 2:
Input: 
{input_2}
Output:
1. 变量
*暴露变量*
| 暴露变量 | 定义与测量 |
|---------|-----------|
| 治疗方式 | 化疗、免疫治疗 (ICI)、靶向治疗 (EGFR-TKI、ALK-TKI 等)、手术、放疗、姑息治疗 |
| 治疗组合 | 单药或联合方案 (免疫+化疗，免疫+靶向，靶向+化疗等) |
| 治疗日期 | 各治疗线的起止日期 |
| 放疗暴露 | 是否有纵隔/胸部放疗 (是/否)，记录日期和类型 |
| 吸烟史 | 从不、既往、当前，记录包年数 |
    
*结局变量*
| 结局变量 | 定义与测量 |
|---------|-----------|
| SPC 发生 | 病理学确诊，独立于首发肿瘤的新原发癌 |
| SPC 时间 | 索引日至 SPC 诊断的间隔时间 |
| SPC 类型 | 部位分类 (膀胱、结直肠、前列腺、肺、头颈、乳腺等)，使用 ICD 编码 |
| 死亡 | 全因死亡，记录日期 |

人口学与基线特征
- 年龄、性别、种族
- ECOG PS
- 个人肿瘤史
- 家族肿瘤史
- 肿瘤组织学类型
- 临床分期

---
协变量/混杂因素
吸烟情况、年龄、性别、组织学类型、肿瘤分期、放疗史、既往肿瘤史、家族肿瘤史
效应修饰因素
- 吸烟状态（可能既是混杂因素，也可能调节治疗与 SPC 风险关系）
- 组织学类型（NSCLC vs. SCLC）

---
2. 数据来源
- 来源类型：西班牙胸部肿瘤登记（TTR）
- 医院病历系统
- 病理报告（SPC 确证）
- 放疗记录
- 数据库描述
  - 建立时间：2006 年
  - 覆盖范围：全国 >80 家医院
  - 数据质量：统一录入标准，定期质控与审核
  - 潜在局限：部分变量可能缺失（如吸烟包年数、分子检测信息）；女性患者比例相对偏低

---
3. 统计方法
- 数据管理：EDC 系统统一录入，数据脱敏，严格质控
- 描述性分析：连续变量（均值、标准差、中位数、四分位间距），分类变量（频数、百分比）
- 混杂控制：多变量回归；必要时使用倾向评分
- 缺失值处理：多重插补，敏感性分析
- 亚组/交互分析：按组织学、吸烟、性别、年龄分组；分析交互效应
- 敏感性分析：不同 SPC 定义，限制随访 ≥2 年患者
- 失访处理：事件时间方法中按最后随访删失
- 多重性调整：Benjamini–Hochberg 法控制假发现率（FDR）


Example 3:
Input: 
{input_3}
Output:
1. 变量（Variables）
• 暴露变量（Exposure Variables）
| 暴露变量 | 定义 | 测量方式 |
|---------|------|----------|
| CMC OA状态 | 是否由临床医生确诊为终末期CMCOA | 临床诊断 + X光影像（Eaton分级、Hand OA Index） |
| 肌肉活动 | 手部及前臂相关肌群的电生理活动模式 | 表面与肌内EMG，采集9块拇指相关肌肉及部分前臂肌肉 |
| 关节运动学与稳定性 | 拇指与腕关节运动幅度、关节接触力、稳定性 | Vicon运动捕捉系统 + 定制力传感器 |
| 运动诱发性疼痛 | 任务前/中/后的疼痛感受 | 视觉模拟量表(VAS) |

• 结局变量（Outcome Variables）
| 结局变量 | 定义 | 测量方式 |
|---------|------|----------|
| 实验性疼痛 (QST) | 个体对不同刺激的疼痛敏感性 | TSA 1热/冷痛分析仪、von Frey单丝、手持压力仪、MediPin |
| 临床疼痛 | 主观疼痛严重度、部位、干扰程度 | GCPS、BPI、AUSCAN、OPTIMIZE问卷 |
| 心理学指标 | 焦虑、抑郁、应对方式、生活满意度 | PROMIS、CES-D、BDI、PSS、MoCA、CSQ-R、SWLS、LOT-R、PANAS |
| 功能结局 | 手部精细与粗大功能、力量、活动范围 | 拇指活动度测试、捏力/握力测试、Jebsen手功能测试、DASH |
| 疾病严重度 | 影像学分级 | X光片 (Robert位+侧位)，Eaton分级与Hand OA Index |

---
• 人口学与基线特征（Patient demographics/characteristics）
- 年龄、性别（仅女性）
- 身高、体重、肢体长度
- 既往病史与用药史
- 疼痛史与功能史

---
• 协变量/混杂因素（Covariates/Confounders）
- 年龄、BMI
- 心理状态（焦虑/抑郁）
- 疼痛表型（QST结果）
- 功能评分（DASH、Jebsen）

---
• 效应修饰因子（Effect Modifiers）
- 疼痛敏化表型（中枢 vs 外周）
- 手功能水平（力量、活动范围）
- 影像学严重度

---
2. 数据来源（Data Sources）
• 来源类型（Source Type）
- 实验室数据：运动捕捉、肌电图（EMG）、QST
- 临床数据：病史、体格检查、疼痛与心理学问卷
- 影像学数据：拇指X光片


• 各变量对应来源（Details per Variable）
| 变量 | 数据来源 | 方法/工具 | 编码/标准 |
|------|----------|-----------|-----------|
| CMC OA状态 | 临床诊断、X光影像 | 医生诊断 + Eaton分级 | 临床诊断标准 |
| 肌肉活动 | 实验室 | 表面/肌内EMG，Vicon系统 | SENIAM/ISEK指南 |
| 运动学与稳定性 | 实验室 | 12摄像头Vicon运动捕捉 + 力传感器 | 国际生物力学学会标准 |
| 疼痛敏感性 | 实验室 | TSA 1热/冷刺激、von Frey单丝、压力仪 | 标准化QST流程 |
| 临床疼痛 | 自填问卷 | GCPS、BPI、AUSCAN | 已验证量表 |
| 心理学指标 | 自填问卷 | PROMIS、CES-D、BDI、PSS等 | 心理学标准量表 |
| 手功能 | 实验室 + 问卷 | Jebsen测试、DASH、握力/捏力仪 | 功能学标准 |
| 影像学 | 医院影像中心 | 拇指X光 (Robert位+侧位) | Eaton分级 |


• 数据库描述（Database Description）
- 数据库名称：UF REDCap & 实验室HIPAA合规服务器
- 覆盖范围：受试者招募至实验完成
- 质量控制：
  - 设备校准与标准化
  - 研究人员培训与重复测量
  - 双人核对录入
- 局限性：横断面数据仅能揭示相关性；对照组可能存在影像学退变

3. 统计学方法（Statistical Methods）
- 数据管理（Data management）
  - 所有数据将存储于佛罗里达大学的 HIPAA 合规服务器和 REDCap 数据库，仅限获批研究人员访问。
  - 数据采用匿名编码，受试者识别信息与研究数据分开保存。
  - 数据分析使用 SPSS/SAS/R（具体软件待补充），结合 Vicon 运动捕捉与 Delysis Trigno EMG 专用软件。
- 数据分析（Data analysis）
  - 描述性分析：计算人口学和基线变量的均值、标准差和频率。
  - 组间比较：采用单因素方差分析（ANOVA）或非参数检验比较三组（CMC OA组、年龄匹配对照组、年轻健康对照组）差异。
  - 混杂因素控制：使用多元回归模型（线性/逻辑回归），调整年龄、BMI、心理因素等混杂变量。
  - 缺失数据处理：
    - 缺失比例小：完全案例分析
    - 缺失比例大：多重插补
  - 亚组分析与交互作用：
    - 疼痛表型（中枢敏化 vs 外周敏化）
    - 疼痛严重度与功能障碍程度的关系
  - 敏感性分析：排除存在轻度影像学退变的对照组，检验结果稳健性。
- 研究类型特异方法（Study-type-specific methods）
  - 横断面研究：采用分层和调整方法，保证不同年龄组间可比性。
  - 病例-对照与随访：不适用（本研究为横断面设计）。
  - 多重性调整（Multiplicity Adjustment）：对于多指标比较，采用 Bonferroni 或 FDR 方法控制第一类错误率。

"""

few_shot_cases_d = """
Example 1:
Input: 
{input_1}
Output:
1. 研究方法的局限性：作为观察性研究，即便调整多个协变量，仍可能存在未测量或不可见的混杂因素。
  1. 选择偏倚：RSC 网络虽具代表性，但仍可能在性别、族裔、社会经济群体中存在不均衡。
  2. 暴露错分：慢性肝病病因学和合并症依赖电子病历编码，可能存在误分类。
  3. 结局错分：部分接种可能在旅行门诊等机构完成而未被记录，导致接种状态低估。
  4. 缺失数据：如族裔、BMI、吸烟强度等信息缺失率较高，缺失机制可能不完全随机。
  5. 系统外部因素：如疫苗供应、医务人员建议、患者信任度等外部因素未能纳入模型。
  6. 推广性：结果主要适用于英国初级保健体系，推广至其他国家需谨慎。

Example 2:
Input: 
{input_2}
Output:
1. 研究方法局限性
  1. 观察性设计 → 存在残余混杂
  2. 患者选择偏倚（尽管 TTR 已验证具有代表性）
  3. 暴露错分（病历记录不全）
  4. 结局错分（部分 SPC 漏诊）
  5. 失访风险（影响长期 SPC 监测）
  6. 外部推广性有限（结果可能不适用于其他医疗体系）
  7. 数据缺失（如吸烟强度、分子检测数据）

Example 3:
Input: 
{input_3}
Output:
1. 研究方法学局限性（Limitations of the research methods）
- 混杂因素
 心理状态（如焦虑/抑郁）、日常活动水平和疼痛应对方式可能影响结果，难以完全控制。
- 选择偏倚
 CMC OA患者主要来源于单一医疗中心（佛罗里达大学矫形运动医学门诊），样本代表性有限。
- 测量偏倚
 疼痛敏感性（QST）部分依赖主观自报，可能受受试者期望或实验环境影响。
- 暴露误分类
 对照组中可能存在无症状但影像学上有退变者，降低分组纯度。
- 因果推断限制
 横断面研究仅能揭示变量间的相关性，无法推断因果关系。
- 样本量限制
 本研究计划招募60例（每组20例），样本量计算基于捏力差异，其他变量统计效能有限；结果需在大样本研究中验证。
"""

# few_shot_cases_a_creative = """
# """

# few_shot_cases_b_creative = """
# """

# few_shot_cases_c_creative = """
# """

# few_shot_cases_d_creative = """
# """