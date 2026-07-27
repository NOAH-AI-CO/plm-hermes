import datetime

current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

professional_output_prompt = """
### 输出要求
禁止添加分析性引导语或总结性开场白；不得声明身份、能力或写作方法；
不出现“我分析”“关键信息”及类似表述；不输出占位符；
不得编造数据或文献；证据不足处以一句中文说明不确定性，避免抱怨性措辞；

"""

current_time_prompt = """
  当前时间为： {current_time}
""" .format(current_time=current_time)

origin_text_prompt = """
### 原文本说明

禁止添加分析性引导语或总结性开场白；不得声明身份、能力或写作方法；
不出现“我分析”“关键信息”及类似表述；不输出占位符；
不得编造数据或文献；证据不足处以一句中文说明不确定性，避免抱怨性措辞；

以下任何形式的"说明性文字"都**绝对禁止**出现在输出中：

**禁止类型1：任务说明**
  - "好的，我将为您撰写第2章..."
  - "以下是第2章的内容："
  - "根据您的要求，我生成了..."
  - "现在开始撰写..."

**禁止类型2：过程说明**
  - "首先，我们需要..."
  - "接下来将讨论..."
  - "在撰写本章时，我注意到..."

**禁止类型3：结束语**
  - "以上是第2章的内容。"
  - "本章完成。"
  - "希望这符合您的要求。"
  - "如需修改，请告诉我。"

**禁止类型4：自我评价**
  - "这一部分写得比较详细..."
  - "我认为这个章节..."
  - "这里可能需要补充..."

**禁止类型5：格式说明**
  - "【以下是正文】"
  - "【章节开始】"
  - "【注：这里使用了...】"
  - "```markdown"（代码块标记）

**禁止类型6：引用说明**
  - "（此处应添加引用）"
  - "[引用待补充]"

"""


numbering_format_prompt = """
### 序号格式要求

请在输出内容时，按以下规则使用序号格式，兼顾层级清晰性与阅读舒适度：

#### 一、核心序号格式（层级较多或内容较长时使用）
- 一级标题：1. 2. 3.（后接空格+内容，单独成行）
- 二级标题：1.1 1.2 1.3（后接空格+内容，单独成行，可缩进2-4字符）
- 三级标题：1.1.1 1.1.2（后接空格+内容，单独成行，缩进比上一级多2-4字符）
- 四级及以上标题：以此类推（仅在内容需多层细分时使用）

#### 二、简化格式（标题下内容简短，仅1-2行时适用）
- 若一级标题下的子项内容简短（如单句描述），可直接用短横线（-）引出，无需嵌套数字序号：
  1. 标题内容
     - 子项1（简短内容，一行内完成）
     - 子项2（简短内容，一行内完成）
- 若二级标题下的子项内容简短，同样可用短横线（-）简化：
  1. 标题内容
     1.1 子标题
        - 子项1（简短内容）
        - 子项2（简短内容）

#### 三、禁止使用的格式
- 禁止中文序号：一、二、三、
- 禁止括号序号：(1) (2) (3)
- 禁止字母序号：A. B. C. 或 a. b. c.
- 禁止罗马数字：I. II. III. 或 i. ii. iii.
- 禁止特殊符号：① ② ③ 或 • · 

#### 四、格式示例
1. 主要分类
   - 简短子项1（内容少，用短横线）
   - 简短子项2（内容少，用短横线）
2. 另一主要分类
   2.1 需详细说明的子分类（内容较长）
       2.1.1 三级细分点（内容较多时使用）
           - 三级下的简短子项（进一步简化）
           - 另一简短子项
   2.2 另一子分类（内容中等）
       - 子项1（无需更细层级时用短横线）
       - 子项2（无需更细层级时用短横线）

"""


