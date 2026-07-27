from copy import copy
import json
import logging
import os
from agent.human_in_loop.selection import llm_id_selection

from utils.catalyst.retrieve import get_catalyst_list, get_catalyst_related_info, get_catalysts_and_related_info_by_id, get_company_catalysts_and_related_info
from workflows.drug_compete import drug_compete
from utils.sql_client import get_connection
from workflows.conf_paper_search import search_conference_papers
from workflows.clinical_trial_result_comparison import compare_clinical_trial_results
from utils.human_in_loop.helpers import build_search_prompt, save_to_file
import random

logger = logging.getLogger(__name__)

query_tool_mapping = {
    "Clinical-Trial-Result-Analysis": compare_clinical_trial_results,
    "Drug-Analysis": drug_compete,
    'Catalyst-Event-Analysis': get_catalyst_list,
    # "Summarize-Results": {"func": SummarizeResultsInputSchema, "prompt": summarize_results_prompt},
}

top_n_mapping = {
    "Clinical-Trial-Result-Analysis": 150,
    "Drug-Analysis": 2000,
    'Catalyst-Event-Analysis': 30,
}

selection_mapping = {
    "Clinical-Trial-Result-Analysis": 40,
    "Drug-Analysis": 240,
    'Catalyst-Event-Analysis': 20,
}

