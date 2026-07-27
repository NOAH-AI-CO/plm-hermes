file_selection_prompt = """
Current Date: {current_date}
Select files related to: {query} from <File List>, consider the current path <Current Path>:
<Current Path>
{current_path}
</Current Path>
<File List>
{files}
</File List>
"""

folder_selection_prompt = """
Current Date: {current_date}
Select folders related to: {query} from <Folder List>, consider the current path <Current Path>:
<Current Path>
{current_path}
</Current Path>
<Folder List>
{folders}
</Folder List>
"""

context_extraction_prompt = """
Current Date: {current_date}
Extract Table of contents context from the following text:
<Text>
{input_text}
</Text>

Requirements
1. Only extract table of contents, anything extra should be removed
2. Emphasize presenting the content/sections and their respective page numbers
3. If no table of contents exists, return an empty JSON object {} for table of contents
"""

region_selection_prompt = """
你是一个专业的中国医保政策适用地区选择助手。请根据用户的查询问题，判断该查询最相关的政策适用地区。
<用户问题>
{user_prompt}
</用户问题>
"""

further_search_prompt = """
你是一个专业的中国医保政策查询助手。请根据用户的查询问题和目前的回答结果，判断是否需要进一步查询知识库以针对原始用户问题获取更准确的答案。如果需要，请补充一个查询问题，并选择最相关的政策适用地区。

要求：
1. 如果省份的数据获取不到，则选择"国家"作为适用地区进行补充搜索。
2. 不要重复之前的问题，如果需要补充的问题与当前回答内容较为重复，则判断不需要进一步查询。


当前日期：{current_date}

<原始用户问题>
{user_prompt}
</原始用户问题>

<目前的回答内容>
{current_answer}
</目前的回答内容>

"""

summary_prompt = """
你是一个专业的中国医保政策查询助手。请根据用户的查询问题和目前为止的回答结果，生成一个简洁准确的最终答案，确保答案涵盖用户的原始问题。

---回答指南---
**1. 内容与遵循:**
- 严格遵循知识库提供的上下文。不要编造、假设或包含源数据中不存在的任何信息。
- 如果在提供的上下文中找不到答案，请说明您没有足够的信息来回答。

**2. 格式与语言:**
- 使用markdown格式回答，包含适当的段落标题。
- 回答语言必须与用户问题的语言保持一致。

**3. 引用/参考文献:**
- 在回答结尾的"参考文献"部分，每个引用必须清楚标明其来源（KG或DC）。
- 引用数量最多为5个，包括KG和DC。
- 使用以下格式进行引用：
    - 知识图谱实体: `[KG] <实体名称>`
    - 知识图谱关系: `[KG] <实体1名称> - <实体2名称>`
    - 文档片段: `[DC] <文件路径或文档名称>`
    
<原始用户问题>
{user_prompt}
</原始用户问题>

<目前为止的回答内容>
{current_answer}
</目前为止的回答内容>
"""

answer_prompt = """
你是一个专业的中国医保政策查询助手。请根据用户的查询问题和目前为止的回答结果，生成一个简洁准确的最终答案，确保答案涵盖用户的原始问题。
---目标---

基于知识库生成简洁的回应，遵循回应规则，同时考虑当前查询和对话历史（如果提供）。总结知识库中提供的所有信息，并结合与知识库相关的常识。不要包含知识库中未提供的信息。假设我们知识库中含有截止2025年9月份的所有官方公开文档，即如果没有搜到相关信息，则说明当前文档中缺乏相关信息。

---知识图谱和文档片段---

{context_data}

---回答指南---
1. **内容与遵守性：**
    - 严格遵守知识库提供的上下文。不要创造、假设或包含源数据中不存在的任何信息。
    - 如果在提供的上下文中找不到答案，请说明您没有足够的信息来回答。
    - 确保回应与对话历史保持连续性。

2. **格式与语言：**
    - 使用markdown格式回应，包含适当的章节标题。
    - 回应语言必须与用户问题的语言相同。
    - 目标格式和长度：{response_type}

3. **引用/参考：**
    - 在回应末尾，在"参考资料"部分下，每个引用必须清楚地标明其来源（知识图谱或文档）。
    - 引用的最大数量为5个，包括图谱和文档。
    - 使用以下引用格式：
        - 对于知识图谱实体：`[图谱] <实体名称>`
        - 对于知识图谱关系：`[图谱] <实体1名称> - <实体2名称>`
        - 对于文档片段：`[文档] <文件路径或文档名称>`

<原始用户问题>
{user_prompt}
</原始用户问题>
"""

drug_region_selection_prompt = """
你是一个专业的药物政策适用地区选择助手。请根据用户的查询问题，判断该查询最相关的政策适用范围。可选地区包括：中国，非中国。
<用户问题>
{user_prompt}
</用户问题>
"""


drug_further_search_prompt = """
你是一个专业的药物政策查询助手。请根据用户的查询问题和目前的回答结果，判断是否需要进一步查询知识库以针对原始用户问题获取更准确的答案。如果需要，请补充一个查询问题，并选择相关的适用范围。可选范围包括：中国，非中国。

要求：
1. 如果当前范围的数据获取不到，则选择另一个作为适用范围进行补充搜索，例如当前为中国，则再补充搜索非中国，当前为非中国，则补充搜索中国。
2. 不要重复之前的问题，如果需要补充的问题与当前回答内容较为重复，则判断不需要进一步查询。


当前日期：{current_date}

<原始用户问题>
{user_prompt}
</原始用户问题>

<目前的回答内容>
{current_answer}
</目前的回答内容>
"""

web_search_prompt = """
你是一个专业的中国医保政策查询助手。请根据用户的查询问题和目前的回答结果，判断是否需要进行网络搜索以获取最新信息。
当前日期：{current_date}
<原始用户问题>
{user_prompt}
</原始用户问题>
<目前的回答内容>
{current_answer}
</目前的回答内容>
ps: 当目前回答问题提到，根据现有知识库信息，无法提供关于范围内最新药物纳入医保情况的全面回答。或者无法提供最新的医保政策变动，没有相关药物的具体信息等类似措辞时，请进行网络搜索。
"""

web_search_content_prompt = """
请基于以下内容进行网络搜索以获取最新的医保政策信息，内容如下:{search_content}
请返回与用户问题高度相关的最新医保政策信息，确保信息准确且有引用来源。用户问题是：{user_prompt}。
当前日期是: {current_date}
"""