import traceback
from typing import List

from utils.clinical_utils.get_local_clinical_trial_result import get_local_clinical_trial_result, fill_events_until_token_limit_v1
from utils.core.timer import async_timer


async def compare_clinical_trial_results(
    indication_name:List[str]=[],
    lead_company:List[str]=[],
    company:List[str]=[],
    target:dict={},
    drug_name:dict={},
    drug_modality:dict={},
    drug_feature:dict={},
    route_of_administration:dict={},
    nctids:List[str]=[],
    gender:str="",
    current_status:List[str]=[],
    phase:List[str]=[],
    locations:dict={},
    top_n:int=10,
    page:int=1,
    id:List[int]=[],
    include_events:bool=False,
    **kwargs
    ):
    kwargs = {
        'indication_name': indication_name,
        'lead_company': lead_company or company, #TODO remove lead_compay use company finaly
        'target': target,
        'drug_names': drug_name,
        'drug_modality': drug_modality,
        'drug_feature': drug_feature,
        'route_of_administration': route_of_administration,
        'nctids': nctids,
        'gender': gender,
        'current_status': current_status,
        'phase': phase,
        'locations': locations,
        'top_n': top_n,
        'page': page,
        'id': id,
        'include_events': include_events,
        **kwargs
    }
    results, total_count = await get_local_clinical_trial_result(type='comparison', **kwargs)
    for result in results:
        if not result['nct_id'] and result['primary_id']:
            result['nct_id'] = result['primary_id']
        if not result['official_title']:
            result['official_title'] = 'Not disclosed'
        if result['label'] == 'not_enough_info':
            result['label'] = ''
    try:
        if include_events:
            results = await fill_events_until_token_limit_v1(results)        
    except Exception as e:
        print(e)
    if total_count > 10000:
        total_count = 10000
    if total_count == 1 and type(id) == str:
        return results
    return {"results": results, "total_count": total_count}
    # return results