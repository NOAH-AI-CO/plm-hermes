# -*- coding: utf-8 -*-
"""Unit tests for ``agent.writing.hooks.WritingRunHooks``.

Covers the translation from SDK lifecycle callbacks into SSE-shaped dicts
pushed onto an ``asyncio.Queue``.
"""

import asyncio
from types import SimpleNamespace

import pytest

from agent.writing.context import WritingContext
from agent.writing.hooks import (
    DONE_SENTINEL,
    WritingRunHooks,
    _agent_phase,
    _set_phase,
)


# -----------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------


def _fake_agent(name: str):
    """Minimal stand-in for the SDK's ``Agent`` in hook tests."""
    return SimpleNamespace(name=name)


def _fake_ctx():
    """Wrapper shaped like ``RunContextWrapper`` with a ``WritingContext``."""
    inner = WritingContext(
        sandbox_manager=None,
        thread_id="",
        correlation_id="",
        api_base_url="",
    )
    return SimpleNamespace(context=inner)


def _drain(queue: "asyncio.Queue[dict]") -> list[dict]:
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


# -----------------------------------------------------------------------
# Phase derivation helpers
# -----------------------------------------------------------------------


class TestPhaseHelpers:
    @pytest.mark.parametrize("name,expected", [
        ("BlueprintSpecialist", "planning"),
        ("WriterSpecialist", "writing"),
        ("LandscapeSpecialist", "landscape"),
        ("LiteratureAnalysisSpecialist", "literature"),
        ("CitationSpecialist", "citation"),
        ("WritingManager", None),
        ("", None),
    ])
    def test_agent_phase_mapping(self, name, expected):
        assert _agent_phase(_fake_agent(name)) == expected

    def test_set_phase_writes_through_wrapper(self):
        ctx = _fake_ctx()
        _set_phase(ctx, "writing")
        assert ctx.context.current_phase == "writing"

    def test_set_phase_ignores_none(self):
        ctx = _fake_ctx()
        ctx.context.current_phase = "writing"
        _set_phase(ctx, None)
        # None must not overwrite an existing phase.
        assert ctx.context.current_phase == "writing"

    def test_set_phase_tolerates_missing_inner(self):
        # Should never raise even if the wrapper shape is wrong.
        _set_phase(SimpleNamespace(context=None), "writing")
        _set_phase(SimpleNamespace(), "writing")


# -----------------------------------------------------------------------
# Lifecycle → SSE translation
# -----------------------------------------------------------------------


