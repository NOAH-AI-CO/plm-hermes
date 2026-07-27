# -*- coding: utf-8 -*-
"""Clarification module — registered via ``@register_module`` at import time."""

from agent.modules.clarification.module import (  # noqa: F401  (import for side effect)
    ClarificationArgs,
    ClarificationModule,
)

__all__ = ["ClarificationArgs", "ClarificationModule"]
