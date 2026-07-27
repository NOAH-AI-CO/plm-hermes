# -*- coding: utf-8 -*-
"""``CapabilityRegistry`` — single source of truth for skills + modules.

Two related shapes:

- ``SkillSpec`` — declarative description of a capability. Kind discriminator
  controls how the builder consumes it (instruction text, function tools,
  ``.as_tool()`` specialist, handoff specialist).
- ``ModuleSpec`` — mirrors ``agent.modules.base.InteractiveModule`` subclasses
  into the runtime registry so the v2 router can list them alongside skills.
  Modules themselves still go through ``agent/modules/pipeline.py`` (the outer
  preflight router) — runtime never builds them directly.

Import-clean: this module imports nothing from ``agent.*``; ``ModuleSpec.cls``
and ``args_model`` are typed loosely on purpose so the runtime layer stays
below the agent layer in the dependency graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Tuple


class CapabilityKind(str, Enum):
    PROMPT_SKILL = "prompt_skill"
    TOOL_BUNDLE = "tool_bundle"
    SPECIALIST_TOOL = "specialist_tool"
    SPECIALIST_HANDOFF = "specialist_handoff"
    INTERACTIVE_MODULE = "interactive_module"


@dataclass(frozen=True)
class SkillSpec:
    id: str
    name: str
    description: str
    kind: CapabilityKind
    instructions: Any = ""  # str | Callable[[RuntimeContext], str]
    tools: Tuple[Any, ...] = ()
    specialist_factory: Optional[Callable[..., Any]] = None
    as_tool_name: Optional[str] = None
    as_tool_description: Optional[str] = None
    output_extractor: Optional[Callable[..., Any]] = None
    # Per-turn visibility gate for SPECIALIST_TOOL. SDK signature:
    # ``(run_context, agent) -> bool``. Builder forwards to ``.as_tool()``.
    is_enabled: Optional[Callable[..., bool]] = None
    triggers: Tuple[str, ...] = ()
    allowed_agents: Optional[Tuple[str, ...]] = None
    version: str = "1"


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    name: str
    description: str
    cls: Any  # Type[InteractiveModule] — typed loosely to keep import-clean
    args_model: Any  # Type[BaseModel]
    triggers: Tuple[str, ...] = ()
    allowed_agents: Optional[Tuple[str, ...]] = None
    version: str = "1"


@dataclass(frozen=True)
class CapabilityView:
    skills: Tuple[SkillSpec, ...] = ()
    modules: Tuple[ModuleSpec, ...] = ()


class CapabilityRegistry:
    """Singleton registry. Skills and modules indexed by id."""

    _instance: "Optional[CapabilityRegistry]" = None

    def __new__(cls) -> "CapabilityRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
            cls._instance._modules = {}
        return cls._instance

    _skills: dict
    _modules: dict

    def register_skill(self, spec: SkillSpec) -> None:
        if spec.id in self._skills:
            existing = self._skills[spec.id]
            if existing is spec:
                return  # idempotent
            raise ValueError(
                f"skill {spec.id!r} already registered (existing kind={existing.kind})"
            )
        self._skills[spec.id] = spec

    def register_module(self, spec: ModuleSpec) -> None:
        if spec.id in self._modules:
            existing = self._modules[spec.id]
            if existing is spec:
                return
            raise ValueError(f"module {spec.id!r} already registered")
        self._modules[spec.id] = spec

    def get_skill(self, id: str) -> SkillSpec:
        return self._skills[id]

    def get_module(self, id: str) -> ModuleSpec:
        return self._modules[id]

    def has_skill(self, id: str) -> bool:
        return id in self._skills

    def has_module(self, id: str) -> bool:
        return id in self._modules

    def list_for_agent(self, agent_name: str) -> CapabilityView:
        """Return capabilities visible to a given agent (filtered by allowed_agents)."""
        skills = tuple(
            s for s in self._skills.values()
            if s.allowed_agents is None or agent_name in s.allowed_agents
        )
        modules = tuple(
            m for m in self._modules.values()
            if m.allowed_agents is None or agent_name in m.allowed_agents
        )
        return CapabilityView(skills=skills, modules=modules)

    def reset(self) -> None:
        """Drop all registrations. Used by tests; never called from production."""
        self._skills = {}
        self._modules = {}


def get_registry() -> CapabilityRegistry:
    return CapabilityRegistry()


def register_skill(spec: SkillSpec) -> SkillSpec:
    """Convenience: register at import time and return the spec for binding."""
    get_registry().register_skill(spec)
    return spec
