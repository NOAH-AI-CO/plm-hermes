# -*- coding: utf-8 -*-
"""Unit tests for ``agent.runtime.builder.build_agent_from_plan``.

These tests exercise the dispatcher logic without spinning up a real LLM —
factories return stub objects and we inspect the Agent's composed
instructions/tools/handoffs.
"""

import pytest

from agent.runtime.builder import build_agent_from_plan
from agent.runtime.context import RuntimeContext
from agent.runtime.paths import WorkspacePaths
from agent.runtime.registry import (
    CapabilityKind,
    SkillSpec,
    get_registry,
)
from agent.runtime.router import CapabilityPlan


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_registry():
    reg = get_registry()
    reg.reset()
    yield
    reg.reset()


@pytest.fixture
def ctx():
    return RuntimeContext(
        paths=WorkspacePaths(env="dev", user_id="42", session_id="abc-123"),
    )


class _StubSubAgent:
    """Minimal stand-in for ``Agent`` used as a specialist factory output."""

    def __init__(self, name):
        self.name = name

    def as_tool(self, **kwargs):
        return {
            "kind": "as_tool_result",
            "name": self.name,
            "kwargs": kwargs,
        }


def _factory(name):
    """Return a factory that produces stub sub-agents named ``name``."""
    def _make(ctx, model):
        return _StubSubAgent(name)
    return _make


def _model():
    """Use None — Agent accepts None and our builder only forwards it."""
    return None


# ---------------------------------------------------------------------------
# Happy path — each kind composes correctly
# ---------------------------------------------------------------------------


def test_prompt_skill_appends_instructions(ctx):
    spec = SkillSpec(
        id="attachment", name="Attachment",
        description="…", kind=CapabilityKind.PROMPT_SKILL,
        instructions="Handle attachments carefully.",
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["attachment"]),
        context=ctx,
        base_instructions="BASE",
        base_tools=[],
        model=_model(),
    )
    assert "BASE" in agent.instructions
    assert "## Skill: Attachment" in agent.instructions
    assert "Handle attachments carefully." in agent.instructions
    assert agent.tools == []
    assert agent.handoffs == []


def test_tool_bundle_appends_tools(ctx):
    tool_a = {"sentinel": "tool_a"}
    tool_b = {"sentinel": "tool_b"}
    spec = SkillSpec(
        id="search", name="Search",
        description="…", kind=CapabilityKind.TOOL_BUNDLE,
        instructions="Use search wisely.",
        tools=(tool_a, tool_b),
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["search"]),
        context=ctx,
        base_instructions="BASE",
        base_tools=[],
        model=_model(),
    )
    assert tool_a in agent.tools
    assert tool_b in agent.tools
    assert "Use search wisely." in agent.instructions


def test_specialist_tool_invokes_factory_and_as_tool(ctx):
    extractor = lambda x: "extracted"
    spec = SkillSpec(
        id="blueprint", name="Blueprint",
        description="Plan writing.", kind=CapabilityKind.SPECIALIST_TOOL,
        instructions="Plan first.",
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
        as_tool_description="Custom desc.",
        output_extractor=extractor,
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["blueprint"]),
        context=ctx,
        base_instructions="BASE",
        base_tools=[],
        model=_model(),
    )
    assert len(agent.tools) == 1
    tool_entry = agent.tools[0]
    assert tool_entry["kind"] == "as_tool_result"
    assert tool_entry["name"] == "blueprint_agent"
    assert tool_entry["kwargs"]["tool_name"] == "plan_writing"
    assert tool_entry["kwargs"]["tool_description"] == "Custom desc."
    assert tool_entry["kwargs"]["custom_output_extractor"] is extractor
    assert agent.handoffs == []


