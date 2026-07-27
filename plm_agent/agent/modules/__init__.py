# -*- coding: utf-8 -*-
"""Pluggable interactive modules for the ``general_writing`` flow.

Each submodule registers itself via ``@register_module`` at import time.
The whitelist in ``agent.modules.registry.MODULE_PIPELINE_AGENTS`` decides
which agents actually go through ``ModulePipeline`` — everything else
uses the unmodified ``/chat`` code path in ``main.py``.

Adding a new module: create a ``agent/modules/<name>/module.py`` with a
``@register_module``-decorated subclass of ``InteractiveModule`` plus a
pydantic ``args_model``, then add ``from agent.modules import <name>``
below. The router LLM will see the new tool automatically; no other
changes needed.
"""

# Side-effect imports: each submodule's ``__init__`` triggers ``@register_module``.
from agent.modules import clarification  # noqa: F401
from agent.modules import confirmation   # noqa: F401

# WorkspaceModule lives under ``agent/workspace/`` (not ``agent/modules/``)
# because its store has a longer lifetime than per-conversation modules,
# but it registers through the same decorator so reply routing still works.
from agent import workspace as _workspace_register  # noqa: F401

__all__ = ["clarification", "confirmation"]
