# -*- coding: utf-8 -*-
"""Unit tests for the plan-card emission in ``WritingRunHooks._emit_plan``."""

import asyncio
import time
from types import SimpleNamespace

import pytest


def _drain_queue(queue):
    out = []
    while True:
        try:
            out.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return out


@pytest.fixture
def hooks():
    """Construct a fresh ``WritingRunHooks`` with an isolated queue."""
    from agent.writing.hooks import WritingRunHooks

    queue: asyncio.Queue = asyncio.Queue()
    h = WritingRunHooks(
        queue=queue,
        agent_label="general_writing",
        thread_id="th-1",
        sandbox_manager=None,
        chat_id="chat-1",
        task_id="task-1",
    )
    # Seed a plan_update so _v2_plan_tasks has something to render.
    h.plan_updates.append({
        "id": "step_1",
        "reason": "调用工具: plan_writing",
        "startedAt": int(time.time()),
        "status": "doing",
        "tool": "plan_writing",
    })
    h.step = 1
    return h


def _run_emit(hooks_obj, context=None, save=False):
    asyncio.run(hooks_obj._emit_plan(save=save, context=context))
    return _drain_queue(hooks_obj.queue)


def _make_context(phase: str):
    """Mimic ``RunContextWrapper(context=WritingContext)``."""
    inner = SimpleNamespace(current_phase=phase)
    return SimpleNamespace(context=inner)


class TestPlanCardEmission:
    def test_emits_card_content_type(self, hooks):
        frames = _run_emit(hooks)
        assert len(frames) == 1
        env = frames[0]["event_v2"]
        v = env["value"]
        assert v["content"]["type"] == "executeCard"
        assert env["op"] == "add"

    def test_card_meta_data_shape(self, hooks):
        frames = _run_emit(hooks)
        v = frames[0]["event_v2"]["value"]
        md = v["meta_data"]
        # Standard six card fields populated.
        assert md["title"] == "Noah 准备执行的研究计划"
        assert md["frame_type"] == "ver"
        assert md["priority"] == "p0"
        assert md["open"] is True
        # steps[] derived from plan_updates.
        assert isinstance(md["steps"], list)
        assert md["steps"], "expected at least one step"
        step = md["steps"][0]
        # Step schema: id / index / title / status / summary.
        assert set(step.keys()) == {"id", "index", "title", "status", "summary"}
        # Legacy ``tasks`` list preserved under meta_data for Backend chat-formatter.
        assert "tasks" in md

    def test_actions_empty_for_plan_card(self, hooks):
        """Plan card has no user-facing action buttons (read-only progress)."""
        frames = _run_emit(hooks)
        assert frames[0]["event_v2"]["value"]["actions"] == []

    def test_op_replace_on_second_emit(self, hooks):
        _run_emit(hooks)  # first → op=add
        frames = _run_emit(hooks)
        assert frames[0]["event_v2"]["op"] == "replace"

    def test_task_status_outline_in_planning_phase(self, hooks):
        from agent.writing.context import PHASE_PLANNING
        ctx = _make_context(PHASE_PLANNING)
        frames = _run_emit(hooks, context=ctx)
        assert frames[0]["event_v2"]["task_status"] == "outline"

    def test_task_status_running_outside_planning(self, hooks):
        from agent.writing.context import PHASE_WRITING
        ctx = _make_context(PHASE_WRITING)
        frames = _run_emit(hooks, context=ctx)
        assert frames[0]["event_v2"]["task_status"] == "running"

    def test_task_status_running_when_no_context(self, hooks):
        """No phase info → fall back to current_task_status (running)."""
        frames = _run_emit(hooks, context=None)
        assert frames[0]["event_v2"]["task_status"] == "running"

    def test_save_flag_promotes_status_to_success(self, hooks):
        frames = _run_emit(hooks, save=True)
        v = frames[0]["event_v2"]["value"]
        assert v["status"] == "success"
        assert v["end_time"] is not None


class TestEmitCardHelper:
    """Spot-check the generic _emit_card helper used by future card emitters."""

    def test_emit_card_minimal(self, hooks):
        from agent.modules._v2_envelope import TASK_STATUS_FEEDBACK, make_action

        async def go():
            return await hooks._emit_card(
                title="Hello",
                desc="World",
                actions=[make_action(0, "confirm", "OK", type_="primary")],
                task_status=TASK_STATUS_FEEDBACK,
            )

        msg_id = asyncio.run(go())
        frames = _drain_queue(hooks.queue)
        assert msg_id
        env = frames[0]["event_v2"]
        assert env["op"] == "add"
        assert env["task_status"] == "feedback"
        v = env["value"]
        assert v["content"]["type"] == "executeCard"
        assert v["meta_data"]["title"] == "Hello"
        assert v["meta_data"]["desc"] == "World"
        assert v["actions"][0]["model"] == "confirm"
