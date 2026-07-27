from llm.azure_models import GPT4oWorkflow
from json_repair import repair_json

from utils.retrievers.typesense_retriever import search_one_column, get_client

async def text_to_param(query: str):
    sys_prompt = """You are a clinical trial expert. Your task is to extract all the arguments of the function clinical_trial_results and the following question according to user's request. return in json format.

def clinical_trial_results(
    indication_name:dict={},
    lead_company:List[str]=[],
    target:dict={},
    drug_name:dict={},
    nctids:List[str]=[],
    gender:str="",
    current_status:List[str]=[],
    phase:List[str]=[],
    locations:dict={},
)
note: dict type is like {"data": ["FT-522"], "logic": "or"}, where data is a list of strings and logic is "or" or "and"

example:
query: Search all phase 3 results for obesity drugs and tell me which drug is the best-in-disease
return: {"args": {"phase": ["III"], "indication_name": {"data": ["obesity"], "logic": "or"}}, "question": "which drug is the best-in-disease"}
"""
    model = GPT4oWorkflow()
    response = await model(sys_prompt, query)
    ret = eval(repair_json(response.content))
    client = get_client()
    map_dict = {"indication_name": "indication", "target": "target", "lead_company": "company"}
    for key in ["indication_name", "target", "lead_company"]:
        if key in ret["args"]:
            new_data = []
            for item in ret["args"][key]["data"]:
                search_result = search_one_column(client=client, name=map_dict[key], query=item, num_typos=1)
                if search_result:
                    new_data.append(search_result)
                else:
                    new_data.append(item)
            ret["args"][key]["data"] = new_data
    return ret
