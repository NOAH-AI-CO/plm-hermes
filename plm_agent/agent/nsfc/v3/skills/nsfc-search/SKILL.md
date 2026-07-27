---
name: nsfc-search
description: "Search funded NSFC projects by keywords. Returns project name, PI, abstract, keywords, funding year, etc."
---

# NSFC Project Search

## Usage
```bash
nsfc-search '{"keywords": ["关键词1", "关键词2"], "start_year": 2020, "top_k": 50}'
```

## Parameters
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keywords | list[str] | Yes | - | Search keywords (Chinese or English) |
| start_year | int | No | 2020 | Start year for filtering projects |
| top_k | int | No | 50 | Maximum number of projects to return |

## Output
Numbered list of NSFC projects, each containing:
- Project name, PI, institution
- Keywords, funding period, approval number
- Project type and code
- Abstract (truncated to 500 chars)
- Conclusion abstract (truncated to 300 chars)

## Example
```bash
nsfc-search '{"keywords": ["肿瘤免疫", "PD-1"], "start_year": 2021, "top_k": 30}'
```