class TestLifecycleEmission:
    def test_on_agent_start_emits_plan_and_sets_phase(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        ctx = _fake_ctx()
        asyncio.run(hooks.on_agent_start(ctx, _fake_agent("BlueprintSpecialist")))
        events = _drain(queue)
        assert len(events) == 1
        assert events[0]["type"] == "planUpdate"
        assert events[0]["agent"] == "general_writing"
        assert ctx.context.current_phase == "planning"

    def test_emit_plan_carries_v2_envelope(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-plan")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        ev = _drain(queue)[0]
        assert ev["protocol_version"] == 2
        env = ev["event_v2"]
        # First emit of ``_plan_msg_id`` is ``add`` per v2.1 §11.3.
        assert env["op"] == "add"
        assert env["value"]["thread_id"] == "t-plan"
        # Plan is rendered as the unified card protocol now.
        assert env["value"]["content"]["type"] == "executeCard"
        md = env["value"]["meta_data"]
        # meta_data.tasks is the legacy PlanTask-shaped list still preserved
        # for Backend chat-formatter compatibility.
        tasks = md["tasks"]
        assert tasks and tasks[0]["status"] == "loading"
        # PlanTask time fields use the v2 spec names (start_time / end_time),
        # not the legacy time_created / time_finished.
        assert "start_time" in tasks[0]
        assert "end_time" in tasks[0]
        assert "time_created" not in tasks[0]
        assert "time_finished" not in tasks[0]
        # Card meta_data also exposes the same items as steps[] for direct
        # front-end rendering.
        assert md["steps"]
        assert md["frame_type"] == "ver"
        # v1 fields preserved for backward compatibility.
        assert ev["plan"] and ev["plan"][0]["status"] == "doing"

    def test_plan_task_end_time_set_on_terminal_steps(self):
        """A done step gets end_time stamped; in-flight steps stay None."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        # Drain initial in-flight emit.
        in_flight = _drain(queue)[0]
        assert in_flight["event_v2"]["value"]["meta_data"]["tasks"][0]["end_time"] is None
        # Trigger handoff which marks the prior step done and emits a save=True plan.
        asyncio.run(hooks.on_handoff(
            _fake_ctx(), _fake_agent("WritingManager"),
            _fake_agent("CitationSpecialist"),
        ))
        events = _drain(queue)
        plan_events = [e for e in events if e.get("type") == "planUpdate"]
        assert plan_events
        terminal_tasks = plan_events[-1]["event_v2"]["value"]["meta_data"]["tasks"]
        # At least one task is now done with a populated end_time.
        done = [t for t in terminal_tasks if t["status"] == "success"]
        assert done and all(t["end_time"] is not None for t in done)

    def test_emit_plan_reuses_stable_task_id_across_calls(self):
        """Multiple plan emits in one run target the same v2 entry; the
        front-end overwrites in place rather than spawning new bubbles."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        asyncio.run(hooks.on_handoff(
            _fake_ctx(), _fake_agent("WritingManager"),
            _fake_agent("CitationSpecialist"),
        ))
        events = _drain(queue)
        plan_task_ids = {
            e["event_v2"]["task_id"] for e in events if e.get("type") == "planUpdate"
        }
        assert len(plan_task_ids) == 1

    def test_index_counter_assigns_unique_indexes_per_messageitem(self):
        """Every new MessageItem (plan/status/stream first-delta) gets a
        unique increasing v2 ``index``; same task_id reuses its slot across
        emits."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-idx", start_index=1)
        # Emit twice for plan: same task_id → same index.
        asyncio.run(hooks._emit_plan())
        asyncio.run(hooks._emit_plan(save=True))
        plan_events = _drain(queue)
        assert len(plan_events) == 2
        plan_indexes = {e["event_v2"]["value"]["index"] for e in plan_events}
        assert plan_indexes == {1}  # plan reuses index 1 (first hook alloc)

        asyncio.run(hooks._emit_status())
        status_event = _drain(queue)[0]
        assert status_event["event_v2"]["value"]["index"] == 2  # next slot

        # First stream delta gets index 3.
        asyncio.run(hooks.handle_raw_response(
            SimpleNamespace(type="response.output_text.delta", delta="hi")
        ))
        stream_event = _drain(queue)[0]
        assert stream_event["event_v2"]["value"]["index"] == 3

    def test_start_index_reserves_slot_for_user_echo(self):
        """``start_index=1`` lets WritingAgent reserve index 0 for the
        user-question echo it yields before constructing hooks."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, start_index=1)
        asyncio.run(hooks._emit_plan())
        ev = _drain(queue)[0]
        assert ev["event_v2"]["value"]["index"] == 1

    def test_terminal_frames_carry_end_time(self):
        """``end_time`` is stamped on every MessageItem that reaches a
        terminal status — front-end uses it to render finish timestamps and
        stop "still working" spinners."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-end")
        # Plan in-flight: no end_time yet.
        asyncio.run(hooks._emit_plan(save=False))
        in_flight = _drain(queue)[0]
        assert in_flight["event_v2"]["value"]["end_time"] is None

        # Plan terminal: end_time present.
        asyncio.run(hooks._emit_plan(save=True))
        terminal = _drain(queue)[0]
        assert terminal["event_v2"]["value"]["end_time"] is not None
        assert terminal["event_v2"]["value"]["end_time"].endswith("Z")

        # Status emit: always terminal.
        asyncio.run(hooks._emit_status())
        status = _drain(queue)[0]
        assert status["event_v2"]["value"]["end_time"] is not None

    def test_emit_status_carries_v2_envelope(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-status")
        asyncio.run(hooks._emit_status())
        ev = _drain(queue)[0]
        assert ev["type"] == "statusUpdate"
        assert ev["protocol_version"] == 2
        env = ev["event_v2"]
        # First emit of ``_status_msg_id`` is ``add`` per v2.1 §11.3.
        assert env["op"] == "add"
        assert env["value"]["content"]["type"] == "status"
        assert env["value"]["thread_id"] == "t-status"
        assert env["value"]["meta_data"]["agent_status"] == "step_complete"

    def test_on_handoff_emits_plan_chat_and_switches_phase(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        ctx = _fake_ctx()
        asyncio.run(hooks.on_handoff(
            ctx, _fake_agent("WritingManager"), _fake_agent("CitationSpecialist"),
        ))
        events = _drain(queue)
        types = [e["type"] for e in events]
        assert types == ["planUpdate", "chat"]
        assert ctx.context.current_phase == "citation"
        # Chat payload names the destination agent.
        assert "CitationSpecialist" in events[1]["message"]

    def test_on_tool_start_then_end_emits_status_update(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        tool = SimpleNamespace(name="pubmed_search")
        asyncio.run(hooks.on_tool_start(_fake_ctx(), _fake_agent("WritingManager"), tool))
        asyncio.run(hooks.on_tool_end(_fake_ctx(), _fake_agent("WritingManager"), tool, "hello"))
        events = _drain(queue)
        types = [e["type"] for e in events]
        # 1st: planUpdate (doing), 2nd: planUpdate (done), 3rd: statusUpdate.
        assert types.count("planUpdate") >= 2
        assert "statusUpdate" in types

    def test_on_llm_end_with_text_emits_chat(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        # Response.output must be iterable; ``ItemHelpers.extract_text`` returns "" for
        # items it doesn't recognise, so _extract_response_text yields "" → no emit.
        asyncio.run(hooks.on_llm_end(_fake_ctx(), _fake_agent("WritingManager"),
                                     SimpleNamespace(output=[])))
        assert _drain(queue) == []  # empty text → no chat event.


# -----------------------------------------------------------------------
# v2 PlanTask shape — friendly labels + status-only completion
# -----------------------------------------------------------------------


class TestV2PlanTasks:
    """The v2 ``meta_data.tasks`` list (the PlanTask cards rendered on the
    frontend) is derived from ``plan_updates`` via ``_v2_plan_tasks``. It
    differs from the v1 ``plan`` field in two user-visible ways:

    1. The synthetic ``step_X_end`` marker that ``on_agent_end`` appends is
       suppressed — for v2 each logical step is one card whose status
       transitions ``loading → success``, instead of two separate rows.
    2. ``title`` / ``desc`` use friendly Chinese labels keyed by tool /
       agent name so the user sees "撰写章节 — 起草段落内容" instead of
       "WriterSpecialist — WriterSpecialist 开始规划任务".
    """

    def test_v2_plan_drops_synthetic_end_marker(self):
        """A complete agent run (start → end) produces ONE PlanTask card
        with ``status=success``, not two cards (start + synthetic end)."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        asyncio.run(hooks.on_agent_end(_fake_ctx(), _fake_agent("WritingManager"), None))
        events = _drain(queue)

        plan_events = [e for e in events if e.get("type") == "planUpdate"]
        assert plan_events
        terminal_tasks = plan_events[-1]["event_v2"]["value"]["meta_data"]["tasks"]
        assert len(terminal_tasks) == 1
        assert terminal_tasks[0]["status"] == "success"
        # No id ending with `_end` leaks into the v2 envelope.
        assert all(not t["id"].endswith("_end") for t in terminal_tasks)

    def test_v2_plan_uses_friendly_label_for_manager(self):
        """The orchestrator's PlanTask shows the Chinese alias, not the
        ``WritingManager`` class name. Labels are generic ("助手" /
        "正在思考" / "思考完成") so consultation turns don't read as a
        writing-only artefact."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        ev = _drain(queue)[0]
        task = ev["event_v2"]["value"]["meta_data"]["tasks"][0]
        assert task["title"] == "助手"
        # Loading desc differs from the success desc so the card visibly
        # advances when the run finishes.
        assert task["desc"] == "正在思考"
        assert task["status"] == "loading"

    def test_v2_plan_uses_friendly_label_for_known_tool(self):
        """A registered tool name (``pubmed_search``) maps to the friendly
        label rather than echoing the function name."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        tool = SimpleNamespace(name="pubmed_search")
        asyncio.run(hooks.on_tool_start(_fake_ctx(), _fake_agent("WritingManager"), tool))
        events = _drain(queue)
        plan_events = [e for e in events if e.get("type") == "planUpdate"]
        tasks = plan_events[-1]["event_v2"]["value"]["meta_data"]["tasks"]
        # Last task is the in-flight pubmed_search.
        assert tasks[-1]["title"] == "PubMed 检索"
        assert tasks[-1]["desc"] == "在 PubMed 中检索相关文献"
        assert tasks[-1]["status"] == "loading"

    def test_v2_plan_falls_back_for_unknown_tool(self):
        """A tool not in ``_V2_PLAN_LABELS`` keeps the raw name and reason
        — the front-end at least gets readable strings."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        tool = SimpleNamespace(name="some_future_tool")
        asyncio.run(hooks.on_tool_start(_fake_ctx(), _fake_agent("WritingManager"), tool))
        events = _drain(queue)
        plan_events = [e for e in events if e.get("type") == "planUpdate"]
        tasks = plan_events[-1]["event_v2"]["value"]["meta_data"]["tasks"]
        assert tasks[-1]["title"] == "some_future_tool"
        assert "some_future_tool" in tasks[-1]["desc"]

    def test_v2_plan_completion_only_flips_status(self):
        """``on_agent_end`` should not introduce a new PlanTask — the
        existing card just transitions from ``loading`` to ``success``."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.on_agent_start(_fake_ctx(), _fake_agent("WritingManager")))
        before = _drain(queue)[0]
        before_tasks = before["event_v2"]["value"]["meta_data"]["tasks"]
        before_ids = [t["id"] for t in before_tasks]

        asyncio.run(hooks.on_agent_end(_fake_ctx(), _fake_agent("WritingManager"), None))
        after = _drain(queue)[-1]
        after_tasks = after["event_v2"]["value"]["meta_data"]["tasks"]
        after_ids = [t["id"] for t in after_tasks]

        # Same set of cards before and after — only the status changed.
        assert before_ids == after_ids
        assert before_tasks[0]["status"] == "loading"
        assert after_tasks[0]["status"] == "success"


