

import asyncio
import json
from agent.workflow.selection import IdSelectionAgent
from utils.human_in_loop.helpers import function_call_with_retry
import random
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def llm_id_selection(short_data=[], orig_data=[], limit=150000, select_n=100, prompt='', headers=[], params={}, condition_or=False):
    # Randomize the order of the short_data list to avoid positional bias
    data_size = len(short_data)
    select_size = min(data_size - 20, select_n)
    id_list = []
    retry = 0
    batches = []
    
    if headers:
        if not condition_or:
            new_headers = []
            old_headers = []
            for key in headers:
                val = params.get(key, None)
                if val:
                    if type(val) == str:
                        new_headers.append(f"{key}={val}")
                    elif type(val) == list and len(val) == 1:
                        new_headers.append(f"{key}={val[0]}")
                    else:
                        old_headers.append(key)
                else:
                    old_headers.append(key)
            headers = old_headers + new_headers
        cur_batch = []
        cur_len = 0
        for d in short_data:
            line = ', '.join([str(d.get(h, '')) for h in headers])
            if cur_len + len(line) > limit:
                batches.append(cur_batch)
                cur_batch = []
                cur_len = 0
                if len(batches) >= 4:
                    break
            cur_batch.append(line)
            cur_len += len(line)
        batches.append(cur_batch)
    else:
        batches = [short_data] 
        
    logger.info(f"Total Batches: {len(batches)}")
    for batch in batches:
        logger.info(f"Batch Size: {len(batch)}")

    if data_size > select_n:
        while len(id_list) < select_size and retry < 1:
            logger.info("GOING THROUGH BATCHES")
            aio_tasks = []
            for batch in batches:
                # Create a list to store the tasks
                aio_task = asyncio.create_task(select_batch(batch, headers, prompt, select_size=select_size//len(batches)))
                aio_tasks.append(aio_task)
                
            # Wait for all tasks to complete and gather results
            results = await asyncio.gather(*aio_tasks)
            
            # Process results from all batches
            for result in results:
                if result and isinstance(result, list):
                    id_list.extend(result)
            # Remove duplicates
            id_list = list(set(id_list))
            short_data = [item for item in short_data if item['id'] not in id_list]
            
            # If we still need more items and have attempts left
            if len(id_list) < select_size:
                retry += 1
            else:
                break

    ret = []
    not_selected_list = []
    cur_len = 0
    drug_field_keys = {}
    merged = 0
    new = 0
    for item in orig_data:
        if len(ret)>= select_n:
            break
        if data_size < select_n or 'id' in item and (item['id'] in id_list or str(item['id']) in id_list):
            # item.pop('id', None)
            item_copy = item.copy()
            for key in item:
                if not item[key]:
                    item_copy.pop(key, None)
                    continue
                if key == 'drug_modality':
                    item_copy['modality'] = item_copy.pop('drug_modality', None)
                if key == 'drug_feature':
                    item_copy['feature'] = item_copy.pop('drug_feature', None)
                if key == 'lead_company':
                    item_copy['company'] = item_copy.pop('lead_company', None)
                if key == 'route_of_administration':
                    item_copy['route'] = item_copy.pop('route_of_administration', None)
            cur_len += len(str(item_copy))
            if cur_len > limit*5:
                break
            if 'name' in item_copy and 'indication' in item_copy and 'location' in item_copy and 'phase' in item_copy and 'company' in item_copy:
                drug_field_key = f"{item_copy['name']}_{item_copy['indication']}_{item_copy['phase']}_{item_copy['company']}"
                if drug_field_key in drug_field_keys and item_copy['location'] not in drug_field_keys[drug_field_key]['location']:
                    merged+=1
                    drug_field_keys[drug_field_key]['location'].append(item_copy['location'])
                else:
                    new+=1
                    if type(item_copy['location']) == str:
                        item_copy['location'] = [item_copy['location']]
                    drug_field_keys[drug_field_key] = item_copy
                    ret.append(item_copy)
            else:
                ret.append(item_copy)
            continue
        not_selected_list.append(item)
    logger.info(f"Total Selected IDs: {len(ret)}")
    logger.info(f"new {new}, merged {merged}")
    return ret

async def select_batch(short_data, headers=[], prompt="", select_size=100):
    if len(short_data) <= select_size:
        logger.info(f"Auto Selected IDs: {len(short_data)}")
        if short_data and isinstance(short_data[0], dict):
            return [item['id'] for item in short_data if 'id' in item]
        elif short_data and isinstance(short_data[0], str):
            return [item.split(",")[0].strip() for item in short_data]
    if headers:
        minimized_data = [', '.join(headers)] + short_data
        minimized_data = '\n'.join(minimized_data)
    else:  
        minimized_data = json.dumps(short_data, separators=(',', ':'), ensure_ascii=False)
    prompt_template = f"""
You are an expert in selecting medical items for analysis.
<User Prompt>
{prompt}
</User Prompt>
Please help me select appropriate or relevant <Items> based on their properties and the <User Prompt>, try to select around {select_size+10} items of most interest and relevance.
Note that the items we select are only candidates for further analysis, not final results, so you can choose potential items of interest, even if they are not the most relevant.
Don't just choose the ones in the front, also consider items further down the list.
If date requirements not specifed, prioritize items with more recent updated date (if provided).
Select items by ID and return ID list of chosen items.

<Items>
{minimized_data}
</Items>
"""
    result = await function_call_with_retry(IdSelectionAgent().use_tool, user_prompt=prompt_template)
    logger.info(f"Selected IDs: {len(result['id_list'])}")
    return result['id_list']