citation_prompt = """
### 引用格式要求

1. **正文中的引用**：
   - 在需要引用的地方使用 [1]、[2]、[3] 这样的格式
   - 多个引用可以写成 [1,2] 或 [1-3]
   - 例如："根据研究显示，这种方法有效[1]。其他研究也证实了这一发现[2,3]。"

2. **引用原则**：
   - 每个重要的观点、数据、结论都需要引用
   - 引用应该紧跟在相关论述之后
   - 不要过度引用，只引用最相关和最重要的文献

3. **参考文献列表**：
   - 在文章末尾添加"参考文献"部分
   - 按照在正文中出现的顺序编号
   - 格式：1. Author A, Author B. Title. Journal. Year.
   - 每一条参考文献独占一行

示例：
正文：根据Smith等人[1]的研究，这种方法在临床试验中表现出色。后续研究[2,3]进一步验证了这一结论。

参考文献：
1. Smith A, Jones B. Novel therapeutic approach for treatment. Nature Medicine. 2023.
2. Wang C, et al. Clinical validation study. Lancet. 2024.
3. Zhang D. Meta-analysis of treatment outcomes. JAMA. 2024.
"""


reference_format_instruction_prompt = """
### 参考文献格式要求

#### 基本原则
- **排序方式**：按照在正文中首次被引用的顺序编号（不按字母顺序或年份排序）
- **编号格式**：使用阿拉伯数字，如 1. 2. 3. ...
- **每条文献独占一行**

#### 标准格式模板

**期刊论文（Journal Article）**：
```
序号. 作者1姓名缩写, 作者2姓名缩写, 作者3姓名缩写, et al. 文章完整标题. 期刊名缩写. 年份;卷号(期号):起始页码-结束页码. PMID: PubMed编号.
```

#### 作者格式规则
- **1-3位作者**：全部列出，用逗号分隔
  - 示例：`Smith A, Johnson B, Williams C.`
- **4位及以上作者**：列出前3位 + "et al."
  - 示例：`Larson HJ, Jarrett C, Eckersberger E, et al.`
- **作者姓名格式**：姓 + 名字首字母（不加点）
  - 正确：`Smith A`
  - 错误：`Smith, A.` 或 `A. Smith`

#### 期刊名格式
- 使用**标准缩写**（参考PubMed/Index Medicus缩写）
- 常见期刊缩写示例：
  - Nature Medicine → Nat Med
  - Journal of the American Medical Association → JAMA
  - The Lancet → Lancet
  - Vaccine → Vaccine
  - Medical Principles and Practice → Med Princ Pract

#### 卷期页码格式
- **格式**：年份;卷号(期号):起始页-结束页
- **示例**：
  - `2021;46(2):270-7` （卷46，期2，页270-277）
  - `2014;32(19):2150-9` （卷32，期19，页2150-2159）
  - `2020;8(3):482` （卷8，期3，页482）

#### PMID格式
- **格式**：`PMID: 数字编号.`（末尾有句点）
- **示例**：`PMID: 34696208.`

#### 完整示例

```
1. Larson HJ, Jarrett C, Eckersberger E, Smith DMD, Paterson P. Understanding vaccine hesitancy around vaccines and vaccination from a global perspective: A systematic review of published literature, 2007–2012. Vaccine. 2014;32(19):2150-9. PMID: 34358168.

2. Alqudeimat Y, Alenezi D, AlHajri B, et al. Acceptance of a COVID-19 vaccine and its related determinants among the general adult population in Kuwait. Med Princ Pract. 2021;30(3):262-71. PMID: 34202298.

3. Wang J, Jing R, Lai X, et al. Acceptance of COVID-19 vaccination during the COVID-19 pandemic in China. Vaccines (Basel). 2020;8(3):482. PMID: 34358188.

4. Sallam M, Dababseh D, Eid H, et al. High rates of COVID-19 vaccine hesitancy and its association with conspiracy beliefs: A study in Jordan and Kuwait among other Arab countries. Vaccines (Basel). 2021;9(1):42. PMID: 34843545.
```

#### 禁止使用的格式

**错误示例**：
```
1. Pubmed 31607600.
2. DOI: 10.1038/s41591-023-xxxxx.
3. Smith et al., Nature, 2023.
4. [1] Smith A. (2023). Article title. Journal Name, 10(2), 100-110.
```

**正确示例**：
```
1. Smith A, Johnson B, Williams C. The impact of artificial intelligence on healthcare delivery. Nat Med. 2023;29(5):1234-45. PMID: 12345678.
```

#### 特殊情况处理

**1. 无PMID的文献**：
- 可以省略PMID部分，但保持格式一致
- 示例：`Smith A, Jones B. Article title. J Med. 2023;10(2):100-10.`

**2. 在线发表（Epub）**：
- 格式：`期刊名. 年份. Epub ahead of print. PMID: 编号.`

**3. 书籍章节**：
- 格式：`作者. 章节标题. In: 编者, ed. 书名. 版本. 出版地: 出版社; 年份:页码.`

**4. 会议摘要**：
- 格式：`作者. 标题 [abstract]. 会议名; 年份 月 日; 地点.`

#### 质量检查清单

格式化完成后，请检查：
- [ ] 所有引用序号与正文标注一一对应
- [ ] 序号连续无遗漏（1, 2, 3...）
- [ ] 作者姓名格式统一
- [ ] 期刊名使用标准缩写
- [ ] 卷期页码格式正确（年份;卷(期):页码）
- [ ] PMID格式正确（PMID: 数字.）
- [ ] 每条文献末尾有句点
- [ ] 无重复文献

#### 常见错误对照表

| 错误 | 正确 |
|------|------|
| Smith, A., Jones, B. | Smith A, Jones B |
| Nature Medicine | Nat Med |
| 2023, 29(5), 1234-1245 | 2023;29(5):1234-45 |
| PMID 12345678 | PMID: 12345678. |
| et.al. | et al. |
| Vol. 29, No. 5 | 29(5) |

---

### 使用示例

**输入原始引文**：
```
Smith, A., Johnson, B., & Williams, C. (2023). The impact of AI on healthcare. Nature Medicine, Volume 29, Issue 5, pages 1234-1245. PubMed ID: 12345678
```

**输出标准格式**：
```
1. Smith A, Johnson B, Williams C. The impact of AI on healthcare. Nat Med. 2023;29(5):1234-45. PMID: 12345678.
```
"""

