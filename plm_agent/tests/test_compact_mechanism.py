# -*- coding: utf-8 -*-
"""
Tests for MindSearchAgentV3 passive compact mechanism.
Verifies:
1. azure_openai provider routes to _compact_via_responses_api
2. responses.compact() failure falls back to _compact_via_summarization
3. context_length_exceeded exception triggers _compact_history_messages
"""
import asyncio
import sys
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub heavy transitive imports that require GCP credentials / network access.
# ---------------------------------------------------------------------------

def _ensure_stub(name: str):
    if name not in sys.modules:
        mod = MagicMock()
        mod.__name__ = name
        mod.__path__ = []
        sys.modules[name] = mod


# llm chain: composite_models -> ali_models -> deepseek_models -> gcp_models (google.auth)
_ensure_stub('llm.gcp_models')
_ensure_stub('llm.deepseek_models')
_ensure_stub('llm.ali_models')
_ensure_stub('llm.openai_models')
_ensure_stub('llm.composite_models')

# lite_llm -> google.genai
_ensure_stub('lite_llm')
_ensure_stub('lite_llm.aliyun_models')
_ensure_stub('lite_llm.google_models')

for _mod in [
    'agent.knowledge.summary',
    'agent.bp.pp',
    'agent.iit.gl_toc_builder',
    'utils.citation.citation_generator',
    'utils.scholar',
    'utils.web_search',
    'utils.core.prompt_fetcher',
    'utils.pubmed_opt.pubmed_reader',
    'utils.sensitive_check.diting',
    'utils.utils.attachment',
    'utils.tokenizer',
    'logging_config',
    'tools.sandbox',
    'tools.sandbox.cloud_executor',
    'tools.sandbox.agentrun_sandbox',
    'tools.sandbox.skill_manager',
    'tools.explore.mindsearch_tools_v3',
    'tools.explore.attachment_tools',
]:
    _ensure_stub(_mod)

from agent.explore.mindsearch_agent_v3 import MindSearchAgentV3  # noqa: E402


def _make_agent():
    """Create a bare MindSearchAgentV3 with mocked sub-agents."""
    instance = object.__new__(MindSearchAgentV3)
    # Initialize Pydantic internals that __new__ skips
    instance.__pydantic_fields_set__ = set()
    instance.__pydantic_extra__ = None
    instance.__pydantic_private__ = None
    instance.__dict__['__pydantic_fields_set__'] = set()

    # Mock thinking_agent: llm field is a class, llm() returns an instance
    mock_llm_instance = MagicMock()
    mock_llm_instance.provider = 'azure_openai'
    mock_llm_instance.compact = AsyncMock()

    mock_llm_class = MagicMock(return_value=mock_llm_instance)

    thinking_agent = MagicMock()
    thinking_agent.llm = mock_llm_class
    thinking_agent.sys_prompt = "test system prompt"
    instance.__dict__['thinking_agent'] = thinking_agent

    # Mock compact_agent
    instance.__dict__['compact_agent'] = MagicMock()

    # Defaults used by _compact_via_summarization and _thinking
    instance.__dict__['compact_max_item_tokens'] = 150000
    instance.__dict__['proactive_compact_threshold'] = 100000
    instance.__dict__['max_thinking_rounds'] = 6
    instance.__dict__['retry_sleep_timespan'] = 0
    instance.__dict__['agentrun_sandbox_executor'] = None

    return instance


def test_compact_routes_to_responses_api():
    """azure_openai provider -> _compact_via_responses_api -> thinking_llm.compact()."""
    agent = _make_agent()

    history_messages = [
        {'role': 'user', 'content': 'original question'},
        {'role': 'assistant', 'content': 'long response...'},
    ]
    runtime_info = {
        'llm_response': [{'response': MagicMock(), 'function_calling_results': []}],
        'last_step_hms_length': 1,
    }

    compacted_output = [{'type': 'message', 'content': 'compacted'}]
    thinking_llm = agent.thinking_agent.llm()
    thinking_llm.compact.return_value = compacted_output

    asyncio.run(agent._compact_history_messages(history_messages, 'test question', runtime_info))

    # compact() was called with correct instructions
    thinking_llm.compact.assert_awaited_once()
    call_kwargs = thinking_llm.compact.call_args
    assert call_kwargs.kwargs['instructions'] == "test system prompt"

    # history_messages replaced with compacted output
    assert history_messages == compacted_output

    # llm_response cleared, last_step_hms_length updated
    assert runtime_info['llm_response'] == []
    assert runtime_info['last_step_hms_length'] == len(compacted_output)


