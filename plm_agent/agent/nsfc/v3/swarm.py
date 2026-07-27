# -*- coding: utf-8 -*-
"""
Agent swarm: ForkAgents function tool + SubAgent mini-LLM loop.

Spawns parallel sub-agents with shell access, sharing one sandbox instance.
Each sub-agent runs an independent LLM loop with shell-only tools.
"""

import asyncio
import json
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool
from tools.explore.mindsearch_tools_v3 import FunctionCallResult

logger = logging.getLogger(__name__)

SUB_AGENT_INSTRUCTIONS = """You are a research assistant with shell access to a cloud sandbox.
Complete the assigned task efficiently. Use shell commands and Python scripts.
Save important results to the workspace. Be concise in your final summary.

Available tools in sandbox: python3, pdfplumber, pypdf, python-docx, openpyxl,
tabula-py, matplotlib, pandas, numpy, and standard Linux utilities.

When processing files, use appropriate libraries:
- PDF: pdfplumber or pypdf
- DOCX: python-docx
- XLSX/CSV: openpyxl or pandas
- Images: pytesseract (OCR)

## Local CLI Commands (intercepted by the agent, not sandbox binaries)
These commands run on the agent server, not in the sandbox. Call them directly:
- `nsfc-search '{"keywords": ["keyword1"], "start_year": 2020, "top_k": 50}'` — Search NSFC funded projects
- `literature-pool '{"keywords": ["keyword1"], "years": [2023, 2024, 2025], "max_papers": 40}'` — Build PubMed literature pool ranked by IF
- `pubmed-search '{"pubmed_query": "search query", "years": [2024, 2025]}'` — Hybrid search PubMed articles
- `attachment-download '{"urls": ["https://..."]}'` — Download and parse attachments
Do NOT use `which`, `find`, or `command -v` to look for these — they are not filesystem binaries.
"""


class SubAgentTask(BaseModel):
    """One sub-agent task definition."""
    task: str = Field(description="Natural language task description")
    files: List[str] = Field(
        default=[],
        description="Files in sandbox workspace for this sub-agent to process",
    )


class ForkAgentsInputSchema(BaseModel):
    """Input schema for the fork_agents function tool."""
    explanation: str = Field(description="Why forking sub-agents is needed")
    tasks: List[SubAgentTask] = Field(description="List of parallel tasks")
    max_steps_per_agent: Optional[int] = Field(
        default=15, description="Max steps per sub-agent"
    )


class ForkAgents(BaseTool):
    """Function tool that spawns parallel sub-agents with shell access."""

    name: str = "fork_agents"
    description: str = (
        "Fork multiple sub-agents to process tasks in parallel. "
        "Each sub-agent has shell access to the shared sandbox workspace. "
        "Use when you need to process multiple files independently "
        "(e.g., reading 5 PDFs, analyzing multiple datasets)."
    )
    input_schema: BaseModel = ForkAgentsInputSchema

    async def run(self, **kwargs):
        sandbox_manager = kwargs["_sandbox_manager"]
        tools_schema = kwargs["_tools_schema"]
        model = kwargs["_model"]
        shell_router = kwargs.get("_shell_router", None)
        sys_prompt = kwargs.get("_sys_prompt", SUB_AGENT_INSTRUCTIONS)

        tasks_raw = kwargs.get("tasks", [])
        max_steps = kwargs.get("max_steps_per_agent", 15)

        # Parse tasks
        tasks = []
        for t in tasks_raw:
            if isinstance(t, dict):
                tasks.append(SubAgentTask(**t))
            elif isinstance(t, SubAgentTask):
                tasks.append(t)
            else:
                tasks.append(SubAgentTask(task=str(t)))

        if not tasks:
            yield FunctionCallResult(
                name=self.name,
                result={"error": "No tasks provided"},
            )
            return

        logger.info(
            f"[ForkAgents] Spawning {len(tasks)} sub-agents, max_steps={max_steps}"
        )

        # Run all sub-agents concurrently
        results = await asyncio.gather(
            *[
                SubAgent(
                    task=t.task,
                    files=t.files,
                    sandbox_manager=sandbox_manager,
                    tools_schema=tools_schema,
                    model=model,
                    sys_prompt=sys_prompt,
                    max_steps=max_steps,
                    shell_router=shell_router,
                ).run()
                for t in tasks
            ],
            return_exceptions=True,
        )

        # Aggregate results
        parts = []
        for t, r in zip(tasks, results):
            if isinstance(r, Exception):
                parts.append(f"## Task: {t.task}\nError: {r}")
                logger.error(f"[ForkAgents] Sub-agent failed: {t.task}: {r}")
            else:
                parts.append(f"## Task: {t.task}\n{r}")

        aggregated = "\n\n---\n\n".join(parts)
        logger.info(
            f"[ForkAgents] All sub-agents done, aggregated {len(aggregated)} chars"
        )

        yield FunctionCallResult(
            name=self.name,
            result={"aggregated_results": aggregated, "task_count": len(tasks)},
        )