# -----------------------------------------------------------------------
# Raw response delta streaming
# -----------------------------------------------------------------------


class TestHandleRawResponse:
    def test_first_delta_emits_immediately(self):
        """The first delta of a stream bypasses throttle so the front-end can
        ``op=add`` an entry as soon as content starts arriving."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.handle_raw_response(
            SimpleNamespace(type="response.output_text.delta", delta="hi")
        ))
        events = _drain(queue)
        assert len(events) == 1
        # v1 ``message`` is intentionally empty — v2 envelope owns the text now.
        assert events[0]["message"] == ""
        assert events[0]["save"] is False

    def test_throttle_collapses_internal_deltas(self):
        """Within one throttle window only the first delta emits; later
        deltas accumulate silently into the cumulative buffer."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        for ch in "abcde":
            asyncio.run(hooks.handle_raw_response(
                SimpleNamespace(type="response.output_text.delta", delta=ch)
            ))
        events = _drain(queue)
        assert len(events) == 1
        # v1 ``chunkIdx`` was dropped — v2 ``index`` on the value identifies
        # the message bubble, not the per-frame sequence.
        assert "chunkIdx" not in events[0]
        assert events[0]["event_v2"]["value"]["index"] == 0

    def test_ignores_other_events(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.handle_raw_response(
            SimpleNamespace(type="response.created", delta=None)
        ))
        asyncio.run(hooks.handle_raw_response(
            SimpleNamespace(type="response.output_text.done", delta="")
        ))
        assert _drain(queue) == []

    def test_ignores_empty_delta(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.handle_raw_response(
            SimpleNamespace(type="response.output_text.delta", delta="")
        ))
        assert _drain(queue) == []


# -----------------------------------------------------------------------
# v2 cumulative streaming envelope
# -----------------------------------------------------------------------


