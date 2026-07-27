# -*- coding: utf-8 -*-
"""Model factory for the writing agent.

The factory ``build_default_model()`` returns the Model instance passed to
``Agent(model=...)`` — a ``Model`` protocol implementation from
``openai-agents`` SDK.

P1 implementation: ``OpenAIChatCompletionsModel`` wired to an
``AsyncAzureOpenAI`` client. Future adapters for non-OpenAI providers
(Claude, Gemini, composite fallback) will replace the internals of this
function without touching Agent construction sites.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_azure_client = None


def _get_azure_client():
    """Lazy-init a singleton ``AsyncAzureOpenAI`` client."""
    global _azure_client
    if _azure_client is not None:
        return _azure_client

    import httpx
    from openai import AsyncAzureOpenAI

    from config import api_config

    # Bump connect timeout from the SDK default (5s). Cross-Pacific TLS
    # handshakes to the Azure endpoint regularly exceed 5s in practice,
    # causing spurious "Request timed out" failures before the model is
    # even reached. Read/write/pool stay at the SDK default (600s).
    _azure_client = AsyncAzureOpenAI(
        api_key=api_config.AZURE_GPT4_OPENAI_API_KEY,
        api_version=api_config.AZURE_GPT5_VERSION,
        azure_endpoint=api_config.AZURE_GPT4_AZURE_ENDPOINT,
        timeout=httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=600.0),
    )
    return _azure_client


def build_default_model(deployment: Optional[str] = None):
    """Return the default ``Model`` for the writing agent.

    P1: Azure ChatGPT (gpt-5-mini) via Chat Completions.
    """
    from agents import OpenAIChatCompletionsModel

    from config import api_config

    target = deployment or api_config.AZURE_GPT5_MIN_DEPLOYMENT
    return OpenAIChatCompletionsModel(
        model=target,
        openai_client=_get_azure_client(),
    )


def build_model(name: str = "default"):
    """Return a named ``Model``. Extension point for future providers."""
    if name in ("default", "azure-gpt5-mini"):
        return build_default_model()
    if name == "azure-gpt5":
        from config import api_config
        return build_default_model(api_config.AZURE_GPT5_DEPLOYMENT)
    if name == "azure-gpt4o":
        from config import api_config
        return build_default_model(api_config.AZURE_GPT4_AZURE_DEPLOYMENT)
    raise ValueError(f"Unknown model name: {name!r}")
