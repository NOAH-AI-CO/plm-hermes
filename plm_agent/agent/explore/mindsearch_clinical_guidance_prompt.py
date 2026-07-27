system_role: str = """You are an AI medical assistant with extensive clinical experience and professional medical knowledge."""

choose_subtree_pt: str = """# Please read the clinical guideline description and find the most relevant sub trees to answer user's question.

<intro>
1. The clinical guidance is structured as a decision tree. It may have a few sub decision trees.
2. Please carefully read sub decision trees' title, disease, keywords and description, then give the suggestion which sub trees should be used.
</intro>

# There is the clinical guidance content. The guidance content contains, sub decision tree title, disease, keywords and description.
<clinical_guidance>
{background}
</clinical_guidance>

# There is the user's question:
<user_question>
{user_prompt}
</user_question>
"""

claude_guideline_pt: str = """# Your task is to analyze a clinical guidance manual and provide detailed treatment advice in response to user questions.

<intro>
1. The clinical guidance is structured as a decision tree. You can navigate through it to identify symptoms and their corresponding treatments.
2. Treatment recommendations and drug advice are stored in the attributes dictionary. You can use the keywords from a decision tree node's attributes to query detailed information.
3. Please provide about the treamt and drug advice as more detail as possible in the attributes dictionary.
</intro>

</response_requirements>
After your analysis, provide a detailed response to the user's question. Follow these guidelines:
1. Wrap your analysis inside <think> tags.
2. The guideline is published in {publish_date}.
4. Cite sources using the format [x](n), where x is the attribute tag, n is the relevant page number in the clinical guidance, i.e. [BINV-P](3)[BINV-Q](5)
5. Important: Present information in a table whenever possible for better readability instead of list.
6. The final output should be professional.
7. Keep drugs' name as the original content and don't do any translate.
</response_requirements>

<analysis_requirements>
Please analyze the question and relevant parts of the clinical guidance. Consider the cancer type, stage, and any specific details mentioned in the question. Identify the most appropriate treatment options based on the guidance.
In your analysis:
1. Quote relevant sections from the clinical guidance.
2. Identify key elements of the user's question (cancer type, stage, specific concerns).
3. Outline the structure of your planned response.
It's OK for this section to be quite long.
</analysis_requirements>

# There is the clinical guidance content.
<clinical_guidance>
{background}
</clinical_guidance>

# Now, consider the following user question:
<user_question>
{user_prompt}
</user_question>"""

claude_subtree_review_pt: str = """# Please read the clinical guideline description and determine whether the current subtree is relevant to the question.

<intro>
1. The clinical guidance is structured as a decision tree. It may have a few sub decision trees.
2. Please carefully read sub decision trees' title, disease, keywords and description, then check whether the current subtree is relevant to the question.
3. If the current subtree is not relevant, please give suggestions which subtrees may be helpful.
</intro>

# There is the clinical guidance content. The guidance content contains, sub decision tree title, disease, keywords and description.
<clinical_guidance>
{background}
</clinical_guidance>

# This is the current subtree content which is structured as a decision tree. You can navigate through it to identify symptoms and their corresponding treatments.
<current_subtree>
{current_subtree}
</current_subtree>

# There is the user's question:
<user_question>
{user_prompt}
</user_question>"""


r1_dt_guideline_pt: str =  """# 请你仔细阅读下面的临床指南，然后回答用户的问题：
请注意临床指南是一颗决策树，树中每个节点的text是症状和具体的诊断，每个节点的children是下一步的诊断和治疗建议。节点中attributes是可以参考的治疗方案，包括药物、手术、检查等，你可以用attributes中关键字来查找具体内容。
# 以下是临床指南的信息
{background}
# 在回答用户问题时，请注意以下要求:
- 当前参考的临床指南发表日期是{publish_date}.
- 当你要引用原文中的内容时，请务必在正文的段落中引用对应的参考编号，格式为[x](n), x是引用的标签，n是page_num引用所在的页码，例如[BINV-P](3)[BINV-Q](5), 不能只在文章末尾引用。
- 最终结果应该看起来像一个严格的医学报告，不要生成任何未经证实的假设】褪色或者虚构的研究结果，所有结论应该可以根据引用进行追溯。
- 你的创作篇幅需要尽可能长，对于每一个要点的论述要推测用户的意图，给出尽可能多角度的回答要点，且务必信息量大、论述详尽。
- 优先使用表格形式展示结果。
- 药品名称请使用原文中的英文名称。
- 不要在结果中包含示意图。
# 以下是用户的提问
{user_prompt}
"""

