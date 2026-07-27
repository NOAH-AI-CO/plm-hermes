# -*- coding: utf-8 -*-
"""
Sandbox Execution V3 HITL Agent.

MindSearchSandboxHitlAgent extends MindSearchAgentV3 with sandbox-focused tools
and thinking prompt optimized for code execution, data analysis, and file processing.
"""
import logging
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
from agent.explore.mindsearch_hitl_agent.mindsearch_agent_v3_sandbox_prompt import (
    sandbox_thinking_sys_pt, sandbox_final_output_sys_pt,
)
from tools.explore.mindsearch_tools_v3 import (
    GeneralSearch, DocumentSearchFinished,
)
from tools.sandbox import AgentRunSandbox
from tools.explore.attachment_tools import AttachmentDownload

logger = logging.getLogger(__name__)


class MindSearchSandboxThinkingAgent(AgentPreset):
    """Thinking agent for Sandbox Execution with AgentRunSandbox as primary tool."""
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: List[BaseTool] = [
        AgentRunSandbox,         # Primary tool
        AttachmentDownload,      # For file retrieval
        GeneralSearch,           # For finding download URLs
        DocumentSearchFinished,  # Completion signal
    ]
    tool_choice: str = "required"


class MindSearchSandboxFinalOutputAgent(AgentPreset):
    llm: BaseLLM = ClaudeHaiku45
    sys_prompt: str = ''
    tools: List[BaseTool] = []


class MindSearchSandboxHitlAgent(MindSearchAgentV3):
    """Sandbox Execution V3 HITL agent. Optimized for code execution, data analysis, and file processing."""

    thinking_agent: MindSearchSandboxThinkingAgent = MindSearchSandboxThinkingAgent()
    final_output_agent: MindSearchSandboxFinalOutputAgent = MindSearchSandboxFinalOutputAgent()
    max_source_count: int = 10

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str,
    ):
        r"Format thinking prompt; return (sys_prompt, user_prompt)."
        user_prompt = gpt_query_rewrite_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )
        return sandbox_thinking_sys_pt, user_prompt

    async def _format_final_output_prompt(
        self,
        user_prompt: str,
        history_messages: List[dict],
        runtime_info: dict,
        background: str,
        language: str = constants.ENGLISH,
    ):
        websearch_results = self._format_final_searchresults(runtime_info, history_messages)
        final_user_prompt = gpt_o_search_final_output_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d.'),
            language=language,
            background=background,
            websearch_results=websearch_results,
            user_question=user_prompt,
        )
        return sandbox_final_output_sys_pt, final_user_prompt

    def _truncate_final_output(self, content: str) -> str:
        return tokenizer.truncate_by_tokens(content, 130000, 'claude')
