# -*- coding: utf-8 -*-
"""Integration tests for ``WritingAgent.start`` skill-routing wiring.

These tests pin the contract between ``WritingAgent.start`` and
``agent.runtime.{router,builder}`` without exercising any real LLM:

- ``select_skills_via_llm`` → fake plan
- ``build_default_model`` → ``None``
- ``SandboxManager`` → no-op
- ``Runner.run_streamed`` → captures the manager Agent and yields no events

We then inspect the captured manager's ``tools`` / ``handoffs`` /
``instructions`` to assert the router's plan flowed through correctly.
"""

from __future__ import annotations

import asyncio

import pytest


_BASE_TOOL_NAMES = {
    "run_in_sandbox",
    "project_search",
    "literature_pool",
    "pubmed_search",
    "attachment_download",
}


@pytest.fixture(autouse=True)
def _ensure_writing_skills_registered():
    """Repopulate the registry per-test.

    The capability registry is a singleton; ``tests/agent/runtime/test_router.py``
    has an autouse fixture that ``reg.reset()`` between tests to keep its own
    registrations isolated. When pytest collects both suites together, that
    reset runs after our skills were imported, leaving the registry empty for
    these tests. Calling ``_register_writing_skills`` is idempotent, so we
    just re-run it here to guarantee the skills are present.
    """
    from agent.writing import _register_writing_skills
    _register_writing_skills()
    yield


def _tool_names(tools):
    out = set()
    for t in tools:
        n = getattr(t, "name", None)
        if n is None and isinstance(t, dict):
            n = t.get("name") or t.get("tool_name")
        if n:
            out.add(n)
    return out


class _FakeSandbox:
    def __init__(self, *args, **kwargs):
        self.session_id = kwargs.get("session_id") or "fake"
        self.workspace_paths = kwargs.get("workspace_paths")

    async def ensure_sandbox(self):
        return None

    async def close(self):
        return None

    def list_files(self, *a, **kw):
        return []

    def get_session_id(self):
        return self.session_id


class _FakeStreamResult:
    """Stands in for the SDK's RunResultStreaming — no events."""

    async def stream_events(self):
        if False:  # pragma: no cover - keeps this an async generator
            yield


async def _run_agent_capture(monkeypatch, fake_select, *, user_prompt: str, thread_id: str):
    """Exercise WritingAgent.start with all heavy deps stubbed; return manager."""
    captured: dict = {}

    def fake_build_model():
        return None

    def fake_install_tracing():
        return None

    def fake_run_streamed(manager, **kwargs):
        captured["manager"] = manager
        captured["runner_kwargs"] = kwargs
        return _FakeStreamResult()

    monkeypatch.setattr(
        "agent.writing.router_llm.select_skills_via_llm", fake_select,
    )
    monkeypatch.setattr(
        "agent.writing.agent.build_default_model", fake_build_model,
    )
    monkeypatch.setattr(
        "tools.sandbox.sandbox_manager.SandboxManager", _FakeSandbox,
    )
    monkeypatch.setattr(
        "agent.writing.tracing_processor.install_local_tracing_processor",
        fake_install_tracing,
    )
    import agents
    monkeypatch.setattr(
        agents.Runner, "run_streamed", staticmethod(fake_run_streamed),
    )

    from agent.writing.agent import WritingAgent
    agent = WritingAgent()
    async for _ in agent.start(user_prompt=user_prompt, thread_id=thread_id):
        pass
    return captured["manager"]


def test_minimal_plan_yields_only_base_tools(monkeypatch):
    """Greeting → router picks 'search' (PROMPT_SKILL) → no specialists wired."""

    async def fake_select(*, model, prompt):
        return '{"skills": ["search"], "reasoning": "trivial chat"}'

    manager = asyncio.run(_run_agent_capture(
        monkeypatch, fake_select,
        user_prompt="你好啊", thread_id="t-route-min",
    ))

    names = _tool_names(manager.tools)
    assert _BASE_TOOL_NAMES.issubset(names), f"missing base tools; got {names}"
    specialist_tool_names = {
        "plan_writing", "write_section", "survey_landscape", "analyse_paper",
    }
    assert not (specialist_tool_names & names), (
        f"unexpected specialists with minimal plan: {specialist_tool_names & names}"
    )
    assert manager.handoffs == [], "no handoff expected when citation not in plan"


def test_full_plan_wires_specialists_and_handoff(monkeypatch):
    """Research request → router picks all 7 → manager has all 4 specialists + citation handoff."""

    async def fake_select(*, model, prompt):
        return (
            '{"skills": ["attachment", "search", "blueprint", "writing", '
            '"landscape-analysis", "literature-analysis", "citation"], '
            '"reasoning": "deep work"}'
        )

    manager = asyncio.run(_run_agent_capture(
        monkeypatch, fake_select,
        user_prompt="帮我写一篇 CAR-T 实体瘤综述",
        thread_id="t-route-full",
    ))

    names = _tool_names(manager.tools)
    assert {"plan_writing", "write_section", "survey_landscape", "analyse_paper"}.issubset(names)
    assert len(manager.handoffs) == 1, "citation = handoff, expected exactly one"


def test_router_failure_falls_back_to_full_plan(monkeypatch):
    """LLM error → PreRunRouter returns fallback_plan (= full skill set)."""

    async def fake_select(*, model, prompt):
        raise RuntimeError("simulated LLM outage")

    manager = asyncio.run(_run_agent_capture(
        monkeypatch, fake_select,
        user_prompt="anything",
        thread_id="t-route-fallback",
    ))

    names = _tool_names(manager.tools)
    assert {"plan_writing", "write_section", "survey_landscape", "analyse_paper"}.issubset(names), (
        f"expected full specialist set on fallback; got {names}"
    )
    assert len(manager.handoffs) == 1, "citation handoff must be present in fallback"
