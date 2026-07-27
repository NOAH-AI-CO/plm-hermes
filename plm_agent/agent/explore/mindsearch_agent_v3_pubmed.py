# -*- coding: utf-8 -*-
import logging

from datetime import datetime

from agent.core.preset import AgentPreset
import agent.explore.constants as constants
from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3
from llm.base_model import BaseLLM
from llm.azure_models import GPT51, GPT54Mini, GPT5Nano, GPT52
from tools.core.base_tool import BaseTool
import copy

from tools.explore.mindsearch_tools_v3 import (
    PubMedArticlesLocalSearch,
    PubMedArticlesSearch,
    DocumentReader,
    DocumentSearchFinished,
)


from agent.explore.mindsearch_prompt_v3 import (
    gpt_5_search_final_output_thesis_pt, gpt_pubmed_sys_pt, gpt_query_rewrite_user_pt,
    gpt_o_search_final_output_user_pt,
)


logger = logging.getLogger(__name__)


class MindSearchPubMedThinkingAgent(AgentPreset):
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: list[BaseTool] = [
        PubMedArticlesLocalSearch,
        PubMedArticlesSearch,
        DocumentReader,
        DocumentSearchFinished,
    ]
    tool_choice: str = "required"


class MindSearchFinalOutputAgent(AgentPreset):
    llm: BaseLLM = GPT52
    sys_prompt: str = ''
    tools: list[BaseTool] = []


class MindSearchPubMedHitlAgent(MindSearchAgentV3):
    
    thinking_agent: MindSearchPubMedThinkingAgent = MindSearchPubMedThinkingAgent()
    final_output_agent: MindSearchFinalOutputAgent =  MindSearchFinalOutputAgent()

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str):
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        user_prompt = gpt_query_rewrite_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return gpt_pubmed_sys_pt, user_prompt

    async def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: list[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH
    ):
        # Response user's question
        websearch_results = self._format_final_searchresults(runtime_info, history_messages)

        final_user_prompt = gpt_o_search_final_output_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language,
            background=background,
            websearch_results=websearch_results,
            user_question=user_prompt)
        
        return gpt_5_search_final_output_thesis_pt, final_user_prompt





async def fetch_pubmed_articles_by_existing_logic(
    query: str,
    language: str = "en",
    priority_pmids: list[str] | None = None,
) -> dict[str, any]:
    """
    直接复用 MindSearchPubMedHitlAgent 现有逻辑：
    - 让 agent 自己重写 query
    - 让 agent 自己决定用本地 PubMed 还是远端 PubMed
    - 让 agent 自己决定是否需要 DocumentReader 读原文

    返回:
    {
        "articles": [...],          # PubMed 搜索结果原始片段
        "document_contents": [...], # 如果 agent 读了原文，这里有精读内容
        "runtime_info": ...,        # 所有信息
    }
    """
    agent = MindSearchPubMedHitlAgent()

    init_response = None
    background = ""
    runtime_info = None
    history_messages = []
    lang = language

    # 1. 复用原来的初始化逻辑
    async for response, bg, rt, lg, hms in agent._init_agent(
        user_prompt=query,
        history_messages=[],
        images=[],
        language=language,
        params={"language": language},
        priority_pubmed_ids=priority_pmids or [],
    ):
        # _init_agent 前几个 yield 是给前端占位用的
        if rt is not None:
            init_response = response
            background = bg
            runtime_info = rt
            history_messages = hms
            lang = lg

    if runtime_info is None:
        return {
            "articles": [],
            "document_contents": [],
            "runtime_info": {},
        }

    # 2. 复用 agent 自己的 thinking 流程
    # 这里会自动：
    # - query rewrite
    # - LocalSearch / RemoteSearch
    # - 是否调用 DocumentReader
    await agent._thinking(
        init_response,
        runtime_info,
        query,
        copy.deepcopy(history_messages),
        background,
        lang,
    )

    # 3. 从 runtime_info 里提取 PubMed 原始片段
    articles: list[dict[str, any]] = []
    for tool_result in runtime_info.get("tool_results", []):
        tool_name = getattr(tool_result, "name", "")
        result = getattr(tool_result, "result", None)

        if tool_name in [PubMedArticlesLocalSearch.__name__, PubMedArticlesSearch.__name__]:
            if isinstance(result, list):
                for item in result:
                    if not isinstance(item, dict):
                        continue
                    articles.append(item)

    # 去重（按 PMID）
    dedup_articles = []
    seen_pmids = set()
    for item in articles:
        pmid = str(item.get("uid") or item.get("pmid") or "")
        if not pmid or pmid in seen_pmids:
            continue
        seen_pmids.add(pmid)
        dedup_articles.append(item)

    # 4. 从 url_content_map 里提取“读原文后的内容”
    # 注意：这里是 DocumentReader 处理后的内容，不一定是完整原文，
    # 更接近“精读后的文章内容片段”
    document_contents: list[dict[str, any]] = []
    url_content_map = runtime_info.get("url_content_map", {})
    url_map = runtime_info.get("url_map", {})

    for url, content in url_content_map.items():
        link = url_map.get(url)
        if not link:
            continue

        if getattr(link, "type", None) is None:
            continue

        document_contents.append({
            "url": url,
            "title": getattr(link, "title", ""),
            "pubmed_id": getattr(link, "pubmed_id", ""),
            "pmcid": getattr(link, "pmcid", ""),
            "doi": getattr(link, "doi", ""),
            "content": content,
        })

    return {
        "articles": dedup_articles,
        "document_contents": document_contents,
        "runtime_info": runtime_info,
    }

async def pubmed_hybrid_search(
    query: str,
    years: list[int] | None = None,
) -> dict:
    """
    首页 文章详情接口，用本地 PubMed hybrid_search（ES BM25 + Milvus 向量融合）搜索文章。
    直接用本地 PubMed hybrid_search（ES BM25 + Milvus 向量融合）搜索文章。

    Args:
        query:  查询词，必须英文，支持自然语言，如 "EGFR mutation lung cancer"
        years:  年份过滤列表，如 [2024, 2025]，不传则默认最近两年

    Returns:
        {
            "results": [...],   # 文章列表，每条含 title/summary/pmid/doi 等
            "count": int        # 返回数量
        }
    """
    from utils.pubmed_opt.pubmed_search import PubMedSearch
    import logging

    logger = logging.getLogger(__name__)

    if not query or not query.strip():
        return {"results": [], "count": 0}

    pubmed_search = PubMedSearch()
    try:
        results = await pubmed_search.hybrid_search(
            query=query.strip(),
            years=years or [],
        )
        logger.info(f"[pubmed_hybrid_search] query={query}, years={years}, got {len(results)} results")
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.exception(f"[pubmed_hybrid_search] failed: {e}")
        return {"results": [], "count": 0}