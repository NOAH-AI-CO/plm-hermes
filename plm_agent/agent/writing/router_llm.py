# -*- coding: utf-8 -*-
"""LLM adapter for ``PreRunRouter`` — routes via lite_llm Claude Haiku singleton.

The router only needs an ``async (model, prompt) -> str`` callable; this module
provides one that delegates to ``VertexClaude45Haiku``. The ``model`` arg from
``RouterConfig`` is informational — the singleton already encodes which model
to use (``api_config.VERTEX_CLAUDEHAIKU45_MODEL_ID``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def select_skills_via_llm(*, model: str, prompt: str) -> str:
    """``RouterConfig.llm_call`` adapter for the writing PreRunRouter.

    Returns raw assistant text (JSON expected). ``PreRunRouter._parse``
    handles JSON extraction + skill-id validation, so we only need to
    forward whatever the model produces.
    """
    # Lazy import — keeps ``agent.writing`` package import cheap (e.g. when
    # ``__init__.py`` runs at process startup before lite_llm singletons exist).
    from lite_llm.vertex_claude import VertexClaude45Haiku

    client = VertexClaude45Haiku()  # singleton via AsyncLlmSDKSingleton
    # NOTE: sys_prompt must be a string, not None — VertexClaudeModel.generate
    # forwards it to Anthropic's ``system=`` field, which rejects None
    # ("Input should be a valid list"). Empty string is accepted.
    text = await client.generate(
        input=[{"role": "user", "content": prompt}],
        sys_prompt="",
        max_output_tokens=512,
        temperature=0.0,
    )
    return text or ""
