# -*- coding: utf-8 -*-
"""Generic writing agent module (openai-agents SDK + AgentRun sandbox)."""

from __future__ import annotations

import logging
from pathlib import Path

from agent.writing.agent import WritingAgent
from agent.writing.data_routes import writing_data_router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# v2 capability registration (additive — does not change WritingAgent's flow).
#
# Populates ``agent.runtime.registry`` with one ``SkillSpec`` per writing
# skill. This makes the writing skill set discoverable via the runtime layer
# (e.g. for future ``PreRunRouter`` selection) without changing any existing
# imports or behavior. Registration is best-effort; failures are logged.
# ---------------------------------------------------------------------------


_SKILLS_DIR = Path(__file__).parent / "skills"


def _load_md_body(path: Path) -> str:
    """Return the SKILL.md body, stripping YAML frontmatter when present.

    Reuses ``tools.sandbox.skill_manager._parse_frontmatter`` so the parser
    rules stay aligned with the sandbox-side skill loader.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    from tools.sandbox.skill_manager import _parse_frontmatter
    _, body = _parse_frontmatter(text)
    return body


def _plan_writing_is_enabled(run_context, agent) -> bool:
    """Visibility gate for the ``plan_writing`` specialist tool.

    Hidden once the run has moved past the planning phase so the manager
    can't loop back to ``plan_writing`` after blueprint is locked in. Defined
    here (not in ``agent.py``) so the registration block has no inbound
    dependency on ``WritingAgent`` and we avoid an import cycle.
    """
    from agent.writing.context import PHASE_PLANNING
    phase = getattr(getattr(run_context, "context", None), "current_phase", None)
    return phase in (None, "", PHASE_PLANNING)


def _render_html_is_enabled(run_context, agent) -> bool:
    """Visibility gate for the ``render_html`` specialist tool.

    Inverse of ``plan_writing``: hidden during planning so the manager
    doesn't prematurely render anything before the outline is locked in.
    Becomes visible once the run has transitioned to writing / landscape
    / literature / citation phases — the points where the PRD marks the
    right-pane stage as "HTML 自适应".
    """
    from agent.writing.context import PHASE_PLANNING
    phase = getattr(getattr(run_context, "context", None), "current_phase", None)
    return phase not in (None, "", PHASE_PLANNING)


def _register_writing_skills() -> None:
    try:
        from agent.runtime.registry import (
            CapabilityKind,
            SkillSpec,
            register_skill,
        )
        from agent.writing.specialists import (
            _pydantic_to_json,
            build_blueprint_agent,
            build_citation_agent,
            build_html_render_agent,
            build_landscape_agent,
            build_literature_analysis_agent,
            build_writer_agent,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[Writing] cannot register skills (import failed): %s", e)
        return

    allowed = ("general_writing",)

    def _safe_register(spec: "SkillSpec") -> None:
        try:
            register_skill(spec)
        except Exception as e:  # noqa: BLE001 - registration must never block startup
            logger.warning("[Writing] skill %r registration failed: %s", spec.id, e)

    # PROMPT_SKILL — manager-level instruction text only
    _safe_register(SkillSpec(
        id="attachment", kind=CapabilityKind.PROMPT_SKILL,
        name="Attachment handling",
        description=(
            "Guidance for processing user-uploaded files. Use when the request "
            "involves attached PDFs/images/datasets."
        ),
        instructions=_load_md_body(_SKILLS_DIR / "attachment" / "SKILL.md"),
        allowed_agents=allowed,
    ))
    _safe_register(SkillSpec(
        id="search", kind=CapabilityKind.PROMPT_SKILL,
        name="Search guidance",
        description="Direction for using web/literature search tools effectively.",
        instructions=_load_md_body(_SKILLS_DIR / "search" / "SKILL.md"),
        allowed_agents=allowed,
    ))

    # SPECIALIST_TOOL — built-on-demand, exposed via .as_tool()
    _safe_register(SkillSpec(
        id="blueprint", kind=CapabilityKind.SPECIALIST_TOOL,
        name="Writing blueprint",
        description=(
            "Produce a structured writing Blueprint (goal, audience, outline, "
            "search_queries) as JSON."
        ),
        instructions=_load_md_body(_SKILLS_DIR / "blueprint" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_blueprint_agent(model=model),
        as_tool_name="plan_writing",
        as_tool_description=(
            "Produce a structured writing Blueprint (goal, audience, outline, "
            "search_queries) as JSON. Call this once at the start of a "
            "non-trivial writing task."
        ),
        output_extractor=_pydantic_to_json,
        is_enabled=_plan_writing_is_enabled,
        allowed_agents=allowed,
    ))
    _safe_register(SkillSpec(
        id="writing", kind=CapabilityKind.SPECIALIST_TOOL,
        name="Section drafting",
        description="Draft one markdown section.",
        instructions=_load_md_body(_SKILLS_DIR / "writing" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_writer_agent(model=model),
        as_tool_name="write_section",
        as_tool_description=(
            "Draft one markdown section. Input must describe the section "
            "heading, key_points, target_length (optional), and citation_needs. "
            "Returns the section as markdown."
        ),
        output_extractor=_pydantic_to_json,
        allowed_agents=allowed,
    ))
    _safe_register(SkillSpec(
        id="landscape-analysis", kind=CapabilityKind.SPECIALIST_TOOL,
        name="Landscape survey",
        description="Survey a research area and return a LandscapeReport JSON.",
        instructions=_load_md_body(_SKILLS_DIR / "landscape-analysis" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_landscape_agent(model=model),
        as_tool_name="survey_landscape",
        as_tool_description=(
            "Survey a research area and return a LandscapeReport JSON "
            "(key_themes, major_players, timeline, summary)."
        ),
        output_extractor=_pydantic_to_json,
        allowed_agents=allowed,
    ))
    _safe_register(SkillSpec(
        id="literature-analysis", kind=CapabilityKind.SPECIALIST_TOOL,
        name="Paper deep-read",
        description="Deep-read one paper (URL/PMID/DOI/file) and return a PaperAnalysis JSON.",
        instructions=_load_md_body(_SKILLS_DIR / "literature-analysis" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_literature_analysis_agent(model=model),
        as_tool_name="analyse_paper",
        as_tool_description=(
            "Deep-read one paper (given URL / PMID / DOI / uploaded file) "
            "and return a PaperAnalysis JSON."
        ),
        output_extractor=_pydantic_to_json,
        allowed_agents=allowed,
    ))
    _safe_register(SkillSpec(
        id="html-render", kind=CapabilityKind.SPECIALIST_TOOL,
        name="HTML rendering",
        description=(
            "Render a self-contained HTML document for the current "
            "writing-mode stage (literature query card, draft preview, "
            "QA list, stats summary, final review, journal recommendation)."
        ),
        instructions=_load_md_body(_SKILLS_DIR / "html-render" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_html_render_agent(model=model),
        as_tool_name="render_html",
        as_tool_description=(
            "Render the current stage's right-pane content as a complete, "
            "self-contained HTML document (<!DOCTYPE html> ... </html>). "
            "Input must describe the stage, the data to render, and any UI "
            "intent (preview / cards / table / etc.). Call ONLY when the "
            "current stage is marked HTML 自适应 — do not use for plain prose."
        ),
        is_enabled=_render_html_is_enabled,
        allowed_agents=allowed,
    ))

    # SPECIALIST_HANDOFF — citation takes over the conversation
    _safe_register(SkillSpec(
        id="citation", kind=CapabilityKind.SPECIALIST_HANDOFF,
        name="Citation specialist",
        description="Take over the conversation to produce final cited deliverable.",
        instructions=_load_md_body(_SKILLS_DIR / "citation" / "SKILL.md"),
        specialist_factory=lambda ctx, model: build_citation_agent(model=model),
        allowed_agents=allowed,
    ))


_register_writing_skills()


__all__ = [
    "WritingAgent",
    "writing_data_router",
]
