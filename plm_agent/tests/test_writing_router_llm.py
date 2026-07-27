# -*- coding: utf-8 -*-
"""Unit tests for ``agent.writing.router_llm.select_skills_via_llm``.

The adapter is a thin wrapper around the lite_llm Haiku singleton. We don't
exercise Vertex; we monkeypatch ``VertexClaude45Haiku.generate`` and verify
the adapter forwards args correctly and returns the model's text verbatim.
"""

import asyncio

import pytest


def test_adapter_returns_text_verbatim(monkeypatch):
    captured = {}

    async def _fake_generate(self, *, input, sys_prompt=None, **kwargs):
        captured["input"] = input
        captured["sys_prompt"] = sys_prompt
        captured["kwargs"] = kwargs
        return '{"skills": ["blueprint"], "reasoning": "ok"}'

    from lite_llm.vertex_claude import VertexClaude45Haiku
    monkeypatch.setattr(VertexClaude45Haiku, "generate", _fake_generate)

    from agent.writing.router_llm import select_skills_via_llm

    out = asyncio.run(select_skills_via_llm(
        model="claude-haiku-4-5", prompt="Pick skills for: 'hi'",
    ))
    assert out == '{"skills": ["blueprint"], "reasoning": "ok"}'
    # Adapter passes the prompt as the only user message.
    assert captured["input"] == [
        {"role": "user", "content": "Pick skills for: 'hi'"},
    ]
    # PreRunRouter folds the system part into the user prompt template, so
    # we don't need a system message — but the underlying ``generate`` rejects
    # ``None`` (Vertex Anthropic API constraint), so we must pass empty string.
    assert captured["sys_prompt"] == ""
    # Sanity: temperature must be deterministic for a routing decision.
    assert captured["kwargs"]["temperature"] == 0.0
    # Cap output to keep the request cheap.
    assert captured["kwargs"]["max_output_tokens"] == 512


def test_adapter_handles_empty_response(monkeypatch):
    """An empty/None LLM response should map to empty string (router will fall back)."""

    async def _fake_generate(self, *, input, sys_prompt=None, **kwargs):
        return None

    from lite_llm.vertex_claude import VertexClaude45Haiku
    monkeypatch.setattr(VertexClaude45Haiku, "generate", _fake_generate)

    from agent.writing.router_llm import select_skills_via_llm
    out = asyncio.run(select_skills_via_llm(model="x", prompt="y"))
    assert out == ""


def test_adapter_propagates_llm_exception(monkeypatch):
    """LLM errors must propagate so PreRunRouter can fall back to its plan."""

    async def _fake_generate(self, *, input, sys_prompt=None, **kwargs):
        raise RuntimeError("vertex unavailable")

    from lite_llm.vertex_claude import VertexClaude45Haiku
    monkeypatch.setattr(VertexClaude45Haiku, "generate", _fake_generate)

    from agent.writing.router_llm import select_skills_via_llm
    with pytest.raises(RuntimeError, match="vertex unavailable"):
        asyncio.run(select_skills_via_llm(model="x", prompt="y"))