# 连贯性和一致性要求
coherence_and_consistency_prompt = """
### 1. 内容连贯性与一致性
#### 1.1 内容连贯性
- **自然承接**：开头第一段必须自然承接上一章的结论或核心观点
  - 正确示例："基于前述分析，本章将深入探讨..."
  - 错误示例：直接开始新话题，无任何过渡
  
- **逻辑递进**：确保本章内容是整体论证链条的有机组成部分
  - 如果是第2章（文献综述），需要从第1章（引言）提出的问题出发
  - 如果是第4章（结果），需要基于第3章（方法）的研究设计
  
- **避免重复**：
  - 不要重复前面章节已经详细阐述的内容
  - 如需提及前文观点，使用简短回顾（如"如第X章所述..."）

#### 1.2 术语一致性
- **专业术语**：使用与前文完全一致的术语
  - 示例：如果前文使用"医护人员"，不要突然改成"医疗工作者"
  - 如果前文使用"non-NIP vaccines"，本章继续使用，不要换成"自费疫苗"
  
- **缩写规范**：
  - 首次出现：全称（英文全称，缩写）
  - 后续使用：直接使用缩写
  - 注意：如果缩写已在前文定义，本章直接使用缩写即可

#### 1.3 语言风格一致性
- **学术规范**：全文保持一致的学术写作风格
  - 使用第三人称客观叙述
  - 采用被动语态为主
  - 避免口语化表达（"很多" → "大量"；"差不多" → "约"）
  
- **时态一致**：
  - 已有研究：过去时（"Smith等（2023）发现..."）
  - 普遍真理：现在时（"疫苗接种是预防疾病的有效手段"）
  - 本研究结果：过去时（"本研究发现..."）

#### 1.4 数据与事实一致性
- 引用的数据、百分比、统计结果必须与前文保持一致
- 如果需要引用前文数据，确保数值完全相同
- 人物角色、机构名称等信息保持一致（主要针对案例研究）
"""



