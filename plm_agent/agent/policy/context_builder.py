from datetime import datetime
import os
import time
from typing import List, Dict, Any
import json
import asyncio

from agent.policy.prompt import context_extraction_prompt
from llm.composite_models import DeepseekChatModels as ExtractionModels

current_date = datetime.now().strftime('%Y-%m-%d')
# Load sh.md file and store in sh_text
sh_text = ""
with open('agent/policy/sh.md', 'r', encoding='utf-8') as f:
    sh_text = f.read()

prompt = context_extraction_prompt.format(current_date=current_date, input_text=sh_text[:5000])

llm = ExtractionModels()

async def main():
    async for chunk in llm.stream_call(user_prompt=prompt):
        print(chunk, sep='')

asyncio.run(main())