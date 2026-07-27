# -*- coding: utf-8 -*-
"""Integration tests for the openai-agents SDK against Azure Foundry.

This test suite answers three questions about using the `openai-agents`
library with this project's Azure OpenAI deployment (keys from api.json):

  1. Does the SDK import and instantiate correctly? (T1 — no network)
  2. Which API path works on our Azure endpoint — Responses or
     Chat Completions? (T2, T3)
  3. Do the core agent features the writing module will depend on
     (function tools, multi-tool selection, structured output,
     streaming, handoffs, error propagation) work on Azure? (T4–T9)

Run:
    pytest tests/test_openai_agents_sdk.py -v
        # only T1 runs; T2–T9 are skipped (no Azure round-trips)

    RUN_AGENTS_SDK_INTEGRATION=1 pytest tests/test_openai_agents_sdk.py -v
        # all tests run against real Azure (~$0.01 of gpt-5-mini tokens)
"""
import asyncio
import os

import pytest

# Skip the whole module if the SDK isn't installed in this env.
agents = pytest.importorskip("agents")
openai_pkg = pytest.importorskip("openai")

from agents import (
    Agent,
    Runner,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncAzureOpenAI


INTEGRATION_FLAG = "RUN_AGENTS_SDK_INTEGRATION"
needs_azure = pytest.mark.skipif(
    os.environ.get(INTEGRATION_FLAG) != "1",
    reason=f"Set {INTEGRATION_FLAG}=1 to run Azure integration tests",
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def azure_config():
    """Read Azure Foundry config from api.json via the project's api_config."""
    from config import api_config
    return {
        "api_key": api_config.AZURE_GPT4_OPENAI_API_KEY,
        "api_version": api_config.AZURE_GPT5_VERSION,
        "endpoint": api_config.AZURE_GPT4_AZURE_ENDPOINT,
        "deployment": api_config.AZURE_GPT5_MIN_DEPLOYMENT,
    }


@pytest.fixture(scope="session")
def azure_client(azure_config):
    return AsyncAzureOpenAI(
        api_key=azure_config["api_key"],
        api_version=azure_config["api_version"],
        azure_endpoint=azure_config["endpoint"],
    )


@pytest.fixture(autouse=True)
def _disable_tracing():
    # OpenAI's tracing uploads to platform.openai.com — irrelevant for Azure
    # and noisy in local runs.
    set_tracing_disabled(True)


def _chat_model(azure_client, deployment: str) -> OpenAIChatCompletionsModel:
    return OpenAIChatCompletionsModel(model=deployment, openai_client=azure_client)


def _responses_model(azure_client, deployment: str) -> OpenAIResponsesModel:
    return OpenAIResponsesModel(model=deployment, openai_client=azure_client)


# --------------------------------------------------------------------------- #
# T1: Local-only — no network                                                 #
# --------------------------------------------------------------------------- #

class TestImportAndSetup:
    def test_sdk_symbols_present(self):
        for name in (
            "Agent", "Runner", "function_tool",
            "OpenAIChatCompletionsModel", "OpenAIResponsesModel",
            "set_default_openai_client", "set_default_openai_api",
            "set_tracing_disabled",
        ):
            assert hasattr(agents, name), f"agents.{name} missing"

    def test_azure_config_present(self, azure_config):
        assert azure_config["api_key"], "AZURE_GPT4_OPENAI_API_KEY is empty"
        assert azure_config["endpoint"].startswith("https://"), \
            f"endpoint looks wrong: {azure_config['endpoint']!r}"
        assert azure_config["deployment"], "AZURE_GPT5_MIN_DEPLOYMENT is empty"
        assert azure_config["api_version"], "AZURE_GPT5_VERSION is empty"

    def test_azure_client_construction(self, azure_client):
        assert isinstance(azure_client, AsyncAzureOpenAI)

    def test_agent_can_be_built_without_network(self, azure_client, azure_config):
        agent = Agent(
            name="Offline",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions="noop",
        )
        assert agent.name == "Offline"
        assert agent.model is not None


# --------------------------------------------------------------------------- #
# T2: Responses API — does Azure accept /v1/responses?                        #
# --------------------------------------------------------------------------- #

@needs_azure
class TestResponsesAPI:
    def test_basic_run(self, azure_client, azure_config):
        agent = Agent(
            name="Smoke",
            model=_responses_model(azure_client, azure_config["deployment"]),
            instructions="Reply with exactly one word: pong",
        )
        try:
            result = Runner.run_sync(agent, "ping")
        except Exception as exc:
            pytest.fail(
                "Responses API failed on Azure Foundry.\n"
                f"  endpoint:   {azure_config['endpoint']}\n"
                f"  deployment: {azure_config['deployment']}\n"
                f"  error:      {type(exc).__name__}: {exc}\n"
                "If this is a 404/InvalidEndpoint, fall back to Chat Completions "
                "(see TestChatCompletionsAPI)."
            )
        assert "pong" in result.final_output.lower(), \
            f"unexpected output: {result.final_output!r}"


# --------------------------------------------------------------------------- #
# T3: Chat Completions fallback — guaranteed path                             #
# --------------------------------------------------------------------------- #

@needs_azure
class TestChatCompletionsAPI:
    def test_basic_run(self, azure_client, azure_config):
        agent = Agent(
            name="Smoke",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions="Reply with exactly one word: pong",
        )
        result = Runner.run_sync(agent, "ping")
        assert "pong" in result.final_output.lower(), \
            f"unexpected output: {result.final_output!r}"


# --------------------------------------------------------------------------- #
# T4: @function_tool gets invoked with the right arg                          #
# --------------------------------------------------------------------------- #

@needs_azure
class TestFunctionTool:
    def test_invocation(self, azure_client, azure_config):
        calls: list[str] = []

        @function_tool
        def echo(msg: str) -> str:
            """Return the provided message unchanged."""
            calls.append(msg)
            return msg

        agent = Agent(
            name="Echo",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "You must call the `echo` tool exactly once with the "
                "argument msg='hello', then reply with whatever it returns."
            ),
            tools=[echo],
        )
        result = Runner.run_sync(agent, "Run the tool.")
        assert calls, f"echo was never called. final_output={result.final_output!r}"
        assert any("hello" in c.lower() for c in calls), \
            f"echo called with wrong args: {calls!r}"


# --------------------------------------------------------------------------- #
# T5: LLM picks the right tool out of several                                 #
# --------------------------------------------------------------------------- #

@needs_azure
class TestMultiToolSelection:
    def test_picks_weather_for_weather_question(self, azure_client, azure_config):
        weather_calls: list[str] = []
        math_calls: list[tuple[int, int]] = []

        @function_tool
        def get_weather(city: str) -> str:
            """Return the current weather for a given city."""
            weather_calls.append(city)
            return f"sunny in {city}"

        @function_tool
        def add(a: int, b: int) -> int:
            """Add two integers together."""
            math_calls.append((a, b))
            return a + b

        agent = Agent(
            name="Router",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "Use `get_weather` for weather questions and `add` for math. "
                "Call exactly one tool."
            ),
            tools=[get_weather, add],
        )
        Runner.run_sync(agent, "What's the weather in Tokyo?")
        assert weather_calls, f"weather tool not called; math_calls={math_calls}"
        assert not math_calls, f"math tool should not have been called: {math_calls}"


