import json
from typing import List
from datetime import datetime
import re
from sqlalchemy import Connection, text

from utils.sql_client import get_connection
from utils.core.timer import async_timer

from .common import get_drug_ids, generate_conditions_and_params, get_indication_mapped

TOKEN_LIMIT = 10000

@async_timer
async def get_local_clinical_trial_result(
        top_n:int=10,
        page:int=1,
        indication_name:List[str]=[],
        lead_company:List[str]=[],
        target:dict={},
        drug_names:dict={},
        drug_modality:dict={},
        drug_feature:dict={},
        route_of_administration:dict={},
        nctids:List[str]=[],
        gender:str="",
        current_status:List[str]=[],
        phase:List[str]=[],
        locations:dict={},
        id:List[int]=[],
        type:str="comparison",
        include_events:bool=False,
        exact_indication:bool=False,
        fetch_recent:bool=False,
        **kwargs):
    drug_ids = await get_drug_ids(drug_names)
    filtering_params = {
        'id': id,
        'indication_tree': {'data':indication_name, 'logic': 'or'},
        'companies': {"data":lead_company, "logic": "or"},
        'target': target,
        'drug_modality_mapping': drug_modality,
        'drug_feature': drug_feature,
        'route_of_administration': route_of_administration,
        'drug_ids': {'data':drug_ids, 'logic': drug_names['logic'] if drug_names else 'or'},
        'current_status': current_status,
        # 'phase': {'data':phase, 'logic': 'or'},
        'phase_mapping': {'data':phase, 'logic': 'or'},
        'nct_id': nctids,
        'gender': gender,
        'locations': locations
    }
    query_mapping = {
        'drug_modality': 'drug_modality_mapping',
        "drug_names": "drug_ids",
        "indication_name": "indication_tree",
        "lead_company": "companies",
        "phase": "phase_mapping",
        "nctids": "nct_id",
    }
    if "not_lead_company" in kwargs and not lead_company:
        filtering_params['companies'] = {"data":kwargs.pop("not_lead_company"), "logic": "not"}
    if exact_indication:
        filtering_params['indication_tree'] = {'data':await get_indication_mapped(indication_name), 'logic': 'or'}
    conditions, params = generate_conditions_and_params(filtering_params)
    and_keys = []
    apply_not_fields = kwargs.get("apply_not_fields", [])
    apply_not_fields = set([query_mapping.get(k, k) for k in apply_not_fields])
    if "condition_or" in kwargs and kwargs["condition_or"]:
        or_keys = []
        # print('apply_not_fields', apply_not_fields)
        for c in conditions:
            for key in apply_not_fields:
                if c.startswith(key):
                    c = f"NOT {c}"
                    break
            for key in set(['indication_tree', 'drug_ids', 'companies', 'target', 'drug_modality_mapping', 'drug_feature', 'route_of_administration']) - apply_not_fields:
                if c.startswith(key):
                    or_keys.append(c)
                    break
            else:
                and_keys.append(c)
        where_clause = " OR ".join(or_keys) if or_keys else f"1=1"
        if and_keys:
            where_clause = " AND ".join(and_keys + [f"({where_clause})"])
    else:
        for c in conditions:
            for key in apply_not_fields:
                if c.startswith(key):
                    c = f"NOT {c}"
                    break
            and_keys.append(c)
        where_clause = " AND ".join(and_keys) if and_keys else f"1=1"
    if fetch_recent:
        print("fetch_recent is true")
        where_clause_with_conditions = where_clause + f""" ORDER BY 
        id DESC,
        CASE WHEN last_updated IS NOT NULL THEN 1 ELSE 0 END DESC, 
        last_updated DESC, 
        anticipated_enrollment DESC limit {top_n} OFFSET {(page-1)*top_n}"""
    else:
        where_clause_with_conditions = where_clause + f" ORDER BY last_updated IS NOT NULL DESC, anticipated_enrollment DESC, id DESC limit {top_n} OFFSET {(page-1)*top_n}"
    if type == "comparison":
        selected = [
            "id",
            "nct_id",
            "primary_id",
            "last_updated",
            "official_title",
            "lead_company",
            "partner_companies",
            "drug_name",
            "drug_modality",
            "drug_feature",
            "route_of_administration",
            "indication_mapping",
            "target",
            "phase",
            "phase_mapping",
            "current_status",
            "gender",
            "actual_enrollment",
            "locations",
            "design",
            "efficacy",
            "safety",
            "key_findings",
            "sources",
            "label"
        ]
        if include_events: selected += ["event_ids"]
    else:
        raise ValueError(f"Invalid type: {type}")
    with get_connection() as conn:
        result = conn.execute(text(f"SELECT {','.join(selected)} FROM biomedtracker_trial_workflow WHERE {where_clause_with_conditions}"), params)
        results = result.fetchall()
    total_count = 0
    with get_connection() as conn:
        # Get total count
        count_result = conn.execute(text(f"SELECT COUNT(*) FROM biomedtracker_trial_workflow WHERE {where_clause}"), params)
        total_count = count_result.scalar()
    # sort the trials
    json_results = [{k if k != 'indication_mapping' else 'indication_name': v for k, v in dict(zip(selected, row)).items()} for row in results]
    for result in json_results:
        for key in ["start_date", "completion_date", "last_updated"]:
            if key in result and result[key]:
                result[key] = result[key].strftime('%Y-%m-%d')

    def sort_key(item):
        phase_order = {'III': 0, 'II/III': 1, 'IIb': 2, 'IIa': 3, 'II': 4, 'I/II': 5, 'I': 6}
        phase = item.get('phase', '')
        phase_value = phase_order.get(phase, 999)  # Default to 999 if phase not in the order
        status = item.get('current_status', '')
        status_value = 0 if status == 'Final Data' else 1 if status == 'Interim Data Released' else 2
        enrollment = item.get('actual_enrollment')
        enrollment_value = enrollment if enrollment is not None else -1  # Use -1 as default if enrollment is None
        return (phase_value, status_value, -enrollment_value)
    
    sorted_results = sorted(json_results, key=sort_key) if not fetch_recent else json_results
    return sorted_results, total_count

