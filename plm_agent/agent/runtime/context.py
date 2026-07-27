# -*- coding: utf-8 -*-
"""``RuntimeContext`` — request-scoped carrier for paths, plan, phase, sandbox.

A small dataclass passed to every component that needs to know about the
current request. Mutable for ``plan`` / ``phase`` / ``sandbox_manager`` so they
can be filled in as the run progresses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from agent.runtime.paths import WorkspacePaths

if TYPE_CHECKING:
    from agent.runtime.router import CapabilityPlan


@dataclass
class RuntimeContext:
    paths: WorkspacePaths
    log_id: str = ""
    plan: "Optional[CapabilityPlan]" = None
    phase: Optional[str] = None
    sandbox_manager: Optional[Any] = None  # tools.sandbox.sandbox_manager.SandboxManager

    def set_phase(self, phase: str) -> None:
        self.phase = phase