# --------------------------------------------------------------------------- #
# T6: Structured output via a Pydantic model                                  #
# --------------------------------------------------------------------------- #

@needs_azure
class TestStructuredOutput:
    def test_pydantic_output_type(self, azure_client, azure_config):
        from pydantic import BaseModel

        class Outline(BaseModel):
            title: str
            sections: list[str]

        agent = Agent(
            name="Outliner",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "Produce a short article outline. "
                "Return a title and at least 2 section headings."
            ),
            output_type=Outline,
        )
        result = Runner.run_sync(agent, "Topic: common side effects of aspirin")
        assert isinstance(result.final_output, Outline), \
            f"expected Outline, got {type(result.final_output).__name__}"
        assert result.final_output.title.strip()
        assert len(result.final_output.sections) >= 2


# --------------------------------------------------------------------------- #
# T7: Streaming events                                                        #
# --------------------------------------------------------------------------- #

@needs_azure
class TestStreaming:
    def test_stream_events(self, azure_client, azure_config):
        agent = Agent(
            name="Streamer",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions="Reply with exactly: one two three",
        )

        async def drain():
            stream = Runner.run_streamed(agent, "go")
            count = 0
            async for _ in stream.stream_events():
                count += 1
            return count, stream.final_output

        event_count, final_output = asyncio.run(drain())
        assert event_count > 0, "no streaming events received"
        assert final_output, "final_output empty after stream finished"


