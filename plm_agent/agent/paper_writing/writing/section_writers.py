from typing import Any, Dict
from .base_writer import BaseWriter
from ..schema.writing import SectionSpecification, WritingInput
from ..schema.manuscript import Section


class MethodsWriter(BaseWriter):
    """Methods section writer implementation"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build methods-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 方法章节润色要求

请特别注意以下要点：

1. **设计清晰**：清晰描述研究类型、设计方法和流程
2. **样本完整**：详细说明研究对象选择标准和特征
3. **数据准确**：准确描述数据收集工具、方法和质量控制
4. **变量明确**：明确定义研究变量和测量方法
5. **分析规范**：详细描述分析方法和统计技术
6. **伦理合规**：说明伦理批准和合规要求

确保方法描述足够详细，使读者能够理解研究过程并评估其可靠性。
"""
        else:
            return """
## Methods Section Polishing Requirements

Please pay special attention to:

1. **Clear Design**: Clearly describe study type, design methodology, and procedures
2. **Complete Sample**: Detail selection criteria and characteristics of study subjects
3. **Accurate Data**: Accurately describe data collection tools, methods, and quality control
4. **Clear Variables**: Clearly define study variables and measurement methods
5. **Standard Analysis**: Detail analytical methods and statistical techniques
6. **Ethical Compliance**: Explain ethical approvals and compliance requirements

Ensure the methods description is detailed enough for readers to understand the research process and evaluate its reliability.
"""


class ResultsWriter(BaseWriter):
    """Results section writer implementation"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build results-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 结果章节润色要求

请特别注意以下要点：

1. **客观呈现**：准确、客观地描述研究发现，避免主观解释
2. **重点突出**：突出最重要的发现和关键数据
3. **逻辑清晰**：按逻辑顺序组织结果，确保连贯性
4. **数据完整**：报告样本量、缺失数据等关键信息
5. **统计准确**：准确报告统计结果，包括效应量和置信区间

确保结果描述为后续讨论提供坚实基础。
"""
        else:
            return """
## Results Section Polishing Requirements

Please pay special attention to:

1. **Objective Presentation**: Accurately and objectively describe findings, avoid subjective interpretation
2. **Highlight Key Findings**: Emphasize the most important discoveries and key data
3. **Logical Organization**: Organize results logically with clear coherence
4. **Complete Data**: Report sample sizes, missing data, and other key information
5. **Statistical Accuracy**: Accurately report statistical results including effect sizes and confidence intervals

Ensure the results description provides a solid foundation for subsequent discussion.
"""


class IntroductionWriter(BaseWriter):
    """Introduction section writer implementation"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build introduction-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 引言章节润色要求

请特别注意以下要点：

1. **背景清晰**：清晰介绍研究背景和现状
2. **问题明确**：明确指出现有研究的不足和知识缺口
3. **目标突出**：突出研究目标和假设
4. **逻辑连贯**：确保各部分之间的逻辑连贯性
5. **文献恰当**：恰当引用相关文献，避免过度引用

确保引言为读者提供充分的研究背景和动机。
"""
        else:
            return """
## Introduction Section Polishing Requirements

Please pay special attention to:

1. **Clear Background**: Clearly introduce research background and current status
2. **Clear Problem**: Clearly identify gaps in existing research and knowledge
3. **Highlight Objectives**: Emphasize research objectives and hypotheses
4. **Logical Flow**: Ensure logical coherence between sections
5. **Appropriate Citations**: Appropriately cite relevant literature, avoid over-citation

Ensure the introduction provides readers with sufficient research background and motivation.
"""


class DiscussionWriter(BaseWriter):
    """Discussion section writer implementation"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build discussion-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 讨论章节润色要求

请特别注意以下要点：

1. **结果解释**：深入解释主要发现及其意义
2. **文献对比**：与现有文献进行对比和讨论
3. **机制探讨**：探讨可能的机制和解释
4. **局限性**：客观讨论研究的局限性
5. **未来方向**：提出未来研究方向和临床应用

确保讨论深入且有见地，为研究提供充分的理论和实践意义。
"""
        else:
            return """
## Discussion Section Polishing Requirements

Please pay special attention to:

1. **Result Interpretation**: Deeply interpret main findings and their significance
2. **Literature Comparison**: Compare and discuss with existing literature
3. **Mechanism Discussion**: Explore possible mechanisms and explanations
4. **Limitations**: Objectively discuss study limitations
5. **Future Directions**: Propose future research directions and clinical applications

Ensure the discussion is insightful and provides sufficient theoretical and practical significance.
"""


