from typing import List, Optional, Any, Dict
from datetime import datetime

from ..schema.data_insight import DatasetAnalysisResult
from ..schema.manuscript import Section, Subsection, ManuscriptStatus, ManuscriptOutline, ManuscriptProfile, OutlineSection
from ..schema.writing import WritingInput, DatasetInfoForWriting
from ..presets.template import MANUSCRIPT_STRUCTURE, WRITING_STRUCTURE

def get_section_outline(outline: ManuscriptOutline, section_name: str) -> Optional[Any]:
    """
    Get section outline from manuscript outline
    
    Args:
        outline: Manuscript outline
        section_name: Name of the section to find
        
    Returns:
        Section outline if found, None otherwise
    """
    for section in outline.sections:
        if section.title.lower() == section_name.lower():
            return section
    return None


def combine_subsections(subsections: List[Subsection]) -> str:
    """
    Combine all subsections into a single content
    
    Args:
        subsections: List of subsections to combine
        
    Returns:
        Combined content as string
    """
    combined = []
    for subsection in subsections:
        combined.append(f"## {subsection.name}\n\n{subsection.content}")
    return "\n\n".join(combined)


def create_section(
    name: str,
    content: str,
    subsections: List[Subsection],
    profile: Any,
    dataset_citations: Optional[List[str]] = None,
    document_citations: Optional[List[str]] = None,
    completed_sections_citations: Optional[List[str]] = None,
    literature_citations: Optional[List[str]] = None
) -> Section:
    """
    Create a Section object
    
    Args:
        name: Section name
        content: Section content
        subsections: List of subsections
        profile: Manuscript profile (for future use)
        dataset_citations: Citations of dataset information
        document_citations: Citations of document information
        completed_sections_citations: Citations of completed sections
        literature_citations: Citations of literature search results
        
    Returns:
        Section object
    """
    return Section(
        name=name,
        content=content,
        word_count=count_words(content),
        subsections=subsections,
        dataset_citations=dataset_citations or [],
        document_citations=document_citations or [],
        completed_sections_citations=completed_sections_citations or [],
        literature_citations=literature_citations or [],
        status=ManuscriptStatus.DRAFT,
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp())
    )


def create_subsection(
    name: str,
    content: str,
    dataset_citations: Optional[List[str]] = None,
    document_citations: Optional[List[str]] = None,
    completed_sections_citations: Optional[List[str]] = None,
    literature_citations: Optional[List[str]] = None
) -> Subsection:
    """
    Create a Subsection object
    
    Args:
        name: Subsection name
        content: Subsection content
        dataset_citations: Citations of dataset information
        document_citations: Citations of document information
        completed_sections_citations: Citations of completed sections
        literature_citations: Citations of literature search results
        
    Returns:
        Subsection object
    """
    return Subsection(
        name=name,
        content=content,
        word_count=count_words(content),
        dataset_citations=dataset_citations or [],
        document_citations=document_citations or [],
        completed_sections_citations=completed_sections_citations or [],
        literature_citations=literature_citations or [],
        status=ManuscriptStatus.DRAFT,
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp())
    )


def count_words(text: str) -> int:
    """
    Count words in text
    
    Args:
        text: Text to count words in
        
    Returns:
        Number of words
    """
    return len(text.split())


def format_section_content(section_name: str, content: str) -> str:
    """
    Format section content with proper headers
    
    Args:
        section_name: Name of the section
        content: Raw content
        
    Returns:
        Formatted content with headers
    """
    return f"# {section_name}\n\n{content}"


def extract_keywords_from_text(text: str, max_keywords: int = 10) -> List[str]:
    """
    Extract keywords from text for literature search
    
    Args:
        text: Text to extract keywords from
        max_keywords: Maximum number of keywords to extract
        
    Returns:
        List of keywords
    """
    # Simple keyword extraction - can be enhanced with NLP libraries
    words = text.lower().split()
    # Remove common stop words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can'}
    keywords = [word for word in words if word not in stop_words and len(word) > 3]
    
    # Count frequency and return top keywords
    from collections import Counter
    keyword_counts = Counter(keywords)
    return [keyword for keyword, count in keyword_counts.most_common(max_keywords)]


def validate_content_length(content: str, target_length: Optional[int] = None, tolerance: float = 0.2) -> bool:
    """
    Validate if content length is within acceptable range
    
    Args:
        content: Content to validate
        target_length: Target word count
        tolerance: Acceptable deviation (e.g., 0.2 means ±20%)
        
    Returns:
        True if content length is acceptable
    """
    if target_length is None:
        return True
    
    actual_length = count_words(content)
    min_length = int(target_length * (1 - tolerance))
    max_length = int(target_length * (1 + tolerance))
    
    return min_length <= actual_length <= max_length


def sanitize_content(content: str) -> str:
    """
    Sanitize content by removing unwanted characters and formatting
    
    Args:
        content: Raw content
        
    Returns:
        Sanitized content
    """
    # Remove excessive whitespace
    import re
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    content = re.sub(r' +', ' ', content)
    
    # Remove leading/trailing whitespace
    content = content.strip()
    
    return content


def extract_citations_from_text(text: str) -> List[str]:
    """
    Extract citation patterns from text
    
    Args:
        text: Text to extract citations from
        
    Returns:
        List of citation patterns found
    """
    import re
    
    # Common citation patterns
    patterns = [
        r'\([A-Za-z]+\s+et\s+al\.\s+\d{4}\)',  # (Author et al. 2024)
        r'\([A-Za-z]+\s+\d{4}\)',              # (Author 2024)
        r'\[[A-Za-z]+\s+et\s+al\.\s+\d{4}\]',  # [Author et al. 2024]
        r'\[[A-Za-z]+\s+\d{4}\]',              # [Author 2024]
        r'[A-Za-z]+\s+et\s+al\.\s+\(\d{4}\)',  # Author et al. (2024)
        r'[A-Za-z]+\s+\(\d{4}\)',              # Author (2024)
    ]
    
    citations = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        citations.extend(matches)
    
    return list(set(citations))  # Remove duplicates 

