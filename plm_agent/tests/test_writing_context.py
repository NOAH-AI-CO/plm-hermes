# -*- coding: utf-8 -*-
"""Unit tests for ``agent.writing.context.WritingContext``.

These are pure-Python tests — no network, no LLM, no sandbox.
"""

import pytest

from agent.writing.context import WritingContext


class TestWritingContextConstruction:
    def test_minimal_fields(self):
        ctx = WritingContext(
            sandbox_manager=None,
            thread_id="t-1",
            correlation_id="cid-1",
            api_base_url="http://localhost:8013",
        )
        assert ctx.thread_id == "t-1"
        assert ctx.correlation_id == "cid-1"
        assert ctx.api_base_url == "http://localhost:8013"
        assert ctx.sandbox_manager is None

    def test_current_phase_defaults_none(self):
        ctx = WritingContext(
            sandbox_manager=None,
            thread_id="",
            correlation_id="",
            api_base_url="",
        )
        assert ctx.current_phase is None

    def test_current_phase_is_mutable(self):
        ctx = WritingContext(
            sandbox_manager=None,
            thread_id="",
            correlation_id="",
            api_base_url="",
        )
        ctx.current_phase = "planning"
        assert ctx.current_phase == "planning"


class TestRunContextWrapperPassthrough:
    """Confirm the SDK's ``RunContextWrapper`` exposes our context under ``.context``."""

    def test_wrapper_roundtrip(self):
        # Imported locally so pytest collection still works on envs that
        # lack the SDK; the whole writing module requires it in practice.
        RunContextWrapper = pytest.importorskip("agents").RunContextWrapper

        ctx = WritingContext(
            sandbox_manager=None,
            thread_id="thread-42",
            correlation_id="corr-42",
            api_base_url="http://example.test",
        )
        wrapper = RunContextWrapper(context=ctx)
        assert wrapper.context is ctx
        # Mutations flow through the wrapper (hooks rely on this).
        wrapper.context.current_phase = "writing"
        assert ctx.current_phase == "writing"