# --------------------------------------------------------------------------- #
# T8: Handoff from one agent to another                                       #
# --------------------------------------------------------------------------- #

@needs_azure
class TestHandoff:
    def test_between_agents(self, azure_client, azure_config):
        model = _chat_model(azure_client, azure_config["deployment"])

        polisher = Agent(
            name="Polisher",
            model=model,
            instructions=(
                "Respond with the single word 'HELLO' in all uppercase, "
                "with no extra words."
            ),
        )
        drafter = Agent(
            name="Drafter",
            model=model,
            instructions=(
                "Immediately hand off to the Polisher agent. "
                "Do not produce any output yourself."
            ),
            handoffs=[polisher],
        )
        result = Runner.run_sync(drafter, "start")
        assert result.last_agent.name == "Polisher", \
            f"handoff did not occur; ended at {result.last_agent.name}"
        assert "HELLO" in result.final_output.upper()


# --------------------------------------------------------------------------- #
# T9: Invalid deployment name surfaces an exception                           #
# --------------------------------------------------------------------------- #

@needs_azure
class TestInvalidModel:
    def test_bogus_deployment_raises(self, azure_client):
        agent = Agent(
            name="Bad",
            model=_chat_model(azure_client, "nonexistent-deployment-xyz-abc"),
            instructions="anything",
        )
        with pytest.raises(Exception):
            Runner.run_sync(agent, "hello")


# --------------------------------------------------------------------------- #
# T10-T11: AgentRun cloud sandbox integration                                 #
# --------------------------------------------------------------------------- #
# These verify the other half of the writing-module stack: an SDK Agent       #
# wraps AgentRun (Alibaba Cloud) as a function_tool and successfully          #
# delegates compute/shell work to it.                                         #
#                                                                             #
# T10 uses the low-level AgentRunSandboxClient.execute_shell primitive —      #
# a single shell round-trip. Fast and cheap.                                  #
# T11 uses the full AgentRunSandboxExecutor.execute (multi-step Claude loop   #
# inside the sandbox) — what a real writing sub-task would look like. Slow.   #
#                                                                             #
# Both need AgentRun credentials in api.json (ALIYUN_ACCESS_KEY /             #
# ALIYUN_ACCESS_SECRET / ALIYUN_SANDBOX_API_KEY) and network access to        #
# Alibaba Cloud.                                                              #

try:  # noqa: SIM105 — keep the import optional for envs without agentrun-sdk
    import agentrun  # type: ignore  # noqa: F401
    _HAS_AGENTRUN = True
except ImportError:
    _HAS_AGENTRUN = False

needs_agentrun = pytest.mark.skipif(
    not _HAS_AGENTRUN,
    reason="agentrun-sdk not installed; sandbox tests cannot run",
)


