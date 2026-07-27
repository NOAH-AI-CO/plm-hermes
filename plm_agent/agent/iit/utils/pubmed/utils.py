import asyncio
import json
import traceback
import logging
from llm.gcp_models import Gemini25Pro
from agent.explore.mindsearch_agent_v3_pubmed import MindSearchPubMedHitlAgent
from agent.iit.utils.db import write_iit_context
from utils.pubmed_opt.pubmed_reader import PubMedReader
pubmed_reader = PubMedReader()
llm = Gemini25Pro()

logger = logging.getLogger(__name__)

async def select_article(articles, q):
    sys_prompt = f"""
    You are a medical literature selection expert. Your task is to select the most relevant PubMed article from the search results that best matches the user's query.

    You will be given:
    1. Original query: {q}
    2. Search results with PubMed articles: {json.dumps(articles, indent=2)}

    Analyze each article based on:
    - Relevance to the original query
    - Specificity and accuracy of the article description
    
    If none of the articles are relevant, respond with "None".

    Return ONLY the pmcid (not pmid) field of the most appropriate article as a single string, with no additional explanation.
"""
    ret = await llm(sys_prompt=sys_prompt, user_prompt="")
    if hasattr(ret, 'content'):
        ret = ret.content.strip()
        if ret == "None":
            return None
    print("Selected PubMed Article PMCID:", ret)
    for a in articles:
        articleids = a.get('articleids', [])
        for aid in articleids:
            if aid.get('idtype', '') == 'pmcid' and aid.get('value', '') == ret:
                a['pmcid'] = ret
                return a
    return ret

async def run_pubmed_analysis(pubmed_articles, iit_protocol=""):
    user_prompt = f"""Given the PubMed articles and the IIT protocol details, please analyze whether the IIT protocol adheres to the relevant findings and recommendations from the research article.
<Pubmed Articles>
{json.dumps(pubmed_articles, indent=2)}
</Pubmed Articles>
<IIT Protocol>
{iit_protocol}
</IIT Protocol>

Specifically, evaluate:
1. Does the protocol follow the diagnostic or assessment criteria outlined in the article?
2. Does the treatment approach align with the findings and recommendations from the article?
3. Are there any deviations or conflicts between the protocol and the article's findings?
4. If there are deviations, are they justified or potentially problematic?

Provide a detailed analysis with specific references to both the article and protocol."""
    ret = await llm(user_prompt=user_prompt)
    if hasattr(ret, 'content'):
        ret = ret.content.strip()
    return ret

async def pubmed_analysis(ctx, pubmed_query, content):
    from utils.pubmed_opt.pubmed_search import PubMedSearch
    pubmed_search = PubMedSearch()
    selected = {}
    results = await pubmed_search.hybrid_search(pubmed_query, max_results=5)
    pmcid_results = []
    for a in results:
        articleids = a.get('articleids', [])
        for aid in articleids:
            if aid.get('idtype', '') == 'pmcid' and aid.get('value', ''):
                pmcid_results.append(a)
    selected = await select_article(pmcid_results, pubmed_query)
    pubmed_reader = PubMedReader()
    pmc_article = None
    start_time = asyncio.get_event_loop().time()
    if selected:
        pmc_article = await pubmed_reader.read_pmc_batch(pmcids=[selected.get('pmcid')])
    end_time = asyncio.get_event_loop().time()
    print(f"PubMed article read time: {end_time - start_time} seconds")
    article = results[:1]
    if article:
        result = await run_pubmed_analysis(article, iit_protocol=content)
        ctx.pubmed_result = result
        return result
    return None

async def run_pubmed_agent(ctx, pubmed_query, content):
    try:
        agent = MindSearchPubMedHitlAgent()
        step_body = {
            "user_prompt": pubmed_query,
            "history_messages": [],
            "agent": "mindsearchpubmed",
            "skip_followup": True,
            "params":{
                "language": 'CN',
                "model": "",
                "enable_rag": True,
                "is_hitl": True,
                }
        }
        generator = agent.start_wo_dump(**step_body)
        content = ""
        async for chunk in generator:
            content = chunk
        if isinstance(content, dict):
            content = content.get('content') or ''
        ctx.pubmed_result = content
        await write_iit_context(ctx)
        return content
    except Exception as e:
        logger.error(f"[PubMedAgent] run_pubmed_agent error: {str(e)}\n{traceback.format_exc()}", stacklevel=2, stack_info=True)
        return None