from typing import List, Optional, Type
from pydantic import BaseModel, Field
from tools.core.base_tool import BaseTool
from tools.human_in_loop.planning.prompt import planning_input_prompt, replanning_input_prompt
from tools.human_in_loop.planning.enums import *

class SequentialToolSchema(BaseModel):
    tool: str = Field(description="""
    Tool to use in a sequence to answer user prompt. 
    """, examples=tools)
    # goal: str = Field(description="The goal of the tool", json_schema_extra={"optional": True})
    reason: str = Field(description="The reasoning behind the tool choice, how this tool uses data from the tool at hand and previous tool results", json_schema_extra={"optional": True})
    query_params: str = Field(description="Parameters to pass to the tool or the description of the parameters, can be a text string or a JSON string, leave empty if not required", json_schema_extra={"optional": True})

class PlanningInputSchema(BaseModel):
    planned_sequence: List[SequentialToolSchema] = Field(description="sequence of tools to use to answer user prompt")
    # translated_keywords: List[Translation] = Field(description="List of translated non-english keywords, used to translate the keywords to english", json_schema_extra={"optional": True})
    
class OutputSummarySchema(BaseModel):
    summary: str = Field(description="Summary of the result of a tool")
    
# class QueryDict(BaseModel):
#     data: List[str] = Field(description="list of strings (english)")
#     logic: str = Field(description="the logical operation to be performed in the query, can be one of and/or", examples=["or", "and"])

# class DrugModalityQueryDict(BaseModel):
#     data: List[str] = Field(description="list of strings", examples=drug_modality)
#     logic: str = Field(description="the logical operation to be performed in the query, can be one of and/or", examples=["or", "and"])

# class DrugFeatureQueryDict(BaseModel):
#     data: List[str] = Field(description="list of strings", examples=drug_features)
#     logic: str = Field(description="the logical operation to be performed in the query, can be one of and/or", examples=["or", "and"])

# class RouteOfAdministrationQueryDict(BaseModel):
#     data: List[str] = Field(description="list of strings", examples=route_of_administration)
#     logic: str = Field(description="the logical operation to be performed in the query, can be one of and/or", examples=["or", "and"])

class CommonMedicalQuerySchema(BaseModel):
    indication_name: List[str] = Field(description="List of english indication names (translate to english if in other languages), include alt names of same indication to increase query success rate", json_schema_extra={"optional": True})
    target: List[str] = Field(description="Target name and logical operation in query (english)", json_schema_extra={"optional": True})
    phase: List[str] = Field(description="List of phases", json_schema_extra={"optional": True}, examples=phases)
    drug_modality: List[str] = Field(description="Molecular type of drug, e.g., large molecule, small molecule, ADC; limited to around a dozen predefined values directly provided to LLM.", examples=drug_modality, json_schema_extra={"optional": True})
    drug_feature: List[str] = Field(description="Drug characteristics, e.g., 505b2; limited to around a dozen predefined values directly provided to LLM.", examples=drug_features, json_schema_extra={"optional": True})
    route_of_administration: List[str] = Field(description="Administration method, e.g., oral, injection; limited to around a dozen predefined values directly provided to LLM.", examples=route_of_administration, json_schema_extra={"optional": True})

class ClinicalResultsInputSchema(CommonMedicalQuerySchema):
    drug_name: List[str] = Field(description="Name of the drug (including generic name, trade name, and development code) in english and logical operation of query", json_schema_extra={"optional": True})
    lead_company: List[str] = Field(description="Company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    nctids: List[str] = Field(description="Clinical trial identifier (e.g., NCT00090233).", json_schema_extra={"optional": True})
    locations: List[str] = Field(description="Locations (country, english) and logical operation of query", json_schema_extra={"optional": True})
    apply_not_fields: List[str] = Field(description="List of fields to apply NOT operation on", examples=clinical_results_field_list_not_apply, json_schema_extra={"optional": True})
    
class DrugCompetitionLandscapeInputSchema(CommonMedicalQuerySchema):
    drug_names: List[str] = Field(description="Name of the drug (including generic name, trade name, and development code) in english and logical operation of query", json_schema_extra={"optional": True})
    company: List[str] = Field(description="Company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    location: List[str] = Field(description="List of locations (country, english)", json_schema_extra={"optional": True})
    phase: List[str] = Field(description="Development phase of the drug; limited to around a dozen predefined values directly provided to LLM", json_schema_extra={"optional": True}, examples=phases_2)
    apply_not_fields: List[str] = Field(description="List of fields to apply NOT operation on", examples=drug_competition_landscape_field_list_not_apply, json_schema_extra={"optional": True})
    
class NCCNGuidelinesInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})
    
class GeneralInferenceInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})
    
class MedicalSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})

class WebSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})

class FinanceSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})

class PatentSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})

class NewsSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages)", json_schema_extra={"optional": False})

class DrugManualSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages). For drug manual search: include drug name(s) or topic (e.g. indications, dosage, contraindications for specific drugs).", json_schema_extra={"optional": False})

class ClinicalGuidelineSearchInputSchema(BaseModel):
    question: str = Field(description="The english question to ask on behalf of the user (translate to english if in other languages). For clinical guideline search: include disease, indication, guideline name or topic (e.g. HR+ HER2- breast cancer, NSCLC first-line).", json_schema_extra={"optional": False})

class CatalystSearchInputSchema(BaseModel):
    phases: List[str] = Field(description="A list of phases", json_schema_extra={"optional": True}, examples=phases_2)
    indication_name: List[str] = Field(description="Indication names in english", json_schema_extra={"optional": True})
    company: List[str] = Field(description="Company names in english (translate to english if in other languages)", json_schema_extra={"optional": True})
    drug_name: List[str] = Field(description="Drug name in english", json_schema_extra={"optional": True})
    catalyst_type: List[str] = Field(description="Catalyst type, can be from ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update']", json_schema_extra={"optional": True}, examples=catalyst_types)
    apply_not_fields: List[str] = Field(description="Catalyst types, can be from ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update']", examples=catalyst_search_field_list_not_apply, json_schema_extra={"optional": True})

class ReflectionSchema(BaseModel):
    additional_steps: List[SequentialToolSchema] = Field(description="The additional steps to append to plan")

class ClinicalTrialResultAnalysisInputSchema(BaseModel):
    question: str = Field(description=f"""The english question to ask on behalf of the user for searching relevant clinical results records from database (translate to english if in other languages).
The question must contains enough details for another agent to do the research. It's ok to use a very long question.
The question should contains indication, target, phase, drug name, company, nctids, locations, drug modality, drug feature, route of administration.
""", json_schema_extra={"optional": False})
    
class DrugAnalysisInputSchema(BaseModel):
    question: str = Field(description=f"""The english question to ask on behalf of the user for searching relevant drug competition landscape records from database (translate to english if in other languages).
The question must contains enough details for another agent to do the research. It's ok to use a very long question.
The question should contains indication, target, phase, drug name, company, nctids, locations, drug modality, drug feature, route of administration.
""", json_schema_extra={"optional": False})
    
class CatalystEventAnalysisInputSchema(BaseModel):
    question: str = Field(description=f"""The english question to ask on behalf of the user for searching relevant catalyst event records from database (translate to english if in other languages).
The question must contains enough details for another agent to do the research. It's ok to use a very long question.
The question should contains phases, indication, company, drug name, catalys type (e.g. ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update'])
""", json_schema_extra={"optional": False})

class IrrelevantParamValue(BaseModel):
    param_name: str = Field(description="The name of the parameter with irrelevant values")
    value: str = Field(description="The irrelevant value identified in the query parameters")

class IrrelevantParamValueList(BaseModel):
    irrelevant_values: List[IrrelevantParamValue] = Field(description="A list of irrelevant values identified in the query parameters, each with the parameter name and the value that is irrelevant")

class DocumentSearchInputSchema(BaseModel):
    question: str = Field(description="""The question to search the from upload attachments in natural language.
The question could be very long or detailed, since this task would be executed by another agent.
Examples:
1. please help me get the xxx details from document1, document2;
2, compare the xxx by document1 and document2;
3, etc.""")

class SandboxExecutionInputSchema(BaseModel):
    question: str = Field(description="""The task description for sandbox code execution in natural language.
Describe what needs to be computed, analyzed, or processed. Include details about:
- What data or files to work with
- What calculations or transformations to perform
- What output format is expected
Examples:
1. Parse the attached Excel file and calculate the average revenue per quarter
2. Download the CSV from the given URL, clean the data, and compute summary statistics
3. Process the PDF report and extract all tables into a structured format
4. Compare numerical data across multiple uploaded documents and compute differences""")