@needs_azure
@needs_agentrun
class TestAgentRunSandboxIntegration:
    def test_sdk_agent_calls_sandbox_shell(self, azure_client, azure_config):
        """SDK Agent uses a function_tool that wraps AgentRunSandboxClient.execute_shell."""
        from tools.sandbox.agentrun_sandbox import AgentRunSandboxClient

        sandbox = AgentRunSandboxClient()
        shell_calls: list[str] = []

        @function_tool
        async def run_in_cloud_sandbox(command: str) -> str:
            """Run a shell command inside the AgentRun cloud sandbox.

            Returns a short summary including stdout and exit_code.
            Use this whenever you need to execute shell commands
            or interrogate a Linux environment.
            """
            shell_calls.append(command)
            result = await sandbox.execute_shell(command)
            stdout = (result.get("stdout") or "").strip()
            return (
                f"exit_code={result.get('exit_code')} "
                f"stdout={stdout[:500]}"
            )

        agent = Agent(
            name="SandboxCaller",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "You have a `run_in_cloud_sandbox` tool that executes shell "
                "commands in a Linux sandbox. Call it exactly once with the "
                "command `uname -s` and then state what operating system "
                "family the sandbox runs, based on the tool's stdout."
            ),
            tools=[run_in_cloud_sandbox],
        )

        try:
            result = Runner.run_sync(agent, "Please check the sandbox OS.")
        finally:
            asyncio.run(sandbox.close())

        assert shell_calls, "sandbox shell tool was never called by the agent"
        assert any("uname" in c.lower() for c in shell_calls), \
            f"unexpected shell commands: {shell_calls!r}"
        assert "linux" in result.final_output.lower(), \
            f"agent final output did not mention Linux: {result.final_output!r}"

    def test_sdk_agent_delegates_full_executor(self, azure_client, azure_config):
        """SDK Agent delegates a compute task to AgentRunSandboxExecutor (full loop).

        This is the closer-to-production pattern: the SDK agent doesn't
        micro-manage the sandbox — it hands off a whole sub-task to the
        AgentRun executor, which runs its own Claude-driven shell/python loop.
        """
        import uuid as _uuid
        from tools.sandbox.cloud_executor import AgentRunSandboxExecutor

        session_id = f"sdk-test-{_uuid.uuid4().hex[:8]}"
        executor = AgentRunSandboxExecutor(session_id=session_id)
        delegated_tasks: list[str] = []

        @function_tool
        async def compute_in_sandbox(task: str) -> str:
            """Delegate a multi-step compute or analysis task to the AgentRun
            cloud sandbox executor. Use this for anything that requires
            running Python or shell commands to produce a result.
            """
            delegated_tasks.append(task)
            return await executor.execute(task=task)

        agent = Agent(
            name="WritingModuleStub",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "You have a `compute_in_sandbox` tool for any task that "
                "requires code execution. Call it with a concise task "
                "description, then quote the result verbatim as your final "
                "answer."
            ),
            tools=[compute_in_sandbox],
        )

        try:
            result = Runner.run_sync(
                agent,
                "Use the sandbox to compute the number of characters in the "
                "word 'immunotherapy' and return just the number.",
            )
        finally:
            asyncio.run(executor.sandbox_client.close())

        assert delegated_tasks, "sandbox executor was never invoked"
        # The word 'immunotherapy' has 13 characters.
        assert "13" in result.final_output, \
            f"expected '13' in final output, got {result.final_output!r}"


# --------------------------------------------------------------------------- #
# POC: Use the SDK's NATIVE SandboxAgent path, not function_tool               #
# --------------------------------------------------------------------------- #
# This proves (or refutes) that AgentRun can be plugged into the SDK as a     #
# native sandbox backend, so a SandboxAgent with the Shell capability runs    #
# `exec_command` calls through AgentRun instead of unix_local / docker.       #
#                                                                             #
# Minimal surface implemented:                                                #
#   - BaseSandboxClientOptions  subclass (discriminator only)                 #
#   - SandboxSessionState       subclass (adds AgentRun session_id)           #
#   - BaseSandboxClient:        create / delete / resume /                    #
#                                deserialize_session_state                    #
#   - BaseSandboxSession:       _exec_internal + no-op _start_workspace       #
#                               (snapshot/manifest application skipped)       #
#                                                                             #
# Everything else (PTY, filesystem tools, memory, skills, snapshot            #
# persistence) is intentionally left as default/no-op.                        #


