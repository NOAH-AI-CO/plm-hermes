# -*- coding: utf-8 -*-
"""End-to-end integration test for the writing agent.

Skipped by default. Run with::

    pytest tests/test_writing_e2e.py --rune2e -v

What it exercises:
- ``WritingAgent.start`` construction path (model factory + specialists +
  guardrails + tracing processor wiring).
- One short live call to Azure via the openai-agents SDK.
- At least one ``planUpdate`` SSE event lands in the stream before the
  run completes.

Costs: ~1K gpt-5-mini-noah tokens per run.
"""

import asyncio
import json

import pytest

pytestmark = pytest.mark.integration


def _decode(event):
    """``@standardize_yield`` ships dicts as JSON strings + newline."""
    if isinstance(event, str):
        return json.loads(event.rstrip("\n"))
    return event


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def azure_available():
    """Fail fast with a readable error if api.json is missing writing keys."""
    from config import api_config

    for attr in (
        "AZURE_GPT4_OPENAI_API_KEY",
        "AZURE_GPT5_VERSION",
        "AZURE_GPT4_AZURE_ENDPOINT",
        "AZURE_GPT5_MIN_DEPLOYMENT",
    ):
        if not getattr(api_config, attr, None):
            pytest.fail(f"api.json missing {attr}; cannot run e2e.")


async def _collect_first_n_events(n: int, prompt: str, thread_id: str) -> list[dict]:
    from agent.writing import WritingAgent

    agent = WritingAgent(thread_id=thread_id)
    events: list[dict] = []
    gen = agent.start(user_prompt=prompt, thread_id=thread_id)
    try:
        async for ev in gen:
            events.append(_decode(ev))
            if len(events) >= n:
                break
    finally:
        await gen.aclose()
    return events


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


class TestWritingAgentE2E:
    def test_start_emits_plan_update(self, azure_available):
        """A short prompt should produce at least one SSE event with a valid shape."""
        prompt = "用一句话回答：Python 的 GIL 是什么？"
        thread_id = "test-writing-e2e-shape"
        events = asyncio.run(
            asyncio.wait_for(
                _collect_first_n_events(n=3, prompt=prompt, thread_id=thread_id),
                timeout=90,
            )
        )
        assert events, "writing agent emitted no events"
        # Every event must carry our standard envelope.
        for ev in events:
            assert ev.get("agent") == "general_writing"
            assert "type" in ev
        # Expect at least one planUpdate (from on_agent_start).
        assert any(ev.get("type") == "planUpdate" for ev in events)

    def test_empty_prompt_short_circuits(self, azure_available):
        """No prompt + no history → immediate error SSE; the Runner never starts."""
        from agent.writing import WritingAgent

        async def _run():
            agent = WritingAgent()
            events = []
            gen = agent.start(user_prompt="", history_messages=None)
            try:
                async for ev in gen:
                    events.append(_decode(ev))
            finally:
                await gen.aclose()
            return events

        events = asyncio.run(asyncio.wait_for(_run(), timeout=10))
        assert events, "no early-error event emitted"
        assert events[0]["type"] == "chat"
        assert "请提供" in events[0]["message"] or events[0]["message"]
