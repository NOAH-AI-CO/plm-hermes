# -*- coding: utf-8 -*-
"""``ConfirmationModule`` — let the user confirm/edit a rewritten request.

Two trigger paths share a single state machine:

**Proactive** (router LLM picks ``ask_confirmation``)
    The router decides the user's prompt is ambiguous enough that running
    the writing agent on it would likely miss the mark. It proposes a
    rewritten version (``args.rewrite``) plus a brief rationale, and we
    show that to the user as a card with two actions:
    - ``confirm`` → approve as-is (``approve=true``)
    - ``revision`` → rewrite (``approve=false`` + freetext feedback)
    Skip (``skip=true``) falls back to the original query.

**Reactive** (frontend posts ``type='edit'`` referencing some past event)
    The user clicks "edit" on any earlier event in the thread. We don't
    invoke the router; we just record the (event_id, feedback) pair and
    let the writing agent see it on the next dispatch via ``enrich_prompt``.

Both paths emit v2 ``content.type='executeCard'`` envelopes for the front-end.
Reactive edits emit a single ``status='success'`` ``replace`` ack.
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


# Shared card title — matches clarification.py so the front-end renders the
# same "Noah 对研究任务的理解" widget for both HITL flows.
_CARD_TITLE = "Noah 对研究任务的理解"


class ConfirmationArgs(BaseModel):
    """Parameters the router LLM passes when calling ``ask_confirmation``."""

    rewrite: str = Field(
        min_length=1,
        description=(
            "改写后的写作请求（用户将看到这个版本，可以直接采纳，也可以编辑）。"
            "应当具体、明确，能直接交给写作 agent 动笔。"
        ),
    )
    rationale: str = Field(
        default="",
        description="为什么要这样改写——一句话；用户可以看到，帮助理解。",
    )


def _default_actions() -> list[dict]:
    """The two-button row shown on every confirmation card."""
    return [
        make_action(0, "confirm", "批准范围", type_="primary"),
        make_action(1, "revision", "修订问题", type_="default"),
    ]


def _build_proactive_steps(
    *, original_query: str, rewrite: str, rationale: str,
) -> list[dict]:
    """The three-row body used on the proactive confirmation card."""
    steps = [
        make_step(0, "step_query", title="用户原始需求", summary=original_query),
        make_step(1, "step_rewrite", title="需要确认", summary=rewrite),
    ]
    if rationale:
        steps.append(
            make_step(2, "step_rationale", title="改写理由", summary=rationale),
        )
    return steps


@register_module
class ConfirmationModule(InteractiveModule):
    name = "confirmation"
    content_type = "executeCard"
    args_model = ConfirmationArgs
    tool_description = (
        "当 router 认为需要先把用户的原始请求改写成更明确的版本，让用户确认 / 编辑后"
        "再交给写作 agent 时调用。仅在请求方向可能跑偏、改写后能显著降低误解风险时"
        "才调用本工具。如果用户的原始请求已经足够具体，不要调用。"
    )
    # ``module_reply`` is the wildcard reply path (used by ClarificationModule too,
    # routed via body['module']); ``edit`` is reactive — frontend posts directly.
    reply_types = ("module_reply", "edit")
    routable = True

    # ------------------------------------------------------------------
    # Proactive: run() invoked by the pipeline after router selects this tool
    # ------------------------------------------------------------------

    async def run(
        self,
        body: dict,
        state: dict,
        args: ConfirmationArgs,
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        user_query = (body.get("user_prompt") or "").strip()
        rewrite = (args.rewrite or "").strip()
        rationale = args.rationale or ""

        task_id = body.get("task_id") or ""
        msg_id = new_msg_id()
        state.setdefault("original_query", user_query)
        state.setdefault("rounds", [])
        state["rewrite"] = rewrite
        state["awaiting_user"] = True
        state["done"] = False
        state["pending"] = {"msg_id": msg_id, "task_id": task_id, "rewrite": rewrite}

        yield build_add_envelope(
            build_card_value(
                task_id=task_id,
                msg_id=msg_id,
                thread_id=thread_id,
                title=_CARD_TITLE,
                desc=rewrite,
                frame_type="ver",
                priority="p1",
                open_=True,
                steps=_build_proactive_steps(
                    original_query=state["original_query"],
                    rewrite=rewrite,
                    rationale=rationale,
                ),
                actions=_default_actions(),
                status="ready",
                index=len(state["rounds"]) + 1,
                extra_meta={
                    "module": self.name,
                    "rewrite": rewrite,
                    "rationale": rationale,
                    "original_query": state["original_query"],
                    "allow_freetext": True,
                    "skip_allowed": True,
                },
            ),
            task_status=TASK_STATUS_FEEDBACK,
        )

    # ------------------------------------------------------------------
    # Reply path — both ``module_reply`` (proactive) and ``edit`` (reactive)
    # ------------------------------------------------------------------

    async def consume_reply(
        self,
        body: dict,
        state: dict,
    ) -> AsyncIterator[dict]:
        rt = body.get("type")
        if rt == "edit":
            async for frame in self._consume_edit(body, state):
                yield frame
        else:
            async for frame in self._consume_module_reply(body, state):
                yield frame

    # ----- Reactive edit ---------------------------------------------------

    async def _consume_edit(
        self,
        body: dict,
        state: dict,
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        feedback = (body.get("feedback") or "").strip()
        event_id = body.get("event_id") or ""

        # First-touch state: capture the original query so enrich_prompt has
        # something to anchor on.
        state.setdefault(
            "original_query",
            (body.get("user_prompt") or "").strip(),
        )

        if feedback:
            state.setdefault("edits", []).append(
                {"event_id": event_id, "feedback": feedback},
            )

        state["awaiting_user"] = False
        state["done"] = True

        ack_msg_id = event_id or new_msg_id()
        ack_task_id = body.get("task_id") or ""
        yield build_replace_envelope(
            build_card_value(
                task_id=ack_task_id,
                msg_id=ack_msg_id,
                thread_id=thread_id,
                title=_CARD_TITLE,
                desc=feedback or state.get("rewrite", ""),
                frame_type="ver",
                priority="p1",
                open_=False,
                steps=[
                    make_step(
                        0, "step_edit",
                        title="用户编辑",
                        status="success",
                        summary=feedback,
                    ),
                ],
                actions=[],
                status="success",
                index=len(state.get("edits", [])),
                extra_meta={
                    "module": self.name,
                    "ack": True,
                    "event_id": event_id,
                    "edits_count": len(state.get("edits", [])),
                },
            )
        )

    # ----- Proactive module_reply (skip / approve / edit) ------------------

    async def _consume_module_reply(
        self,
        body: dict,
        state: dict,
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        feedback = (body.get("feedback") or "").strip()
        approve = bool(body.get("approve", False))
        skip = bool(body.get("skip", False))

        pending = state.get("pending") or {}
        pending_msg_id = pending.get("msg_id") or pending.get("task_id") or new_msg_id()
        pending_task_id = pending.get("task_id") or body.get("task_id") or ""
        rewrite = state.get("rewrite") or pending.get("rewrite") or ""

        if skip:
            state["awaiting_user"] = False
            state["done"] = True
            state["skipped"] = True
            state["accepted_rewrite"] = state.get("original_query", "")
            state.pop("pending", None)
            yield build_replace_envelope(
                build_card_value(
                    task_id=pending_task_id,
                    msg_id=pending_msg_id,
                    thread_id=thread_id,
                    title=_CARD_TITLE,
                    desc=rewrite or state.get("original_query", ""),
                    frame_type="ver",
                    priority="p1",
                    open_=False,
                    steps=[
                        make_step(
                            0, "step_skip",
                            title="用户操作",
                            status="success",
                            summary="已跳过确认",
                        ),
                    ],
                    actions=[],
                    status="success",
                    extra_meta={
                        "module": self.name,
                        "skipped": True,
                        "original_query": state.get("original_query", ""),
                    },
                )
            )
            return

        # Invalid: nothing to act on. Re-emit the same proactive question.
        if not feedback and not approve:
            yield build_replace_envelope(
                build_card_value(
                    task_id=pending_task_id,
                    msg_id=pending_msg_id,
                    thread_id=thread_id,
                    title=_CARD_TITLE,
                    desc=rewrite,
                    frame_type="ver",
                    priority="p1",
                    open_=True,
                    steps=_build_proactive_steps(
                        original_query=state.get("original_query", ""),
                        rewrite=rewrite,
                        rationale="",
                    ),
                    actions=_default_actions(),
                    status="ready",
                    extra_meta={
                        "module": self.name,
                        "rewrite": rewrite,
                        "original_query": state.get("original_query", ""),
                        "allow_freetext": True,
                        "skip_allowed": True,
                        "invalid_input": True,
                    },
                ),
                task_status=TASK_STATUS_FEEDBACK,
            )
            return

        # User edited the rewrite (their version wins) or approved as-is.
        accepted = feedback if feedback else rewrite
        state["accepted_rewrite"] = accepted
        state.setdefault("rounds", []).append({
            "rewrite": rewrite,
            "feedback": feedback,
            "approve": approve,
        })
        state["awaiting_user"] = False
        state["done"] = True
        state.pop("pending", None)

        yield build_replace_envelope(
            build_card_value(
                task_id=pending_task_id,
                msg_id=pending_msg_id,
                thread_id=thread_id,
                title=_CARD_TITLE,
                desc=accepted,
                frame_type="ver",
                priority="p1",
                open_=False,
                steps=[
                    make_step(
                        0, "step_rewrite",
                        title="原改写建议",
                        status="success",
                        summary=rewrite,
                    ),
                    make_step(
                        1, "step_accepted",
                        title="用户采纳",
                        status="success",
                        summary=accepted,
                    ),
                ],
                actions=[],
                status="success",
                extra_meta={
                    "module": self.name,
                    "rewrite": rewrite,
                    "accepted": accepted,
                    "approve": approve,
                    "original_query": state.get("original_query", ""),
                },
            )
        )

    # ------------------------------------------------------------------
    # enrich_prompt — runs after done; the writing agent sees the result
    # ------------------------------------------------------------------

    def enrich_prompt(self, body: dict, state: dict) -> dict:
        new_body = dict(body)
        base = (new_body.get("user_prompt") or "").strip()
        if not base:
            base = (state.get("original_query") or "").strip()

        # If the user accepted/edited a rewrite, that becomes the prompt's
        # main body; the original query is preserved in state for reference.
        accepted = (state.get("accepted_rewrite") or "").strip()
        if state.get("skipped"):
            main = base
        elif accepted:
            main = accepted
        else:
            # Defensive: pre-edit only — no proactive round happened. Fall back
            # to the body's original prompt.
            main = base

        edits = state.get("edits") or []
        edit_lines = [e.get("feedback", "").strip() for e in edits]
        edit_lines = [e for e in edit_lines if e]

        parts = [main]
        if edit_lines:
            parts.append("\n[用户编辑补充]")
            parts.extend(f"- {line}" for line in edit_lines)

        new_body["user_prompt"] = "\n".join(parts).strip()
        return new_body