class TestV2CumulativeStreaming:
    def _emit_deltas(self, hooks, deltas):
        for d in deltas:
            asyncio.run(hooks.handle_raw_response(
                SimpleNamespace(type="response.output_text.delta", delta=d)
            ))

    def _disable_throttle(self, hooks):
        """Force every delta past the throttle gate (used by tests that care
        about per-delta v2 frame structure rather than throttle behaviour)."""
        hooks._v2_throttle_interval = 0.0
        hooks._v2_throttle_chars = 1

    def test_first_delta_is_op_add_with_cumulative_text(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-1")
        self._emit_deltas(hooks, ["你好"])
        events = _drain(queue)
        env = events[0]["event_v2"]
        assert env["op"] == "add"
        assert env["value"]["thread_id"] == "t-1"
        assert env["value"]["content"] == {"type": "markdown", "text": "你好"}
        assert env["value"]["status"] == "loading"

    def test_subsequent_deltas_emit_replace_with_cumulative(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        self._disable_throttle(hooks)
        self._emit_deltas(hooks, ["你好", "！", "我"])
        events = _drain(queue)
        ops = [e["event_v2"]["op"] for e in events]
        # ``replace`` not ``patch``: per ``handle_raw_response`` the patch
        # value would be the cumulative full text — same payload size as
        # replace, but the patch wrapper adds decoding cost.
        assert ops == ["add", "replace", "replace"]
        # Each replace carries the cumulative text under
        # ``event_v2.value.content.text``.
        assert events[1]["event_v2"]["value"]["content"]["text"] == "你好！"
        assert events[2]["event_v2"]["value"]["content"]["text"] == "你好！我"

    def test_same_stream_shares_task_id(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        self._disable_throttle(hooks)
        self._emit_deltas(hooks, ["a", "b", "c"])
        events = _drain(queue)
        task_ids = {e["event_v2"]["task_id"] for e in events}
        assert len(task_ids) == 1

    def test_v1_message_field_is_blank_in_stream_frames(self):
        """v2 envelope owns the text; v1 ``message`` is intentionally empty
        in throttled stream frames so v1-only clients can no longer accidentally
        render half-baked deltas."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        self._emit_deltas(hooks, ["hi"])
        ev = _drain(queue)[0]
        assert ev["type"] == "chat"
        assert ev["sender"] == "assistant"
        assert ev["message"] == ""
        assert "chunkIdx" not in ev
        assert ev["save"] is False
        assert ev["protocol_version"] == 2
        assert "event_v2" in ev

    def test_throttle_collapses_short_burst(self):
        """A burst of small deltas inside one throttle window emits exactly
        one frame (the first). The cumulative text on that frame reflects only
        the deltas seen so far."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        # Generous throttle so the burst can't escape it; short deltas keep
        # us under the char threshold too.
        hooks._v2_throttle_interval = 5.0
        hooks._v2_throttle_chars = 100
        self._emit_deltas(hooks, ["你", "好", "啊"])
        events = _drain(queue)
        assert len(events) == 1
        # Only the first delta made it onto the frame.
        assert events[0]["event_v2"]["value"]["content"]["text"] == "你"

    def test_throttle_emits_after_char_threshold(self):
        """If accumulated chars cross the threshold inside one window, emit
        without waiting for the timer."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        hooks._v2_throttle_interval = 5.0  # disable time-based emit
        hooks._v2_throttle_chars = 4
        # First delta passes (is_first); next 3 stay queued; the 5th delta
        # pushes the cumulative beyond the 4-char gate and emits.
        self._emit_deltas(hooks, ["a", "b", "c", "d", "ef"])
        events = _drain(queue)
        assert len(events) == 2
        ops = [e["event_v2"]["op"] for e in events]
        assert ops == ["add", "replace"]
        assert events[1]["event_v2"]["value"]["content"]["text"] == "abcdef"

    def test_on_tool_start_resets_stream_buffer(self):
        """A new step (e.g. handing off to a sub-agent) starts a fresh
        stream with a new ``msg_id`` so the front-end allocates a separate
        bubble. ``event_v2.task_id`` (= hooks.parent_task_id) stays
        constant across the whole run; the per-stream identity lives in
        ``event_v2.msg_id`` (= ``s["msg_id"]`` from ``_streams``)."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        self._emit_deltas(hooks, ["abc"])
        first_msg_id = _drain(queue)[0]["event_v2"]["msg_id"]

        tool = SimpleNamespace(name="search")
        asyncio.run(hooks.on_tool_start(_fake_ctx(),
                                        _fake_agent("WritingManager"), tool))
        _drain(queue)  # discard plan frames

        self._emit_deltas(hooks, ["xyz"])
        second_msg_id = _drain(queue)[0]["event_v2"]["msg_id"]
        assert first_msg_id != second_msg_id

    def test_on_llm_end_emits_terminal_replace_reusing_task_id(self):
        """Direct extraction is opaque to the SDK in tests, so we patch
        ``_extract_response_text`` to return a fixed final string."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        self._emit_deltas(hooks, ["hello"])
        stream_task = _drain(queue)[0]["event_v2"]["task_id"]

        from unittest.mock import patch
        text = "hello world"
        with patch.object(WritingRunHooks, "_extract_response_text",
                           return_value=text):
            asyncio.run(hooks.on_llm_end(_fake_ctx(),
                                         _fake_agent("WritingManager"),
                                         SimpleNamespace(output=[])))
        events = _drain(queue)
        assert len(events) == 1
        env = events[0]["event_v2"]
        assert env["op"] == "replace"
        assert env["task_id"] == stream_task
        assert env["value"]["content"]["text"] == text
        assert env["value"]["status"] == "success"
        # Stream-flush terminal frame: v1 ``message`` is empty even though the
        # v2 envelope still carries the full cumulative text.
        assert events[0]["message"] == ""

    def test_on_llm_end_without_prior_stream_emits_op_add(self):
        """Non-streamed responses (no preceding deltas) emit op=add directly."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        from unittest.mock import patch
        text = "direct response"
        with patch.object(WritingRunHooks, "_extract_response_text",
                           return_value=text):
            asyncio.run(hooks.on_llm_end(_fake_ctx(),
                                         _fake_agent("WritingManager"),
                                         SimpleNamespace(output=[])))
        env = _drain(queue)[0]["event_v2"]
        assert env["op"] == "add"
        assert env["value"]["status"] == "success"
        assert env["value"]["content"]["text"] == text

    def test_emit_chat_outside_stream_keeps_v1_message(self):
        """Non-stream chat events (handoff, errors, direct response) must keep
        the v1 ``message`` field populated — only the stream-flush path blanks
        it."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks._emit_chat("welcome", flush_stream=False))
        ev = _drain(queue)[0]
        assert ev["message"] == "welcome"


# -----------------------------------------------------------------------
# Sentinel / error / done
# -----------------------------------------------------------------------


class TestSignalsAndErrors:
    def test_signal_done_enqueues_sentinel(self):
        """``signal_done`` now emits a ``stream_end`` v2 frame *before* the
        sentinel (Plan F). The reader breaks on the sentinel, so the
        terminal frame must come first or it'll never reach the consumer."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        asyncio.run(hooks.signal_done())
        events = _drain(queue)
        assert len(events) == 2
        assert events[1] is DONE_SENTINEL
        assert events[0]["event_v2"]["value"]["content"]["type"] == "stream_end"

    def test_emit_error_payload_shape(self):
        """``emit_error`` must produce a v2-enveloped frame so v2 clients can
        render the failure (the frame fires when ``Runner.run`` raises)."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing",
                                 thread_id="t-err")
        asyncio.run(hooks.emit_error("boom"))
        events = _drain(queue)
        assert len(events) == 1
        ev = events[0]
        # v1 fields kept for legacy routing.
        assert ev["type"] == "chat"
        assert ev["message"] == "boom"
        assert ev["save"] is True
        assert ev["id"] == "error-0"
        # v2 envelope present.
        assert ev["protocol_version"] == 2
        env = ev["event_v2"]
        assert env["op"] == "add"
        assert env["value"]["thread_id"] == "t-err"
        assert env["value"]["sender"] == "system"
        assert env["value"]["status"] == "error"
        assert env["value"]["content"] == {"type": "error", "text": "boom"}
        assert env["value"]["end_time"] is not None

    def test_writing_agent_does_not_yield_user_echo(self):
        """WritingAgent.start no longer yields the user-question echo —
        Backend (``API/chat.py::_get_agent_input``) sends it directly to
        the WebSocket immediately after the v2 snapshot seed, so the
        frontend renders the user bubble before NoahAgent's HTTP
        roundtrip finishes. NoahAgent's role is to stream agent /
        assistant frames only.
        """
        import json
        from unittest.mock import patch
        from agent.writing.agent import WritingAgent

        async def collect_all_frames():
            agent = WritingAgent(thread_id="t-echo")
            # Stop early: model init raises so we don't spin up Runner.
            with patch(
                "agent.writing.agent.build_default_model",
                side_effect=RuntimeError("stop"),
            ):
                out: list = []
                async for line in agent.start(user_prompt="你好啊", thread_id="t-echo"):
                    out.append(line)
                return out

        lines = asyncio.run(collect_all_frames())
        for line in lines:
            ev = json.loads(line.rstrip("\n"))
            assert ev.get("sender") != "user", (
                f"unexpected user-echo from NoahAgent (Backend owns it): {ev}"
            )

    def test_writing_agent_model_init_failure_emits_v2_error_envelope(self):
        """When ``build_default_model`` raises, ``WritingAgent.start`` must
        yield a chat frame whose v2 envelope is ``op=add`` + ``content.type=error``
        so the front-end's ErrorMessage renderer can show the failure."""
        import json
        from unittest.mock import patch
        from agent.writing.agent import WritingAgent

        async def collect():
            agent = WritingAgent(thread_id="t-err")
            with patch(
                "agent.writing.agent.build_default_model",
                side_effect=RuntimeError("boom"),
            ):
                out: list = []
                async for line in agent.start(user_prompt="hi", thread_id="t-err"):
                    out.append(line)
                return out

        lines = asyncio.run(collect())
        # ``standardize_yield`` serializes each yielded dict as JSON + "\n".
        # First frame is the user-question echo (added later); the error
        # frame follows once build_default_model raises.
        frames = [json.loads(line.rstrip("\n")) for line in lines]
        error_frames = [
            f for f in frames
            if f.get("event_v2", {}).get("value", {}).get("content", {}).get("type") == "error"
        ]
        assert error_frames, f"no error frame in {frames}"
        ev = error_frames[0]
        assert ev["type"] == "chat"
        assert "模型初始化失败" in ev["message"]
        assert ev["protocol_version"] == 2
        env = ev["event_v2"]
        assert env["op"] == "add"
        assert env["value"]["thread_id"] == "t-err"
        assert env["value"]["status"] == "error"
        assert env["value"]["sender"] == "system"

    def test_writing_agent_empty_input_emits_v2_error_envelope(self):
        """Empty ``user_prompt`` + no history must yield a v2-enveloped error
        frame so the front-end shows '请提供写作任务描述' instead of silently
        dropping the frame."""
        import json
        from agent.writing.agent import WritingAgent

        async def collect():
            agent = WritingAgent(thread_id="t-empty")
            out: list = []
            async for line in agent.start(user_prompt="", thread_id="t-empty"):
                out.append(line)
            return out

        lines = asyncio.run(collect())
        frames = [json.loads(line.rstrip("\n")) for line in lines]
        # The empty-input branch is the only frame yielded.
        assert len(frames) == 1, f"expected 1 frame, got {frames}"
        ev = frames[0]
        assert ev["type"] == "chat"
        assert "请提供写作任务描述" in ev["message"]
        assert ev["protocol_version"] == 2
        env = ev["event_v2"]
        assert env["op"] == "add"
        assert env["value"]["thread_id"] == "t-empty"
        assert env["value"]["sender"] == "system"
        assert env["value"]["status"] == "error"
        assert env["value"]["content"]["type"] == "error"


# -----------------------------------------------------------------------
# stream_end terminal frame (Plan F)
# -----------------------------------------------------------------------


class TestStreamEndFrame:
    """Verify ``WritingRunHooks.signal_done`` emits a ``stream_end`` v2 frame
    immediately before ``DONE_SENTINEL`` so Backend can distinguish clean
    completion from a broken stream.

    Without this, Backend's ``_update_task`` cannot tell whether the writing
    agent finished the run or the stream just stopped — which surfaces as
    the ``task_status="complete" + result_json={} + time_finished=null``
    dirty-completion bug.
    """

    def test_signal_done_ok_emits_stream_end_then_sentinel(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, thread_id="t-1", task_id="task-1")
        asyncio.run(hooks.signal_done(status="ok"))
        frames = _drain(queue)
        # Two items: the stream_end envelope, then the sentinel.
        assert len(frames) == 2
        assert frames[1] is DONE_SENTINEL
        end_frame = frames[0]
        assert end_frame["type"] == "statusUpdate"
        assert end_frame["protocol_version"] == 2
        env = end_frame["event_v2"]
        assert env["op"] == "add"
        assert env["task_id"] == "task-1"
        assert env["value"]["status"] == "ok"
        assert env["value"]["content"]["type"] == "stream_end"
        assert env["value"]["meta_data"]["stream_status"] == "ok"
        assert env["value"]["meta_data"]["reason"] is None
        assert isinstance(env["value"]["meta_data"]["frame_count"], int)

    def test_signal_done_error_carries_reason(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, task_id="task-2")
        asyncio.run(hooks.signal_done(status="error", reason="boom"))
        end_frame = _drain(queue)[0]
        env = end_frame["event_v2"]
        assert env["value"]["status"] == "error"
        assert env["value"]["meta_data"]["stream_status"] == "error"
        assert env["value"]["meta_data"]["reason"] == "boom"

    def test_signal_done_interrupted_uses_status(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.signal_done(status="interrupted", reason="cancelled"))
        end_frame = _drain(queue)[0]
        assert end_frame["event_v2"]["value"]["status"] == "interrupted"
        assert end_frame["event_v2"]["value"]["meta_data"]["reason"] == "cancelled"

    def test_signal_done_default_status_is_ok(self):
        """Backwards-compatible call site: ``await hooks.signal_done()``."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.signal_done())
        end_frame = _drain(queue)[0]
        assert end_frame["event_v2"]["value"]["status"] == "ok"

    def test_stream_end_index_is_after_other_frames(self):
        """``frame_count`` should reflect every index allocated up to that point."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, start_index=1)
        # Burn a few indexes as if real frames had emitted.
        hooks._alloc_index(); hooks._alloc_index(); hooks._alloc_index()
        asyncio.run(hooks.signal_done(status="ok"))
        end_frame = _drain(queue)[0]
        # 3 fake allocs + 1 for stream_end = next_index = 5 (start was 1).
        assert end_frame["event_v2"]["value"]["meta_data"]["frame_count"] == 5


# -----------------------------------------------------------------------
# Dirty-completion bug fix: stream_end must be delivered under cancellation,
# never silently dropped via put_nowait, and ``on_agent_end`` must flip the
# envelope-level task_status so the LAST regular frame carries terminal.
# -----------------------------------------------------------------------


class TestStreamEndDeliveryUnderCancellation:
    """Verify the three guarantees that prevent the
    ``task_status=complete + result_json={} + time_finished=null``
    dirty-completion bug on Backend's Task row.
    """

    def test_signal_done_uses_await_put_not_put_nowait(self):
        """``signal_done`` must enqueue via ``await put`` so that a future
        bounded queue (or one that's transiently full) doesn't silently drop
        the terminal frame.

        Regression guard: a previous implementation called ``put_nowait``
        and only logged a warning on ``QueueFull``. Backend would then see
        DONE_SENTINEL with no preceding stream_end and write the wrong
        ``task_status``.
        """
        # maxsize=1 queue. With ``put_nowait`` the second put would raise
        # QueueFull and drop the stream_end. With ``await put`` it just
        # waits — and we drain in parallel below.
        queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        hooks = WritingRunHooks(queue=queue, task_id="task-await")

        async def _scenario():
            # Pre-fill the queue so the first signal_done.put would block.
            await queue.put({"filler": True})
            # Start signal_done — it must NOT drop stream_end, it must
            # await for room.
            done_task = asyncio.create_task(hooks.signal_done(status="ok"))
            # Let the put attempt schedule.
            await asyncio.sleep(0)
            # Drain the filler so signal_done can proceed.
            filler = await queue.get()
            assert filler == {"filler": True}
            # Now signal_done's stream_end + DONE_SENTINEL flow through.
            stream_end = await queue.get()
            sentinel = await queue.get()
            await done_task
            return stream_end, sentinel

        stream_end, sentinel = asyncio.run(_scenario())
        # stream_end is real (not dropped) and DONE_SENTINEL follows.
        assert stream_end["event_v2"]["value"]["content"]["type"] == "stream_end"
        assert stream_end["event_v2"]["task_status"] == "complete"
        assert sentinel is DONE_SENTINEL

    def test_stream_end_reachable_after_runner_cancellation(self):
        """Simulate the drain-loop / runner_task race: an outer task awaits
        the queue while an inner "runner" task runs ``signal_done`` during
        its ``finally`` block after being cancelled. The fix in
        ``agent.py``'s drain loop is to drain remaining frames in the
        outer ``finally`` so stream_end reaches the HTTP consumer.

        Here we just verify the queue itself ends up with the stream_end
        frame after cancellation — the drain-loop side is integration-tested
        in ``TestSignalsAndErrors``.
        """
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, task_id="task-cancel")

        async def _fake_runner():
            try:
                # Pretend we're streaming forever until cancelled.
                while True:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                # The real ``_run_and_signal`` sets terminal_status here.
                raise
            finally:
                # ``signal_done`` in the runner's finally — exactly mirrors
                # ``WritingAgent._run_and_signal``.
                await hooks.signal_done(status="interrupted", reason="cancelled")

        async def _scenario():
            runner = asyncio.create_task(_fake_runner())
            await asyncio.sleep(0.02)
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            # After cancellation completes, the runner's finally has run
            # and stream_end + DONE_SENTINEL should be sitting in the queue.
            frames = []
            while not queue.empty():
                frames.append(queue.get_nowait())
            return frames

        frames = asyncio.run(_scenario())
        # We expect at least stream_end + DONE_SENTINEL (in that order).
        # stream_end is the v2 statusUpdate frame.
        stream_end_frames = [
            f for f in frames
            if isinstance(f, dict)
            and f.get("type") == "statusUpdate"
            and f.get("event_v2", {}).get("value", {})
                 .get("content", {}).get("type") == "stream_end"
        ]
        assert stream_end_frames, (
            f"stream_end frame missing after runner cancellation; got: {frames}"
        )
        end = stream_end_frames[0]
        assert end["event_v2"]["task_status"] == "abandon"
        assert end["event_v2"]["value"]["meta_data"]["reason"] == "cancelled"
        # DONE_SENTINEL is last.
        assert DONE_SENTINEL in frames
        assert frames.index(end) < frames.index(DONE_SENTINEL)

    def test_on_agent_end_flips_task_status_so_final_plan_frame_is_terminal(self):
        """``on_agent_end`` must flip ``_current_task_status`` from RUNNING
        to COMPLETE BEFORE emitting the final plan frame, so the last
        non-stream_end frame Backend sees already carries the terminal
        envelope-level status. This is the "double safety" against
        stream_end loss in the network layer.
        """
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, task_id="task-end")
        ctx = _fake_ctx()
        # Simulate the manager agent running one step.
        asyncio.run(hooks.on_agent_start(ctx, _fake_agent("WritingManager")))
        # Pre-condition: still running.
        assert hooks._current_task_status == "running"
        # Drive the agent-end callback (mirrors what SDK does on clean exit).
        asyncio.run(hooks.on_agent_end(ctx, _fake_agent("WritingManager"), None))
        # Post-condition 1: state flipped to COMPLETE.
        assert hooks._current_task_status == "complete"
        # Post-condition 2: the LAST planUpdate frame emitted in on_agent_end
        # carries ``task_status=complete`` at the envelope level.
        frames = _drain(queue)
        plan_frames = [f for f in frames if f.get("type") == "planUpdate"]
        assert plan_frames, "expected at least one planUpdate"
        last_plan = plan_frames[-1]
        assert last_plan["event_v2"]["task_status"] == "complete"

    def test_signal_done_error_overrides_on_agent_end_complete(self):
        """If a crash happens AFTER ``on_agent_end`` already flipped to
        COMPLETE, ``signal_done(status='error')`` must still flip back to
        FAILED — i.e. the on_agent_end shortcut isn't sticky against the
        actual run outcome.
        """
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, task_id="task-race")
        ctx = _fake_ctx()
        asyncio.run(hooks.on_agent_start(ctx, _fake_agent("WritingManager")))
        asyncio.run(hooks.on_agent_end(ctx, _fake_agent("WritingManager"), None))
        assert hooks._current_task_status == "complete"
        # Then something blows up post-completion.
        asyncio.run(hooks.signal_done(status="error", reason="post-end crash"))
        assert hooks._current_task_status == "failed"
        # stream_end frame also carries failed.
        stream_end_frames = [
            f for f in _drain(queue)
            if isinstance(f, dict)
            and f.get("type") == "statusUpdate"
            and f.get("event_v2", {}).get("value", {})
                 .get("content", {}).get("type") == "stream_end"
        ]
        assert stream_end_frames
        assert stream_end_frames[0]["event_v2"]["task_status"] == "failed"