@async_timer
async def fill_events_until_token_limit_v1(results):
    event_id_collection = set()
    for result in results:
        if 'event_ids' not in result:
            continue
        event_id_collection.update(result['event_ids'])
    selected = ["id", "event_date", "event_type", "analysis"]
    where_clause = "id = ANY(:id)"
    params = {"id": list(int(event_id) for event_id in event_id_collection)}
    with get_connection() as conn:
        raw_events_res = conn.execute(text(f"SELECT {','.join(selected)} FROM biomedtracker_event WHERE {where_clause} AND event_type NOT LIKE '%Preclinical Results%'"), params)
        raw_events_all = raw_events_res.fetchall()
    event_results_all = [{k: v for k, v in dict(zip(selected, row)).items()} for row in raw_events_all]
    event_results_all_dict = {event.pop('id'): event for event in event_results_all}
    # for event_result in event_results_all:
    #     event_result['event_date'] = event_result['event_date'].strftime('%Y-%m-%d')
    def sort_key(item):
        event_type_order = {
            'Final Results': 0,
            'Published Results': 1,
            'Top-Line Results': 2,
            'Trial Data (Clinical Analysis)': 3,
            'Trial Data (Emerging Markets)': 4,
            'Subgroup Analysis': 5,
            'Updated Results': 6,
            'Retrospective Analysis': 7,
            'Suspension': 8
        }
        event_type = item.get('event_type', '')
        event_type_value = 99
        for key in event_type_order:
            if key in event_type:
                event_type_value = event_type_order[key]
        event_date = item.get('event_date', None)
        if event_date:
            if isinstance(event_date, str):
                event_date = datetime.strptime(event_date, '%Y-%m-%d').toordinal()
            else:
                event_date = event_date.toordinal()
        return (event_type_value, -event_date)
    
    for result in results:
        if 'sources' in result:
            del result['sources']
            # Remove references from text fields                
        pending_fields = ['design', 'efficacy', 'safety']
        pending_dict = {field: re.sub(r'\[\[\d+\]\]\([^)]+\)', '', result.pop(field, None)) for field in pending_fields if field in result}
        event_results = [event_results_all_dict[int(event_id)] for event_id in result['event_ids'] if int(event_id) in event_results_all_dict]
        sorted_event_results = sorted(event_results, key=sort_key)
        for event in sorted_event_results:
            event.pop('event_type', None)
            if not type(event['event_date']) == str:
                event['event_date'] = event['event_date'].strftime('%Y-%m-%d')
        cur_len = len(json.dumps(result))
        event_len = len(json.dumps(sorted_event_results))
        # print("event_len", len(sorted_event_results))
        if cur_len + event_len <= TOKEN_LIMIT * 4:
            result['events'] = sorted_event_results
            cur_len += len(json.dumps(sorted_event_results))
        else:
            result.update(pending_dict)
            result['events'] = []
            for event in sorted_event_results:
                event_len = len(json.dumps(event))
                if cur_len + event_len > TOKEN_LIMIT * 4:
                    # result['length'] = cur_len
                    break
                result['events'].append(event)
                cur_len += event_len
        # result['length'] = cur_len
        print("result['length']", cur_len)
        if 'event_ids' in result:
            result.pop('event_ids')
        # print("res_event_len", len(result['events']))
    return results


