# -*- coding: utf-8 -*-
"""Registration / gating tests for the ``html-render`` SkillSpec.

Importing ``agent.writing`` triggers ``_register_writing_skills()`` as a
side effect; these tests assert the resulting registry state matches the
declared contract.
"""

from pathlib import Path

import pytest


@pytest.fixture
def writing_imported():
    """Ensure ``agent.writing`` skills are registered before the assertion.

    Other test modules (e.g. ``tests/agent/runtime/test_runtime_registry``)
    use an autouse fixture that ``reset()``s the singleton registry between
    tests, which wipes the skill set populated by the module-level
    ``_register_writing_skills()`` side effect. Re-registering on demand keeps
    these tests order-independent.
    """
    import agent.writing as _writing  # noqa: F401
    from agent.runtime.registry import get_registry

    if not get_registry().has_skill("html-render"):
        _writing._register_writing_skills()
    return True


def test_html_render_registered(writing_imported):
    from agent.runtime.registry import CapabilityKind, get_registry

    reg = get_registry()
    assert reg.has_skill("html-render"), \
        "html-render skill not registered after importing agent.writing"

    spec = reg.get_skill("html-render")
    assert spec.kind is CapabilityKind.SPECIALIST_TOOL
    assert spec.as_tool_name == "render_html"
    assert spec.specialist_factory is not None
    assert spec.allowed_agents == ("general_writing",)
    assert spec.is_enabled is not None  # phase gate must be wired


def test_html_render_phase_gating(writing_imported):
    """`render_html` hidden during planning, visible afterwards."""
    from agent.runtime.registry import get_registry
    from agent.writing.context import (
        PHASE_PLANNING,
        PHASE_WRITING,
        WritingContext,
    )

    spec = get_registry().get_skill("html-render")
    gate = spec.is_enabled

    class _Wrapper:
        """Mimics openai-agents' RunContextWrapper just enough for the gate."""
        def __init__(self, ctx):
            self.context = ctx

    planning_ctx = WritingContext()
    planning_ctx.current_phase = PHASE_PLANNING
    assert gate(_Wrapper(planning_ctx), agent=None) is False

    writing_ctx = WritingContext()
    writing_ctx.current_phase = PHASE_WRITING
    assert gate(_Wrapper(writing_ctx), agent=None) is True

    # Unset phase (run hasn't transitioned to any specialist yet) → hidden.
    empty_ctx = WritingContext()
    empty_ctx.current_phase = ""
    assert gate(_Wrapper(empty_ctx), agent=None) is False


def test_skill_md_loadable():
    """``SKILL.md`` exists and carries the key constraints."""
    skill_path = (
        Path(__file__).resolve().parents[3]
        / "agent" / "writing" / "skills" / "html-render" / "SKILL.md"
    )
    assert skill_path.exists(), f"SKILL.md missing at {skill_path}"
    text = skill_path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    # Spot-check the key directives so silent edits that gut the prompt
    # are caught.
    for needle in ("<!DOCTYPE html>", "安全要求", "Tailwind", "--shadow-sm"):
        assert needle in text, f"SKILL.md missing key directive: {needle!r}"


def test_render_html_plan_label_present():
    """Plan-card label must exist or the front-end falls back to raw name."""
    from agent.writing.hooks import _V2_PLAN_LABELS

    assert "render_html" in _V2_PLAN_LABELS
    title, loading, success = _V2_PLAN_LABELS["render_html"]
    assert title and loading and success
