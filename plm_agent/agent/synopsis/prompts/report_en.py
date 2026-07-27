full_prompt_template_en = """
<Synopsis Specification>
{query_params}
</Synopsis Specification>
Please generate a clinical trial synopsis based on the target parameters provided in <Synopsis Specification> by referencing and imitating trial data from <Noah Data> and output it in the provided format <Output Template>.

<Noah Data>
{trial_data}
</Noah Data>

Generated on: {current_date}

## Synopsis Structure (Generate in Order)
<Output Template>
{synopsis_output_template}
</Output Template>

"""

partial_prompt_template_en = """
<Synopsis Specification>
{query_params}
</Synopsis Specification>

Generation Date: {current_date}

The user wants to generate a new, original clinical trial synopsis. We will write it section by section.
Please strictly adhere to the <Synopsis Specification> provided by the user, learn from the trial data in <Noah Data>, generate an original clinical trial protocol summary, and output the protocol summary sections according to the <Output Template> format. Do not output any sections other than those specified in <Output Template>.

<Noah Data>
{trial_data}
</Noah Data>

## Synopsis Structure (generate in order)
<Output Template>
{synopsis_output_template}
</Output Template>

Requirements:
1. Please provide comprehensive, detailed content for each section
{extra_requirements}
"""

partial_prompt_template_post_en = """
<Synopsis Specification>
{query_params}
</Synopsis Specification>

Generation Date: {current_date}

The user wants to generate a new, original clinical trial synopsis. We will write it section by section.
Based on the sections we have already written in <Synopsis In Progress>, and strictly according to the <Synopsis Specification> provided by the user, generate the clinical trial synopsis section specified in <Output Template>. Do not output any sections other than those specified in <Output Template>.

<Synopsis In Progress>
{synopsis_parts}
</Synopsis In Progress>

## Synopsis Structure (generate in order)
<Output Template>
{synopsis_output_template}
</Output Template>

Requirements:
1. For Limitations of the research methods section, list only the most critical ones, avoid listing too many.
2. Ensure that related information from previous sections consistently carry into the output, for example, variables like exposure variables should be described consistently
{extra_requirements}
"""

partial_prompt_template_chain_en = """
<Synopsis Specification>
{query_params}
</Synopsis Specification>

<Synopsis In Progress>
{synopsis_parts}
</Synopsis In Progress>

{background_info}

Generation Date: {current_date}

The user wishes to generate a brand new, original clinical trial protocol summary. We will write it section by section.
Please strictly adhere to the <Synopsis Specification> provided by the user, learn from the trial data in <Noah Data>, generate an original clinical trial protocol summary, and output the protocol summary sections according to the <Output Template> format. Do not output any sections other than those specified in <Output Template>.
Refer to the sections we have already written in <Synopsis In Progress> to ensure consistency and coherence.

<Noah Data>
{trial_data}
</Noah Data>

## Synopsis Structure (generate in order)
<Output Template>
{synopsis_output_template}
</Output Template>

Requirements:
1. Please provide comprehensive, detailed content for each section
2. Ensure that related information from previous sections consistently carry into the output, for example, variables like exposure variables should be described consistently
{extra_requirements}
"""

merge_prompt_en = """
<Synopsis Specification>
{query_params}
</Synopsis Specification>

You need to combine the <Synopsis Chunks> into sections while preserving all original text and details, outputting the clinical trial synopsis according to the order specified in <Output Order>.

<Synopsis Chunks>
{synopsis_parts}
</Synopsis Chunks>

Generation Date: {current_date}

## Synopsis Order
<Output Order>
{synopsis_output_template}
</Output Order>

Requirements:
1. When combining sections, preserve all text and details of each section without simplifying, summarizing, or omitting any content from <Synopsis Chunks>. 
2. While not omitting any text from the other sections in each chunk, concatenate and deduplicate each chunks' glossary of terms and references from the Appendices section .
3. Adjust indentation and formatting, and deduplicate headings to make the final output more well-organized and easier to read.
4. Do not add any extra notes or prompts related annotations to the headings, such as: 'References (after merging and deduplication)' should be just 'References'
5. Please output in English
"""