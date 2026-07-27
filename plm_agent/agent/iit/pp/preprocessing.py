import asyncio
import os
import glob
import pandas as pd
from llm.composite_models import SlotFillingModels as LowEffortSlotFillingModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from .schema import ClassificationSchemaFirstLayer, ClassificationSchemaNum, ExtractionSchema, ClassificationSchema, ClusteringSchema
from .prompt import *
import traceback
import json
from collections import Counter, defaultdict
import pickle

# Columns to read
columns = ['项目名称', '专家意见1', '专家意见2', '专家意见3', '专家意见4', '专家意见5']
columns_2 = ['项目名称', '意见']

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
    extraction_schema = get_openai_json_schema_v3(ExtractionSchema)
    extraction_tool_choice = {"type": "function", "function": {"name": extraction_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    opinion_text = ""
    # for i in range(len(results)//10 + 1):
    async def process_item(idx, item):
        project_name = item['项目名称']
        opinions = [f"专家意见{i}: {item.get(f'专家意见{i}')}" for i in range(1, 6) if item.get(f'专家意见{i}')]
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
    classification_schema = get_openai_json_schema_v3(ClassificationSchemaFirstLayer)
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
                    user_prompt=classification_prompt_0.replace("{input}", opinion_text),
                )
                classifications = response['classifications']
                if abs(len(classifications) - len(flattened_list)) > 1:
                    print(f"Length mismatch: {len(classifications)} vs {len(flattened_list)}, retrying...")
                    raise ValueError("Length mismatch")
                for c in classifications:
                    if c == '0' or not c or c not in '1234567' and len(c)<2 or c == '无法归类':
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
        for project in _results:
            for r, cls in project:
                if cls not in '1234567':
                    if '：' in cls:
                        cls = cls.split('：', 1)[1]
                    elif '-' in cls:
                        cls = cls.split('-', 1)[1]
                    elif ' ' in cls:
                        cls = cls.split(' ', 1)[1]
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
            for c in '1234567':
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
    
def get_second_layer_classification(classification_results):
    classification_schema = get_openai_json_schema_v3(ClassificationSchema)
    classification_tool_choice = {"type": "function", "function": {"name": classification_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    async def process_opinions(l, prompt):
        if not l:
            return
        opinion_text = f"{l}"
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
                if len(classifications) != len(l):
                    print(f"Length mismatch: {len(classifications)} vs {len(l)}, retrying...")
                    raise ValueError("Length mismatch")
                for c in classifications:
                    if c == '0':
                        print(f"Found unclassified opinion, retrying...")
                        raise ValueError("Unclassified opinion found")
                zipped = list(zip(l, classifications))
                print(f"Response: {response}")
                # Save response to file
                return zipped
            except Exception as e:
                latest_e = str(e)
                traceback.print_exc()
        return f"Error: {latest_e}"


    async def process_class(results, prompt, type='def'):
        batch_size = 5
        batches = [results[i:i + batch_size] for i in range(0, len(results), batch_size)]
        _results = [None] * len(batches)
        needs_processing = range(len(batches))
        cache_path = f"second_layer_results_{type}.pkl"
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as pf:
                _results = pickle.load(pf)
            print(f"Loaded {cache_path} from cache.")
            needs_processing = [idx for idx, item in enumerate(_results) if isinstance(item, str) and item.startswith("Error")]
        tasks = [process_opinions(batch, prompt) for idx, batch in enumerate(batches) if idx in needs_processing]
        if not tasks:
            print("No new tasks to process.")
            return
        results = await asyncio.gather(*tasks)
        _zip = zip(needs_processing, results)
        for idx, result in _zip:
            _results[idx] = result
        with open(cache_path, "wb") as pf:
            pickle.dump(_results, pf)
        print(f"Results pickled to {cache_path}")
        # tasks = [process_project(idx, item) for idx, item in enumerate(project_list)]
        # results = await asyncio.gather(*tasks)
        # # Save results to pickle file
        # with open("classification_results.pkl", "wb") as pf:
        #     pickle.dump(results, pf)
        # print("Results pickled to classification_results.pkl")

        output_filename = f"second_layer_results_temp_{type}.txt"
        with open(output_filename, 'w', encoding='utf-8') as f:
            for idx, result in enumerate(_results):
                if isinstance(result, str):
                    f.write(result + '\n')
                    continue
                for r, c in result:
                    if len(str(c))>1:
                        f.write(f"{str(c)}                 《{str(r)}》\n")
            print(f"Results written to {output_filename}")
            
    async def process_all():
        
        prompts = [classification_prompt_1, classification_prompt_2, classification_prompt_3, classification_prompt_4, classification_prompt_5, classification_prompt_6, classification_prompt_7]
        tasks = [process_class(classification_results[t], prompts[int(t)-1], t) for t in classification_results if t in '1234567']
        await asyncio.gather(*tasks)
        
    asyncio.run(process_all())

def clustering(layer='second'):
    cache_path = "first_layer_results.pkl"
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as pf:
            first_layer_results = pickle.load(pf)
    clustering_schema = get_openai_json_schema_v3(ClusteringSchema)
    clustering_tool_choice = {"type": "function", "function": {"name": clustering_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    async def process_classifications(classification_results, tag='def', dimensions=''):
        classification_text = f"{classification_results}"
        latest_e = ""
        for _ in range(5):
            try:
                response = await function_call_with_retry(
                    llm,
                    tool_choice=clustering_tool_choice,
                    tools=clustering_schema,
                    user_prompt=clustering_prompt.replace("{input}", classification_text).replace("{dimensions}", dimensions)
                )
                try:
                    clusters = json.loads(response['clusters'])
                except:
                    clusters = response['clusters']
                
                print(f"Response: {response}")
                # Save response to file

                cluster_cache_path = f"second_layer_clusters_{tag}.pkl" if layer == 'second' else f"first_layer_clusters_{tag}.pkl"
                cluster_cache_txt_path = f"second_layer_clusters_{tag}.txt" if layer == 'second' else f"first_layer_clusters_{tag}.txt"
                with open(cluster_cache_path, "wb") as pf:
                    pickle.dump(clusters, pf)
                print(f"Results pickled to {cluster_cache_path}")
                with open(cluster_cache_txt_path, 'w', encoding='utf-8') as f:
                    json.dump(clusters, f, ensure_ascii=False, indent=2)
                return
            except Exception as e:
                latest_e = str(e)
                traceback.print_exc()
        return f"Error: {latest_e}"
    
    async def process_all():
        num_of_dimensions = ['1234','123','123456','123456789','123','1234','1234']
        dimensions = [dimensions_1, dimensions_2, dimensions_3, dimensions_4, dimensions_5, dimensions_6, dimensions_7]
        tasks = []
        if layer == 'second':
            for i in range(1,8):
                if str(i) in first_layer_results:
                    cache_cluster_path = f"second_layer_clusters_{i}.pkl"
                    if os.path.exists(cache_cluster_path):
                        continue
                    cache_path = f"second_layer_results_{i}.pkl"
                    if os.path.exists(cache_path):
                        with open(cache_path, "rb") as pf:
                            second_layer_results = pickle.load(pf)
                        res = []
                        for p in second_layer_results:
                            for orig, c in p:
                                if c[0] in num_of_dimensions[i-1]:
                                    continue
                                res.append(c)
                        tasks.append(asyncio.create_task(process_classifications(res, tag=str(i), dimensions=dimensions[i-1])))
        else:
            res = []
            for p in first_layer_results['other']:
                for c in p:
                    if c[0] in '1234567':
                        continue
                    res.append(c)
            tasks.append(asyncio.create_task(process_classifications(res, tag="0", dimensions='1234567')))

        await asyncio.gather(*tasks)

    asyncio.run(process_all())
        
        
def slotting(layer='second'):
    cache_path = "first_layer_results.pkl"
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as pf:
            first_layer_results = pickle.load(pf)
    cache_path = "first_layer_clusters_0.pkl"
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as pf:
            first_layer_cluster = pickle.load(pf)
    classification_schema = get_openai_json_schema_v3(ClassificationSchemaNum)
    classification_tool_choice = {"type": "function", "function": {"name": classification_schema[0]['function']['name']}}
    llm = LowEffortSlotFillingModels()
    num_of_dimensions = []
    dimensions = []
    for i in range(1,8):
        cache_path = f"second_layer_clusters_{i}.pkl"
        with open(cache_path, "rb") as pf:
            clusters = pickle.load(pf)
            dimensions.append(clusters)
            num_of_dimensions.append(''.join(str(j+1) for j in range(len(clusters))))
    # dimensions = [dimensions_1, dimensions_2, dimensions_3, dimensions_4, dimensions_5, dimensions_6, dimensions_7]
    async def process_slotting(classification_results, i):
        classification_text = "\n".join(f"{idx+1}: {classification_results}" for idx, classification_results in enumerate(classification_results))
        dimensions_text = "\n".join(f"{idx+1} {dim}" for idx, dim in enumerate(dimensions[i-1] if layer == 'second' else first_layer_cluster))
        latest_e = ""
        for _ in range(15):
            try:
                response = await function_call_with_retry(
                    llm,
                    tool_choice=classification_tool_choice,
                    tools=classification_schema,
                    user_prompt=classification_prompt_common.replace("{input}", classification_text).replace("{dimensions}", dimensions_text).replace("{dim_count}", str(len(dimensions[i-1])) if layer == 'second' else '7')
                )
                try:
                    classifications = json.loads(response['classifications'])
                except:
                    classifications = response['classifications']
                if len(classifications) != len(classification_results):
                    print(f"Length mismatch: {len(classifications)} vs {len(classification_results)}, retrying...")
                    raise ValueError("Length mismatch")
                for c in classifications:
                    if layer == 'second':
                        if str(c) not in num_of_dimensions[i-1]:
                            print(f"Found unclassified opinion, retrying...")
                            raise ValueError("Unclassified opinion found")
                    else:
                        if str(c) not in '1234567':
                            print(f"Found unclassified opinion, retrying...")
                            raise ValueError("Unclassified opinion found")
                
                print(f"Response: {response}")
                # Save response to file

                return classifications
            except Exception as e:
                latest_e = str(e)
                traceback.print_exc()
        return f"Error: {latest_e}"
            
    async def process_all():
        tasks = []
        orig_num_of_dimensions = ['1234','123','123456','123456789','123','1234','1234']
        if layer == 'second':
            for i in range(1,8):
                if str(i) in first_layer_results:
                    cache_path = f"second_layer_results_{i}.pkl"
                    if os.path.exists(cache_path):
                        with open(cache_path, "rb") as pf:
                            second_layer_results = pickle.load(pf)
                        res = []
                        for p in second_layer_results:
                            for orig, c in p:
                                if c[0] in orig_num_of_dimensions[i-1]:
                                    continue
                                res.append(c)
                        batch_size = 5
                        batches = [res[j:j + batch_size] for j in range(0, len(res), batch_size)]
                        classifications = [process_slotting(b, i) for b in batches]
                        tasks.append(asyncio.gather(*classifications))
        else:
            res = []
            for p in first_layer_results['other']:
                if p[0] in '1234567':
                    continue
                res.append(p)
            batch_size = 5
            batches = [res[j:j + batch_size] for j in range(0, len(res), batch_size)]
            classifications = [process_slotting(b, 0) for b in batches]
            tasks.append(asyncio.gather(*classifications))
        results = await asyncio.gather(*tasks)
        for i, classifications in enumerate(results):
            res = []
            for l in classifications:
                res.extend(l)
            slotting_cache_path = f"second_layer_slotting_{i+1}.pkl" if layer == 'second' else f"first_layer_slotting_{i}.pkl"
            with open(slotting_cache_path, "wb") as pf:
                pickle.dump(res, pf)
            print(f"Results pickled to {slotting_cache_path}")
            if layer == 'second':
                with open(f"second_layer_slotting_{i+1}.txt", 'w', encoding='utf-8') as f:
                    json.dump(classifications, f, ensure_ascii=False, indent=2)
            else:
                with open(f"first_layer_slotting_{i}.txt", 'w', encoding='utf-8') as f:
                    json.dump(classifications, f, ensure_ascii=False, indent=2)
            
    asyncio.run(process_all())

def count():
    orig_num_of_dimensions = ['1234','123','123456','123456789','123','1234','1234']
    dimensions = [dimensions_1, dimensions_2, dimensions_3, dimensions_4, dimensions_5, dimensions_6, dimensions_7]
    
    with open("first_layer_results.pkl", "rb") as pf: first_layer_results = pickle.load(pf)
    with open("first_layer_slotting_0.pkl", "rb") as pf: first_layer_slotting = pickle.load(pf)
    with open("first_layer_clusters_0.pkl", "rb") as pf: first_layer_clusters = pickle.load(pf)
    with open("second_layer_results_1.pkl", "rb") as pf: second_layer_results_1 = pickle.load(pf)
    with open("second_layer_results_2.pkl", "rb") as pf: second_layer_results_2 = pickle.load(pf)
    with open("second_layer_results_3.pkl", "rb") as pf: second_layer_results_3 = pickle.load(pf)
    with open("second_layer_results_4.pkl", "rb") as pf: second_layer_results_4 = pickle.load(pf)
    with open("second_layer_results_5.pkl", "rb") as pf: second_layer_results_5 = pickle.load(pf)
    with open("second_layer_results_6.pkl", "rb") as pf: second_layer_results_6 = pickle.load(pf)
    with open("second_layer_results_7.pkl", "rb") as pf: second_layer_results_7 = pickle.load(pf)
    second_layer_results = [second_layer_results_1, second_layer_results_2, second_layer_results_3, second_layer_results_4, second_layer_results_5, second_layer_results_6, second_layer_results_7]

    with open("second_layer_slotting_1.pkl", "rb") as pf: second_layer_slotting_1 = pickle.load(pf)
    with open("second_layer_slotting_2.pkl", "rb") as pf: second_layer_slotting_2 = pickle.load(pf)
    with open("second_layer_slotting_3.pkl", "rb") as pf: second_layer_slotting_3 = pickle.load(pf)
    with open("second_layer_slotting_4.pkl", "rb") as pf: second_layer_slotting_4 = pickle.load(pf)
    with open("second_layer_slotting_5.pkl", "rb") as pf: second_layer_slotting_5 = pickle.load(pf)
    with open("second_layer_slotting_6.pkl", "rb") as pf: second_layer_slotting_6 = pickle.load(pf)
    with open("second_layer_slotting_7.pkl", "rb") as pf: second_layer_slotting_7 = pickle.load(pf)
    
    with open("second_layer_clusters_1.pkl", "rb") as pf: second_layer_clusters_1 = pickle.load(pf)
    with open("second_layer_clusters_2.pkl", "rb") as pf: second_layer_clusters_2 = pickle.load(pf)
    with open("second_layer_clusters_3.pkl", "rb") as pf: second_layer_clusters_3 = pickle.load(pf)
    with open("second_layer_clusters_4.pkl", "rb") as pf: second_layer_clusters_4 = pickle.load(pf)
    with open("second_layer_clusters_5.pkl", "rb") as pf: second_layer_clusters_5 = pickle.load(pf)
    with open("second_layer_clusters_6.pkl", "rb") as pf: second_layer_clusters_6 = pickle.load(pf)
    with open("second_layer_clusters_7.pkl", "rb") as pf: second_layer_clusters_7 = pickle.load(pf)

    first_layer_count = {k: len(v) for k, v in first_layer_results.items()}
    first_layer_count_cluster = Counter(first_layer_slotting)
    first_layer_count_other = {cluster: first_layer_count_cluster[idx+1] for idx, cluster in enumerate(first_layer_clusters)}

    second_layer_counts = {}
    second_layer_count_cluster = {1: Counter(second_layer_slotting_1), 2: Counter(second_layer_slotting_2), 3: Counter(second_layer_slotting_3), 4: Counter(second_layer_slotting_4), 5: Counter(second_layer_slotting_5), 6: Counter(second_layer_slotting_6), 7: Counter(second_layer_slotting_7)}
    second_layer_count_other = {1: {cluster: second_layer_count_cluster[1][idx+1] for idx, cluster in enumerate(second_layer_clusters_1)}, 
                                2: {cluster: second_layer_count_cluster[2][idx+1] for idx, cluster in enumerate(second_layer_clusters_2)},
                                3: {cluster: second_layer_count_cluster[3][idx+1] for idx, cluster in enumerate(second_layer_clusters_3)},
                                4: {cluster: second_layer_count_cluster[4][idx+1] for idx, cluster in enumerate(second_layer_clusters_4)},
                                5: {cluster: second_layer_count_cluster[5][idx+1] for idx, cluster in enumerate(second_layer_clusters_5)},
                                6: {cluster: second_layer_count_cluster[6][idx+1] for idx, cluster in enumerate(second_layer_clusters_6)},
                                7: {cluster: second_layer_count_cluster[7][idx+1] for idx, cluster in enumerate(second_layer_clusters_7)},
                                }
    with open("final_counts.txt", 'w', encoding='utf-8') as f:
        print("total", sum(first_layer_count[first_layer] for first_layer in ['1','2','3','4','5','6','7', 'other']))
        f.write(f"total: {sum(first_layer_count[first_layer] for first_layer in ['1','2','3','4','5','6','7', 'other'])}\n")
        for first_layer in ['1','2','3','4','5','6','7', 'other']:
            if first_layer == 'other':
                print(first_layer, first_layer_count[first_layer])
                f.write(f"{first_layer}: {first_layer_count[first_layer]}\n")
                for idx, cluster in enumerate(first_layer_clusters):
                    print(f"  {cluster}: {first_layer_count_other[cluster]}")
                    f.write(f"  {cluster}: {first_layer_count_other[cluster]}\n")
                continue
            print(dimensions_0.splitlines()[int(first_layer)-1], first_layer_count[first_layer])
            f.write(f"{dimensions_0.splitlines()[int(first_layer)-1]}: {first_layer_count[first_layer]}\n")
            _dimensions = dimensions[int(first_layer)-1]
            second_layer_counts[first_layer] = {}
            cnt = Counter()
            for p in second_layer_results[int(first_layer)-1]:
                for orig, c in p:
                    if c[0] in orig_num_of_dimensions[int(first_layer)-1]:
                        cnt[c[0]] += 1
                    else:
                        cnt['new---'] += 1
            second_layer_counts[first_layer] = cnt
            for second_layer in sorted(second_layer_counts[first_layer]):
                if second_layer == 'new---':
                    print(f"  {second_layer}: {second_layer_counts[first_layer][second_layer]}")
                    f.write(f"  {second_layer}: {second_layer_counts[first_layer][second_layer]}\n")
                    continue
                print(f"  {_dimensions.splitlines()[int(second_layer)-1]}: {second_layer_counts[first_layer][second_layer]}")
                f.write(f"  {_dimensions.splitlines()[int(second_layer)-1]}: {second_layer_counts[first_layer][second_layer]}\n")
            for idx, second_layer in enumerate(second_layer_count_other[int(first_layer)]):
                print(f"  {second_layer}: {second_layer_count_other[int(first_layer)][second_layer]}")
                f.write(f"  {second_layer}: {second_layer_count_other[int(first_layer)][second_layer]}\n")

        
    # print("First layer count", first_layer_count)
    # print("First layer count other", first_layer_count_other)
    # print("Second layer counts", second_layer_counts)
    # print("Second layer count other", second_layer_count_other)
    
    # with open("final_counts.txt", 'w', encoding='utf-8') as f:
    #     f.write("First layer count\n")
    #     json.dump(first_layer_count, f, ensure_ascii=False, indent=2)
    #     f.write("\nFirst layer count other\n")
    #     json.dump(first_layer_count_other, f, ensure_ascii=False, indent=2)
    #     f.write("\nSecond layer counts\n")
    #     json.dump(second_layer_counts, f, ensure_ascii=False, indent=2)
    #     f.write("\nSecond layer count other\n")
    #     json.dump(second_layer_count_other, f, ensure_ascii=False, indent=2)
    # print("Final counts written to final_counts.txt")

if __name__ == "__main__":
    # results = read_xlsx_files_with_columns(os.path.dirname(__file__))
    results = read_xlsx_files_with_columns('/Users/andy/repos/NoahAgent/noah_agent/agent/iit/pp/1020', columns=columns_2)
    # print(results)
    # print(len(results))
    # print(len(str(results)))
    # classify_files(results)
    
    # cache_path = '/Users/andy/repos/NoahAgent/noah_agent/extracted_results.pkl'
    # if os.path.exists(cache_path):
    #     with open(cache_path, 'rb') as pf:
    #         extracted_results = pickle.load(pf)
    #     print("Loaded extracted_results from cache.")
    # else:
    #     extracted_results = bucket_slotting_list('/Users/andy/repos/NoahAgent/noah_agent/extraction_results.txt')
    #     with open(cache_path, 'wb') as pf:
    #         pickle.dump(extracted_results, pf)
    #     print("Saved extracted_results to cache.")
    extract_from_files(results)
    extracted_results = read_extracted_results_into_list()
    
    # classify_from_opinions(extracted_results)
    
    # cache_path = "classification_results.pkl"
    # if os.path.exists(cache_path):
    #     with open(cache_path, "rb") as pf:
    #         classification_results = pickle.load(pf)
    # first_layer_lists = get_first_layer_lists(classification_results)

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


    