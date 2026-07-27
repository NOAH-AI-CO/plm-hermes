---
name: pubmed-search
description: "Hybrid search PubMed articles combining keyword and vector search. Returns article titles, abstracts, and metadata."
---

# PubMed Article Search

## Usage
```bash
pubmed-search '{"pubmed_query": "search query in English", "years": [2024, 2025]}'
```

## Parameters
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| pubmed_query | str | Yes | - | Search query in English (no AND/OR operators needed) |
| years | list[int] | No | [] (latest 2 years) | Filter by publication years |

## Output
Numbered list of PubMed articles, each containing:
- Title, authors (first 3 + et al)
- Journal, year, PMID
- Abstract excerpt (400 chars)

## Example
```bash
pubmed-search '{"pubmed_query": "CAR-T cell therapy solid tumors", "years": [2024, 2025]}'
```

## Notes
- Uses hybrid search (BM25 + vector) for best relevance
- Query should be a natural language description, not boolean operators
- Good for targeted literature searches on specific topics
