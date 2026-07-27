# -*- coding: utf-8 -*-
"""``WorkspaceModule`` — non-routable InteractiveModule that owns the workspace
reply types.

The workspace store is a singleton with a long-lived per-thread lifecycle, so
this module deliberately does **not** participate in router LLM selection
(``routable=False``) and has no ``args_model``. Its only job is to translate
front-end ``body['type']`` events into store mutations and propagate the
resulting v2 envelope frames.

Reply types claimed:
- ``view_state_update``    — generic view_state merge
- ``file_opened``          — record open + viewed_files timestamp
- ``file_closed``          — remove from open_files
- ``tab_activated``        — set active_file_tab
- ``asset_status_update``  — change one asset's status
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from agent.modules.base import InteractiveModule
from agent.modules.registry import register_module
from agent.workspace.store import get_store

logger = logging.getLogger(__name__)


@register_module
class WorkspaceModule(InteractiveModule):
    name = "workspace"
    content_type = "workspace"
    routable = False  # never offered to the router LLM
    reply_types = (
        "view_state_update",
        "file_opened",
        "file_closed",
        "tab_activated",
        "asset_status_update",
    )

    # The base class declares ``run`` abstract because routable modules need it;
    # we implement a no-op so concrete instantiation works.
    async def run(self, body, state, args):  # noqa: ARG002
        if False:
            yield {}  # pragma: no cover

    async def consume_reply(
        self,
        body: dict,
        state: dict,  # unused — workspace state lives in the singleton store
    ) -> AsyncIterator[dict]:
        thread_id = body.get("thread_id") or ""
        if not thread_id:
            logger.warning("[Workspace] reply missing thread_id; ignoring: %s",
                           body.get("type"))
            return

        store = get_store()
        rt = body.get("type")
        frame = None

        try:
            if rt == "view_state_update":
                patch = body.get("patch") or {}
                if not isinstance(patch, dict):
                    logger.warning("[Workspace] view_state_update patch not a dict")
                    return
                frame = await store.apply_view_patch(thread_id, patch)

            elif rt == "file_opened":
                filename = body.get("file") or body.get("filename")
                if filename:
                    frame = await store.record_open(thread_id, filename=filename)

            elif rt == "file_closed":
                filename = body.get("file") or body.get("filename")
                if filename:
                    frame = await store.record_close(thread_id, filename=filename)

            elif rt == "tab_activated":
                idx = body.get("index")
                if isinstance(idx, int):
                    frame = await store.set_active_tab(thread_id, index=idx)

            elif rt == "asset_status_update":
                name = body.get("asset") or body.get("name")
                status = body.get("status")
                if name and status:
                    frame = await store.set_asset_status(
                        thread_id, name=name, status=status,
                    )

            else:
                logger.warning("[Workspace] unknown reply type: %s", rt)
        except Exception:
            logger.exception("[Workspace] consume_reply failed for type=%s", rt)
            return

        if frame is not None:
            yield frame
