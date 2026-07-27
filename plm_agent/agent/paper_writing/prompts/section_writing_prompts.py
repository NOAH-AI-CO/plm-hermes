"""
Section Writing Prompts

定义各个章节的写作提示词
"""

from typing import Dict, Any


class SectionWritingPrompts:
    """章节写作提示词类"""
    
    @staticmethod
    def get_section_instructions(section_name: str) -> str:
        """获取章节特定的写作指导"""
        instructions = {
            "Introduction": """
引言部分应包含：
1. 研究背景和现状
2. 研究问题和目标
3. 研究意义和创新点
4. 论文结构概述
            """,
            
            "Methodology": """
方法部分应包含：
1. 研究设计
2. 参与者/样本
3. 数据收集方法
4. 数据分析方法
5. 伦理考虑
            """,
            
            "Results": """
结果部分应包含：
1. 描述性统计
2. 主要发现
3. 统计检验结果
4. 图表说明
            """,
            
            "Discussion": """
讨论部分应包含：
1. 主要发现解释
2. 与现有研究比较
3. 研究局限性
4. 未来研究方向
5. 实际应用意义
6. 结论总结（作为讨论的最后部分）
            """,
            
            "Background": """
背景部分应包含：
1. 研究领域概述
2. 相关理论背景
3. 现有研究综述
4. 研究空白识别
            """,
            
            "Main Topics": """
主要话题部分应包含：
1. 核心概念定义
2. 关键理论框架
3. 主要研究问题
4. 研究假设
            """,
            
            "Ethics": """
伦理部分应包含：
1. 伦理审批信息
2. 知情同意过程
3. 数据保护措施
4. 利益冲突声明
            """,
            
            "Case Presentation": """
病例展示部分应包含：
1. 病例基本信息
2. 临床表现
3. 诊断过程
4. 治疗方案
5. 治疗结果
            """,
            
            "Conclusions": """
结论部分应包含：
1. 主要发现总结
2. 研究贡献
3. 实际意义
4. 未来展望
            """
        }
        
        return instructions.get(section_name, "")
    
    @staticmethod
    def get_section_review_instructions(section_name: str) -> str:
        """获取章节特定的审查指导"""
        review_instructions = {
            "Introduction": """
请审查引言部分是否：
1. 清晰阐述了研究背景和问题
2. 明确提出了研究目标
3. 说明了研究意义
4. 概述了论文结构
            """,
            
            "Methodology": """
请审查方法部分是否：
1. 详细描述了研究设计
2. 明确了参与者/样本信息
3. 说明了数据收集过程
4. 描述了分析方法
5. 包含了伦理考虑
            """,
            
            "Results": """
请审查结果部分是否：
1. 客观呈现了数据
2. 包含了必要的统计信息
3. 清晰描述了主要发现
4. 正确解释了图表
            """,
            
            "Discussion": """
请审查讨论部分是否：
1. 深入解释了主要发现
2. 与现有研究进行了比较
3. 承认了研究局限性
4. 提出了未来方向
5. 总结了实际意义
            """,
            
            "Background": """
请审查背景部分是否：
1. 全面概述了研究领域
2. 建立了理论背景
3. 综述了相关研究
4. 识别了研究空白
            """,
            
            "Main Topics": """
请审查主要话题部分是否：
1. 明确定义了核心概念
2. 建立了理论框架
3. 提出了研究问题
4. 形成了研究假设
            """,
            
            "Ethics": """
请审查伦理部分是否：
1. 包含了伦理审批信息
2. 描述了知情同意过程
3. 说明了数据保护措施
4. 声明了利益冲突
            """,
            
            "Case Presentation": """
请审查病例展示部分是否：
1. 提供了完整的病例信息
2. 详细描述了临床表现
3. 说明了诊断过程
4. 描述了治疗方案
5. 报告了治疗结果
            """,
            
            "Conclusions": """
请审查结论部分是否：
1. 准确总结了主要发现
2. 强调了研究贡献
3. 说明了实际意义
4. 提出了未来展望
            """
        }
        
        return review_instructions.get(section_name, "")
    
    @staticmethod
    def build_section_prompt(
        section_name: str,
        manuscript_profile: Dict[str, Any],
        outline: Dict[str, Any],
        data_insights: Dict[str, Any] = None,
        document_insights: Dict[str, Any] = None,
        literature_search_results: Dict[str, Any] = None,
        rag_context: str = "",
        config: Dict[str, Any] = None
    ) -> str:
        """构建章节写作的完整提示词"""
        
        # 基础提示词
        prompt = f"""
你是一位专业的学术论文写作专家。请根据以下信息撰写论文的{section_name}部分。

## 论文基本信息
- 标题: {manuscript_profile.get('title', 'N/A')}
- 研究类型: {manuscript_profile.get('study_type', 'N/A')}
- 发表类型: {manuscript_profile.get('publication_type', 'N/A')}
- 目标期刊: {manuscript_profile.get('target_journal', 'N/A')}
- 研究领域: {manuscript_profile.get('research_field', 'N/A')}
- 关键词: {', '.join(manuscript_profile.get('keywords', []))}

## 论文大纲
{outline.get('sections', [])}

## 写作要求
{SectionWritingPrompts.get_section_instructions(section_name)}

## 写作指导
{manuscript_profile.get('writing_guidance', '')}
"""
        
        # 添加数据洞察（如果配置允许）
        if config and config.get('use_data_insights') and data_insights:
            prompt += f"""
## 数据分析洞察
{data_insights}
"""
        
        # 添加文档洞察（如果配置允许）
        if config and config.get('use_document_insights') and document_insights:
            prompt += f"""
## 文档分析洞察
{document_insights}
"""
        
        # 添加文献搜索结果（如果配置允许）
        if config and config.get('use_literature_search') and literature_search_results:
            prompt += f"""
## 相关文献
{literature_search_results}
"""
        
        # 添加RAG上下文（如果配置允许）
        if config and config.get('use_rag') and rag_context:
            prompt += f"""
## 相关背景信息
{rag_context}
"""
        
        prompt += f"""
请根据以上信息撰写{section_name}部分。要求：
1. 内容准确、逻辑清晰
2. 语言学术化、专业化
3. 符合目标期刊的写作风格
4. 适当引用相关文献
5. 字数控制在合理范围内

请开始写作：
"""
        
        return prompt
    
    @staticmethod
    def build_review_prompt(
        section_name: str,
        section_content: str,
        manuscript_profile: Dict[str, Any],
        config: Dict[str, Any] = None
    ) -> str:
        """构建章节审查的提示词"""
        
        prompt = f"""
你是一位专业的学术论文审查专家。请审查以下{section_name}部分的内容。

## 论文基本信息
- 标题: {manuscript_profile.get('title', 'N/A')}
- 研究类型: {manuscript_profile.get('study_type', 'N/A')}
- 发表类型: {manuscript_profile.get('publication_type', 'N/A')}
- 目标期刊: {manuscript_profile.get('target_journal', 'N/A')}

## 审查内容
{section_content}

## 审查标准
{SectionWritingPrompts.get_section_review_instructions(section_name)}

请从以下方面进行审查：
1. 内容完整性
2. 逻辑结构
3. 语言表达
4. 学术规范
5. 与论文整体的协调性

请提供具体的修改建议：
"""
        
        return prompt 