def test_compact_fallback_to_summarization():
    """When responses.compact() raises, should fall back to _compact_via_summarization."""
    agent = _make_agent()

    thinking_llm = agent.thinking_agent.llm()
    thinking_llm.compact.side_effect = Exception("compact API unavailable")

    summary_text = "This is a summary of the conversation"

    async def mock_stream_call(user_prompt, messages):
        for word in summary_text.split():
            yield word + " "

    agent.compact_agent.stream_call = mock_stream_call

    # Build runtime_info with 2 entries (summarization slices fc_results[:-2] / [-2:])
    mock_response = MagicMock()
    mock_output_item = MagicMock()
    mock_output_item.model_dump_json.return_value = '{"type":"message","content":"test"}'
    mock_response.output = [mock_output_item]

    history_messages = [
        {'role': 'user', 'content': 'original question'},
        {'role': 'assistant', 'content': 'thinking response'},
    ]
    runtime_info = {
        'llm_response': [
            {'response': mock_response, 'function_calling_results': {'tool': 'result1'}},
            {'response': mock_response, 'function_calling_results': {'tool': 'result2'}},
        ],
        'last_step_hms_length': 1,
    }

    # tokenizer.openai() returns a token list; len() is called on the result
    tokenizer_mod = sys.modules['utils.tokenizer']
    tokenizer_mod.tokenizer.openai.return_value = [0] * 100  # 100 tokens (under limit)

    asyncio.run(agent._compact_history_messages(history_messages, 'test question', runtime_info))

    # Fallback path replaces history_messages
    assert len(history_messages) > 0
    # llm_response must be cleared
    assert runtime_info['llm_response'] == []


def test_compact_triggered_on_context_exceeded():
    """context_length_exceeded in _thinking loop triggers _compact_history_messages."""
    import openai
    agent = _make_agent()

    async def run():
        with patch.object(agent, '_compact_history_messages', new_callable=AsyncMock) as mock_compact, \
             patch.object(agent, '_execute_thinking', new_callable=AsyncMock) as mock_execute:

            error = openai.APIError(
                message="context length exceeded",
                request=MagicMock(),
                body={'code': 'context_length_exceeded'},
            )
            error.code = 'context_length_exceeded'
            mock_execute.side_effect = [error, (0, True)]

            from agent.explore.schema import MindSearchResponse
            response = MindSearchResponse()
            runtime_info = {
                'llm_response': [],
                'last_step_hms_length': 0,
                'tool_results': [],
            }
            history_messages = [{'role': 'user', 'content': 'test'}]

            await agent._thinking(response, runtime_info, 'test', history_messages)

            mock_compact.assert_awaited_once()

    asyncio.run(run())


def test_proactive_compact_triggered():
    """Proactive compaction triggers when token estimate exceeds threshold."""
    agent = _make_agent()
    agent.__dict__['proactive_compact_threshold'] = 100  # Low threshold for testing

    async def run():
        with patch.object(agent, '_compact_history_messages', new_callable=AsyncMock) as mock_compact, \
             patch.object(agent, '_execute_thinking', new_callable=AsyncMock) as mock_execute, \
             patch.object(agent, '_estimate_history_tokens', return_value=150) as mock_estimate, \
             patch.object(agent, '_age_history_content') as mock_age:

            # First call: not finished, tokens over threshold -> compact
            # Second call: finished
            mock_execute.side_effect = [(2, False), (0, True)]

            from agent.explore.schema import MindSearchResponse
            response = MindSearchResponse()
            runtime_info = {
                'llm_response': [],
                'last_step_hms_length': 0,
                'tool_results': [],
            }
            history_messages = [{'role': 'user', 'content': 'test'}]

            await agent._thinking(response, runtime_info, 'test', history_messages)

            mock_age.assert_called()
            mock_estimate.assert_called()
            mock_compact.assert_awaited_once()

    asyncio.run(run())


def _make_fake_final_output(actions):
    """
    Build an async-generator function for _final_output.
    actions: list where each element is either Exception or list[str] chunks.
    """
    state = {"idx": 0}

    async def fake_final_output(user_prompt, history_messages, runtime_info, background, language):
        action = actions[state["idx"]]
        state["idx"] += 1
        if isinstance(action, Exception):
            raise action
        for chunk in action:
            yield chunk

    return fake_final_output


