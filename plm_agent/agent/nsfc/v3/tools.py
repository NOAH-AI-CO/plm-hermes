# -*- coding: utf-8 -*-
"""
NSFC V3 tools — SubmitBlueprints (Phase 1 termination tool).

Deprecated NSFCProjectSearch and BuildLiteraturePool have been removed;
those capabilities are now handled by local CLI commands.
"""

from typing import List

from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool


class BlueprintSchema(BaseModel):
    title: str = Field(description="Project title (NSFC style)")
    rationale: str = Field(description="Project rationale (2-3 sentences)")
    objectives: List[str] = Field(description="3-5 research objectives")
    contents: List[str] = Field(description="3-5 research content items")
    methods: List[str] = Field(description="3-5 key methods")
    innovations: List[str] = Field(description="2-4 innovation points")


class SubmitBlueprintsInputSchema(BaseModel):
    blueprints: List[BlueprintSchema] = Field(description="3 candidate NSFC project blueprints")
    research_summary: str = Field(default="", description="Summary of research findings")


class SubmitBlueprints(BaseTool):
    """Intercepted by Phase 1 use_tool — no run() needed."""
    name: str = "submit_blueprints"
    description: str = (
        "Submit 3 candidate NSFC project blueprints after research analysis is complete. "
        "Call this tool when you have finished all research (NSFC search, PubMed search, "
        "document analysis) and are ready to present candidate blueprints to the user."
    )
    input_schema: BaseModel = SubmitBlueprintsInputSchema