def convert_dataset_for_writing(dataset_result: DatasetAnalysisResult) -> DatasetInfoForWriting:
    """将 DatasetAnalysisResult 转换为写作用的格式"""
    
    # 处理 analysis_summaries，确保是字符串列表
    analysis_summaries = []
    for result in dataset_result.analysis_results:
        if result.success and result.summary:
            # 如果 summary 是 TextBlock 对象，提取其 text 属性
            if hasattr(result.summary, 'text'):
                analysis_summaries.append(result.summary.text)
            elif isinstance(result.summary, str):
                analysis_summaries.append(result.summary)
            else:
                # 其他情况，转换为字符串
                analysis_summaries.append(str(result.summary))
    
    return DatasetInfoForWriting(
        data_preview=dataset_result.data_preview.data_preview,
        data_structure=dataset_result.data_preview.data_structure,
        analysis_summaries=analysis_summaries,
        key_findings=dataset_result.key_findings or [],
        statistical_methods=dataset_result.statistical_methods_used or []
    )

def convert_document_for_writing(document_content: Any) -> Dict[str, Any]:
    """将文档内容对象转换为写作用的字典格式"""
    if hasattr(document_content, 'dict'):
        # 如果是 Pydantic 模型，使用 dict() 方法
        return document_content.dict()
    elif hasattr(document_content, '__dict__'):
        # 如果是普通对象，使用 __dict__
        return document_content.__dict__
    else:
        # 其他情况，转换为字符串
        return {"content": str(document_content)}

def create_writing_input(
    profile: ManuscriptProfile,
    outline: ManuscriptOutline,
    dataset_analyses: List[DatasetAnalysisResult],
    document_contents: List[Any]
) -> WritingInput:
    """创建写作输入"""
    
    # 转换数据集为写作格式
    writing_datasets = [convert_dataset_for_writing(dataset) for dataset in dataset_analyses]
    
    # 转换文档内容为字典格式
    writing_documents = [convert_document_for_writing(doc) for doc in document_contents]
    
    return WritingInput(
        writing_purpose=profile.writing_purpose,
        study_type=profile.study_type.value,
        publication_type=profile.publication_type.value,
        target_journal=profile.writing_purpose.target_journal,
        outline=outline,
        dataset_info=writing_datasets or [],
        document_info=writing_documents or []
    )

def create_manuscript_outline(manuscript_profile: ManuscriptProfile) -> ManuscriptOutline:
    """根据manuscript_profile创建ManuscriptOutline"""
    
    study_type = manuscript_profile.study_type
    publication_type = manuscript_profile.publication_type
    target_journal = manuscript_profile.writing_purpose.target_journal
    
    # 从presets获取章节结构
    structure_key = (study_type, publication_type)
    if structure_key in MANUSCRIPT_STRUCTURE:
        section_names = MANUSCRIPT_STRUCTURE[structure_key]
    else:
        # 默认结构
        section_names = ["Title", "Abstract", "Introduction", "Methods", "Results", "Discussion", "References"]
    
    # 创建OutlineSection列表
    sections = []
    for i, section_name in enumerate(section_names):
        if section_name in ["Title", "Abstract", "References"]:
            # 这些是主章节
            level = 1
            word_estimate = "Variable"
        else:
            # 其他是主章节
            level = 1
            word_estimate = "500-1000 words"
        
        # 获取子章节结构
        subsection_key = (study_type, publication_type, section_name)
        subsections = []
        if subsection_key in WRITING_STRUCTURE:
            for subsection_name, subsection_words in WRITING_STRUCTURE[subsection_key]:
                subsections.append(OutlineSection(
                    title=subsection_name,
                    level=2,
                    word_estimate=subsection_words,
                    content_hints=[],
                    key_points=[],
                    writing_guidance=[],
                    section_id=f"subsection_{section_name.lower().replace(' ', '_')}_{subsection_name.lower().replace(' ', '_')}"
                ))
        
        # 创建主章节
        main_section = OutlineSection(
            title=section_name,
            level=level,
            word_estimate=word_estimate,
            content_hints=[],
            key_points=[],
            writing_guidance=[],
            section_id=f"section_{section_name.lower().replace(' ', '_')}"
        )
        sections.append(main_section)
        
        # 添加子章节
        sections.extend(subsections)
    
    # 计算总字数估计
    total_words = 0
    for section in sections:
        if section.word_estimate and section.word_estimate != "Variable":
            try:
                if "-" in section.word_estimate:
                    max_words = int(section.word_estimate.split("-")[1].split()[0])
                    total_words += max_words
                else:
                    words = int(section.word_estimate.split()[0])
                    total_words += words
            except (ValueError, IndexError):
                continue
    
    return ManuscriptOutline(
        study_type=study_type,
        publication_type=publication_type,
        target_journal=target_journal,
        sections=sections,
        total_word_estimate=f"{total_words} words",
        main_sections_count=len([s for s in sections if s.level == 1]),
        subsections_count=len([s for s in sections if s.level == 2]),
        writing_style=manuscript_profile.writing_purpose.writing_style,
        tone=manuscript_profile.writing_purpose.tone,
        focus_areas=manuscript_profile.writing_purpose.focus_areas,
        emphasis_points=manuscript_profile.writing_purpose.emphasis_points,
        outline_metadata={}
    )