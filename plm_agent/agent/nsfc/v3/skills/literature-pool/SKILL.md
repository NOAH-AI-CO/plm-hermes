---
name: literature-pool
description: "Build a PubMed literature pool ranked by impact factor. Returns formatted citation snippets for academic writing."
---

# Literature Pool Builder

## Usage
```bash
literature-pool '{"keywords": ["keyword1", "keyword2"], "years": [2022, 2023, 2024, 2025], "max_papers": 40}'
```

## Parameters
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keywords | list[str] | Yes | - | Search keywords (English preferred) |
| years | list[int] | No | [2021-2025] | Publication years to search |
| max_papers | int | No | 40 | Maximum number of papers to return |

## Output
Numbered citation snippets, each containing:
- Authors, title, journal, year
- PMID and DOI
- Impact factor (IF)
- Abstract excerpt (300 chars)

## Example
```bash
literature-pool '{"keywords": ["EGFR", "lung cancer", "resistance"], "years": [2023, 2024, 2025], "max_papers": 30}'
```

## Notes
- Results are ranked by impact factor and relevance
- Use this for building reference pools for NSFC proposal writing
- Each snippet is formatted for direct citation use
