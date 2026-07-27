# -*- coding: utf-8 -*-
"""Unit tests for ``MemoryStore``, ``FileManifest``, and handoff filter helpers."""

import asyncio
import json
from dataclasses import dataclass
from typing import Tuple

import pytest

from agent.runtime.handoff_filters import (
    inject_messages,
    keep_recent_assistant_text,
    keep_user_request_only,
)
from agent.runtime.manifest import ArtifactRecord, FileManifest
from agent.runtime.memory import MemoryStore
from agent.runtime.paths import WorkspacePaths


# ---------------------------------------------------------------------------
# Fake sandbox/client for I/O tests
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self):
        self.files: dict = {}

    async def read_file(self, path):
        return self.files.get(path)

    async def write_file(self, path, content):
        self.files[path] = content
        return True

    async def list_files(self, path):
        prefix = path.rstrip("/") + "/"
        return [k for k in self.files if k.startswith(prefix)]


class _FakeSandbox:
    """Mimics ``SandboxManager`` enough for MemoryStore/FileManifest."""

    def __init__(self):
        self._client = _FakeClient()
        self.ensure_called = 0

    async def ensure_sandbox(self):
        self.ensure_called += 1


def _paths():
    return WorkspacePaths(env="dev", user_id="42", session_id="abc-123")


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------


def test_memory_write_and_read_roundtrip():
    sandbox = _FakeSandbox()
    store = MemoryStore(_paths(), sandbox)
    asyncio.run(store.write("task_plan", "step 1\nstep 2"))
    assert asyncio.run(store.read("task_plan")) == "step 1\nstep 2"
    expected_path = "/mnt/workspace/dev/users/42/sessions/abc-123/.memory/task_plan.md"
    assert expected_path in sandbox._client.files


def test_memory_read_missing_returns_empty_string():
    store = MemoryStore(_paths(), _FakeSandbox())
    assert asyncio.run(store.read("never_written")) == ""


def test_memory_explicit_extension_passes_through():
    sandbox = _FakeSandbox()
    store = MemoryStore(_paths(), sandbox)
    asyncio.run(store.write("manifest.json", "[]"))
    expected_path = "/mnt/workspace/dev/users/42/sessions/abc-123/.memory/manifest.json"
    assert expected_path in sandbox._client.files


def test_memory_append_adds_to_existing():
    store = MemoryStore(_paths(), _FakeSandbox())
    asyncio.run(store.write("findings", "line 1\n"))
    asyncio.run(store.append("findings", "line 2\n"))
    assert asyncio.run(store.read("findings")) == "line 1\nline 2\n"


def test_memory_list_returns_basenames():
    sandbox = _FakeSandbox()
    store = MemoryStore(_paths(), sandbox)
    asyncio.run(store.write("task_plan", "x"))
    asyncio.run(store.write("findings", "y"))
    asyncio.run(store.write("manifest.json", "[]"))
    names = asyncio.run(store.list())
    assert set(names) == {"task_plan.md", "findings.md", "manifest.json"}


def test_memory_snapshot_returns_dict_keyed_by_stem():
    sandbox = _FakeSandbox()
    store = MemoryStore(_paths(), sandbox)
    asyncio.run(store.write("task_plan", "plan"))
    asyncio.run(store.write("findings", "find"))
    snap = asyncio.run(store.snapshot())
    assert snap == {"task_plan": "plan", "findings": "find"}


def test_memory_calls_ensure_sandbox_at_least_once():
    sandbox = _FakeSandbox()
    store = MemoryStore(_paths(), sandbox)
    asyncio.run(store.write("task_plan", "x"))
    assert sandbox.ensure_called >= 1


# ---------------------------------------------------------------------------
# FileManifest
# ---------------------------------------------------------------------------


def test_manifest_record_and_list_roundtrip():
    sandbox = _FakeSandbox()
    manifest = FileManifest(_paths(), sandbox)
    rec = ArtifactRecord(
        path="drafts/draft_v1.md",
        kind="draft",
        source_phase="writer",
        source_turn=3,
        version=1,
        checksum="deadbeef",
        created_at=1.0,
    )
    asyncio.run(manifest.record(rec))
    items = asyncio.run(manifest.list())
    assert len(items) == 1
    assert items[0].path == "drafts/draft_v1.md"
    assert items[0].source_phase == "writer"


