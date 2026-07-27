import asyncio
import os
import glob
import pandas as pd
# from llm.composite_models import SlotFillingModels as LowEffortSlotFillingModels
from llm.composite_models import LowEffortSlotFillingModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from .schema_v2 import ClassificationSchemaFirstLayerV2, ClassificationSchemaNum, ExtractionSchemaV2, ClassificationSchema, ClusteringSchema
from .prompt import *
from .prompt_v2 import *
import traceback
import json
from collections import Counter, defaultdict
import pickle

# Columns to read
columns = ['项目名称', '意见']

def read_xlsx_files_with_columns(directory='.', columns=columns):
    data = []
    xlsx_files = glob.glob(os.path.join(directory, '*.xlsx'))
    print(f"Found {len(xlsx_files)} XLSX files.")
    for file in xlsx_files:
        try:
            df = pd.read_excel(file, usecols=columns)
            data.extend(df.to_dict(orient='records'))
        except Exception as e:
            print(f"Error reading {file}: {e}")
    print('Total records read:', len(data))
    print('Sample record:', data[0] if data else 'No data')
    return data

def read_csv_files_with_columns(directory='.'):
    data = []
    csv_files = glob.glob(os.path.join(directory, '*.csv'))
    print(f"Found {len(csv_files)} CSV files.")
    for file in csv_files:
        try:
            df = pd.read_csv(file, usecols=columns, encoding='utf-8')
        except Exception:
            # Try with gbk encoding if utf-8 fails
            df = pd.read_csv(file, usecols=columns, encoding='gbk')
        data.extend(df.to_dict(orient='records'))
    return data

