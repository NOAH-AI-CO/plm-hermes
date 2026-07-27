# -*- coding: utf-8 -*-
"""FastAPI routes for the workspace tracker.

Endpoints (all per-thread, under the ``/api/v2/...`` prefix so the Django
backend's ``V2ResponseWrapperMiddleware`` wraps responses with
``{code, message, data}`` automatically when the front-end goes through it).

Two route families:

- **Legacy (kept for back-compat):** ``GET /api/v2/workspace/{thread_id}`` —
  no user_id, no X-Env. Reads/writes use the legacy
  ``workspace/{thread_id}/state.json`` OSS key. Untouched callers still work.

- **v2 (preferred, used by the writing flow):**
  ``GET /api/v2/workspace/{user_id}/{thread_id}`` with ``X-Env`` header from
  Backend Django proxy. Uses the user-scoped OSS key
  ``workspace/{env}/users/{uid}/sessions/{tid}/state.json``. Reads
  fall back to the legacy key if the new one is missing (covers in-flight
  threads that started before v2).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from agent.workspace.schemas import AssetStatus
from agent.workspace.store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/workspace", tags=["workspace"])


# ----- Request bodies ------------------------------------------------------


class AssetUpsertBody(BaseModel):
    filename: str = Field(description="Including extension, e.g. 'Noah AI Logo.html'")
    oss_key: str = Field(description="Permanent OSS object key")
    oss_url: str = ""
    chat_id: str = ""
    size: int = 0
    subtitle: str = ""
    status: AssetStatus = "needs-review"


class ViewPatchBody(BaseModel):
    patch: dict = Field(default_factory=dict)


# ----- Path resolution -----------------------------------------------------


def _resolve_paths(user_id: Optional[str], thread_id: str, env: Optional[str]):
    """Build a ``WorkspacePaths`` from URL params + X-Env header.

    Returns ``None`` when any required field is missing — the store falls back
    to legacy keys in that case. Validation errors raise 400.
    """
    if not (user_id and env):
        return None
    try:
        from agent.runtime.paths import WorkspacePaths
        return WorkspacePaths(env=env, user_id=user_id, session_id=thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid workspace path: {e}")


# ----- v2 routes (preferred — Backend Django proxy injects user_id + X-Env) -


@router.get("/{user_id}/{thread_id}")
async def get_workspace_v2(
    user_id: str,
    thread_id: str,
    x_env: Optional[str] = Header(default=None, alias="X-Env"),
) -> dict:
    paths = _resolve_paths(user_id, thread_id, x_env)
    store = get_store()
    state = await store.load(thread_id, paths=paths)
    return {
        "task_id": state.task_id,
        "assets": {k: a.model_dump(mode="json") for k, a in state.assets.items()},
        "view_state": state.view_state.model_dump(mode="json"),
        "viewed_files": dict(state.viewed_files),
    }


@router.post("/{user_id}/{thread_id}/asset")
async def upsert_asset_v2(
    user_id: str,
    thread_id: str,
    body: AssetUpsertBody,
    x_env: Optional[str] = Header(default=None, alias="X-Env"),
) -> dict:
    paths = _resolve_paths(user_id, thread_id, x_env)
    store = get_store()
    frame = await store.upsert_asset(
        thread_id,
        filename=body.filename,
        oss_key=body.oss_key,
        oss_url=body.oss_url,
        chat_id=body.chat_id,
        size=body.size,
        subtitle=body.subtitle,
        status=body.status,
        paths=paths,
    )
    return {"ok": True, "frame": frame}


@router.post("/{user_id}/{thread_id}/view")
async def patch_view_v2(
    user_id: str,
    thread_id: str,
    body: ViewPatchBody,
    x_env: Optional[str] = Header(default=None, alias="X-Env"),
) -> dict:
    paths = _resolve_paths(user_id, thread_id, x_env)
    store = get_store()
    frame = await store.apply_view_patch(thread_id, body.patch, paths=paths)
    state = await store.load(thread_id, paths=paths)
    return {
        "ok": True,
        "frame": frame,
        "view_state": state.view_state.model_dump(mode="json"),
    }


@router.post("/{user_id}/{thread_id}/asset/{name}/refresh-url")
async def refresh_asset_url_v2(
    user_id: str,
    thread_id: str,
    name: str,
    x_env: Optional[str] = Header(default=None, alias="X-Env"),
) -> dict:
    paths = _resolve_paths(user_id, thread_id, x_env)
    store = get_store()
    url = await store.refresh_asset_url(thread_id, name, paths=paths)
    if url is None:
        raise HTTPException(status_code=404, detail="asset not found or no oss_key")
    return {"ok": True, "oss_url": url}


# ----- Legacy routes (untouched callers — single-segment thread_id) --------
#
# These remain for any deployment of the Backend proxy that hasn't yet been
# updated to inject ``user_id`` + ``X-Env``. They use the legacy OSS key
# scheme. Once all Backend deployments are updated, these routes can be
# removed in a follow-up.


@router.get("/{thread_id}")
async def get_workspace(thread_id: str) -> dict:
    store = get_store()
    state = await store.load(thread_id)
    return {
        "task_id": state.task_id,
        "assets": {k: a.model_dump(mode="json") for k, a in state.assets.items()},
        "view_state": state.view_state.model_dump(mode="json"),
        "viewed_files": dict(state.viewed_files),
    }


@router.post("/{thread_id}/asset")
async def upsert_asset(thread_id: str, body: AssetUpsertBody) -> dict:
    store = get_store()
    frame = await store.upsert_asset(
        thread_id,
        filename=body.filename,
        oss_key=body.oss_key,
        oss_url=body.oss_url,
        chat_id=body.chat_id,
        size=body.size,
        subtitle=body.subtitle,
        status=body.status,
    )
    return {"ok": True, "frame": frame}


@router.post("/{thread_id}/view")
async def patch_view(thread_id: str, body: ViewPatchBody) -> dict:
    store = get_store()
    frame = await store.apply_view_patch(thread_id, body.patch)
    state = await store.load(thread_id)
    return {
        "ok": True,
        "frame": frame,
        "view_state": state.view_state.model_dump(mode="json"),
    }


@router.post("/{thread_id}/asset/{name}/refresh-url")
async def refresh_asset_url(thread_id: str, name: str) -> dict:
    store = get_store()
    url = await store.refresh_asset_url(thread_id, name)
    if url is None:
        raise HTTPException(status_code=404, detail="asset not found or no oss_key")
    return {"ok": True, "oss_url": url}
