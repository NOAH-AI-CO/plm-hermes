import time
import asyncio
import logging

from datetime import datetime
from typing import List

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.composite_models import CompositeGPT5
from tools.core.base_tool import BaseTool
from agent.article_writing.article_rewriting_prompt import (
    gpt_rewriting_sys_pt, gpt_rewriting_user_pt
)

logger = logging.getLogger(__name__)


class ArticleRewritingOutputAgent(AgentPreset):
    llm: BaseLLM = CompositeGPT5
    sys_prompt: str = gpt_rewriting_sys_pt
    tools: List[BaseTool] = []
    tool_choice: str = "auto"


class ArticleRewritingAgent(AgentPreset):
    llm: BaseLLM = CompositeGPT5

    rewriting_agent: ArticleRewritingOutputAgent = ArticleRewritingOutputAgent()

    def _content_format(
        self,
        content: str) -> str:
        r"""
        1. '<'-> '//<'
        """
        content = content.replace('<', '\\<')
        return content

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        start_time = time.time()

        params = kwargs.get('params', {})

        # yield user question status update event
        yield {
            'agent': 'article_rewriting',
            'chunkIdx': 0,
            'id': '0-u',
            'message': user_prompt,
            'sender': 'user',
            'startedAt': int(time.time()),
            'type': 'chat',
            'save': True,
        }

        # yield article rewriting telling user that the article is being rewritten
        yield {
            'agent': 'article_rewriting',
            'chunkIdx': 0,
            'id': '0-rw',
            'message': '改写中，正在思考如何改写, 预计完成时间: 3分钟...',
            'sender': 'assistant',
            'startedAt': int(time.time()),
            'type': 'article_rewriting',
        }

        final_user_prompt = gpt_rewriting_user_pt.format(
            current_date=datetime.now().strftime('%Y-%m-%d'),
            article=params.get('article', ''),
            user_question=user_prompt,
        )
        
        event = {
            'agent': 'article_rewriting',
            'chunkIdx': 0,
            'id': '0-rw',
            'message': '',
            'sender': 'assistant',
            'startedAt': int(time.time()),
            'type': 'article_rewriting',
        }

        # use different agent
        output = ""
        buffer = ""
        last_yield_time = time.time()
        yield_interval = 20 # 调整输出时间间隔(秒)

        async for chunk in self.rewriting_agent.stream_call(user_prompt=final_user_prompt, max_output_tokens=1024*60):
            buffer += chunk
            current_time = time.time()

            if current_time - last_yield_time >= yield_interval:
                output += buffer
                event['message'] = self._content_format(output)
                yield event
                buffer = ""
                last_yield_time = current_time

        if buffer:
            output += buffer

        event['message'] = self._content_format(output)
        yield event
        logger.info(f"Article rewriting final output: {event} cost {time.time() - start_time}s")

        event['save'] = True
        yield event
        await asyncio.sleep(1)

        # yield event status update event
        yield {
            'agent': 'article_rewriting',
            'chunkIdx': 0,
            'id': '0-s',
            'sender': 'assistant',
            'startedAt': int(time.time()),
            'type': 'statusUpdate',
            'save': True,
        }

