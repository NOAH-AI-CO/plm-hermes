# -*- coding: utf-8 -*-
"""
NSFC Writing Agent V3 — Phase 2: Writing from selected blueprint.

Receives Phase 1 context (blueprints + research summary) and the user's
selected blueprint ID. Writes the full NSFC proposal.

Event flow:
  planUpdate + chat (writing progress) -> article_writing (full text)
  -> planUpdate (all done) -> statusUpdate
"""

import json
import logging
import time
from typing import ClassVar

from agent.nsfc.v3.base import NSFCAgentV3Base, LoopHooks
from agent.nsfc.v3.swarm import ForkAgents

logger = logging.getLogger(__name__)

# Phase 2 system prompt suffix
PHASE2_SUFFIX_PROMPT = """

## 重要：Phase 2 写作任务

你现在处于 **Phase 2 写作阶段**。用户已经从 Phase 1 选择了一个候选课题方案。

### 你的任务
1. 根据选定的课题方案和研究背景，撰写完整的 NSFC 申请书
2. 按照 writing skill 的指导，逐章节撰写
3. 所有引用必须基于真实文献（使用 literature-pool 命令获取）
4. 如需处理多个文件或并行任务，使用 fork_agents

### 输出格式
- 以 markdown 格式输出完整申请书内容
- 章节标题与 NSFC 官方提纲一致
- 在最终输出中包含所有章节的完整内容
"""


class NSFCAgentV3PhaseTwo(NSFCAgentV3Base):
    """Phase 2: Full proposal writing from selected blueprint."""

    PHASE2_SKILLS: ClassVar[list[str]] = ["writing", "citation", "literature-pool", "pubmed-search"]

    nsfc_context: dict = {}
    nsfc_selected_blueprint_id: int = 0
    pre_plan_updates: list = []

    def __init__(self, **kwargs):
        super().__init__(skills_filter=self.PHASE2_SKILLS, **kwargs)
        self.sys_prompt += PHASE2_SUFFIX_PROMPT
        # Phase 2 tools: only fork_agents (search tools are now local CLI)
        self.tools = [ForkAgents]
        self._tools_schema = self._build_tools_schema()

        # Receive Phase 1 context (same interface as V2)
        params = kwargs.get("params", {})
        self.nsfc_context = params.get("nsfc_context", {})
        self.nsfc_selected_blueprint_id = params.get("nsfc_selected_blueprint_id", 0)
        self.pre_plan_updates = self.nsfc_context.get("plan_updates", [])

    async def use_tool(self, user_prompt: str = "", **kwargs):
        """
        Writing loop: receives selected blueprint -> multi-turn writing -> article_writing.

        Yields V2-compatible events:
        - planUpdate + chat: writing progress
        - article_writing: full proposal text
        - statusUpdate: completion signal
        """
        # Extract selected blueprint and research context
        blueprints = self.nsfc_context.get("nsfc_project_blueprints", [])
        selected = {}
        if blueprints and 0 <= self.nsfc_selected_blueprint_id < len(blueprints):
            selected = blueprints[self.nsfc_selected_blueprint_id]
        elif blueprints:
            selected = blueprints[0]

        research_summary = self.nsfc_context.get("research_summary", "")
        query_params = self.nsfc_context.get("query_params", {})
        user_input = query_params.get("user_input", user_prompt)

        # Build initial writing instruction
        initial_msg = f"""请根据以下选定的课题方案，撰写完整的 NSFC 申请书。

## 用户原始需求
{user_input}

## 选定的课题方案
{json.dumps(selected, ensure_ascii=False, indent=2)}

## 研究背景
{research_summary[:6000] if research_summary else '（无额外研究背景，请根据课题方案直接撰写）'}

## 任务
按照 writing skill 的指导，逐章节撰写完整的 NSFC 申请书。所有引用必须基于真实文献。"""

        messages = [{"role": "user", "content": initial_msg}]

        # Initialize sandbox
        await self.sandbox_manager.ensure_sandbox()
        await self._init_memory_files(initial_msg[:500])
        prior_context = await self._load_prior_context()
        if prior_context:
            messages[0]["content"] += prior_context

        started_at = int(time.time())
        # Inherit Phase 1 plan_updates for continuity
        plan_updates = list(self.pre_plan_updates)
        step = len(plan_updates)
        article_content = ""

        try:
            # Initial progress event
            writing_step = {
                "id": f"step_{step}_writing",
                "reason": "开始撰写申请书...",
                "startedAt": started_at,
                "status": "doing",
                "tool": "Writing-Assistant",
            }
            plan_updates.append(writing_step)
            yield self._make_plan_event(plan_updates, step, started_at)
            yield self._make_chat_event(
                f"已选定课题方案「{selected.get('title', '')}」，开始撰写完整申请书...",
                step, started_at, plan_updates, save=True,
            )

            # --- Define hooks ---
            def on_message(text: str) -> bool:
                nonlocal article_content
                if len(text) > len(article_content):
                    article_content = text
                return False

            hooks = LoopHooks(
                on_message=on_message,
                done_reason="撰写完成",
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
                logger.warning(f"[NSFCAgentV3P2] sandbox close failed: {close_err}")

        final_step = step + self.max_steps  # Use a safe step number for event IDs

        # Final event sequence (matches V2 order):
        # 1. article_writing — provides article content to frontend panel
        if article_content:
            yield {
                "agent": "article_nsfc_writing",
                "type": "article_writing",
                "hitl_mode": "always",
                "sender": "assistant",
                "chunkIdx": 0,
                "message": article_content,
                "id": f"{final_step}-w-0",
                "startedAt": int(time.time()),
                "save": True,
            }

        # 2. Final planUpdate — mark all steps done
        for p in plan_updates:
            if p.get("status") != "done":
                p["status"] = "done"
        yield self._make_plan_event(plan_updates, final_step, started_at, save=True)

        # 3. statusUpdate — prevents backend from overwriting last event
        yield self._make_status_event(final_step, int(time.time()))
