# -*- coding: utf-8 -*-
"""Thin ``Session`` adapter for backend-managed conversation history.

Backend is the authoritative source of history (Django stores messages per
``thread_id``). This adapter lets the ``openai-agents`` SDK consume that
history via its ``Session`` protocol without the SDK ever mutating it:

- ``get_items`` returns the ``history_messages`` list that arrived on the
  HTTP request body, already in ``{"role": ..., "content": ...}`` shape.
- ``add_items`` / ``pop_item`` / ``clear_session`` are intentional no-ops —
  the backend owns persistence.

The Runner calls ``get_items`` once at the start of a run to seed input;
it doesn't attempt to mutate a remote session, so these no-ops are safe.
If we ever migrate to a two-way model, replace this with a Django HTTP
round-trip (PATCH /threads/<id>/messages).

Plan decision #5 / #8-layer-4.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from agents.memory import Session

logger = logging.getLogger(__name__)


class BackendSession(Session):
    """Read-only ``Session`` backed by body['history_messages']."""

    def __init__(
        self,
        session_id: str,
        history_messages: Optional[List[dict]] = None,
    ):
        self.session_id = session_id or "default"
        self._items: list[Any] = [
            {"role": h["role"], "content": h["content"]}
            for h in (history_messages or [])
            if isinstance(h, dict) and h.get("role") and h.get("content")
        ]

    async def get_items(self, limit: Optional[int] = None) -> List[Any]:
        if limit is None or limit >= len(self._items):
            return list(self._items)
        return list(self._items[-limit:])

    async def add_items(self, items: List[Any]) -> None:
        # Backend owns persistence; the SDK's in-memory view is local only.
        self._items.extend(items)

    async def pop_item(self) -> Optional[Any]:
        if not self._items:
            return None
        return self._items.pop()

    async def clear_session(self) -> None:
        self._items.clear()


__all__ = ["BackendSession"]
