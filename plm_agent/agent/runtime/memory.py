# -*- coding: utf-8 -*-
"""``MemoryStore`` — typed access to ``.memory/`` files inside a session sandbox.

Wraps the existing sandbox file API so callers get string-typed read / write /
append without shell-escaping or path concatenation. The sandbox executor's
own writes (``task_plan.md``, ``findings.md``, ``progress.md``) keep working
unchanged — this store is just an additional ergonomic surface.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.runtime.paths import WorkspacePaths

logger = logging.getLogger(__name__)


class MemoryStore:
    """Read/write ``.memory/<name>.md`` (or ``<name>.<ext>``) files."""

    def __init__(self, paths: WorkspacePaths, sandbox: Any):
        self.paths = paths
        self.sandbox = sandbox

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _path(self, name: str) -> str:
        """Resolve ``name`` to a full sandbox path under ``.memory/``.

        ``name`` may be a bare stem (``"task_plan"`` → ``task_plan.md``) or
        already include an extension (``"manifest.json"``).
        """
        if "." in name:
            return f"{self.paths.memory_dir}/{name}"
        return f"{self.paths.memory_dir}/{name}.md"

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    async def read(self, name: str) -> str:
        """Return file contents or '' if missing."""
        client = await self._client()
        if client is None:
            return ""
        try:
            content = await client.read_file(self._path(name))
        except Exception as e:  # noqa: BLE001
            logger.warning("[MemoryStore] read %r failed: %s", name, e)
            return ""
        return content or ""

    async def write(self, name: str, content: str) -> bool:
        client = await self._client()
        if client is None:
            return False
        try:
            return bool(await client.write_file(self._path(name), content))
        except Exception as e:  # noqa: BLE001
            logger.warning("[MemoryStore] write %r failed: %s", name, e)
            return False

    async def append(self, name: str, content: str) -> bool:
        existing = await self.read(name)
        return await self.write(name, existing + content)

    async def list(self) -> List[str]:
        """Return basenames of every file currently under ``.memory/``."""
        client = await self._client()
        if client is None:
            return []
        try:
            entries = await client.list_files(self.paths.memory_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning("[MemoryStore] list failed: %s", e)
            return []
        # Tolerate either bare names or full paths.
        return [e.rsplit("/", 1)[-1] for e in (entries or [])]

    async def snapshot(self) -> Dict[str, str]:
        """Read every file in ``.memory/``; return ``{stem: content}`` dict."""
        names = await self.list()
        out: Dict[str, str] = {}
        for fname in names:
            stem = fname.rsplit(".", 1)[0] if "." in fname else fname
            out[stem] = await self.read(fname)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _client(self) -> Any:
        """Return the underlying file client.

        Prefers ``SandboxManager.get_client`` (the public accessor). Falls back
        to ``ensure_sandbox`` + ``_client`` for older fakes used in tests.
        """
        sandbox = self.sandbox
        get_client = getattr(sandbox, "get_client", None)
        if callable(get_client):
            try:
                return await get_client()
            except Exception as e:  # noqa: BLE001
                logger.warning("[MemoryStore] get_client failed: %s", e)
                return None
        ensure = getattr(sandbox, "ensure_sandbox", None)
        if ensure is not None:
            try:
                await ensure()
            except Exception as e:  # noqa: BLE001
                logger.warning("[MemoryStore] ensure_sandbox failed: %s", e)
                return None
        client = getattr(sandbox, "_client", None)
        return client if client is not None else sandbox
