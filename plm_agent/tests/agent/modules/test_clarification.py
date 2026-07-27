# -*- coding: utf-8 -*-
"""Unit tests for ``ClarificationModule`` after the router-LLM refactor.

The module no longer runs its own LLM judgment — the router LLM picks it
and supplies the ``ClarificationArgs`` (question + options) directly.
These tests verify the state machine around ``run(args)`` /
``consume_reply`` / ``enrich_prompt``.
"""

import asyncio

import pytest

from agent.modules import _state_store
from agent.modules.clarification.module import (
    ClarificationArgs,
    ClarificationModule,
)


@pytest.fixture(autouse=True)
def _reset_state_cache():
    """Each test starts with an empty state cache."""
    _state_store._cache.clear()
    yield
    _state_store._cache.clear()


def _drain(gen):
    """Drain an async generator into a list."""
    async def _go():
        return [item async for item in gen]
    return asyncio.run(_go())


# ----------------------------------------------------------------------
# Tool schema
# ----------------------------------------------------------------------


class TestToolSchema:
    def test_schema_function_name(self):
        sch = ClarificationModule.tool_schema()
        assert sch is not None
        assert sch["function"]["name"] == "ask_clarification"
        assert "parameters" in sch["function"]

    def test_schema_describes_args(self):
        sch = ClarificationModule.tool_schema()
        params = sch["function"]["parameters"]
        # pydantic JSON schema has 'properties' for fields
        assert "question" in params["properties"]
        assert "options" in params["properties"]
        assert "question" in params["required"]
        assert "options" in params["required"]

    def test_default_args_for_force_path(self):
        defaults = ClarificationModule.default_args()
        assert isinstance(defaults, ClarificationArgs)
        assert defaults.question
        assert len(defaults.options) >= 2


# ----------------------------------------------------------------------
# run — emits a card with options as actions[]
# ----------------------------------------------------------------------


class TestRun:
    def test_emits_card_frame_with_options_as_actions(self):
        m = ClarificationModule()
        body = {"user_prompt": "帮我写综述", "thread_id": "t1"}
        state = {}
        args = ClarificationArgs(
            question="目标读者是谁？",
            options=["医生", "患者", "学生"],
        )
        frames = _drain(m.run(body, state, args))
        assert len(frames) == 1
        env = frames[0]["event_v2"]
        assert env["op"] == "add"
        # Card frames wait for user click → task_status="feedback".
        assert env["task_status"] == "feedback"
        v = env["value"]
        assert v["content"]["type"] == "executeCard"
        # Card body text is "" — the question lives in meta_data.desc and the
        # steps[] summaries. Options are rendered as actions[].
        assert v["content"]["text"] == ""
        assert v["meta_data"]["desc"] == "目标读者是谁？"
        assert v["meta_data"]["frame_type"] == "ver"
        assert v["meta_data"]["title"]
        # Options surfaced as buttons. First option is recommended (primary).
        assert [a["text"] for a in v["actions"]] == ["医生", "患者", "学生"]
        assert v["actions"][0]["type"] == "primary"
        assert v["actions"][1]["type"] == "default"
        assert all(a["model"] == "clarification" for a in v["actions"])
        # Extra meta survives.
        assert v["meta_data"]["options"] == ["医生", "患者", "学生"]
        assert v["meta_data"]["round"] == 1
        assert v["meta_data"]["skip_allowed"] is True
        # State machine unchanged.
        assert state["awaiting_user"] is True
        assert state["pending"]["q"] == "目标读者是谁？"
        assert state["original_query"] == "帮我写综述"

    def test_round_increments_with_existing_history(self):
        m = ClarificationModule()
        state = {
            "rounds": [{"q": "earlier?", "a": "yes"}],
            "original_query": "帮我写综述",
        }
        args = ClarificationArgs(question="next?", options=["a", "b"])
        frames = _drain(m.run({"user_prompt": "x", "thread_id": "t"}, state, args))
        assert frames[0]["event_v2"]["value"]["meta_data"]["round"] == 2


# ----------------------------------------------------------------------
# consume_reply
# ----------------------------------------------------------------------


