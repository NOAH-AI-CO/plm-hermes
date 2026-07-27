from typing import List, Optional, Type
from pydantic import BaseModel, Field
from tools.core.base_tool import BaseTool
from tools.human_in_loop.planning.enums import tools, phases, drug_features, drug_modality, route_of_administration, gender, current_status, catalyst_types
from tools.human_in_loop.planning.schema import *

class SequentialToolSchemaCn(BaseModel):
    tool: str = Field(description="""
    在序列中使用的工具，用于回答用户提示。
    """, examples=tools)
    # goal: str = Field(description="工具的目标", json_schema_extra={"optional": True})
    reason: str = Field(description="工具选择背后的原因，这个工具如何使用当前工具和先前工具结果的数据", json_schema_extra={"optional": True})
    query_params: str = Field(description="传递给工具的参数或关于参数的解释，可以是字符串或JSON字符串", json_schema_extra={"optional": True})

class PlanningInputSchemaCn(PlanningInputSchema):
    planned_sequence: List[SequentialToolSchemaCn] = Field(description="用来回答用户的问题的一系列工具使用步骤")
    # translated_keywords: List[Translation] = Field(description="List of translated non-english keywords, used to translate the keywords to english", json_schema_extra={"optional": True})
    
# class ReplanningInputSchemaCn(ReplanningInputSchema):
#     planned_sequence: List[SequentialToolSchemaCn] = Field(description=replanning_input_prompt_cn)
#     translated_keywords: List[Translation] = Field(description="List of translated non-english keywords, used to translate the keywords to english", json_schema_extra={"optional": True})
    
class CommonMedicalQuerySchemaCn(CommonMedicalQuerySchema):
    indication_name: List[str] = Field(description="List of english indication names (translate to english if in other languages), include alt names of same indication to increase query success rate", json_schema_extra={"optional": True})
    target: List[str] = Field(description="Target names in english", json_schema_extra={"optional": True})
    phase: List[str] = Field(description="List of phases", json_schema_extra={"optional": True}, examples=phases)
    drug_modality: List[str] = Field(description="Molecular type of drug, e.g., large molecule, small molecule, ADC; limited to around a dozen predefined values directly provided to LLM.", examples=drug_modality, json_schema_extra={"optional": True})
    drug_feature: List[str] = Field(description="Drug characteristics, e.g., 505b2; limited to around a dozen predefined values directly provided to LLM.", examples=drug_features, json_schema_extra={"optional": True})
    route_of_administration: List[str] = Field(description="Administration method, e.g., oral, injection; limited to around a dozen predefined values directly provided to LLM.", examples=route_of_administration, json_schema_extra={"optional": True})

class ClinicalResultsInputSchemaCn(CommonMedicalQuerySchemaCn):
    drug_name: List[str] = Field(description="Name of the drug (including generic name, trade name, and development code) in english and logical operation of query", json_schema_extra={"optional": True})
    lead_company: List[str] = Field(description="Company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    nctids: List[str] = Field(description="Clinical trial identifier (e.g., NCT00090233).", json_schema_extra={"optional": True})
    locations: List[str] = Field(description="Locations (country, english) and logical operation of query", json_schema_extra={"optional": True})
    apply_not_fields: List[str] = Field(description="List of fields to apply NOT operation on", examples=clinical_results_field_list, json_schema_extra={"optional": True})
    
class DrugCompetitionLandscapeInputSchemaCn(CommonMedicalQuerySchemaCn):
    drug_names: List[str] = Field(description="Name of the drug (including generic name, trade name, and development code) in english and logical operation of query", json_schema_extra={"optional": True})
    company: List[str] = Field(description="Company responsible for the drug. The company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    location: List[str] = Field(description="List of locations (country, english)", json_schema_extra={"optional": True})
    phase: List[str] = Field(description="Development phase of the drug; limited to around a dozen predefined values directly provided to LLM.", json_schema_extra={"optional": True}, examples=phases_2)
    apply_not_fields: List[str] = Field(description="List of fields to apply NOT operation on", examples=drug_competition_landscape_field_list, json_schema_extra={"optional": True})
    
# class NCCNGuidelinesInputSchemaCn(BaseModel):
#     question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})
    
class GeneralInferenceInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})
    
class MedicalSearchInputSchemaCn(MedicalSearchInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})
    
class WebSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})

class FinanceSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})

class PatentSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})

class NewsSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题", json_schema_extra={"optional": False})

class DrugManualSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题（药品说明书检索请包含药品名称或主题，如适应症、用法用量、禁忌等）", json_schema_extra={"optional": False})

class ClinicalGuidelineSearchInputSchemaCn(GeneralInferenceInputSchema):
    question: str = Field(description="代表用户提出的问题（临床指南检索请包含疾病、适应症、指南名称或主题，如 HR+ HER2- 乳腺癌、肺癌一线治疗等）", json_schema_extra={"optional": False})

# class AshAbstractsInputSchemaCn(AshAbstractsInputSchema):
#     question: str = Field(description="获取查询结果后代表用户提出的问题", json_schema_extra={"optional": True})
#     keyword: str = Field(description="Keyword to use in query, searches in both title and full text")
#     phases: List[str] = Field(description="List of phases", json_schema_extra={"optional": True}, examples=phases)

class CatalystSearchInputSchemaCn(CatalystSearchInputSchema):
    phases: List[str] = Field(description="List of phases", json_schema_extra={"optional": True}, examples=phases_2)
    indication_name: List[str] = Field(description="Indication names in english", json_schema_extra={"optional": True})
    company: List[str] = Field(description="Company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    drug_name: List[str] = Field(description="Drug names in english ", json_schema_extra={"optional": True})
    catalyst_type: List[str] = Field(description="Catalyst types, can be from ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update']", json_schema_extra={"optional": True}, examples=catalyst_types)

class SandboxExecutionInputSchemaCn(SandboxExecutionInputSchema):
    question: str = Field(description="代表用户提出的任务描述（沙箱代码执行任务，包括需要计算、分析或处理的数据/文件详情）", json_schema_extra={"optional": False})
