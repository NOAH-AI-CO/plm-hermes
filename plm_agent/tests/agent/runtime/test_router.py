# -*- coding: utf-8 -*-
"""Unit tests for ``agent.runtime.router.PreRunRouter``."""

import asyncio

import pytest

from agent.runtime.registry import (
    CapabilityKind,
    SkillSpec,
    get_registry,
)
from agent.runtime.router import (
    CapabilityPlan,
    PreRunRouter,
    RouterConfig,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reg = get_registry()
    reg.reset()
    yield
    reg.reset()


@pytest.fixture
def populated_registry():
    """A registry with 3 skills: 2 for general_writing, 1 unrestricted."""
    reg = get_registry()
    reg.register_skill(SkillSpec(
        id="blueprint", name="Blueprint",
        description="Plan a piece of writing.",
        kind=CapabilityKind.SPECIALIST_TOOL,
        allowed_agents=("general_writing",),
        triggers=("outline", "structure"),
    ))
    reg.register_skill(SkillSpec(
        id="citation", name="Citation",
        description="Manage references.",
        kind=CapabilityKind.SPECIALIST_HANDOFF,
        allowed_agents=("general_writing",),
    ))
    reg.register_skill(SkillSpec(
        id="search", name="Search",
        description="Use search tools.",
        kind=CapabilityKind.PROMPT_SKILL,
        allowed_agents=None,
    ))
    return reg


def _fake_llm(response_text):
    """Build an async LLM call that returns a fixed string."""
    async def _call(*, model, prompt):
        return response_text
    return _call


def _failing_llm(exc):
    async def _call(*, model, prompt):
        raise exc
    return _call


def _slow_llm():
    """Sleeps forever — exercises the timeout path."""
    async def _call(*, model, prompt):
        await asyncio.sleep(60)
        return ""
    return _call


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_selected_skills(populated_registry):
    cfg = RouterConfig(
        llm_call=_fake_llm('{"skills": ["blueprint", "citation"], "reasoning": "outline + cite"}'),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(
        agent_name="general_writing",
        user_prompt="draft a paper outline with citations",
    ))
    assert plan.skills == ["blueprint", "citation"]
    assert plan.reasoning == "outline + cite"


def test_strips_code_fences(populated_registry):
    cfg = RouterConfig(llm_call=_fake_llm(
        '```json\n{"skills": ["blueprint"], "reasoning": "x"}\n```'
    ))
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan.skills == ["blueprint"]


# ---------------------------------------------------------------------------
# Filtering & validation
# ---------------------------------------------------------------------------


def test_unknown_skill_ids_are_dropped(populated_registry):
    cfg = RouterConfig(llm_call=_fake_llm(
        '{"skills": ["blueprint", "fictional", "citation"], "reasoning": "x"}'
    ))
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan.skills == ["blueprint", "citation"]


def test_max_skills_truncation(populated_registry):
    cfg = RouterConfig(
        max_skills=1,
        llm_call=_fake_llm(
            '{"skills": ["blueprint", "citation"], "reasoning": "both"}'
        ),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan.skills == ["blueprint"]


def test_duplicate_ids_deduped(populated_registry):
    cfg = RouterConfig(llm_call=_fake_llm(
        '{"skills": ["blueprint", "blueprint", "citation"], "reasoning": "x"}'
    ))
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan.skills == ["blueprint", "citation"]


def test_only_skills_visible_to_agent_are_listed_in_prompt(populated_registry):
    """When LLM picks 'blueprint' for an agent that's NOT 'general_writing',
    blueprint is not visible to that agent and must be dropped."""
    cfg = RouterConfig(llm_call=_fake_llm(
        '{"skills": ["blueprint", "search"], "reasoning": "x"}'
    ))
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="some_other_agent", user_prompt="hi"))
    # blueprint is allowed_agents=("general_writing",) → dropped
    # search is allowed_agents=None → kept
    assert plan.skills == ["search"]


# ---------------------------------------------------------------------------
# Fallback paths
# ---------------------------------------------------------------------------


def test_empty_registry_returns_empty_plan():
    # Don't use populated_registry — registry is reset by fixture.
    cfg = RouterConfig(llm_call=_fake_llm("{}"))
    router = PreRunRouter(get_registry(), cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan.skills == []
    assert "no skills registered" in plan.reasoning


def test_empty_user_prompt_returns_fallback(populated_registry):
    fallback = CapabilityPlan(skills=["search"], reasoning="empty input fallback")
    cfg = RouterConfig(
        fallback_plan=fallback,
        llm_call=_fake_llm("ignored"),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt=""))
    assert plan is fallback


def test_llm_error_returns_fallback(populated_registry):
    fallback = CapabilityPlan(skills=["search"], reasoning="fallback")
    cfg = RouterConfig(
        fallback_plan=fallback,
        llm_call=_failing_llm(RuntimeError("network down")),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan is fallback


def test_timeout_returns_fallback(populated_registry):
    fallback = CapabilityPlan(skills=[], reasoning="timeout fallback")
    cfg = RouterConfig(
        timeout_s=0.05,
        fallback_plan=fallback,
        llm_call=_slow_llm(),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan is fallback


def test_malformed_json_returns_fallback(populated_registry):
    fallback = CapabilityPlan(skills=[], reasoning="parse fallback")
    cfg = RouterConfig(
        fallback_plan=fallback,
        llm_call=_fake_llm("not json at all"),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan is fallback


def test_skills_not_a_list_returns_fallback(populated_registry):
    fallback = CapabilityPlan(skills=[], reasoning="schema fallback")
    cfg = RouterConfig(
        fallback_plan=fallback,
        llm_call=_fake_llm('{"skills": "blueprint", "reasoning": "wrong"}'),
    )
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan is fallback


def test_no_llm_call_configured_falls_back(populated_registry):
    """Production path: caller forgot to wire llm_call → fallback, never crash."""
    fallback = CapabilityPlan(skills=[], reasoning="no llm")
    cfg = RouterConfig(fallback_plan=fallback, llm_call=None)
    router = PreRunRouter(populated_registry, cfg)
    plan = asyncio.run(router.select(agent_name="general_writing", user_prompt="hi"))
    assert plan is fallback


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_includes_visible_skills_only(populated_registry):
    captured = {}

    async def _capturing_llm(*, model, prompt):
        captured["prompt"] = prompt
        return '{"skills": [], "reasoning": "test"}'

    cfg = RouterConfig(llm_call=_capturing_llm)
    router = PreRunRouter(populated_registry, cfg)
    asyncio.run(router.select(
        agent_name="general_writing",
        user_prompt="Need an outline",
        current_phase="blueprint",
    ))
    prompt = captured["prompt"]
    assert "blueprint" in prompt
    assert "citation" in prompt
    assert "search" in prompt
    assert "Need an outline" in prompt
    assert "blueprint" in prompt  # current_phase value


def test_prompt_excludes_skills_not_visible_to_agent(populated_registry):
    captured = {}

    async def _capturing_llm(*, model, prompt):
        captured["prompt"] = prompt
        return '{"skills": [], "reasoning": "x"}'

    cfg = RouterConfig(llm_call=_capturing_llm)
    router = PreRunRouter(populated_registry, cfg)
    asyncio.run(router.select(agent_name="other_agent", user_prompt="hi"))
    prompt = captured["prompt"]
    # blueprint and citation are gated to general_writing → must not appear
    assert "blueprint" not in prompt
    assert "citation" not in prompt
    assert "search" in prompt
