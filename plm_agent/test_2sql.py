import asyncio
import json
from utils.core.get_json_schema import get_openai_json_schema_v2
from tools.human_in_loop.planning.schema import *
from tools.human_in_loop.planning.prompt import *
from llm.azure_models import GPT4o
from utils.clinical_utils.clean_args_typesense import clean_args_typesense

tool_mapping = {
    "NCCN-Guidelines": {"schema": NCCNGuidelinesInputSchema, "prompt": nccn_slot_filling_prompt},
    "General-Inference": {"schema": GeneralInferenceInputSchema, "prompt": general_inference_slot_filling_prompt},
    "Medical-Search": {"schema": MedicalSearchInputSchema, "prompt": medical_search_slot_filling_prompt},
    "Clinical-Trial-Result-Analysis": {"schema": ClinicalResultsInputSchema, "prompt": clinical_trial_results_slot_filling_prompt},
    "Drug-Analysis": {"schema": DrugCompetitionLandscapeInputSchema, "prompt": drug_competition_landscape_slot_filling_prompt},
    # "Summarize-Results": {"schema": SummarizeResultsInputSchema, "prompt": summarize_results_prompt},
}


def slot_fill(tool_name, prompt, llm):
    body = {
        "history_messages": [],
        "images": []
    }
    tool_info = tool_mapping[tool_name]
    body['user_prompt'] = prompt
    if tool_info['prompt']:
        body['sys_prompt'] = tool_info['prompt']
    response_format = get_openai_json_schema_v2(tool_info['schema'])
    response = asyncio.run(llm.call_response(**body, response_format=response_format))
    return response.choices[0].message.content

def test(query: str, slot_name: str):
    res = slot_fill(slot_name, query, GPT4o())
    print("original res", res)
    res = clean_args_typesense(json.loads(res))
    print("cleaned res", res)

test("搜索适应症为NSCLC的PD-1抗体的所有临床结果，并分析哪个药物是最好的治疗NSCLC的PD-1抗体", "Clinical-Trial-Result-Analysis")
test("Search all phase 3 results for obesity drugs and tell me which drug is the best-in-disease", "Clinical-Trial-Result-Analysis")