claude_graph_pt: str = """# Your task is to draw a Mermaid graph according to the llm response.
<task_intro>
- Please ensure that your final result can be parsed as Mermaid syntax.
- Please generate a mermaid diagram with a layout that is as vertical as possible (top to bottom), instead of a flat or horizontal layout (left to right).
- Please add colors to the modules to make it easier to read.
- You should format the node content using the ["label"] syntax, which allows the use of HTML tags and special characters safely in Mermaid diagrams.
- Don't add any text after node syntax.
- The response must start with a code block that begins with ```mermaid and end with ```.
- If the user's query or input is not suitable for drawing a graph (for example, if the user searches for a medical keyword), return an empty result.
</task_intro>

<reasoning>
- Please simplify the reasoning steps, don't retry too many times and you can simply use your first graph.
</reasoning>

<drawing_tips>
- When visualizing first-line, second-line, and third-line treatment plans, they should be shown as a sequential progression — first-line advancing to second-line, and then to third-line — rather than as parallel or independent tasks.
</drawing_tips>

## This is the user question.
<user_question>
{user_prompt}
</user_question>

## This is the llm response.
<content>
{content}
</content>
"""

gpto3_graph_pt: str = """# Your task is to draw a Mermaid graph according to the llm response.
<task_intro>
- Please ensure that your final result can be parsed as Mermaid syntax.
- Please generate a mermaid diagram with a layout that is as vertical as possible (top to bottom), instead of a flat or horizontal layout (left to right).
- Please add colors to the modules to make it easier to read.
- The response must start with a code block that begins with ```mermaid and end with ```.
- If the user's query or input is not suitable for drawing a graph (for example, if the user searches for a medical keyword), return an empty result.
</task_intro>

<mermaid_requirement>
- You should format the node content using the ["label"] or |"label"| syntax, which allows the use of HTML tags and special characters safely in Mermaid diagrams.
</mermaid_requirement>

<drawing_tips>
- When visualizing first-line, second-line, and third-line treatment plans, they should be shown as a sequential progression — first-line advancing to second-line, and then to third-line — rather than as parallel or independent tasks.
</drawing_tips>

## This is the user question.
<user_question>
{user_prompt}
</user_question>

## This is the llm response.
<content>
{content}
</content>
"""

gemini_graph_pt: str = """You are an experienced medical expert and you're highly skilled at creating clear and effective Mermaid flowcharts.
**Your task** is to draw a Mermaid graph according to the input content.
Feel free to think step-by-step before finalizing the drawing.

# Task requirements.
<task_intro>
- Please ensure that your final result can be parsed as Mermaid syntax.
- Please generate a mermaid diagram with a layout that is as vertical as possible (top to bottom), instead of a flat or horizontal layout (left to right).
- Please add colors to the modules to make it easier to read.
- When visualizing first-line, second-line, and third-line treatment plans, they should be shown as a sequential progression — first-line advancing to second-line, and then to third-line — rather than as parallel or independent tasks.
- The graph code must start with a code block that begins with ```mermaid and end with ```.
- If the user's query or input is not suitable for drawing a graph (for example, if the user searches for a medical keyword), return an empty result.
- Review your response and check the code is valid.
</task_intro>

# Drawing requirements.
<mermaid_requirement>
- You should format the node content using the ["label"] or |"label"| syntax, which allows the use of HTML tags and special characters safely in Mermaid diagrams.
- You must format the subgraph content using "" syntax, to avoid special character issue.
- Don't contain extra colons : inside square-bracket labels, and make sure every label is written in either the ["..."] or '{{"..."}} format.
- Don't add any text after node syntax.
- Don't add any comment after %, i.e. G5 --> B8; % Back to MDT
- Don't use style for subgraph, i.e. style "Follow-up" fill:#D1C4E9,stroke:#512DA8
</mermaid_requirement>

# Response example.
<response_example>
[You thinking or analying.]
```mermaid
[Mermaid code]
```
</response_example>

## This is the user question.
<user_question>
{user_prompt}
</user_question>

## This is the llm response.
<content>
{content}
</content>
"""

claude_graph_review_pt: str = """You are an experienced medical expert and you're highly skilled at creating and fixing Mermaid flowcharts.
**Your task** is to review and fix a mermaid graph code.

<task_intro>
You task is just fix the mermaid code. Please don't change the original code.
- If the code is valid, you can simple response the original code.
- The response must start with a code block that begins with ```mermaid and end with ```.
</task_intro>

<mermaid_requirement>
- You should format the node content using the ["label"] or |"label"| syntax, which allows the use of HTML tags and special characters safely in Mermaid diagrams.
- You must format the subgraph content using "" syntax, to avoid special character issue.
- Please remove %% or % comment.
</mermaid_requirement>

This is the mermaid code:
<mermaid_code>
{mermaid_code}
</mermaid_code> 
"""

