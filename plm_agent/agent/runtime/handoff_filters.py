# -*- coding: utf-8 -*-
"""Helpers for ``handoff(input_filter=...)`` — compress conversation context
before passing it to a specialist agent.

The OpenAI Agents SDK exposes ``HandoffInputData`` to filters; we operate on
its three fields:
  - ``input_history``   tuple of conversation turns prior to the handoff
  - ``pre_handoff_items`` items generated during the manager's last turn
  - ``new_items``        items generated as part of the handoff itself

Each helper returns a function suitable for the ``input_filter=`` kwarg.
SDK filters run synchronously; if a caller needs memory contents injected,
they must call ``MemoryStore.snapshot()`` ahead of time and bind the result
via a closure (``inject_messages(messages)``).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, List, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filters that inspect HandoffInputData and return a new HandoffInputData
# ---------------------------------------------------------------------------


def keep_user_request_only(data: Any) -> Any:
    """Drop everything except the original user message.

    Useful for specialists that only need the raw request (e.g., Blueprint
    re-plans from scratch).
    """
    history = tuple(_keep_user_messages(getattr(data, "input_history", ())))
    return _replace(data, input_history=history, pre_handoff_items=(), new_items=())


def keep_recent_assistant_text(k: int) -> Callable[[Any], Any]:
    """Keep only the last ``k`` assistant turns (and the original user msg).

    Drops earlier history. Useful for specialists like Citation that want the
    most recent draft but not every turn that preceded it.
    """

    def _filter(data: Any) -> Any:
        history = list(getattr(data, "input_history", ()))
        users = [m for m in history if _role_of(m) == "user"]
        assistants = [m for m in history if _role_of(m) == "assistant"]
        kept_users = users[:1] if users else []
        kept_assistants = assistants[-k:] if k > 0 else []
        merged = kept_users + kept_assistants
        return _replace(
            data,
            input_history=tuple(merged),
            pre_handoff_items=(),
            new_items=(),
        )

    return _filter


def inject_messages(messages: Sequence[dict]) -> Callable[[Any], Any]:
    """Prepend a fixed list of messages to the user-only history.

    Use to splice in pre-computed context (e.g., a ``MemoryStore.snapshot()``
    rendered as a system message) before handing off. Synchronous, side-effect-free.
    """
    fixed = tuple(messages)

    def _filter(data: Any) -> Any:
        kept_users = tuple(_keep_user_messages(getattr(data, "input_history", ())))
        return _replace(
            data,
            input_history=fixed + kept_users,
            pre_handoff_items=(),
            new_items=(),
        )

    return _filter


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _role_of(item: Any) -> Optional[str]:
    if isinstance(item, dict):
        role = item.get("role")
        return str(role) if role else None
    return getattr(item, "role", None)


def _keep_user_messages(items: Iterable[Any]) -> List[Any]:
    out: List[Any] = []
    for it in items:
        if _role_of(it) == "user":
            out.append(it)
    return out


def _replace(data: Any, **changes: Any) -> Any:
    """Return a copy of ``data`` with the named fields replaced.

    Tries ``dataclasses.replace`` first (the SDK uses a frozen dataclass);
    falls back to dict-update or attribute-copy.
    """
    from dataclasses import is_dataclass, replace as dc_replace
    if is_dataclass(data):
        return dc_replace(data, **changes)
    if isinstance(data, dict):
        out = dict(data)
        out.update(changes)
        return out
    new = type(data).__new__(type(data))
    for k, v in vars(data).items():
        setattr(new, k, v)
    for k, v in changes.items():
        setattr(new, k, v)
    return new
