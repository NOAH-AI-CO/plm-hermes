# -*- coding: utf-8 -*-
"""Unit tests for the workspace module (store / module / frames / hooks_integration).

OSS and the sandbox manager are mocked end-to-end so these tests are pure unit
tests — they never touch the network. The store is reset between tests so each
test starts from a clean singleton.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.workspace import frames as workspace_frames
from agent.workspace import hooks_integration
from agent.workspace.module import WorkspaceModule
from agent.workspace.schemas import Asset, ViewState, WorkspaceState, empty_state
from agent.workspace.store import _reset_for_tests, get_store


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    """Per-test cleanup + universal bucket-name stub.

    The bucket name comes from ``api_config.ALIYUN_OSS_BUCKET``; test envs
    don't carry that key, so we patch the property globally.
    """
    from agent.workspace import store as _store_module
    monkeypatch.setattr(
        _store_module.WorkspaceStore, "_bucket",
        property(lambda self: "test-bucket"),
    )
    _reset_for_tests()
    yield
    _reset_for_tests()


@pytest.fixture
def fake_oss(monkeypatch):
    """In-memory replacement for the OSS get/put helpers used by the store."""
    blobs: dict[tuple[str, str], str] = {}

    def fake_put(bucket, key, content, content_type="application/json"):
        blobs[(bucket, key)] = content

    def fake_get(bucket, key):
        return blobs.get((bucket, key))

    def fake_presign(bucket, key):
        return f"https://signed.example.com/{bucket}/{key}?Signature=abc"

    monkeypatch.setattr("agent.workspace.store.put_object_text", fake_put)
    monkeypatch.setattr("agent.workspace.store.get_object_text", fake_get)
    monkeypatch.setattr("agent.workspace.store.presign_get", fake_presign)
    return blobs


def _drain(gen):
    async def _go():
        return [item async for item in gen]
    return asyncio.run(_go())


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class TestSchemas:
    def test_asset_round_trip(self):
        a = Asset(name="x", filename="x.html", ext="html", oss_key="k", oss_url="u")
        d = a.model_dump(mode="json")
        assert Asset.model_validate(d) == a

    def test_view_state_defaults(self):
        v = ViewState()
        assert v.open_files == []
        assert v.folder_history == [""]
        assert v.active_file_tab == 0

    def test_empty_state_uses_given_task_id(self):
        s = empty_state("task-1")
        assert s.task_id == "task-1"
        assert s.assets == {}
        assert s.viewed_files == {}


# ----------------------------------------------------------------------
# Frames (envelope construction)
# ----------------------------------------------------------------------


class TestFrames:
    def _state(self):
        return WorkspaceState(task_id="task-1")

    def test_full_snapshot_uses_op_add(self):
        s = self._state()
        s.assets["foo"] = Asset(name="foo", filename="foo.html", oss_key="k", oss_url="u")
        env = workspace_frames.build_full_snapshot_frame(s, "thr-1")["event_v2"]
        assert env["op"] == "add"
        # Wire ``task_id`` is the parent context (thread_id for workspace);
        # ``msg_id`` is the per-MessageItem merge key (still kept on
        # WorkspaceState.task_id internally for backward compat).
        assert env["task_id"] == "thr-1"
        assert env["msg_id"] == "task-1"
        assert env["value"]["content"] == {"type": "workspace", "text": ""}
        assert "foo" in env["value"]["meta_data"]["assets"]

    def test_asset_upsert_patch_path(self):
        s = self._state()
        a = Asset(name="foo", filename="foo.html", oss_key="k")
        env = workspace_frames.build_asset_upsert_frame(s, a)["event_v2"]
        assert env["op"] == "patch"
        assert env["patches"][0]["path"] == "/meta_data/assets/foo"

    def test_file_opened_double_patch(self):
        s = self._state()
        env = workspace_frames.build_file_opened_frame(s, "foo.html", "2026-01-01T00:00:00Z")["event_v2"]
        ops = [(p["op"], p["path"]) for p in env["patches"]]
        assert ("add", "/meta_data/view_state/open_files/-") in ops
        assert ("add", "/meta_data/viewed_files/foo.html") in ops

    def test_path_segment_escapes_slash_and_tilde(self):
        s = self._state()
        a = Asset(name="a/b~c", filename="a-b-c.html", oss_key="k")
        env = workspace_frames.build_asset_upsert_frame(s, a)["event_v2"]
        assert env["patches"][0]["path"] == "/meta_data/assets/a~1b~0c"


# ----------------------------------------------------------------------
# Store — load / persist / mutate
# ----------------------------------------------------------------------


class TestStoreLoad:
    def test_first_load_creates_and_persists(self, fake_oss):
        store = get_store()
        s = asyncio.run(store.load("thr-1"))
        assert s.task_id  # uuid was minted
        # The empty state was persisted so a second load returns the same task_id.
        assert any("workspace/thr-1/state.json" in k[1] for k in fake_oss.keys())
        s2 = asyncio.run(store.load("thr-1"))
        assert s2.task_id == s.task_id

    def test_load_returns_existing_oss_state(self, monkeypatch):
        existing = {
            "version": 1,
            "task_id": "from-oss",
            "assets": {"x": {"name": "x", "filename": "x.html", "oss_key": "k"}},
            "view_state": {},
            "viewed_files": {},
        }
        monkeypatch.setattr("agent.workspace.store.get_object_text",
                            lambda *_a, **_k: json.dumps(existing))
        monkeypatch.setattr("agent.workspace.store.put_object_text",
                            lambda *_a, **_k: None)
        store = get_store()
        s = asyncio.run(store.load("thr-2"))
        assert s.task_id == "from-oss"
        assert "x" in s.assets

    def test_load_handles_corrupt_oss_object(self, monkeypatch):
        monkeypatch.setattr("agent.workspace.store.get_object_text",
                            lambda *_a, **_k: "not-json")
        monkeypatch.setattr("agent.workspace.store.put_object_text",
                            lambda *_a, **_k: None)
        store = get_store()
        s = asyncio.run(store.load("thr-3"))
        # Falls back to a fresh document instead of crashing.
        assert s.assets == {}


class TestStoreMutators:
    def test_upsert_asset_returns_patch_frame_and_persists(self, fake_oss):
        store = get_store()
        frame = asyncio.run(store.upsert_asset(
            "thr-1", filename="Noah AI Logo.html",
            oss_key="workspace/thr-1/assets/Noah AI Logo.html",
            oss_url="https://signed/...",
            chat_id="c-1",
        ))
        assert frame is not None
        env = frame["event_v2"]
        assert env["op"] == "patch"
        assert env["patches"][0]["path"] == "/meta_data/assets/Noah AI Logo"
        # The stem (without extension) is the map key.
        s = asyncio.run(store.load("thr-1"))
        assert "Noah AI Logo" in s.assets
        assert s.assets["Noah AI Logo"].chat_id == "c-1"
        assert s.assets["Noah AI Logo"].ext == "html"

    def test_upsert_asset_idempotent_returns_none(self, fake_oss):
        store = get_store()
        kwargs = dict(filename="x.html", oss_key="k", oss_url="u", chat_id="c")
        first = asyncio.run(store.upsert_asset("thr-1", **kwargs))
        second = asyncio.run(store.upsert_asset("thr-1", **kwargs))
        assert first is not None
        assert second is None  # nothing changed

    def test_upsert_preserves_status_on_repeat(self, fake_oss):
        store = get_store()
        asyncio.run(store.upsert_asset("thr-1", filename="x.html", oss_key="k1"))
        asyncio.run(store.set_asset_status("thr-1", name="x", status="reviewed"))
        # A later upsert (e.g. from a re-run) must not reset the status.
        asyncio.run(store.upsert_asset("thr-1", filename="x.html", oss_key="k1",
                                        oss_url="new-url"))
        s = asyncio.run(store.load("thr-1"))
        assert s.assets["x"].status == "reviewed"

    def test_set_asset_status_returns_replace_patch(self, fake_oss):
        store = get_store()
        asyncio.run(store.upsert_asset("thr-1", filename="x.html", oss_key="k"))
        frame = asyncio.run(store.set_asset_status("thr-1", name="x", status="reviewed"))
        assert frame is not None
        p = frame["event_v2"]["patches"][0]
        assert p["op"] == "replace"
        assert p["path"] == "/meta_data/assets/x/status"
        assert p["value"] == "reviewed"

    def test_set_asset_status_unknown_returns_none(self, fake_oss):
        store = get_store()
        frame = asyncio.run(store.set_asset_status("thr-1", name="missing", status="reviewed"))
        assert frame is None

    def test_apply_view_patch_merges_and_emits(self, fake_oss):
        store = get_store()
        frame = asyncio.run(store.apply_view_patch("thr-1", {"active_file_tab": 2}))
        assert frame is not None
        s = asyncio.run(store.load("thr-1"))
        assert s.view_state.active_file_tab == 2

    def test_record_open_appends_and_timestamps(self, fake_oss):
        store = get_store()
        frame = asyncio.run(store.record_open("thr-1", filename="a.html"))
        assert frame is not None
        s = asyncio.run(store.load("thr-1"))
        assert s.view_state.open_files == ["a.html"]
        assert "a.html" in s.viewed_files

    def test_record_open_does_not_duplicate(self, fake_oss):
        store = get_store()
        asyncio.run(store.record_open("thr-1", filename="a.html"))
        asyncio.run(store.record_open("thr-1", filename="a.html"))
        s = asyncio.run(store.load("thr-1"))
        assert s.view_state.open_files.count("a.html") == 1

    def test_record_close_removes(self, fake_oss):
        store = get_store()
        asyncio.run(store.record_open("thr-1", filename="a.html"))
        asyncio.run(store.record_close("thr-1", filename="a.html"))
        s = asyncio.run(store.load("thr-1"))
        assert s.view_state.open_files == []

    def test_set_active_tab(self, fake_oss):
        store = get_store()
        frame = asyncio.run(store.set_active_tab("thr-1", index=3))
        assert frame is not None
        s = asyncio.run(store.load("thr-1"))
        assert s.view_state.active_file_tab == 3

    def test_set_active_tab_noop(self, fake_oss):
        store = get_store()
        # default active_file_tab is 0
        frame = asyncio.run(store.set_active_tab("thr-1", index=0))
        assert frame is None

    def test_refresh_asset_url_repsigns(self, fake_oss):
        store = get_store()
        asyncio.run(store.upsert_asset(
            "thr-1", filename="x.html", oss_key="workspace/thr-1/assets/x.html",
            oss_url="https://old/",
        ))
        url = asyncio.run(store.refresh_asset_url("thr-1", "x"))
        assert url is not None and "signed.example.com" in url
        s = asyncio.run(store.load("thr-1"))
        assert s.assets["x"].oss_url == url


# ----------------------------------------------------------------------
# WorkspaceModule reply routing
# ----------------------------------------------------------------------


class TestWorkspaceModuleReplies:
    def test_view_state_update_dispatches(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "view_state_update", "thread_id": "thr-1",
                "patch": {"active_file_tab": 5}}
        frames_out = _drain(m.consume_reply(body, {}))
        assert len(frames_out) == 1
        assert frames_out[0]["event_v2"]["op"] == "patch"

    def test_file_opened_dispatches(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "file_opened", "thread_id": "thr-1", "file": "a.html"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert len(frames_out) == 1

    def test_file_closed_silent_when_not_open(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "file_closed", "thread_id": "thr-1", "file": "ghost.html"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert frames_out == []

    def test_tab_activated_requires_int(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "tab_activated", "thread_id": "thr-1", "index": "not-int"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert frames_out == []

    def test_asset_status_update(self, fake_oss):
        store = get_store()
        asyncio.run(store.upsert_asset("thr-1", filename="x.html", oss_key="k"))
        m = WorkspaceModule()
        body = {"type": "asset_status_update", "thread_id": "thr-1",
                "asset": "x", "status": "reviewed"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert len(frames_out) == 1

    def test_missing_thread_id_silent(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "file_opened", "file": "a.html"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert frames_out == []

    def test_unknown_type_silent(self, fake_oss):
        m = WorkspaceModule()
        body = {"type": "made_up", "thread_id": "thr-1"}
        frames_out = _drain(m.consume_reply(body, {}))
        assert frames_out == []


# ----------------------------------------------------------------------
# hooks_integration.reconcile_assets
# ----------------------------------------------------------------------


class TestReconcileAssets:
    def _fake_sandbox(self, *, list_files_returns, upload_returns):
        client = SimpleNamespace(list_files=AsyncMock(return_value=list_files_returns))
        sm = SimpleNamespace(
            _client=client,
            workspace="/mnt/workspace/sessions/thr-1/workspace",
            upload_artifacts=AsyncMock(return_value=upload_returns),
        )
        return sm

    def test_no_new_files_returns_empty_frames(self, fake_oss):
        sm = self._fake_sandbox(
            list_files_returns=["a.html"], upload_returns=[],
        )
        # Pretend baseline already saw a.html.
        before = {"outputs/a.html"}
        frames_out, after = asyncio.run(hooks_integration.reconcile_assets(
            sandbox_manager=sm, thread_id="thr-1", chat_id="c", before_snapshot=before,
        ))
        assert frames_out == []
        assert "outputs/a.html" in after

    def test_new_file_triggers_upsert(self, fake_oss):
        sm = self._fake_sandbox(
            list_files_returns=["a.html", "b.html"],
            upload_returns=[
                {"filename": "b.html", "oss_url": "https://oss/b",
                 "oss_key": "workspace/thr-1/assets/b.html"},
            ],
        )
        before = {"outputs/a.html"}
        frames_out, after = asyncio.run(hooks_integration.reconcile_assets(
            sandbox_manager=sm, thread_id="thr-1", chat_id="c-9", before_snapshot=before,
        ))
        assert len(frames_out) == 1
        assert frames_out[0]["event_v2"]["op"] == "patch"
        # The store now has an asset entry.
        s = asyncio.run(get_store().load("thr-1"))
        assert "b" in s.assets
        assert s.assets["b"].chat_id == "c-9"

    def test_no_sandbox_is_noop(self, fake_oss):
        frames_out, after = asyncio.run(hooks_integration.reconcile_assets(
            sandbox_manager=None, thread_id="thr-1", chat_id="c",
        ))
        assert frames_out == []
        assert after == set()

    def test_no_thread_id_is_noop(self, fake_oss):
        sm = self._fake_sandbox(list_files_returns=["x"], upload_returns=[])
        frames_out, after = asyncio.run(hooks_integration.reconcile_assets(
            sandbox_manager=sm, thread_id="", chat_id="c",
        ))
        assert frames_out == []

    def test_handles_dict_entries(self, fake_oss):
        # SDK sometimes returns dicts instead of strings for list_files.
        sm = self._fake_sandbox(
            list_files_returns=[{"name": "c.html"}],
            upload_returns=[{"filename": "c.html", "oss_url": "https://oss/c"}],
        )
        frames_out, after = asyncio.run(hooks_integration.reconcile_assets(
            sandbox_manager=sm, thread_id="thr-1", chat_id="", before_snapshot=set(),
        ))
        assert len(frames_out) == 1
        assert "outputs/c.html" in after or "figures/c.html" in after