# -----------------------------------------------------------------------
# Reconcile / snapshot allow-list throttle (Plan C)
# -----------------------------------------------------------------------


class TestReconcileAllowList:
    """Verify the ``_WRITE_CAPABLE_TOOL_NAMES`` allow-list and
    ``_should_reconcile`` gate.

    Search tools (``pubmed_search`` / ``literature_pool`` / ``project_search``)
    can't produce sandbox files, so snapshot + reconcile must skip them.
    Unknown tool names fall back to "always reconcile" — losing files would
    be far worse than an extra OSS round-trip.
    """

    def test_should_reconcile_writes_yes(self):
        assert WritingRunHooks._should_reconcile("run_in_sandbox") is True
        assert WritingRunHooks._should_reconcile("attachment_download") is True

    def test_should_reconcile_readonly_no(self):
        assert WritingRunHooks._should_reconcile("pubmed_search") is False
        assert WritingRunHooks._should_reconcile("literature_pool") is False
        assert WritingRunHooks._should_reconcile("project_search") is False

    def test_should_reconcile_unknown_falls_back_to_yes(self):
        """Conservative default — unknown tools reconcile so files don't vanish."""
        assert WritingRunHooks._should_reconcile("brand_new_tool_2026") is True

    def test_on_tool_start_skips_snapshot_for_readonly_tool(self, monkeypatch):
        """No snapshot call when a read-only tool fires."""
        called = []

        async def _fake_snapshot(_):
            called.append(1)
            return {"sentinel"}

        monkeypatch.setattr(
            "agent.writing.hooks.snapshot_sandbox_files", _fake_snapshot,
        )
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        tool = SimpleNamespace(name="pubmed_search")
        asyncio.run(hooks.on_tool_start(_fake_ctx(),
                                         _fake_agent("WritingManager"), tool))
        assert called == [], "snapshot must not run for read-only tools"
        # Baseline cleared so the next write-capable tool starts fresh.
        assert hooks._sandbox_snapshot == set()

    def test_on_tool_start_snapshots_for_write_capable_tool(self, monkeypatch):
        called = []

        async def _fake_snapshot(_):
            called.append(1)
            return {"file_a"}

        monkeypatch.setattr(
            "agent.writing.hooks.snapshot_sandbox_files", _fake_snapshot,
        )
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        tool = SimpleNamespace(name="run_in_sandbox")
        asyncio.run(hooks.on_tool_start(_fake_ctx(),
                                         _fake_agent("WritingManager"), tool))
        assert called == [1]
        assert hooks._sandbox_snapshot == {"file_a"}

    def test_on_tool_end_skips_reconcile_for_readonly_tool(self, monkeypatch):
        called = []

        async def _fake_reconcile(self):  # bound method shape
            called.append(1)

        monkeypatch.setattr(
            WritingRunHooks, "_reconcile_workspace_assets", _fake_reconcile,
        )
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        tool = SimpleNamespace(name="literature_pool")
        asyncio.run(hooks.on_tool_end(_fake_ctx(),
                                       _fake_agent("WritingManager"), tool,
                                       "result text"))
        assert called == [], "reconcile must not run for read-only tools"

    def test_on_tool_end_reconciles_for_write_capable_tool(self, monkeypatch):
        called = []

        async def _fake_reconcile(self):
            called.append(1)

        monkeypatch.setattr(
            WritingRunHooks, "_reconcile_workspace_assets", _fake_reconcile,
        )
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        tool = SimpleNamespace(name="run_in_sandbox")
        asyncio.run(hooks.on_tool_end(_fake_ctx(),
                                       _fake_agent("WritingManager"), tool,
                                       "result text"))
        assert called == [1]

    def test_on_tool_end_unknown_tool_reconciles(self, monkeypatch):
        """Conservative fallback: a new tool we haven't classified yet still
        gets reconcile so its outputs don't disappear silently."""
        called = []

        async def _fake_reconcile(self):
            called.append(1)

        monkeypatch.setattr(
            WritingRunHooks, "_reconcile_workspace_assets", _fake_reconcile,
        )
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        tool = SimpleNamespace(name="future_tool_not_yet_classified")
        asyncio.run(hooks.on_tool_end(_fake_ctx(),
                                       _fake_agent("WritingManager"), tool,
                                       "x"))
        assert called == [1]


