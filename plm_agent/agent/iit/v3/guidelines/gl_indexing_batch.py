import os
import json
import traceback

from agent.iit.v3.guidelines.es_indexing import client, ensure_guidelines_index
from agent.iit.gl_toc_builder import run_on_path
import asyncio

from agent.iit.v3.guidelines.check_pdf_type import classify_pdf

path = "/Users/andy/Downloads/2025NCCN指南（中英文）/25年nccn英文"
missing_cn_title_cnt = 0
missing_en_title_cnt = 0


async def batch_processing():
    needs_processing = 0
    newest_cnt = 0
    deleted_cnt = 0
    tasks = []
    img_pdfs = []
    skipped = 0
    # Ensure index exists before querying
    ensure_guidelines_index()
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
    from hashlib import md5
    from agent.iit.utils.guidelines.embedding import get_embedding
    for root, dirs, files in os.walk(path):
        if processed_count >= 10:
            break
        pdf_files = [f for f in files if f.endswith('.pdf')]

        for pdf_filename in pdf_files:
            if processed_count >= 10:
                break
            pdf_file_path = os.path.join(root, pdf_filename)
            dummy_id = int(md5(os.path.basename(pdf_file_path).encode('utf-8')).hexdigest()[:15], 16)
            obj = {"data": {"id": dummy_id, "title_cn": os.path.basename(pdf_file_path), "title_en": ""}}

            try:
                if not classify_pdf(pdf_file_path):
                    skipped += 1
                    img_pdfs.append(obj['data']['id'])
                    print(f"Image-based PDF {pdf_file_path}, skipping")
                    continue
                # needs_processing += 1
                if len(tasks) >= 50:
                    # Wait for the first task to complete
                    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)

                try:
                    doc = {
                        "id": obj["data"]["id"],
                        "title_cn": obj["data"]["title_cn"],
                        "title_en": obj["data"]["title_en"],
                        "title_cn_vector": get_embedding(obj["data"]["title_cn"]) if obj["data"]["title_cn"] else None,
                        "title_en_vector": get_embedding(obj["data"]["title_en"]) if obj["data"]["title_en"] else None,
                    }
                    client.index(index="guidelines", id=obj["data"]["id"], document=doc, refresh=True)
                except Exception as e:
                    print(f"Failed to initial-index {pdf_file_path}: {e}")
                    continue

                task = asyncio.create_task(asyncio.wait_for(run_on_path(pdf_file_path, obj), timeout=1500.0))
                tasks.append(task)
                processed_count += 1
                print(f"Added task {processed_count}: {pdf_file_path}")

            except Exception as e:
                with open('updated_gl_ids.txt', 'a') as f:
                    f.write(f"Error processing {pdf_file_path}: {e}\n")
                print(f"Error processing {pdf_file_path}: {e}")
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
