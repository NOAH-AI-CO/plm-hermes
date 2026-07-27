import os
import json
import traceback

from agent.iit.v3.guidelines.es_indexing import index_doc
from agent.iit.v3.guidelines.es_indexing import client
from agent.iit.gl_toc_builder import run_on_path
import asyncio

from agent.iit.v3.guidelines.check_pdf_type import classify_pdf

path = "/Users/andy/Downloads/医脉通"
missing_cn_title_cnt = 0
missing_en_title_cnt = 0


async def batch_processing():
    needs_processing = 0
    newest_cnt = 0
    deleted_cnt = 0
    tasks = []
    img_pdfs = []
    skipped = 0
    # Fetch all documents that already have a TOC and are Chinese guidelines
    query = {
        "query": {
            "bool": {
                "must": [
                    {"exists": {"field": "toc"}},
                    {"term": {"cn_file_flg.keyword": "Y"}}
                ]
            }
        },
        "_source": ["id"],
        "size": 10000  # Adjust size as needed, or use the scroll API for very large result sets
    }
    
    response = client.search(index="guidelines", body=query)
    processed_ids = {hit['_source']['id'] for hit in response['hits']['hits']}
    processed_ids = set()
    # Use the scroll API to fetch all matching document IDs
    scroll_response = client.search(
        index="guidelines",
        body=query,
        scroll="2m"  # Keep the search context alive for 2 minutes
    )
    
    scroll_id = scroll_response.get('_scroll_id')
    hits = scroll_response['hits']['hits']
    
    while scroll_id and hits:
        processed_ids.update({hit['_source']['id'] for hit in hits})
        
        scroll_response = client.scroll(
            scroll_id=scroll_id,
            scroll="2m"
        )
        
        scroll_id = scroll_response.get('_scroll_id')
        hits = scroll_response['hits']['hits']

    # Clear the scroll context
    if scroll_id:
        client.clear_scroll(scroll_id=scroll_id)

    print(f"Found {len(processed_ids)} already processed guidelines with TOC.")

    processed_count = 0
    for root, dirs, files in os.walk(path):
        if processed_count >= 10:
            break
            
        pdf_file_path = None
        json_file_path = None
        for file in files:
            if file.endswith('.pdf'):
                pdf_file_path = os.path.join(root, file)
        for file in files:
            if file.endswith('.json'):
                json_file_path = os.path.join(root, file)
        if not pdf_file_path:
            # print("No PDF found in", root)
            continue
        _json_cnt = 0
        # if json_file_path:
        #     continue
        if not json_file_path:
            for d in dirs:
                for _root, _, files in os.walk(os.path.join(root, d)):
                    for file in files:
                        if file.endswith('.json'):
                            json_file_path = os.path.join(_root, file)
                            _json_cnt += 1
            if not _json_cnt:
                # print("No PDF found in", d)
                print("Missing JSON for PDF:", pdf_file_path)
            elif _json_cnt>1:
                print("Multiple JSONs found for PDF:", pdf_file_path)
                continue
            
        try:
            obj = None
            if json_file_path:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    obj = json.load(f)
                    # if obj['data']['id'] != 27938:
                    #     continue
                    if 'data' in obj and 'content' in obj['data']:
                        if obj['data'].get('publish_date', '') and obj['data'].get('back_ver', []):
                            newest = sorted(obj['data']['back_ver'], key=lambda x: x['publish_date'], reverse=True)[0]
                            if newest['publish_date'] > obj['data']['publish_date']:
                                client.update_by_query(index="guidelines", body={"script": {"source": "ctx._source.remove('toc')", "lang": "painless"}, "query": {"term": {"id": obj['data']['id']}}})
                                # client.delete_by_query(index="guidelines", body={"query": {"term": {"id": obj['data']['id']}}}, ignore_unavailable=True)
                                # deleted_cnt += 1
                                print(f"Skipping due to newer version available for id {obj['data']['id']}")
                                continue
                    else:
                        print(f"No content found in {json_file_path}")
                        continue
            else:
                from hashlib import md5
                dummy_id = int(md5(pdf_file_path.encode('utf-8')).hexdigest()[:15], 16)
                obj = {"data": {"id": dummy_id, "title_cn": os.path.basename(pdf_file_path), "title_en": ""}}

            if not classify_pdf(pdf_file_path):
                skipped += 1
                img_pdfs.append((obj['data']['id'] if obj and 'data' in obj else pdf_file_path))
                print(f"Image-based PDF {pdf_file_path}, skipping")
                continue
            # needs_processing += 1
            if len(tasks) >= 50:
                # Wait for the first task to complete
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks = list(pending)
            
            # Ensure document is established in Elasticsearch before adding pages and TOC
            if json_file_path:
                try:
                    index_doc(json_file_path)
                except Exception as e:
                    print(f"Failed to initial-index {json_file_path}: {e}")
                    continue
            else:
                try:
                    from agent.iit.utils.guidelines.embedding import get_embedding
                    doc = {
                        "id": obj["data"]["id"],
                        "title_cn": obj["data"]["title_cn"],
                        "title_en": obj["data"]["title_en"],
                        "title_cn_vector": get_embedding(obj["data"]["title_cn"]) if obj["data"]["title_cn"] else None,
                        "title_en_vector": get_embedding(obj["data"]["title_en"]) if obj["data"]["title_en"] else None,
                    }
                    client.index(index="guidelines", id=obj["data"]["id"], document=doc, refresh=True)
                except Exception as e:
                    print(f"Failed to initial-index generated dummy for {pdf_file_path}: {e}")
                    continue
            
            task = asyncio.create_task(asyncio.wait_for(run_on_path(pdf_file_path, obj), timeout=1500.0))
            tasks.append(task)
            processed_count += 1
            print(f"Added task {processed_count}: {pdf_file_path}")
                    
        except Exception as e:
            with open('updated_gl_ids.txt', 'a') as f:
                f.write(f"Error reading {json_file_path}: {e}\n")
            print(f"Error reading {json_file_path}: {e}")
            traceback.print_exc()
            print(obj)
    with open('img_pdfs.txt', 'w') as f:
        f.write(str(img_pdfs))
    try:
        if tasks:
            _, pending = await asyncio.wait(tasks)
            print("Batch processing completed.")
            print("Pending", pending)
            with open('updated_gl_ids.txt', 'a') as f:
                f.write(f"Pending: {pending}\n")
    except Exception as e:
        with open('updated_gl_ids.txt', 'a') as f:
            f.write(f"Error reading {json_file_path}: {e}\n")
        print(f"Error reading {json_file_path}: {e}")
        print(obj)
    # print("Needs processing count:", needs_processing)
    # print("Newest count:", newest_cnt)
    # print("Deleted count:", deleted_cnt)
    
