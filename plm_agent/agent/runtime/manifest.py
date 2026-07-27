# -*- coding: utf-8 -*-
"""``FileManifest`` — typed artifact log persisted to ``.memory/manifest.json``.

Each artifact (drafts, outputs, figures, references, attachments) is recorded
once per produce-event with provenance (which phase produced it, which turn,
version, checksum). Read by ``hooks_integration.reconcile_assets`` to upsert
``WorkspaceState`` assets in the OSS workspace state JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from agent.runtime.paths import WorkspacePaths

logger = logging.getLogger(__name__)

_MANIFEST_FILE = "manifest.json"


@dataclass
class ArtifactRecord:
    path: str                       # relative to workspace_dir
    kind: str                       # "draft" | "output" | "figure" | "reference" | "attachment"
    source_phase: Optional[str] = None
    source_turn: int = 0
    version: int = 1
    checksum: str = ""
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class FileManifest:
    """Append-only-ish log of artifacts. Reads/writes a single JSON blob."""

    def __init__(self, paths: WorkspacePaths, sandbox: Any):
        self.paths = paths
        self.sandbox = sandbox

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record(self, rec: ArtifactRecord) -> bool:
        records = await self._load()
        records.append(asdict(rec))
        return await self._save(records)

    async def list(self, kind: Optional[str] = None) -> List[ArtifactRecord]:
        records = await self._load()
        out = [_to_record(r) for r in records]
        if kind is not None:
            out = [r for r in out if r.kind == kind]
        return out

    async def latest(self, kind: str) -> Optional[ArtifactRecord]:
        items = await self.list(kind=kind)
        return items[-1] if items else None

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @property
    def _path(self) -> str:
        return f"{self.paths.memory_dir}/{_MANIFEST_FILE}"

    async def _load(self) -> List[Dict[str, Any]]:
        client = await self._get_client()
        if client is None:
            return []
        try:
            raw = await client.read_file(self._path)
        except Exception as e:  # noqa: BLE001
            logger.warning("[FileManifest] read failed: %s", e)
            return []
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[FileManifest] corrupt manifest at %s; resetting", self._path)
            return []
        if not isinstance(data, list):
            logger.warning("[FileManifest] unexpected shape %r; resetting", type(data))
            return []
        return data

    async def _save(self, records: List[Dict[str, Any]]) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            return bool(await client.write_file(self._path, json.dumps(records, ensure_ascii=False, indent=2)))
        except Exception as e:  # noqa: BLE001
            logger.warning("[FileManifest] write failed: %s", e)
            return False

    async def _get_client(self) -> Any:
        sandbox = self.sandbox
        get_client = getattr(sandbox, "get_client", None)
        if callable(get_client):
            try:
                return await get_client()
            except Exception as e:  # noqa: BLE001
                logger.warning("[FileManifest] get_client failed: %s", e)
                return None
        ensure = getattr(sandbox, "ensure_sandbox", None)
        if ensure is not None:
            try:
                await ensure()
            except Exception as e:  # noqa: BLE001
                logger.warning("[FileManifest] ensure_sandbox failed: %s", e)
                return None
        return getattr(sandbox, "_client", sandbox)


def _to_record(d: Dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        path=str(d.get("path", "")),
        kind=str(d.get("kind", "")),
        source_phase=d.get("source_phase"),
        source_turn=int(d.get("source_turn", 0)),
        version=int(d.get("version", 1)),
        checksum=str(d.get("checksum", "")),
        created_at=float(d.get("created_at", 0.0)),
        metadata=dict(d.get("metadata") or {}),
    )
