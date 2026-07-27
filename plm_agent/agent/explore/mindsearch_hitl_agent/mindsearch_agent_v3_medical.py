# -*- coding: utf-8 -*-
import logging

import time
from typing import List
from datetime import datetime

from agent.core.preset import AgentPreset
import agent.explore.constants as constants
from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini
from llm.gcp_models import ClaudeHaiku45
from tools.core.base_tool import BaseTool
from utils.tokenizer import tokenizer


from agent.explore.mindsearch_prompt_v3 import (
    gpt_query_rewrite_user_pt, gpt_o_search_final_output_user_pt,
)
from agent.explore.mindsearch_hitl_agent.mindsearch_agent_v3_medical_prompt import (
    medical_thinking_sys_pt, medical_final_output_sys_pt,
)
from tools.explore.mindsearch_tools_v3 import (
    GeneralSearch, MedicalSearch, PubMedArticlesLocalSearch, PubMedArticlesSearch,
    DocumentReader, DocumentSearchFinished
)
from tools.explore.attachment_tools import AttachmentDownload
from tools.sandbox import AgentRunSandbox

logger = logging.getLogger(__name__)


# MindSearchMedicalHitlQueryRewriteAgent
class MindSearchMedicalThinkingAgent(AgentPreset):
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        GeneralSearch,
        MedicalSearch,
        PubMedArticlesLocalSearch,
        PubMedArticlesSearch,
        AttachmentDownload,
        AgentRunSandbox,
        DocumentReader,
        DocumentSearchFinished,
    ]
    tool_choice: str = "required"


class MindSearchFinalOutputAgent(AgentPreset):
    llm: BaseLLM = ClaudeHaiku45
    sys_prompt: str = ''
    tools: List[BaseTool] = []


class MindSearchMedicalHitlAgent(MindSearchAgentV3):
    
    thinking_agent: MindSearchMedicalThinkingAgent = MindSearchMedicalThinkingAgent()
    final_output_agent: MindSearchFinalOutputAgent =  MindSearchFinalOutputAgent()
    max_source_count: int = 20 # max number of citations, for PubMed articles.

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

        return medical_thinking_sys_pt, user_prompt

    async def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: List[dict],
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

        return medical_final_output_sys_pt, final_user_prompt

    def _truncate_final_output(
        self,
        content: str
    ) -> str:
        return tokenizer.truncate_by_tokens(content, 130000, 'claude')
