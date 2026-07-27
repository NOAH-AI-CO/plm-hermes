# -*- coding: utf-8 -*-
"""
NSFC Writing Agent V3 — Base class for Phase 1 / Phase 2 split.

Provides shared infrastructure (LLM calling, tool execution, sandbox,
event formatting, context management) and a unified execution loop.
Subclasses implement ``use_tool``, injecting phase-specific behavior
via ``LoopHooks``.

V3 architecture:
- Native shell tool (OpenAI Responses API `type: "shell"`) — main LLM directly
  executes shell/python in cloud sandbox
- Agent swarm (fork_agents) — spawns parallel sub-agents for multi-file processing
- Unified workspace — all agents share one sandbox via SandboxManager
"""

import asyncio
import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Awaitable, Callable, List, Optional
from pathlib import Path

from pydantic import ConfigDict

from agent.core.preset import AgentPreset
from agent.core.skill_loader import AgentSkillLoader
from llm.base_model import BaseLLM, CompositeModel
from llm.composite_models import CompositeGPT52
from tools.core.base_tool import BaseTool
from tools.sandbox.sandbox_manager import SandboxManager
from tools.sandbox.skill_manager import SkillManager
from agent.nsfc.v3.swarm import ForkAgents
from agent.nsfc.v3.local_cli import route_shell_commands
from utils.core.get_tool_schema import get_openai_input_schema
import config

logger = logging.getLogger(__name__)

# ============================================================
# Base system prompt (combined with skills at runtime)
# ============================================================

BASE_NSFC_V3_PROMPT = """你是一名国家自然科学基金长期评审专家和申请书写作顾问。

## 工作原则
1. 所有分析必须基于工具返回的真实数据，不得虚构项目或文献
2. 使用正式学术中文撰写申请书内容
3. 引用使用方括号顺序编号 [1-3], [4,5]
4. 每完成一个主要环节后，向用户汇报进展
5. 如果用户已有明确方案，可灵活跳过分析阶段
6. 当生成候选课题方案时，请呈现给用户确认后再继续
7. 当需要处理多个文件时，使用 fork_agents 并行处理

## 输出约定
- 分析类内容直接输出markdown文本
- 候选课题方案以JSON数组格式输出（包含title, rationale, objectives, contents, methods, innovations字段）
- 写作内容以markdown格式输出，章节标题与NSFC官方提纲一致
- 通过shell工具执行Python脚本生成DOCX文件

下面是你的技能指南，请根据这些指南和用户需求灵活执行工作流程：

"""


# ============================================================
# LoopHooks — phase-specific callbacks for the unified loop
# ============================================================

@dataclass
class LoopHooks:
    """Phase-specific callbacks for the unified execution loop."""

    on_message: Callable[[str], bool] | None = None
    """Called on text message. Return True to break loop."""

    on_function_call: Callable[[str, dict, str], Awaitable[tuple[str | None, bool]]] | None = None
    """Called on function_call. Args: (tool_name, tool_args, call_id).
    Return (output_str, should_break). Return (None, False) to fall through to default handling."""

    on_no_tool_call: Callable[[], bool] | None = None
    """Called when a step has no tool calls. Return True to continue (retry), False to break."""

    done_reason: str = "完成"
    """Text for plan_update status when a message completes."""


