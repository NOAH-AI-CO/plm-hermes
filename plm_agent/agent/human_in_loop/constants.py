from tools.human_in_loop.planning.schema import *
from tools.human_in_loop.planning.schema_cn import *
from tools.human_in_loop.planning.prompt import *
from agent.explore.mindsearch_hitl_agent import (
    MindSearchMedicalHitlAgent, MindSearchNewsHitlAgent,
    MindSearchPatentHitlAgent, MindSearchWebHitlAgent,
    MindSearchDrugManualHitlAgent, MindSearchClinicalGuidelineHitlAgent,
    MindSearchDocumentReadHitlAgent,
    MindSearchFinanceHitlAgent,
    MindSearchSandboxHitlAgent,
)
from agent.explore.mindsearch_pubmed_agent_v2 import MindSearchPubMedAgentV2
# clinical_background = 'Workflow trail sheet result:'
# clinical_background_0 = 'Selected clinical trial result data:'
# drug_background = 'Selected drug data:'
# conference_background = 'Selected conference data:'
# catalyst_background = 'Selected catalyst data:'
background_prefix_map = {}

data_empty_prompt = "Data for this tool is empty. Inform the user that data is empty so the tool cannot be used, but they can try again with different search instructions."
data_empty_prompt_cn = "该工具的数据为空，无法使用。请告知用户数据为空，可以尝试使用不同的搜索指令。"

tool_mapping = {
    "General-Inference": {"schema": GeneralInferenceInputSchema, "schema_cn": GeneralInferenceInputSchemaCn, "prompt": general_inference_slot_filling_prompt},
    "Medical-Search": {"schema": MedicalSearchInputSchema, "schema_cn": MedicalSearchInputSchemaCn, "prompt": medical_search_slot_filling_prompt},
    "Web-Search": {"schema": WebSearchInputSchema, "schema_cn": WebSearchInputSchemaCn, "prompt": web_search_slot_filling_prompt},
    "Clinical-Trial-Result-Analysis": {"schema": ClinicalResultsInputSchema, "schema_cn": ClinicalResultsInputSchemaCn, "prompt": clinical_trial_results_slot_filling_prompt},
    "Drug-Analysis": {"schema": DrugCompetitionLandscapeInputSchema, "schema_cn": DrugCompetitionLandscapeInputSchemaCn, "prompt": drug_competition_landscape_slot_filling_prompt},
    "Catalyst-Event-Analysis": {"schema": CatalystSearchInputSchema, "schema_cn": CatalystSearchInputSchemaCn, "prompt": catalyst_search_slot_filling_prompt},
    "Finance-Search": {"schema": FinanceSearchInputSchema, "schema_cn": FinanceSearchInputSchemaCn, "prompt": finance_search_slot_filling_prompt},
    "Patent-Search": {"schema": PatentSearchInputSchema, "schema_cn": PatentSearchInputSchemaCn, "prompt": patent_search_slot_filling_prompt},
    "News-Search": {"schema": NewsSearchInputSchema, "schema_cn": NewsSearchInputSchemaCn, "prompt": news_search_slot_filling_prompt},
    "Drug-Manual-Search": {"schema": DrugManualSearchInputSchema, "schema_cn": DrugManualSearchInputSchemaCn, "prompt": drug_manual_search_slot_filling_prompt},
    "Clinical-Guideline-Search": {"schema": ClinicalGuidelineSearchInputSchema, "schema_cn": ClinicalGuidelineSearchInputSchemaCn, "prompt": clinical_guideline_search_slot_filling_prompt},
    "Document-Read": {"schema": DocumentSearchInputSchema, "schema_cn": DocumentSearchInputSchema, "prompt": document_search_slot_filling_prompt},
    # "Sandbox-Execution": {"schema": SandboxExecutionInputSchema, "schema_cn": SandboxExecutionInputSchemaCn, "prompt": sandbox_execution_slot_filling_prompt},
}

search_routing = {
    'Medical-Search': (MindSearchMedicalHitlAgent, "mindsearchofficialsite"),
    "Web-Search": (MindSearchWebHitlAgent, "mindsearch"),
    "Finance-Search": (MindSearchFinanceHitlAgent, "mindsearchfinance"),
    "Patent-Search": (MindSearchPatentHitlAgent, "mindsearchpatent"),
    "News-Search": (MindSearchNewsHitlAgent, "mindsearchnews"),
    "Drug-Manual-Search": (MindSearchDrugManualHitlAgent, "mindsearchdrugmanual"),
    "Clinical-Guideline-Search": (MindSearchClinicalGuidelineHitlAgent, "mindsearchclinicalguideline"),
    "Document-Read": (MindSearchDocumentReadHitlAgent, "mindsearchdocumentread"),
    # "Sandbox-Execution": (MindSearchSandboxHitlAgent, "mindsearchsandbox"),
    # "PubMed-Search": (MindSearchPubMedAgentV2, "mindsearchpubmed"),
}
