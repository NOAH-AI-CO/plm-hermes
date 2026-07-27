import time
import logging

from datetime import datetime
from typing import List

from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.composite_models import CompositeGPT5
from tools.core.base_tool import BaseTool
from agent.article_writing.article_editing_prompt import (
    gpt_editing_sys_pt,
    gpt_editing_user_pt,
    gpt_editing_nsfc_placeholder_notice,
    gpt_editing_nsfc_body_only_notice,
)
from agent.article_writing.nsfc_edit_heading_preservation import (
    prepare_nsfc_editing,
    should_apply_nsfc_heading_preservation,
    stitch_nsfc_segments,
    strip_markdown_heading_lines_from_body,
    unmask_nsfc_placeholders,
)

logger = logging.getLogger(__name__)


class ArticleEditingOutputAgent(AgentPreset):
    llm: BaseLLM = CompositeGPT5
    sys_prompt: str = gpt_editing_sys_pt
    tools: List[BaseTool] = []
    tool_choice: str = "auto"


class ArticleEditingAgent(AgentPreset):
    llm: BaseLLM = CompositeGPT5

    editing_agent: ArticleEditingOutputAgent = ArticleEditingOutputAgent()

    async def use_tool(self, user_prompt: str, history_messages: List[dict] = [], images: List[str] = [], **kwargs):
        start_time = time.time()

        params = kwargs.get('params', {})

        paragraph = params.get('paragraph', '') or ''
        selected_words = params.get('selected_words', '') or ''
        plan = None
        fund_type = should_apply_nsfc_heading_preservation(params)
        if fund_type:
            plan = prepare_nsfc_editing(paragraph, selected_words, fund_type)
            paragraph = plan.paragraph_for_prompt
            selected_words = plan.selected_for_prompt

        final_user_prompt = None
        if not (plan and plan.mode == "body_split" and plan.original_bodies):
            nsfc_notice = ""
            if plan and plan.mode == "placeholder_mask" and plan.preserved_headings:
                nsfc_notice = gpt_editing_nsfc_placeholder_notice
            final_user_prompt = nsfc_notice + gpt_editing_user_pt.format(
                current_date=datetime.now().strftime('%Y-%m-%d'),
                paragraph=paragraph,
                selected_words=selected_words,
                user_question=user_prompt,
            )
            logger.info(f'Article editing {final_user_prompt}')

        event = {
            'agent': 'article_editing',
            'chunkIdx': 0,
            'id': '0',
            'message': '',
            'sender': 'assistant',
            'startedAt': int(time.time()),
            'type': 'article_editing',
        }

        # 选区仅含标题，或标题后只有空行等无实质正文：不调用模型（避免空选区触发话术回复）
        if plan and plan.mode == "body_split":
            bodies = plan.original_bodies or []
            has_real_body = any((b or "").strip() for b in bodies)
            if not has_real_body:
                event['message'] = stitch_nsfc_segments(plan.segments, [], bodies)
                yield event
                event['save'] = True
                yield event
                logger.info(
                    "Article editing NSFC heading-only skip LLM (len=%s) cost %ss",
                    len(event.get("message", "")),
                    time.time() - start_time,
                )
                yield {
                    'agent': 'article_editing',
                    'chunkIdx': 0,
                    'id': '0',
                    'sender': 'assistant',
                    'startedAt': int(time.time()),
                    'type': 'statusUpdate',
                    'save': True,
                }
                return

        if plan and plan.mode == "body_split" and plan.original_bodies:
            edited_bodies: List[str] = []
            total = len(plan.original_bodies)
            for idx, original_body in enumerate(plan.original_bodies):
                if not (original_body or "").strip():
                    edited_bodies.append(original_body)
                    preview_bodies = edited_bodies + plan.original_bodies[idx + 1 : total]
                    event['message'] = stitch_nsfc_segments(
                        plan.segments, preview_bodies, plan.original_bodies
                    )
                    yield event
                    continue
                current_prompt = gpt_editing_nsfc_body_only_notice + gpt_editing_user_pt.format(
                    current_date=datetime.now().strftime('%Y-%m-%d'),
                    paragraph=paragraph,
                    selected_words=original_body,
                    user_question=user_prompt,
                )
                current_acc = ""
                async for chunk in self.editing_agent.stream_call(user_prompt=current_prompt):
                    current_acc += chunk
                    current_clean = strip_markdown_heading_lines_from_body(current_acc)
                    preview_bodies = edited_bodies + [current_clean] + plan.original_bodies[idx + 1 : total]
                    event['message'] = stitch_nsfc_segments(
                        plan.segments, preview_bodies, plan.original_bodies
                    )
                    yield event
                edited_bodies.append(
                    strip_markdown_heading_lines_from_body(current_acc) or original_body
                )
        else:
            body_accum = ""
            async for chunk in self.editing_agent.stream_call(user_prompt=final_user_prompt or ""):
                body_accum += chunk
                if plan and plan.mode == "placeholder_mask" and plan.preserved_headings:
                    event['message'] = unmask_nsfc_placeholders(
                        body_accum, plan.preserved_headings
                    )
                else:
                    event['message'] = body_accum
                yield event

        event['save'] = True
        yield event

        logger.info(
            "Article editing done (message_len=%s, nsfc_mode=%s) cost %ss",
            len(event.get("message", "")),
            getattr(plan, "mode", None),
            time.time() - start_time,
        )
        
        # yield event status update event
        yield {
            'agent': 'article_editing',
            'chunkIdx': 0,
            'id': '0',
            'sender': 'assistant',
            'startedAt': int(time.time()),
            'type': 'statusUpdate',
            'save': True,
        }
