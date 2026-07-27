background_info_search_prompt = """
In order to help generate the clinical trial synopsis, please assist in searching for background information based on the <Synopsis Specification> provided by the user.

<Synopsis Specification>
{query_params}
</Synopsis Specification>

<Target Info>
- *Background*
    - Scientific background and rationale for conducting the study; include disease/condition overview, existing evidence gaps.

- *Justification*
    - Explain why the study is needed, potential impact on medical practice, regulatory or HTA value.

- *Relevant Literature*
    - Key references supporting the study rationale.
</Target Info>
"""