#序号格式，引用格式要求，输出要求（禁止输出无用信息）
output_requirement_prompt = numbering_format_prompt + '\n\n' + reference_format_instruction_prompt + '\n\n'  +  professional_output_prompt


chapter_by_chapter_paper_prompt = """
    # 角色设定
    你是一位经验丰富的医学论文写作专家，擅长撰写高质量的医学、医疗、公共卫生类学术论文。你的论文符合国际顶级医学期刊（如JAMA、Lancet、NEJM、BMJ）的写作标准。

    ## 任务
    根据已知的信息，对已给出的章节标题进行论文写作。

    ## 输入信息
    
    - 论文总体标题： {thesis_title}
    - 论文总体大纲：{thesis_outline}
    - 论文总体字数：{thesis_words}
    - 本章为第{chapter_index}章，共{chapter_count}章
    - 本章前三章内容摘要：
        {thesis_data}
    - 本章字数要求：{chapter_words}+-200字
    - 本章章节标题总览：
        {thesis_section}

    ## 输出要求
    ### 输出语言
        请用{language}语言、markdown格式输出
    ### 连贯性、一致性要求:
        {coherence_and_consistency}
    ### 文章序号要求:
        {numbering_format}
    ### 引文标准要求:
        {reference_format_instruction}
    ### 元文本输出要求:
        {origin_text}
   
"""

section_abstract_prompt = """
    # 角色设定
    你是擅长浓缩文本的语言专家。
    
    ## 输入信息
    - 论文总体标题
        {thesis_title}
    - 论文总体大纲
        {thesis_outline}
    - 本章内容
        {thesis_section_data}
    ## 任务
    请根据本章内容，撰写本章摘要。
    字数：150-200字

"""



gen_thesis_from_outline_section_prompt = """

请你根据论文大纲和标题整体构思，帮我写作其中这个章节的内容，要求中：
1.内容需有数据支撑，禁止编造数据和引文，没有数据支撑的时候要写明这部分内容没有数据支持，例如'当前公开文献尚未提供'。
2.识别“故事骨架文献”与“配角文献”。骨架文献：landmark trial、指南、权威综述；配角文献：真实世界研究、小样本探索、相反结果的研究
3.生成 narrative 结构
4.用{language}输出
5.根据医学专业论文写作的习惯决定分段和是否添加小标题。
6.每段写作都需要注意把关联的文献综合成一个故事线清楚、而不是堆砌总结句的叙述段落。
7.写作前，简要说明本章的写作思路和内容。
8.第一段讲整体趋势 + 核心 landmark 研究，后面段落讲补充证据 / 异质性 / 争议。
9.要注意要考虑到大纲行文思路和上下章节之间的连贯性。
10.**字数要求**，必须满足大纲中要求字数的两倍以上，如果字数不足，则需要补充内容。
11.请充分挖掘每篇提供的文献核心数据、研究设计与结论，按‘骨架文献搭建核心论证 + 配角文献多维度补充（人群 / 区域 / 研究设计异质性、真实世界验证、争议点回应）’的逻辑，最大化引用所有提供的文献（优先保证每篇文献至少被引用 1 次，关键文献可多维度重复引用），通过延伸讨论研究一致性 / 差异、机制解释、局限性分析等方式扩充内容，确保引用密度与内容深度兼具。
12.**非常重要**充分使用提供的文献，尽可能保留足够多的文献引用，不要遗漏。

写作风格要求：
- 仿照该主题领域高分期刊的医学写作风格进行写作，符合医学写作的逻辑性、连贯性以及简洁性，不需要太多艺术色彩，条理清晰地写作，围绕小标题的同时时刻紧扣大纲
- 本文章不适用医学资助或伦理申请，因此不需要额外添加这一部分
- 文章每节标题不适合较多的艺术色彩，更应该倾向于医学科学性、逻辑性与总结性
- 文章输出按照大纲序号来输出，禁止扩写新标题，按自然语言输出
- 若需输出中文，需将原文中所有英文词汇（包括但不限于 “uptake”“initiation”“intend”“immigrant”“caregivers” 等）全部翻译为准确对应的中文，避免保留英文原词，翻译需贴合上下文场景且统一；若需输出英文，可直接保留原文英文词汇或按需优化表达，无需额外翻译为中文。无论哪种语言输出，均需保证表述流畅、逻辑连贯，符合对应语言的表达习惯。
- 引言部分禁止细分标题序号, 引言需用自然语言来输出
- 引言部分如果涉及本文章写作目标或者简要介绍时，禁止引用文献。
- 禁止 “标签：内容” 的格式，把标签对应的核心维度（如可及性、可负担性）融入句子开头，用 “在 XX 方面”“从 XX 角度看” 这类自然衔接的表述引出内容，如必须用“标签：内容” 这种格式，请改写成自然语言来输出。
- 将原本的分项内容整合成连贯的语句，不用生硬的标点分隔，让逻辑更顺畅；
- 如有表格，请添加表注，包含数据来源说明和缩写的全称。
- 通篇风格应为自然语言风格，禁止AI风格输出，例如解释在()里、破折号、小括号等。


原始信息：
- 标题:
{title}

---

- 论文大纲:
{thesis_outline}

---

- 上下文:
{thesis_context}

---

- 章节:
{outline_section}
"""


