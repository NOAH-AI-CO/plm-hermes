---
name: search
description: "Research-data search tools: project_search (NSFC ES), literature_pool (PubMed + IF ranking), pubmed_search (hybrid)."
---

# Search skill

Three search tools are available for gathering research data.

## When to use which

| Need | Tool |
|---|---|
| Which NSFC projects funded research on topic X? | ``project_search`` |
| Build a ranked reference set for a writing task | ``literature_pool`` |
| Answer a specific factual question from PubMed | ``pubmed_search`` |

## ``project_search`` — NSFC funded projects (ES)

Keyword-search funded NSFC projects. Returns project name, PI, unit,
keywords, dates, approval number, type/code, and a truncated abstract
and conclusion.

```json
{
  "keywords": ["EGFR", "非小细胞肺癌"],
  "start_year": 2020,
  "end_year": 2024,
  "project_types": null,
  "codes": null,
  "top_k": 50
}
```

Tips:

- Mix Chinese and English keywords when the field allows both.
- Limit ``top_k`` when scanning; raise it when building a landscape.
- ``codes`` filters NSFC discipline codes (e.g. ``["H16"]`` for
  oncology). Leave ``null`` for broad searches.

## ``literature_pool`` — ranked PubMed reference set

Vector-search PubMed then rerank by journal impact factor. Best for
building a curated set of papers to cite in a writing task.

```json
{
  "keywords": ["CAR-T therapy", "solid tumors", "exhaustion"],
  "years": [2022, 2023, 2024, 2025],
  "max_papers": 40
}
```

Tips:

- 3–6 keywords is usually the sweet spot. Too many keywords narrows
  results.
- ``max_papers`` defaults to 40. Use 20 for a brief, 60 for a
  comprehensive review.
- Each result has ``impact_factor`` — use it to prioritize.

## ``pubmed_search`` — hybrid single-query search

Hybrid BM25 + vector search. Use for targeted look-ups, not pool
building. The query is a natural-language sentence, not boolean
syntax.

```json
{
  "pubmed_query": "what is the response rate of CAR-T in glioblastoma",
  "years": [2023, 2024, 2025],
  "size": 20
}
```

Tips:

- Write the query as a question or declarative statement. Do **not**
  use AND / OR / NOT.
- Default ``size`` is 20 — usually enough for answering a question.

## Output schema (all three)

```json
{"success": true, "count": N, "results": [...]}
```

On failure: ``{"success": false, "count": 0, "results": [], "error": "..."}``.
Each result's long fields are truncated (abstract ≤ 500 chars,
conclusion ≤ 300 chars) — dig into the original PMID / DOI if the
preview isn't enough.
