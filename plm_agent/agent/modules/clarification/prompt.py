# -*- coding: utf-8 -*-
"""Prompt strings for ClarificationModule.

The judge prompt that used to live here has moved into
``agent.modules.router`` (single router LLM for all modules). This file
is kept as a placeholder for any clarification-specific prompts a future
revision may want to add (e.g., per-domain phrasing for the question).
"""

# Intentionally empty — kept for future use. ClarificationModule no longer
# has its own judge LLM; the router decides via ``args_model`` schema.
