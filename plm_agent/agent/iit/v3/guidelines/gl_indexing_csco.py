import os
import json

from agent.iit.gl_toc_builder import run_on_pages
import asyncio
from collections import defaultdict

path = "/Users/andy/Downloads/home/noahai/csco/2025CSCO完全汇总全31本"
csco = defaultdict(list)

for root, dirs, files in os.walk(path):
    # print("sorted(files):", sorted(files))
    for file in sorted(files):
        if file.endswith('.json'):
            file_path = os.path.join(root, file)
            splitted = file.split('.')
            id = int(splitted[0])
            name = splitted[1].rstrip('12')
            with open(file_path, 'r', encoding='utf-8') as f:
                pages = json.load(f)
            csco[str(id)+'.'+name]+=pages
            
# for key in csco:
#     splitted = key.split('.')
#     id = int(splitted[0])
#     name = splitted[1]
#     pages = csco[key]
#     print(f"Inserting {key} with {len(pages)} pages")
#     insert_index(pages, id+50000, name)
            
async def batch_processing():
    tasks = []
    for key in csco:
        if len(tasks) >= 50:
            # Wait for the first task to complete
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            tasks = list(pending)
        splitted = key.split('.')
        id = int(splitted[0]) + 50000
        task = asyncio.create_task(asyncio.wait_for(run_on_pages(csco[key], id), timeout=1500.0))
        tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks)
        
asyncio.run(batch_processing())