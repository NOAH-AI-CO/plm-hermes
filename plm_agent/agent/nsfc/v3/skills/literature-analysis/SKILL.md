---
name: literature-analysis
description: "PubMed literature analysis methodology. Guides how to search and analyze international literature for research paradigms, evidence levels, and knowledge gaps."
---

# PubMed Literature Analysis

## When to Use
When you need to analyze the international research landscape via PubMed literature. Use after retrieving papers via PubMedArticlesLocalSearch or BuildLiteraturePool.

## Search Strategy
- Combine core keywords with broader terms
- Search recent 5 years (2021-2025) for currency
- Use English queries for PubMed
- Target 50+ papers for initial retrieval, then rank by impact factor

## Analysis Workflow

### Part 1: Per-Paper Analytical Reading
Select 5-7 representative papers with clearly different research stances or types. For each paper, write an independent paragraph (5-7 sentences) addressing:

1. **Core research claim**: Is it proposing a key relationship/conclusion, or mainly describing a phenomenon/pattern/tool/resource?
2. **Research level**: Which level is the argument built on? (specific mechanism node, regulatory pathway, cell state/microenvironment, system-level structure, method/resource/clinical indicator)
3. **Evidence type**: What evidence does the claim primarily rely on? (in vitro experiments, animal models, population/clinical data, computational inference, descriptive summary)
4. **Incompleteness**: From a research completeness perspective, which key step was not pursued further? (validation, closed-loop, extrapolation)
5. **Position in research chain**: Is the paper closer to proposing hypotheses, supplementing intermediate mechanisms, explaining results/phenotypes, providing prediction/typing tools, or pointing to intervention/decision basis?
6. **Trade-off**: What advantage did this research trade for what limitation or uncertainty?

### Part 2: Cross-Paper Synthesis
Based only on Part 1 content, provide restrained synthesis:

- Which research premises or narrative approaches are repeatedly used but rarely tested directly?
- Which research steps repeatedly show "progress stops here" across different works, forming structural pause points?
- Overall, does the field lean toward descriptive research, mechanism supplementation without closure, or established paradigms on some questions?

## Writing Requirements
- Do not copy abstract text
- Do not use review-style cliches ("studies have shown", "research indicates")
- Do not provide specific project titles or future research suggestions
- Maintain analytical, judgmental, and academically restrained tone
- Organize naturally with paragraphs and subheadings, no "Part 1" / "Part 2" explicit labels

## Impact Factor Weighting
When building a literature pool for citation:
- Prioritize high-IF journals (normalize IF with cap at 20)
- Use formula: rank_score = base_score * (1.0 + alpha * normalized_IF)
- Target 40 papers for citation pool from 120+ initial results
