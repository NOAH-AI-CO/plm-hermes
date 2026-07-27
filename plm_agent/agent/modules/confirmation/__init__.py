# -*- coding: utf-8 -*-
"""Confirmation module — registered via ``@register_module`` at import time."""

from agent.modules.confirmation.module import (  # noqa: F401
    ConfirmationArgs,
    ConfirmationModule,
)

__all__ = ["ConfirmationArgs", "ConfirmationModule"]