gen_abstract_prompt = """
你是一位经验丰富的学术研究者，请帮提供的论文内容、论文讨论部分和结论部分，撰写摘要部分。达到sci论文投稿需求。

## 论文内容：

{thesis_data}

## 结论

{thesis_conclusion}

请用{language}语言输出

要求：
  - 英文版摘要必须包含以下五个模块：Background、Methods、Results、Conclusions、Keywords
  - 中文版摘要必须包含以下五个模块：背景、方法、结果、结论、关键词
  - 根据输入语言自动判断：如果原文是英文则只生成英文版摘要，如果原文是中文则只生成中文版摘要
  - 不要出现任何引文
  - 关键词数量范围为3-5个
  - 根据示例生成摘要

示例：
Abstract
Background:
 Healthcare workers (HCWs) play a decisive role in bridging evidence and practice for non–National Immunization Program (non-NIP, Category II) vaccines in China. These vaccines—delivered voluntarily and financed out-of-pocket—serve as a critical test of health system equity, provider engagement, and public trust. Despite growing international evidence that provider recommendation is the strongest predictor of vaccine uptake, comprehensive analyses of Chinese HCWs’ recommendation behaviors, their determinants, and modifiable levers remain scarce.
Methods:
 A mixed narrative and thematic review was conducted using bilingual (English–Chinese) searches across PubMed. The analysis synthesized quantitative and qualitative studies on influenza, human papillomavirus (HPV), and Haemophilus influenzae type b (Hib) vaccination. Determinants were categorized under the COM-B model (Capability, Opportunity, Motivation → Behavior) and the 5A framework (Accessibility, Affordability, Awareness, Acceptance, Activation), integrating behavioral and systems perspectives to map intervention entry points.
Results:
 Evidence shows that HCW recommendation frequency for non-NIP vaccines remains low and uneven across cadres. In a 10-province influenza study, only 25.3% of HCWs were vaccinated themselves, and public health workers were significantly more likely than general practitioners to recommend vaccination to children (62.4% vs. 49.1%) and older adults (68.1% vs. 54.7%). Capability deficits—limited knowledge of priority groups and vaccine timing—combined with motivational barriers such as low perceived need, safety concerns, and workload constraints, substantially reduce proactive recommendation. Organizational and policy factors, including reimbursement ambiguity, workload pressures, and unclear role delineation between clinical and public health staff, further weaken routine recommendation practice. Educational interventions targeting HPV and influenza have shown measurable gains in provider knowledge and confidence, while economic incentives and workflow integration enhance opportunity for consistent counseling. Digital trust-building and transparent communication strategies are emerging as complementary motivators for sustained engagement.
Conclusions:
 HCW recommendation behavior for non-NIP vaccines is a multi-level phenomenon shaped by individual capability and motivation, institutional opportunity, and system-level trust and financing architectures. Strengthening HCW vaccination, communication competence, and policy clarity—while aligning financial and performance incentives—constitutes a feasible pathway to improve recommendation consistency and vaccine uptake. An integrated “Recommendation Ecology Framework” linking education, workflow optimization, and trust governance offers a scalable model for advancing equitable, life-course immunization in China.
Keywords:
 Non-NIP vaccines; healthcare workers; vaccine recommendation; COM-B model; 5A framework.
"""

