# -*- coding: utf-8 -*-
"""Unit tests for ``ConfirmationModule`` (proactive + reactive paths)."""

import asyncio

import pytest

from agent.modules import _state_store
from agent.modules.confirmation.module import (
    ConfirmationArgs,
    ConfirmationModule,
)


@pytest.fixture(autouse=True)
def _reset_state_cache():
    _state_store._cache.clear()
    yield
    _state_store._cache.clear()


def _drain(gen):
    async def _go():
        return [item async for item in gen]
    return asyncio.run(_go())


# ----------------------------------------------------------------------
# Tool schema
# ----------------------------------------------------------------------


class TestToolSchema:
    def test_schema_function_name(self):
        sch = ConfirmationModule.tool_schema()
        assert sch is not None
        assert sch["function"]["name"] == "ask_confirmation"

    def test_schema_describes_args(self):
        sch = ConfirmationModule.tool_schema()
        params = sch["function"]["parameters"]
        assert "rewrite" in params["properties"]
        assert "rewrite" in params["required"]


# ----------------------------------------------------------------------
# Proactive run
# ----------------------------------------------------------------------


class TestProactiveRun:
    def test_emits_card_frame_with_confirm_and_revision_actions(self):
        m = ConfirmationModule()
        body = {"user_prompt": "帮我写", "thread_id": "t1"}
        state = {}
        args = ConfirmationArgs(
            rewrite="撰写一篇关于 mRNA 疫苗的医学综述（面向研究生，3000 字）",
            rationale="原请求过于宽泛",
        )
        frames = _drain(m.run(body, state, args))
        assert len(frames) == 1
        env = frames[0]["event_v2"]
        assert env["op"] == "add"
        # Awaiting user click on confirm / revision.
        assert env["task_status"] == "feedback"
        v = env["value"]
        assert v["content"]["type"] == "executeCard"
        # Card body text is empty; the rewrite shows up in meta_data.desc
        # and the per-step summaries.
        assert v["content"]["text"] == ""
        assert "mRNA" in v["meta_data"]["desc"]
        assert v["meta_data"]["frame_type"] == "ver"
        # Two-button row: confirm (primary) + revision (default).
        assert [a["model"] for a in v["actions"]] == ["confirm", "revision"]
        assert v["actions"][0]["type"] == "primary"
        assert v["actions"][1]["type"] == "default"
        # Extra meta keys carried through.
        assert v["meta_data"]["rewrite"].startswith("撰写")
        assert v["meta_data"]["rationale"] == "原请求过于宽泛"
        assert v["meta_data"]["skip_allowed"] is True
        assert state["awaiting_user"] is True
        assert state["rewrite"].startswith("撰写")
        assert state["original_query"] == "帮我写"

    def test_empty_rewrite_rejected_by_schema(self):
        # Empty ``rewrite`` is rejected at the Pydantic boundary so the router
        # pipeline never reaches ``run()`` with an unusable card body. The
        # in-method defensive guard was removed in favour of this contract.
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ConfirmationArgs(rewrite="", rationale="")


# ----------------------------------------------------------------------
# Proactive consume_reply (type='module_reply')
# ----------------------------------------------------------------------