class SubAgent:
    """Lightweight LLM loop with shell access. Runs independently in shared sandbox."""

    def __init__(
        self,
        task: str,
        files: List[str],
        sandbox_manager,
        tools_schema: list,
        model,
        sys_prompt: str = SUB_AGENT_INSTRUCTIONS,
        max_steps: int = 15,
        shell_router=None,
    ):
        self.task = task
        self.files = files
        self.sandbox_manager = sandbox_manager
        self.tools_schema = tools_schema
        self.model = model
        self.sys_prompt = sys_prompt
        self.max_steps = max_steps
        self.shell_router = shell_router

    async def run(self) -> str:
        """Execute sub-agent loop. Returns final text output."""
        # Sub-agents get only shell tools (no function tools)
        shell_tools = [t for t in self.tools_schema if t.get("type") == "shell"]

        history = [{"role": "user", "content": self._build_prompt()}]

        model = self.model
        if isinstance(model, type):
            model = model()

        for step in range(self.max_steps):
            try:
                response = await model(
                    sys_prompt=self.sys_prompt,
                    user_prompt="",
                    history_messages=history,
                    tools=shell_tools if shell_tools else None,
                    max_output_tokens=8192,
                )
            except Exception as e:
                logger.error(f"[SubAgent] LLM call failed at step {step}: {e}")
                break

            if response is None or not hasattr(response, "output"):
                break

            # Append response output to history
            history.extend(list(response.output))

            has_tool_call = False
            for item in response.output:
                item_type = getattr(item, "type", None)
                if item_type == "shell_call":
                    has_tool_call = True
                    if self.shell_router:
                        output_str = await self.shell_router(item)
                    else:
                        output_str = await self.sandbox_manager.execute_commands(item)
                    history.append({
                        "type": "shell_call_output",
                        "call_id": getattr(item, "call_id", ""),
                        "output": [{
                            "outcome": {"type": "exit", "exit_code": 0},
                            "stdout": output_str,
                            "stderr": "",
                        }],
                    })

            if not has_tool_call:
                break

        return self._extract_final_text(history)

    def _build_prompt(self) -> str:
        parts = [self.task]
        if self.files:
            file_list = "\n".join(f"- {f}" for f in self.files)
            parts.append(f"\nFiles available in workspace:\n{file_list}")
        parts.append(f"\nWorkspace directory: {self.sandbox_manager.workspace}")
        return "\n".join(parts)

    @staticmethod
    def _extract_final_text(history: list) -> str:
        """Extract text from the last message items in history."""
        for item in reversed(history):
            # SDK response object
            if hasattr(item, "type") and getattr(item, "type", None) == "message":
                text_parts = []
                for block in getattr(item, "content", []):
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
                if text_parts:
                    return "\n".join(text_parts)
            # Dict format
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content", "")
                if isinstance(content, str) and content:
                    return content

        return "Sub-agent completed without text output."
