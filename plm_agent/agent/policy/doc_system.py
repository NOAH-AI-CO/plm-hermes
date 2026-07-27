from datetime import datetime
import os
import time
from typing import List, Dict, Any
import json
import asyncio

from agent.policy.schema import SelectFile, SelectFolder
from agent.policy.prompt import file_selection_prompt, folder_selection_prompt
from llm.composite_models import LowEffortSlotFillingModels as SlotFillingModels
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry

base_policy_dir = '/Users/andy/Desktop/LRAGDemo/lightrag/policy_downloads/digital_archive'
file_filter = ('.DS_Store', '.html')
folder_filter = ('解读','医保动态')
must_include = ('其他文件',)
current_date = datetime.now().strftime('%Y-%m-%d')
def contains(a,b):
    for it in b:
        if it in a:
            return True
    return False
class FileSystemAgent:
    def __init__(self, root_dir: str, max_results: int):
        self.root_dir = root_dir
        self.selected_files = []
        # self.traversal_tasks = []
        self.max_results = max_results
        self.slot_filling_llm = SlotFillingModels(max_retries=0, timeout=15, first_chunk_timeout=10)

    async def get_subdirectories(self, path: str) -> List[str]:
        """Get list of subdirectories in the given path"""
        try:
            items = os.listdir(path)
            subdirs = [item for item in items if os.path.isdir(os.path.join(path, item)) and not contains(item, folder_filter)]
            return subdirs
        except (OSError, PermissionError):
            return []
    
    async def get_files(self, path: str) -> List[str]:
        """Get list of files in the given path"""
        try:
            items = os.listdir(path)
            files = [item for item in items if os.path.isfile(os.path.join(path, item)) and not contains(item, file_filter)]
            return files
        except (OSError, PermissionError):
            return []

    async def select_folders(self, query: str, folders: List[str], current_path: str) -> List[str]:
        """Function call to select relevant folders based on query"""
        folder_schema = get_openai_json_schema_v3(SelectFolder)
        traversal_tasks = []
        must_folders = [f for f in folders if contains(f, must_include)]
        folders = [f for f in folders if (not contains(f, folder_filter) and not contains(f, must_include))]
        for f in must_folders:
            # Directly include folders with must_include keywords
            folder_path = os.path.join(current_path, f)
            traversal_tasks.append(asyncio.create_task(self.traverse_directory(query, folder_path)))
        # This would integrate with an LLM function call
        # For now, returning all folders as placeholder
        if len(folders) > 1:
            select_folders_prompt = folder_selection_prompt.format(query=query, folders=", ".join(folders), current_path=current_path[len(base_policy_dir):] or '/', current_date=current_date)
            tool_choice = {"type": "function", "function": {"name": folder_schema[0]['function']['name']}}
            slot_fill_result = await function_call_with_retry(self.slot_filling_llm, user_prompt=select_folders_prompt, tools=folder_schema, tool_choice=tool_choice, temperature=0.3, max_tokens=8192)
        else:
            slot_fill_result = {"folders": folders}
        # This would integrate with an LLM function call
        # For now, returning all folders as placeholder
        for folder in slot_fill_result.get('folders', []):
            folder_path = os.path.join(current_path, folder)
            traversal_tasks.append(asyncio.create_task(self.traverse_directory(query, folder_path)))
        await asyncio.gather(*traversal_tasks)

    async def select_files(self, query: str, files: List[str], current_path: str) -> List[str]:
        """Function call to select relevant files based on query"""
        files_to_select = []
        for f in files:
            if f == 'detail.json' or len(f) > 15:
                full_path = os.path.join(current_path, f)
                self.selected_files.append(full_path)
            else:
                files_to_select.append(f)
        if len(files_to_select) == 1:
            full_path = os.path.join(current_path, files_to_select[0])
            self.selected_files.append(full_path)
        elif files_to_select:
            file_schema = get_openai_json_schema_v3(SelectFile)
            select_files_prompt = file_selection_prompt.format(query=query, files=", ".join(files), current_path=current_path[len(base_policy_dir):] or '/', current_date=current_date)
            tool_choice = {"type": "function", "function": {"name": file_schema[0]['function']['name']}}
            slot_fill_result = await function_call_with_retry(self.slot_filling_llm, user_prompt=select_files_prompt, tools=file_schema, tool_choice=tool_choice, temperature=0.3, max_tokens=8192)
            # This would integrate with an LLM function call
            # For now, returning all files as placeholder
            full_paths = [os.path.join(current_path, f) for f in slot_fill_result.get('files', [])]
            self.selected_files.extend(full_paths)
    
    async def traverse_directory(self, query: str, current_path: str = None) -> List[str]:
        """Recursively traverse directory structure based on query"""
        if self.max_results and len(self.selected_files) >= self.max_results:
            return self.selected_files

        if current_path is None:
            current_path = self.root_dir

        files = await self.get_files(current_path)
        select_file_task = None
        if files:
            select_file_task = asyncio.create_task(self.select_files(query, files, current_path))
        
        subdirs = await self.get_subdirectories(current_path)
        subdir_traversal_tasks = []
        if subdirs:  # Leaf directory - no more subdirectories
            # Select which folders to explore
            subdir_traversal_tasks.append(asyncio.create_task(self.select_folders(query, subdirs, current_path)))
            
            # Recursively traverse selected folders

        traversal_tasks = subdir_traversal_tasks
        if select_file_task:
            traversal_tasks.append(select_file_task)
        await asyncio.gather(*traversal_tasks)

        return self.selected_files

    async def search_files(self, query: str) -> List[str]:
        """Main method to search for files based on query"""
        self.selected_files = []  # Reset for new search
        await self.traverse_directory(query)
        # await asyncio.gather(*self.traversal_tasks)
        return self.selected_files[:self.max_results]

# Usage


async def main():
    start = time.perf_counter()
    agent = FileSystemAgent(base_policy_dir, max_results=10)
    # question = "罗氏法瑞西单抗在上海属于前三年医保预算单列吗？"
    question = "浙江省关于国谈药品双通道的文件？"
    res = await agent.search_files(question)
    print(len(res), res[:1000])
    end = time.perf_counter()
    print(f"Time taken: {end - start} seconds")

if __name__ == "__main__":
    asyncio.run(main())