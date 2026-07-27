# -*- coding: utf-8 -*-
"""
NSFC Writing Agent V3 — Phase 1: Research & Blueprint Generation.

Runs research tools (NSFC search, PubMed, document analysis) then
calls submit_blueprints to present 3 candidate blueprints to the user.

Event flow:
  planUpdate + chat (research progress) -> nsfc_confirm (blueprint data)
  -> blueprint chats x 3 -> statusUpdate (need_future_steps=True)
"""

import json
import logging
import time
from typing import ClassVar

from agent.nsfc.v3.base import NSFCAgentV3Base, LoopHooks
from agent.nsfc.v3.tools import SubmitBlueprints

logger = logging.getLogger(__name__)

# Phase 1 system prompt suffix — instructs LLM to call submit_blueprints
PHASE1_SUFFIX_PROMPT = """

## 重要：完成研究后的操作

当你完成以下所有分析后，**必须**调用 submit_blueprints 工具提交 3 个候选课题方案：
1. NSFC 项目检索与分析（使用 nsfc-search 命令）
2. PubMed 文献检索与分析（使用 pubmed-search 或 literature-pool 命令）
3. 用户文档分析（如有附件，使用 attachment-download 命令）

### submit_blueprints 工具使用说明
- blueprints 字段必须包含 **3 个**完整的课题方案
- 每个方案必须包含：title（项目标题）, rationale（立项理由）, objectives（研究目标）, contents（研究内容）, methods（研究方法）, innovations（创新点）
- research_summary 字段应包含你的研究发现总结（包括关键文献和NSFC项目分析要点）
- 在调用 submit_blueprints 之前，不要结束对话
"""


