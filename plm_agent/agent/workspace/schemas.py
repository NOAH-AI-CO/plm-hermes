# -*- coding: utf-8 -*-
"""Pydantic models for the ``general_writing`` workspace tracker.

Persisted shape (one OSS object per thread, ``workspace/{thread_id}/state.json``):

* ``Asset`` — one entry per artifact produced by the writing flow. Indexed by
  the file's stem in ``WorkspaceState.assets`` to match the front-end's expected
  ``{ 'Noah AI Logo': {...}, 'Noah AI Logo v2': {...} }`` map.
* ``ViewState`` — opaque UI state pushed up by the front-end (active tabs,
  open files, folder navigation history). The backend doesn't interpret it;
  it just persists and broadcasts.
* ``WorkspaceState`` — the full per-thread document with a stable v2 envelope
  ``task_id`` so the front-end merges every workspace frame onto the same
  local object.

All field names here use ``snake_case`` to match the rest of the v2 protocol
(``task_id``, ``thread_id``, ``content.type``, ``meta_data`` …). All ISO-8601
timestamps are produced by the helpers in ``store.py`` so we have a single
source of truth for the format (UTC, no microseconds).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Coarse status taxonomy; extend as the product evolves.
AssetStatus = Literal["needs-review", "reviewed", "archived"]


class Asset(BaseModel):
    """One artifact tracked in the workspace tree."""

    model_config = ConfigDict(extra="allow")  # tolerate unknown fields from older clients

    name: str = Field(description="File stem; matches the assets map key")
    filename: str = Field(description="Full file name including extension")
    ext: str = Field(default="", description="File extension without dot")
    size: int = Field(default=0, description="Bytes; 0 if unknown")
    created_at: str = Field(default="", description="ISO-8601 UTC, set when first observed")
    chat_id: str = Field(default="", description="The chat that produced this asset")
    status: AssetStatus = Field(default="needs-review")
    subtitle: str = Field(default="", description="Short LLM- or user-supplied description")
    oss_key: str = Field(default="", description="Permanent OSS object key (no signature)")
    oss_url: str = Field(default="", description="Most recent presigned GET URL — may expire")


class ViewState(BaseModel):
    """Front-end UI state — backend stores it verbatim."""

    model_config = ConfigDict(extra="allow")

    active_chat_id: str = ""
    active_file_tab: int = 0
    active_project_tab: int = 0
    open_files: list[str] = Field(default_factory=list)
    folder_path: str = ""
    folder_history: list[str] = Field(default_factory=lambda: [""])
    folder_history_index: int = 0


class WorkspaceState(BaseModel):
    """The full per-thread workspace document persisted to OSS."""

    model_config = ConfigDict(extra="allow")

    version: int = 1
    task_id: str = Field(description="Stable v2 envelope task_id for this thread")
    assets: dict[str, Asset] = Field(default_factory=dict)
    view_state: ViewState = Field(default_factory=ViewState)
    viewed_files: dict[str, str] = Field(
        default_factory=dict,
        description="filename → ISO-8601 timestamp of the last UI open event",
    )

    def asset_keys(self) -> set[str]:
        return set(self.assets.keys())


def empty_state(task_id: str) -> WorkspaceState:
    """Build a fresh, empty workspace document with the given v2 task_id."""
    return WorkspaceState(task_id=task_id)
