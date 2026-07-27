# -*- coding: utf-8 -*-
"""Unit tests for the writing module's ``@function_tool`` wrappers.

Covers:
- ``ALL_TOOLS`` membership and names.
- Generated JSON schemas (argument names + required / types sanity).
- Guardrail wiring (step 15): ``run_in_sandbox`` has the size output
  guardrail; ``attachment_download`` has the URL-count input guardrail.
"""

import pytest

from agent.writing.guardrails import (
    sandbox_output_size_guardrail,
    url_count_guardrail,
)
from agent.writing.tools import (
    ALL_TOOLS,
    attachment_download,
    literature_pool,
    project_search,
    pubmed_search,
    run_in_sandbox,
)


EXPECTED_TOOL_NAMES = {
    "run_in_sandbox",
    "project_search",
    "literature_pool",
    "pubmed_search",
    "attachment_download",
}


class TestAllToolsRegistry:
    def test_five_tools_registered(self):
        assert len(ALL_TOOLS) == 5

    def test_tool_names_match(self):
        names = {t.name for t in ALL_TOOLS}
        assert names == EXPECTED_TOOL_NAMES

    def test_each_tool_has_description(self):
        for t in ALL_TOOLS:
            assert isinstance(t.description, str) and len(t.description) > 10


class TestToolSchemas:
    @pytest.mark.parametrize("tool,expected_args", [
        (run_in_sandbox, {"command", "timeout"}),
        (project_search, {"keywords", "start_year", "end_year", "project_types", "codes", "top_k"}),
        (literature_pool, {"keywords", "years", "max_papers"}),
        (pubmed_search, {"pubmed_query", "years", "size"}),
        (attachment_download, {"urls", "explanation"}),
    ])
    def test_parameter_names(self, tool, expected_args):
        props = set(tool.params_json_schema.get("properties", {}).keys())
        # ``ctx`` (RunContextWrapper) is stripped by @function_tool — it must
        # NOT appear in the model-visible schema.
        assert "ctx" not in props
        assert expected_args <= props, f"missing args: {expected_args - props}"

    def test_run_in_sandbox_requires_command(self):
        required = run_in_sandbox.params_json_schema.get("required", [])
        assert "command" in required

    def test_attachment_download_requires_urls(self):
        required = attachment_download.params_json_schema.get("required", [])
        assert "urls" in required


class TestGuardrailWiring:
    def test_run_in_sandbox_has_output_size_guardrail(self):
        guards = run_in_sandbox.tool_output_guardrails or []
        assert len(guards) == 1
        assert guards[0] is sandbox_output_size_guardrail

    def test_run_in_sandbox_has_no_input_guardrail(self):
        assert not (run_in_sandbox.tool_input_guardrails or [])

    def test_attachment_download_has_url_count_guardrail(self):
        guards = attachment_download.tool_input_guardrails or []
        assert len(guards) == 1
        assert guards[0] is url_count_guardrail

    def test_attachment_download_has_no_output_guardrail(self):
        assert not (attachment_download.tool_output_guardrails or [])

    @pytest.mark.parametrize("tool", [project_search, literature_pool, pubmed_search])
    def test_data_tools_have_no_guardrails(self, tool):
        assert not (tool.tool_input_guardrails or [])
        assert not (tool.tool_output_guardrails or [])