# client.indices.put_settings(index="guidelines", body={"index.blocks.write": False})
asyncio.run(batch_processing())

# Count the total number of documents in the index
# count_response = client.count(index='guidelines')
# print(f"Total documents in 'guidelines' index: {count_response['count']}")
# # Get all unique IDs from the index
# all_ids_query = {
#     "query": {"match_all": {}},
#     "_source": ["id"],
#     "size": 10000
# }

# unique_ids = set()

# # Use the scroll API to fetch all document IDs
# scroll_response = client.search(
#     index="guidelines",
#     body=all_ids_query,
#     scroll="2m"  # Keep the search context alive for 2 minutes
# )

# scroll_id = scroll_response.get('_scroll_id')
# hits = scroll_response['hits']['hits']

# print("Fetching all unique IDs...")
# while scroll_id and hits:
#     for hit in hits:
#         if 'id' in hit['_source']:
#             unique_ids.add(hit['_source']['id'])
    
#     scroll_response = client.scroll(
#         scroll_id=scroll_id,
#         scroll="2m"
#     )
    
#     scroll_id = scroll_response.get('_scroll_id')
#     hits = scroll_response['hits']['hits']

# # Clear the scroll context
# if scroll_id:
#     client.clear_scroll(scroll_id=scroll_id)

# unique_ids_set = set(unique_ids)
# print(f"Found {len(unique_ids_set)} unique IDs.")