# -----------------------------------------------------------------------
# Envelope-level task_status field
# -----------------------------------------------------------------------


class TestTaskStatusInEnvelope:
    """Verify every v2 frame emitted by ``WritingRunHooks`` carries a
    ``task_status`` field at envelope level (alongside ``task_id``).

    Front-end reads this off any frame to lock/unlock the composer and
    decide whether to show the cancel button — without it, the field has
    to be re-derived from a separate signal, defeating the point.
    """

    def _ts(self, frame):
        """Pull the envelope-level ``task_status`` for assertion."""
        return frame["event_v2"]["task_status"]

    def test_default_status_is_running(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        assert hooks._current_task_status == "running"

    def test_plan_frame_carries_running(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, task_id="t-1")
        asyncio.run(hooks.on_agent_start(_fake_ctx(),
                                          _fake_agent("WritingManager")))
        frames = _drain(queue)
        plan_frames = [f for f in frames if f.get("type") == "planUpdate"]
        assert plan_frames, "expected at least one planUpdate"
        for f in plan_frames:
            assert self._ts(f) == "running"

    def test_chat_frame_carries_running(self):
        """A streaming chat frame mid-run should carry ``running``."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks._emit_chat("hello world", save=False,
                                      stream_key="0-stream-0"))
        chat_frames = [f for f in _drain(queue) if f.get("type") == "chat"]
        assert chat_frames
        assert self._ts(chat_frames[0]) == "running"

    def test_signal_done_ok_writes_complete(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.signal_done(status="ok"))
        end = _drain(queue)[0]
        # Both the inline state machine and the emitted frame must agree.
        assert hooks._current_task_status == "complete"
        assert self._ts(end) == "complete"

    def test_signal_done_error_writes_failed(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.signal_done(status="error", reason="boom"))
        end = _drain(queue)[0]
        assert hooks._current_task_status == "failed"
        assert self._ts(end) == "failed"

    def test_signal_done_interrupted_writes_abandon(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.signal_done(status="interrupted", reason="cancelled"))
        end = _drain(queue)[0]
        assert hooks._current_task_status == "abandon"
        assert self._ts(end) == "abandon"

    def test_emit_error_flips_status_before_frame(self):
        """The error frame itself must already carry ``failed`` — otherwise
        the front-end sees a ``running`` frame after the agent crashed."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.emit_error("kaboom"))
        err_frame = _drain(queue)[0]
        assert hooks._current_task_status == "failed"
        assert self._ts(err_frame) == "failed"

    def test_status_persists_across_frames_after_terminal(self):
        """Once flipped to a terminal value, subsequent frames keep it."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue)
        asyncio.run(hooks.emit_error("kaboom"))
        # Now imagine a stream_end follows — must also carry failed.
        asyncio.run(hooks.signal_done(status="error", reason="kaboom"))
        frames = _drain(queue)
        # First frame is the error chat; second is stream_end; third sentinel.
        assert frames[-1] is DONE_SENTINEL
        for f in frames[:-1]:
            assert self._ts(f) == "failed"


# -----------------------------------------------------------------------
# ``<plan>`` tag extraction (per AGENTS.md)
# -----------------------------------------------------------------------


class TestPlanTagExtraction:
    """The LLM appends a ``<plan>...</plan>`` tag at the end of every
    response per AGENTS.md. Backend pulls the content as the plan card
    ``desc`` and strips the tag from the user-facing markdown."""

    def test_extracts_tag_at_end(self):
        text = "你好！\n<plan>已为您回复</plan>"
        plan, stripped = WritingRunHooks._extract_and_strip_plan_tag(text)
        assert plan == "已为您回复"
        assert stripped == "你好！"

    def test_extracts_multiline_content(self):
        text = "Reply.\n<plan>正在检索 PubMed\n并整理引用</plan>"
        plan, stripped = WritingRunHooks._extract_and_strip_plan_tag(text)
        assert plan == "正在检索 PubMed\n并整理引用"
        assert stripped == "Reply."

    def test_no_tag_returns_original_text(self):
        text = "plain reply, no tag"
        plan, stripped = WritingRunHooks._extract_and_strip_plan_tag(text)
        assert plan == ""
        assert stripped == "plain reply, no tag"

    def test_empty_tag_yields_empty_plan(self):
        text = "Reply.<plan>   </plan>"
        plan, stripped = WritingRunHooks._extract_and_strip_plan_tag(text)
        assert plan == ""
        assert stripped == "Reply."

    def test_multiple_tags_keeps_last_strips_all(self):
        """LLM occasionally emits more than one tag; canonical is the last."""
        text = "<plan>old</plan>body\n<plan>new</plan>"
        plan, stripped = WritingRunHooks._extract_and_strip_plan_tag(text)
        assert plan == "new"
        assert stripped == "body"

    def test_truncate_at_plan_start_drops_in_flight_tag(self):
        """Streaming-time helper: cut before ``<plan>`` even if not yet closed."""
        cumulative = "Hello world\n<plan>正在准"  # closing tag hasn't arrived
        assert WritingRunHooks._truncate_at_plan_start(cumulative) == "Hello world"

    def test_truncate_at_plan_start_no_tag_passthrough(self):
        assert WritingRunHooks._truncate_at_plan_start("hi") == "hi"

    def test_truncate_at_plan_start_handles_empty(self):
        assert WritingRunHooks._truncate_at_plan_start("") == ""


class TestPlanTagDescriptionFlow:
    """End-to-end-ish: when the LLM emits a plan tag, the plan card's
    ``desc`` field reflects that text instead of the static label."""

    def test_llm_plan_overrides_static_label(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        # Simulate on_agent_start having pushed the WritingManager step.
        hooks.plan_updates.append({
            "id": "step_0_start",
            "reason": "WritingManager 开始规划任务",
            "startedAt": 0,
            "status": "doing",
            "tool": "WritingManager",
        })
        # LLM emits a plan tag; on_llm_end records it on the active step.
        hooks.plan_updates[-1]["llm_plan"] = "正在思考与回复"

        cards = hooks._v2_plan_tasks()
        assert len(cards) == 1
        # The dynamic plan from the LLM wins over the static
        # ``("助手", "正在思考", "思考完成")`` label.
        assert cards[0]["desc"] == "正在思考与回复"
        assert cards[0]["title"] == "助手"

    def test_falls_back_to_static_label_when_no_llm_plan(self):
        """No tag emitted → static success_desc still drives the card."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        hooks.plan_updates.append({
            "id": "step_0_start",
            "reason": "...",
            "startedAt": 0,
            "status": "done",   # terminal
            "tool": "WritingManager",
        })
        cards = hooks._v2_plan_tasks()
        assert cards[0]["desc"] == "思考完成"   # static success_desc

    def test_on_llm_end_records_llm_plan_and_strips_text(self):
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        hooks.plan_updates.append({
            "id": "step_0_start",
            "reason": "...",
            "startedAt": 0,
            "status": "doing",
            "tool": "WritingManager",
        })
        # Build a fake ModelResponse whose extracted text contains the tag.
        fake_response = SimpleNamespace(output=[
            SimpleNamespace(content=[SimpleNamespace(text="你好！\n<plan>已生成回复</plan>", type="output_text")])
        ])
        # Patch ItemHelpers.extract_text since the agents-SDK shape is fragile.
        from agent.writing import hooks as hooks_mod
        original = hooks_mod.ItemHelpers.extract_text
        try:
            hooks_mod.ItemHelpers.extract_text = staticmethod(
                lambda item: getattr(item.content[0], "text", "")
            )
            asyncio.run(hooks.on_llm_end(_fake_ctx(), _fake_agent("WritingManager"), fake_response))
        finally:
            hooks_mod.ItemHelpers.extract_text = original

        # Plan card desc reflects the LLM-emitted plan.
        assert hooks.plan_updates[-1].get("llm_plan") == "已生成回复"
        # The chat frame emitted to the queue must NOT contain the tag.
        chat_frame = next(
            f for f in _drain(queue)
            if isinstance(f, dict) and (f.get("event_v2") or {}).get("value", {}).get("content", {}).get("type") == "markdown"
        )
        text = chat_frame["event_v2"]["value"]["content"]["text"]
        assert "<plan>" not in text
        assert "</plan>" not in text
        assert "你好！" in text


