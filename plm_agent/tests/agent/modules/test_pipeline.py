# -*- coding: utf-8 -*-
"""Unit tests for ``ModulePipeline`` (router-LLM era).

We mock ``router.select_tool`` and ``_run_downstream_agent`` so the tests
don't import ``agent.router`` (which transitively pulls GCP creds) or hit
any LLM. The fakes mirror the contract the pipeline depends on.
"""

import asyncio
from typing import AsyncIterator, Optional, Tuple

import pytest
from pydantic import BaseModel

from agent.modules import _state_store, pipeline as module_pipeline, registry
from agent.modules.base import InteractiveModule


class _NopArgs(BaseModel):
    payload: str = "ok"


class FakeModule(InteractiveModule):
    """Configurable module driving specific scenarios in tests.

    Override per-instance via constructor kwargs; class attrs (``name`` / ...)
    are set instance-side so multiple FakeModules can coexist.
    """

    args_model = _NopArgs
    tool_description = "fake tool — only here to satisfy the schema check"

    def __init__(
        self,
        *,
        name: str = "fake",
        script: list[dict] | None = None,
        pause_after_run: bool = True,
        consume_script: list[dict] | None = None,
        finish_after_consume: bool = True,
        enrichment: dict | None = None,
        routable: bool = True,
        reply_types: tuple[str, ...] = ("module_reply",),
    ):
        self.name = name
        self.content_type = name
        self.routable = routable
        self.reply_types = reply_types
        self._script = script or []
        self._pause = pause_after_run
        self._consume_script = consume_script or []
        self._finish_after_consume = finish_after_consume
        self._enrichment = enrichment or {}

    async def run(self, body, state, args) -> AsyncIterator[dict]:
        for frame in self._script:
            yield frame
        if self._pause:
            state["awaiting_user"] = True
        else:
            state["done"] = True

    async def consume_reply(self, body, state) -> AsyncIterator[dict]:
        for frame in self._consume_script:
            yield frame
        if self._finish_after_consume:
            state["done"] = True
            state["awaiting_user"] = False

    def enrich_prompt(self, body, state):
        if not self._enrichment:
            return body
        out = dict(body)
        out.update(self._enrichment)
        return out


class FakeAgent:
    last_init_body: dict | None = None
    last_start_body: dict | None = None

    def __init__(self, **body):
        FakeAgent.last_init_body = dict(body)
        self._body = body

    async def start(self, **body):
        FakeAgent.last_start_body = dict(body)
        yield {"event_v2": {"op": "add", "task_id": "agent-task",
                             "value": {"content": {"type": "text", "text": "ok"}}}}


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_ROUTABLE_ORDER", [])
    monkeypatch.setattr(registry, "_REPLY_TYPE_MAP", {})
    yield


@pytest.fixture(autouse=True)
def _reset_state_cache():
    _state_store._cache.clear()
    yield
    _state_store._cache.clear()


@pytest.fixture
def fake_router(monkeypatch):
    """Replace pipeline._run_downstream_agent so tests don't import agent.router."""
    FakeAgent.last_init_body = None
    FakeAgent.last_start_body = None

    async def fake_dispatch(body):
        agent = FakeAgent(**body)
        async for frame in agent.start(**body):
            yield frame

    monkeypatch.setattr(module_pipeline, "_run_downstream_agent", fake_dispatch)
    yield FakeAgent


def _drain(gen):
    async def _go():
        return [item async for item in gen]
    return asyncio.run(_go())


def _register(module: FakeModule):
    """Inject a FakeModule into the (already-isolated) registry by hand,
    bypassing the class-decorator path which expects unique class types."""
    registry._REGISTRY[module.name] = module
    if module.routable:
        registry._ROUTABLE_ORDER.append(module.name)
    for rt in module.reply_types:
        if rt == "module_reply":
            continue
        registry._REPLY_TYPE_MAP[rt] = module.name


# ----------------------------------------------------------------------
# pipeline.run — router-LLM path
# ----------------------------------------------------------------------