def extract_from_files(results):
    extraction_schema = get_openai_json_schema_v3(ExtractionSchemaV2)
    extraction_tool_choice = {"type": "function", "function": {"name": extraction_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    opinion_text = ""
    # for i in range(len(results)//10 + 1):
    async def process_item(idx, item):
        project_name = item['项目名称']
        opinions = [f"专家意见: {item['意见']}"]
        if not opinions:
            return
        opinion_text = f"项目序号: {idx+1}\n项目名称: {project_name}\n评审意见: {opinions}\n\n"
        user_input = {
            "input": opinion_text,
        }
        try:
            response = await function_call_with_retry(
                llm,
                tool_choice=extraction_tool_choice,
                tools=extraction_schema,
                user_prompt=extraction_prompt.replace("{input}", user_input['input']),
            )
            print(f"Project: {project_name}")
            print(f"Response: {response}")
            # Save response to file
            output_filename = f"extraction_results.txt"
            with open(output_filename, 'a', encoding='utf-8') as f:
                f.write(f"Project {idx}: {project_name}\n")
                json.dump(response, f, ensure_ascii=False, indent=2)
                f.write('\n')
            print(f"Results appended to {output_filename}")
        except Exception as e:
            traceback.print_exc()
            print(f"Error processing project {project_name}: {e}")

    async def process_all():
        tasks = [process_item(idx, item) for idx, item in enumerate(results)]
        await asyncio.gather(*tasks)

    asyncio.run(process_all())
            
def bucket_slotting(opinions_file_path):
    opinion_counter = Counter()
    with open(opinions_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    cur_dict_str = ''
    in_dict = False
    for line in lines:
        line = line.strip()
        if line == '{':
            in_dict = True
        if in_dict:
            cur_dict_str += line
        if line == '}':
            try:
                print("cur_dict_str:", cur_dict_str)
                opinions_dict = json.loads(cur_dict_str)
                for key in opinions_dict:
                    for opinion in opinions_dict[key]:
                        opinion_counter[opinion] += 1
                cur_dict_str = ''
            except Exception as e:
                # traceback.print_exc()
                print(f"Error parsing line: {e}")
                break
            in_dict = False
    print("Opinion counts:")
    # print(opinion_counter)

    for opinion, count in opinion_counter.items():
        print(f"{opinion}: {count}")
    return opinion_counter


def bucket_slotting_list(opinions_file_path):
    project_list = []
    opinions = []
    with open(opinions_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    cur_dict_str = ''
    in_dict = False
    for line in lines:
        line = line.strip()
        if line == '{':
            in_dict = True
        if in_dict:
            cur_dict_str += line
        if line == '}':
            try:
                opinions_dict = json.loads(cur_dict_str)
                opinions_list = []
                for key in opinions_dict:
                    for opinion in opinions_dict[key]:
                        opinions.append(opinion)
                    opinions_list.append(opinions)
                    opinions = []
                    
                cur_dict_str = ''
                project_list.append(opinions_list)
                opinions_list = []
            except Exception as e:
                # traceback.print_exc()
                print(f"Error parsing line: {e}")
                break
            in_dict = False
    for opinions_list in project_list[:2]:
        print(opinions_list)
    return project_list

def read_extracted_results_into_list():
    cache_path = '/Users/andy/repos/NoahAgent/noah_agent/extracted_results.pkl'
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as pf:
            extracted_results = pickle.load(pf)
        print("Loaded extracted_results from cache.")
    else:
        extracted_results = bucket_slotting_list('/Users/andy/repos/NoahAgent/noah_agent/extraction_results.txt')
        with open(cache_path, 'wb') as pf:
            pickle.dump(extracted_results, pf)
        print("Saved extracted_results to cache.")
    return extracted_results

def classify_from_opinions(project_list):
    classification_schema = get_openai_json_schema_v3(ClassificationSchemaFirstLayerV2)
    classification_tool_choice = {"type": "function", "function": {"name": classification_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    async def process_project(idx, project):
        if not project:
            return
        flattened_list = [o for o_list in project for o in o_list]
        opinion_text = f"{flattened_list}"
        latest_e = ""
        for _ in range(5):
            try:
                response = await function_call_with_retry(
                    llm,
                    tool_choice=classification_tool_choice,
                    tools=classification_schema,
                    user_prompt=full_classification_0.replace("{input}", opinion_text),
                )
                classifications = response['classifications']
                if abs(len(classifications) - len(flattened_list)) > 1:
                    print(f"Length mismatch: {len(classifications)} vs {len(flattened_list)}, retrying...")
                    raise ValueError("Length mismatch")
                for c in classifications:
                    if c not in ['A', 'B']:
                        print(f"Found unclassified opinion, retrying...")
                        raise ValueError("Unclassified opinion found")
                zipped = list(zip(flattened_list, classifications))
                print(f"Response: {response}")
                # Save response to file
                return zipped
            except Exception as e:
                latest_e = str(e)
                traceback.print_exc()
        return f"Error: {latest_e}"


    async def process_all():
        _results = [None] * len(project_list)
        needs_processing = range(len(project_list))
        cache_path = "classification_results.pkl"
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as pf:
                _results = pickle.load(pf)
            print("Loaded classification_results from cache.")
            needs_processing = [idx for idx, item in enumerate(_results) if isinstance(item, str) and item.startswith("Error")]
        tasks = [process_project(idx, item) for idx, item in enumerate(project_list) if idx in needs_processing]
        if not tasks:
            print("No new tasks to process.")
            return
        results = await asyncio.gather(*tasks)
        _zip = zip(needs_processing, results)
        for idx, result in _zip:
            _results[idx] = result
        with open(cache_path, "wb") as pf:
            pickle.dump(_results, pf)
        print("Results pickled to classification_results.pkl")
        
        output_filename = f"classification_results_temp.txt"
        with open(output_filename, 'w', encoding='utf-8') as f:
            for idx, result in enumerate(_results):
                f.write(f"Project {idx}\n")
                if isinstance(result, str):
                    f.write(result + '\n')
                    continue
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write('\n')
            print(f"Results written to {output_filename}")
        cnt = {}
        for l in _results:
            for cls in l:
                if cls not in cnt:
                    cnt[cls] = 0
                cnt[cls] += 1
        for key in cnt:
            print(key, cnt[key])
    asyncio.run(process_all())
    

def get_first_layer_lists(classification_results):
    res = defaultdict(list)
    for project in classification_results:
        for r, cls in project:
            for c in 'AB':
                if str(cls).startswith(c):
                    res[c].append(r)
                    break
            else:
                res['other'].append(r)
    for r in res:
        print(f"Class {r}: {len(res[r])} opinions")
    with open('first_layer_results.pkl', 'wb') as pf:
        pickle.dump(res, pf)
    print("First layer results saved to first_layer_results.pkl")
    return res
    
def classify_from_single_list(class_list, file_name='classification_results_scientific', prompt=scientific_classification, sections=list_of_scientific_sections):
    classification_schema = get_openai_json_schema_v3(ClassificationSchema)
    classification_tool_choice = {"type": "function", "function": {"name": classification_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    async def process_list(idx, c_list):
        if not c_list:
            return
        flattened_list = c_list
        opinion_text = f"{flattened_list}"
        latest_e = ""
        for _ in range(5):
            try:
                response = await function_call_with_retry(
                    llm,
                    tool_choice=classification_tool_choice,
                    tools=classification_schema,
                    user_prompt=prompt.replace("{input}", opinion_text),
                )
                classifications = response['classifications']
                if abs(len(classifications) - len(flattened_list)) > 5:
                    print(f"Length mismatch: {len(classifications)} vs {len(flattened_list)}, retrying...")
                    raise ValueError("Length mismatch")
                for c in classifications:
                    if c not in sections and (not c or len(c)<2 or '无法归类' in c or c.isascii()):
                        print(f"Found unclassified opinion, retrying...")
                        raise ValueError("Unclassified opinion found")
                zipped = list(zip(flattened_list, classifications))
                print(f"Response: {response}")
                # Save response to file
                return zipped
            except Exception as e:
                latest_e = str(e)
                traceback.print_exc()
        return f"Error: {latest_e}"


    async def process_all():
        nonlocal class_list
        # Group class_list into chunks of 1
        CHUNK_SIZE = 1
        chunked_class_list = []
        for i in range(0, len(class_list), CHUNK_SIZE):
            chunked_class_list.append(class_list[i:i+CHUNK_SIZE])
        class_list = chunked_class_list
        _results = [None] * len(class_list)
        needs_processing = range(len(class_list))
        cache_path = f"{file_name}.pkl"
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as pf:
                _results = pickle.load(pf)
            print(f"Loaded {file_name} from cache.")
            needs_processing = [idx for idx, l in enumerate(_results) if not l or isinstance(l, str) and l.startswith("Error")]
        tasks = [process_list(idx, l) for idx, l in enumerate(class_list) if idx in needs_processing]
        if not tasks:
            print("No new tasks to process.")
            cnt = {}
            for l in _results:
                for idx, _cls in l:
                    if _cls not in cnt:
                        cnt[_cls] = 0
                    cnt[_cls] += 1
            for key in cnt:
                print(key, cnt[key])
            return
        results = await asyncio.gather(*tasks)
        _zip = zip(needs_processing, results)
        for idx, result in _zip:
            _results[idx] = result
        with open(cache_path, "wb") as pf:
            pickle.dump(_results, pf)
        print(f"Results pickled to {file_name}.pkl")

        output_filename = f"{file_name}.txt"
        with open(output_filename, 'w', encoding='utf-8') as f:
            for idx, result in enumerate(_results):
                f.write(f"Project {idx}\n")
                if isinstance(result, str):
                    f.write(result + '\n')
                    continue
                json.dump(result, f, ensure_ascii=False, indent=2)
                f.write('\n')
            print(f"Results written to {output_filename}")
        cnt = {}
        for l in _results:
            for item in l:
                if isinstance(item, str):
                    continue
                idx, _cls = item
                if _cls not in cnt:
                    cnt[_cls] = 0
                cnt[_cls] += 1
        for key in cnt:
            print(key, cnt[key])
    asyncio.run(process_all())

if __name__ == "__main__":
    # results = read_xlsx_files_with_columns('/Users/andy/repos/NoahAgent/noah_agent/agent/iit/pp/1020', columns=columns)
    # extract_from_files(results)
    # extracted_results = read_extracted_results_into_list()
    
    # classify_from_opinions(extracted_results)
    
    cache_path = "classification_results.pkl"
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as pf:
            classification_results = pickle.load(pf)
    first_layer_lists = get_first_layer_lists(classification_results)

    classify_from_single_list(first_layer_lists['B'], file_name='classification_results_scientific')

    classify_from_single_list(first_layer_lists['A'], file_name='classification_results_formal', prompt=formal_classification, sections=list_of_formal_sections)

    # cache_path = "first_layer_results.pkl"
    # if os.path.exists(cache_path):
    #     with open(cache_path, "rb") as pf:
    #         first_layer_lists = pickle.load(pf)
    # get_second_layer_classification(first_layer_lists)
    
    # clustering(layer='first')
    # slotting(layer='first')
    
    # count()
    
    # res_cache_path = "first_layer_results.pkl"
    # if os.path.exists(res_cache_path):
    #     with open(res_cache_path, "rb") as pf:
    #         first_layer_results = pickle.load(pf)
            
    # cluster_cache_path = "first_layer_clusters.pkl"
    # first_layer_clusters = clustering(first_layer_results['other'])
    # with open(cluster_cache_path, "wb") as pf:
    #     pickle.dump(first_layer_clusters, pf)
    # print(f"Results pickled to {cluster_cache_path}")


    