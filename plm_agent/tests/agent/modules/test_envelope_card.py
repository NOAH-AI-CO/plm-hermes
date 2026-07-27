# -*- coding: utf-8 -*-
"""Unit tests for the card-protocol builders in ``agent.modules._v2_envelope``."""

from agent.modules._v2_envelope import (
    TASK_STATUS_FEEDBACK,
    TASK_STATUS_OUTLINE,
    build_add_envelope,
    build_card_value,
    make_action,
    make_step,
)


class TestConstants:
    def test_new_task_status_values(self):
        assert TASK_STATUS_FEEDBACK == "feedback"
        assert TASK_STATUS_OUTLINE == "outline"


class TestMakeStep:
    def test_defaults(self):
        s = make_step(0, "step_1", title="Foo")
        assert s == {
            "index": 0,
            "id": "step_1",
            "title": "Foo",
            "status": "loading",
            "summary": "",
        }

    def test_full(self):
        s = make_step(2, "x", title="t", status="success", summary="sum")
        assert s["status"] == "success"
        assert s["summary"] == "sum"


class TestMakeAction:
    def test_defaults(self):
        a = make_action(0, "confirm", "OK")
        assert a == {
            "index": 0,
            "model": "confirm",
            "text": "OK",
            "type": "default",
            "disabled": False,
        }

    def test_primary_disabled(self):
        a = make_action(1, "revision", "改", type_="primary", disabled=True)
        assert a["type"] == "primary"
        assert a["disabled"] is True


class TestBuildCardValue:
    def test_minimal(self):
        value = build_card_value(
            task_id="t1", msg_id="m1", thread_id="th1", title="Hello",
        )
        # Content discriminator
        assert value["content"] == {"type": "executeCard", "text": ""}
        # All six standard meta fields populated with defaults
        assert value["meta_data"]["title"] == "Hello"
        assert value["meta_data"]["desc"] == ""
        assert value["meta_data"]["open"] is False
        assert value["meta_data"]["frame_type"] == "ver"
        assert value["meta_data"]["priority"] == "p1"
        assert value["meta_data"]["steps"] == []
        # actions is at value top level, not under meta_data
        assert value["actions"] == []
        assert "actions" not in value["meta_data"]

    def test_full(self):
        steps = [make_step(0, "s1", title="x")]
        actions = [make_action(0, "confirm", "OK", type_="primary")]
        value = build_card_value(
            task_id="t", msg_id="m", thread_id="th",
            title="T", desc="D", frame_type="linkCard",
            priority="p0", open_=True, steps=steps, actions=actions,
            status="ready", index=3,
            extra_meta={"round": 2, "module": "clarification"},
        )
        md = value["meta_data"]
        assert md["frame_type"] == "linkCard"
        assert md["priority"] == "p0"
        assert md["open"] is True
        assert md["steps"] == steps
        # extra_meta survives alongside the standard six
        assert md["round"] == 2
        assert md["module"] == "clarification"
        # actions at top level
        assert value["actions"] == actions
        # standard MessageItem fields propagated
        assert value["index"] == 3
        assert value["status"] == "ready"
        assert value["sender"] == "assistant"

    def test_envelope_carries_task_status_feedback(self):
        """The envelope wrapper must let callers set task_status=feedback."""
        value = build_card_value(
            task_id="t", msg_id="m", thread_id="th",
            title="Question",
            actions=[make_action(0, "clarification", "A")],
        )
        env = build_add_envelope(value, task_status=TASK_STATUS_FEEDBACK)
        assert env["event_v2"]["task_status"] == "feedback"
        assert env["event_v2"]["value"]["actions"][0]["model"] == "clarification"
