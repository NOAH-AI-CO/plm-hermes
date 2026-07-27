# -*- coding: utf-8 -*-
"""Unit tests for ``agent.runtime.registry``."""

import pytest
from pydantic import BaseModel

from agent.runtime.registry import (
    CapabilityKind,
    CapabilityRegistry,
    CapabilityView,
    ModuleSpec,
    SkillSpec,
    get_registry,
    register_skill,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Reset the singleton state for every test in this module."""
    reg = get_registry()
    reg.reset()
    yield
    reg.reset()


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------


def _make_skill(skill_id="x", kind=CapabilityKind.PROMPT_SKILL, **overrides):
    base = dict(
        id=skill_id,
        name=skill_id.title(),
        description=f"{skill_id} description",
        kind=kind,
    )
    base.update(overrides)
    return SkillSpec(**base)


class _Args(BaseModel):
    foo: str = "x"


def _make_module(module_id="m", **overrides):
    base = dict(
        id=module_id,
        name=module_id.title(),
        description=f"{module_id} description",
        cls=object,
        args_model=_Args,
    )
    base.update(overrides)
    return ModuleSpec(**base)


def test_skill_spec_is_hashable_and_frozen():
    spec = _make_skill()
    # frozen dataclass → can't mutate
    with pytest.raises(Exception):
        spec.id = "y"  # type: ignore[misc]
    # hashable → fits in a set/dict key
    assert spec in {spec}


def test_module_spec_defaults():
    spec = _make_module()
    assert spec.triggers == ()
    assert spec.allowed_agents is None


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------


def test_singleton_returns_same_instance():
    a = CapabilityRegistry()
    b = CapabilityRegistry()
    assert a is b
    assert a is get_registry()


def test_register_and_get_skill():
    spec = _make_skill("blueprint")
    get_registry().register_skill(spec)
    assert get_registry().get_skill("blueprint") is spec
    assert get_registry().has_skill("blueprint") is True


def test_register_and_get_module():
    spec = _make_module("workspace")
    get_registry().register_module(spec)
    assert get_registry().get_module("workspace") is spec
    assert get_registry().has_module("workspace") is True


def test_duplicate_skill_with_same_object_is_idempotent():
    spec = _make_skill("blueprint")
    get_registry().register_skill(spec)
    get_registry().register_skill(spec)  # must not raise
    assert get_registry().get_skill("blueprint") is spec


def test_duplicate_skill_with_different_object_raises():
    get_registry().register_skill(_make_skill("blueprint"))
    with pytest.raises(ValueError, match="blueprint"):
        get_registry().register_skill(_make_skill("blueprint", description="other"))


def test_duplicate_module_with_different_object_raises():
    get_registry().register_module(_make_module("workspace"))
    with pytest.raises(ValueError, match="workspace"):
        get_registry().register_module(_make_module("workspace", description="other"))


# ---------------------------------------------------------------------------
# allowed_agents filter
# ---------------------------------------------------------------------------


def test_list_for_agent_returns_unrestricted_skills_to_everyone():
    spec = _make_skill("attachment", allowed_agents=None)
    get_registry().register_skill(spec)
    view = get_registry().list_for_agent("anything")
    assert spec in view.skills


def test_list_for_agent_filters_restricted_skills():
    writing_only = _make_skill("blueprint", allowed_agents=("general_writing",))
    nsfc_only = _make_skill("nsfc-step", allowed_agents=("nsfc_v3",))
    get_registry().register_skill(writing_only)
    get_registry().register_skill(nsfc_only)

    writing_view = get_registry().list_for_agent("general_writing")
    nsfc_view = get_registry().list_for_agent("nsfc_v3")
    other_view = get_registry().list_for_agent("mindsearch")

    assert writing_only in writing_view.skills
    assert nsfc_only not in writing_view.skills
    assert nsfc_only in nsfc_view.skills
    assert other_view.skills == ()


def test_list_for_agent_filters_modules_likewise():
    everyone = _make_module("clarification", allowed_agents=None)
    writing_only = _make_module("workspace", allowed_agents=("general_writing",))
    get_registry().register_module(everyone)
    get_registry().register_module(writing_only)

    view = get_registry().list_for_agent("general_writing")
    assert everyone in view.modules
    assert writing_only in view.modules

    view2 = get_registry().list_for_agent("mindsearch")
    assert everyone in view2.modules
    assert writing_only not in view2.modules


def test_capability_view_is_namedtuple_like():
    view = CapabilityView(skills=(_make_skill("a"),), modules=(_make_module("m"),))
    assert len(view.skills) == 1
    assert len(view.modules) == 1


# ---------------------------------------------------------------------------
# register_skill convenience function
# ---------------------------------------------------------------------------


def test_register_skill_function_returns_spec():
    spec = _make_skill("citation")
    returned = register_skill(spec)
    assert returned is spec
    assert get_registry().get_skill("citation") is spec
