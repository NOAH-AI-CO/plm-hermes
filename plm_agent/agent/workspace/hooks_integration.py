# -*- coding: utf-8 -*-
"""Bridge between ``WritingRunHooks`` and ``WorkspaceStore``.

When a tool completes inside the writing agent the sandbox may have produced
new files in ``outputs/`` or ``figures/``. We don't get those events from the
SDK — instead we snapshot directory listings around tool execution and diff.
For each new file we ask the sandbox to upload it to OSS (via the existing
``upload_artifacts`` plumbing in ``SandboxManager``) and then record the asset
in the persistent store, returning v2 envelope frames the hook can yield to
the SSE stream.

Snapshots / reconcile are deliberately defensive: any error here must not
crash the writing run, so everything is wrapped in broad ``try/except`` with
warnings logged. The store and the sandbox are both optional — if either is
unavailable, ``reconcile_assets`` is a no-op.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from agent.workspace.store import get_store

logger = logging.getLogger(__name__)


# Directories inside the sandbox workspace where artifacts get written.
# Matches the layout created by SandboxManager._ensure_session_dirs.
_ARTIFACT_DIRS = ("outputs", "figures")


async def snapshot_sandbox_files(sandbox_manager) -> set[str]:
    """Return the set of artifact-relative paths currently in the sandbox.

    Used as the "before" half of the diff in ``reconcile_assets``. Returns an
    empty set when the sandbox isn't ready or listing fails — callers treat
    that as "no baseline" rather than blowing up the run.
    """
    if sandbox_manager is None or sandbox_manager._client is None:
        return set()
    workspace = sandbox_manager.workspace
    paths: set[str] = set()
    for sub in _ARTIFACT_DIRS:
        try:
            entries = await sandbox_manager._client.list_files(f"{workspace}/{sub}")
        except Exception:
            logger.debug("[Workspace] list %s/%s failed", workspace, sub)
            continue
        for entry in entries or []:
            name = _entry_name(entry)
            if name:
                paths.add(f"{sub}/{name}")
    return paths


async def reconcile_assets(
    *,
    sandbox_manager,
    thread_id: str,
    chat_id: str,
    before_snapshot: Optional[set[str]] = None,
    paths=None,
) -> tuple[list[dict], set[str]]:
    """Diff the sandbox against ``before_snapshot``, upload new files, register.

    Returns ``(frames, after_snapshot)``. ``frames`` is the list of v2 envelope
    patches the caller should yield to the SSE queue, in order. ``after_snapshot``
    can be passed back as ``before_snapshot`` to chain reconciles cheaply.
    """
    if not thread_id or sandbox_manager is None:
        return [], before_snapshot or set()

    after = await snapshot_sandbox_files(sandbox_manager)
    new_paths = after - (before_snapshot or set())
    if not new_paths:
        return [], after

    # Push all new files to OSS in one shot — SandboxManager.upload_artifacts
    # already walks outputs/ and figures/ and uploads each. It's slightly
    # over-eager (re-uploads files we'd already seen), but the receiving
    # ``upsert_asset`` is idempotent so duplicates collapse.
    try:
        artifacts = await sandbox_manager.upload_artifacts() or []
    except Exception:
        logger.exception("[Workspace] upload_artifacts failed for %s", thread_id)
        return [], after

    if not artifacts:
        return [], after

    store = get_store()
    out_frames: list[dict] = []
    seen: set[str] = set()
    for art in artifacts:
        filename = art.get("filename") or ""
        oss_url = art.get("oss_url") or ""
        if not filename or filename in seen:
            continue
        seen.add(filename)
        try:
            frame = await store.upsert_asset(
                thread_id,
                filename=filename,
                # SandboxManager uploads under ``nsfc/<session>/<filename>``;
                # store this canonical key so refresh-url can re-presign.
                # We don't try to compute a different key — letting the source
                # of truth (the upload helper) own the key avoids drift.
                oss_key=art.get("oss_key") or f"nsfc/{thread_id}/{filename}",
                oss_url=oss_url,
                chat_id=chat_id,
                paths=paths,
            )
        except Exception:
            logger.exception("[Workspace] upsert_asset failed for %s", filename)
            continue
        if frame is not None:
            out_frames.append(frame)

    return out_frames, after


def _entry_name(entry) -> str:
    """Extract a leaf filename from whatever shape the SDK returned.

    The agentrun SDK has historically returned ``str``, ``dict`` with a
    ``name`` field, or pydantic models. We accept all three.
    """
    if isinstance(entry, str):
        return entry.rsplit("/", 1)[-1]
    if isinstance(entry, dict):
        for key in ("name", "filename", "path"):
            v = entry.get(key)
            if isinstance(v, str) and v:
                return v.rsplit("/", 1)[-1]
        return ""
    name = getattr(entry, "name", None) or getattr(entry, "filename", None)
    if isinstance(name, str):
        return name.rsplit("/", 1)[-1]
    return ""