gen_conclusion_prompt = """
你是一位经验丰富的学术研究者，请根据提供的论文内容以及论文讨论部分，撰写结论部分，字数在350字之内。尽量详细，达到sci论文投稿需求。

## 论文内容：

{thesis_data}


请用{language}语言输出
不要出现任何引文

"""


gen_discuss_prompt = """
你是一位经验丰富的学术研究者，请帮提供的论文撰写讨论部分。尽量详细，达到sci论文投稿需求。

## 论文内容：

{thesis_data}

请用{language}语言输出
需要有引文出现

以 `## 讨论` 开头

"""

polish_thesis_prompt = """
    # 请你作为一个资深医学教授来润色整篇文章
    ## 要求：        
        - 保持学术论文的精简风格，适当删缩语句，但保持引用内容与引文对应关系不变。
        - 使段落有更好的过渡。
        - 缩写要求标准：对「重复出现≥3 次」且「全称较长（通常≥4 个单词）」的术语 / 机构 / 技术缩写（如生物医学中 ‘National Immunization Program (NIP)’、‘healthcare workers (HCWs)’。请在生成时自检是否第一次出现专业名词以及重复出现专业名词，重复出现的必须用缩写。
        - 输出中不用拘泥于固定格式，禁止用 “可操作性建议：XXXXXXXXXX”“纳入标准：XXX；排除标准：XXX” 这类生硬表述。尽量以自然的段落起始句展开，比如用 “实践中，可通过以下路径推动 XXXX……” 这样的方式呈现，让内容更流畅易读。
        - 如单个章节中分成了多级标题，请在一级标题下简要说明本章的写作思路和内容。
        - 引用、讨论、结论部分禁止添加小标题，直接输出内容。
        - 对原文要做适当删减，使整体论文输出字数控制在12000字以内。
        - **非常重要**: 引文的格式必须保持不变，禁止进行任何修改，禁止进行添加，禁止进行替换。只可以出现一种格式，例如：单个引文[1]、多个引文[1][2]。
        
    ## 输出语言风格要求:
        必须以医学综述的语言风格来输出，但避免AI化，通篇应以自然语言来输出。
        
    ## 强制统一：
        时态（一般过去 vs 现在）
        术语写法
        引用格式（文中引用）

    ## 输出结构顺序：
        1. 标题
        2. 摘要
        3. 正文（论文中不需要出现这个标题）
        4. 讨论
        5. 结论
    
    ## 强烈禁止：
        正文中的引文禁止任何修改，禁止进行删除，禁止进行添加，禁止进行替换。
        文章中禁止出现冒号，例如‘建议下一步研究重点：建立覆盖全国xxx’
        

    ## 输出语言 
        文章的整体都需要用{language}语言输出，包括标题、摘要、正文、结论以及对引文的说明。

    ## 输入部分
    
    正文的大纲部分
    {thesis_outline}
    
    ### 标题
        {thesis_title}
    ---
    ### 摘要
        {thesis_abstract}
    ---
    ### 正文
        {thesis_data}
    ---
    ### 结论
        {thesis_conclusion}
    --- 
""" + professional_output_prompt