def test_specialist_tool_passes_is_enabled_to_as_tool(ctx):
    """``SkillSpec.is_enabled`` must reach ``.as_tool(is_enabled=...)``.

    Without this the writing agent loses its phase-based gate on
    ``plan_writing`` (hides it once the run leaves the planning phase).
    """
    def _gate(run_context, agent):
        return False  # body irrelevant; we check identity

    spec = SkillSpec(
        id="blueprint", name="Blueprint",
        description="…", kind=CapabilityKind.SPECIALIST_TOOL,
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
        is_enabled=_gate,
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["blueprint"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    tool_entry = agent.tools[0]
    assert tool_entry["kwargs"]["is_enabled"] is _gate


def test_specialist_tool_omits_is_enabled_when_not_set(ctx):
    spec = SkillSpec(
        id="blueprint", name="Blueprint",
        description="…", kind=CapabilityKind.SPECIALIST_TOOL,
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["blueprint"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    tool_entry = agent.tools[0]
    assert "is_enabled" not in tool_entry["kwargs"]


def test_specialist_tool_falls_back_to_description_when_as_tool_description_missing(ctx):
    spec = SkillSpec(
        id="blueprint", name="Blueprint",
        description="Default tool desc.",
        kind=CapabilityKind.SPECIALIST_TOOL,
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["blueprint"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    tool_entry = agent.tools[0]
    assert tool_entry["kwargs"]["tool_description"] == "Default tool desc."
    assert "custom_output_extractor" not in tool_entry["kwargs"]


def test_specialist_handoff_adds_to_handoffs(ctx):
    spec = SkillSpec(
        id="citation", name="Citation",
        description="Cite sources.",
        kind=CapabilityKind.SPECIALIST_HANDOFF,
        instructions="Do citations.",
        specialist_factory=_factory("citation_agent"),
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["citation"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    assert len(agent.handoffs) == 1
    sub = agent.handoffs[0]
    assert isinstance(sub, _StubSubAgent)
    assert sub.name == "citation_agent"
    assert agent.tools == []
    assert "Do citations." in agent.instructions


def test_interactive_module_kind_is_skipped(ctx):
    """INTERACTIVE_MODULE is handled by the outer ModulePipeline, not the builder."""
    spec = SkillSpec(
        id="workspace", name="Workspace",
        description="…", kind=CapabilityKind.INTERACTIVE_MODULE,
        instructions="Manage workspace.",
    )
    get_registry().register_skill(spec)
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["workspace"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    assert agent.tools == []
    assert agent.handoffs == []


# ---------------------------------------------------------------------------
# Composition across multiple skills
# ---------------------------------------------------------------------------


def test_multiple_skills_compose(ctx):
    get_registry().register_skill(SkillSpec(
        id="attachment", name="Attachment", description="…",
        kind=CapabilityKind.PROMPT_SKILL,
        instructions="Handle uploads.",
    ))
    get_registry().register_skill(SkillSpec(
        id="blueprint", name="Blueprint", description="Plan.",
        kind=CapabilityKind.SPECIALIST_TOOL,
        instructions="Plan first.",
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
    ))
    get_registry().register_skill(SkillSpec(
        id="citation", name="Citation", description="Cite.",
        kind=CapabilityKind.SPECIALIST_HANDOFF,
        specialist_factory=_factory("citation_agent"),
    ))
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["attachment", "blueprint", "citation"]),
        context=ctx,
        base_instructions="BASE",
        base_tools=[{"sentinel": "base_tool"}],
        model=_model(),
    )
    # Instructions: BASE + each skill's section
    assert "BASE" in agent.instructions
    assert "## Skill: Attachment" in agent.instructions
    assert "## Skill: Blueprint" in agent.instructions
    # Citation has no instructions text but is a handoff
    # base tool plus blueprint .as_tool result
    assert {"sentinel": "base_tool"} in agent.tools
    assert any(
        isinstance(t, dict) and t.get("name") == "blueprint_agent"
        for t in agent.tools
    )
    assert any(
        isinstance(h, _StubSubAgent) and h.name == "citation_agent"
        for h in agent.handoffs
    )


def test_unknown_skill_in_plan_is_dropped(ctx):
    get_registry().register_skill(SkillSpec(
        id="blueprint", name="Blueprint",
        description="…", kind=CapabilityKind.SPECIALIST_TOOL,
        specialist_factory=_factory("blueprint_agent"),
        as_tool_name="plan_writing",
    ))
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["blueprint", "fictional"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    # Only blueprint should be present
    assert len(agent.tools) == 1


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_specialist_tool_without_factory_raises(ctx):
    get_registry().register_skill(SkillSpec(
        id="blueprint", name="Blueprint",
        description="…", kind=CapabilityKind.SPECIALIST_TOOL,
        as_tool_name="plan_writing",
    ))
    with pytest.raises(ValueError, match="specialist_factory"):
        build_agent_from_plan(
            agent_name="general_writing",
            plan=CapabilityPlan(skills=["blueprint"]),
            context=ctx,
            base_instructions="BASE",
            model=_model(),
        )


def test_specialist_tool_without_as_tool_name_raises(ctx):
    get_registry().register_skill(SkillSpec(
        id="blueprint", name="Blueprint",
        description="…", kind=CapabilityKind.SPECIALIST_TOOL,
        specialist_factory=_factory("blueprint_agent"),
    ))
    with pytest.raises(ValueError, match="as_tool_name"):
        build_agent_from_plan(
            agent_name="general_writing",
            plan=CapabilityPlan(skills=["blueprint"]),
            context=ctx,
            base_instructions="BASE",
            model=_model(),
        )


def test_specialist_handoff_without_factory_raises(ctx):
    get_registry().register_skill(SkillSpec(
        id="citation", name="Citation",
        description="…", kind=CapabilityKind.SPECIALIST_HANDOFF,
    ))
    with pytest.raises(ValueError, match="specialist_factory"):
        build_agent_from_plan(
            agent_name="general_writing",
            plan=CapabilityPlan(skills=["citation"]),
            context=ctx,
            base_instructions="BASE",
            model=_model(),
        )


# ---------------------------------------------------------------------------
# Callable instructions
# ---------------------------------------------------------------------------


def test_callable_instructions_receive_context(ctx):
    captured = {}

    def _instructions(c):
        captured["ctx"] = c
        return f"phase={c.phase}"

    get_registry().register_skill(SkillSpec(
        id="dynamic", name="Dynamic",
        description="…", kind=CapabilityKind.PROMPT_SKILL,
        instructions=_instructions,
    ))
    ctx.set_phase("blueprint")
    agent = build_agent_from_plan(
        agent_name="general_writing",
        plan=CapabilityPlan(skills=["dynamic"]),
        context=ctx,
        base_instructions="BASE",
        model=_model(),
    )
    assert captured["ctx"] is ctx
    assert "phase=blueprint" in agent.instructions
