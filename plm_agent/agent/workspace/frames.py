# -*- coding: utf-8 -*-
"""``event_v2`` envelope builders specific to the workspace module.

The workspace stream uses a single stable ``msg_id`` per thread (lifetime ==
the thread itself), so most frames are ``op=patch`` against ``/meta_data/...``.
The very first frame for a thread is ``op=add`` carrying the full snapshot so
new clients can hydrate without a separate fetch.

Naming (post v2 rename):
- ``msg_id`` is the per-MessageItem merge key — for workspace this is the
  per-thread stable id (still stored in ``WorkspaceState.task_id`` field for
  compatibility; treat it as the workspace's msg_id semantically).
- The wire envelope ``task_id`` field is the v1-style parent identifier;
  workspace uses ``thread_id`` as its parent context.

All JSON Pointer paths use ``snake_case`` segments (``view_state``,
``viewed_files``) to keep wire field names consistent with the rest of the v2
protocol.
"""

from __future__ import annotations

import time
from typing import Any

from agent.modules._v2_envelope import (
    build_add_envelope,
    build_message_value,
    build_patch_envelope,
)
from agent.workspace.schemas import Asset, WorkspaceState


_SENDER = "system"
_CONTENT_TYPE = "workspace"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_full_snapshot_frame(state: WorkspaceState, thread_id: str) -> dict:
    """``op=add`` envelope carrying the entire workspace document.

    Front-end uses this on first connect / resync — it overwrites whatever
    they had locally for this ``msg_id`` with the authoritative state.
    """
    value = build_message_value(
        task_id=thread_id,
        msg_id=state.task_id,
        thread_id=thread_id,
        content_type=_CONTENT_TYPE,
        text="",
        sender=_SENDER,
        status="ready",
        meta_data={
            "assets": {k: a.model_dump(mode="json") for k, a in state.assets.items()},
            "view_state": state.view_state.model_dump(mode="json"),
            "viewed_files": dict(state.viewed_files),
        },
    )
    return build_add_envelope(value)


def build_asset_upsert_frame(state: WorkspaceState, asset: Asset, thread_id: str = "") -> dict:
    """Insert (or replace) one asset under ``/meta_data/assets/<name>``."""
    return build_patch_envelope(
        task_id=thread_id or state.task_id,
        msg_id=state.task_id,
        patches=[{
            "op": "add",  # JSON Patch ``add`` is upsert at an object property
            "path": f"/meta_data/assets/{_escape(asset.name)}",
            "value": asset.model_dump(mode="json"),
        }],
    )


def build_asset_status_frame(state: WorkspaceState, name: str, status: str, thread_id: str = "") -> dict:
    """Replace just the status field of an existing asset."""
    return build_patch_envelope(
        task_id=thread_id or state.task_id,
        msg_id=state.task_id,
        patches=[{
            "op": "replace",
            "path": f"/meta_data/assets/{_escape(name)}/status",
            "value": status,
        }],
    )


def build_view_state_patch_frame(state: WorkspaceState, fields: dict[str, Any], thread_id: str = "") -> dict:
    """One JSON Patch op per changed view_state field — keeps frames small."""
    patches = [
        {
            "op": "replace",
            "path": f"/meta_data/view_state/{_escape(k)}",
            "value": v,
        }
        for k, v in fields.items()
    ]
    return build_patch_envelope(
        task_id=thread_id or state.task_id,
        msg_id=state.task_id,
        patches=patches,
    )


def build_file_opened_frame(state: WorkspaceState, filename: str, ts: str, thread_id: str = "") -> dict:
    """Append to open_files + record the timestamp in viewed_files in one frame."""
    patches = [
        # Append-end semantics for arrays in JSON Patch is the ``-`` token.
        {
            "op": "add",
            "path": "/meta_data/view_state/open_files/-",
            "value": filename,
        },
        {
            "op": "add",
            "path": f"/meta_data/viewed_files/{_escape(filename)}",
            "value": ts,
        },
    ]
    return build_patch_envelope(
        task_id=thread_id or state.task_id,
        msg_id=state.task_id,
        patches=patches,
    )


def build_file_closed_frame(state: WorkspaceState, idx: int, thread_id: str = "") -> dict:
    """Remove open_files[idx]."""
    return build_patch_envelope(
        task_id=thread_id or state.task_id,
        msg_id=state.task_id,
        patches=[{
            "op": "remove",
            "path": f"/meta_data/view_state/open_files/{idx}",
        }],
    )


# RFC 6901 reserves '/' and '~' inside JSON Pointer segments. Escape them so
# filenames like 'foo/bar.html' don't blow up the patch parser. (Most asset
# names are plain stems, but never trust input.)
def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")
