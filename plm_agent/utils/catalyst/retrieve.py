from datetime import datetime, timedelta
import json
import os
import traceback
from pytz import timezone
from sqlalchemy import text
from utils.sql_client import get_connection
from utils.clinical_utils.common import generate_conditions_and_params
from workflows.clinical_trial_result_comparison import compare_clinical_trial_results
from workflows.drug_compete import drug_compete
from utils.retrievers.typesense_retriever import get_client
from agent.workflow.selection import IdSelectionAgent
import logging

typesense_client = get_client()
logger = logging.getLogger(__name__)

def process_condition_or(conditions, apply_not_fields=set(), condition_or=False):
    and_keys = []
    if condition_or:
        or_keys = []
        for c in conditions:
            for key in apply_not_fields:
                if c.startswith(key):
                    c = f"NOT {c}"
                    break
            for key in set(['lead_company', '(lead_company', 'drug_name', 'indication_name', 'partner_companies', 'catalyst_type']) - apply_not_fields:
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
    return where_clause

def get_catalyst_list(top_n=10,page=1, details=False, focus_company=[], custom_impact=False, get_count=False, include_past=False, **kwargs):
    if include_past and custom_impact:
        top_n = 5
    condition_or = kwargs.pop('condition_or', False)
    if 'phases' in kwargs:
        kwargs['clinical_analysis_phase'] = kwargs.pop('phases')
    apply_not_fields = set(kwargs.pop('apply_not_fields', []))
    if 'company' in apply_not_fields:
        apply_not_fields.discard('company')
        apply_not_fields.update(set(['lead_company', 'partner_companies', '(lead_company']))

    _focus_company = kwargs.pop('company', [])
    if not focus_company: focus_company = _focus_company
    current_date = datetime.now(tz=timezone('US/Eastern')).date().strftime('%Y-%m-%d')
    impact_field = "catalyst_type" if custom_impact else "expected_catalyst_type"
    selected = ["catalyst_id", "title", "expected_date_start", "expected_date_end", "date_occurred", "clinical_analysis_phase", "expected_catalyst_type",
                "drug_name", "indication_name", "lead_company", "lead_company_symbol", "partner_companies"]
    selected_return = ["catalyst_id", "title", "expected_date_start", "expected_date_end", "date_occurred", "clinical_analysis_phase", impact_field,
                "drug_name", "indication_name", "lead_company", "lead_company_symbol", "partner_companies"]
    catalyst_type = kwargs.pop('catalyst_type', [])
    where_clause = "1=1"
    if details:
        selected.append("json_data")
        selected_return.append("json_data")
    catalyst_ids = kwargs.pop('catalyst_id', [])
    if type(catalyst_ids) in (int,str):
        catalyst_ids = [int(catalyst_ids)]
    if catalyst_ids:
        kwargs["catalyst_id"] = list((int(catalyst_id)-1)//3 for catalyst_id in catalyst_ids)
    date_range = kwargs.pop('date_range', None)
        
    fields_to_convert_to_list = ['drug_name', 'indication_name', 'lead_company', 'partner_companies'] 
    for field in fields_to_convert_to_list:
        if type(kwargs.get(field, None)) == dict:
            try: kwargs[field] = kwargs[field]['data']
            except: pass
    if 'indication_name' in kwargs and kwargs['indication_name']:
        kwargs['indication_tree'] = {'data':kwargs.pop('indication_name'), 'logic': 'or'}
    if 'clinical_analysis_phase' in kwargs and kwargs['clinical_analysis_phase']:
        kwargs['phase_mapping'] = {'data':kwargs.pop('clinical_analysis_phase'), 'logic': 'or'}
    conditions, params = generate_conditions_and_params({
        **kwargs
    })
    if focus_company:
        conditions_company, params_company = generate_conditions_and_params({
            'lead_company': focus_company,
            'partner_companies': {'data': focus_company, 'logic': 'or'},
        })
        where_clause_company = f'({" OR ".join(conditions_company)})' if conditions_company else ''
        if where_clause_company:
            conditions.append(where_clause_company)
            params.update(params_company)
    extra_conditions_not_removed = ["date_removed IS NULL"]
    conditions += extra_conditions_not_removed
    if date_range:
        start_date, end_date = date_range
        if not start_date and not end_date:
            pass
        if start_date and not end_date:
            conditions.append(f"expected_date_end >= '{start_date}'")
        elif not start_date and end_date:
            conditions.append(f"expected_date_start <= '{end_date}' OR expected_date_start IS NULL")
        else:
            conditions.append(f"expected_date_end >= '{start_date}' AND (expected_date_start IS NULL OR expected_date_start <= '{end_date}')")
    elif not catalyst_ids and not date_range:
        if include_past:
        # current_date = datetime.now(tz=timezone('US/Eastern')).date().strftime('%Y-%m-%d')
            current_date_minus_a_week = (datetime.now(tz=timezone('US/Eastern')).date() - timedelta(days=17)).strftime('%Y-%m-%d')
            conditions.append(f"expected_date_end >= '{current_date_minus_a_week}'")
        else: conditions.append(f"expected_date_end >= '{current_date}'")
    results = []
    if custom_impact and not len(catalyst_ids):
        extra_conditions = []
        if "PDUFA Approval" in catalyst_type:
            extra_conditions.append("expected_catalyst_type like '%PDUFA/Approval%'")
        if "Top-Line Results" in catalyst_type and "Trial Data Update" in catalyst_type:
            extra_conditions.append("expected_catalyst_type like '%Trial Data%'")
        elif "Top-Line Results" in catalyst_type:
            extra_conditions.append("expected_catalyst_type like '%Top-Line%'")
        elif "Trial Data Update" in catalyst_type:
            extra_conditions.append("expected_catalyst_type like '%Trial Data%' AND expected_catalyst_type not like '%Top-Line%'")

        extra_conditions_default = ["(expected_catalyst_type like '%PDUFA/Approval%' OR expected_catalyst_type like '%Trial Data%')"]
        extra_conditions = ["(" + " OR ".join(extra_conditions) + ")"] if extra_conditions else extra_conditions_default
        extra_conditions_has_ticker = ["(lead_company ~ '.*[(][A-Za-z]{2,5}[)]$' OR length(lead_company_symbol)>0 OR array_length(partner_company_symbols, 1)>0)"]
        extra_conditions += extra_conditions_has_ticker

        if not focus_company:
            extra_conditions_not_null_start_date = ["expected_date_start IS NOT NULL"] 
            extra_conditions += extra_conditions_not_null_start_date
        if not include_past:
            extra_conditions_hasnt_occurred = ["date_occurred IS NULL"]
            extra_conditions += extra_conditions_hasnt_occurred
        where_clause = process_condition_or(conditions + extra_conditions, apply_not_fields, condition_or)
        where_clause_with_order_limit = where_clause + f" ORDER BY expected_date_start IS NULL ASC, expected_date_end ASC, expected_date_start ASC, catalyst_id DESC limit  {top_n} OFFSET {(page-1)*top_n}"
        with get_connection() as conn:
            raw_catalysts_res = conn.execute(text(f"SELECT {','.join(selected)} FROM biomedtracker_catalyst_info WHERE {where_clause_with_order_limit}"), params)
            raw_catalysts_all = raw_catalysts_res.fetchall()
        results = [{k: v for k, v in dict(zip(selected_return, row)).items()} for row in raw_catalysts_all]
        for result in results:
            if "PDUFA/Approval" in result[impact_field]:
                result[impact_field] = "PDUFA Approval"
            elif "Top-Line" in result[impact_field]:
                result[impact_field] = "Top-Line Results"
            elif "Trial Data" in result[impact_field]:
                result[impact_field] = "Trial Data Update"
    else:
        where_clause = process_condition_or(conditions, apply_not_fields, condition_or)
        where_clause_with_order_limit = where_clause + f" ORDER BY expected_date_end ASC, expected_date_start IS NULL DESC, expected_date_start ASC, catalyst_id DESC limit {top_n} OFFSET {(page-1)*top_n}"
        with get_connection() as conn:
            raw_catalysts_res = conn.execute(text(f"SELECT {','.join(selected)} FROM biomedtracker_catalyst_info WHERE {where_clause_with_order_limit}"), params)
            raw_catalysts_all = raw_catalysts_res.fetchall()
        results = [{k: v for k, v in dict(zip(selected_return, row)).items()} for row in raw_catalysts_all]
    print("len(result)", len(results))
    total_count = 0
    if get_count:
        with get_connection() as conn:
            # Get total count
            count_result = conn.execute(text(f"SELECT COUNT(*) FROM biomedtracker_catalyst_info WHERE {where_clause}"), params)
            total_count = count_result.scalar()
    consecutive_delay_count = 0
    for result in results:
        result["company"] = [result.pop("lead_company","")] + result.pop("partner_companies", [])
        for key in ["expected_date_start", "expected_date_end"]:
            if key in result and result[key]:
                result[key] = result[key].strftime('%Y-%m-%d')
            
        if get_count:
            result.pop("title", None)
                
        if include_past:
            if result["date_occurred"]:
                result.pop("expected_date_start", None)
                result.pop("expected_date_end", None)
        result.pop("date_occurred", None)
        result["id"] = result.pop("catalyst_id") * 3 + 1
        if "json_data" not in result:
            continue
        try:
            context = result.pop("json_data")["Context"]
            # Show full context for detail page
            sources = []
            try: 
                filter_delay_context = []
                delay_flag = False
                source_flag = False
                for item in context:
                    # for item in context:
                    c = item.get("context", [])
                    s = item.get("source", {})
                    if 'Delayed' in c.get('label', ''):
                        if not delay_flag:
                            filter_delay_context.append(item)
                            if not source_flag:
                                for link in s.get('links', []):
                                    if link.get('href', ''):
                                        sources.append(link)
                            source_flag = True
                        else:
                            if result['expected_date_start'] is None:
                                if not result.get('consecutive_delay', None):
                                    consecutive_delay_count += 1
                                result['consecutive_delay'] = True
                        delay_flag = True
                    else:
                        delay_flag = False
                        if 'No Conference' in c.get('info', ''):
                            c['info'] = None
                        if not source_flag:
                            for link in s.get('links', []):
                                if link.get('href', ''):
                                    sources.append(link)
                            source_flag = True
                        filter_delay_context.append(item)
                if custom_impact:
                    result["sources"] = sources
                # if len(catalyst_ids) == 1:
                #     result["updates"] = filter_delay_context
            except Exception as e: 
                print("Error getting source", e)
        except Exception as e: print("Error getting context", e)
        if 'expected_date_start' in result and not result['expected_date_start']:
            result['expected_date_start'] = current_date
    if total_count <= 10:
        results = [result for result in results if not result.get("consecutive_delay", None)]
        total_count -= consecutive_delay_count
    if len(catalyst_ids) == 1:
        return results
    return {"results": results, "total_count": min(10000,total_count)} if get_count else results

def get_company_name(ticker):
    with get_connection() as conn:
        result = conn.execute(text(f"SELECT lead_company FROM biomedtracker_catalyst_info WHERE lead_company LIKE '%({ticker})%' OR lead_company_symbol='{ticker}' Limit 1"))
        name = result.scalar()
    return name

async def get_catalyst_related_info(catalysts, verbose=False, limit=210000):
    indication_drug_pairs = set()
    for catalyst in catalysts:
        if (catalyst["indication_name"], catalyst["drug_name"]) in indication_drug_pairs:
            continue
        try: 
            trials = (await compare_clinical_trial_results(indication_name=[catalyst["indication_name"]], drug_name={"data": [catalyst["drug_name"]], "logic": "or"}, exact_indication=True, include_events=True, fetch_recent=True, keep_id=True))['results']
            for trial in trials:
                trial_id = trial.pop("id", None)
                trial['url'] = f"{os.getenv('HOST', 'https://www.noahai.co')}/detail/clinical-trial/{trial_id}"
        except Exception as e: 
            trials = []
            print("Error getting clinical data", e)
        drug_info = []
        if not trials:
            try:
                drug_info = (await drug_compete(drug_names={"data": [catalyst["drug_name"]], "logic": "or"}, indication_name=[catalyst["indication_name"]], company=[catalyst["company"][:1]], exact_indication=True, top_n=1))['results'] or {}
                if drug_info: drug_info = drug_info[0]
            except Exception as e:
                drug_info = {}
                logger.info("Error getting drug info data in catalyst retreival", e)
        try: 
            drug_info = (await drug_compete(drug_names={"data": [catalyst["drug_name"]], "logic": "or"}, indication_name=[catalyst["indication_name"]], company=[catalyst["company"][:1]], exact_indication=True, top_n=1))['results'] or {}
            if drug_info: drug_info = drug_info[0]
        except Exception as e:
            drug_info = {}
            logger.info("Error getting drug info data in catalyst retreival", e)
        compete_trials = []
        if drug_info and 'target' in drug_info and not verbose:
            target = drug_info['target']
            compete_top_n = 1
            compete_trials_raw = (await compare_clinical_trial_results(target={"data": [target], "logic":"or"}, not_lead_company=[drug_info["lead_company"]], indication_name=[catalyst["indication_name"]], exact_indication=True, include_events=True, keep_id=True, top_n=compete_top_n))['results']
            compete_companies = set()
            for compete_trial in compete_trials_raw:
                if compete_trial["lead_company"] not in compete_companies:
                    compete_companies.add(compete_trial["lead_company"])
                    compete_trial.pop("id", None)
                    compete_trials.append(compete_trial)
        cur_len = len(str(catalysts)) + len(str(trials)) + len(str(drug_info))
        
        if cur_len > limit:
            break
        # drug_id = ""
        if drug_info:
            catalyst["drug_info"] = drug_info
            # drug_id = drug_info[0]["id"]
        catalyst["clinical_trial_data"] = trials
        if cur_len + len(str(compete_trials)) > limit:
            break
        catalyst["competing_drug_trial_data"] = compete_trials
        # catalyst["drug_compete_data"] = [drug for drug in drugs_compete if drug["id"] != drug_id]
        indication_drug_pairs.add((catalyst["indication_name"], catalyst["drug_name"]))
    try:
        if not verbose:
            return
        if not catalysts or len(str(catalysts)) > limit - 10000:
            return
        company = catalysts[0]["company"]
        if not company:
            return
        target = catalysts[0]["drug_info"]["target"]
        indication = catalysts[0]["indication_name"]
        if len(str(catalysts)) < limit - 10000:
            competing_trials = await llm_trial_selection(indication, target, company, len(str(catalysts)), limit)
        if competing_trials:
            catalysts[0]["competing_drug_trial_data"] = competing_trials
    except: 
        return

async def get_company_catalysts_and_related_info(ticker, include_past=False):
    # company_name = search_one_column(client=typesense_client, name='company', query='('+ticker+')', num_typos=0)
    company_name = get_company_name(ticker)
    if not company_name:
        return None, None
    
    large_impact_catalysts = get_catalyst_list(top_n=3, page=1, focus_company=[company_name], details=True, include_past=include_past, custom_impact=True)
    non_large_catalysts = get_catalyst_list(top_n=10, page=1, focus_company=[company_name], details=True, include_past=include_past)
    non_large_catalysts = [catalyst for catalyst in non_large_catalysts if catalyst["id"] not in [item["id"] for item in large_impact_catalysts]]
    if large_impact_catalysts:
        await get_catalyst_related_info(large_impact_catalysts, verbose=False)
    else:
        await get_catalyst_related_info(non_large_catalysts, verbose=False)
    # additional_trial_data = []
    # cur_len = len(str(non_large_catalysts) + str(large_impact_catalysts))
    # if cur_len < 28000:
        # compeeting = await llm_trial_selection()
        # catalyst_in_point = (large_impact_catalysts if large_impact_catalysts else non_large_catalysts)[0]
        # indication_name = (large_impact_catalysts if large_impact_catalysts else non_large_catalysts)[0]["indication_name"] if non_large_catalysts else ""
        # target_name = ""
        
        # target_name = (large_impact_catalysts if large_impact_catalysts else non_large_catalysts)[0]["drug_name"] if non_large_catalysts else ""
        # additional_trials = await llm_trial_selection()
        # existing_trial_ids = set()
        # append_target = None
        # if large_impact_catalysts and 'clinical_trial_data' in large_impact_catalysts[0]:
        #     append_target = large_impact_catalysts[0]
        #     existing_trial_ids.update(set([t['id'] for t in large_impact_catalysts[0]['clinical_trial_data']]))
        # if non_large_catalysts and 'clinical_trial_data' in non_large_catalysts[0]:
        #     append_target = non_large_catalysts[0]
        #     existing_trial_ids.update(set([t['id'] for t in non_large_catalysts[0]['clinical_trial_data']]))
        # for trial in additional_trials:
        #     trial_len = len(str(trial))
        #     if trial["id"] not in existing_trial_ids and cur_len + trial_len < 40000:
        #         additional_trial_data.append(trial)
        #         cur_len += trial_len
        # if additional_trial_data and append_target:
        #     append_target["additional_trial_data_for_same_indication"] = additional_trial_data
        # ret["competing_drug_trial_data"] = additional_trial_data
    ret = {
        "large_impact_catalysts": large_impact_catalysts,
        "non_large_catalysts": non_large_catalysts,
    }
    # try:
    #     for key in ret:
    #         if ret[key]:
    #             for item in ret[key]:
    #                 if not item:
    #                     continue
    #                 item.pop('id', None)
    #                 for content in ['clinical_trial_data', 'drug_compete_data', 'additional_trial_data_for_same_indication']:
    #                     if content in item:
    #                         for trial in item[content]:
    #                             trial.pop('id', None)
    # except Exception as e:
    #     print("Error removing id", e)
    #     pass

    return ret, company_name
    
async def get_catalysts_and_related_info_by_id(ids):
    catalysts = get_catalyst_list(catalyst_id=ids, details=True)
    await get_catalyst_related_info(catalysts, verbose=True)
    return catalysts
    
    
        
        
async def llm_trial_selection(indication, target, company, cur_len, limit):
    if not indication: return []
    trials = (await compare_clinical_trial_results(target={"data": [target], "logic":"or"}, not_lead_company=[company], indication_name=[indication], exact_indication=True, keep_id=True, top_n=25))['results']
    prompt_trials = []
    # for trial in trials:
    #     if trial["lead_company"] not in compete_companies:
    #         compete_companies.add(trial["lead_company"])
            
    prompt_trials = [{"id":trial["id"], "title": trial['official_title']} for trial in trials]
    
    prompt = f"""
    Please help me select the 5 most important and high impact clinical trials for the indication <{indication}> based on each trials' title.
    Return the selected ids in a list.
    Trial data:
    {prompt_trials}
    """
    result = (await anext(IdSelectionAgent().use_tool(user_prompt=prompt))).dict()['content']
    result = json.loads(result)
    id_list = result['id_list']
    ret = []
    for trial in trials:
        if trial['id'] in id_list:
            trial.pop('id', None)
            trial.pop('sources', None)
            cur_len += len(str(trial))
            if cur_len > limit:
                break
            ret.append(trial)
    return ret