class TestConsumeReply:
    def _make_state_with_pending(self):
        return {
            "original_query": "帮我写综述",
            "awaiting_user": True,
            "rounds": [],
            "pending": {
                "task_id": "task-1",
                "round": 1,
                "q": "目标期刊？",
                "options": ["JAMA", "NEJM"],
            },
        }

    def test_skip_marks_done_and_emits_replace(self):
        m = ClarificationModule()
        state = self._make_state_with_pending()
        body = {
            "module": "clarification",
            "thread_id": "t1",
            "skip": True,
            "approve": False,
            "feedback": "",
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["done"] is True
        assert state["skipped"] is True
        assert state["awaiting_user"] is False
        assert "pending" not in state
        env = frames[0]["event_v2"]
        assert env["op"] == "replace"
        assert env["value"]["status"] == "success"
        assert env["value"]["meta_data"]["skipped"] is True

    def test_invalid_reply_reasks(self):
        m = ClarificationModule()
        state = self._make_state_with_pending()
        body = {
            "module": "clarification",
            "thread_id": "t1",
            "skip": False,
            "approve": False,
            "feedback": "",
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["awaiting_user"] is True
        assert state.get("done") is not True
        assert state["rounds"] == []
        env = frames[0]["event_v2"]
        v = env["value"]
        assert v["meta_data"]["invalid_input"] is True
        # Re-ask still surfaces the options as actions (so the user keeps
        # seeing the same buttons) and stays at task_status=feedback.
        assert env["task_status"] == "feedback"
        assert v["content"]["type"] == "executeCard"
        assert [a["text"] for a in v["actions"]] == ["JAMA", "NEJM"]
        assert v["meta_data"]["desc"] == "目标期刊？"

    def test_resolved_card_has_empty_actions_and_success_status(self):
        """status=success branches (skip / answered) clear actions[] and the
        card collapses to a resolved state."""
        # Skip path
        m = ClarificationModule()
        state = self._make_state_with_pending()
        frames = _drain(m.consume_reply(
            {"module": "clarification", "thread_id": "t1", "skip": True,
             "approve": False, "feedback": ""},
            state,
        ))
        v = frames[0]["event_v2"]["value"]
        assert v["content"]["type"] == "executeCard"
        assert v["status"] == "success"
        assert v["actions"] == []

        # Answered path
        m = ClarificationModule()
        state = self._make_state_with_pending()
        frames = _drain(m.consume_reply(
            {"module": "clarification", "thread_id": "t1", "skip": False,
             "approve": True, "feedback": "JAMA"},
            state,
        ))
        v = frames[0]["event_v2"]["value"]
        assert v["content"]["type"] == "executeCard"
        assert v["status"] == "success"
        assert v["actions"] == []
        # User answer is preserved in the steps summary.
        answer_step = next(s for s in v["meta_data"]["steps"]
                           if s["id"] == "step_answer")
        assert answer_step["summary"] == "JAMA"

    def test_approve_with_feedback_records_round_and_marks_done(self):
        m = ClarificationModule()
        state = self._make_state_with_pending()
        body = {
            "module": "clarification",
            "thread_id": "t1",
            "skip": False,
            "approve": True,
            "feedback": "JAMA",
            "user_prompt": "帮我写综述",
        }
        frames = _drain(m.consume_reply(body, state))
        assert state["done"] is True
        assert state["awaiting_user"] is False
        assert state["rounds"] == [{
            "q": "目标期刊？",
            "options": ["JAMA", "NEJM"],
            "a": "JAMA",
            "approve": True,
        }]
        # The router decides whether to re-ask on the next /chat — this
        # module only emits one frame here.
        assert len(frames) == 1
        assert frames[0]["event_v2"]["op"] == "replace"

    def test_supplement_records_and_marks_done(self):
        """approve=False with feedback is recorded; the router will decide
        whether another round is needed on the next /chat."""
        m = ClarificationModule()
        state = self._make_state_with_pending()
        body = {
            "module": "clarification",
            "thread_id": "t1",
            "skip": False,
            "approve": False,
            "feedback": "想写medical综述",
            "user_prompt": "帮我写综述",
        }
        frames = _drain(m.consume_reply(body, state))
        assert len(state["rounds"]) == 1
        assert state["rounds"][0]["a"] == "想写medical综述"
        assert state["awaiting_user"] is False
        assert state["done"] is True
        assert len(frames) == 1
        assert frames[0]["event_v2"]["op"] == "replace"


# ----------------------------------------------------------------------
# enrich_prompt
# ----------------------------------------------------------------------


class TestEnrichPrompt:
    def test_appends_qa_pairs(self):
        m = ClarificationModule()
        body = {"user_prompt": "帮我写综述"}
        state = {
            "rounds": [
                {"q": "目标期刊？", "a": "JAMA"},
                {"q": "读者是谁？", "a": "医生"},
            ]
        }
        new = m.enrich_prompt(body, state)
        assert "[澄清补充]" in new["user_prompt"]
        assert "JAMA" in new["user_prompt"]
        assert "医生" in new["user_prompt"]

    def test_skipped_does_not_enrich(self):
        m = ClarificationModule()
        body = {"user_prompt": "帮我写综述"}
        state = {
            "rounds": [{"q": "Q", "a": "A"}],
            "skipped": True,
            "original_query": "帮我写综述",
        }
        new = m.enrich_prompt(body, state)
        assert new["user_prompt"] == "帮我写综述"
        assert "[澄清补充]" not in new["user_prompt"]

    def test_no_rounds_returns_body_with_user_prompt(self):
        m = ClarificationModule()
        body = {"user_prompt": "帮我写综述"}
        new = m.enrich_prompt(body, {})
        assert new["user_prompt"] == "帮我写综述"

    def test_restores_user_prompt_from_state_when_missing(self):
        """module_reply requests omit user_prompt — we recover it from state."""
        m = ClarificationModule()
        body = {"thread_id": "t1"}  # no user_prompt
        state = {
            "rounds": [{"q": "目标读者?", "a": "医生"}],
            "original_query": "帮我写综述",
        }
        new = m.enrich_prompt(body, state)
        assert new["user_prompt"].startswith("帮我写综述")
        assert "医生" in new["user_prompt"]
