from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ResearchDirection(BaseModel):
    """One recommended research direction with integrated methodology."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: Optional[str] = Field(default=None, min_length=1, description="Direction title")
    phase: str = Field(
        ...,
        min_length=1,
        description="Clinical trial phase (e.g., Phase I, Phase II, Phase III, Phase IV). This field is required.",
    )
    study_design: str = Field(
        ...,
        alias="研究设计",
        min_length=1,
        description="研究设计类型及详细说明",
    )
    population: str = Field(
        ...,
        alias="人群及样本",
        min_length=1,
        description="目标研究人群、纳排标准、关键协变量与样本量考量",
    )
    exposure: str = Field(
        ...,
        alias="暴露/干预",
        min_length=1,
        description="干预或暴露因素",
    )
    comparison: str = Field(
        ...,
        alias="对照",
        min_length=1,
        description="对照组或对照处理",
    )
    outcomes_and_analysis: str = Field(
        ...,
        alias="终点及分析",
        min_length=1,
        description="采样方案、主要/次要终点测量方法及统计建模方案",
    )
    gap: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Core unresolved research gap",
    )
    objective: str = Field(
        ...,
        min_length=1,
        description="Research objective and expected practical value",
    )


class Reference(BaseModel):
    """A cited reference in the report."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, description="Paper title")
    authors: str = Field(..., min_length=1, description="Author list")
    journal: str = Field(..., min_length=1, description="Journal name")
    year: str = Field(..., min_length=1, description="Publication year")
    pmid: Optional[str] = Field(
        default=None,
        description="PubMed ID, use null when unavailable",
    )
    url: Optional[str] = Field(
        default=None,
        description="URL to the paper, use null if unavailable",
    )
    impact_factor: Optional[str] = Field(
        default=None,
        description="Impact Factor or Cite Score of the journal, use null if unavailable",
    )
    preview: Optional[str] = Field(
        default=None,
        description="Preview of the paper abstract (first 200 characters), use null if unavailable",
    )


class ResearchReport(BaseModel):
    """Structured JSON contract for the final research recommendation report."""

    model_config = ConfigDict(extra="forbid")

    overview: str = Field(
        ...,
        min_length=1,
        description="Narrative overview of current research status",
    )
    key_findings: list[str] = Field(
        ...,
        min_length=1,
        description="Major findings with inline citations",
    )
    research_directions: list[ResearchDirection] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3 to 5 concrete research directions with integrated methodology",
    )
    references: list[Reference] = Field(
        default_factory=list,
        description="All references cited in the report",
    )


def llm_response_schema() -> dict:
    """Return JSON schema that can be passed to LLM structured-output APIs."""
    return ResearchReport.model_json_schema()
