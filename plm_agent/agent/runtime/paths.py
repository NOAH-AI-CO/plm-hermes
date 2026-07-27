# -*- coding: utf-8 -*-
"""``WorkspacePaths`` — single source of truth for sandbox + OSS path layout.

Pure data; no FS / OSS calls. Constructed once per request from
``(env, user_id, session_id)`` and passed around via ``RuntimeContext`` so
every component (sandbox client, workspace store, hooks) builds paths the
same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_ROOT = "/mnt/workspace"
_OSS_PREFIX = "workspace"

_ENV_WHITELIST = frozenset({"dev", "test", "staging", "prod"})
_USER_ID_RE = re.compile(r"^\d+$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9\-]+$")


@dataclass(frozen=True)
class WorkspacePaths:
    env: Optional[str]
    user_id: Optional[str]
    session_id: str

    def __post_init__(self) -> None:
        if self.env is not None and self.env not in _ENV_WHITELIST:
            raise ValueError(
                f"WorkspacePaths.env must be in {sorted(_ENV_WHITELIST)}; got {self.env!r}"
            )
        if self.user_id is not None and not _USER_ID_RE.match(self.user_id):
            raise ValueError(
                f"WorkspacePaths.user_id must be a digit string; got {self.user_id!r}"
            )
        if not self.session_id or not _SESSION_ID_RE.match(self.session_id):
            raise ValueError(
                f"WorkspacePaths.session_id must match {_SESSION_ID_RE.pattern}; got {self.session_id!r}"
            )

    @property
    def is_legacy(self) -> bool:
        """True when env or user_id is missing → legacy single-tenant layout."""
        return self.env is None or self.user_id is None

    @property
    def base_dir(self) -> str:
        if self.is_legacy:
            return f"{_ROOT}/sessions/{self.session_id}"
        return f"{_ROOT}/{self.env}/users/{self.user_id}/sessions/{self.session_id}"

    @property
    def workspace_dir(self) -> str:
        return f"{self.base_dir}/workspace"

    @property
    def memory_dir(self) -> str:
        return f"{self.base_dir}/.memory"

    @property
    def module_state_dir(self) -> str:
        return f"{self.base_dir}/.modules"

    @property
    def skills_link(self) -> str:
        """Global skills directory — shared across all sessions and users."""
        return f"{_ROOT}/skills"

    @property
    def oss_workspace_prefix(self) -> str:
        """OSS key prefix for workspace state JSON + assets — mirrors sandbox layout."""
        if self.is_legacy:
            return f"{_OSS_PREFIX}/{self.session_id}"
        return f"{_OSS_PREFIX}/{self.env}/users/{self.user_id}/sessions/{self.session_id}"

    @classmethod
    def legacy(cls, session_id: str) -> "WorkspacePaths":
        """Construct a legacy-mode paths object (used by non-writing agents)."""
        return cls(env=None, user_id=None, session_id=session_id)