# -----------------------------------------------------------------------
# ``<thinking>`` tag + ``ResponseReasoningItem`` native reasoning
# -----------------------------------------------------------------------


class TestThinkingTagAndReasoning:
    """Three-tier fallback for the plan card's ``desc``:
    ``<plan>`` → ``<thinking>`` → native ``ResponseReasoningItem``."""

    def test_thinking_tag_extracted_alongside_plan(self):
        """A response with ONLY a ``<thinking>`` tag → ``thinking_text``
        set, ``plan_text`` empty, body stripped of the tag."""
        text = "你好！\n<thinking>问候,询问写作意图</thinking>"
        plan, thinking, stripped = WritingRunHooks._extract_plan_and_thinking(text)
        assert plan == ""
        assert thinking == "问候,询问写作意图"
        assert stripped == "你好！"

    def test_plan_wins_over_thinking_when_both_present(self):
        """Defence-in-depth: if the LLM emits both tags (it shouldn't,
        per AGENTS.md), the explicit plan-of-action wins. Body strips
        both."""
        text = "回复正文\n<plan>正在检索文献</plan>\n<thinking>用户在做综述</thinking>"
        plan, thinking, stripped = WritingRunHooks._extract_plan_and_thinking(text)
        assert plan == "正在检索文献"
        assert thinking == "用户在做综述"
        assert stripped == "回复正文"

    def test_native_reasoning_wins_when_no_tags(self):
        """Reasoning models emit a ``ResponseReasoningItem`` in
        ``response.output`` with a ``summary[0].text`` written by the
        model. Without any tag in the text, that summary becomes the
        plan card's ``desc``."""
        # Fake the SDK's nested shape: ReasoningItem → raw_item ResponseReasoningItem
        reasoning_raw = SimpleNamespace(
            type="reasoning",
            summary=[SimpleNamespace(text="用户问医学术语,用中文做科普概览", type="summary_text")],
            content=[SimpleNamespace(text="...long trace...", type="reasoning_text")],
        )
        reasoning_item = SimpleNamespace(raw_item=reasoning_raw)
        response = SimpleNamespace(output=[reasoning_item])
        summary = WritingRunHooks._extract_reasoning_summary(response)
        assert summary == "用户问医学术语,用中文做科普概览"

    def test_native_reasoning_falls_back_to_content_when_no_summary(self):
        """Some reasoning items only populate ``content`` (no
        summary). Truncate to 120 chars."""
        reasoning_raw = SimpleNamespace(
            type="reasoning",
            summary=[],
            content=[SimpleNamespace(text="A" * 200, type="reasoning_text")],
        )
        response = SimpleNamespace(output=[SimpleNamespace(raw_item=reasoning_raw)])
        summary = WritingRunHooks._extract_reasoning_summary(response)
        assert len(summary) == 120
        assert summary == "A" * 120

    def test_no_reasoning_item_returns_empty(self):
        """Non-reasoning model → no ResponseReasoningItem → empty
        summary, caller falls through to the static label."""
        response = SimpleNamespace(output=[
            SimpleNamespace(raw_item=SimpleNamespace(type="message", content=[]))
        ])
        assert WritingRunHooks._extract_reasoning_summary(response) == ""

    def test_static_fallback_label_updated_to_思考完成(self):
        """When the LLM emits no plan/thinking/reasoning, the card's
        ``desc`` falls back to ``("助手", "正在思考", "思考完成")`` —
        no longer "已完成" (which read like a writing-only artefact)."""
        queue: asyncio.Queue = asyncio.Queue()
        hooks = WritingRunHooks(queue=queue, agent_label="general_writing")
        hooks.plan_updates.append({
            "id": "step_0_start",
            "reason": "...",
            "startedAt": 0,
            "status": "done",   # terminal
            "tool": "WritingManager",
            # No llm_plan recorded → static label takes over.
        })
        cards = hooks._v2_plan_tasks()
        assert cards[0]["title"] == "助手"
        assert cards[0]["desc"] == "思考完成"

    def test_back_compat_alias_returns_plan_or_thinking(self):
        """``_extract_and_strip_plan_tag`` still works for callers /
        tests that haven't migrated to ``_extract_plan_and_thinking``,
        collapsing the two fields into one with plan precedence."""
        # plan only
        p, _ = WritingRunHooks._extract_and_strip_plan_tag(
            "x\n<plan>a</plan>"
        )
        assert p == "a"
        # thinking only
        p, _ = WritingRunHooks._extract_and_strip_plan_tag(
            "x\n<thinking>b</thinking>"
        )
        assert p == "b"
        # both → plan wins
        p, _ = WritingRunHooks._extract_and_strip_plan_tag(
            "x\n<plan>a</plan>\n<thinking>b</thinking>"
        )
        assert p == "a"

    def test_truncate_at_plan_start_handles_thinking_tag(self):
        """Streaming-time helper: cut before ``<thinking>`` too."""
        cumulative = "Reply text\n<thinking>正在思"
        assert WritingRunHooks._truncate_at_plan_start(cumulative) == "Reply text"

    def test_truncate_picks_earliest_of_plan_or_thinking(self):
        """If both opening tags exist (rare), cut at whichever appears
        first so all subsequent in-flight content is dropped."""
        cumulative = "x<plan>a</plan>y<thinking>b</thinking>z"
        assert WritingRunHooks._truncate_at_plan_start(cumulative) == "x"
