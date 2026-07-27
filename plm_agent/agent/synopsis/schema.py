from difflib import get_close_matches
from typing import List, Literal, Optional, Type
from pydantic import BaseModel, Field, field_validator

from agent.synopsis.enums import *


def _fuzzy_normalize(value: str, allowed: list[str], cutoff: float = 0.6) -> str:
    """Return the closest allowed value, or raise ValueError if no close match exists."""
    if value in allowed:
        return value
    # Try case-insensitive exact match first
    upper = value.upper().replace("-", "_").replace(" ", "_")
    for a in allowed:
        if a.upper().replace("-", "_").replace(" ", "_") == upper:
            return a
    matches = get_close_matches(value, allowed, n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    raise ValueError(f"{value!r} is not a valid value. Must be one of: {allowed}")

class SynopsisTranslationSchema(BaseModel):
    translated_indication: str = Field(description="English indication name (must be in english, translate into english if not)")
    # phase: List[str] = Field(description="Phase", json_schema_extra={"optional": True}, examples=phases)
    # treatment_line: List[str] = Field(description="Treatment line", json_schema_extra={"optional": True}, examples=treatment_lines)
    # health_condition: List[str] = Field(description="Health condition", json_schema_extra={"optional": True}, examples=health_conditions)
    # sex: Optional[str] = Field(description="Patient sex", json_schema_extra={"optional": True}, examples=sex)
    # age: Optional[str] = Field(description="Patient age", json_schema_extra={"optional": True}, examples=ages)
    # intervention_model: List[str] = Field(description="Intervention models", json_schema_extra={"optional": True}, examples=intervention_models)
    # masking: List[str] = Field(description="Masking type", json_schema_extra={"optional": True}, examples=masking_types)

class IndicationExpansionSchema(BaseModel):
    indication_list: List[str] = Field(description="List of indications to increase search coverage")
    
class AgeGroupMatchingSchema(BaseModel):
    age_group: str = Field(description="Age group that best describes user provided age term", examples=['CHILD', 'ADULT', 'OLDER_ADULT'])


# ── RWS Synopsis structured output schema ──────────────────────────────────────

class RWSBasicInfo(BaseModel):
    study_title: str = Field(description="研究标题（完整标题）")
    principal_authors: str = Field(description="主要作者姓名和单位，若未指定请填写'待填写'")
    study_start_date: Optional[str] = Field(default=None, description="计划研究开始日期，如 2022-01-01；未指定时为 null")
    study_end_date: Optional[str] = Field(default=None, description="计划研究结束日期，如 2024-12-31；未指定时为 null")
    intervention_exposure: str = Field(description="干预/暴露的简要描述")


class RWSBackground(BaseModel):
    background: str = Field(description="研究背景，包含疾病流行病学、现有治疗格局、真实世界证据缺口等内容")
    rationale: str = Field(description="开展本研究的合理性/科学依据")
    references: List[str] = Field(description="相关参考文献列表，每条为一个字符串")


class RWSTimeline(BaseModel):
    study_period: str = Field(description="整体研究期间，如 '2018年1月-2023年12月'")
    identification_period: str = Field(description="用于识别目标人群的时间范围")
    index_date_definition: str = Field(description="索引日期（Index Date）的定义")
    baseline_period: str = Field(description="基线期的定义与范围")
    follow_up_period: str = Field(description="观察/随访期的定义与范围")


class RWSStudyDesign(BaseModel):
    design_type: str = Field(description="研究设计类型，如'基于真实世界数据库的回顾性队列研究'")
    study_type: str = Field(description="研究类型，如'真实世界观察性研究 / 真实世界药物效果研究'")
    exposure_comparison_groups: List[str] = Field(description="暴露/比较分组列表，每个元素为一个分组名称")
    primary_endpoint: str = Field(description="主要终点的定义与测量方式")
    secondary_endpoints: Optional[str] = Field(default=None, description="次要终点描述；若无则为 null")
    primary_measurement_methods: str = Field(description="主要统计测量方法，如'Kaplan-Meier + Cox比例风险模型'")
    timeline: RWSTimeline = Field(description="研究时间设置")


class RWSStudyPopulation(BaseModel):
    inclusion_criteria: List[str] = Field(description="纳入标准列表，每条为一个字符串")
    exclusion_criteria: List[str] = Field(description="排除标准列表，每条为一个字符串")


class RWSVariableItem(BaseModel):
    variable_name: str = Field(description="变量名称")
    data_field: Optional[str] = Field(default=None, description="对应的数据库字段名；若无则为 null")
    definition: str = Field(description="变量的定义和测量方式")


class RWSCovariateGroup(BaseModel):
    covariate_type: str = Field(description="协变量类型，如'协变量'、'核心混杂因素'、'年龄分层'等")
    variables: List[str] = Field(description="该类型下的变量列表")


class RWSEffectModifier(BaseModel):
    modifier_name: str = Field(description="效应修饰因子名称")
    definition: str = Field(description="效应修饰因子的定义与测量方式")


class RWSVariables(BaseModel):
    exposure_variables: List[RWSVariableItem] = Field(description="暴露变量列表")
    outcome_variables: List[RWSVariableItem] = Field(description="结局变量列表")
    demographic_baseline_variables: List[RWSVariableItem] = Field(description="人口统计学和基线特征变量列表")
    covariate_groups: List[RWSCovariateGroup] = Field(description="协变量/混杂因素分组描述")
    effect_modifiers: List[RWSEffectModifier] = Field(description="效应修饰因子列表")


class RWSDataSource(BaseModel):
    source_name: str = Field(description="数据来源名称，如'电子病历系统'")
    description: str = Field(description="该数据来源的用途描述")


class RWSStatisticalMethods(BaseModel):
    data_management: str = Field(description="数据管理与清洗方法概述")
    descriptive_analysis: str = Field(description="描述性统计分析方法")
    primary_outcome_analysis: str = Field(description="主要结局（如rwOS）的估计方法")
    confounding_control: str = Field(description="混杂控制策略，如多因素Cox模型、倾向评分等")
    subgroup_effect_modification: str = Field(description="亚组分析与效应修饰分析方案")
    missing_data_handling: str = Field(description="缺失数据处理策略")
    sensitivity_analyses: List[str] = Field(description="敏感性分析方案列表，每条为一个字符串")


class RWSGlossaryItem(BaseModel):
    abbreviation: str = Field(description="缩略词，如 MRC1、TAM、IHC")
    full_name: str = Field(description="缩略词对应的英文全称")
    explanation: str = Field(description="中文释义")


class RWSAppendix(BaseModel):
    glossary: List[RWSGlossaryItem] = Field(description="术语表列表")
    references: List[str] = Field(description="参考文献列表，每条为一个字符串，保留原始格式")
    download_url: Optional[str] = Field(default=None, description="文档下载链接；若无则为 null")


class RWSSynopsisSchema(BaseModel):
    """
    临床/真实世界研究方案（Synopsis）的结构化输出 Schema。
    涵盖基本信息、背景、研究设计、研究人群、变量、数据来源、统计方法、局限性、附录共九个部分。
    """
    basic_info: RWSBasicInfo = Field(description="第1节：基本信息")
    background_rationale: RWSBackground = Field(description="第2节：背景与理论依据")
    study_design: RWSStudyDesign = Field(description="第3节：研究设计概述")
    study_population: RWSStudyPopulation = Field(description="第4节：研究人群（纳入/排除标准）")
    variables: RWSVariables = Field(description="第5节：变量定义")
    data_sources: List[RWSDataSource] = Field(description="第6节：数据来源列表")
    statistical_methods: RWSStatisticalMethods = Field(description="第7节：统计方法")
    limitations: List[str] = Field(description="第8节：研究方法的局限性列表，每条为一个字符串")
    appendix: Optional[RWSAppendix] = Field(default=None, description="第9节：附录（术语表、参考文献、下载链接）；若文档无附录则为 null")

_STUDY_TYPES = ["EXPANDED_ACCESS", "INTERVENTIONAL", "OBSERVATIONAL"]
_AGES = ["CHILD", "ADULT", "OLDER_ADULT"]
_SEXES = ["FEMALE", "MALE", "ALL"]
_PHASES = ["1", "1/2", "2", "2/3", "3", "4", "not_123"]
_INTERVENTION_MODELS = ["SINGLE_GROUP", "PARALLEL", "CROSSOVER", "FACTORIAL", "SEQUENTIAL"]
_OBSERVATIONAL_MODELS = [
    "COHORT", "CASE_CONTROL", "CASE_ONLY", "OTHER", "ECOLOGIC_OR_COMMUNITY",
    "CASE_CROSSOVER", "DEFINED_POPULATION", "FAMILY_BASED", "NATURAL_HISTORY",
]
_TIME_PERSPECTIVES = ["PROSPECTIVE", "RETROSPECTIVE", "CROSS_SECTIONAL", "OTHER"]
_MASKINGS = ["NONE", "SINGLE", "DOUBLE", "TRIPLE", "QUADRUPLE"]
_TREATMENT_LINES = ["first-line", "second-line", "later-line", "rr"]
_HEALTH_CONDITIONS = [
    "Healthy Volunteers", "HIV-positive", "Diabetic", "Hypertensive",
    "Obese", "Hepatic/Renal Impairment", "Liver/Kidney Dysfunction",
]


class SynopsisFormInput(BaseModel):
    study_type: Literal["EXPANDED_ACCESS", "INTERVENTIONAL", "OBSERVATIONAL"] = Field(
        ..., description="One of: EXPANDED_ACCESS, INTERVENTIONAL, OBSERVATIONAL"
    )
    researchObjective: str = Field(..., description="Research objective text")
    indication: str = Field(..., description="disease or condition")
    age: Literal["CHILD", "ADULT", "OLDER_ADULT"] = Field(
        ..., description="One of: CHILD, ADULT, OLDER_ADULT"
    )
    sex: Literal["FEMALE", "MALE", "ALL"] = Field(
        ..., description="One of: FEMALE, MALE, ALL"
    )
    outcome: List[str] = Field(..., description="List of outcomes. Must have at least 1 item.")
    phase: Optional[Literal["1", "1/2", "2", "2/3", "3", "4", "not_123"]] = Field(
        None, description="One of: 1, 1/2, 2, 2/3, 3, 4, not_123"
    )
    intervention_model: Optional[
        Literal["SINGLE_GROUP", "PARALLEL", "CROSSOVER", "FACTORIAL", "SEQUENTIAL"]
    ] = Field(None, description="One of: SINGLE_GROUP, PARALLEL, CROSSOVER, FACTORIAL, SEQUENTIAL")
    observational_model: Optional[
        Literal[
            "COHORT", "CASE_CONTROL", "CASE_ONLY", "OTHER", "ECOLOGIC_OR_COMMUNITY",
            "CASE_CROSSOVER", "DEFINED_POPULATION", "FAMILY_BASED", "NATURAL_HISTORY",
        ]
    ] = Field(None, description="One of: COHORT, CASE_CONTROL, CASE_ONLY, OTHER, ECOLOGIC_OR_COMMUNITY, CASE_CROSSOVER, DEFINED_POPULATION, FAMILY_BASED, NATURAL_HISTORY")
    time_perspective: Optional[
        Literal["PROSPECTIVE", "RETROSPECTIVE", "CROSS_SECTIONAL", "OTHER"]
    ] = Field(None, description="One of: PROSPECTIVE, RETROSPECTIVE, CROSS_SECTIONAL, OTHER")
    masking: Optional[Literal["NONE", "SINGLE", "DOUBLE", "TRIPLE", "QUADRUPLE"]] = Field(
        None, description="One of: NONE, SINGLE, DOUBLE, TRIPLE, QUADRUPLE"
    )
    treatment_line: Optional[Literal["first-line", "second-line", "later-line", "rr"]] = Field(
        None, description="One of: first-line, second-line, later-line, rr"
    )
    health_condition: Optional[
        Literal[
            "Healthy Volunteers", "HIV-positive", "Diabetic", "Hypertensive",
            "Obese", "Hepatic/Renal Impairment", "Liver/Kidney Dysfunction",
        ]
    ] = Field(None, description="One of: Healthy Volunteers, HIV-positive, Diabetic, Hypertensive, Obese, Hepatic/Renal Impairment, Liver/Kidney Dysfunction")

    # ── Fuzzy normalization: run before Literal validation ────────────────────

    @field_validator("study_type", mode="before")
    @classmethod
    def normalize_study_type(cls, v: str) -> str:
        return _fuzzy_normalize(str(v), _STUDY_TYPES)

    @field_validator("age", mode="before")
    @classmethod
    def normalize_age(cls, v: str) -> str:
        return _fuzzy_normalize(str(v), _AGES)

    @field_validator("sex", mode="before")
    @classmethod
    def normalize_sex(cls, v: str) -> str:
        return _fuzzy_normalize(str(v), _SEXES)

    @field_validator("phase", mode="before")
    @classmethod
    def normalize_phase(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _PHASES)

    @field_validator("intervention_model", mode="before")
    @classmethod
    def normalize_intervention_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _INTERVENTION_MODELS)

    @field_validator("observational_model", mode="before")
    @classmethod
    def normalize_observational_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _OBSERVATIONAL_MODELS)

    @field_validator("time_perspective", mode="before")
    @classmethod
    def normalize_time_perspective(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _TIME_PERSPECTIVES)

    @field_validator("masking", mode="before")
    @classmethod
    def normalize_masking(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _MASKINGS)

    @field_validator("treatment_line", mode="before")
    @classmethod
    def normalize_treatment_line(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _TREATMENT_LINES)

    @field_validator("health_condition", mode="before")
    @classmethod
    def normalize_health_condition(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _fuzzy_normalize(str(v), _HEALTH_CONDITIONS)
