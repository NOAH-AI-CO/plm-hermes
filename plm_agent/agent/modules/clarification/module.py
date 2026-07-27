# -*- coding: utf-8 -*-
"""``ClarificationModule`` — pre-flight Q&A for ``general_writing``.

Lifecycle (router-LLM model):

1. Router LLM (in ``agent.modules.router``) sees this module's tool schema
   (``ask_clarification``) and decides whether to call it. We don't run
   our own ``should_engage`` LLM anymore — the router owns that decision.

2. ``run(body, state, args)`` receives ``ClarificationArgs`` with the
   question + options the router picked. Emits one ``content.type='executeCard'``
   ``add`` envelope (``task_status='feedback'``) and pauses
   (``awaiting_user=True``).

3. ``consume_reply`` handles the four reply states:
   - ``skip=True`` → mark done, no enrichment
   - ``approve=True`` + ``feedback`` → record round, mark done
   - ``approve=False`` + ``feedback`` → record as supplementary, mark done
     (next round, if any, is decided by the next /chat's router LLM call)
   - Empty / invalid → re-emit the same question

4. ``enrich_prompt`` (called after ``done``)
   - Restore ``original_query`` from state (reply bodies don't carry it)
   - Append ``[澄清补充]`` block with Q&A pairs
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from pydantic import BaseModel, Field

from agent.modules._v2_envelope import (
    TASK_STATUS_FEEDBACK,
    build_add_envelope,
    build_card_value,
    build_replace_envelope,
    make_action,
    make_step,
    new_msg_id,
)
from agent.modules.base import InteractiveModule
from agent.modules.registry import register_module

logger = logging.getLogger(__name__)


# Shared card title for every frame this module emits — front-end keys off
# the title to render the unified "Noah 对研究任务的理解" widget.
_CARD_TITLE = "Noah 对研究任务的理解"


class ClarificationArgs(BaseModel):
    """Parameters the router LLM passes when calling ``ask_clarification``."""

    question: str = Field(min_length=1, description="向用户提的澄清问题（一句话）")
    options: list[str] = Field(
        min_length=2,
        max_length=4,
        description="2-4 个候选答案选项，覆盖最常见的几种用户意图",
    )
    rationale: str | None = Field(
        default=None,
        description="解释为什么需要澄清（不展示给用户，仅供调试日志）",
    )


# Default args for the ``force_clarification=True`` bypass — used when the
# caller wants to force a clarification round without going through the
# router LLM (e.g. integration tests, debugging).
_DEFAULT_FORCE_ARGS = ClarificationArgs(
    question="为了更好地帮您写作，请告诉我目标读者、内容方向或篇幅偏好。",
    options=[
        "面向行业读者，正式风格",
        "面向大众读者，科普风格",
        "学术论文综述",
        "短篇要点总结",
    ],
)


def _options_to_actions(options: list[str]) -> list[dict]:
    """Render the option list as clickable card actions.

    First option is the recommended one (``type="primary"``); the rest are
    secondary. All carry ``model="clarification"`` so the front-end POSTs
    back via the existing ``module_reply`` route.
    """
    return [
        make_action(
            i,
            "clarification",
            opt,
            type_="primary" if i == 0 else "default",
        )
        for i, opt in enumerate(options)
    ]


@register_module
class ClarificationModule(InteractiveModule):
    name = "clarification"
    content_type = "executeCard"
    args_model = ClarificationArgs
    tool_description = (
        "当用户的写作请求缺少关键信息（目标读者 / 文体 / 字数 / 语气其中之一）"
        "或存在明显歧义时，提出一个最关键的澄清问题，并给出 2-4 个候选答案选项。"
        "信息已经足够具体、可以直接动笔的请求**不要调用本工具**。"
    )
    reply_types = ("module_reply",)
    routable = True
    max_rounds = 3

    @classmethod
    def default_args(cls) -> ClarificationArgs:
        """Used by ``pipeline._maybe_force_run`` for the force_<name>=True bypass."""
        return _DEFAULT_FORCE_ARGS

    # ------------------------------------------------------------------
    # run — invoked by the pipeline after the router picked this tool
    # ------------------------------------------------------------------

    async def run(
        self,
        body: dict,
        state: dict,
        args: ClarificationArgs,
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        task_id = body.get("task_id") or ""    # v1-style parent Task UUID from Backend
        user_query = (body.get("user_prompt") or "").strip()

        question = args.question.strip()
        options = list(args.options or [])

        round_idx = len(state.get("rounds", [])) + 1
        msg_id = new_msg_id()

        state.setdefault("original_query", user_query)
        state.setdefault("rounds", [])
        state["awaiting_user"] = True
        state["done"] = False
        state["pending"] = {
            "msg_id": msg_id,
            "task_id": task_id,
            "round": round_idx,
            "q": question,
            "options": options,
        }

        steps = [
            make_step(
                0, "step_query",
                title="用户原始需求",
                summary=state["original_query"],
            ),
            make_step(
                1, "step_question",
                title="需要澄清",
                summary=question,
            ),
        ]

        yield build_add_envelope(
            build_card_value(
                task_id=task_id,
                msg_id=msg_id,
                thread_id=thread_id,
                title=_CARD_TITLE,
                desc=question,
                frame_type="ver",
                priority="p1",
                open_=True,
                steps=steps,
                actions=_options_to_actions(options),
                status="ready",
                index=round_idx,
                extra_meta={
                    "module": self.name,
                    "round": round_idx,
                    "max_rounds": self.max_rounds,
                    "options": options,
                    "allow_freetext": True,
                    "skip_allowed": True,
                    "original_query": state["original_query"],
                },
            ),
            task_status=TASK_STATUS_FEEDBACK,
        )

    # ------------------------------------------------------------------
    # consume_reply — handles ``type='module_reply', module='clarification'``
    # ------------------------------------------------------------------

    async def consume_reply(
        self,
        body: dict,
        state: dict,
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        feedback = (body.get("feedback") or "").strip()
        approve = bool(body.get("approve", False))
        skip = bool(body.get("skip", False))

        pending = state.get("pending") or {}
        # The reply re-uses the asking task's task_id + msg_id so Backend can
        # backfill the asking task's events row with the resolved state.
        pending_msg_id = pending.get("msg_id") or pending.get("task_id") or new_msg_id()
        pending_task_id = pending.get("task_id") or body.get("task_id") or ""
        round_idx = pending.get("round") or (len(state.get("rounds", [])) + 1)
        question = pending.get("q", "")
        options = pending.get("options", [])

        # Skip: terminate immediately
        if skip:
            state["awaiting_user"] = False
            state["done"] = True
            state["skipped"] = True
            state.pop("pending", None)
            yield build_replace_envelope(
                build_card_value(
                    task_id=pending_task_id,
                    msg_id=pending_msg_id,
                    thread_id=thread_id,
                    title=_CARD_TITLE,
                    desc=question or state.get("original_query", ""),
                    frame_type="ver",
                    priority="p1",
                    open_=False,
                    steps=[
                        make_step(
                            0, "step_skip",
                            title="用户操作",
                            status="success",
                            summary="已跳过澄清",
                        ),
                    ],
                    actions=[],
                    status="success",
                    index=round_idx,
                    extra_meta={
                        "module": self.name,
                        "round": round_idx,
                        "skipped": True,
                        "original_query": state.get("original_query", ""),
                    },
                )
            )
            return

        # Invalid input: re-ask the same question (no round consumed)
        if not feedback and not approve:
            yield build_replace_envelope(
                build_card_value(
                    task_id=pending_task_id,
                    msg_id=pending_msg_id,
                    thread_id=thread_id,
                    title=_CARD_TITLE,
                    desc=question,
                    frame_type="ver",
                    priority="p1",
                    open_=True,
                    steps=[
                        make_step(
                            0, "step_query",
                            title="用户原始需求",
                            summary=state.get("original_query", ""),
                        ),
                        make_step(
                            1, "step_question",
                            title="需要澄清",
                            summary=question,
                        ),
                    ],
                    actions=_options_to_actions(options),
                    status="ready",
                    index=round_idx,
                    extra_meta={
                        "module": self.name,
                        "round": round_idx,
                        "max_rounds": self.max_rounds,
                        "options": options,
                        "allow_freetext": True,
                        "skip_allowed": True,
                        "original_query": state.get("original_query", ""),
                        "invalid_input": True,
                    },
                ),
                task_status=TASK_STATUS_FEEDBACK,
            )
            return

        # Record the round (both approve=True+feedback and approve=False+feedback consume one)
        rounds = state.setdefault("rounds", [])
        rounds.append({
            "q": question,
            "options": options,
            "a": feedback,
            "approve": approve,
        })
        state.pop("pending", None)
        state["awaiting_user"] = False
        state["done"] = True

        yield build_replace_envelope(
            build_card_value(
                task_id=pending_task_id,
                msg_id=pending_msg_id,
                thread_id=thread_id,
                title=_CARD_TITLE,
                desc=question,
                frame_type="ver",
                priority="p1",
                open_=False,
                steps=[
                    make_step(
                        0, "step_question",
                        title="澄清问题",
                        status="success",
                        summary=question,
                    ),
                    make_step(
                        1, "step_answer",
                        title="用户答复",
                        status="success",
                        summary=feedback,
                    ),
                ],
                actions=[],
                status="success",
                index=round_idx,
                extra_meta={
                    "module": self.name,
                    "round": round_idx,
                    "answer": feedback,
                    "approve": approve,
                    "original_query": state.get("original_query", ""),
                },
            )
        )

    # ------------------------------------------------------------------
    # enrich_prompt — runs after done; downstream agent sees the result
    # ------------------------------------------------------------------

    def enrich_prompt(self, body: dict, state: dict) -> dict:
        new_body = dict(body)
        original = (new_body.get("user_prompt") or "").strip()
        if not original:
            original = (state.get("original_query") or "").strip()

        rounds = state.get("rounds") or []
        if state.get("skipped") or not rounds:
            new_body["user_prompt"] = original
            return new_body

        addendum_parts = []
        for r in rounds:
            q = (r.get("q") or "").strip()
            a = (r.get("a") or "").strip()
            if q and a:
                addendum_parts.append(f"- {q} 用户答复：{a}")
        if not addendum_parts:
            new_body["user_prompt"] = original
            return new_body

        addendum = "\n\n[澄清补充]\n" + "\n".join(addendum_parts)
        new_body["user_prompt"] = (original + addendum).strip()
        return new_body
