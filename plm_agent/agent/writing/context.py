# -*- coding: utf-8 -*-
"""Runtime context shared across writing agent tools and hooks.

Injected into every ``@function_tool`` via ``RunContextWrapper[WritingContext]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


PHASE_PLANNING = "planning"
PHASE_WRITING = "writing"
PHASE_LANDSCAPE = "landscape"
PHASE_LITERATURE = "literature"
PHASE_CITATION = "citation"


@dataclass
class WritingContext:
    """Per-run state for the writing agent.

    ``sandbox_manager`` is a ``tools.sandbox.sandbox_manager.SandboxManager``
    (typed as Any to avoid import cycles when this module is imported at
    Agent-construction time).
    """

    sandbox_manager: Any = None
    thread_id: str = ""
    correlation_id: str = ""
    api_base_url: str = ""
    current_phase: Optional[str] = None