class NSFCAgentV3Base(AgentPreset):
    """
    NSFC Writing Agent V3 — Base class with shared infrastructure.

    Subclasses (Phase 1 / Phase 2) implement ``use_tool``.
    """

    llm: BaseLLM = CompositeGPT52
    tools: List[BaseTool] = [ForkAgents]
    tool_choice: str = "auto"

    # Agent configuration
    max_steps: int = 35
    attachment_included: bool = False

    # Runtime fields (populated in __init__)
    language: str = "cn"
    scene: str = "default"
    env: str = "default"
    thread_id: str = ""
    sandbox_manager: Any = None

    # Runtime state (not serialized)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, skills_filter: list[str] | None = None, **kwargs):
        super().__init__()

        # Load agent-level skills and build system prompt
        skills_dir = str(Path(__file__).resolve().parent / "skills")
        loader = AgentSkillLoader(skills_dir)
        all_skills = loader.load_all()
        if skills_filter:
            all_skills = [s for s in all_skills if s.name in skills_filter]
        skills_prompt = loader.compose_prompt(all_skills)
        self.sys_prompt = BASE_NSFC_V3_PROMPT + skills_prompt

        # Parse constructor params
        params = kwargs.get("params", {})
        self.language = params.get("language", "cn").lower()
        self.scene = params.get("scene", "default")
        self.env = config.settings.get("ENV", "default")

        # Thread ID for sandbox session persistence
        self.thread_id = kwargs.get("thread_id", "") or params.get("thread_id", "")

        # SandboxManager — shared by main LLM and all sub-agents
        self.sandbox_manager = SandboxManager(session_id=self.thread_id or None)

        # Lock to serialize concurrent _write_step_log calls (prevents read-write races)
        self._step_log_lock = asyncio.Lock()

        # Discover sandbox skills for shell tool config
        sandbox_skill_mgr = SkillManager()
        self._sandbox_skills = list(sandbox_skill_mgr.discover().values())

        # Build mixed tools schema: native shell + function tools
        self._tools_schema = self._build_tools_schema()

        logger.info(
            f"[{self.__class__.__name__}] Initialized with {len(all_skills)} skills, "
            f"{len(self._sandbox_skills)} sandbox skills, "
            f"sys_prompt={len(self.sys_prompt)} chars"
        )

    # ============================================================
    # Tools schema
    # ============================================================

    def _build_tools_schema(self) -> list:
        """Build mixed tools: native shell (with skills) + function tools."""
        # Shell tool — sandbox as high-level concept
        shell_tool = {
            "type": "shell",
        }

        # Add skills to shell environment if available
        if self._sandbox_skills:
            shell_tool["environment"] = {
                "type": "local",
                "skills": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "path": str(s.directory),
                    }
                    for s in self._sandbox_skills
                ],
            }

        # Function tools — domain operations + fork_agents
        function_tools = [get_openai_input_schema(tool()) for tool in self.tools]

        return [shell_tool] + function_tools

    # ============================================================
    # LLM calling
    # ============================================================

    async def _call_model(self, messages: list, tool_choice: str = "auto") -> Any:
        """Call the LLM with full message history and mixed tools schema."""
        model = self.llm
        if isinstance(model, type):
            model = model()

        call_kwargs = dict(
            sys_prompt=self.sys_prompt,
            tools=self._tools_schema,
            temperature=0.3,
            max_output_tokens=16384,
            tool_choice=tool_choice,
        )
        if len(messages) == 1:
            call_kwargs["user_prompt"] = messages[0]["content"]
        else:
            call_kwargs["user_prompt"] = ""
            call_kwargs["history_messages"] = messages

        return await model(**call_kwargs)

    # ============================================================
    # Response parsing
    # ============================================================

    @staticmethod
    def _extract_text(item) -> str:
        """Extract text from a Responses API message item."""
        text_parts = []
        for block in getattr(item, "content", []):
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "".join(text_parts)

    # ============================================================
    # Unified execution loop
    # ============================================================

    async def _execute_loop(
        self,
        messages: list,
        plan_updates: list,
        started_at: int,
        step_offset: int,
        hooks: LoopHooks,
    ) -> AsyncGenerator[dict, None]:
        """
        Unified LLM tool-use loop. Yields frontend events.

        Phase-specific behavior is injected via ``hooks``.
        """
        break_after = False

        for step_i in range(self.max_steps):
            current_step = step_offset + step_i

            # --- LLM call ---
            try:
                response = await self._call_model(messages, tool_choice="auto")
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}] LLM call failed at step {current_step}: {e}")
                logger.error(traceback.format_exc())
                yield self._make_chat_event(
                    f"模型调用失败，正在重试... ({str(e)[:100]})",
                    current_step, started_at, plan_updates,
                )
                await asyncio.sleep(2)
                continue

            if response is None or not hasattr(response, "output"):
                logger.warning(f"[{self.__class__.__name__}] Empty response at step {current_step}")
                break

            messages.extend(list(response.output))
            has_tool_call = False

            # --- Process response items ---
            for item in response.output:
                item_type = getattr(item, "type", None)

                # ---- message ----
                if item_type == "message":
                    text = self._extract_text(item)
                    if text:
                        # Hook: on_message
                        if hooks.on_message and hooks.on_message(text):
                            break_after = True

                        if plan_updates and plan_updates[-1].get("status") == "doing":
                            plan_updates[-1]["status"] = "done"
                            plan_updates[-1]["reason"] = hooks.done_reason
                        step_info = {
                            "id": f"step_{current_step}_msg",
                            "reason": text[:80],
                            "startedAt": int(time.time()),
                            "status": "done",
                            "tool": "Writing-Assistant",
                        }
                        plan_updates.append(step_info)
                        yield self._make_plan_event(plan_updates, current_step, started_at, save=True)
                        yield self._make_chat_event(
                            text, current_step, started_at, plan_updates, save=True,
                        )
                        started_at = int(time.time())

                # ---- shell_call ----
                elif item_type == "shell_call":
                    has_tool_call = True
                    call_id = getattr(item, "call_id", "")
                    step_info = {
                        "id": f"step_{current_step}",
                        "reason": "正在执行: Shell命令",
                        "startedAt": int(time.time()),
                        "status": "doing",
                        "tool": "Shell",
                    }
                    plan_updates.append(step_info)
                    yield self._make_plan_event(plan_updates, current_step, started_at)

                    logger.info(f"[{self.__class__.__name__}] Step {current_step} executing shell_call")
                    output_str = await self._route_shell_call(item)

                    messages.append(self._make_shell_output(call_id, output_str))
                    asyncio.create_task(self._write_step_log(
                        step=current_step, tool_name="Shell",
                        args_summary=str(getattr(item, "action", ""))[:200],
                        output_summary=output_str[:500],
                    ))
                    plan_updates[-1]["status"] = "done"
                    plan_updates[-1]["reason"] = "Shell命令 完成"
                    yield self._make_plan_event(plan_updates, current_step, started_at, save=True)
                    started_at = int(time.time())

                # ---- function_call ----
                elif item_type == "function_call":
                    has_tool_call = True
                    tool_name = getattr(item, "name", "")
                    call_id = getattr(item, "call_id", "")

                    try:
                        tool_args = json.loads(item.arguments)
                    except (json.JSONDecodeError, AttributeError):
                        tool_args = {}

                    # Hook: on_function_call (phase-specific interception)
                    handled = False
                    if hooks.on_function_call:
                        output, should_break = await hooks.on_function_call(tool_name, tool_args, call_id)
                        if output is not None:
                            handled = True
                            messages.append({
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": output,
                            })
                            if should_break:
                                break_after = True
                                continue

                    if not handled:
                        # Default: fork_agents dispatch
                        if tool_name == "fork_agents":
                            step_info = {
                                "id": f"step_{current_step}",
                                "reason": f"正在执行: {tool_name}",
                                "startedAt": int(time.time()),
                                "status": "doing",
                                "tool": tool_name,
                            }
                            plan_updates.append(step_info)
                            yield self._make_plan_event(plan_updates, current_step, started_at)

                            logger.info(
                                f"[{self.__class__.__name__}] Step {current_step} executing {tool_name}: "
                                f"{str(tool_args)[:200]}"
                            )

                            result_text = await self._execute_fork(tool_args, call_id)
                            truncated_result = self._truncate(result_text, 30000)
                            messages.append({
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": truncated_result,
                            })
                            asyncio.create_task(self._write_step_log(
                                step=current_step, tool_name=tool_name,
                                args_summary=str(tool_args)[:200],
                                output_summary=truncated_result[:500],
                            ))
                            plan_updates[-1]["status"] = "done"
                            plan_updates[-1]["reason"] = f"{tool_name} 完成"
                            yield self._make_plan_event(plan_updates, current_step, started_at, save=True)
                            started_at = int(time.time())
                        else:
                            logger.warning(f"[{self.__class__.__name__}] Unexpected function_call: {tool_name}")
                            messages.append({
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": f"Tool '{tool_name}' is not available as a function call. Use the corresponding shell command instead.",
                            })

            # --- Post-iteration checks ---
            if break_after:
                break

            if not has_tool_call:
                # Hook: on_no_tool_call — return True to continue (retry), False to break
                if hooks.on_no_tool_call and hooks.on_no_tool_call():
                    continue
                break

            # Context management
            if step_i > 5:
                if len(messages) > 12:
                    messages[:] = self._trim_messages(messages, keep_rounds=4)
                self._age_old_outputs(messages)

    # ============================================================
    # Tool execution
    # ============================================================

    async def _execute_tool(self, tool_name: str, tool_args: dict, call_id: str) -> str:
        """Execute a function tool by name and return result as string."""
        tool_cls = None
        for t in self.tools:
            if t.__name__ == tool_name:
                tool_cls = t
                break

        if tool_cls is None:
            return f"Tool '{tool_name}' not found."

        try:
            tool_args["_context"] = type("MockContext", (), {
                "id": call_id,
                "call_id": call_id,
            })()

            tool_instance = tool_cls()
            result_text = ""

            async for chunk in tool_instance.run(**tool_args):
                if hasattr(chunk, "result"):
                    r = chunk.result
                    if isinstance(r, str):
                        result_text = r
                    elif isinstance(r, (dict, list)):
                        result_text = json.dumps(r, ensure_ascii=False, indent=1)
                    else:
                        result_text = str(r)
                elif isinstance(chunk, str):
                    result_text += chunk
                else:
                    result_text = str(chunk)

            return result_text if result_text else "Tool executed successfully (no output)."

        except Exception as e:
            logger.error(f"[NSFCAgentV3Base] Tool {tool_name} failed: {e}")
            return f"Tool execution error: {str(e)}"

    async def _route_shell_call(self, item) -> str:
        """Route shell commands: local CLI -> local execution, others -> sandbox."""
        commands = self.sandbox_manager._extract_commands(item)
        if not commands:
            return "Error: No commands to execute"
        await self.sandbox_manager.ensure_sandbox()
        executor = lambda cmd: self.sandbox_manager.execute_shell(command=cmd, timeout=120)
        return await route_shell_commands(commands, executor)

    async def _execute_fork(self, tool_args: dict, call_id: str) -> str:
        """Execute fork_agents with sandbox_manager and tools injected."""
        # Inject internal dependencies
        tool_args["_sandbox_manager"] = self.sandbox_manager
        tool_args["_tools_schema"] = self._tools_schema
        tool_args["_model"] = self.llm
        tool_args["_shell_router"] = self._route_shell_call
        tool_args["_context"] = type("MockContext", (), {
            "id": call_id,
            "call_id": call_id,
        })()

        fork_tool = ForkAgents()
        result_text = ""

        try:
            async for chunk in fork_tool.run(**tool_args):
                if hasattr(chunk, "result"):
                    r = chunk.result
                    if isinstance(r, dict):
                        result_text = r.get(
                            "aggregated_results",
                            json.dumps(r, ensure_ascii=False, indent=1),
                        )
                    elif isinstance(r, str):
                        result_text = r
                    else:
                        result_text = str(r)
        except Exception as e:
            logger.error(f"[NSFCAgentV3Base] fork_agents failed: {e}")
            result_text = f"fork_agents execution error: {str(e)}"

        return result_text if result_text else "fork_agents completed (no output)."

    # ============================================================
    # Shell call output formatting
    # ============================================================

    @staticmethod
    def _make_shell_output(call_id: str, output_str: str) -> dict:
        """Build a correctly-formatted shell_call_output message."""
        return {
            "type": "shell_call_output",
            "call_id": call_id,
            "output": [{
                "outcome": {"type": "exit", "exit_code": 0},
                "stdout": output_str,
                "stderr": "",
            }],
        }

    @staticmethod
    def _get_shell_output_text(msg: dict) -> str:
        """Extract text from a shell_call_output message (handles both formats)."""
        output = msg.get("output", "")
        if isinstance(output, str):
            return output
        if isinstance(output, list):
            parts = []
            for item in output:
                if isinstance(item, dict):
                    parts.append(item.get("stdout", ""))
                    stderr = item.get("stderr", "")
                    if stderr:
                        parts.append(f"STDERR: {stderr}")
            return "\n".join(parts)
        return str(output)

    # ============================================================
    # Context management
    # ============================================================

    def _age_old_outputs(self, messages: list):
        """
        Progressively truncate old tool outputs in-place.
        Handles function_call_output and shell_call_output.
        """
        total = len(messages)
        for idx, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type", "")

            if msg_type == "function_call_output":
                content_key = "output"
            elif msg_type == "shell_call_output":
                # shell_call_output has list-format output; truncate stdout in-place
                rounds_from_end = (total - 1 - idx) // 2
                if rounds_from_end < 1:
                    continue
                if rounds_from_end >= 5:
                    limit = 1500
                elif rounds_from_end >= 3:
                    limit = 5000
                else:
                    limit = 10000
                output = msg.get("output", [])
                if isinstance(output, list):
                    for entry in output:
                        if isinstance(entry, dict):
                            stdout = entry.get("stdout", "")
                            if isinstance(stdout, str) and len(stdout) > limit:
                                entry["stdout"] = stdout[:limit] + f"\n...[truncated from {len(stdout)} chars]"
                continue
            elif msg.get("role") == "tool":
                content_key = "content"
            else:
                continue

            rounds_from_end = (total - 1 - idx) // 2
            if rounds_from_end < 1:
                continue

            if rounds_from_end >= 5:
                limit = 1500
            elif rounds_from_end >= 3:
                limit = 5000
            else:
                limit = 10000

            content = msg.get(content_key, "")
            if isinstance(content, str) and len(content) > limit:
                msg[content_key] = (
                    content[:limit] + f"\n...[truncated from {len(content)} chars]"
                )

    # ============================================================
    # .memory/ file offloading
    # ============================================================

    @property
    def _memory_dir(self) -> str:
        return f"{self.sandbox_manager.workspace}/.memory"

    async def _init_memory_files(self, task: str) -> None:
        """Initialize .memory/ directory and files for this session."""
        try:
            memory_dir = self._memory_dir
            await self.sandbox_manager.execute_shell(
                command=f'mkdir -p {memory_dir}', timeout=5,
            )
            await self.sandbox_manager.execute_shell(
                command=f'cat > {memory_dir}/task_plan.md << \'TASKEOF\'\n# Task Plan\n\n## Current Task\n{task}\nTASKEOF',
                timeout=5,
            )
            await self.sandbox_manager.execute_shell(
                command=f'test -f {memory_dir}/findings.md || echo "# Findings\\n" > {memory_dir}/findings.md',
                timeout=5,
            )
            await self.sandbox_manager.execute_shell(
                command=f'test -f {memory_dir}/progress.md || echo "# Execution Progress\\n" > {memory_dir}/progress.md',
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"[NSFCAgentV3Base] Failed to init memory files: {e}")

    async def _load_prior_context(self) -> str:
        """Load prior session context from .memory/ files. Returns context string or empty."""
        if not self.thread_id:
            return ""
        try:
            memory_dir = self._memory_dir
            parts = []
            for fname in ["findings.md", "progress.md"]:
                result = await self.sandbox_manager.execute_shell(
                    command=f'cat {memory_dir}/{fname} 2>/dev/null || true',
                    timeout=5,
                )
                content = result.get("stdout", "").strip()
                if content and len(content) > 20:
                    parts.append(f"### {fname}\n{content}")
            if parts:
                context = "\n\n## Prior Session Context (from persistent memory)\n" + "\n\n".join(parts)
                logger.info(f"[NSFCAgentV3Base] Loaded prior context: {len(context)} chars")
                return context
        except Exception as e:
            logger.warning(f"[NSFCAgentV3Base] Failed to load prior context: {e}")
        return ""

    async def _write_step_log(
        self, step: int, tool_name: str, args_summary: str, output_summary: str,
    ) -> None:
        """Append step log to progress.md (fire-and-forget, non-fatal)."""
        try:
            memory_dir = self._memory_dir
            step_content = (
                f"\n## Step {step} — {tool_name}\n"
                f"Args: {args_summary}\n"
                f"> Output: {output_summary}\n"
            )
            progress_path = f"{memory_dir}/progress.md"
            client = self.sandbox_manager._client
            if client:
                async with self._step_log_lock:
                    existing = await client.read_file(progress_path) or ""
                    await client.write_file(progress_path, existing + step_content)
            else:
                logger.warning(f"[NSFCAgentV3Base] No sandbox client for step log {step}")
        except Exception as e:
            logger.warning(f"[NSFCAgentV3Base] Failed to write step log {step}: {e}")

    def _trim_messages(self, messages: list, keep_rounds: int = 4) -> list:
        """
        Keep first user message + last N rounds + trimmed marker.

        A "round" is counted by dict messages (tool outputs: function_call_output,
        shell_call_output). SDK response items (from response.output) don't count.
        """
        if len(messages) <= 1 + keep_rounds * 2:
            return messages

        first_msg = messages[0]
        recent = messages[-(keep_rounds * 2):]
        trimmed = messages[1:-(keep_rounds * 2)]

        # Extract file paths from trimmed messages
        path_pattern = r'(?:/home/user|/mnt/workspace)/\S+'
        file_mentions = set()
        for msg in trimmed:
            if isinstance(msg, dict):
                if msg.get("type") == "shell_call_output":
                    content = self._get_shell_output_text(msg)
                else:
                    content = msg.get("content", msg.get("output", ""))
            else:
                content = str(getattr(msg, "content", "") or "")
            if isinstance(content, str):
                for match in re.findall(path_pattern, content):
                    file_mentions.add(match.rstrip('.,;:)]\'"'))

        # Extract progress summaries from trimmed messages
        progress_entries = []
        for msg in trimmed:
            if isinstance(msg, dict) and msg.get("type") in ("function_call_output", "shell_call_output"):
                output_text = self._get_shell_output_text(msg) if msg.get("type") == "shell_call_output" else msg.get("output", "")
                if isinstance(output_text, str) and len(output_text) > 20:
                    progress_entries.append(output_text[:200])

        trimmed_count = len(trimmed) // 2
        note = (
            f"[Note: {trimmed_count} earlier execution rounds were trimmed from context. "
            "Continue based on the progress summaries below and your most recent work.]"
        )
        if progress_entries:
            max_progress = 6
            if len(progress_entries) > max_progress:
                omitted = len(progress_entries) - max_progress
                kept = progress_entries[-max_progress:]
                note += f"\n\n[Progress from earlier rounds ({omitted} older entries omitted):\n" + "\n---\n".join(kept) + "]"
            else:
                note += "\n\n[Progress from earlier rounds:\n" + "\n---\n".join(progress_entries) + "]"
        if file_mentions:
            note += f"\n\n[Files referenced in trimmed rounds: {', '.join(sorted(file_mentions))}]"

        trimmed_marker = {"role": "user", "content": note}
        return [first_msg, trimmed_marker] + recent

    # ============================================================
    # Blueprint preview (shared by Phase 1 output + Phase 2 input)
    # ============================================================

    @staticmethod
    def _build_blueprint_preview(blueprint: dict, index: int) -> str:
        """Format a single blueprint as readable markdown (matches V2 format)."""
        title = blueprint.get("title") or f"未命名备选课题方案 {index}"
        rationale = (blueprint.get("rationale") or "").strip()
        objectives = blueprint.get("objectives") or []
        contents = blueprint.get("contents") or []
        methods = blueprint.get("methods") or []
        innovations = blueprint.get("innovations") or []

        lines = [f"### {index}）{title}"]
        if rationale:
            lines.append(f"**立项理由：**{rationale}")
            lines.append("")
        if objectives:
            lines.append("**研究目标：**")
            for o in objectives:
                lines.append(f"- {o}")
            lines.append("")
        if contents:
            lines.append("**研究内容：**")
            for c in contents:
                lines.append(f"- {c}")
            lines.append("")
        if methods:
            lines.append("**拟采用方法：**")
            for m in methods:
                lines.append(f"- {m}")
            lines.append("")
        if innovations:
            lines.append("**创新点：**")
            for inn in innovations:
                lines.append(f"- {inn}")
            lines.append("")
        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    # ============================================================
    # Event formatting (compatible with V2 frontend)
    # ============================================================

    def _make_plan_event(
        self, plan_updates: list, step: int, started_at: int, save: bool = False,
    ) -> dict:
        return {
            "agent": "article_nsfc_writing",
            "type": "planUpdate",
            "sender": "assistant",
            "plan": plan_updates,
            "chunkIdx": 0,
            "id": f"{step}-p-0",
            "startedAt": started_at,
            "save": save,
        }

    def _make_chat_event(
        self, content: str, step: int, started_at: int,
        plan_updates: list, save: bool = False,
        tool_name: str = "Writing-Assistant",
    ) -> dict:
        return {
            "agent": "article_nsfc_writing",
            "current_tool": {
                "reason": content[:100] if len(content) > 100 else content,
                "startedAt": started_at,
                "status": "done" if save else "doing",
                "tool": tool_name,
            },
            "type": "chat",
            "sender": "assistant",
            "chunkIdx": 0,
            "message": content,
            "id": f"{step}-c-0",
            "startedAt": started_at,
            "save": save,
        }

    def _make_status_event(self, step: int, started_at: int) -> dict:
        return {
            "agent": "article_nsfc_writing",
            "chunkIdx": 0,
            "id": f"{step}-s-0",
            "sender": "assistant",
            "startedAt": started_at,
            "type": "statusUpdate",
            "save": True,
        }

    def _make_error_event(self, message: str) -> dict:
        return {
            "agent": "article_nsfc_writing",
            "type": "chat",
            "sender": "assistant",
            "message": message,
            "chunkIdx": 0,
            "id": "error-0",
            "startedAt": int(time.time()),
            "save": True,
        }

    # ============================================================
    # Utilities
    # ============================================================

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n...[truncated from {len(text)} chars]"
