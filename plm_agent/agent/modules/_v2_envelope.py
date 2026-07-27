# -*- coding: utf-8 -*-
"""event_v2 envelope builders for InteractiveModule frames.

The general_writing flow speaks pure v2 protocol — frames are
``{event_v2: {op, task_id, msg_id, value | patches}, protocol_version: 2}``
with no legacy fields. Other agents are unaffected; their pipelines
keep emitting whatever they emit today.

Naming (post-rename):
- ``msg_id`` is the per-MessageItem merge key (frontend Map key, React key)
- ``task_id`` is the v1-style parent Task UUID — passed in from Backend via
  the chat request body. Multiple MessageItems share one ``task_id``.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional


def iso_now() -> str:
    """ISO 8601 UTC timestamp (``YYYY-MM-DDTHH:MM:SSZ``).

    Public so emitters can stamp ``end_time`` consistently when a MessageItem
    transitions to a terminal status (``success`` / ``error`` / ``abandon``
    / ``failed``).
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# Internal alias kept for callers inside this module.
_iso_now = iso_now


def new_msg_id() -> str:
    """Fresh per-MessageItem id (the merge key)."""
    return str(uuid.uuid4())


def build_message_value(
    task_id: str,
    msg_id: str,
    thread_id: str,
    content_type: str,
    text: str,
    *,
    sender: str = "assistant",
    status: str = "ready",
    index: int = 0,
    context: Optional[dict] = None,
    meta_data: Optional[dict] = None,
    end_time: Optional[str] = None,
    actions: Optional[list[dict]] = None,
) -> dict:
    """Build the inner ``value`` of an event_v2 envelope (a MessageItem).

    Both ``task_id`` (v1-style parent) and ``msg_id`` (per-message merge
    key) are required and are echoed both at envelope and value level.

    ``context`` carries user-message attachments (files / folders /
    parent_id) per frontend ``MessageContext`` schema. Use ``meta_data``
    for structured assistant-side extras (plan tasks, search graph,
    sources, agent_status, etc.) — the two are intentionally distinct.
    """
    value: dict[str, Any] = {
        "task_id": task_id,
        "msg_id": msg_id,
        "thread_id": thread_id,
        "sender": sender,
        "status": status,
        "index": index,
        "start_time": _iso_now(),
        "end_time": end_time,
        "context": context,
        "content": {"type": content_type, "text": text},
        "meta_data": meta_data,
    }
    if actions is not None:
        # ``actions`` sits at value top-level (sibling of ``content`` / ``meta_data``)
        # per the card-protocol contract — front-end reads it directly from the
        # MessageItem to render the bottom-row buttons.
        value["actions"] = list(actions)
    return value


# Task-level execution status carried at the envelope top level (alongside
# ``task_id``). One of: ``running`` / ``complete`` / ``abandon`` / ``failed``
# / ``error``. The front-end reads this off any frame to lock/unlock the
# composer and decide whether to show the cancel button — no need to query
# history. ``running`` covers both LLM/tool execution AND HITL pauses
# (clarification/confirmation): the task is alive, the HITL widget owns its
# own input. Defaults to ``running`` because most frames are mid-execution;
# emitters pass explicit terminal values on the last frame of a turn.
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETE = "complete"
TASK_STATUS_ABANDON = "abandon"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_ERROR = "error"
# Card-protocol additions: surfaced when a frame carries actions[] awaiting a
# user click (FEEDBACK) or when the run is in the outline/planning phase
# (OUTLINE). The front-end uses these to swap the composer / show the card-
# focused UI; the runner itself doesn't branch on them.
TASK_STATUS_FEEDBACK = "feedback"
TASK_STATUS_OUTLINE = "outline"


# ---------------------------------------------------------------------------
# ExecuteCard protocol — content.type="executeCard" with structured meta_data + actions[].
# Front-end consumes this for all "讲解卡片" / "行动卡片" / "思考链卡片"
# variants; only ``frame_type`` / ``priority`` / contents differ between
# card kinds.
# ---------------------------------------------------------------------------


def make_step(
    index: int,
    id: str,
    title: str,
    *,
    status: str = "loading",
    summary: str = "",
) -> dict:
    """One row inside ``meta_data.steps[]`` (label on the left, body on right)."""
    return {
        "index": index,
        "id": id,
        "title": title,
        "status": status,
        "summary": summary,
    }


def make_action(
    index: int,
    model: str,
    text: str,
    *,
    type_: str = "default",
    disabled: bool = False,
) -> dict:
    """One button in ``value.actions[]``.

    ``model`` is the front-end's routing hint and maps back to the reply
    body as: clarification → ``module="clarification"``, confirm →
    ``module="confirmation"`` + ``approve=true``, revision →
    ``module="confirmation"`` + ``approve=false`` + freetext feedback.
    """
    return {
        "index": index,
        "model": model,
        "text": text,
        "type": type_,
        "disabled": disabled,
    }


def build_card_value(
    task_id: str,
    msg_id: str,
    thread_id: str,
    *,
    title: str,
    desc: str = "",
    frame_type: str = "ver",
    priority: str = "p1",
    open_: bool = False,
    steps: Optional[list[dict]] = None,
    actions: Optional[list[dict]] = None,
    sender: str = "assistant",
    status: str = "loading",
    index: int = 0,
    end_time: Optional[str] = None,
    context: Optional[dict] = None,
    extra_meta: Optional[dict] = None,
) -> dict:
    """Build a ``content.type="executeCard"`` MessageItem.

    ``extra_meta`` lets module-specific keys (round, original_query, etc.)
    ride along in ``meta_data`` without breaking the standard six fields —
    the card schema is free-form on extra keys.
    """
    meta_data: dict[str, Any] = {
        "title": title,
        "desc": desc,
        "open": open_,
        "frame_type": frame_type,
        "priority": priority,
        "steps": list(steps or ()),
    }
    if extra_meta:
        meta_data.update(extra_meta)
    return build_message_value(
        task_id=task_id,
        msg_id=msg_id,
        thread_id=thread_id,
        content_type="executeCard",
        text="",
        sender=sender,
        status=status,
        index=index,
        end_time=end_time,
        context=context,
        meta_data=meta_data,
        actions=list(actions or ()),
    )


def build_add_envelope(value: dict, task_status: str = TASK_STATUS_RUNNING) -> dict:
    """``op=add`` envelope — first frame for a msg_id; frontend writes directly."""
    return {
        "protocol_version": 2,
        "event_v2": {
            "op": "add",
            "task_id": value["task_id"],
            "task_status": task_status,
            "msg_id":  value["msg_id"],
            "value": value,
        },
    }


def build_replace_envelope(value: dict, task_status: str = TASK_STATUS_RUNNING) -> dict:
    """``op=replace`` envelope — full overwrite of an existing msg_id."""
    return {
        "protocol_version": 2,
        "event_v2": {
            "op": "replace",
            "task_id": value["task_id"],
            "task_status": task_status,
            "msg_id":  value["msg_id"],
            "value": value,
        },
    }


def build_patch_envelope(
    task_id: str, msg_id: str, patches: list[dict],
    task_status: str = TASK_STATUS_RUNNING,
) -> dict:
    """``op=patch`` envelope — RFC 6902 JSON Patch list applied to the local copy."""
    return {
        "protocol_version": 2,
        "event_v2": {
            "op": "patch",
            "task_id": task_id,
            "task_status": task_status,
            "msg_id":  msg_id,
            "patches": patches,
        },
    }
