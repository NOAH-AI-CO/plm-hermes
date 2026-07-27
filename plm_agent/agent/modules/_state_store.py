# -*- coding: utf-8 -*-
"""NAS-backed module state store with in-memory LRU cache.

Storage layout (one file per thread, all module states inside):

    /mnt/workspace/sessions/{thread_id}/.modules/state.json
    {
        "version": 1,
        "modules": {
            "clarification": {...},
            "confirmation":  {...}
        }
    }

A merged file means each ``/chat`` request reads at most one NAS file
even when many modules participate. Backwards compatibility: when the
merged file is missing we fall back to the older per-module layout
(``.modules/<name>.json``) so existing thread state isn't lost.

Public API is two-tiered:
- Per-module helpers (``load_state`` / ``save_state`` / ``drop_state``):
  used by ``InteractiveModule.load_state`` for compatibility with code
  that touches a single module at a time (tests, ad-hoc paths).
- Thread-level helpers (``load_thread_state`` / ``save_thread_state``):
  used by the pipeline for the common case of "load every module's
  state for this thread, then save them all back".

Cache behaviour: in-memory LRU keyed by ``(thread_id, module_name)``.
Thread-level helpers populate the cache for every module they touch so
subsequent per-module reads short-circuit.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Optional

from tools.sandbox.sandbox_manager import SandboxManager

logger = logging.getLogger(__name__)

# Bounded cache so a long-running process can't accumulate state for every
# thread we've ever seen. 512 modules-per-thread is comfortably above any
# realistic concurrent session count for general_writing.
_CACHE_MAX = 512
_cache: "OrderedDict[tuple[str, str], dict]" = OrderedDict()

_STATE_VERSION = 1


def _cache_key(thread_id: str, module_name: str) -> tuple[str, str]:
    return (thread_id or "__no_thread__", module_name)


def _cache_get(thread_id: str, module_name: str) -> Optional[dict]:
    key = _cache_key(thread_id, module_name)
    if key not in _cache:
        return None
    _cache.move_to_end(key)
    return _cache[key]


def _cache_put(thread_id: str, module_name: str, state: dict) -> None:
    key = _cache_key(thread_id, module_name)
    _cache[key] = state
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def _cache_drop(thread_id: str, module_name: str) -> None:
    _cache.pop(_cache_key(thread_id, module_name), None)


def _module_state_dir(thread_id: str, sandbox: Optional[SandboxManager]) -> str:
    """Resolve the .modules/ directory, using sandbox.paths when available.

    For non-writing callers that built the sandbox with only ``session_id``,
    ``sandbox.paths`` is the legacy form and this returns the legacy directory.
    For writing callers passing ``workspace_paths``, this returns the
    user-scoped directory.
    """
    paths = getattr(sandbox, "paths", None) if sandbox is not None else None
    if paths is not None:
        return paths.module_state_dir
    return f"/mnt/workspace/sessions/{thread_id}/.modules"


def _merged_state_path(thread_id: str, sandbox: Optional[SandboxManager]) -> str:
    return f"{_module_state_dir(thread_id, sandbox)}/state.json"


def _legacy_module_state_path(
    thread_id: str, module_name: str, sandbox: Optional[SandboxManager],
) -> str:
    return f"{_module_state_dir(thread_id, sandbox)}/{module_name}.json"


# ----------------------------------------------------------------------
# Thread-level API (preferred entrypoint for pipeline)
# ----------------------------------------------------------------------


async def load_thread_state(
    thread_id: str,
    *,
    sandbox: Optional[SandboxManager] = None,
) -> dict[str, dict]:
    """Return all module states for a thread as a dict ``{name: state}``.

    Cache-first: returns whatever's already in cache merged with what's on
    NAS (cache wins on conflict). Falls back to legacy per-module files if
    the merged file is absent.
    """
    if not thread_id or sandbox is None:
        # No sandbox / thread → cache only.
        return _collect_cached_for_thread(thread_id)

    try:
        client = await sandbox.get_client()
        raw = await client.read_file(_merged_state_path(thread_id, sandbox))
    except FileNotFoundError:
        raw = None
    except Exception as e:
        logger.warning(
            "[ModuleStateStore] thread load failed for %s: %s", thread_id, e,
        )
        raw = None

    states: dict[str, dict] = {}
    if raw:
        try:
            doc = json.loads(raw)
            modules = doc.get("modules") if isinstance(doc, dict) else None
            if isinstance(modules, dict):
                states = {k: dict(v) for k, v in modules.items() if isinstance(v, dict)}
        except json.JSONDecodeError as e:
            logger.warning(
                "[ModuleStateStore] corrupt thread state %s: %s", thread_id, e,
            )

    # Cache wins on conflict (it represents the latest in-process write).
    cached = _collect_cached_for_thread(thread_id)
    states.update(cached)

    # Refresh cache with whatever we ended up with so subsequent per-module
    # reads short-circuit.
    for name, st in states.items():
        _cache_put(thread_id, name, st)

    return states


async def save_thread_state(
    thread_id: str,
    states: dict[str, dict],
    *,
    sandbox: Optional[SandboxManager] = None,
) -> None:
    """Persist a full snapshot of module states for the thread to NAS."""
    for name, st in states.items():
        _cache_put(thread_id, name, st)

    if not thread_id or sandbox is None:
        return

    payload = json.dumps(
        {"version": _STATE_VERSION, "modules": states},
        ensure_ascii=False,
        indent=2,
    )
    try:
        client = await sandbox.get_client()
        # ``.modules/`` is created once per sandbox lifetime by
        # ``AgentRunSandboxClient._ensure_session_dirs`` — no per-save mkdir.
        await client.write_file(
            path=_merged_state_path(thread_id, sandbox), content=payload,
        )
    except Exception as e:
        logger.warning(
            "[ModuleStateStore] thread save failed for %s: %s", thread_id, e,
        )


# ----------------------------------------------------------------------
# Per-module API (used by InteractiveModule.load_state, tests)
# ----------------------------------------------------------------------


async def load_state(
    thread_id: str,
    module_name: str,
    *,
    sandbox: Optional[SandboxManager] = None,
) -> dict:
    """Return one module's state. Cache-first; pulls thread file on miss."""
    cached = _cache_get(thread_id, module_name)
    if cached is not None:
        return dict(cached)

    if not thread_id or sandbox is None:
        return {}

    # Pull the merged file (which also populates cache for every module).
    states = await load_thread_state(thread_id, sandbox=sandbox)
    if module_name in states:
        return dict(states[module_name])

    # Backward compat: try the older per-module file layout.
    try:
        client = await sandbox.get_client()
        raw = await client.read_file(
            _legacy_module_state_path(thread_id, module_name, sandbox)
        )
        if not raw:
            return {}
        legacy = json.loads(raw)
        if not isinstance(legacy, dict):
            return {}
        _cache_put(thread_id, module_name, legacy)
        return dict(legacy)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        logger.warning(
            "[ModuleStateStore] corrupt legacy state for %s/%s: %s",
            thread_id, module_name, e,
        )
        return {}
    except Exception as e:
        logger.warning(
            "[ModuleStateStore] legacy load failed for %s/%s: %s",
            thread_id, module_name, e,
        )
        return {}


async def save_state(
    thread_id: str,
    module_name: str,
    state: dict,
    *,
    sandbox: Optional[SandboxManager] = None,
) -> None:
    """Persist one module's state. Reads-modify-writes the merged file.

    Falls back to a cache-only update when ``thread_id`` or ``sandbox`` is
    unavailable, which preserves the in-process semantics callers were used
    to from the original per-module store.
    """
    _cache_put(thread_id, module_name, state)

    if not thread_id or sandbox is None:
        return

    # Read existing merged file (or empty), update slot, write back.
    states = await load_thread_state(thread_id, sandbox=sandbox)
    states[module_name] = state
    await save_thread_state(thread_id, states, sandbox=sandbox)


def drop_state(thread_id: str, module_name: str) -> None:
    """Invalidate the cache entry for a (thread, module) pair."""
    _cache_drop(thread_id, module_name)


# ----------------------------------------------------------------------
# Internal
# ----------------------------------------------------------------------


def _collect_cached_for_thread(thread_id: str) -> dict[str, dict]:
    target = thread_id or "__no_thread__"
    out: dict[str, dict] = {}
    for (tid, name), state in _cache.items():
        if tid == target:
            out[name] = dict(state)
    return out
