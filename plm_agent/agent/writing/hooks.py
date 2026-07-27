# -*- coding: utf-8 -*-
"""SDK lifecycle → SSE event translation for the writing agent.

The ``openai-agents`` Runner emits events via ``RunHooks`` callbacks.
``WritingRunHooks`` pushes translated SSE-shaped dicts onto an
``asyncio.Queue`` so ``WritingAgent.start`` can ``yield`` them while
``Runner.run`` is still executing.

SSE event shape mirrors ``agent.nsfc.v3.base`` (``planUpdate`` / ``chat``
/ ``statusUpdate`` / error) so the existing frontend renderer works.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Optional

from agents import RunContextWrapper, RunHooks
from agents.items import ItemHelpers

from agent.modules._v2_envelope import (
    TASK_STATUS_ABANDON,
    TASK_STATUS_COMPLETE,
    TASK_STATUS_FAILED,
    TASK_STATUS_OUTLINE,
    TASK_STATUS_RUNNING,
    build_add_envelope,
    build_card_value,
    build_message_value,
    build_replace_envelope,
    iso_now,
    make_step,
    new_msg_id,
)
from agent.workspace.hooks_integration import (
    reconcile_assets,
    snapshot_sandbox_files,
)
from agent.workspace.store import get_store as _get_workspace_store
from agent.writing.context import (
    PHASE_CITATION,
    PHASE_LANDSCAPE,
    PHASE_LITERATURE,
    PHASE_PLANNING,
    PHASE_WRITING,
    WritingContext,
)

logger = logging.getLogger(__name__)


# Sentinel placed on the queue to signal "no more events" to the reader.
DONE_SENTINEL: dict = {"__done__": True}


# Tools that may produce files in the sandbox workspace. Only these trigger
# pre/post-tool snapshot + OSS reconcile. Adding a new write-capable tool?
# Append it here — silently missing files in the workspace UI is harder to
# diagnose than an extra reconcile call.
_WRITE_CAPABLE_TOOL_NAMES: frozenset[str] = frozenset({
    "run_in_sandbox",
    "attachment_download",
})

# Tools known to be read-only (search APIs that return JSON). Listed
# explicitly so unknown tools fall back to "reconcile anyway" — better to
# pay an extra OSS round-trip than lose a future tool's outputs.
_KNOWN_READONLY_TOOL_NAMES: frozenset[str] = frozenset({
    "pubmed_search",
    "literature_pool",
    "project_search",
})


# Specialist name → phase label written onto WritingContext.current_phase.
# Consumed by is_enabled(ctx) and dynamic instructions to gate behaviour.
# Manager (WritingManager) keeps whatever phase was last set by a specialist.
_PHASE_BY_AGENT_NAME: dict[str, str] = {
    "BlueprintSpecialist": PHASE_PLANNING,
    "WriterSpecialist": PHASE_WRITING,
    "LandscapeSpecialist": PHASE_LANDSCAPE,
    "LiteratureAnalysisSpecialist": PHASE_LITERATURE,
    "CitationSpecialist": PHASE_CITATION,
}


# v2 PlanTask labels: tool/agent name → (title, loading_desc, success_desc).
# The frontend renders the v2 plan as a list of cards; mapping the raw
# class / function names to user-facing Chinese labels keeps the UI
# meaningful for non-engineers. Unknown names fall back to the raw value
# so the card still has *something* to show.
_V2_PLAN_LABELS: dict[str, tuple[str, str, str]] = {
    # Manager (orchestrator)
    "WritingManager": ("助手", "正在思考", "思考完成"),
    # Specialist agent class names (handoff destinations)
    "BlueprintSpecialist": ("拟定写作蓝图", "构建结构化写作计划", "蓝图已就绪"),
    "WriterSpecialist": ("撰写章节", "起草段落内容", "章节已完成"),
    "CitationSpecialist": ("引用整理", "处理引用与参考", "引用已整理"),
    "LandscapeSpecialist": ("调研研究领域", "总结领域热点与时间线", "调研已完成"),
    "LiteratureAnalysisSpecialist": ("解读论文", "提取方法、结果与局限", "解读已完成"),
    # Specialist .as_tool() names (Agents-SDK exposes the same specialist
    # under both agent class name *and* tool name depending on the call site).
    "plan_writing": ("拟定写作蓝图", "构建结构化写作计划", "蓝图已就绪"),
    "write_section": ("撰写章节", "起草段落内容", "章节已完成"),
    "survey_landscape": ("调研研究领域", "总结领域热点与时间线", "调研已完成"),
    "analyse_paper": ("解读论文", "提取方法、结果与局限", "解读已完成"),
    "render_html": ("生成 HTML 预览", "渲染当前阶段右栏内容", "预览已就绪"),
    # Function tools (writing/tools.py)
    "run_in_sandbox": ("沙箱执行", "在沙箱里运行脚本", "执行已完成"),
    "project_search": ("NSFC 项目检索", "在 NSFC 资助项目库中检索", "检索完成"),
    "literature_pool": ("文献池构建", "按影响因子拉取参考文献", "文献池已就绪"),
    "pubmed_search": ("PubMed 检索", "在 PubMed 中检索相关文献", "检索完成"),
    "attachment_download": ("附件下载与解析", "下载并解析附件", "附件已就绪"),
}


def _agent_phase(agent: Any) -> Optional[str]:
    return _PHASE_BY_AGENT_NAME.get(getattr(agent, "name", ""))


def _set_phase(context: Any, phase: Optional[str]) -> None:
    """Safely write ``current_phase`` onto the wrapped WritingContext."""
    if phase is None:
        return
    inner = getattr(context, "context", None)
    if inner is not None and hasattr(inner, "current_phase"):
        inner.current_phase = phase


class WritingRunHooks(RunHooks):
    """Translates SDK lifecycle events into SSE-ready dicts.

    Subclasses ``RunHooks`` because the SDK validates
    ``isinstance(hooks, RunHooksBase)`` before starting a run.
    """

    def __init__(
        self,
        queue: "asyncio.Queue[dict]",
        agent_label: str = "general_writing",
        thread_id: str = "",
        sandbox_manager: Any = None,
        chat_id: str = "",
        start_index: int = 0,
        task_id: str = "",
    ):
        self.queue = queue
        self.agent_label = agent_label
        self.thread_id = thread_id
        # v1-style parent Task UUID; passed by Backend in the chat body and
        # threaded into every v2 envelope this hooks instance emits.
        self.parent_task_id = task_id
        self.sandbox_manager = sandbox_manager
        self.chat_id = chat_id
        self.started_at = int(time.time())
        self.step = 0
        self.plan_updates: list[dict] = []
        # v2 cumulative streaming state — keyed by stream_id (per-step stream).
        # value: {"msg_id": uuid, "cumulative": str, "first": bool, "index": int}
        self._streams: dict[str, dict] = {}
        # Workspace asset reconciliation: track sandbox dir state across tools
        # so on_tool_end can diff against this baseline.
        self._sandbox_snapshot: set[str] = set()
        # Whether we've pushed the initial workspace snapshot frame yet.
        self._workspace_initialized = False
        # ------------------------------------------------------------------
        # v2 frame throttle (mirrors mindsearch_agent_v3.py:3367-3385)
        # ------------------------------------------------------------------
        # OpenAI streams text 10–50 ms per token, which is far too dense for
        # the front-end's overwrite render. Coalesce deltas: only emit a v2
        # frame when one of the conditions is met.
        self._v2_throttle_interval = 0.25   # seconds since last emit
        self._v2_throttle_chars = 24        # chars accumulated since last emit
        self._last_v2_emit_time = 0.0
        self._last_v2_emit_len = 0
        # Per-MessageItem index counter — every new msg_id gets the next
        # value. Same msg_id reuses its allocated index across patch/replace.
        # ``start_index`` lets the caller offset for frames emitted upstream
        # (e.g. WritingAgent yields the user-question echo at index 0 and
        # then constructs hooks with ``start_index=1``).
        self._next_index = start_index
        # Stable msg_ids for status-class frames; index allocated lazily on
        # first emit so plan/status share their slot through the run.
        self._plan_msg_id = new_msg_id()
        self._plan_index: Optional[int] = None
        self._status_msg_id = new_msg_id()
        self._status_index: Optional[int] = None
        # Envelope-level ``task_status`` (running / complete / abandon /
        # failed / error). Stays ``running`` until ``signal_done`` /
        # ``emit_error`` flips it to a terminal value. Front-end reads this
        # off every frame to lock/unlock the composer and decide whether to
        # show the cancel button. HITL pauses keep this as ``running`` —
        # the task is still alive, the HITL widget owns its own input.
        self._current_task_status: str = "running"

    def _alloc_index(self) -> int:
        """Return the next message index for a brand-new MessageItem."""
        idx = self._next_index
        self._next_index += 1
        return idx

    @staticmethod
    def _should_reconcile(tool_name: str) -> bool:
        """Decide whether ``on_tool_start``/``on_tool_end`` should run the
        sandbox snapshot + OSS reconcile pipeline for this tool.

        Conservative: only known read-only tools skip; anything else
        (including unrecognised tool names) reconciles, so a newly-added
        write-capable tool's outputs surface in the workspace by default.
        """
        if tool_name in _WRITE_CAPABLE_TOOL_NAMES:
            return True
        if tool_name in _KNOWN_READONLY_TOOL_NAMES:
            return False
        return True

    async def _put_v1_frame(
        self,
        *,
        frame_type: str,
        frame_id: str,
        envelope: dict,
        sender: str = "assistant",
        message: str = "",
        save: bool = False,
        extra_v1: Optional[dict] = None,
    ) -> None:
        """Push a v1+v2 frame onto the queue.

        v2 envelope comes from ``_v2_envelope.build_*_envelope`` — the single
        source of truth for ``event_v2`` shape. v1 wrapper keys
        (``agent``/``thread_id``/``type``/...) live here because Backend's
        chat-formatter still routes on them; ``extra_v1`` carries per-emitter
        extras (legacy ``plan`` list, ``current_tool``, etc.).
        """
        frame: dict[str, Any] = {
            "agent": self.agent_label,
            "thread_id": self.thread_id,
            "type": frame_type,
            "sender": sender,
            "message": message,
            "id": frame_id,
            "startedAt": self.started_at,
            "save": save,
            "protocol_version": 2,
            "event_v2": envelope["event_v2"],
        }
        if extra_v1:
            frame.update(extra_v1)
        await self.queue.put(frame)

    # ------------------------------------------------------------
    # SDK lifecycle hooks
    # ------------------------------------------------------------

    async def on_agent_start(self, context, agent) -> None:
        agent_name = getattr(agent, "name", "Writer")
        _set_phase(context, _agent_phase(agent))
        self.plan_updates.append({
            "id": f"step_{self.step}_start",
            "reason": f"{agent_name} 开始规划任务",
            "startedAt": int(time.time()),
            "status": "doing",
            "tool": agent_name,
        })
        await self._emit_plan(context=context)
        # Push the workspace snapshot once so the front-end has the full
        # assets/view_state/viewed_files document to merge against. Subsequent
        # mutations are op=patch frames against the same task_id.
        await self._maybe_emit_workspace_snapshot()

    async def on_agent_end(self, context, agent, output) -> None:
        if self.plan_updates and self.plan_updates[-1].get("status") == "doing":
            self.plan_updates[-1]["status"] = "done"
            self.plan_updates[-1]["reason"] = "完成"
        self.plan_updates.append({
            "id": f"step_{self.step}_end",
            "reason": "任务完成",
            "startedAt": int(time.time()),
            "status": "done",
            "tool": getattr(agent, "name", "Writer"),
        })
        # Flip envelope task_status to ``complete`` BEFORE emitting the final
        # plan frame. This way the last "real" frame Backend sees already
        # carries a terminal status — if stream_end is later lost in transit
        # (network blip, fast disconnect, etc.), Backend's
        # ``_v2_sync_envelope_task_status`` still has a terminal signal to
        # write into the Task row. ``signal_done`` will re-flip to
        # FAILED/ABANDON on error/interrupt paths (idempotent for the
        # happy-path mapping).
        if self._current_task_status == TASK_STATUS_RUNNING:
            self._current_task_status = TASK_STATUS_COMPLETE
        await self._emit_plan(save=True, context=context)
        # Final reconcile in case a tool produced a file but didn't trigger
        # on_tool_end (e.g. handoff specialist).
        await self._reconcile_workspace_assets()

    async def on_handoff(self, context, from_agent, to_agent) -> None:
        from_name = getattr(from_agent, "name", "?")
        to_name = getattr(to_agent, "name", "?")
        _set_phase(context, _agent_phase(to_agent))
        self.plan_updates.append({
            "id": f"step_{self.step}_handoff",
            "reason": f"交接至 {to_name}",
            "startedAt": int(time.time()),
            "status": "done",
            "tool": to_name,
        })
        await self._emit_plan(save=True, context=context)
        await self._emit_chat(f"交由 {to_name} 继续处理（来自 {from_name}）。")

    async def on_tool_start(self, context, agent, tool) -> None:
        # New step → cumulative buffer from the previous step is no longer
        # relevant. Clear so a new stream gets a fresh task_id and op=add first.
        self._streams.clear()
        # New stream gets a fresh throttle window (so the very first delta
        # always passes the "is_first" gate, see handle_raw_response).
        self._last_v2_emit_time = 0.0
        self._last_v2_emit_len = 0
        self.step += 1
        tool_name = getattr(tool, "name", type(tool).__name__)
        # Snapshot sandbox artifact dirs so on_tool_end can diff what's new —
        # but only for tools that may actually write files. Read-only search
        # tools never produce artifacts, so skipping their snapshot saves an
        # OSS round-trip per call (~75% of typical traffic).
        if self._should_reconcile(tool_name):
            try:
                self._sandbox_snapshot = await snapshot_sandbox_files(self.sandbox_manager)
            except Exception:
                logger.exception("[WritingHooks] sandbox snapshot failed")
                self._sandbox_snapshot = set()
        else:
            # Reset baseline so a stale snapshot from an earlier write-capable
            # tool can't accidentally seed the next one's diff.
            self._sandbox_snapshot = set()
        if self.plan_updates and self.plan_updates[-1].get("status") == "doing":
            self.plan_updates[-1]["status"] = "done"
        self.plan_updates.append({
            "id": f"step_{self.step}",
            "reason": f"调用工具: {tool_name}",
            "startedAt": int(time.time()),
            "status": "doing",
            "tool": tool_name,
        })
        await self._emit_plan(context=context)

    async def on_tool_end(self, context, agent, tool, result: str) -> None:
        tool_name = getattr(tool, "name", type(tool).__name__)
        preview = (result or "")[:120].replace("\n", " ")
        if self.plan_updates and self.plan_updates[-1].get("status") == "doing":
            self.plan_updates[-1]["status"] = "done"
            self.plan_updates[-1]["reason"] = f"{tool_name} 完成：{preview}"
        # ``render_html`` returns a full HTML document string; surface it as a
        # dedicated ``content_type="html"`` v2 frame so the front-end can
        # iframe-render it instead of letting the markdown renderer swallow
        # the tags. The result also still flows back to the manager LLM as the
        # tool's return value — both paths are independent.
        if tool_name == "render_html" and result:
            await self._emit_html(result, context)
        await self._emit_plan(save=True, context=context)
        await self._emit_status()
        # Diff sandbox dirs against the on_tool_start snapshot, upload any new
        # files to OSS, register them in the workspace store, and forward the
        # resulting v2 envelope frames to the SSE queue. Skip for read-only
        # tools (they can't have produced anything to reconcile).
        if self._should_reconcile(tool_name):
            await self._reconcile_workspace_assets()

    async def on_llm_start(
        self, context, agent, system_prompt: Optional[str], input_items: list
    ) -> None:
        # No visible event — keeps the stream tidy.
        return

    async def on_llm_end(self, context, agent, response) -> None:
        text = self._extract_response_text(response)
        # Three-tier fallback for the plan card's description:
        #   1. ``<plan>...</plan>``  — explicit writing intent
        #   2. ``<thinking>...</thinking>``  — explicit reasoning (any turn)
        #   3. ``ResponseReasoningItem.summary[0].text`` — native chain-of-
        #      thought from reasoning models (Claude extended thinking,
        #      OpenAI o-series); no prompt cooperation required
        # The static ``("助手", "正在思考", "思考完成")`` label is only
        # used when all three are empty.
        plan_text, thinking_text, stripped = self._extract_plan_and_thinking(text)
        reasoning_text = self._extract_reasoning_summary(response)
        desc = plan_text or thinking_text or reasoning_text
        if desc and self.plan_updates:
            self.plan_updates[-1]["llm_plan"] = desc
        if stripped:
            stream_key = f"{self.step}-stream-0"
            # ``flush_stream=True`` swaps the v1 ``message`` payload for ""
            # (the v2 envelope already carries the full cumulative text). Non-
            # stream chat events (handoff, errors) keep ``message`` populated.
            await self._emit_chat(stripped, stream_key=stream_key, flush_stream=True)

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        """Extract assistant text from a ModelResponse."""
        output = getattr(response, "output", None) or []
        parts: list[str] = []
        for item in output:
            txt = ItemHelpers.extract_text(item)
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_reasoning_summary(response: Any) -> str:
        """Pull a one-line summary from ``ResponseReasoningItem``(s) in
        ``response.output``.

        Reasoning models (Claude extended thinking, OpenAI o-series)
        return a ``ResponseReasoningItem`` alongside the regular message
        in their output. The agents SDK exposes ``summary`` (a model-
        written brief) and ``content`` (the full reasoning trace);
        we prefer ``summary[0].text`` and fall back to truncated
        ``content[0].text``. Empty string when no reasoning items
        exist (non-reasoning model) — caller can then fall back to
        the ``<plan>`` / ``<thinking>`` XML tag.

        Resilient against the SDK's wrapper shape (``ReasoningItem``
        wraps ``ResponseReasoningItem`` as ``raw_item``) by walking
        through ``raw_item`` when present.
        """
        output = getattr(response, "output", None) or []
        for item in output:
            raw = getattr(item, "raw_item", item)
            if getattr(raw, "type", None) != "reasoning":
                continue
            summary = getattr(raw, "summary", None) or []
            for s in summary:
                txt = (getattr(s, "text", "") or "").strip()
                if txt:
                    return txt[:120]
            content = getattr(raw, "content", None) or []
            for c in content:
                txt = (getattr(c, "text", "") or "").strip()
                if txt:
                    return txt[:120]
        return ""

    # Per AGENTS.md the LLM emits ONE of:
    #   <plan>brief action description</plan>      ← writing task intent
    #   <thinking>brief reasoning</thinking>       ← consultation / Q&A
    # at the very end of its response. Backend strips it from the
    # user-visible markdown and surfaces the content on the plan card's
    # ``desc`` (formerly hard-coded to "已完成"). Priority on the
    # consumer side: <plan> > <thinking> > native reasoning summary.
    _PLAN_TAG_RE = re.compile(r"<plan>(.*?)</plan>", re.DOTALL | re.IGNORECASE)
    _THINKING_TAG_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL | re.IGNORECASE)
    _ANY_TAG_RE = re.compile(
        r"<(?:plan|thinking)>.*?</(?:plan|thinking)>",
        re.DOTALL | re.IGNORECASE,
    )

    @classmethod
    def _extract_plan_and_thinking(cls, text: str) -> tuple[str, str, str]:
        """Pull the LAST ``<plan>`` and the LAST ``<thinking>`` tag and
        return ``(plan_text, thinking_text, stripped_text)``.

        - ``plan_text`` / ``thinking_text``: trimmed content of the
          respective tag, empty string when the tag isn't present.
        - ``stripped_text``: ``text`` with BOTH tag types removed and
          trailing whitespace cleaned up.
        """
        if not text:
            return "", "", ""
        plan_matches = cls._PLAN_TAG_RE.findall(text)
        thinking_matches = cls._THINKING_TAG_RE.findall(text)
        plan_text = (plan_matches[-1].strip() if plan_matches else "")
        thinking_text = (thinking_matches[-1].strip() if thinking_matches else "")
        stripped = cls._ANY_TAG_RE.sub("", text).rstrip()
        return plan_text, thinking_text, stripped

    @classmethod
    def _extract_and_strip_plan_tag(cls, text: str) -> tuple[str, str]:
        """Back-compat alias for the dual-tag extractor.

        Returns ``(plan_text, stripped_text)`` — collapses ``<plan>``
        and ``<thinking>`` into one field, preferring ``<plan>``. Used
        by existing tests + any caller that hasn't migrated to
        ``_extract_plan_and_thinking``.
        """
        plan_text, thinking_text, stripped = cls._extract_plan_and_thinking(text)
        return (plan_text or thinking_text), stripped

    @staticmethod
    def _truncate_at_plan_start(text: str) -> str:
        """Truncate ``text`` at the first ``<plan>`` or ``<thinking>``
        opening tag.

        Used during streaming: per AGENTS.md the LLM puts the tag at
        the END of its response, so cutting at the first occurrence of
        either drops the in-flight tag (open or closed) and any
        trailing content. Without this, users would briefly see
        ``<plan>...`` / ``<thinking>...`` flash in the chat bubble
        before the on_llm_end terminal flush replaces it.
        ``_extract_plan_and_thinking`` does the regex-based final
        cleanup.
        """
        if not text:
            return text
        candidates = [
            i for i in (text.find("<plan>"), text.find("<thinking>"))
            if i >= 0
        ]
        if not candidates:
            return text
        return text[: min(candidates)].rstrip()

    def _v2_plan_tasks(self) -> list[dict]:
        """Map ``plan_updates`` to PlanTask shape for the v2 envelope.

        Differs from the v1 ``plan`` field in two user-visible ways:

        - The synthetic ``step_X_end`` marker that ``on_agent_end`` appends
          is suppressed. For v2 each logical step is one card whose status
          transitions ``loading → success`` — completion is conveyed by the
          status flip alone, not a second card.
        - ``title`` / ``desc`` resolve via ``_V2_PLAN_LABELS`` so the user
          sees a friendly Chinese label (e.g. "撰写章节 — 起草段落内容")
          instead of the raw class / function name.

        Per spec Section 4.2.3, PlanTask uses ``start_time`` / ``end_time``
        (the same time field names as the parent MessageItem) — *not* the
        legacy ``time_created`` / ``time_finished`` from the v1 plan dict.
        """
        status_map = {"doing": "loading", "done": "success"}
        visible = [
            p for p in self.plan_updates
            if not (p.get("id") or "").endswith("_end")
        ]
        out: list[dict] = []
        for i, p in enumerate(visible):
            started = p.get("startedAt")
            start_time = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
                if isinstance(started, int) and started > 0
                else None
            )
            terminal = p.get("status") == "done"
            tool = p.get("tool") or ""
            label = _V2_PLAN_LABELS.get(tool)
            if label:
                title, loading_desc, success_desc = label
                desc = success_desc if terminal else loading_desc
            else:
                # Unknown tool/agent — keep the raw name + reason so the
                # frontend at least has readable fallback strings.
                title = tool or p.get("reason") or ""
                desc = p.get("reason", "")
            # Prefer the LLM-emitted plan (``<plan>...</plan>`` tag, see
            # AGENTS.md) over the static loading_desc/success_desc when
            # available — the LLM describes the *actual* current step,
            # not the generic phase label. Falls back to the static label
            # when the LLM didn't emit a tag this turn.
            llm_plan = p.get("llm_plan")
            if llm_plan:
                desc = llm_plan
            out.append({
                "id": p.get("id", f"task_{i}"),
                "index": i,
                "title": title,
                "desc": desc,
                "status": status_map.get(p.get("status", ""), "loading"),
                "start_time": start_time,
                "end_time": iso_now() if terminal else None,
            })
        return out

    @staticmethod
    def _tasks_to_steps(tasks: list[dict]) -> list[dict]:
        """Convert ``_v2_plan_tasks()`` output into the card's ``steps[]``.

        Field mapping: ``(id, index, title, desc, status)`` →
        ``(id, index, title, status, summary=desc)``. Per-step
        ``start_time`` / ``end_time`` are dropped — the card's own
        timestamps cover that.
        """
        return [
            make_step(
                t.get("index", i),
                t.get("id", f"step_{i}"),
                title=t.get("title", ""),
                status=t.get("status", "loading"),
                summary=t.get("desc", ""),
            )
            for i, t in enumerate(tasks)
        ]

    def _resolve_plan_task_status(self, context: Any = None) -> str:
        """Pick envelope ``task_status`` for plan-card frames.

        During the planning phase the front-end swaps the UI to outline-
        review mode; everywhere else the runner's current task_status
        wins (running / complete / abandon / failed). Reads the phase
        from the wrapped ``WritingContext`` when available so the gate
        survives manager → specialist → manager handoffs.
        """
        from agent.writing.context import PHASE_PLANNING

        ctx = getattr(context, "context", None) if context is not None else None
        phase = getattr(ctx, "current_phase", None)
        if phase == PHASE_PLANNING:
            return TASK_STATUS_OUTLINE
        return self._current_task_status

    async def _emit_plan(self, save: bool = False, context: Any = None) -> None:
        # Per v2.1 protocol §11.3, the first frame for any msg_id must be
        # ``add``; subsequent frames are ``replace`` (or ``patch`` for
        # bandwidth optimization). Detect first emit via the index being
        # unallocated.
        is_first = self._plan_index is None
        if is_first:
            self._plan_index = self._alloc_index()
        tasks = self._v2_plan_tasks()
        value = build_card_value(
            task_id=self.parent_task_id,
            msg_id=self._plan_msg_id,
            thread_id=self.thread_id,
            title="Noah 准备执行的研究计划",
            desc="",
            frame_type="ver",
            priority="p0",
            open_=True,
            steps=self._tasks_to_steps(tasks),
            actions=(),
            status="success" if save else "loading",
            index=self._plan_index,
            # Stamp end_time only when the plan reaches its terminal state
            # (``save=True`` is the on_agent_end / handoff finalisation).
            end_time=iso_now() if save else None,
            # Keep the legacy ``tasks`` list under meta_data too — Backend
            # chat-formatters and analytics still read it.
            extra_meta={"tasks": tasks},
        )
        task_status = self._resolve_plan_task_status(context)
        envelope = (
            build_add_envelope(value, task_status)
            if is_first
            else build_replace_envelope(value, task_status)
        )
        await self._put_v1_frame(
            frame_type="planUpdate",
            frame_id=f"{self.step}-p-0",
            envelope=envelope,
            save=save,
            extra_v1={"plan": [dict(p) for p in self.plan_updates]},
        )

    async def _emit_card(
        self,
        *,
        title: str,
        desc: str = "",
        frame_type: str = "ver",
        priority: str = "p1",
        open_: bool = False,
        steps: Optional[list[dict]] = None,
        actions: Optional[list[dict]] = None,
        msg_id: Optional[str] = None,
        status: str = "loading",
        task_status: Optional[str] = None,
    ) -> str:
        """Push an arbitrary card frame and return its ``msg_id``.

        When ``msg_id`` is passed in (re-emit), uses ``op=replace``; else
        mints a new id and emits ``op=add``. Always reads the envelope
        task_status from ``self._current_task_status`` unless overridden
        via ``task_status`` (use ``TASK_STATUS_FEEDBACK`` when the card
        carries actions awaiting user click).
        """
        is_first = msg_id is None
        if msg_id is None:
            msg_id = new_msg_id()
        value = build_card_value(
            task_id=self.parent_task_id,
            msg_id=msg_id,
            thread_id=self.thread_id,
            title=title,
            desc=desc,
            frame_type=frame_type,
            priority=priority,
            open_=open_,
            steps=steps or [],
            actions=actions or [],
            sender="assistant",
            status=status,
            index=self._alloc_index() if is_first else 0,
            end_time=iso_now() if status in ("success", "error") else None,
        )
        ts = task_status or self._current_task_status
        envelope = (
            build_add_envelope(value, ts)
            if is_first
            else build_replace_envelope(value, ts)
        )
        await self._put_v1_frame(
            frame_type="chat",
            frame_id=f"{self.step}-card-0",
            envelope=envelope,
            save=status == "success",
        )
        return msg_id

    async def _emit_chat(
        self,
        message: str,
        save: bool = True,
        stream_key: Optional[str] = None,
        flush_stream: bool = False,
    ) -> None:
        """Emit a non-streaming or stream-terminating chat frame.

        When ``stream_key`` matches an open stream (token deltas were emitted
        before this), reuse that stream's ``task_id`` and emit ``op=replace``
        with the final cumulative text — front-end's local copy gets a clean
        terminal state. Otherwise emit ``op=add`` with the full text (for
        non-streamed direct responses).

        ``flush_stream`` (true only when called from ``on_llm_end`` after a
        token-streamed run) blanks the v1 ``message`` field — the v2 envelope
        already carries the full text and live-stream v1 frames are also empty,
        so keeping the terminal one consistent avoids confusion. Non-stream
        callers (handoff, errors, direct response) leave ``message`` populated.
        """
        # Resolve msg_id + index: reuse the open stream's slot if any,
        # otherwise mint a brand-new MessageItem.
        s = self._streams.pop(stream_key, None) if stream_key else None
        if s:
            msg_id = s["msg_id"]
            index = s["index"]
            is_first = False
        else:
            msg_id = new_msg_id()
            index = self._alloc_index()
            is_first = True

        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=msg_id,
            thread_id=self.thread_id,
            content_type="markdown",
            text=message,
            sender="assistant",
            status="success",
            index=index,
            end_time=iso_now(),
        )
        envelope = (
            build_add_envelope(value, self._current_task_status)
            if is_first
            else build_replace_envelope(value, self._current_task_status)
        )
        # v1 wrapper kept for Backend chat-formatter routing; ``current_tool``
        # is a legacy field still read by analytics pipelines.
        await self._put_v1_frame(
            frame_type="chat",
            frame_id=f"{self.step}-c-0",
            envelope=envelope,
            message="" if flush_stream else message,
            save=save,
            extra_v1={
                "current_tool": {
                    "reason": message[:100],
                    "startedAt": int(time.time()),
                    "status": "done",
                    "tool": "Writing-Assistant",
                },
            },
        )

    async def _emit_status(self) -> None:
        # First emit must be ``add`` (see _emit_plan for protocol rationale).
        is_first = self._status_index is None
        if is_first:
            self._status_index = self._alloc_index()
        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=self._status_msg_id,
            thread_id=self.thread_id,
            content_type="status",
            text="",
            sender="assistant",
            status="success",
            index=self._status_index,
            end_time=iso_now(),
            meta_data={"agent_status": "step_complete"},
        )
        envelope = (
            build_add_envelope(value, self._current_task_status)
            if is_first
            else build_replace_envelope(value, self._current_task_status)
        )
        await self._put_v1_frame(
            frame_type="statusUpdate",
            frame_id=f"{self.step}-s-0",
            envelope=envelope,
            save=True,
        )

    async def _emit_html(self, html: str, context: Any) -> None:
        """Push a ``content_type="html"`` v2 frame carrying a full HTML doc.

        Always emits ``op=add`` with a fresh ``msg_id`` — every render_html
        call produces a brand-new MessageItem so the front-end can stack
        multiple stage previews instead of overwriting the previous one.
        ``task_status`` stays ``running`` because the manager LLM may still
        do more after the tool returns.
        """
        msg_id = new_msg_id()
        index = self._alloc_index()
        phase = getattr(getattr(context, "context", None), "current_phase", None)
        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=msg_id,
            thread_id=self.thread_id,
            content_type="html",
            text=html,
            sender="assistant",
            status="success",
            index=index,
            end_time=iso_now(),
            meta_data={"source_tool": "render_html", "stage": phase},
        )
        await self._put_v1_frame(
            frame_type="chat",
            frame_id=f"{self.step}-html-0",
            envelope=build_add_envelope(value, self._current_task_status),
            save=True,
        )

    # ------------------------------------------------------------
    # Workspace integration
    # ------------------------------------------------------------

    async def _maybe_emit_workspace_snapshot(self) -> None:
        """Push the workspace ``op=add`` snapshot once per run."""
        if self._workspace_initialized or not self.thread_id:
            return
        try:
            store = _get_workspace_store()
            frame = await store.snapshot_frame(self.thread_id)
        except Exception:
            logger.exception("[WritingHooks] workspace snapshot failed")
            return
        self._workspace_initialized = True
        await self.queue.put(frame)

    async def _reconcile_workspace_assets(self) -> None:
        """Diff sandbox dirs since on_tool_start, register new files, push frames."""
        if not self.thread_id or self.sandbox_manager is None:
            return
        try:
            new_frames, after = await reconcile_assets(
                sandbox_manager=self.sandbox_manager,
                thread_id=self.thread_id,
                chat_id=self.chat_id,
                before_snapshot=self._sandbox_snapshot,
            )
        except Exception:
            logger.exception("[WritingHooks] workspace reconcile failed")
            return
        self._sandbox_snapshot = after
        for frame in new_frames:
            await self.queue.put(frame)

    async def handle_raw_response(self, data: Any) -> None:
        """Coalesce streaming Responses-API deltas into v2 envelope frames.

        OpenAI emits one delta every 10–50 ms which is far too dense for the
        front-end's overwrite render. We accumulate every delta into a per-
        stream buffer but only emit a frame when one of three conditions
        holds (mirrors the mindsearch v1 throttle in
        ``agent/explore/mindsearch_agent_v3.py:3367-3385``):

        1. **First delta of the stream** — always emit so the front-end can
           ``op=add`` a new task_id entry.
        2. **>= ``_v2_throttle_interval`` seconds since the last emit** — keeps
           UI updates at a comfortable cadence.
        3. **>= ``_v2_throttle_chars`` characters added since the last emit** —
           bursty long deltas don't have to wait the full interval.

        The terminal flush (full text + ``op=replace`` + ``status=success``) is
        handled by ``on_llm_end`` calling ``_emit_chat`` with ``flush_stream=True``.

        v1 fields (``id``/``type``/etc.) are kept on every emit so Backend's
        chat formatter pipeline still sees a recognisable chat frame, but
        ``message`` is **empty** — clients that talk v2 must read
        ``event_v2.patches[*].value`` instead. (No production v1-only client
        consumes general_writing token deltas today.)
        """
        if getattr(data, "type", "") != "response.output_text.delta":
            return
        delta = getattr(data, "delta", "") or ""
        if not delta:
            return

        stream_key = f"{self.step}-stream-0"

        s = self._streams.get(stream_key)
        if s is None:
            s = self._streams[stream_key] = {
                "msg_id": new_msg_id(),
                "cumulative": "",
                "first": True,
                "index": self._alloc_index(),
            }
        s["cumulative"] += delta

        # ---- Throttle gate ----
        now = time.monotonic()
        is_first = s["first"]
        chars_since_last = len(s["cumulative"]) - self._last_v2_emit_len
        elapsed = now - self._last_v2_emit_time
        should_emit = (
            is_first
            or elapsed >= self._v2_throttle_interval
            or chars_since_last >= self._v2_throttle_chars
        )
        if not should_emit:
            return  # accumulate; the next delta (or terminal flush) will emit

        self._last_v2_emit_time = now
        self._last_v2_emit_len = len(s["cumulative"])

        # Strip the in-flight ``<plan>...`` tag (and anything trailing) from
        # the cumulative text we ship to the frontend. Final on_llm_end
        # flush does a regex-based ``_extract_and_strip_plan_tag`` pass for
        # the canonical version.
        display_text = self._truncate_at_plan_start(s["cumulative"])
        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=s["msg_id"],
            thread_id=self.thread_id,
            content_type="markdown",
            text=display_text,
            sender="assistant",
            status="loading",
            index=s["index"],
        )
        # Per v2.1 protocol: streaming markdown uses ``replace`` after the
        # first ``add``. ``patch`` with the cumulative full text saves no
        # bandwidth (value size is the same) — replace keeps client parsing
        # simpler.
        if is_first:
            s["first"] = False
            envelope = build_add_envelope(value, self._current_task_status)
        else:
            envelope = build_replace_envelope(value, self._current_task_status)

        # v1 wrapper kept for Backend compatibility; ``message`` is empty —
        # the v2 envelope carries the cumulative text. No production v1
        # client renders this stream.
        await self._put_v1_frame(
            frame_type="chat",
            frame_id=stream_key,
            envelope=envelope,
            save=False,
        )

    async def emit_error(self, message: str) -> None:
        # Flip envelope status to ``failed`` so this error frame *and* every
        # frame after it (e.g. the stream_end follow-up) carries the terminal
        # value. signal_done will leave it on ``failed`` (its mapping for
        # ``error`` is also ``failed``) — consistent.
        self._current_task_status = TASK_STATUS_FAILED
        err_msg_id = new_msg_id()
        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=err_msg_id,
            thread_id=self.thread_id,
            content_type="error",
            text=message,
            sender="system",
            status="error",
            index=self._alloc_index(),
            end_time=iso_now(),
        )
        # emit_error pre-dates the queue having a single per-run ``started_at``
        # for the wrapper frame; use the per-error timestamp via ``extra_v1`` to
        # preserve historical behaviour.
        await self._put_v1_frame(
            frame_type="chat",
            frame_id="error-0",
            envelope=build_add_envelope(value, self._current_task_status),
            sender="system",
            message=message,
            save=True,
            extra_v1={"startedAt": int(time.time())},
        )

    def _build_stream_end_frame(
        self, status: str, reason: Optional[str] = None,
    ) -> dict:
        """Build the v2 ``stream_end`` envelope.

        Tells Backend whether this stream finished cleanly. Backend uses it
        to decide ``task_status`` (Complete / Failed / Interrupted); without
        it, Backend can't distinguish "finished ok" from "stream broke".
        """
        end_msg_id = new_msg_id()
        value = build_message_value(
            task_id=self.parent_task_id,
            msg_id=end_msg_id,
            thread_id=self.thread_id,
            content_type="stream_end",
            text="",
            sender="system",
            status=status,
            index=self._alloc_index(),
            end_time=iso_now(),
            meta_data={
                "stream_status": status,
                "reason": reason,
                "frame_count": self._next_index,
            },
        )
        envelope = build_add_envelope(value, self._current_task_status)
        # Synchronous frame builder — signal_done is async and awaits a
        # queue.put() on the returned dict. We can't call ``_put_v1_frame``
        # here because it would require this method to be async; inline the
        # v1 wrapper instead. The envelope itself still comes from the builder.
        return {
            "agent": self.agent_label,
            "thread_id": self.thread_id,
            "type": "statusUpdate",
            "sender": "system",
            "id": "stream-end-0",
            "startedAt": int(time.time()),
            "save": False,
            "protocol_version": 2,
            "event_v2": envelope["event_v2"],
        }

    # Maps the internal ``signal_done`` status (driven by the runner's
    # try/except outcome) to the envelope-level ``task_status`` that the
    # frontend reads. Kept here so the mapping is co-located with the
    # state-machine transitions instead of leaking into ``agent.py``.
    _SIGNAL_DONE_TO_TASK_STATUS = {
        "ok": TASK_STATUS_COMPLETE,
        "error": TASK_STATUS_FAILED,   # default error → failed; ``error`` (e.g.
                                       # 积分不足) is decided by Backend on reason
        "interrupted": TASK_STATUS_ABANDON,
    }

    async def signal_done(
        self, status: str = "ok", reason: Optional[str] = None,
    ) -> None:
        """Terminate the stream.

        Emits the ``stream_end`` v2 frame *before* ``DONE_SENTINEL`` —
        ordering matters because the reader breaks the loop on the sentinel.
        Status: ``ok`` (clean), ``error`` (raised exception), ``interrupted``
        (cancelled / external stop).
        """
        # Flip the envelope-level task_status BEFORE building the
        # stream_end frame so it carries the terminal value.
        self._current_task_status = self._SIGNAL_DONE_TO_TASK_STATUS.get(
            status, TASK_STATUS_COMPLETE,
        )
        # ``await put`` instead of ``put_nowait``: the queue is unbounded by
        # construction so this never blocks today, but using the awaitable
        # form means a future caller adding ``maxsize`` won't silently drop
        # stream_end — they'd see backpressure instead. Backend's
        # dirty-completion fallback depends on this frame arriving.
        try:
            await self.queue.put(self._build_stream_end_frame(status, reason))
        except Exception:
            logger.exception(
                "[WritingRunHooks] failed to enqueue stream_end frame; "
                "Backend will fall back to its default task_status policy",
            )
        await self.queue.put(DONE_SENTINEL)
