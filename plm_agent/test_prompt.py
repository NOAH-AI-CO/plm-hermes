import asyncio
from collections import defaultdict
import json
from typing import List

from json_repair import repair_json

from llm.azure_models import GPT4o
from utils.sql_client import execute_sql


async def gen_llm_result(prompt: str, input: str):
    model = GPT4o()
    sys_prompt = prompt
    user_prompt = input
    result = await model.call_response(sys_prompt, user_prompt, json_mode=True)
    res = {"content": eval(repair_json(result.choices[0].message.content, ensure_ascii=False), {"null":None}), "usage":result.usage.dict()}
    return res

def prepare_testset(nctids: List[str], select_fields: List[str]):
    """
    Prepares a test set by querying the database for specified NCT IDs and selected fields.

    Args:
        nctids (List[str]): A list of NCT IDs to query.
        select_fields (List[str]): A list of field names to select from the database.

    Returns:
        List[dict]: A list of dictionaries, where each dictionary represents a trial
                    with the specified fields as keys and their corresponding values.

    Example:
        nctids = ["NCT01146574", "NCT01163266"]
        select_fields = ["nctid", "dose"]
    """
    select_fields_str = ", ".join(select_fields)
    results = execute_sql("SELECT {} FROM biomedtracker_trials WHERE nctid = ANY(:nctids)".format(select_fields_str), {"nctids": nctids})
    return [dict(zip(select_fields, result)) for result in results]

async def run_testset(testset: List[dict], prompt: str):
    """
    testset: List of dictionaries, each containing 'nctid' and one other key-value pair.
             Example: [
                 {'nctid': 'NCT01146574', 'dose': '130 mg QD'},
                 {'nctid': 'NCT01163266', 'dose': '100 mg BID'}
             ]
    prompt: str, the system prompt to be used for the LLM
    """
    other_key = next(key for key in testset[0].keys() if key != 'nct_id')
    tasks = [gen_llm_result(prompt, test[other_key]) for test in testset]
    results = await asyncio.gather(*tasks)
    aggregated_results = {'content': []}
    usage = defaultdict(int)
    for result in results:
        aggregated_results['content'].append(result['content'])
        usage['completion_tokens'] += result['usage']['completion_tokens']
        usage['prompt_tokens'] += result['usage']['prompt_tokens']
    usage['estimated_cost'] = str((usage['completion_tokens'] * 11 + usage['prompt_tokens'] * 2.75) / 1000000) + ' USD'
    aggregated_results['usage'] = usage
    return aggregated_results

if __name__ == "__main__":
    testset = prepare_testset(["NCT01146574", "NCT01163266"], ["nctid", "dose"])
    prompt = """
    You are a clinical trial expert. You are given a list of arms for a clinical trial.
    You need to generate a summary of the arms. Reply with a json with the following format:
    [{
        "name": "LoDAC (Low Dose Cytarabine)",
        "dose": "130 mg",
        "frequency": "QD",
        "duration": "12 weeks",
        "how": "SC" or "IV"
    }, ...]
    # instructions:
    - use SC or IV to indicate how the drug is given
    - keep empty fields as ""
    """
    results = asyncio.run(run_testset(testset, prompt))
    print(json.dumps(results, indent=2))