class TestRunRouter:
    def test_no_tool_selected_dispatches_agent(
        self, isolated_registry, fake_router, monkeypatch,
    ):
        _register(FakeModule(name="m1"))

        async def fake_select(body, modules, states):
            return None

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "hi"}
        frames = _drain(module_pipeline.run(body))
        assert len(frames) == 1  # only the FakeAgent frame
        assert FakeAgent.last_start_body["user_prompt"] == "hi"

    def test_tool_selected_runs_module_and_pauses(
        self, isolated_registry, fake_router, monkeypatch,
    ):
        question_frame = {"event_v2": {"op": "add", "task_id": "q1",
                                        "value": {"content": {"type": "fake", "text": "?"}}}}
        _register(FakeModule(name="m1", script=[question_frame], pause_after_run=True))

        async def fake_select(body, modules, states):
            return "m1", _NopArgs(payload="hi")

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "hi"}
        frames = _drain(module_pipeline.run(body))
        assert len(frames) == 1
        assert frames[0] is question_frame
        # Downstream agent NOT invoked
        assert FakeAgent.last_start_body is None

    def test_tool_selected_runs_module_and_continues_to_agent(
        self, isolated_registry, fake_router, monkeypatch,
    ):
        _register(FakeModule(
            name="m1", script=[], pause_after_run=False,
            enrichment={"user_prompt": "enriched!"},
        ))

        async def fake_select(body, modules, states):
            return "m1", _NopArgs()

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "raw"}
        _drain(module_pipeline.run(body))
        assert FakeAgent.last_start_body["user_prompt"] == "enriched!"

    def test_module_run_exception_falls_through(
        self, isolated_registry, fake_router, monkeypatch,
    ):
        boom = FakeModule(name="boom")

        async def boom_run(body, state, args):
            raise RuntimeError("boom")
            yield  # unreachable, makes async gen

        boom.run = boom_run
        _register(boom)

        async def fake_select(body, modules, states):
            return "boom", _NopArgs()

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "hi"}
        _drain(module_pipeline.run(body))
        assert FakeAgent.last_start_body is not None  # downstream agent ran

    def test_router_crash_falls_through(
        self, isolated_registry, fake_router, monkeypatch,
    ):
        _register(FakeModule(name="m1"))

        async def fake_select(body, modules, states):
            raise RuntimeError("router exploded")

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "hi"}
        _drain(module_pipeline.run(body))
        assert FakeAgent.last_start_body is not None


# ----------------------------------------------------------------------
# pipeline.handle_reply
# ----------------------------------------------------------------------


class TestHandleReply:
    def test_module_reply_routed_via_module_field(
        self, isolated_registry, fake_router,
    ):
        ack = {"event_v2": {"op": "replace", "task_id": "q1",
                             "value": {"content": {"type": "fake", "text": "ok"},
                                       "status": "success"}}}
        _register(FakeModule(
            name="ask",
            consume_script=[ack],
            finish_after_consume=True,
            enrichment={"user_prompt": "after-reply"},
        ))
        body = {
            "type": "module_reply",
            "module": "ask",
            "agent": "general_writing",
            "thread_id": "t1",
            "feedback": "yes",
            "approve": True,
            "skip": False,
        }
        frames = _drain(module_pipeline.handle_reply(body))
        assert frames[0] is ack
        assert FakeAgent.last_start_body["user_prompt"] == "after-reply"
        # Reply markers stripped before dispatch
        for k in ("type", "module", "approve", "feedback", "skip"):
            assert k not in FakeAgent.last_start_body

    def test_specific_reply_type_routed_via_map(
        self, isolated_registry, fake_router,
    ):
        ack = {"event_v2": {"op": "replace", "task_id": "evt-1",
                             "value": {"content": {"type": "fake", "text": "ack"}}}}
        _register(FakeModule(
            name="confirm",
            reply_types=("module_reply", "edit"),
            consume_script=[ack],
            finish_after_consume=True,
        ))
        body = {
            "type": "edit",
            "agent": "general_writing",
            "thread_id": "t1",
            "event_id": "evt-1",
            "feedback": "edit-this",
        }
        frames = _drain(module_pipeline.handle_reply(body))
        assert frames[0] is ack
        # Reply markers stripped, including the new event_id
        assert "event_id" not in FakeAgent.last_start_body

    def test_unknown_module_falls_through(
        self, isolated_registry, fake_router,
    ):
        body = {
            "type": "module_reply",
            "module": "does-not-exist",
            "agent": "general_writing",
            "user_prompt": "hi",
        }
        _drain(module_pipeline.handle_reply(body))
        assert FakeAgent.last_start_body["user_prompt"] == "hi"


# ----------------------------------------------------------------------
# dispatch — single entrypoint
# ----------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_run_path(self, isolated_registry, fake_router, monkeypatch):
        async def fake_select(body, modules, states):
            return None

        monkeypatch.setattr("agent.modules.router.select_tool", fake_select)
        body = {"agent": "general_writing", "user_prompt": "hi"}
        _drain(module_pipeline.dispatch(body))
        assert FakeAgent.last_start_body is not None

    def test_dispatch_reply_path(self, isolated_registry, fake_router):
        _register(FakeModule(
            name="ask",
            reply_types=("module_reply",),
            consume_script=[],
            finish_after_consume=True,
        ))
        body = {
            "type": "module_reply",
            "module": "ask",
            "agent": "general_writing",
            "thread_id": "t1",
            "feedback": "x",
            "approve": True,
        }
        _drain(module_pipeline.dispatch(body))
        assert FakeAgent.last_start_body is not None


# ----------------------------------------------------------------------
# stream_json
# ----------------------------------------------------------------------


class TestStreamJson:
    def test_serializes_dicts_with_newline(self):
        async def gen():
            yield {"a": 1}
            yield "raw\n"
            yield 42

        async def run():
            return [chunk async for chunk in module_pipeline.stream_json(gen())]

        chunks = asyncio.run(run())
        assert chunks[0] == '{"a": 1}\n'
        assert chunks[1] == "raw\n"
        assert chunks[2] == "42\n"