gen_outline_prompt = """
    # 你是一个资深医学教授
    ## 目标

    以论文标题 {thesis_title}
    总字数{thesis_words}+-10%字为基础，
    生成学术综述大纲。
    ## 要求：
    - 分4-5章，每章明确“标题+核心目标+建议字数”，章节逻辑遵循“引言-方法-现状-影响因素-干预策略”，字数分配贴合综述类论文比例，核心要素不遗漏。
    - 引言不需要再次细分小标题，其他章节需细分，最多不超过二级标题。细分的规则例如：对人群的细分，男人女人，老人儿童等
    - 方法章节，来源只能来自pubmed。
    - 引言字数最多只能占百分之八，其他章节字数分配贴合综述类论文比例，核心要素不遗漏。

    输出格式为Python列表套字典。
    ## 示例
    
    ```['''
        一、引言（Introduction）
        目标： 阐明研究背景、问题与创新价值。
        建议字数： 900–1000（约12%）
        - 疫苗接种是预防传染病最具成本效益的公共卫生策略，对健康公平与可持续发展目标至关重要。
        - 中国的二类疫苗（non-NIP vaccines），如HPV、肺炎球菌、Hib和轮状病毒疫苗，由于自愿、自费接种特性，接种率存在显著差异。
        - 医护人员推荐被视为影响公众决策的“信任中介”，是提高接种率的核心行为。
        - 尽管国际研究广泛探讨医护推荐对接种意愿的促进作用，但中国相关系统性研究仍有限。
        强化要点：
        可引入量化证据（如HPV疫苗接种率与医护推荐率对比），突出研究的现实意义与数据支撑。
        过渡句模板：
        “然而，现有研究多聚焦公众态度，缺乏对医护推荐行为的结构性分析与多层干预路径探讨。”
        - 本文聚焦四个核心问题：医护人员二类疫苗推荐行为的现状如何？哪些因素影响推荐意愿与实践？现有干预策略有哪些？如何构建系统化的改进路径？
        - 综述目标：综合国内外文献，识别个体、组织与社会层面影响机制；应用COM-B与5A模型分析行为形成机制；提出整合性理论框架与政策启示。
        ''',
        '''
        二、研究方法与综述策略（Methods）
        目标： 界定研究范围与理论分析框架。
        建议字数： 600–700（约8%）
        2.1 文献来源与筛选原则
        - 数据库：PubMed、Web of Science、CNKI、万方；
        - 时间范围：2005–2025（反映近20年研究趋势）；
        - 关键词：healthcare workers, vaccine recommendation, non-NIP, influencing factors, China；
        - 纳入标准：涉及医护推荐行为、影响因素或干预措施的实证与综述文献；
        - 排除标准：不涉及医护人员的疫苗行为研究。

        ---
        2.2 分析框架与方法
        - 理论框架：
        - COM-B模型（Capability, Opportunity, Motivation → Behavior）分析行为形成与干预切入点；
        - 5A框架（Accessibility, Affordability, Awareness, Acceptance, Activation）分析系统性障碍与推动因素。
        - 方法：叙述性归纳（narrative synthesis）+ 主题分析（thematic analysis）。'''
    ],```
"""

