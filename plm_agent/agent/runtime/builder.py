# -*- coding: utf-8 -*-
"""``build_agent_from_plan`` — construct an OpenAI Agents SDK ``Agent`` from a
``CapabilityPlan`` and ``RuntimeContext``.

Dispatches on ``SkillSpec.kind``:

- ``PROMPT_SKILL`` → instructions appended to manager
- ``TOOL_BUNDLE`` → ``spec.tools`` extended onto manager.tools
- ``SPECIALIST_TOOL`` → ``spec.specialist_factory(ctx, model)`` built, then
  ``.as_tool(tool_name=..., tool_description=..., custom_output_extractor=...)``
- ``SPECIALIST_HANDOFF`` → ``spec.specialist_factory(ctx, model)`` added to handoffs
- ``INTERACTIVE_MODULE`` → out-of-scope; ``ModulePipeline`` handles those.

Pure builder: same plan + same context → same Agent shape. ``hooks`` is **not**
a builder argument — it's passed to ``Runner.run_streamed`` by the caller.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional

from agent.runtime.context import RuntimeContext
from agent.runtime.registry import (
    CapabilityKind,
    CapabilityRegistry,
    SkillSpec,
    get_registry,
)
from agent.runtime.router import CapabilityPlan

logger = logging.getLogger(__name__)


def build_agent_from_plan(
    *,
    agent_name: str,
    plan: CapabilityPlan,
    context: RuntimeContext,
    base_instructions: str,
    base_tools: Iterable[Any] = (),
    model: Any,
    model_settings: Optional[Any] = None,
    input_guardrails: Optional[List[Any]] = None,
    output_guardrails: Optional[List[Any]] = None,
    registry: Optional[CapabilityRegistry] = None,
) -> Any:
    """Build an Agent[RuntimeContext] from the plan.

    Returns the SDK Agent. Caller passes it to ``Runner.run_streamed`` along
    with hooks/session/run_config/max_turns.
    """
    # Deferred import — keeps ``agent.runtime`` importable even when the SDK
    # isn't installed (useful for unit tests that don't touch the SDK).
    from agents import Agent

    registry = registry or get_registry()
    specs: List[SkillSpec] = _resolve_specs(plan, registry)

    instructions_parts: List[str] = [base_instructions] if base_instructions else []
    tools: List[Any] = list(base_tools)
    handoffs: List[Any] = []

    for spec in specs:
        text = _resolve_instructions(spec, context)
        if text:
            instructions_parts.append(f"## Skill: {spec.name}\n{text}")

        if spec.kind == CapabilityKind.PROMPT_SKILL:
            continue
        if spec.kind == CapabilityKind.TOOL_BUNDLE:
            tools.extend(spec.tools)
            continue
        if spec.kind == CapabilityKind.SPECIALIST_TOOL:
            tools.append(_build_specialist_tool(spec, context, model))
            continue
        if spec.kind == CapabilityKind.SPECIALIST_HANDOFF:
            handoffs.append(_build_specialist_handoff(spec, context, model))
            continue
        if spec.kind == CapabilityKind.INTERACTIVE_MODULE:
            logger.warning(
                "[builder] INTERACTIVE_MODULE %r selected; modules go through "
                "ModulePipeline, not the inner builder. Skipping.",
                spec.id,
            )
            continue
        logger.warning("[builder] unknown skill kind %r on %r", spec.kind, spec.id)

    instructions = "\n\n".join(instructions_parts)

    kwargs: dict = dict(
        name=agent_name,
        instructions=instructions,
        tools=tools,
        handoffs=handoffs,
        model=model,
    )
    if model_settings is not None:
        kwargs["model_settings"] = model_settings
    if input_guardrails is not None:
        kwargs["input_guardrails"] = input_guardrails
    if output_guardrails is not None:
        kwargs["output_guardrails"] = output_guardrails

    return Agent(**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_specs(
    plan: CapabilityPlan, registry: CapabilityRegistry,
) -> List[SkillSpec]:
    out: List[SkillSpec] = []
    for sid in plan.skills:
        if not registry.has_skill(sid):
            logger.warning("[builder] plan referenced unknown skill %r; skipping", sid)
            continue
        out.append(registry.get_skill(sid))
    return out


def _resolve_instructions(spec: SkillSpec, ctx: RuntimeContext) -> str:
    instr = spec.instructions
    if not instr:
        return ""
    if callable(instr):
        try:
            return str(instr(ctx) or "")
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[builder] instructions callable failed for %r: %s", spec.id, e,
            )
            return ""
    return str(instr)


def _build_specialist_tool(
    spec: SkillSpec, ctx: RuntimeContext, model: Any,
) -> Any:
    if spec.specialist_factory is None:
        raise ValueError(
            f"SkillSpec {spec.id!r} kind=SPECIALIST_TOOL must have specialist_factory"
        )
    if not spec.as_tool_name:
        raise ValueError(
            f"SkillSpec {spec.id!r} kind=SPECIALIST_TOOL must have as_tool_name"
        )
    sub_agent = spec.specialist_factory(ctx, model)
    as_tool_kwargs: dict = dict(
        tool_name=spec.as_tool_name,
        tool_description=spec.as_tool_description or spec.description,
    )
    if spec.output_extractor is not None:
        as_tool_kwargs["custom_output_extractor"] = spec.output_extractor
    if spec.is_enabled is not None:
        as_tool_kwargs["is_enabled"] = spec.is_enabled
    return sub_agent.as_tool(**as_tool_kwargs)


def _build_specialist_handoff(
    spec: SkillSpec, ctx: RuntimeContext, model: Any,
) -> Any:
    if spec.specialist_factory is None:
        raise ValueError(
            f"SkillSpec {spec.id!r} kind=SPECIALIST_HANDOFF must have specialist_factory"
        )
    return spec.specialist_factory(ctx, model)
