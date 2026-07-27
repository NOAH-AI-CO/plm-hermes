# -*- coding: utf-8 -*-
import asyncio
import httpx
import logging
import os
import sys

from config import api_config
from typing import Optional
from utils.hallucination.parser import parse_blocks
from utils.core.httpx_client import HttpxClientSingleton

logger = logging.getLogger(__name__)


class VectaraHallucination:

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._timeout: int = 30
        self._batch_size: int = 20

    @property
    def http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = HttpxClientSingleton.get_asynclient()
        return self._http_client

    async def vectara_hhme(
        self,
        generated_text: str,
        source_texts: list[str]) -> dict:
        """
        Call Vectara API and return parsed JSON response
        
        Returns:
            dict: Parsed JSON response
        """
        url = f"{api_config.VECTARA_API_URL}/v2/evaluate_factual_consistency"
        
        payload = {
            "model_parameters": {
                "model_name": "hhem_v2.3"
            },
            "generated_text": generated_text,
            "source_texts": source_texts,
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'x-api-key': api_config.VECTARA_API_KEY,
        }
        
        # async with self.http_client as client:
        #     response = await client.post(
        #         url,
        #         json=payload,
        #         headers=headers,
        #         timeout=self._timeout
        #     )
        #     response.raise_for_status()
        #     return response.json()  # Returns dict instead of string

        response = await self.http_client.post(
            url,
            json=payload,
            headers=headers,
            timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()


    async def summary(
        self,
        summary: str,
        source_texts: list[str],
    ):
        blocks = parse_blocks(summary)
        
        # Filter out heading blocks and prepare texts for verification
        texts_to_verify = []
        
        for block in blocks:
            block_type = block.get('type')
            
            # Skip heading blocks
            if block_type == 'heading':
                continue

            # Process paragraph blocks
            elif block_type == 'paragraph' and block.get('text'):
                texts_to_verify.append({
                    'id': block.get('id', ''),
                    'text': block.get('text', '')
                })
            
            # Process table blocks - convert each row to text
            elif block_type == 'table_row' and block.get('rows'):
                rows = block.get('rows', [])
                texts_to_verify.append({
                    'id': block.get('id', ''),
                    'text': ('|').join(rows)
                })
        
        # Batch process texts_to_verify, 20 items per batch to avoid overwhelming the service
        results = []
        
        for i in range(0, len(texts_to_verify), self._batch_size):
            batch = texts_to_verify[i:i + self._batch_size]
            logger.info(f"Processing batch {i // self._batch_size + 1}, items {i + 1}-{min(i + self._batch_size, len(texts_to_verify))}")
            
            # Process batch concurrently
            # Note: asyncio.gather() guarantees that results maintain the same order as tasks
            batch_tasks = [
                self.vectara_hhme(
                    generated_text=item['text'],
                    source_texts=source_texts
                )
                for item in batch
            ]
            
            # return_exceptions=True ensures one failure doesn't break the entire batch
            # and maintains order of results matching the order of batch_tasks
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Combine results with item IDs
            # zip() maintains order: batch[0] pairs with batch_results[0], etc.
            for item, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        'id': item['id'],
                        'result': None,
                        'error': str(result)
                    })
                else:
                    results.append({
                        'id': item['id'],
                        'result': result
                    })

        # Combine results back to blocks
        # Create a mapping from id to result for quick lookup
        result_map = {}
        for result_item in results:
            block_id = result_item['id']
            if 'error' in result_item:
                result_map[block_id] = {'error': result_item['error']}
            else:
                result_map[block_id] = result_item.get('result')
        
        # Add verification results back to blocks
        for block in blocks:
            block_id = block.get('id', '')
            if block_id in result_map:
                block['verification_score'] = result_map[block_id]
        
        return blocks


async def test_vectara():
    vectara: VectaraHallucination = VectaraHallucination()

    source_texts: str = """| 药物 | 分子结构 | 结合靶点 | 药理特点 | 给药方案 |
|------|----------|----------|----------|----------|
| Erenumab | 人IgG2 | CGRP受体 | 竞争性阻断CLR/RAMP1复合体 | 70-140mg皮下注射，每月一次 |
| Fremanezumab | 人源化IgG2 | CGRP α/β配体 | 高亲和度中和游离CGRP | 225mg/月或675mg/季，皮下注射 |
| Galcanezumab | 人源化IgG4 | CGRP α/β配体 | 抑制辣椒素诱导血管扩张 | 首剂240mg，其后120mg/月，皮下注射 |
| Eptinezumab | 人源化IgG1 | CGRP α/β配体 | 静脉给药30分钟内达峰 | 100-300mg静脉滴注，每12周一次 |
    """
    generated_text: str = "| Fremanezumab | 人源化IgG2 | CGRP α/β配体 | 高亲和度中和游离CGRP | 225mg/月或675mg/季，口服 |"

    #result = await vectara.vectara_hhme(generated_text, [source_texts])
    result = await vectara.summary(generated_text, [source_texts])

    print(result)

if __name__ == "__main__":
    asyncio.run(test_vectara())