def test_final_output_timeout_first_retry_then_success():
    """First timeout waits+retries, then returns chunks successfully."""
    agent = _make_agent()
    original_llm = MagicMock(name="OriginalFinalOutputLLM")
    agent.__dict__['final_output_agent'] = MagicMock(llm=original_llm)
    agent.__dict__['_final_output'] = _make_fake_final_output([
        httpx.ReadTimeout("first timeout"),
        ["ok-chunk"],
    ])

    async def run():
        with patch('agent.explore.mindsearch_agent_v3.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            out = []
            async for chunk in agent._final_output_with_compact(
                user_prompt='u',
                history_messages=[],
                runtime_info={},
                background='',
                language='en',
            ):
                out.append(chunk)
            assert out == ["ok-chunk"]
            mock_sleep.assert_awaited_once_with(15)
            assert agent.final_output_agent.llm is original_llm

    asyncio.run(run())


def test_final_output_timeout_second_retry_switch_to_gpt5nano_then_success():
    """Second timeout switches model to GPT5Nano before retrying."""
    from llm.azure_models import GPT5Nano

    agent = _make_agent()
    agent.__dict__['final_output_agent'] = MagicMock(llm=MagicMock(name="OriginalFinalOutputLLM"))
    agent.__dict__['_final_output'] = _make_fake_final_output([
        httpx.ReadTimeout("timeout-1"),
        httpx.ReadTimeout("timeout-2"),
        ["ok-after-switch"],
    ])

    async def run():
        with patch('agent.explore.mindsearch_agent_v3.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            out = []
            async for chunk in agent._final_output_with_compact(
                user_prompt='u',
                history_messages=[],
                runtime_info={},
                background='',
                language='en',
            ):
                out.append(chunk)
            assert out == ["ok-after-switch"]
            assert mock_sleep.await_count == 2
            assert agent.final_output_agent.llm is GPT5Nano

    asyncio.run(run())


def test_final_output_timeout_exhausted_raises():
    """Timeout on all retries should raise instead of being swallowed."""
    from llm.azure_models import GPT5Nano

    agent = _make_agent()
    agent.__dict__['final_output_agent'] = MagicMock(llm=MagicMock(name="OriginalFinalOutputLLM"))
    agent.__dict__['_final_output'] = _make_fake_final_output([
        httpx.ReadTimeout("timeout-1"),
        httpx.ReadTimeout("timeout-2"),
        httpx.ReadTimeout("timeout-3"),
    ])

    async def run():
        with patch('agent.explore.mindsearch_agent_v3.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx.ReadTimeout):
                async for _ in agent._final_output_with_compact(
                    user_prompt='u',
                    history_messages=[],
                    runtime_info={},
                    background='',
                    language='en',
                ):
                    pass
            # first+second attempt wait; third attempt raises directly
            assert mock_sleep.await_count == 2
            assert agent.final_output_agent.llm is GPT5Nano

    asyncio.run(run())


def test_proactive_compact_skipped_under_threshold():
    """Proactive compaction does NOT trigger when token estimate is under threshold."""
    agent = _make_agent()
    agent.__dict__['proactive_compact_threshold'] = 100000

    async def run():
        with patch.object(agent, '_compact_history_messages', new_callable=AsyncMock) as mock_compact, \
             patch.object(agent, '_execute_thinking', new_callable=AsyncMock) as mock_execute, \
             patch.object(agent, '_estimate_history_tokens', return_value=5000) as mock_estimate, \
             patch.object(agent, '_age_history_content') as mock_age:

            # First call: not finished, tokens under threshold -> no compact
            # Second call: finished
            mock_execute.side_effect = [(2, False), (0, True)]

            from agent.explore.schema import MindSearchResponse
            response = MindSearchResponse()
            runtime_info = {
                'llm_response': [],
                'last_step_hms_length': 0,
                'tool_results': [],
            }
            history_messages = [{'role': 'user', 'content': 'test'}]

            await agent._thinking(response, runtime_info, 'test', history_messages)

            mock_age.assert_called()
            mock_estimate.assert_called()
            mock_compact.assert_not_awaited()

    asyncio.run(run())


def test_age_history_content():
    """_age_history_content truncates older function_call_output entries."""
    agent = _make_agent()

    # Build history with 5 function_call_output entries of varying sizes
    history_messages = []
    for i in range(5):
        history_messages.append({
            'type': 'function_call_output',
            'call_id': f'call_{i}',
            'output': 'x' * 30000,  # 30k chars each
        })

    agent._age_history_content(history_messages, preserve_last_n=2)

    # Last 2 (index 3, 4) should be preserved (distance 0, 1)
    assert len(history_messages[4]['output']) == 30000
    assert len(history_messages[3]['output']) == 30000

    # Index 2: distance=2, limit=20000 -> truncated
    assert len(history_messages[2]['output']) < 30000
    assert '...truncated' in history_messages[2]['output']

    # Index 1: distance=3, limit=20000 -> truncated
    assert len(history_messages[1]['output']) < 30000

    # Index 0: distance=4, limit=5000 -> aggressively truncated
    assert len(history_messages[0]['output']) < 10000


def test_age_history_content_preserves_non_fc_messages():
    """_age_history_content does not modify non-function_call_output messages."""
    agent = _make_agent()

    history_messages = [
        {'role': 'user', 'content': 'x' * 50000},
        {'type': 'function_call_output', 'call_id': 'c1', 'output': 'y' * 30000},
        {'role': 'assistant', 'content': 'z' * 50000},
        {'type': 'function_call_output', 'call_id': 'c2', 'output': 'w' * 30000},
        {'type': 'function_call_output', 'call_id': 'c3', 'output': 'v' * 30000},
    ]

    agent._age_history_content(history_messages, preserve_last_n=2)

    # User and assistant messages untouched
    assert len(history_messages[0]['content']) == 50000
    assert len(history_messages[2]['content']) == 50000

    # First fc_output (distance=2) should be truncated
    assert len(history_messages[1]['output']) < 30000

    # Last 2 fc_outputs preserved
    assert len(history_messages[3]['output']) == 30000
    assert len(history_messages[4]['output']) == 30000