# unique_ids_set_2 = set() 
# for root, dirs, files in os.walk(path):
#     for file in files:
#         if file.endswith('.json'):
#             file_path = os.path.join(root, file)
#             with open(file_path, 'r', encoding='utf-8') as f:
#                 obj = json.load(f)
#                 if 'data' in obj and 'content' in obj['data']:
#                     if obj['data'].get('publish_date', '') and obj['data'].get('back_ver', []):
#                         newest = sorted(obj['data']['back_ver'], key=lambda x: x['publish_date'], reverse=True)[0]
#                         if newest['publish_date'] > obj['data']['publish_date']:
#                             continue
#                 if obj['data']['id'] in unique_ids_set_2:
#                     print("Duplicate ID found:", obj['data']['id'], file_path)
#                 unique_ids_set_2.add(obj['data']['id'])

# print(f"Found {len(unique_ids_set_2)} unique IDs from JSON files.")

# with open('unique_ids_set.txt', 'w') as f:
#     f.write(str(unique_ids_set))

# with open('unique_ids_set_2.txt', 'w') as f:
#     f.write(str(unique_ids_set_2))
    
# count_a = 0
# count_b = 0
# pdf_cnt = 0
# json_cnt = 0
# missing_json_cnt = 0
# missing_pdf_cnt = 0
# for root, dirs, files in os.walk(path):
#     pdf_file_path = None
#     json_file_path = None
#     # pdf_cnt = 0
#     # json_cnt = 0
#     for file in files:
#         if file.endswith('.pdf'):
#             pdf_cnt += 1
#             pdf_file_path = os.path.join(root, file)
#     for file in files:
#         if file.endswith('.json'):
#             json_cnt += 1
#             json_file_path = os.path.join(root, file)
#     # if pdf_cnt>1:
#     #     print("Multiple PDFs found in", root, files)
#     # if json_cnt>1:
#     #     print("Multiple JSONs found in", root)
#     # if pdf_file_path and not json_file_path:
#     #     # print("No JSON found in", root)
#     #     count_a += 1
#     #     # print("Missing JSON for PDF:", pdf_file_path)
#     #     continue
    
#     # if pdf_file_path and not json_file_path:
#     #     # print("No PDF found in", root)
#     #     count_b += 1
#     #     # print("Missing PDF for JSON:", json_file_path)
#     #     _json_cnt = 0 
#     #     for d in dirs:
#     #         for _, _, files in os.walk(os.path.join(root, d)):
#     #             for file in files:
#     #                 if file.endswith('.json'):
#     #                     # pdf_file_path = os.path.join(root, file)
#     #                     _json_cnt += 1
#     #     if not _json_cnt:
#     #         # print("No PDF found in", d)
#     #         missing_json_cnt += 1
#     #         print("Missing JSON for PDF:", pdf_file_path)
#     #     if _json_cnt>1:
#     #         print("Multiple JSONs found for PDF:", pdf_file_path)
            
#     # if json_file_path and not pdf_file_path:
#     #     # print("No PDF found in", root)
#     #     # count_b += 1
#     #     # print("Missing PDF for JSON:", json_file_path)
#     #     _pdf_cnt = 0 
#     #     for d in dirs:
#     #         for _, _, files in os.walk(os.path.join(root, d)):
#     #             for file in files:
#     #                 if file.endswith('.pdf'):
#     #                     # pdf_file_path = os.path.join(root, file)
#     #                     _pdf_cnt += 1
#     #     if not _pdf_cnt:
#     #         # print("No PDF found in", d)
#     #         missing_pdf_cnt += 1
#     #         # print("Missing PDF for JSON:", json_file_path)
#     #     if _pdf_cnt>1:
#     #         print("Multiple PDFs found for JSON:", json_file_path)
# # print("Total PDFs found:", pdf_cnt)
# # print("Total JSONs found:", json_cnt)

# # print("PDF without JSON count:", count_a)
# # print("JSON without PDF count:", count_b)
# # print("Missing JSON count:", missing_json_cnt)

# print("Missing PDF count:", missing_pdf_cnt)