async def run_query(current_tool, output_dir, current_step, language='en', user_prompt='', limit=50000, api_mode=False):
    global query_tool_mapping, top_n_mapping, selection_mapping
    if api_mode:
        selection_mapping["Drug-Analysis"] = 120
        top_n_mapping["Drug-Analysis"] = 500
    tool_name = current_tool['tool']
    headers = []
    condition_or = False
    if tool_name not in query_tool_mapping:
        return None, False
    func = query_tool_mapping[tool_name]
    params = current_tool['params']
    default_location = params.pop('default_location', False)
    location_key = None
    for key in ['location', 'locations']:
        if params.get(key, []):
            location_key = key
            location = params[key].copy()
            for l in location:
                if 'global' in l.lower() or 'world' in l.lower():
                    for country in ['USA', 'China', 'Japan', 'UK', 'France', 'Germany', 'Italy', 'Spain']:
                        if country not in params[key]:
                            params[key].append(country)
                    break
                if 'europe' in l.lower():
                    for country in ['Germany', 'France', 'Italy', 'Spain', 'UK']:
                        if country not in params[key]:
                            params[key].append(country)
                    break
            break
    for key in ['company', 'lead_company']:
        if (company_list:=params.get(key, [])):
            if isinstance(company_list, str):
                company_list = [company_list]
            elif isinstance(company_list, dict):
                company_list = company_list.get('data', [])
            new_company_list = []
            for c in company_list:
                if 'inc.' in c.split() or 'inc' in c.split():
                    # Remove 'inc.', 'inc', 'Inc.', or 'Inc' from the end of the company name
                    c = c.rstrip(' .')
                    if c.lower().endswith('inc'):
                        c = c[:-3].rstrip(' .')
                new_company_list.append(c)
            params[key] = new_company_list
            break
        
    if tool_name == "Catalyst-Event-Analysis":
        params['custom_impact'] = True
        params['details'] = True
    if tool_name in top_n_mapping:
        params['top_n'] = top_n_mapping[tool_name]
    params.pop('question', '')
    for k,v in list(current_tool['params'].items()):
        if not v:
            params.pop(k)
    for k,v in func.__annotations__.items():
        if k in params:
            if isinstance(params[k], list) and v == dict:
                params[k] = {'data': params[k], 'logic': 'or'}
            elif isinstance(params[k], dict) and v == list:
                params[k] = params[k].get('data', params[k])
    # if tool_name == "Drug-Analysis" and not params.get('location', []):
    #     params['location'] = ['USA']
    res = func(**params)
    if hasattr(res, '__await__'):  # Check if res is a coroutine
        res = await res
    if res is None:
        return None, False
    data = res['results'] if 'results' in res else res
    if not data:
        condition_or = True
        res = func(**params, condition_or=condition_or)
        if hasattr(res, '__await__'):  # Check if res is a coroutine
            res = await res
        if res is None:
            return None, False
        data = res['results'] if 'results' in res else res
    if len(data) > 200 and location_key and default_location:
        location = []
        if params.get(location_key, []):
            if 'USA' in params[location_key]:
                location.append('USA')
            if 'United States' in params[location_key]:
                location.append('United States')
            if 'China' in params[location_key]:
                location.append('China')
        params[location_key] = location
        current_tool['params'][location_key] = location
        res = func(**params, condition_or=condition_or)
        if hasattr(res, '__await__'):  # Check if res is a coroutine
            res = await res
        if res is None:
            return None, False
        filtered_data = res['results'] if 'results' in res else res
        if len(filtered_data) > 30:
            data = filtered_data
    if tool_name == "Catalyst-Event-Analysis" and not data:
        params.pop('phases', [])
        res = func(**params)
        if hasattr(res, '__await__'):  # Check if res is a coroutine
            res = await res
        if res is None:
            return None, False
        data = res['results'] if 'results' in res else res
    elif tool_name == "Drug-Analysis":
        limit = 30000
        # if not params.get('phase', []):
        #     def sort_key(item):
        #         phase_order = {'Approved': 0, 'BLA/NDA': 1,'NDA/BLA': 1, 'III': 2,'II': 3,'I': 4, 'IND': 5, 
        #                     'Preclinical': 6,'IV': 7,'Suspended': 8,'Withdrawn from Market': 9,
        #                     'Investigator Initiated - phase unknown': 10,'Unknown': 11,'Others': 12,'II/III': 2.5,
        #                     'IIb': 3.1,'IIa': 3.2,'I/II': 3.5
        #         }
        #         phase = item.get('phase', '')
        #         phase_value = phase_order.get(phase, 999)  # Default to 999 if phase not in the order
        #         return phase_value  # Add random factor as third sorting key
        #     data = sorted(data, key=sort_key)
        # else:
        data = sorted(data, key=lambda _: random.random())
    elif tool_name == "Clinical-Trial-Result-Analysis":
        if params.get('phase', []):
            def sort_key(item):
                last_updated = item.get('last_updated', '')
                return last_updated
            try:
                data = sorted(data, key=sort_key, reverse=True)
            except:
                pass
                
    orig_data = data
    short_data = data
    # For token limiting
    if tool_name == "Clinical-Trial-Result-Analysis":
        short_data = []
        for item in data:
            short_item = {'companies': []}
            for k in ['id', 'official_title', 'phase', 'current_status', 'last_updated']:
                short_item[k] = item[k]
            if lead_company := item.get('lead_company'):
                short_item['companies'].append(lead_company)
            if partner_companies := item.get('partner_companies'):
                short_item['companies'].extend(partner_companies)
            if short_item:
                if len(str(short_data)) < limit:
                    short_data.append(short_item)
                else:
                    break
    elif tool_name == "Drug-Analysis":
        short_data = []
        headers = ['id', 'name']
        for key in ['route_of_administration', 'target']:
            if key in params and params[key]:
                headers.append(key)
        if 'indication_name' in params and params['indication_name']:
            headers.append('indication_name')
        if 'lead_company' in params and params['lead_company']:
            headers.append('company')
        # if 'drug_modality' in params and params['drug_modality']:
        headers.append('modality')
        # if 'drug_feature' in params and params['drug_feature']:
        headers.append('feature')
        headers.append('phase')
        for item in data:
            short_item = {}
            for k in ['id', 'name']:
                short_item[k] = item[k]
            for key in ['indication_name', 'route_of_administration', 'target']:
                if item.get(key, ''):
                    short_item[key] = item[key]
            if item.get('phase', ''):
                short_item['phase'] = 'phase ' + item['phase']
            # if item.get('indication_name', ''):
            #     short_item['indication'] = item['indication_name']
            if item.get('lead_company', ''):
                short_item['company'] = item['lead_company']
            if item.get('drug_modality', ''):
                short_item['modality'] = item['drug_modality']
            if item.get('drug_feature', ''):
                short_item['feature'] = item['drug_feature']
            if short_item:
                short_data.append(short_item)
                
                # if len(str(short_data)) < limit:
                #     short_data.append(short_item)
                # else:
                #     break
    # save_to_file(short_data, output_dir, f"{current_step}_{current_tool['tool']}_data_full.json")
    
    base52 = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
    for i, d in enumerate(orig_data):
        if 'id' in d:
            d['orig_id'] = d['id']
            prefix = ""
            num = i
            while num >= 0:
                prefix = base52[num % 52] + prefix
                num = num // 52 - 1
            d['id'] = prefix
            
    for i, d in enumerate(short_data):
        if 'id' in d:
            prefix = ""
            num = i
            while num >= 0:
                prefix = base52[num % 52] + prefix
                num = num // 52 - 1
            d['id'] = prefix
            
    if len(data) > 10 or len(str(data)) > limit:
        prompt = ''
        if 'reason' in current_tool:
            prompt = f"Your task is to select a pool of data for a tool: {current_tool['tool']}. \nThe reason for using the tool: {current_tool['reason']}"
        if user_prompt:
            prompt += f' (to answer the user prompt: {user_prompt})'
        logger.info(f"len(short_data): {len(short_data)}")
        data = await llm_id_selection(short_data=short_data, orig_data=orig_data, select_n=selection_mapping[tool_name] if tool_name in selection_mapping else 10, prompt=prompt, limit=limit, headers=headers, params=params, condition_or=condition_or)
    if tool_name == "Catalyst-Event-Analysis":
        await get_catalyst_related_info(data, verbose=True, limit=limit)
        params.pop('custom_impact', None)
        params.pop('details', None)
    for d in data:
        d['id'] = d.pop('orig_id', None)
    return data, condition_or