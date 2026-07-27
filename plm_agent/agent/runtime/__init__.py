# -*- coding: utf-8 -*-
"""``agent.runtime`` — reusable framework for path construction, capability
selection, and request-scoped context. Import-clean: no imports from elsewhere
in ``agent/``.
"""

from agent.runtime.context import RuntimeContext
from agent.runtime.paths import WorkspacePaths
from agent.runtime.registry import (
    CapabilityKind,
    CapabilityRegistry,
    CapabilityView,
    ModuleSpec,
    SkillSpec,
    get_registry,
    register_skill,
)
from agent.runtime.builder import build_agent_from_plan
from agent.runtime.manifest import ArtifactRecord, FileManifest
from agent.runtime.memory import MemoryStore
from agent.runtime.router import CapabilityPlan, PreRunRouter, RouterConfig

__all__ = [
    "ArtifactRecord",
    "CapabilityKind",
    "CapabilityPlan",
    "CapabilityRegistry",
    "CapabilityView",
    "FileManifest",
    "MemoryStore",
    "ModuleSpec",
    "PreRunRouter",
    "RouterConfig",
    "RuntimeContext",
    "SkillSpec",
    "WorkspacePaths",
    "build_agent_from_plan",
    "get_registry",
    "register_skill",
]
