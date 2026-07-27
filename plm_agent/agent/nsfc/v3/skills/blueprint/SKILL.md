---
name: blueprint
description: "NSFC candidate project blueprint design methodology. Guides how to generate competitive candidate projects from landscape analysis."
---

# NSFC Project Blueprint Design

## When to Use
After completing NSFC landscape analysis and PubMed literature analysis, use this skill to generate candidate project blueprints for user selection.

## Blueprint Structure
Each blueprint must contain:
- **title**: Project title (concise, accurate, NSFC title style)
- **rationale**: Project rationale (2-3 sentences: scientific significance, preliminary basis, corresponding gap/trend)
- **objectives**: Research objectives (3-5 items)
- **contents**: Research contents (3-5 items)
- **methods**: Proposed methods (3-5 key technical approaches)
- **innovations**: Innovation points (2-4 items, emphasizing differences from existing NSFC projects and international research)

## Design Strategy

### With User Documents (preliminary research basis)
When the user has uploaded papers/reports/experimental records:
1. Extract the applicant's strengths: which diseases/objects, problems, and methods they have solid accumulation in
2. Each blueprint should be grounded in these strengths to ensure "the applicant can do it"
3. Cross-reference with NSFC gaps and PubMed trends
4. Each title should fall at the intersection of:
   - Applicant's existing results can support it
   - Does not obviously overlap with existing NSFC projects
   - Can respond to key questions in international trends/gaps

### Without User Documents
1. Use research direction and keywords as boundaries; all titles must develop within this direction
2. Use NSFC landscape to identify gaps not fully covered
3. Use PubMed trends to identify new mechanisms/targets/methods
4. Design "reasonable, feasible, not overly risky" innovative proposals

## Topic Selection Principles
- Young Scientist Fund (youth): more focused, single mechanism, higher completion feasibility
- General Program: broader scope, can address systematic questions, needs stronger preliminary work
- Avoid topics that directly overlap with funded projects
- Prioritize "entry points" where international research is emerging but not yet saturated

## Output Format
Generate 3-5 blueprints as a JSON array. Present them to the user for selection.

When presenting to the user, format each blueprint clearly with:
1. Title in bold
2. Rationale paragraph
3. Objectives as a numbered list
4. Key innovations highlighted

Wait for user selection or modification before proceeding to the writing phase.