@async_timer
async def fill_events_until_token_limit_v2(results):
    def sort_key(item):
        event_type_order = {
            'Final Results': 0,
            'Published Results': 1,
            'Top-Line Results': 2,
            'Trial Data (Clinical Analysis)': 3,
            'Trial Data (Emerging Markets)': 4,
            'Subgroup Analysis': 5,
            'Updated Results': 6,
            'Retrospective Analysis': 7,
            'Suspension': 8
        }
        event_type = item.get('event_type', '')
        event_type_value = 99
        for key in event_type_order:
            if key in event_type:
                event_type_value = event_type_order[key]
                break
        event_date = item.get('event_date', None)
        if event_date:
            event_date = event_date.toordinal()
        return (event_type_value, -event_date)
    
    pending_fields = ['design', 'efficacy', 'safety', 'sources']
    for result in results:
        if 'event_ids' not in result:
            continue
        event_id_collection = set()
        event_id_collection.update(result['event_ids'])

        selected = ["id", "event_date", "event_type", "analysis"]
        where_clause = "id = ANY(:id)"
        params = {"id": list(int(event_id) for event_id in event_id_collection)}
        with get_connection() as conn:
            raw_events_res = conn.execute(text(f"SELECT {','.join(selected)} FROM biomedtracker_event WHERE {where_clause} AND event_type NOT LIKE '%Preclinical Results%'"), params)
            raw_events_all = raw_events_res.fetchall()
        event_results_all = [{k: v for k, v in dict(zip(selected, row)).items()} for row in raw_events_all]
        event_results_all_dict = {event.pop('id'): event for event in event_results_all}
    # for event_result in event_results_all:
    #     event_result['event_date'] = event_result['event_date'].strftime('%Y-%m-%d')
        pending_dict = {field: result.pop(field, None) for field in pending_fields if field in result}
        event_results = [event_results_all_dict[int(event_id)] for event_id in result['event_ids'] if int(event_id) in event_results_all_dict]
        sorted_event_results = sorted(event_results, key=sort_key)
        for event in sorted_event_results:
            event.pop('event_type', None)
            event['event_date'] = event['event_date'].strftime('%Y-%m-%d')
        cur_len = len(json.dumps(result))
        event_len = len(json.dumps(sorted_event_results))
        # print("event_len", len(sorted_event_results))
        if cur_len + event_len <= TOKEN_LIMIT * 4:
            result['events'] = sorted_event_results
            cur_len += len(json.dumps(sorted_event_results))
        else:
            result.update(pending_dict)
            result['events'] = []
            for event in sorted_event_results:
                event_len = len(json.dumps(event))
                if cur_len + event_len > TOKEN_LIMIT * 4:
                    # result['length'] = cur_len
                    break
                result['events'].append(event)
                cur_len += event_len
        # result['length'] = cur_len
        print("result['length']", cur_len)
        if 'event_ids' in result:
            result.pop('event_ids')
        # print("res_event_len", len(result['events']))
    return results