class TestProactiveReply:
    def _state_with_pending(self):
        return {
            "original_query": "帮我写",
            "rewrite": "撰写一篇 mRNA 综述",
            "awaiting_user": True,
            "rounds": [],
            "pending": {"task_id": "t-1", "rewrite": "撰写一篇 mRNA 综述"},
        }

    def test_approve_uses_rewrite(self):
        m = ConfirmationModule()
        state = self._state_with_pending()
        body = {
            "type": "module_reply",
            "module": "confirmation",
            "thread_id": "t1",
            "feedback": "",
            "approve": True,
            "skip": False,
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["done"] is True
        assert state["accepted_rewrite"] == "撰写一篇 mRNA 综述"
        env = frames[0]["event_v2"]
        assert env["op"] == "replace"
        assert env["value"]["meta_data"]["accepted"] == "撰写一篇 mRNA 综述"

    def test_feedback_overrides_rewrite(self):
        m = ConfirmationModule()
        state = self._state_with_pending()
        body = {
            "type": "module_reply",
            "module": "confirmation",
            "thread_id": "t1",
            "feedback": "撰写 mRNA 综述（限 2000 字）",
            "approve": False,
            "skip": False,
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["accepted_rewrite"] == "撰写 mRNA 综述（限 2000 字）"
        assert state["done"] is True
        env = frames[0]["event_v2"]
        assert env["value"]["meta_data"]["accepted"] == "撰写 mRNA 综述（限 2000 字）"

    def test_skip_falls_back_to_original(self):
        m = ConfirmationModule()
        state = self._state_with_pending()
        body = {
            "type": "module_reply",
            "module": "confirmation",
            "thread_id": "t1",
            "feedback": "",
            "approve": False,
            "skip": True,
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["skipped"] is True
        assert state["done"] is True
        assert state["accepted_rewrite"] == "帮我写"
        assert frames[0]["event_v2"]["value"]["meta_data"]["skipped"] is True

    def test_invalid_reply_reasks(self):
        m = ConfirmationModule()
        state = self._state_with_pending()
        body = {
            "type": "module_reply",
            "module": "confirmation",
            "thread_id": "t1",
            "feedback": "",
            "approve": False,
            "skip": False,
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["awaiting_user"] is True
        assert state.get("done") is not True
        assert frames[0]["event_v2"]["value"]["meta_data"]["invalid_input"] is True


# ----------------------------------------------------------------------
# Reactive (type='edit')
# ----------------------------------------------------------------------


class TestReactiveEdit:
    def test_edit_appends_and_acks(self):
        m = ConfirmationModule()
        state = {}
        body = {
            "type": "edit",
            "thread_id": "t1",
            "event_id": "evt-42",
            "feedback": "把第二段改成更口语化",
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["edits"] == [{"event_id": "evt-42",
                                    "feedback": "把第二段改成更口语化"}]
        assert state["done"] is True
        assert state["awaiting_user"] is False
        env = frames[0]["event_v2"]
        assert env["op"] == "replace"
        assert env["value"]["status"] == "success"
        assert env["value"]["meta_data"]["ack"] is True
        assert env["value"]["meta_data"]["event_id"] == "evt-42"
        assert env["value"]["meta_data"]["edits_count"] == 1

    def test_multiple_edits_accumulate(self):
        m = ConfirmationModule()
        state = {}
        for i in range(3):
            body = {
                "type": "edit",
                "thread_id": "t1",
                "event_id": f"evt-{i}",
                "feedback": f"edit-{i}",
            }
            _drain(m.consume_reply(body, state))
            # Reset done/awaiting_user so consume_reply runs again
            state["done"] = False
        assert len(state["edits"]) == 3
        assert state["edits"][2]["feedback"] == "edit-2"

    def test_empty_feedback_still_completes(self):
        m = ConfirmationModule()
        state = {}
        body = {
            "type": "edit",
            "thread_id": "t1",
            "event_id": "evt-1",
            "feedback": "",
        }
        frames = _drain(m.consume_reply(body, state))
        # Empty feedback shouldn't append, but still acks done.
        assert state.get("edits", []) == []
        assert state["done"] is True
        assert frames[0]["event_v2"]["value"]["meta_data"]["edits_count"] == 0


# ----------------------------------------------------------------------
# enrich_prompt
# ----------------------------------------------------------------------


class TestEnrichPrompt:
    def test_uses_accepted_rewrite_when_available(self):
        m = ConfirmationModule()
        body = {"user_prompt": "帮我写"}
        state = {
            "original_query": "帮我写",
            "accepted_rewrite": "撰写一篇 mRNA 综述（3000 字）",
        }
        new = m.enrich_prompt(body, state)
        assert new["user_prompt"] == "撰写一篇 mRNA 综述（3000 字）"

    def test_uses_original_when_skipped(self):
        m = ConfirmationModule()
        body = {}  # reply path: no user_prompt
        state = {
            "original_query": "帮我写",
            "rewrite": "撰写一篇 mRNA 综述",
            "skipped": True,
            "accepted_rewrite": "帮我写",
        }
        new = m.enrich_prompt(body, state)
        assert new["user_prompt"] == "帮我写"

    def test_appends_edits_block(self):
        m = ConfirmationModule()
        body = {"user_prompt": "帮我写"}
        state = {
            "original_query": "帮我写",
            "accepted_rewrite": "撰写一篇 mRNA 综述",
            "edits": [
                {"event_id": "e1", "feedback": "把第二段改口语化"},
                {"event_id": "e2", "feedback": "加一段安全性"},
            ],
        }
        new = m.enrich_prompt(body, state)
        assert new["user_prompt"].startswith("撰写一篇 mRNA 综述")
        assert "[用户编辑补充]" in new["user_prompt"]
        assert "把第二段改口语化" in new["user_prompt"]
        assert "加一段安全性" in new["user_prompt"]

    def test_reactive_only_no_rewrite_falls_back_to_original(self):
        m = ConfirmationModule()
        body = {"user_prompt": "帮我写综述"}
        state = {
            "original_query": "帮我写综述",
            "edits": [{"event_id": "e1", "feedback": "改一下"}],
        }
        new = m.enrich_prompt(body, state)
        assert "帮我写综述" in new["user_prompt"]
        assert "[用户编辑补充]" in new["user_prompt"]
