# -*- coding: utf-8 -*-
"""Guardrails for the writing agent (P3).

Four guardrails in one module:

- Agent input  — ``empty_input_guardrail``: trip on empty / whitespace-only
  user input so the SDK raises before a run starts.
- Agent output — ``empty_output_guardrail``: trip on empty / obviously
  broken final outputs so the caller sees a typed error instead of an
  empty SSE stream.
- Tool input   — ``url_count_guardrail``: cap URL-list tools at 10 URLs
  (externalising the manual check inside ``attachment_download`` so it
  shows up in SDK traces and can be toggled centrally).
- Tool output  — ``sandbox_output_size_guardrail``: truncate tool outputs
  that exceed ``_OUTPUT_HARD_LIMIT`` and surface the truncation via
  ``reject_content`` so the model sees a clear marker.

Wiring:
- Manager agent picks up the two agent-level guardrails via
  ``input_guardrails=[...]`` / ``output_guardrails=[...]`` in ``agent.py``.
- Tool guardrails attach via ``@function_tool(tool_input_guardrails=[...]
  , tool_output_guardrails=[...])`` in ``tools.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Union

from agents import (
    GuardrailFunctionOutput,
    RunContextWrapper,
    input_guardrail,
    output_guardrail,
)
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    ToolOutputGuardrailData,
    tool_input_guardrail,
    tool_output_guardrail,
)

logger = logging.getLogger(__name__)


# Thresholds — tune here; intentionally a bit generous.
_URL_HARD_LIMIT = 10
_OUTPUT_HARD_LIMIT = 20_000  # chars of serialized tool output


# ---------------------------------------------------------------------------
# Agent input guardrail — empty / whitespace-only user message
# ---------------------------------------------------------------------------


def _extract_last_user_text(input_items: Union[str, List[Any]]) -> str:
    """Best-effort: pull the latest user-provided text out of the input.

    The SDK passes either a raw string or a list of TResponseInputItem-style
    dicts. We care only about whether *some* user text is present.
    """
    if isinstance(input_items, str):
        return input_items
    if not isinstance(input_items, list):
        return ""
    for item in reversed(input_items):
        content = None
        if isinstance(item, dict):
            role = item.get("role", "")
            content = item.get("content")
            if role != "user":
                continue
        else:
            role = getattr(item, "role", "")
            content = getattr(item, "content", None)
            if role != "user":
                continue
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Flatten parts that expose a ``text`` or ``input_text`` field.
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    t = part.get("text") or part.get("input_text") or ""
                    if t:
                        parts.append(t)
                elif hasattr(part, "text"):
                    t = getattr(part, "text", "") or ""
                    if t:
                        parts.append(t)
            return "\n".join(parts)
    return ""


@input_guardrail
async def empty_input_guardrail(
    ctx: RunContextWrapper[Any],
    agent: Any,
    input_items: Union[str, List[Any]],
) -> GuardrailFunctionOutput:
    """Trip if the latest user message is empty or too short to be a task."""
    text = _extract_last_user_text(input_items).strip()
    tripped = len(text) < 2
    return GuardrailFunctionOutput(
        output_info={"reason": "empty_or_too_short" if tripped else "ok", "length": len(text)},
        tripwire_triggered=tripped,
    )


# ---------------------------------------------------------------------------
# Agent output guardrail — empty / whitespace-only final answer
# ---------------------------------------------------------------------------


@output_guardrail
async def empty_output_guardrail(
    ctx: RunContextWrapper[Any],
    agent: Any,
    agent_output: Any,
) -> GuardrailFunctionOutput:
    """Trip if the agent's final output has no user-visible text."""
    if agent_output is None:
        return GuardrailFunctionOutput(output_info={"reason": "none"}, tripwire_triggered=True)
    text = agent_output if isinstance(agent_output, str) else str(agent_output)
    tripped = not text.strip()
    return GuardrailFunctionOutput(
        output_info={"reason": "empty" if tripped else "ok", "length": len(text)},
        tripwire_triggered=tripped,
    )


# ---------------------------------------------------------------------------
# Tool input guardrail — URL list ≤ 10
# ---------------------------------------------------------------------------


@tool_input_guardrail
async def url_count_guardrail(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
    """Cap URL-list tools at 10 URLs per invocation.

    Parses ``tool_arguments`` JSON and inspects the ``urls`` field. If the
    caller passes more than 10 entries, we reject the call with a message
    the model can read and retry with a smaller list.
    """
    raw = getattr(data.context, "tool_arguments", "") or ""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return ToolGuardrailFunctionOutput.allow({"reason": "non-json-args"})
    urls = parsed.get("urls") if isinstance(parsed, dict) else None
    if not isinstance(urls, list):
        return ToolGuardrailFunctionOutput.allow({"reason": "no-urls-field"})
    if len(urls) > _URL_HARD_LIMIT:
        return ToolGuardrailFunctionOutput.reject_content(
            message=(
                f"Too many URLs ({len(urls)}). "
                f"Send at most {_URL_HARD_LIMIT} URLs per call; split the list and retry."
            ),
            output_info={"url_count": len(urls), "limit": _URL_HARD_LIMIT},
        )
    return ToolGuardrailFunctionOutput.allow({"url_count": len(urls)})


# ---------------------------------------------------------------------------
# Tool output guardrail — truncate oversized outputs
# ---------------------------------------------------------------------------


def _serialize_for_size(output: Any) -> str:
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, default=str)
    except Exception:
        return str(output)


@tool_output_guardrail
async def sandbox_output_size_guardrail(
    data: ToolOutputGuardrailData,
) -> ToolGuardrailFunctionOutput:
    """Replace oversized sandbox outputs with a head-truncated summary.

    The in-tool truncation in ``run_in_sandbox`` already caps per-stream at
    ~15K chars; this guardrail catches combined / unexpected growth paths
    and makes the truncation visible to the model through ``reject_content``.
    """
    text = _serialize_for_size(data.output)
    if len(text) <= _OUTPUT_HARD_LIMIT:
        return ToolGuardrailFunctionOutput.allow({"size": len(text)})
    head = text[: _OUTPUT_HARD_LIMIT]
    return ToolGuardrailFunctionOutput.reject_content(
        message=(
            f"{head}\n\n...[tool output truncated by guardrail: "
            f"{len(text) - _OUTPUT_HARD_LIMIT} chars dropped; "
            f"limit={_OUTPUT_HARD_LIMIT}]"
        ),
        output_info={"original_size": len(text), "kept": _OUTPUT_HARD_LIMIT},
    )


__all__ = [
    "empty_input_guardrail",
    "empty_output_guardrail",
    "url_count_guardrail",
    "sandbox_output_size_guardrail",
]