def test_manifest_filter_by_kind():
    manifest = FileManifest(_paths(), _FakeSandbox())
    asyncio.run(manifest.record(ArtifactRecord(path="a", kind="draft")))
    asyncio.run(manifest.record(ArtifactRecord(path="b", kind="output")))
    asyncio.run(manifest.record(ArtifactRecord(path="c", kind="draft")))
    drafts = asyncio.run(manifest.list(kind="draft"))
    assert [r.path for r in drafts] == ["a", "c"]


def test_manifest_latest_returns_most_recent():
    manifest = FileManifest(_paths(), _FakeSandbox())
    asyncio.run(manifest.record(ArtifactRecord(path="a", kind="draft", version=1)))
    asyncio.run(manifest.record(ArtifactRecord(path="b", kind="draft", version=2)))
    latest = asyncio.run(manifest.latest("draft"))
    assert latest is not None
    assert latest.path == "b"
    assert latest.version == 2


def test_manifest_latest_for_unknown_kind_is_none():
    manifest = FileManifest(_paths(), _FakeSandbox())
    assert asyncio.run(manifest.latest("nothing")) is None


def test_manifest_persists_as_json_at_expected_path():
    sandbox = _FakeSandbox()
    manifest = FileManifest(_paths(), sandbox)
    asyncio.run(manifest.record(ArtifactRecord(path="x", kind="draft")))
    expected = "/mnt/workspace/dev/users/42/sessions/abc-123/.memory/manifest.json"
    assert expected in sandbox._client.files
    parsed = json.loads(sandbox._client.files[expected])
    assert isinstance(parsed, list)
    assert parsed[0]["path"] == "x"


def test_manifest_recovers_from_corrupt_json():
    sandbox = _FakeSandbox()
    sandbox._client.files[
        "/mnt/workspace/dev/users/42/sessions/abc-123/.memory/manifest.json"
    ] = "not json"
    manifest = FileManifest(_paths(), sandbox)
    # list() should silently treat as empty
    assert asyncio.run(manifest.list()) == []
    # subsequent record() succeeds
    asyncio.run(manifest.record(ArtifactRecord(path="x", kind="draft")))
    assert len(asyncio.run(manifest.list())) == 1


# ---------------------------------------------------------------------------
# handoff_filters
# ---------------------------------------------------------------------------


@dataclass
class _FakeHandoffData:
    input_history: Tuple
    pre_handoff_items: Tuple
    new_items: Tuple


def _data(history):
    return _FakeHandoffData(
        input_history=tuple(history),
        pre_handoff_items=({"role": "tool", "content": "pre"},),
        new_items=({"role": "assistant", "content": "new"},),
    )


def test_keep_user_request_only_strips_assistant_and_tool():
    data = _data([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "more"},
        {"role": "tool", "content": "noise"},
    ])
    out = keep_user_request_only(data)
    assert all(m["role"] == "user" for m in out.input_history)
    assert len(out.input_history) == 2
    assert out.pre_handoff_items == ()
    assert out.new_items == ()


def test_keep_recent_assistant_text_keeps_first_user_and_last_k_assistants():
    data = _data([
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "assistant", "content": "a3"},
    ])
    out = keep_recent_assistant_text(2)(data)
    roles = [m["role"] for m in out.input_history]
    contents = [m["content"] for m in out.input_history]
    assert roles == ["user", "assistant", "assistant"]
    assert contents == ["u1", "a2", "a3"]


def test_inject_messages_prepends_fixed_messages_and_keeps_user_only():
    fixed = [
        {"role": "system", "content": "memory snapshot"},
        {"role": "system", "content": "previous findings"},
    ]
    f = inject_messages(fixed)
    out = f(_data([
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]))
    contents = [m["content"] for m in out.input_history]
    assert contents == ["memory snapshot", "previous findings", "u1", "u2"]
