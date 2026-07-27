import asyncio
import re
from typing import List
import json
from utils.clinical_utils.gen_dose import gen_dose
from utils.clinical_utils.nih_query import nih_query_clinical_trials


async def clinical_trial_design(
    indication_name:dict={},
    lead_company:List[str]=[],
    target:dict={},
    drug_name:dict={},
    nctids:List[str]=[],
    gender:str="",
    current_status:List[str]=[],
    phase:List[str]=[],
    locations:dict={},
    term:str="",
    top_n:int=10):

    raw_results = nih_query_clinical_trials(
        question=term,
        disease=f" {indication_name['logic'].upper()} ".join(indication_name["data"]) if indication_name else "",
        sponsor=f" OR ".join(lead_company) if lead_company else "",
        drugs=f" {drug_name['logic'].upper()} ".join(drug_name["data"]) if drug_name else "",
        ids=nctids,
        filter_gender=gender,
        filter_status=current_status,
        filter_phases=phase,
        filter_locations=locations["data"] if locations else [],
        pagesize=top_n)
    print(json.dumps(raw_results[0], indent=2))
    async def process_result(result):
        pass
    return
