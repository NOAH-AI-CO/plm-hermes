import os
import json
import asyncio

from elasticsearch import Elasticsearch
from llm.gcp_models import Gemini25Pro

from agent.iit.utils.db import write_iit_context
os.environ['no_proxy'] = '*'

from agent.iit.utils.guidelines.embedding import get_embedding

from agent.iit.utils.guidelines.es_guideline_fetch import fetch_guideline_by_id
from agent.explore.mindsearch_clinical_guidance_agent import MindSearchClinicalGuideline
from config import api_config, settings


llm = Gemini25Pro()

# First, create the index with proper mappings
index_name = "guidelines"
    
async def guidelines_analysis(q, ctx, iit_protocol=""):
    query_vector = get_embedding(q)
        
    # Ping ES first before doing the search
    es_client = Elasticsearch(hosts=settings.HW_ELASTICSEARCH_URL, basic_auth=(settings.HW_ELASTICSEARCH_USERNAME, settings.HW_ELASTICSEARCH_PASSWORD))

    try:
        max_attempts = 3
        backoff = 1
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = es_client.search(
                    index=index_name,
                    size=5,
                    query={"match": {"description": q}},
                    knn={
                    "field": "name_vector",
                    "query_vector": query_vector,
                    "k": 5,
                    "num_candidates": 10,
                    },
                )
                break
            except Exception as e:
                last_exc = e
                print(f"Elasticsearch search attempt {attempt} failed: {e}")
                # try to reinitialize client before next attempt
                if attempt < max_attempts:
                    await asyncio.sleep(backoff)
                    backoff *= 2
        else:
            # all attempts failed; propagate the last exception to be handled by outer except
            raise last_exc
    except Exception as e:
        print("Elasticsearch search failed:", e)
        return None
    ret = []
    for hit in resp["hits"]["hits"]:
        item = {}
        for key in ['id', 'name', 'description']:
            item[key] = hit['_source'][key]
        ret.append(item)
        
    async def select_guideline(ret):
        sys_prompt = f"""
        You are a medical guideline selection expert. Your task is to select the most relevant clinical guideline from the search results that best matches the user's query.

        You will be given:
        1. Original query: {q}
        2. Search results with guidelines: {json.dumps(ret, indent=2)}

        Analyze each guideline based on:
        - Relevance to the original query
        - Specificity and accuracy of the guideline description
        
        If none of the guidelines are relevant, respond with "None".

        Return ONLY the id field of the most appropriate guideline as a single string, with no additional explanation.
    """
        ret = await llm(sys_prompt=sys_prompt, user_prompt="")
        if hasattr(ret, 'content'):
            ret = ret.content.strip()
        if ret == "None":
            return None
        return ret
    print(str(ret)[:50])

    selected_guideline_id = await select_guideline(ret)
    if not selected_guideline_id:
        print("No relevant guidelines found.")
        return None
    print("Selected Guideline ID:", selected_guideline_id)

    background = await fetch_guideline_by_id(selected_guideline_id)


    agent = MindSearchClinicalGuideline()
    guide_kwargs = {
        'params': 
        {'language': 'CN', 
         'model': '', 
         'enable_rag': False, 
         'files': [], 
         'reference': selected_guideline_id, 
         'reference_type': 'clinical-guideline', 
         'background': json.dumps(background)
         }
        }

    async def run_guideline_agent(guide_kwargs, iit_protocol=iit_protocol):
        user_prompt = f"""Given the clinical guideline and the IIT protocol details, please analyze whether the IIT protocol '{iit_protocol}' adheres to the relevant rules and recommendations specified in the guideline.
    <IIT Protocol>
    Specifically, evaluate:
    1. Does the protocol follow the diagnostic criteria outlined in the guideline?
    2. Does the treatment approach align with guideline recommendations?
    3. Are there any deviations or conflicts between the protocol and the guideline?
    4. If there are deviations, are they justified or potentially problematic?

    Provide a detailed analysis with specific references to both the guideline and protocol."""
        ret = None
        async for chunk in agent.start_wo_dump(user_prompt=user_prompt, **guide_kwargs):
            if isinstance(chunk, dict):
                content = chunk.get('content') or ''
                if content:
                    ret = content
        if hasattr(ret, 'content'):
            ret = ret.content.strip()
        return ret
                
    anaylsis_result = await run_guideline_agent(guide_kwargs, iit_protocol=iit_protocol)
    print("Analysis Result:", anaylsis_result[:200])
    ctx.progress += 20
    ctx.clinical_guidance_result = anaylsis_result
    await write_iit_context(ctx)
    return anaylsis_result


if __name__ == "__main__":
    # Check if index exists, if not create it with mappings
    client = Elasticsearch(hosts=settings.HW_ELASTICSEARCH_URL, basic_auth=(settings.HW_ELASTICSEARCH_USERNAME, settings.HW_ELASTICSEARCH_PASSWORD))
    if not client.indices.exists(index=index_name):
        mappings = {
            "properties": {
                "id": {"type": "keyword"},
                "name": {"type": "text"},
                "name_vector": {
                    "type": "dense_vector",
                    "dims": 1024,  # Adjust based on your embedding model
                    "index": True,
                    "similarity": "cosine"
                },
                "description": {"type": "text"},
                "source": {"type": "keyword"},
                "version": {"type": "keyword"},
            }
        }
        client.indices.create(index=index_name, mappings=mappings)
        
    guidelines_analysis("early stage non-small-cell lung cancer", iit_protocol="None")