# -*- coding: utf-8 -*-
"""``WritingAgent`` — the router-facing entry point for the writing module.

Pipeline:

    1. Build ``WritingContext`` (sandbox manager + correlation IDs + api base).
    2. Spin up the sandbox (session-scoped by ``thread_id`` for NAS persistence).
    3. Construct a single manager ``Agent`` with:
       - ``model`` from ``build_default_model()``
       - ``instructions`` = ``skills/AGENTS.md`` + selected sub-skills
       - ``tools`` = the five ``@function_tool`` wrappers
    4. Run ``Runner.run`` inside a task while ``WritingRunHooks`` push
       SSE dicts onto a queue.
    5. Yield queue items until ``DONE_SENTINEL``.

Matches the router contract (``async def start(**body)`` yielding dicts),
so it can plug into ``agent_routing["general_writing"]``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional

from config import api_config
from utils.core.standardize import standardize_yield

from agent.writing.context import (
    PHASE_CITATION,
    PHASE_LANDSCAPE,
    PHASE_LITERATURE,
    PHASE_PLANNING,
    PHASE_WRITING,
    WritingContext,
)
from agent.modules._v2_envelope import (
    TASK_STATUS_FAILED,
    build_add_envelope,
    build_message_value,
    iso_now,
    new_msg_id,
)
from agent.writing.guardrails import empty_input_guardrail, empty_output_guardrail
from agent.writing.hooks import DONE_SENTINEL, WritingRunHooks
from agent.writing.model import build_default_model
from agent.writing.session import BackendSession
from agent.writing.tools import ALL_TOOLS

logger = logging.getLogger(__name__)


BASE_INSTRUCTIONS_FILENAME = "AGENTS.md"

# Full skill set — used as PreRunRouter fallback to preserve the
# pre-routing "all-specialists-on" behavior whenever the LLM-based skill
# selection fails (timeout, parse error, etc.).
_FULL_FALLBACK_SKILLS: List[str] = [
    "attachment", "search",
    "blueprint", "writing", "landscape-analysis", "literature-analysis",
    "citation",
]


def _default_api_base_url() -> str:
    """Base URL for ``writing_data_router`` endpoints.

    Read from ``api.json`` (``NOAH_AGENT_PUBLIC_URL``); the sandbox uses
    this via ``$API_BASE_URL`` to reach ``/api/writing/*`` over the public
    internet (sandbox runs in cloud, cannot reach loopback). Callers can
    still override per request by passing ``api_base_url`` in the body.
    """
    try:
        return api_config.NOAH_AGENT_PUBLIC_URL
    except Exception:
        return "http://localhost:8013"


# ----------------------------------------------------------------------
# Skill loader — minimal, reads SKILL.md files as plain text.
# ----------------------------------------------------------------------


_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


@lru_cache(maxsize=None)
def _load_skill_text(name: str) -> str:
    """Load a single skill markdown. Returns empty string if missing.

    Cached per-name — skills are static files at deploy time, and this is
    on the hot path of every ``WritingAgent.start`` invocation.
    """
    path = _SKILLS_DIR / name
    if path.is_dir():
        path = path / "SKILL.md"
    elif not path.suffix:
        path = path.with_suffix(".md")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("[WritingAgent] skill not found: %s", path)
        return ""
    except Exception as e:
        logger.warning("[WritingAgent] skill load failed %s: %s", path, e)
        return ""


# Short phase-specific directive appended to the manager's base instructions.
# Kept tiny so the bulk of the prompt stays static and cacheable.
_PHASE_DIRECTIVE = {
    PHASE_PLANNING: (
        "You are currently in the **planning** phase. Produce or refine the "
        "Blueprint before any section writing. Avoid calling ``write_section`` "
        "until the plan is in ``.memory/task_plan.md``."
    ),
    PHASE_WRITING: (
        "You are currently in the **writing** phase. A plan exists in "
        "``.memory/task_plan.md``. Dispatch ``write_section`` per outline item; "
        "do NOT call ``plan_writing`` again unless the user changes the scope."
    ),
    PHASE_LANDSCAPE: (
        "You are currently running a **landscape survey**. Hold off on drafting "
        "sections until the survey completes."
    ),
    PHASE_LITERATURE: (
        "You are currently running a **literature deep-read**. Wait for the "
        "analysis before drafting dependent sections."
    ),
    PHASE_CITATION: (
        "You are currently in the **citation** phase; the citation specialist "
        "owns the final deliverable."
    ),
}


def _make_instructions_callable(base: str):
    """Return a dynamic ``instructions=`` callable for ``Agent``.

    SDK re-invokes this each run-loop iteration, so any update to
    ``ctx.context.current_phase`` (written by hooks on agent_start /
    handoff) flows through on the next turn.
    """

    def _instructions(run_context, agent):
        phase = getattr(getattr(run_context, "context", None), "current_phase", None)
        directive = _PHASE_DIRECTIVE.get(phase or "")
        if directive:
            return f"{base}\n\n---\n\n{directive}\n"
        return base

    return _instructions


# Tool-visibility gates live with the SkillSpec registration in
# ``agent/writing/__init__.py`` (e.g. ``_plan_writing_is_enabled``) so the
# builder can pass them through to ``.as_tool(is_enabled=...)`` without this
# module needing to know about specific gates.


# ----------------------------------------------------------------------
# WritingAgent
# ----------------------------------------------------------------------


class WritingAgent:
    """Router-compatible wrapper around a single ``openai-agents`` manager Agent."""

    def __init__(self, **body):
        self.body = body
        # Body often has nested "params" dict (router convention).
        self._params = body.get("params") or {}

    @standardize_yield
    async def start(
        self,
        user_prompt: str = "",
        history_messages: Optional[List[dict]] = None,
        images: Optional[List[str]] = None,
        thread_id: str = "",
        **kwargs,
    ) -> AsyncGenerator[dict, None]:
        """Run the writing agent and stream SSE-shaped events.

        Matches ``AgentPreset.start`` protocol: yields dicts that the
        ``standardize_yield`` decorator will serialize to JSON + newline
        for the FastAPI ``StreamingResponse``.
        """
        # -------- Imports scoped into start() so construction is cheap --------
        from agents import RunConfig, Runner

        # Replace the SDK's default OpenAI-platform uploader with a local
        # processor that writes spans into ``logs/agent.log`` and inherits
        # the correlation id from ``log_id_var`` via the log filter.
        from agent.writing.tracing_processor import install_local_tracing_processor
        install_local_tracing_processor()

        # -------- Resolve thread_id, correlation_id, api_base_url --------
        thread_id = (
            thread_id
            or self.body.get("thread_id")
            or self._params.get("thread_id")
            or ""
        )
        correlation_id = (
            self.body.get("correlation_id")
            or self._params.get("correlation_id")
            or ""
        )
        api_base_url = (
            self.body.get("api_base_url")
            or self._params.get("api_base_url")
            or _default_api_base_url()
        )
        # v1-style parent Task UUID propagated from Backend; modules use it
        # to fill in ``MessageItem.task_id`` so envelopes carry both task_id
        # (parent) and msg_id (per-message merge key).
        parent_task_id = self.body.get("task_id") or self._params.get("task_id") or ""

        # User-question echo is sent by Backend's ``_get_agent_input``
        # (Backend/API/chat.py — right after the v2 snapshot seed) so the
        # frontend renders the user bubble before this HTTP roundtrip
        # finishes. ``WritingRunHooks(start_index=1)`` continues to
        # reserve index 0 for that user MessageItem.

        # v2 identity (Backend Django proxy injects these alongside thread_id;
        # see Backend/API/chat.py::_get_agent_input). Optional — when missing,
        # the sandbox falls back to the legacy single-tenant path.
        env = self.body.get("env") or self._params.get("env")
        user_id = self.body.get("user_id") or self._params.get("user_id")
        workspace_paths = None
        if env and user_id and thread_id:
            try:
                from agent.runtime.paths import WorkspacePaths
                workspace_paths = WorkspacePaths(
                    env=env, user_id=str(user_id), session_id=thread_id,
                )
            except ValueError as e:
                logger.warning(
                    "[WritingAgent] invalid env/user_id (%s); "
                    "using legacy sandbox path", e,
                )

        # -------- Sandbox manager (shared across tools in this run) --------
        from tools.sandbox.sandbox_manager import SandboxManager

        if workspace_paths is not None:
            sandbox_manager = SandboxManager(workspace_paths=workspace_paths)
        else:
            sandbox_manager = SandboxManager(session_id=thread_id or None)

        ctx = WritingContext(
            sandbox_manager=sandbox_manager,
            thread_id=thread_id,
            correlation_id=correlation_id,
            api_base_url=api_base_url,
        )

        # -------- Queue & hooks --------
        chat_id = (
            self.body.get("chat_id")
            or self._params.get("chat_id")
            or kwargs.get("chat_id")
            or ""
        )
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        # Backend's WSConsumer seeds the user MessageItem at ``index=0`` (see
        # ``API/chat.py::_get_agent_input`` user-seed block). Hooks therefore
        # start indexing at 1 to avoid colliding with the user bubble.
        hooks = WritingRunHooks(
            queue=queue,
            agent_label="general_writing",
            thread_id=thread_id,
            sandbox_manager=sandbox_manager,
            chat_id=chat_id,
            start_index=1,
            task_id=parent_task_id,
        )

        # -------- Build the manager Agent (model first, manager built below) --------
        try:
            model = build_default_model()
        except Exception as e:
            logger.error("[WritingAgent] failed to build model: %s", e)
            err_text = f"模型初始化失败: {e}"
            err_msg_id = new_msg_id()
            err_value = build_message_value(
                task_id=parent_task_id,
                msg_id=err_msg_id,
                thread_id=thread_id,
                content_type="error",
                text=err_text,
                sender="system",
                status="error",
                index=hooks._alloc_index(),
                end_time=iso_now(),
            )
            # Cannot use ``hooks.emit_error`` here — the queue drain loop
            # below hasn't started yet, so anything pushed to the queue
            # would be lost. Yield directly with the same envelope shape.
            yield {
                "agent": "general_writing",
                "type": "chat",
                "sender": "assistant",
                "message": err_text,
                "id": "error-0",
                "thread_id": thread_id,
                "startedAt": 0,
                "save": True,
                **build_add_envelope(err_value, TASK_STATUS_FAILED),
            }
            return

        # -------- Pre-flight skill selection (PreRunRouter) --------
        # The router is a small Haiku call that picks the minimal skill
        # subset for this request, so we don't pay the token cost of all
        # specialists on every turn. Fallback = full plan, so any router
        # failure (timeout / parse error) gracefully degrades to the
        # pre-routing behavior.
        from agent.runtime.builder import build_agent_from_plan
        from agent.runtime.registry import get_registry
        from agent.runtime.router import (
            CapabilityPlan,
            PreRunRouter,
            RouterConfig,
        )
        from agent.writing.router_llm import select_skills_via_llm

        router = PreRunRouter(
            registry=get_registry(),
            config=RouterConfig(
                model="claude-haiku-4-5",
                llm_call=select_skills_via_llm,
                timeout_s=6.0,
                # 7 skills are registered (attachment, search, blueprint,
                # writing, landscape-analysis, literature-analysis, citation).
                # The cap matches so the router can pick all of them when the
                # request truly needs it; lower would silently drop a skill.
                max_skills=len(_FULL_FALLBACK_SKILLS),
                fallback_plan=CapabilityPlan(
                    skills=list(_FULL_FALLBACK_SKILLS),
                    reasoning="fallback: full plan",
                ),
            ),
        )
        plan = await router.select(
            agent_name="general_writing",
            user_prompt=user_prompt,
            history=history_messages,
            current_phase=getattr(ctx, "current_phase", None),
        )
        logger.info(
            "[WritingAgent] PreRunRouter plan=%s reason=%r",
            plan.skills, plan.reasoning,
        )

        # -------- Build the manager Agent from the plan --------
        # ``base_instructions`` = AGENTS.md only. PROMPT_SKILL bodies
        # (``search``, ``attachment``) are appended by ``build_agent_from_plan``
        # when the router selects them, so we don't double-load any skill.
        # ``base_tools`` = the four ``@function_tool`` wrappers — always
        # available regardless of plan, since they're foundational.
        base_instructions = _load_skill_text(BASE_INSTRUCTIONS_FILENAME)
        manager_agent = build_agent_from_plan(
            agent_name="WritingManager",
            plan=plan,
            context=ctx,
            base_instructions=base_instructions,
            base_tools=list(ALL_TOOLS),
            model=model,
            input_guardrails=[empty_input_guardrail],
            output_guardrails=[empty_output_guardrail],
        )

        # Re-wrap instructions with the phase-aware callable so per-turn
        # phase directives still flow through (hooks update
        # ``ctx.current_phase`` mid-run; the SDK re-invokes the callable
        # each iteration).
        manager_agent = manager_agent.clone(
            instructions=_make_instructions_callable(manager_agent.instructions),
        )

        # -------- Build the input + SDK Session --------
        # Prior turns go through ``BackendSession.get_items()`` (SDK native).
        # Only the current user prompt is passed as ``input``.
        session = BackendSession(
            session_id=thread_id or "default",
            history_messages=history_messages,
        )
        input_items: list[Any] = []
        if user_prompt:
            input_items.append({"role": "user", "content": user_prompt})
        if not input_items and not history_messages:
            err_text = "请提供写作任务描述。"
            err_msg_id = new_msg_id()
            err_value = build_message_value(
                task_id=parent_task_id,
                msg_id=err_msg_id,
                thread_id=thread_id,
                content_type="error",
                text=err_text,
                sender="system",
                status="error",
                index=hooks._alloc_index(),
                end_time=iso_now(),
            )
            yield {
                "agent": "general_writing",
                "type": "chat",
                "sender": "system",
                "message": err_text,
                "id": "error-0",
                "thread_id": thread_id,
                "startedAt": 0,
                "save": True,
                **build_add_envelope(err_value, TASK_STATUS_FAILED),
            }
            return

        # -------- Ensure sandbox is alive before running --------
        try:
            await sandbox_manager.ensure_sandbox()
        except Exception as e:
            logger.warning("[WritingAgent] sandbox init failed: %s", e)
            # Continue anyway — non-sandbox tools (search APIs) still work.

        # -------- Run Runner.run_streamed; stream token deltas + hook events --------
        # Hooks push planUpdate / statusUpdate / final chat onto the queue.
        # Raw response events give us token-by-token deltas for a true
        # streaming UX; we forward only text deltas (save=False) and let
        # on_llm_end commit the assistant message (save=True).
        async def _run_and_signal() -> None:
            terminal_status = "ok"
            terminal_reason: Optional[str] = None
            try:
                result = Runner.run_streamed(
                    manager_agent,
                    input=input_items,
                    context=ctx,
                    hooks=hooks,
                    session=session,
                    run_config=RunConfig(),
                    max_turns=20,
                )
                async for event in result.stream_events():
                    if event.type == "raw_response_event":
                        await hooks.handle_raw_response(event.data)
            except asyncio.CancelledError:
                # External cancel (client disconnect, server shutdown). Mark
                # the stream as interrupted so Backend distinguishes this
                # from a clean exit, then re-raise to honor cancellation.
                terminal_status = "interrupted"
                terminal_reason = "cancelled"
                raise
            except Exception as e:
                logger.error("[WritingAgent] Runner.run_streamed failed: %s", e)
                logger.error(traceback.format_exc())
                terminal_status = "error"
                terminal_reason = str(e)
                await hooks.emit_error(f"执行失败: {e}")
            finally:
                # signal_done is best-effort under cancel — it uses
                # ``put_nowait`` internally so a re-cancel can't deadlock it.
                try:
                    await hooks.signal_done(
                        status=terminal_status, reason=terminal_reason,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[WritingAgent] signal_done failed: %s "
                        "(Backend will see 'no stream_end' → Interrupted)", e,
                    )

        runner_task = asyncio.create_task(_run_and_signal())

        try:
            while True:
                event = await queue.get()
                if event is DONE_SENTINEL or event.get("__done__"):
                    break
                yield event
        finally:
            if not runner_task.done():
                runner_task.cancel()
                try:
                    # Wait for the runner to enter its own finally block, where
                    # ``signal_done`` pushes stream_end + DONE_SENTINEL onto the
                    # queue. Without awaiting here we'd race the runner and lose
                    # its terminal frame.
                    await runner_task
                except (asyncio.CancelledError, Exception):
                    pass
            # Best-effort drain of anything the runner pushed during its
            # finalisation (notably the stream_end frame). If the HTTP
            # consumer is still listening, these frames reach Backend and
            # let it write a clean terminal task_status. If the consumer is
            # gone, ``yield`` raises and we fall through to sandbox close —
            # that's the expected best-effort behaviour, no log spam.
            while True:
                try:
                    event = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if event is DONE_SENTINEL or event.get("__done__"):
                    break
                try:
                    yield event
                except (GeneratorExit, asyncio.CancelledError, Exception):
                    break

            try:
                await sandbox_manager.close()
            except Exception as e:
                logger.warning("[WritingAgent] sandbox close failed: %s", e)