gen_outline_prompt_v1 = """
    # 你是一个资深医学教授
    ## 目标

    以论文标题 {thesis_title}
    总字数{thesis_words}+-10%字为基础，
    生成学术SCI综述大纲。
    ## 要求：
    - 生成6-8章，每章明确“标题+核心目标+建议字数”，大纲逻辑遵循“引言-方法-内容1-内容2-内容3”，字数分配贴合综述类论文比例，核心要素不遗漏。引言不需要再次细分小标题，直接以段落形式输出。其他章节需细分，最多不超过二级标题。
    - 每章需明确“标题（需体现章节核心维度）+核心目标（需对应综述主题的具体解决方向）+建议字数（需标注占总字数的比例）”；章节逻辑严格遵循“引言-方法-核心内容模块1-核心内容模块2-核心内容模块3（从最契合主题的多个维度，确定如“特殊人群VPDs负担现状”“负担影响因素”）”；字数分配需贴合SCI综述常规比例：引言≤8%、方法5%-10%、核心内容模块65%-75%、讨论10%-12%、结论5%-8%。 其中：引言无需细分小标题，直接以3-5个逻辑连贯的自然段落输出；其他章节可以按“核心维度+细分类型”设置二级标题，最多到二级。
    - 引言部分大纲要求：确立出一条主线，围绕主线叙述，不可泛泛而谈无重点，要求从宏观层面到文章核心内容，逻辑层层递进。结构：① 宏观背景：学科 / 行业宏观视角切入；② 领域现状与矛盾：聚焦更细致的现状，可以展开文章具体的主题词进行叙述+ 核心矛盾（“目前进展与矛盾点” 对立）③ 领域缺口：提出目前研究领域中存在的空白视角④ 综述目的与结构预告：再次点明主线，明确综述核心目标 + 全文结构模块预告。
    - 引言部分限制条件：引言部分分3-5自然段，不细分小标题，只以自然段形式输出。引言字数最多只能占8%，其他章节字数分配贴合综述类论文比例，核心要素不遗漏。
    - 方法章节大纲要求：来源只能来自pubmed。
    - 禁止生成讨论、讨论与展望、结论、未来发展方向章节。

    输出格式为Python列表。
    ## 输出示例
    ```['''
        一、引言（Introduction）
        目标： 阐明研究背景、问题与创新价值。
        建议字数： 900–1000（约12%）
        - 疫苗接种是预防传染病最具成本效益的公共卫生策略，对健康公平与可持续发展目标至关重要。
        - 中国的二类疫苗（non-NIP vaccines），如HPV、肺炎球菌、Hib和轮状病毒疫苗，由于自愿、自费接种特性，接种率存在显著差异。
        - 医护人员推荐被视为影响公众决策的“信任中介”，是提高接种率的核心行为。
        - 尽管国际研究广泛探讨医护推荐对接种意愿的促进作用，但中国相关系统性研究仍有限。
        强化要点：
        可引入量化证据（如HPV疫苗接种率与医护推荐率对比），突出研究的现实意义与数据支撑。
        过渡句模板：
        “然而，现有研究多聚焦公众态度，缺乏对医护推荐行为的结构性分析与多层干预路径探讨。”
        - 本文聚焦四个核心问题：医护人员二类疫苗推荐行为的现状如何？哪些因素影响推荐意愿与实践？现有干预策略有哪些？如何构建系统化的改进路径？
        - 综述目标：综合国内外文献，识别个体、组织与社会层面影响机制；应用COM-B与5A模型分析行为形成机制；提出整合性理论框架与政策启示。
        ''',
        '''
        二、研究方法与综述策略（Methods）
        目标： 界定研究范围与理论分析框架。
        建议字数： 600–700（约8%）
        2.1 文献来源与筛选原则
        - 数据库：PubMed、Web of Science、CNKI、万方；
        - 时间范围：2005–2025（反映近20年研究趋势）；
        - 关键词：healthcare workers, vaccine recommendation, non-NIP, influencing factors, China；
        - 纳入标准：涉及医护推荐行为、影响因素或干预措施的实证与综述文献；
        - 排除标准：不涉及医护人员的疫苗行为研究。

        ---
        2.2 分析框架与方法
        - 理论框架：
        - COM-B模型（Capability, Opportunity, Motivation → Behavior）分析行为形成与干预切入点；
        - 5A框架（Accessibility, Affordability, Awareness, Acceptance, Activation）分析系统性障碍与推动因素。
        - 方法：叙述性归纳（narrative synthesis）+ 主题分析（thematic analysis）。'''
    ],```


""" + current_time_prompt