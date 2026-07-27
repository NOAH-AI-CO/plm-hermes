# -*- coding: utf-8 -*-
import logging

from typing import List
from datetime import datetime

import agent.explore.constants as constants
from llm.base_model import BaseLLM
from llm.azure_models import GPT54Mini
from agent.core.preset import AgentPreset
from agent.core.exceptions import ModerationFailure
from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3
from agent.explore.mindsearch_agent_v3_china import SensitiveChecker
from tools.core.base_tool import BaseTool

from agent.explore.mindsearch_refer_prompt_v3 import (
    refer_thinking_sys_pt,
    refer_final_output_sys_pt,
    refer_query_rewrite_user_pt,
)
from agent.explore.mindsearch_prompt_v3 import (
    gpt_o_search_final_output_user_pt,
)
from tools.explore.mindsearch_tools_v3 import (
    GeneralSearch, ContentReader, Finished,
)
from agent.explore.schema import (
    MindSearchResponse, SearchNode, SearchType, ProcessingType,
)

logger = logging.getLogger(__name__)


class MindSearchReferThinkingAgent(AgentPreset):
    llm: BaseLLM = GPT54Mini
    sys_prompt: str = ''
    tools: List[BaseTool] = [GeneralSearch, ContentReader, Finished]
    tool_choice: str = "required"


class MindSearchReferAgentV3(MindSearchAgentV3):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.thinking_agent = MindSearchReferThinkingAgent()
        self.max_thinking_rounds = 3

    def _format_thinking_prompt(
        self,
        user_prompt: str,
        language: str = constants.ENGLISH,
    ) -> tuple[str, str]:
        r"Format thinking prompt, return customer sys_prompt and user_prompt"

        user_prompt = refer_query_rewrite_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            language=language,
            user_question=user_prompt,
        )

        return refer_thinking_sys_pt, user_prompt

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

        return refer_final_output_sys_pt, final_user_prompt


class MindSearchReferChinaAgent(MindSearchReferAgentV3, SensitiveChecker):

    llm: BaseLLM = GPT54Mini

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):

        # Parse input parameters
        language, background, history_messages, attachments, _, _, _, _, _ = self._init_components(history_messages=history_messages, kwargs=kwargs)

        # IMPORTANT: Immediately return an empty node for frontend to show the user's question.
        yield MindSearchResponse()

        if await self._check_sensitive_query(user_prompt, history_messages, background, attachments):
            yield MindSearchResponse(
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE,
            )
            return

        try:
            async for res in super().use_tool(
                user_prompt=user_prompt,
                history_messages=history_messages,
                images=images,
                **kwargs,
            ):
                yield res
        except ModerationFailure as e:
            logger.warning(f"ModerationFailure caught in MindSearchReferChinaAgent: {e}")
            yield MindSearchResponse(
                search_graph=SearchNode(
                    search_type=SearchType.UNKNOWN,
                    query="",
                    key_word="",
                ),
                content=self.format_sensitive_content(language),
                processing_type=ProcessingType.DONE,
            )
