# -*- coding: utf-8 -*-
"""``WorkspaceStore`` — persistent per-thread workspace state, OSS-backed.

State lives in a single JSON object per thread:
    ``{bucket}/workspace/{thread_id}/state.json``

OSS reads/writes go through ``utils.core.aliyun_oss_client`` helpers and run on
``asyncio.to_thread`` because the SDK is synchronous. A bounded LRU keeps the
most recently touched threads in memory so back-to-back updates don't pay the
network round-trip every time. Cache invalidation is trivial: every mutator
saves to OSS and refreshes the cache slot atomically.

The store is intentionally **decoupled from the sandbox lifecycle**: a thread's
sandbox can be destroyed and rebuilt without losing assets or view state.
That's why the asset entry stores both ``oss_key`` (permanent) and ``oss_url``
(presigned, expires) — see ``schemas.Asset``.

Mutator methods all return the v2 envelope frame the caller should yield to
the front-end so updates show up in flight without a separate fetch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import OrderedDict
from typing import Optional

from config import api_config
from utils.core.aliyun_oss_client import (
    get_object_text,
    presign_get,
    put_object_text,
)

from agent.workspace import frames
from agent.workspace.schemas import (
    Asset,
    AssetStatus,
    ViewState,
    WorkspaceState,
    empty_state,
)

logger = logging.getLogger(__name__)

_CACHE_MAX = 256
_OSS_PREFIX = "workspace"


def _legacy_state_key(thread_id: str) -> str:
    return f"{_OSS_PREFIX}/{thread_id}/state.json"


def _legacy_asset_key(thread_id: str, filename: str) -> str:
    return f"{_OSS_PREFIX}/{thread_id}/assets/{filename}"


def _state_key(thread_id: str, paths=None) -> str:
    """OSS key for the workspace state JSON.

    With ``paths`` (writing v2 contract), use the user-scoped key
    ``workspace/{env}/users/{uid}/sessions/{tid}/state.json``. Without paths
    (legacy callers, untouched), use the original ``workspace/{tid}/state.json``.
    """
    if paths is not None and not paths.is_legacy:
        return f"{paths.oss_workspace_prefix}/state.json"
    return _legacy_state_key(thread_id)


def _asset_key(thread_id: str, filename: str, paths=None) -> str:
    if paths is not None and not paths.is_legacy:
        return f"{paths.oss_workspace_prefix}/assets/{filename}"
    return _legacy_asset_key(thread_id, filename)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class WorkspaceStore:
    """Singleton OSS-backed store keyed by ``thread_id``."""

    _instance: Optional["WorkspaceStore"] = None

    def __new__(cls) -> "WorkspaceStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = OrderedDict()
            cls._instance._locks: dict[str, asyncio.Lock] = {}
        return cls._instance

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    _cache: "OrderedDict[str, WorkspaceState]"
    _locks: "dict[str, asyncio.Lock]"

    def _cache_get(self, thread_id: str) -> Optional[WorkspaceState]:
        st = self._cache.get(thread_id)
        if st is not None:
            self._cache.move_to_end(thread_id)
        return st

    def _cache_put(self, thread_id: str, state: WorkspaceState) -> None:
        self._cache[thread_id] = state
        self._cache.move_to_end(thread_id)
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)

    def _lock_for(self, thread_id: str) -> asyncio.Lock:
        lock = self._locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[thread_id] = lock
        return lock

    # ------------------------------------------------------------------
    # OSS I/O (sync SDK → wrap with to_thread)
    # ------------------------------------------------------------------

    @property
    def _bucket(self) -> str:
        # The sandbox-mounted bucket — ``project-sandbox`` in production.
        # Distinct from ``ALIOSS_BUCKET`` (``noahserver-public``), which is
        # the public asset bucket used by ``upload_template_file``.
        return api_config.ALIYUN_SANDBOX_BUCKET

    async def _load_from_oss(self, thread_id: str, paths=None) -> Optional[WorkspaceState]:
        # Try the v2 (paths-aware) key first when provided; fall back to the
        # legacy key so in-flight threads from before this refactor still load.
        keys_to_try = [_state_key(thread_id, paths)]
        legacy = _legacy_state_key(thread_id)
        if keys_to_try[0] != legacy:
            keys_to_try.append(legacy)

        for key in keys_to_try:
            try:
                raw = await asyncio.to_thread(
                    get_object_text, self._bucket, key,
                )
            except Exception:
                logger.exception("[Workspace] OSS load failed for %s (key=%s)", thread_id, key)
                continue
            if raw is None:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[Workspace] corrupt state for %s (key=%s); skipping",
                               thread_id, key)
                continue
            try:
                state = WorkspaceState.model_validate(data)
            except Exception:
                logger.exception("[Workspace] state schema mismatch for %s (key=%s)",
                                 thread_id, key)
                continue
            return state
        return None

    async def _save_to_oss(self, thread_id: str, state: WorkspaceState, paths=None) -> None:
        try:
            payload = state.model_dump_json(indent=2, exclude_none=False)
            await asyncio.to_thread(
                put_object_text,
                self._bucket,
                _state_key(thread_id, paths),
                payload,
                "application/json",
            )
        except Exception:
            logger.exception("[Workspace] OSS save failed for %s", thread_id)
            # Cache is still up to date; we'll retry next mutation.

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    async def load(self, thread_id: str, *, paths=None) -> WorkspaceState:
        """Return the state, hydrating from OSS or creating an empty document.

        ``paths`` (optional) — when supplied, the v2 user-scoped OSS key is used
        for read+write. Without it, the legacy ``workspace/{tid}/state.json``
        key is used, identical to pre-v2 behavior.
        """
        cached = self._cache_get(thread_id)
        if cached is not None:
            return cached

        async with self._lock_for(thread_id):
            return await self._load_under_lock(thread_id, paths=paths)

    async def _load_under_lock(self, thread_id: str, *, paths=None) -> WorkspaceState:
        """Internal load for callers that already hold ``_lock_for(thread_id)``.

        Mutators acquire the lock around their whole read-modify-write cycle, so
        they can't go through ``load()`` (which would re-acquire the lock and
        deadlock). They call this helper instead.
        """
        cached = self._cache_get(thread_id)
        if cached is not None:
            return cached
        state = await self._load_from_oss(thread_id, paths=paths)
        if state is None:
            state = empty_state(task_id=str(uuid.uuid4()))
            await self._save_to_oss(thread_id, state, paths=paths)
        self._cache_put(thread_id, state)
        return state

    async def snapshot_frame(self, thread_id: str, *, paths=None) -> dict:
        """Build the ``op=add`` full-snapshot frame for a fresh client."""
        state = await self.load(thread_id, paths=paths)
        return frames.build_full_snapshot_frame(state, thread_id)

    # ------------------------------------------------------------------
    # Mutators — each returns the v2 envelope frame to push to the front-end
    # ------------------------------------------------------------------

    async def upsert_asset(
        self,
        thread_id: str,
        *,
        filename: str,
        oss_key: str,
        oss_url: str = "",
        chat_id: str = "",
        size: int = 0,
        subtitle: str = "",
        status: AssetStatus = "needs-review",
        paths=None,
    ) -> Optional[dict]:
        """Add or update one asset. Returns the patch frame, or None on no-op.

        ``filename`` is the display name (with extension); ``name`` (the map
        key) is derived as the file stem so two extensions of the same logical
        artifact stay separate entries (matches the front-end's expectation).
        """
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            stem, _, ext = filename.rpartition(".") if "." in filename else (filename, "", "")
            name = stem or filename
            existing = state.assets.get(name)
            asset = Asset(
                name=name,
                filename=filename,
                ext=ext,
                size=size or (existing.size if existing else 0),
                created_at=(existing.created_at if existing and existing.created_at
                             else _now_iso()),
                chat_id=chat_id or (existing.chat_id if existing else ""),
                status=status if not existing else existing.status,
                subtitle=subtitle or (existing.subtitle if existing else ""),
                oss_key=oss_key,
                oss_url=oss_url or (existing.oss_url if existing else ""),
            )
            if existing and existing.model_dump() == asset.model_dump():
                return None  # nothing actually changed → don't bother the wire
            state.assets[name] = asset
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            return frames.build_asset_upsert_frame(state, asset)

    async def set_asset_status(
        self,
        thread_id: str,
        *,
        name: str,
        status: AssetStatus,
        paths=None,
    ) -> Optional[dict]:
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            asset = state.assets.get(name)
            if asset is None or asset.status == status:
                return None
            asset.status = status
            state.assets[name] = asset
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            return frames.build_asset_status_frame(state, name, status)

    async def apply_view_patch(
        self,
        thread_id: str,
        patch: dict,
        *,
        paths=None,
    ) -> Optional[dict]:
        """Merge top-level view_state fields. Unknown fields are passed through
        because the schema has ``extra='allow'``."""
        if not patch:
            return None
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            current = state.view_state.model_dump()
            current.update(patch)
            try:
                state.view_state = ViewState.model_validate(current)
            except Exception:
                logger.exception("[Workspace] invalid view patch %s", patch)
                return None
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            return frames.build_view_state_patch_frame(state, patch)

    async def record_open(
        self,
        thread_id: str,
        *,
        filename: str,
        paths=None,
    ) -> Optional[dict]:
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            ts = _now_iso()
            already_open = filename in state.view_state.open_files
            state.viewed_files[filename] = ts
            if not already_open:
                state.view_state.open_files.append(filename)
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            if already_open:
                # Only the timestamp changed; emit a minimal patch.
                return frames.build_view_state_patch_frame(
                    state, {"open_files": state.view_state.open_files},
                )
            return frames.build_file_opened_frame(state, filename, ts)

    async def record_close(
        self,
        thread_id: str,
        *,
        filename: str,
        paths=None,
    ) -> Optional[dict]:
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            try:
                idx = state.view_state.open_files.index(filename)
            except ValueError:
                return None
            state.view_state.open_files.pop(idx)
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            return frames.build_file_closed_frame(state, idx)

    async def set_active_tab(
        self,
        thread_id: str,
        *,
        index: int,
        paths=None,
    ) -> Optional[dict]:
        async with self._lock_for(thread_id):
            state = await self._load_under_lock(thread_id, paths=paths)
            if state.view_state.active_file_tab == index:
                return None
            state.view_state.active_file_tab = index
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
            return frames.build_view_state_patch_frame(state, {"active_file_tab": index})

    # ------------------------------------------------------------------
    # OSS asset helpers
    # ------------------------------------------------------------------

    @staticmethod
    def asset_object_key(thread_id: str, filename: str, paths=None) -> str:
        """Public helper so callers can compute the canonical key without the
        store loaded — used by ``hooks_integration`` when it asks the sandbox
        to upload a file straight to ``workspace/<tid>/assets/<filename>`` (or
        the v2 user-scoped equivalent when ``paths`` is supplied)."""
        return _asset_key(thread_id, filename, paths=paths)

    async def refresh_asset_url(self, thread_id: str, name: str, *, paths=None) -> Optional[str]:
        """Re-presign an asset's URL (used by ``/refresh-url`` REST endpoint)."""
        state = await self.load(thread_id, paths=paths)
        asset = state.assets.get(name)
        if asset is None or not asset.oss_key:
            return None
        try:
            url = await asyncio.to_thread(presign_get, self._bucket, asset.oss_key)
        except Exception:
            logger.exception("[Workspace] presign failed for %s", asset.oss_key)
            return None
        async with self._lock_for(thread_id):
            asset.oss_url = url
            state.assets[name] = asset
            await self._save_to_oss(thread_id, state, paths=paths)
            self._cache_put(thread_id, state)
        return url


# Module-level convenience accessor — most callers just want the singleton.
def get_store() -> WorkspaceStore:
    return WorkspaceStore()


def _reset_for_tests() -> None:
    """Test-only: drop the singleton so each test starts clean."""
    if WorkspaceStore._instance is not None:
        WorkspaceStore._instance._cache.clear()
        WorkspaceStore._instance._locks.clear()
    WorkspaceStore._instance = None