class NSFCAgentV3PhaseOne(NSFCAgentV3Base):
    """Phase 1: Research analysis + blueprint generation."""

    PHASE1_SKILLS: ClassVar[list[str]] = [
        "blueprint", "landscape-analysis", "literature-analysis", "nsfc-overview", "citation",
        "nsfc-search", "literature-pool", "pubmed-search", "attachment-download",
    ]

    def __init__(self, **kwargs):
        super().__init__(skills_filter=self.PHASE1_SKILLS, **kwargs)
        self.sys_prompt += PHASE1_SUFFIX_PROMPT
        # Phase 1 tools: only submit_blueprints (search tools are now local CLI)
        self.tools = [SubmitBlueprints]
        self._tools_schema = self._build_tools_schema()

    async def use_tool(self, user_prompt: str = "", **kwargs):
        """
        Research loop -> submit_blueprints interception -> yield nsfc_confirm events.

        Yields V2-compatible events:
        - planUpdate + chat: research progress
        - nsfc_confirm: blueprint data for frontend selection UI
        - chat x 3: individual blueprint previews
        - statusUpdate: need_future_steps=True (triggers Phase 2)
        """
        params = kwargs.get("params", {})
        raw_data = params.get("raw_data", {})

        # Build the initial user message
        user_title = raw_data.get("user_title", "")
        user_query = raw_data.get("user_query", "")
        user_input = (
            f"{user_title}\n\n{user_query}".strip()
            if (user_title or user_query)
            else user_prompt
        )

        if not user_input:
            yield self._make_error_event("请提供您的研究方向或写作需求。")
            return

        # Handle attachments
        files = params.get("files", {})
        attachment_info = ""
        if files:
            attachment_info = "\n\n用户已上传附件，请使用 attachment-download 命令下载和解析。"

        # Initialize conversation
        messages = [{"role": "user", "content": user_input + attachment_info}]

        # Initialize sandbox and .memory/ files
        await self.sandbox_manager.ensure_sandbox()
        await self._init_memory_files(user_input)
        prior_context = await self._load_prior_context()
        if prior_context:
            messages[0]["content"] += prior_context

        started_at = int(time.time())
        plan_updates = []
        step = 0
        submitted_blueprints = []
        research_summary = ""
        chat_texts = []
        no_tool_retries = 0

        try:
            # Initial progress event
            initial_step = {
                "id": "step_init",
                "reason": "正在分析您的研究方向...",
                "startedAt": started_at,
                "status": "doing",
                "tool": "Writing-Assistant",
            }
            plan_updates.append(initial_step)
            yield self._make_plan_event(plan_updates, 0, started_at)
            yield self._make_chat_event(
                "正在分析您的研究方向并准备候选课题方案...", 0, started_at, plan_updates, save=True,
            )

            # --- Define hooks ---
            def on_message(text: str) -> bool:
                chat_texts.append(text)
                return False

            async def on_function_call(tool_name: str, tool_args: dict, call_id: str):
                nonlocal submitted_blueprints, research_summary
                if tool_name == "submit_blueprints":
                    logger.info(f"[NSFCAgentV3P1] Intercepted submit_blueprints")
                    submitted_blueprints = tool_args.get("blueprints", [])
                    research_summary = tool_args.get("research_summary", "")

                    output = json.dumps({
                        "status": "success",
                        "message": f"Submitted {len(submitted_blueprints)} blueprints.",
                    })

                    step_info = {
                        "id": f"step_{step}_submit",
                        "reason": "候选课题方案提交完成",
                        "startedAt": int(time.time()),
                        "status": "done",
                        "tool": "submit_blueprints",
                    }
                    plan_updates.append(step_info)

                    return (output, True)  # handled, break
                return (None, False)  # not handled, fall through

            def on_no_tool_call() -> bool:
                nonlocal no_tool_retries
                if not submitted_blueprints:
                    no_tool_retries += 1
                    if no_tool_retries <= 2:
                        messages.append({
                            "role": "user",
                            "content": "你还没有调用 submit_blueprints 工具。请根据已有的研究分析，立即调用 submit_blueprints 提交 3 个候选课题方案。",
                        })
                        return True  # continue loop
                return False  # break

            hooks = LoopHooks(
                on_message=on_message,
                on_function_call=on_function_call,
                on_no_tool_call=on_no_tool_call,
                done_reason="分析完成",
            )

            # --- Run unified loop ---
            async for event in self._execute_loop(
                messages, plan_updates, started_at, step_offset=step, hooks=hooks,
            ):
                yield event

        finally:
            try:
                await self.sandbox_manager.close()
            except Exception as close_err:
                logger.warning(f"[NSFCAgentV3P1] sandbox close failed: {close_err}")

        # Fallback: if LLM didn't call submit_blueprints, try to extract from last output
        if not submitted_blueprints:
            submitted_blueprints = await self._fallback_extract_blueprints(
                messages, chat_texts
            )
            if not research_summary and chat_texts:
                research_summary = "\n\n".join(chat_texts[-3:])

        if not submitted_blueprints:
            yield self._make_chat_event(
                "候选课题方案生成失败，请稍后重试或调整输入。",
                step, started_at, plan_updates, save=True,
            )
            yield self._make_status_event(step, int(time.time()))
            return

        # === Yield nsfc_confirm + blueprint chats + statusUpdate ===
        context = {
            "query_params": {"user_input": user_input, **raw_data},
            "nsfc_project_blueprints": submitted_blueprints,
            "research_summary": research_summary,
            "nsfc_insights": "",   # V2 compat
            "pubmed_insights": "",  # V2 compat
            "plan_updates": plan_updates,
        }

        # 1. nsfc_confirm event
        yield {
            "agent": "article_nsfc_writing",
            "type": "nsfc_confirm",
            "sender": "assistant",
            "chunkIdx": 0,
            "message": "候选课题方案生成完成，正在逐一展示。",
            "data": context,
            "id": f"{step}-nbc-0",
            "startedAt": int(time.time()),
            "save": True,
        }

        # 2. Individual blueprint chats (matches V2 format)
        for idx, bp in enumerate(submitted_blueprints):
            if isinstance(bp, dict):
                preview = self._build_blueprint_preview(bp, idx + 1)
            else:
                preview = self._build_blueprint_preview(
                    bp.model_dump() if hasattr(bp, "model_dump") else dict(bp),
                    idx + 1,
                )
            yield {
                "agent": "article_nsfc_writing",
                "type": "chat",
                "sender": "assistant",
                "chunkIdx": 0,
                "message": preview,
                "id": f"{step}-bp-{idx}",
                "startedAt": int(time.time()),
                "save": True,
            }

        # 3. statusUpdate with need_future_steps (triggers Phase 2 flow)
        yield {
            "agent": "article_nsfc_writing",
            "type": "statusUpdate",
            "sender": "assistant",
            "chunkIdx": 0,
            "need_future_steps": True,
            "id": f"{step}-w-0",
            "startedAt": int(time.time()),
            "save": True,
        }

    async def _fallback_extract_blueprints(
        self, messages: list, chat_texts: list
    ) -> list:
        """
        Fallback: if LLM didn't call submit_blueprints, make one more LLM call
        to format existing research into 3 blueprints as JSON.
        """
        research_context = "\n\n".join(chat_texts[-5:]) if chat_texts else ""
        if not research_context:
            return []

        logger.info("[NSFCAgentV3P1] Fallback: forcing blueprint extraction via extra LLM call")

        fallback_prompt = f"""Based on the following research analysis, generate exactly 3 candidate NSFC project blueprints.

Output ONLY a JSON array with 3 objects, each containing:
- title (string): Project title in Chinese
- rationale (string): 2-3 sentence rationale
- objectives (array of strings): 3-5 research objectives
- contents (array of strings): 3-5 research content items
- methods (array of strings): 3-5 key methods
- innovations (array of strings): 2-4 innovation points

Research context:
{research_context[:8000]}

Output the JSON array only, no other text."""

        try:
            model = self.llm
            if isinstance(model, type):
                model = model()
            response = await model(
                sys_prompt="You are a JSON formatting assistant. Output valid JSON only.",
                user_prompt=fallback_prompt,
                max_output_tokens=8192,
                temperature=0.2,
            )
            if response and getattr(response, "output", None):
                text = ""
                for item in response.output:
                    text += self._extract_text(item)
                import re
                json_match = re.search(r'\[.*\]', text, re.DOTALL)
                if json_match:
                    blueprints = json.loads(json_match.group())
                    if isinstance(blueprints, list) and len(blueprints) > 0:
                        logger.info(f"[NSFCAgentV3P1] Fallback extracted {len(blueprints)} blueprints")
                        return blueprints
        except Exception as e:
            logger.error(f"[NSFCAgentV3P1] Fallback blueprint extraction failed: {e}")

        return []
