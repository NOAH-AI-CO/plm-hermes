# -*- coding: utf-8 -*-
"""Unit tests for ``agent.runtime.context.RuntimeContext``."""

from agent.runtime.context import RuntimeContext
from agent.runtime.paths import WorkspacePaths


def _paths():
    return WorkspacePaths(env="dev", user_id="42", session_id="abc-123")


def test_minimum_construction_only_requires_paths():
    ctx = RuntimeContext(paths=_paths())
    assert ctx.paths.session_id == "abc-123"
    assert ctx.log_id == ""
    assert ctx.plan is None
    assert ctx.phase is None
    assert ctx.sandbox_manager is None


def test_set_phase_mutates_context():
    ctx = RuntimeContext(paths=_paths())
    ctx.set_phase("blueprint")
    assert ctx.phase == "blueprint"
    ctx.set_phase("writer")
    assert ctx.phase == "writer"


def test_construction_accepts_optional_fields():
    ctx = RuntimeContext(
        paths=_paths(),
        log_id="trace-1",
        phase="blueprint",
    )
    assert ctx.log_id == "trace-1"
    assert ctx.phase == "blueprint"
