# -*- coding: utf-8 -*-
"""Specialist Agents for the writing module (P2).

Each specialist is built by a ``build_*_agent()`` factory. The factories
are intentionally stateless — the manager calls them once per run.

Specialists follow a strict three-step instruction pattern baked into
each ``SKILL.md``:

    1. ``cat .memory/task_plan.md .memory/findings.md`` — read prior context
    2. work (search / generate / analyse)
    3. ``run_in_sandbox`` — persist latest artefact back to ``.memory/*.md``

``Blueprint`` / ``LandscapeReport`` / ``PaperAnalysis`` are declared via
``output_type`` so the SDK validates specialist outputs. When such a
specialist is used as a tool (``Agent.as_tool``), wire
``custom_output_extractor=_pydantic_to_json`` so the Pydantic object is
serialised to a JSON string for the manager (SDK requires tool outputs
to be strings).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from agent.writing.context import WritingContext
from agent.writing.model import build_default_model
from agent.writing.schemas import Blueprint, LandscapeReport, PaperAnalysis
from agent.writing.tools import (
    attachment_download,
    literature_pool,
    project_search,
    pubmed_search,
    run_in_sandbox,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill loader
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


@lru_cache(maxsize=None)
def _load_skill(name: str) -> str:
    """Load ``skills/<name>/SKILL.md`` as plain text. Empty string on miss."""
    path = _SKILLS_DIR / name / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("[specialists] SKILL.md missing at %s", path)
        return ""
    except Exception as e:
        logger.warning("[specialists] SKILL.md load failed %s: %s", path, e)
        return ""


# ---------------------------------------------------------------------------
# Generic JSON serializer for as_tool's custom_output_extractor
# ---------------------------------------------------------------------------


async def _pydantic_to_json(result: Any) -> str:
    """``Agent.as_tool`` extractor — serialise final output to JSON string.

    - Pydantic model → ``model_dump_json()``
    - ``None``       → empty string
    - anything else  → ``str(...)`` (non-structured specialists still work)
    """
    out = getattr(result, "final_output", None)
    if isinstance(out, BaseModel):
        return out.model_dump_json()
    if out is None:
        return ""
    return str(out)


# ---------------------------------------------------------------------------
# Specialist factories — imports of Agent / ModelSettings are scoped into
# the functions so importing this module is cheap and side-effect free.
# ---------------------------------------------------------------------------


def build_blueprint_agent(model: Optional[Any] = None):
    """BlueprintSpecialist — produces a ``Blueprint`` object."""
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="BlueprintSpecialist",
        instructions=_load_skill("blueprint"),
        model=model or build_default_model(),
        tools=[run_in_sandbox, project_search, literature_pool, pubmed_search],
        output_type=Blueprint,
        model_settings=ModelSettings(temperature=0.2),
    )


def build_writer_agent(model: Optional[Any] = None):
    """WriterSpecialist — drafts one markdown section; no structured output."""
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="WriterSpecialist",
        instructions=_load_skill("writing"),
        model=model or build_default_model(),
        tools=[run_in_sandbox, literature_pool, pubmed_search],
        model_settings=ModelSettings(temperature=0.7),
    )


def build_citation_agent(model: Optional[Any] = None):
    """CitationSpecialist — normalises citations; used via ``handoffs=[...]``."""
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="CitationSpecialist",
        instructions=_load_skill("citation"),
        model=model or build_default_model(),
        tools=[run_in_sandbox, pubmed_search, literature_pool],
        model_settings=ModelSettings(temperature=0.0),
    )


def build_landscape_agent(model: Optional[Any] = None):
    """LandscapeSpecialist — produces a ``LandscapeReport`` object."""
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="LandscapeSpecialist",
        instructions=_load_skill("landscape-analysis"),
        model=model or build_default_model(),
        tools=[run_in_sandbox, literature_pool, pubmed_search, project_search],
        output_type=LandscapeReport,
        model_settings=ModelSettings(temperature=0.3),
    )


def build_literature_analysis_agent(model: Optional[Any] = None):
    """LiteratureAnalysisSpecialist — produces a ``PaperAnalysis`` object."""
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="LiteratureAnalysisSpecialist",
        instructions=_load_skill("literature-analysis"),
        model=model or build_default_model(),
        tools=[run_in_sandbox, attachment_download, pubmed_search, literature_pool],
        output_type=PaperAnalysis,
        model_settings=ModelSettings(temperature=0.1),
    )


def build_html_render_agent(model: Optional[Any] = None):
    """HtmlRenderSpecialist — produces one self-contained HTML document.

    Output is a raw HTML string (``<!DOCTYPE html>...</html>``), not a
    Pydantic model — no ``output_type`` is declared. No tools: rendering
    is a pure transform over the manager-provided spec, so there's no
    sandbox / search dependency. Temperature sits between Blueprint
    (0.2) and Writer (0.7): the layout has room to vary but the safety
    + style constraints in SKILL.md must hold.
    """
    from agents import Agent, ModelSettings

    return Agent[WritingContext](
        name="HtmlRenderSpecialist",
        instructions=_load_skill("html-render"),
        model=model or build_default_model(),
        tools=[],
        model_settings=ModelSettings(temperature=0.4),
    )


__all__ = [
    "build_blueprint_agent",
    "build_writer_agent",
    "build_citation_agent",
    "build_landscape_agent",
    "build_literature_analysis_agent",
    "build_html_render_agent",
    "_pydantic_to_json",
]
