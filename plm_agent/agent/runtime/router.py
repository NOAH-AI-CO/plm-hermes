# -*- coding: utf-8 -*-
"""``PreRunRouter`` — pre-flight LLM call that selects writing skills per request.

One small LLM call before the manager Agent is built. The router only sees
``id + description + triggers`` for each candidate skill — full instruction
bodies stay out of this call to keep it cheap.

Module dispatch (clarification / confirmation / workspace) is handled by the
**outer** ``agent.modules.pipeline`` router; this inner router is skill-only.

LLM access is dependency-injected via ``RouterConfig.llm_call`` so tests can
provide a deterministic fake without pulling real LLM clients into the import
graph.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

from agent.runtime.registry import (
    CapabilityRegistry,
    CapabilityView,
    SkillSpec,
)

logger = logging.getLogger(__name__)


_DEFAULT_PROMPT_TEMPLATE = """\
You are a capability router for the {agent_name} agent.

Pick the minimum set of skills to load for this request. Loading more is
wasteful; loading less means the agent can't do the job.

Available SKILLS (id — description — triggers):
{skill_list}

USER REQUEST:
\"\"\"{user_prompt}\"\"\"

RECENT TURNS:
{history}

CURRENT PHASE: {current_phase}

Return STRICT JSON only — no surrounding prose, no markdown fences:
{{
  "skills": ["skill_id", ...],
  "reasoning": "one short sentence"
}}
"""


@dataclass(frozen=True)
class CapabilityPlan:
    skills: List[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class RouterConfig:
    model: str = "claude-3-5-haiku"
    timeout_s: float = 6.0
    max_skills: int = 4
    fallback_plan: CapabilityPlan = field(
        default_factory=lambda: CapabilityPlan(skills=[], reasoning="fallback"),
    )
    prompt_template: Optional[str] = None
    # Dependency-injection seam for the LLM call; tests pass a fake.
    # Signature: async def llm_call(*, model, prompt) -> str (raw JSON text)
    llm_call: Optional[Callable[..., Any]] = None


def _format_skill_list(skills: Sequence[SkillSpec]) -> str:
    if not skills:
        return "(none)"
    lines = []
    for s in skills:
        triggers = ", ".join(s.triggers) if s.triggers else "—"
        lines.append(f"- {s.id} — {s.description} — triggers: {triggers}")
    return "\n".join(lines)


def _format_history(history: Sequence[dict], max_chars: int = 800) -> str:
    if not history:
        return "(none)"
    lines = []
    for turn in history:
        role = (turn.get("role") or "?").lower()
        content = (turn.get("content") or "").strip().replace("\n", " ")
        if len(content) > 200:
            content = content[:200] + "…"
        lines.append(f"[{role}] {content}")
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[-max_chars:]
    return out


class PreRunRouter:
    """Routes a request to a subset of registered skills."""

    def __init__(self, registry: CapabilityRegistry, config: RouterConfig):
        self.registry = registry
        self.config = config

    async def select(
        self,
        *,
        agent_name: str,
        user_prompt: str,
        history: Optional[List[dict]] = None,
        current_phase: Optional[str] = None,
    ) -> CapabilityPlan:
        view = self.registry.list_for_agent(agent_name)
        if not view.skills:
            return CapabilityPlan(skills=[], reasoning="no skills registered")

        if not (user_prompt or "").strip():
            return self.config.fallback_plan

        prompt = self._build_prompt(
            agent_name=agent_name,
            view=view,
            user_prompt=user_prompt,
            history=history or [],
            current_phase=current_phase,
        )

        try:
            raw = await asyncio.wait_for(
                self._call_llm(prompt),
                timeout=self.config.timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning("[PreRunRouter] timeout; using fallback plan")
            return self.config.fallback_plan
        except Exception as e:  # noqa: BLE001 - we want to fall back on any LLM failure
            logger.warning("[PreRunRouter] llm error %r; using fallback plan", e)
            return self.config.fallback_plan

        try:
            return self._parse(raw, view)
        except Exception as e:  # noqa: BLE001 - parse errors → fallback
            logger.warning("[PreRunRouter] parse error %r; raw=%.200s", e, raw)
            return self.config.fallback_plan

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        *,
        agent_name: str,
        view: CapabilityView,
        user_prompt: str,
        history: Sequence[dict],
        current_phase: Optional[str],
    ) -> str:
        template = self.config.prompt_template or _DEFAULT_PROMPT_TEMPLATE
        return template.format(
            agent_name=agent_name,
            skill_list=_format_skill_list(view.skills),
            user_prompt=user_prompt,
            history=_format_history(history),
            current_phase=current_phase or "—",
        )

    async def _call_llm(self, prompt: str) -> str:
        if self.config.llm_call is None:
            raise RuntimeError(
                "PreRunRouter has no llm_call configured; "
                "either inject one in RouterConfig or override _call_llm."
            )
        result = await self.config.llm_call(model=self.config.model, prompt=prompt)
        if not isinstance(result, str):
            raise TypeError(f"llm_call must return str, got {type(result).__name__}")
        return result

    def _parse(self, raw: str, view: CapabilityView) -> CapabilityPlan:
        # Strip code fences if the LLM ignored the "no markdown" instruction.
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(f"router output is not a JSON object: {parsed!r}")

        valid_ids = {s.id for s in view.skills}
        skills_in = parsed.get("skills") or []
        if not isinstance(skills_in, list):
            raise ValueError(f"'skills' must be a list, got {type(skills_in).__name__}")

        kept: List[str] = []
        for sid in skills_in:
            if not isinstance(sid, str):
                continue
            if sid not in valid_ids:
                logger.info("[PreRunRouter] dropping unknown skill id %r", sid)
                continue
            if sid in kept:
                continue  # dedupe
            kept.append(sid)
            if len(kept) >= self.config.max_skills:
                break

        reasoning = parsed.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)
        return CapabilityPlan(skills=kept, reasoning=reasoning)
