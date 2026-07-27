import asyncio
import re
from typing import List

from utils.clinical_utils.gen_dose import gen_dose
from utils.clinical_utils.get_local_clinical_trial_result import \
    get_local_clinical_trial_result
from utils.sql_client import get_connection


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
    top_n:int=10):

    with get_connection() as conn:
        results = await get_local_clinical_trial_result(
            conn,
            top_n,
            indication_name,
            lead_company,
            target,
            drug_name,
            nctids,
            gender,
            current_status,
            phase,
            locations,
            type="design")
        doses = await asyncio.gather(*[gen_dose(result["dose"]) for result in results])
        for i, result in enumerate(results):
            result["endpoints"] = ""
            if result["primary_endpoints"]:
                result["endpoints"] += f"#### Primary endpoints:\n {result['primary_endpoints']}\n"
            if result["secondary_endpoints"]:
                result["endpoints"] += f"#### Secondary endpoints:\n {result['secondary_endpoints']}\n"
            result["dose"] = doses[i]
            result["start_date"] = {"date": result["start_date"], "type": result["start_date_type"]}
            result["completion_date"] = {"date": result["completion_date"], "type": result["completion_date_type"]}
            if result["actual_enrollment"]:
                result["enrollment"] = {"count": result["actual_enrollment"], "type": "ACTUAL"}
            elif result["anticipated_enrollment"]:
                result["enrollment"] = {"count": result["anticipated_enrollment"], "type": "ESTIMATED"}
            else:
                result["enrollment"] = None
            trial_type = result.get("trial_type", "")
            if re.search(r"double[-| ]blind", trial_type, re.IGNORECASE):
                result["blind method"] = "Double Blind"
            else:
                result["blind method"] = "None"
            if re.search(r"non[-| ]randomized", trial_type, re.IGNORECASE):
                result["randomized"] = "Non-Randomized"
            elif re.search(r"randomized", trial_type, re.IGNORECASE):
                result["randomized"] = "Randomized"
            else:
                result["randomized"] = "Unknown"
            result["locations"] = result.pop("location_details")
            result.pop("primary_endpoints")
            result.pop("secondary_endpoints")
            result.pop("last_updated")
            result.pop("trial_type")
            result.pop("start_date_type")
            result.pop("completion_date_type")
            result.pop("actual_enrollment")
            result.pop("anticipated_enrollment")
        return results

