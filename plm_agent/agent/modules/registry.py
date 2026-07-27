# -*- coding: utf-8 -*-
"""Module registry + agent whitelist.

Plugin model: a module file declares a class decorated with
``@register_module``; importing the file is enough to make it visible to
the router LLM (function calling) and to the reply router (frontend
``type`` field). The lifecycle is: subclass ``InteractiveModule`` →
implement ``run``/``consume_reply`` → decorate the class. No edits to
``pipeline.py`` or ``main.py`` are needed to add a new module.

The whitelist (``MODULE_PIPELINE_AGENTS``) is the safety rail: only
agents in this set are routed through the pipeline. **Currently only
``general_writing``** — adding new agents requires a deliberate edit
here. All other agents go through the unmodified ``/chat`` code path
with byte-identical behavior.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional, Type

from agent.modules.base import InteractiveModule

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, InteractiveModule] = {}
_ROUTABLE_ORDER: list[str] = []
_REPLY_TYPE_MAP: dict[str, str] = {}  # body['type'] → module.name (excludes wildcards)

# ``module_reply`` is a wildcard: routed by ``body['module']`` instead of by
# reply_type, so multiple modules can declare it. Specific types like ``edit``
# are claimed exclusively.
_WILDCARD_REPLY_TYPES = {"module_reply"}

# Whitelist: only these agents go through the module pipeline. Everything else
# in ``main.py /chat`` falls through to the original code path unchanged.
MODULE_PIPELINE_AGENTS: set[str] = {"general_writing"}


def register_module(cls: Type[InteractiveModule]) -> Type[InteractiveModule]:
    """Decorator: registers an ``InteractiveModule`` subclass at import time.

    Raises ``ValueError`` on duplicate ``name`` or duplicate non-wildcard
    ``reply_types`` — fail-fast at import is better than silent override.
    """
    if not cls.name:
        raise ValueError(f"InteractiveModule {cls.__name__} missing 'name'")
    if cls.name in _REGISTRY:
        existing = type(_REGISTRY[cls.name])
        if existing is cls:
            return cls  # idempotent for re-imports
        raise ValueError(
            f"module name {cls.name!r} already registered by {existing.__name__}"
        )

    instance = cls()
    _REGISTRY[cls.name] = instance

    if cls.routable and cls.tool_schema() is not None:
        if cls.name not in _ROUTABLE_ORDER:
            _ROUTABLE_ORDER.append(cls.name)

    for rt in cls.reply_types or ():
        if rt in _WILDCARD_REPLY_TYPES:
            continue
        owner = _REPLY_TYPE_MAP.get(rt)
        if owner and owner != cls.name:
            raise ValueError(
                f"reply_type {rt!r} already owned by {owner!r}; "
                f"cannot register {cls.name!r}"
            )
        _REPLY_TYPE_MAP[rt] = cls.name

    # v2 mirror: also expose this module via the runtime CapabilityRegistry so
    # the new builder/router can list it alongside SkillSpecs. Existing
    # ModulePipeline behavior (above) is unchanged; this is purely additive.
    _mirror_to_runtime_registry(cls)

    return cls


def _mirror_to_runtime_registry(cls: Type[InteractiveModule]) -> None:
    """Best-effort mirror to ``agent.runtime.registry``. Failures are logged
    and ignored — they must not block legacy module registration."""
    try:
        from agent.runtime.registry import ModuleSpec, get_registry

        spec = ModuleSpec(
            id=cls.name,
            name=getattr(cls, "display_name", cls.name) or cls.name,
            description=cls.tool_description or "",
            cls=cls,
            args_model=cls.args_model,
            triggers=tuple(getattr(cls, "triggers", ()) or ()),
            allowed_agents=getattr(cls, "allowed_agents", None),
        )
        get_registry().register_module(spec)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[ModuleRegistry] runtime mirror failed for %r: %s", cls.name, e,
        )


# Back-compat: a few callers (older clarification __init__) used `register(instance)`
def register(module: InteractiveModule) -> None:
    """Legacy registration entry point — equivalent to applying the decorator
    on the class. Prefer ``@register_module`` in new code."""
    register_module(type(module))


def get(name: str) -> InteractiveModule:
    if name not in _REGISTRY:
        raise KeyError(f"Module not registered: {name}")
    return _REGISTRY[name]


def has(name: str) -> bool:
    return name in _REGISTRY


def iter_routable() -> Iterator[InteractiveModule]:
    """Yield routable modules in registration order."""
    for name in _ROUTABLE_ORDER:
        yield _REGISTRY[name]


# Kept for back-compat with code/tests written against the older preflight model.
# ``preflight`` is now an alias for "routable" — the router LLM decides timing.
def iter_preflight() -> Iterator[InteractiveModule]:
    return iter_routable()


def find_by_reply_type(reply_type: Optional[str]) -> Optional[InteractiveModule]:
    """Resolve a non-wildcard reply_type to its owning module."""
    if not reply_type:
        return None
    name = _REPLY_TYPE_MAP.get(reply_type)
    return _REGISTRY.get(name) if name else None


def routes_reply(reply_type: Optional[str]) -> bool:
    """True if a body['type'] value should be dispatched to ``handle_reply``.

    Covers both ``module_reply`` (wildcard, dispatched by ``body['module']``)
    and module-specific reply types like ``edit``.
    """
    if not reply_type:
        return False
    if reply_type in _WILDCARD_REPLY_TYPES:
        return True
    return reply_type in _REPLY_TYPE_MAP


def is_pipeline_enabled(agent_name: str) -> bool:
    """True if the given agent should go through ``ModulePipeline``."""
    return agent_name in MODULE_PIPELINE_AGENTS


def _reset_for_tests() -> None:
    """Test-only: clear registry. Production code never calls this."""
    _REGISTRY.clear()
    _ROUTABLE_ORDER.clear()
    _REPLY_TYPE_MAP.clear()