@needs_azure
@needs_agentrun
class TestSandboxAgentNativeIntegration:
    """Use SDK's native SandboxAgent + custom AgentRun backend (no function_tool)."""

    def test_sandbox_agent_runs_shell_through_agentrun(self, azure_client, azure_config):
        # Imports are local so the module still loads even if the SDK's sandbox
        # submodules change shape in future versions.
        from typing import Literal

        from agents import Runner, RunConfig
        from agents.run_config import SandboxRunConfig
        from agents.sandbox.sandbox_agent import SandboxAgent
        from agents.sandbox.capabilities.shell import Shell
        from agents.sandbox.manifest import Manifest
        from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
        from agents.sandbox.session.sandbox_client import (
            BaseSandboxClient,
            BaseSandboxClientOptions,
        )
        from agents.sandbox.session.sandbox_session_state import SandboxSessionState
        from agents.sandbox.snapshot import NoopSnapshot
        from agents.sandbox.types import ExecResult

        from tools.sandbox.agentrun_sandbox import AgentRunSandboxClient

        # --- Options / state ---
        class AgentRunClientOptions(BaseSandboxClientOptions):
            type: Literal["agentrun_poc"] = "agentrun_poc"

        class AgentRunSessionState(SandboxSessionState):
            type: Literal["agentrun_poc"] = "agentrun_poc"

        # --- Session ---
        class AgentRunSession(BaseSandboxSession):
            """Minimum viable session: only `_exec_internal` is real.

            Everything that would require a snapshot/manifest application
            is short-circuited, because the AgentRun sandbox already provides
            a working filesystem of its own.
            """

            state: AgentRunSessionState

            def __init__(self, *, state: AgentRunSessionState, sandbox: AgentRunSandboxClient):
                self.state = state
                self._sandbox = sandbox
                self._running = False
                self._exec_log: list[tuple[str, ...]] = []

            async def _start_workspace(self) -> None:
                # AgentRun sandbox already has a ready workspace; no manifest apply.
                self.state.workspace_root_ready = True

            async def _after_start(self) -> None:
                self._running = True

            async def _shutdown_backend(self) -> None:
                # Actual sandbox disposal is owned by the client (see delete()).
                self._running = False

            async def running(self) -> bool:
                return self._running

            async def _exec_internal(self, *command, timeout=None) -> ExecResult:
                # The SDK wraps via `sh -lc`, so we get a single joined string.
                cmd = " ".join(str(c) for c in command)
                self._exec_log.append(tuple(str(c) for c in command))
                result = await self._sandbox.execute_shell(cmd, timeout=timeout)
                stdout = (result.get("stdout") or "").encode("utf-8", "replace")
                stderr = (result.get("stderr") or "").encode("utf-8", "replace")
                exit_code = int(result.get("exit_code") or 0)
                return ExecResult(stdout=stdout, stderr=stderr, exit_code=exit_code)

            # Shell-only POC: the capability we registered doesn't use these.
            async def read(self, path, *, user=None):
                raise NotImplementedError("filesystem read not implemented in POC")

            async def write(self, path, data, *, user=None, mode=None):
                raise NotImplementedError("filesystem write not implemented in POC")

            async def persist_workspace(self):
                raise NotImplementedError("snapshot persistence not implemented in POC")

            async def hydrate_workspace(self, data):
                raise NotImplementedError("snapshot hydration not implemented in POC")

        # --- Client ---
        class AgentRunBackendSandboxClient(BaseSandboxClient):
            backend_id = "agentrun_poc"
            supports_default_options = True

            def __init__(self) -> None:
                self._sandbox_by_session: dict[str, AgentRunSandboxClient] = {}

            async def create(self, *, snapshot=None, manifest=None, options=None):
                manifest = manifest or Manifest(root="/home/user")
                state = AgentRunSessionState(
                    manifest=manifest,
                    snapshot=NoopSnapshot(id="agentrun-poc"),
                )
                sandbox = AgentRunSandboxClient()
                self._sandbox_by_session[str(state.session_id)] = sandbox
                inner = AgentRunSession(state=state, sandbox=sandbox)
                return self._wrap_session(inner)

            async def delete(self, session):
                inner = session._inner
                key = str(inner.state.session_id)
                sandbox = self._sandbox_by_session.pop(key, None)
                if sandbox is not None:
                    await sandbox.close()
                return session

            async def resume(self, state):
                # POC: don't bother reattaching to a prior AgentRun sandbox;
                # start a fresh one each resume. Real impl would re-use state.session_id.
                sandbox = AgentRunSandboxClient()
                self._sandbox_by_session[str(state.session_id)] = sandbox
                inner = AgentRunSession(state=state, sandbox=sandbox)
                return self._wrap_session(inner)

            def deserialize_session_state(self, payload):
                return AgentRunSessionState.model_validate(payload)

        # --- Actual test ---
        client = AgentRunBackendSandboxClient()
        agent = SandboxAgent(
            name="NativeSandboxAgent",
            model=_chat_model(azure_client, azure_config["deployment"]),
            instructions=(
                "Use exec_command exactly once with the command `uname -s` "
                "and then state what operating system family the sandbox runs, "
                "based on the tool's stdout."
            ),
            # Shell-only — omit Filesystem/Compaction defaults so we don't pull
            # in tools whose backends we haven't implemented.
            capabilities=[Shell()],
        )

        run_config = RunConfig(
            sandbox=SandboxRunConfig(
                client=client,
                options=AgentRunClientOptions(),
                manifest=Manifest(root="/home/user"),
            ),
        )

        try:
            result = Runner.run_sync(
                agent, "Please check the sandbox OS.", run_config=run_config
            )
        finally:
            # Make sure we clean up whatever AgentRun sessions survived.
            for sandbox in list(client._sandbox_by_session.values()):
                asyncio.run(sandbox.close())
            client._sandbox_by_session.clear()

        assert "linux" in result.final_output.lower(), (
            f"agent final output did not mention Linux: {result.final_output!r}"
        )
