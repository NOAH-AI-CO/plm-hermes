# -*- coding: utf-8 -*-
"""Wire-format Pydantic models shared across writing specialists.

These models are the **type contract** between specialist Agents (P2).
They are NOT storage — source of truth for task state lives in the
sandbox's ``.memory/*.md`` files and is read/written via
``run_in_sandbox``. See plan decision #8.

Usage:

- ``BlueprintAgent(output_type=Blueprint)`` — SDK validates the specialist's
  output against this schema.
- ``blueprint_agent.as_tool(custom_output_extractor=...)`` — serialize the
  validated object to a JSON string for the manager (SDK's ``as_tool``
  requires tool outputs to be strings).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Blueprint — writing plan produced by BlueprintAgent
# Persisted to ``.memory/task_plan.md`` once the manager accepts it.
# ---------------------------------------------------------------------------


class OutlineSection(BaseModel):
    """One section of the outline — later dispatched to a writer."""

    heading: str
    key_points: List[str] = Field(default_factory=list)
    target_length: Optional[int] = None  # rough target char/word count
    citation_needs: List[str] = Field(
        default_factory=list,
        description="Topics or claims in this section that need a citation.",
    )


class Outline(BaseModel):
    title: str
    sections: List[OutlineSection]


class Blueprint(BaseModel):
    """Top-level writing plan (goal + audience + outline + prep queries)."""

    goal: str
    audience: str
    outline: Outline
    search_queries: List[str] = Field(
        default_factory=list,
        description="Searches the writer should run before drafting.",
    )


# ---------------------------------------------------------------------------
# Bibliography
# ---------------------------------------------------------------------------


class BibEntry(BaseModel):
    """One citable source; fields line up with PubMed + literature_pool results."""

    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None


# ---------------------------------------------------------------------------
# Landscape analysis — big-picture survey of a research area
# Appended to ``.memory/findings.md`` by LandscapeAgent.
# ---------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    year: int
    event: str
    citation: Optional[str] = None  # DOI / PMID / URL pointer


class LandscapeReport(BaseModel):
    topic: str
    key_themes: List[str]
    major_players: List[str] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    summary: str


# ---------------------------------------------------------------------------
# Single-paper deep read
# ---------------------------------------------------------------------------


class PaperAnalysis(BaseModel):
    citation: BibEntry
    summary: str
    methods: str
    findings: str
    relevance_to_task: str


__all__ = [
    "OutlineSection",
    "Outline",
    "Blueprint",
    "BibEntry",
    "TimelineEvent",
    "LandscapeReport",
    "PaperAnalysis",
]
