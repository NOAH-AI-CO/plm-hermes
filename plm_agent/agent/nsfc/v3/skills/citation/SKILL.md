---
name: citation
description: "NSFC proposal reference management specification. Includes Vancouver format, numbering rules, and export format."
---

# NSFC Proposal Citation Management

## Citation Format: Vancouver Style

### PubMed Literature
Format: `Author1, Author2, Author3 et al. Title. Journal. Year. PMID: XXXXX. doi: XXXXX.`

Rules:
- List up to 3 authors; if more, add "et al"
- Author name format: "LastName Initials" (e.g., "Zhang Y", "Smith JA")
- Title: original language, first letter capitalized
- Journal: standard abbreviation
- Year: 4 digits
- Include PMID and DOI when available

### NSFC Project References
Format: `PI Name. Project Title. National Natural Science Foundation of China. Year. Approval No: XXXXXXXX. Institution.`

## In-Text Citation Rules

### Numbering
- Sequential numbering by order of first appearance in text
- Use bracket notation: [1], [2-4], [5,6]
- Continuous numbers use dash: [1-3] (not [1,2,3])
- Non-continuous numbers use comma: [1,3,5]

### Placement
- Place immediately after the relevant statement
- Before punctuation: "...cancer progression[1-3]."
- Can combine: "Studies have shown[1-3] that... recent work suggests[4,5]..."

### Density Requirements by Section
| Section | Minimum Citations |
|---------|------------------|
| Research Significance (1.1) | 8-15 papers |
| Research Status (1.2) | 6-10 per paragraph, 25-35 total |
| Research Plan | As needed for method justification |
| Other sections | As appropriate |

## Reference List Format

At the end of the proposal, list all references in order:

```
[1] Author1, Author2 et al. Title. Journal. Year. PMID: XXXXX.
[2] Author1, Author2 et al. Title. Journal. Year. PMID: XXXXX.
...
```

## Citation Renumbering

After all sections are written, references may need renumbering:
1. Scan all text to find first appearance order of each citation number
2. Create old->new mapping based on first appearance order
3. Renumber all in-text citations
4. Reorder the reference list accordingly

## Important Rules
- NEVER fabricate literature or cite non-existent papers
- NEVER use PMID as in-text citation (wrong: [PMID 12345], correct: [1])
- Only cite papers from the provided literature pool
- Ensure every cited number has a corresponding entry in the reference list
- Ensure every reference list entry is cited at least once in the text