class AbstractWriter(BaseWriter):
    """Abstract section writer implementation"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build abstract-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 摘要章节润色要求

请特别注意以下要点：

1. **结构完整**：确保包含背景、方法、结果、结论的完整结构
2. **信息准确**：准确反映研究的主要内容和发现
3. **语言简洁**：使用简洁明了的语言，避免冗余
4. **重点突出**：突出最重要的发现和结论
5. **字数控制**：控制在目标期刊要求的字数范围内

确保摘要简洁、准确、完整地概括整个研究。
"""
        else:
            return """
## Abstract Section Polishing Requirements

Please pay special attention to:

1. **Complete Structure**: Ensure complete structure including background, methods, results, conclusions
2. **Accurate Information**: Accurately reflect the main content and findings of the study
3. **Concise Language**: Use concise and clear language, avoid redundancy
4. **Highlight Key Points**: Emphasize the most important findings and conclusions
5. **Word Count Control**: Keep within the target journal's word count requirements

Ensure the abstract concisely, accurately, and completely summarizes the entire study.
"""


class BackgroundWriter(BaseWriter):
    """Background section writer implementation (for brief reports)"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)

    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build background-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 背景章节润色要求

请特别注意以下要点：

1. **问题明确**：明确说明研究问题和背景
2. **现状简洁**：简洁描述当前研究现状
3. **动机清晰**：清晰说明研究动机和必要性
4. **目标突出**：突出研究目标和预期贡献
5. **语言精炼**：使用精炼的语言，适合简报格式

确保背景简洁明了，为简报提供充分的研究背景。
"""
        else:
            return """
## Background Section Polishing Requirements

Please pay special attention to:

1. **Clear Problem**: Clearly state the research problem and background
2. **Concise Status**: Briefly describe current research status
3. **Clear Motivation**: Clearly explain research motivation and necessity
4. **Highlight Objectives**: Emphasize research objectives and expected contributions
5. **Refined Language**: Use refined language suitable for brief report format

Ensure the background is concise and clear, providing sufficient research context for the brief report.
"""


class ConclusionsWriter(BaseWriter):
    """Conclusions section writer implementation (for brief reports)"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build conclusions-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 结论章节润色要求

请特别注意以下要点：

1. **主要发现**：突出主要研究发现和关键结果
2. **意义明确**：明确说明研究意义和贡献
3. **应用前景**：简要说明潜在应用和影响
4. **语言简洁**：使用简洁有力的语言
5. **逻辑清晰**：确保结论逻辑清晰，与结果一致

确保结论简洁有力，突出研究的核心贡献。
"""
        else:
            return """
## Conclusions Section Polishing Requirements

Please pay special attention to:

1. **Key Findings**: Emphasize main research findings and key results
2. **Clear Significance**: Clearly state research significance and contributions
3. **Application Prospects**: Briefly explain potential applications and impact
4. **Concise Language**: Use concise and powerful language
5. **Clear Logic**: Ensure conclusions are logically clear and consistent with results

Ensure conclusions are concise and powerful, highlighting the core contributions of the research.
"""


class MainTopicsWriter(BaseWriter):
    """Main Topics section writer implementation (for narrative reviews)"""
    
    def __init__(self, settings: SectionSpecification):
        super().__init__(settings)
    
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build main topics-specific polishing instructions"""
        if self.language == "zh-CN":
            return """
## 主要主题章节润色要求

请特别注意以下要点：

1. **主题清晰**：清晰组织各个主题和子主题
2. **内容全面**：全面涵盖相关研究领域
3. **逻辑连贯**：确保主题之间的逻辑连贯性
4. **文献整合**：有效整合和总结相关文献
5. **观点平衡**：平衡呈现不同观点和争议

确保主要主题章节全面、系统地梳理研究领域。
"""
        else:
            return """
## Main Topics Section Polishing Requirements

Please pay special attention to:

1. **Clear Topics**: Clearly organize various topics and subtopics
2. **Comprehensive Content**: Comprehensively cover relevant research areas
3. **Logical Coherence**: Ensure logical coherence between topics
4. **Literature Integration**: Effectively integrate and summarize relevant literature
5. **Balanced Perspectives**: Balance different viewpoints and controversies

Ensure the main topics section comprehensively and systematically reviews the research field.
"""

