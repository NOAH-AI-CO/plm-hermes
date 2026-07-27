from typing import AsyncGenerator, Dict, List, Any
from abc import ABC, abstractmethod
from datetime import datetime

from ..schema.manuscript import Section, Subsection
from ..schema.writing import SectionSpecification, WritingInput
from ..utils.writing import (
    get_section_outline,
    combine_subsections,
    create_section,
    create_subsection,
    count_words
)
from i18n.languages import normalize as _norm

class BaseWriter(ABC):
    """Base class for paper writing with subsection-based workflow"""
    def __init__(self, settings: SectionSpecification):
        self.settings = settings
        self.language = _norm(getattr(settings, 'language', ''))
        # Validate specification
        self._validate_specification()

    def _validate_specification(self):
        """Validate the writing specification"""
        if not self.settings.section_name:
            raise ValueError("Section name is required")
    
        for field_name in ['writing_llm', 'polishing_llm']:
            llm = getattr(self.settings, field_name)
            if llm is not None and not hasattr(llm, '__call__'):
                raise ValueError(f"{field_name} must be callable (have __call__ method)")

        temperature_fields = [
            'writing_temperature', 'polishing_temperature'
        ]
    
        for field_name in temperature_fields:
            temp = getattr(self.settings, field_name)
            if temp < 0 or temp > 2:
                raise ValueError(f"{field_name} must be between 0 and 2")

    async def write_section(self, writing_input: WritingInput) -> AsyncGenerator[Section, None]:
        """Write the Methods section"""
        async for section_in_progress in self._write_section_with_subsections(writing_input):
            yield section_in_progress
        async for polished_section_in_progress in self._polish_section(section_in_progress):
            yield polished_section_in_progress

    async def _build_writing_context(self, writing_input: WritingInput, section_outline: Any) -> Dict[str, Any]:
        """Build writing context for writing"""
        if not writing_input:
            raise ValueError("Writing input is required")
        context = {
            "writing_purpose": writing_input.writing_purpose,
            "study_type": writing_input.study_type,
            "publication_type": writing_input.publication_type,
            "target_journal": writing_input.target_journal
        }
    
        if self.settings.use_data_insights and writing_input.dataset_info:
            context["dataset_info"] = writing_input.dataset_info
        if self.settings.use_document_insights and writing_input.document_info:
            context["document_info"] = writing_input.document_info
        if self.settings.use_completed_section and writing_input.completed_sections:
            context["completed_sections"] = writing_input.completed_sections

        if self.settings.use_literature_search:
            literature_results = await self._search_literature_for_section(section_outline=section_outline, writing_input=writing_input)
            context["literature_search"] = literature_results["citations"]

        return context

    def _generate_prompt_parts_from_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        available_context_parts = []
        if "dataset_info" in context:
            available_context_parts.append("dataset_info")
        if "document_info" in context:
            available_context_parts.append("document_info")
        if "completed_sections" in context:
            available_context_parts.append("completed_sections")
        if "literature_search" in context:
            available_context_parts.append("literature_search")
        
        if self.language == "zh-CN":
            prompt_parts = {
                "dataset_info": "数据集信息",
                "document_info": "文档信息",
                "completed_sections": "已完成章节",
                "literature_search": "文献搜索"
            }
        else:
            prompt_parts = {
                "dataset_info": "Dataset Information",
                "document_info": "Document Information",
                "completed_sections": "Completed Sections",
                "literature_search": "Literature Search"
            }
        
        return {prompt_parts[part]: context[part] for part in available_context_parts}

    def _build_base_subsection_prompt(self, subsection_outline: Any, writing_context: Dict[str, Any]) -> str:
        context_parts = self._generate_prompt_parts_from_context(writing_context)

        context_prompt_parts = []
        for part, content in context_parts.items():
            context_prompt_parts.append(f"{part}: \n{content}")
        
        context_prompt = "\n".join(context_prompt_parts) if len(context_prompt_parts) > 0 else "No specific data available"
        
        if self.language == "zh-CN":
            prompt = f"""
请撰写{self.settings.section_name}章节下的子章节{subsection_outline.title}内容。

## 研究背景
这是一项关于{writing_context["study_type"]}的研究，旨在{writing_context["writing_purpose"]}。

## 写作要求
- 字数要求：{subsection_outline.word_estimate}
- 关键点：{subsection_outline.key_points}

## 可用数据（请基于这些数据写作）
{context_prompt}

## 写作指导
请严格基于上述数据和分析结果进行写作，确保：
1. 所有论述都有数据支撑
2. 准确引用和解释数据
3. 基于数据得出合理结论
4. 与已完成章节保持一致性
5. 符合学术写作规范
6. 如果没有可用数据，请根据研究背景和写作要求进行写作

## 输出格式
请严格按照以下JSON格式输出：
{{
    "content": "子章节的完整内容，使用Markdown格式。在内容中要明确引用提供的数据和文档信息。",
    "citations": {{
        "dataset": ["对数据集信息的引用说明，如：'根据数据集分析显示，样本量为500例'"],
        "document": ["对文档信息的引用说明，如：'文档内容表明，研究采用随机对照设计'"],
        "completed_sections": ["对已完成章节的引用说明，如：'与引言部分保持一致，本研究...'"],
        "literature": ["对文献搜索结果的引用说明，如：'根据相关文献，Smith et al. (2023)发现...'"]
    }}
}}

注意：
- 如果某种数据源没有被引用，对应的数组可以为空 []
- 只记录实际被引用的数据源
- 确保所有引用的数据源都在对应的数组中有所说明
"""
        else:
            prompt = f"""
Please write the {self.settings.section_name} section's subsection {subsection_outline.title} content.

## Research Background
This is a study about {writing_context["study_type"]} aiming to {writing_context["writing_purpose"]}.

## Writing Requirements
- Word Estimate: {subsection_outline.word_estimate}
- Key Points: {subsection_outline.key_points}

## Available Data (Please write based on these data)
{context_prompt}

## Writing Instructions
Please strictly write based on the above data and analysis results, ensuring:
1. All arguments are supported by data
2. Accurately cite and explain data
3. Draw reasonable conclusions based on data
4. Maintain consistency with completed sections
5. Follow academic writing standards
6. If no available data, please write based on the research background and writing requirements

## Output Format
Please output strictly in the following JSON format:
{{
    "content": "Complete subsection content in Markdown format. Clearly cite the provided data and document information in the content.",
    "citations": {{
        "dataset": ["Citation explanation for dataset information, e.g.: 'According to dataset analysis, the sample size was 500'"],
        "document": ["Citation explanation for document information, e.g.: 'Document content shows that the study used randomized controlled design'"],
        "completed_sections": ["Citation explanation for completed sections, e.g.: 'Consistent with the introduction section, this study...'"],
        "literature": ["Citation explanation for literature search results, e.g.: 'According to relevant literature, Smith et al. (2023) found...'"]
    }}
}}

Note:
- If a data source is not cited, the corresponding array can be empty []
- Only record data sources that are actually cited
- Ensure all cited data sources are explained in the corresponding arrays
"""
        return prompt
    
    async def _write_section_with_subsections(self, writing_input: WritingInput) -> AsyncGenerator[Section, None]:
        if not writing_input.outline:
            raise ValueError("Writing input outline is required")
            
        section_outline = get_section_outline(writing_input.outline, self.settings.section_name)
        if not section_outline:
            raise ValueError(f"Section '{self.settings.section_name}' not found in outline")
        
        subsections_outline = writing_input.outline.get_subsections(self.settings.section_name)

        writing_context = await self._build_writing_context(writing_input=writing_input, section_outline=section_outline)
      
        subsections = []
        for subsection_outline in subsections_outline:
            subsection = None
            subsections.append(subsection)
            async for subsection_in_progress in self._write_subsection(subsection_outline, writing_context):
                subsections[-1] = subsection_in_progress
                # Combine all subsections
                combined_content = combine_subsections(subsections)
                
                # Collect all citations from subsections
                all_dataset_citations = []
                all_document_citations = []
                all_completed_sections_citations = []
                all_literature_citations = []
                
                for subsection in subsections:
                    if subsection.dataset_citations:
                        all_dataset_citations.extend(subsection.dataset_citations)
                    if subsection.document_citations:
                        all_document_citations.extend(subsection.document_citations)
                    if subsection.completed_sections_citations:
                        all_completed_sections_citations.extend(subsection.completed_sections_citations)
                    if subsection.literature_citations:
                        all_literature_citations.extend(subsection.literature_citations)
                
                # Create final section
                yield create_section(
                    name=self.settings.section_name,
                    content=combined_content,
                    subsections=subsections,
                    profile=writing_input,  # Use writing_input as profile
                    dataset_citations=all_dataset_citations,
                    document_citations=all_document_citations,
                    completed_sections_citations=all_completed_sections_citations,
                    literature_citations=all_literature_citations
                )
        combined_content = combine_subsections(subsections)
        
        # Collect all citations from subsections
        all_dataset_citations = []
        all_document_citations = []
        all_completed_sections_citations = []
        all_literature_citations = []
        
        for subsection in subsections:
            if subsection.dataset_citations:
                all_dataset_citations.extend(subsection.dataset_citations)
            if subsection.document_citations:
                all_document_citations.extend(subsection.document_citations)
            if subsection.completed_sections_citations:
                all_completed_sections_citations.extend(subsection.completed_sections_citations)
            if subsection.literature_citations:
                all_literature_citations.extend(subsection.literature_citations)
        
        # Create final section
        yield create_section(
            name=self.settings.section_name,
            content=combined_content,
            subsections=subsections,
            profile=writing_input,  # Use writing_input as profile
            dataset_citations=all_dataset_citations,
            document_citations=all_document_citations,
            completed_sections_citations=all_completed_sections_citations,
            literature_citations=all_literature_citations
        )

    
    async def _write_subsection(self, subsection_outline: Any, writing_context: Dict[str, Any]) -> AsyncGenerator[Subsection, None]:
        """Write a single subsection"""
        prompt = self._build_base_subsection_prompt(subsection_outline, writing_context)
        
        async for output_in_progress in self._generate_content_with_llm(prompt, "writing"):
            yield create_subsection(
                name=subsection_outline.title,
                content=output_in_progress,
            )
            
        # 解析LLM输出
        parsed_result = self._parse_llm_output(output_in_progress)
        
        yield create_subsection(
            name=subsection_outline.title,
            content=parsed_result["content"],
            dataset_citations=parsed_result["dataset_citations"],
            document_citations=parsed_result["document_citations"],
            completed_sections_citations=parsed_result["completed_sections_citations"],
            literature_citations=parsed_result["literature_citations"]
        )

    async def _polish_section(self, section: Section) -> AsyncGenerator[Section, None]:
        """Polish the entire section content and subsection names in one call"""
        base_prompt = self._build_base_polishing_prompt(section)
        polishing_instruction_prompt = self._build_polishing_instruction_prompt(section)
        prompt = base_prompt + polishing_instruction_prompt
        
        # Polish using LLM
        async for output_in_progress in self._generate_content_with_llm(prompt, "polishing"):
            section.content = output_in_progress
            yield section
            
        # Parse the polished output (expecting JSON format for this case)
        try:
            import json
            parsed = json.loads(output_in_progress)
            
            # Update the content
            section.content = parsed.get("content", section.content)
            section.word_count = count_words(section.content)
            
            # Update subsection names if provided
            if "subsection_titles" in parsed and section.subsections:
                new_names = parsed["subsection_titles"]
                for i, subsection in enumerate(section.subsections):
                    if i < len(new_names):
                        subsection.name = new_names[i]
                        subsection.updated_at = int(datetime.now().timestamp())

            section.updated_at = int(datetime.now().timestamp())

        except json.JSONDecodeError:
            # Fallback: treat as plain content polish
            section.content = output_in_progress
            section.word_count = count_words(output_in_progress)
            section.updated_at = int(datetime.now().timestamp())
        
        yield section

    def _build_base_polishing_prompt(self, section: Section) -> str:
        """Build base polishing prompt that can be extended by specific writers"""
        # Build subsection information for the prompt
        subsection_info = []
        if section.subsections:
            for subsection in section.subsections:
                subsection_info.append(f"Subsection name: {subsection.name}\nSubsection content: {subsection.content}")

        if self.language == "zh-CN":
            base_prompt = f"""
            请润色下述{self.settings.section_name}章节，确保逻辑清晰，语气连贯，符合学术写作规范：
            
            {chr(10).join(subsection_info) if subsection_info else "章节内容: " + section.content}

            如有必要，可对子章节标题进行修改，使其更符合学术写作规范。
            
            请返回JSON格式:
            {{
                "content": "润色后的章节内容",
                "subsection_titles": ["润色后的子章节标题1", "润色后的子章节标题2", ...]
            }}
            
            如果没有子章节，只返回内容:
            {{
                "content": "润色后的章节内容"
            }}
            """
        else:
            base_prompt = f"""
            Polish this {self.settings.section_name} section to improve clarity, flow, and academic tone:
            
            {chr(10).join(subsection_info) if subsection_info else "Section content: " + section.content}
            
            If necessary, modify the subsection titles to make them more academic and professional.
            
            Please return in JSON format:
            {{
                "content": "Polished section content",
                "subsection_titles": ["Polished subsection title 1", "Polished subsection title 2", ...]
            }}
            
            If there are no subsections, return only the content:
            {{
                "content": "Polished section content"
            }}
            """
        return base_prompt

    @abstractmethod
    def _build_polishing_instruction_prompt(self, section: Section) -> str:
        """Build prompt for section polishing - to be implemented by specific writers"""
        pass

    async def _generate_content_with_llm(self, prompt: str, content_type: str = "writing") -> AsyncGenerator[str, None]:
        
        if content_type == "writing":
            llm = self.settings.writing_llm()
            temperature = self.settings.writing_temperature
            max_tokens = self.settings.writing_max_tokens
        elif content_type == "polishing":
            llm = self.settings.polishing_llm()
            temperature = self.settings.polishing_temperature
            max_tokens = self.settings.polishing_max_tokens
        else:
            raise ValueError(f"Unsupported content type: {content_type}")

        if llm is None:
            raise ValueError(f"LLM for {content_type} is not configured")
        
        # 调用LLM生成内容
        try:
            print(f"开始调用LLM进行{content_type}...")
            print(f"LLM类型: {type(llm)}")
            print(f"温度: {temperature}, 最大token: {max_tokens}")
            
            # 使用stream call
            print("使用stream_call方法...")
            print(f"提示词长度: {len(prompt)}")
            response_content = ""
            async for chunk in llm.stream_call(
                user_prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens  # 增加token数量
            ):
                print(f"收到chunk: {chunk}")
                response_content += chunk
                yield response_content
            
            print(f"完整响应长度: {len(response_content)}")
            print(f"完整响应: {response_content}")
            
            if not response_content:
                raise RuntimeError("LLM stream call returned empty content")
            
            yield response_content
                
        except Exception as e:
            raise RuntimeError(f"Failed to generate {content_type} content: {str(e)}")

    def _parse_llm_output(self, llm_output: str) -> Dict[str, Any]:
        """解析LLM的JSON输出"""
        import json
        try:
            parsed = json.loads(llm_output)
            
            # 处理嵌套的citations结构
            citations = parsed.get("citations", {})
            
            return {
                "content": parsed.get("content", ""),
                "dataset_citations": citations.get("dataset", []),
                "document_citations": citations.get("document", []),
                "completed_sections_citations": citations.get("completed_sections", []),
                "literature_citations": citations.get("literature", [])
            }
        except json.JSONDecodeError:
            return {
                "content": llm_output,
                "dataset_citations": [],
                "document_citations": [],
                "completed_sections_citations": [],
                "literature_citations": []
            }

    async def _search_literature_for_section(self, section_outline: Any, writing_input: WritingInput) -> Dict[str, Any]:
        target_scopes = self._determine_literature_scopes_for_section(section_outline)
        context_inputs = self._prepare_literature_context_inputs_for_section(section_outline, writing_input)
    
        from ..analyzer.literature_analyzer import LiteratureSearchPipeline
        from ..clients.semantic_scholar import SemanticScholarClient
        from ..clients.pubmed import PubMedClient
    
        semantic_client = SemanticScholarClient(top_k=3)
        pubmed_client = PubMedClient(email='yichen.li@noahai.co', top_k_results=3)
    
        pipeline = LiteratureSearchPipeline(
            context_inputs=context_inputs,
            target_scopes=target_scopes,
            semantic_client=semantic_client,
            pubmed_client=pubmed_client,
            top_k=3
        )

        query_result = await pipeline.generate_search_queries()
        
        await pipeline.retrieve_citations()
    
        citations = pipeline.get_filtered_citations(
            total=20,
            min_influence=0,
            sort_by_similarity=True)
    
        return {
            "query_result": query_result,
            "citations": citations,
            "target_scopes": target_scopes,
            "context_inputs": context_inputs
        }
    
    def _determine_literature_scopes_for_section(self, section_outline: Any) -> List[str]:
        """Determine which literature scopes to search for based on section"""
        section_title = section_outline.title.lower()
        
        # Map section titles to literature scopes
        scope_mapping = {
            "introduction": ["background", "questions"],
            "background": ["background"],
            "literature review": ["background", "methods", "results"],
            "methods": ["methods"],
            "methodology": ["methods"],
            "results": ["results"],
            "findings": ["results"],
            "discussion": ["results", "background"],
            "conclusion": ["results", "background"],
            "limitations": ["background"],
            "future work": ["background"],
            "data": ["dataset"],
            "dataset": ["dataset"],
            "participants": ["dataset"],
            "sample": ["dataset"],
            "statistical analysis": ["methods"],
            "analysis": ["methods", "results"]
        }
        
        # Find matching scopes
        for key, scopes in scope_mapping.items():
            if key in section_title:
                return scopes
        
        # Default scopes
        return ["background", "methods", "results"]
    
    def _prepare_literature_context_inputs_for_section(self, section_outline: Any, writing_input: WritingInput) -> Dict[str, str]:
        """Prepare context inputs for literature search at section level"""
        target_scopes = self._determine_literature_scopes_for_section(section_outline)
        context_inputs = {}
        
        # Prepare context for each scope
        for scope in target_scopes:
            context_inputs[scope] = f"""
            Study Type: {writing_input.study_type}
            Publication Type: {writing_input.publication_type}
            Section: {self.settings.section_name}
            Content Hints: {', '.join(getattr(section_outline, 'content_hints', []))}
            Key Points: {', '.join(getattr(section_outline, 'key_points', []))}
            Writing Purpose: {getattr(writing_input, 'writing_purpose', '')}
            """
        
        return context_inputs