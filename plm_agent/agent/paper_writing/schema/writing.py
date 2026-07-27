from pydantic import BaseModel, Field, validator
from typing import Tuple, Optional, List, Dict, Any
from enum import Enum

from llm.base_model import BaseLLM
from llm.azure_models import GPT4o
from .manuscript import WritingPurposeDetail, ManuscriptOutline


class SectionSpecification(BaseModel):
    """章节写作规格 - 基础配置"""
    section_name: str = Field(..., description="章节名称")
    target_word_count: Optional[int] = Field(default=None, gt=0, description="目标字数")
    max_review_rounds: int = Field(default=1, ge=1, le=5, description="最大审阅轮数")
    
    # LLM配置 - 所有章节采用一致的配置
    writing_llm: Optional[Any] = Field(default=None, description="写作LLM")
    writing_temperature: float = Field(default=0.3, ge=0, le=2, description="写作温度")
    writing_max_tokens: int = Field(default=8000, gt=0, description="写作最大token数")
    polishing_llm: Optional[Any] = Field(default=None, description="润色LLM")
    polishing_temperature: float = Field(default=0.2, ge=0, le=2, description="润色温度")
    polishing_max_tokens: int = Field(default=32000, gt=0, description="润色最大token数")
    
    # 数据源使用配置
    use_literature_search: bool = Field(default=False, description="是否使用文献搜索")
    use_data_insights: bool = Field(default=True, description="是否使用数据分析结果")
    use_document_insights: bool = Field(default=True, description="是否使用文档分析结果")
    use_rag: bool = Field(default=False, description="是否使用RAG检索")
    use_completed_section: bool = Field(default=False, description="是否使用已完成章节")
    
    # 引用配置
    require_citations: bool = Field(default=False, description="是否需要引用")
    citation_style: str = Field(default="APA", description="引用格式")
    
    class Config:
        extra = "forbid"
        arbitrary_types_allowed = True


class AbstractSectionSpecification(SectionSpecification):
    """摘要章节配置"""
    section_name: str = Field(default="Abstract", description="摘要章节")
    use_literature_search: bool = Field(default=False, description="摘要不需要文献搜索")
    use_data_insights: bool = Field(default=False, description="摘要不需要数据分析结果")
    use_document_insights: bool = Field(default=False, description="摘要不需要文档分析结果")
    use_rag: bool = Field(default=False, description="摘要不需要RAG检索")
    use_completed_section: bool = Field(default=True, description="摘要需要参考已完成章节")
    require_citations: bool = Field(default=False, description="摘要不需要引用")


class IntroductionSectionSpecification(SectionSpecification):
    """引言章节配置"""
    section_name: str = Field(default="Introduction", description="引言章节")
    use_literature_search: bool = Field(default=True, description="引言需要文献搜索")
    use_data_insights: bool = Field(default=False, description="引言不需要数据分析结果")
    use_document_insights: bool = Field(default=False, description="引言不需要文档分析结果")
    use_rag: bool = Field(default=False, description="引言不需要RAG检索")
    use_completed_section: bool = Field(default=True, description="引言需要参考已完成章节")
    require_citations: bool = Field(default=True, description="引言需要引用")



class MethodsSectionSpecification(SectionSpecification):
    """方法章节配置"""
    section_name: str = Field(default="Methods", description="方法章节")
    use_literature_search: bool = Field(default=False, description="方法不需要文献搜索")
    use_data_insights: bool = Field(default=True, description="方法需要数据分析结果")
    use_document_insights: bool = Field(default=True, description="方法需要文档分析结果")
    use_rag: bool = Field(default=False, description="方法不需要RAG检索")
    use_completed_section: bool = Field(default=False, description="方法不需要参考已完成章节")
    require_citations: bool = Field(default=False, description="摘要不需要引用")


class ResultsSectionSpecification(SectionSpecification):
    """结果章节配置"""
    section_name: str = Field(default="Results", description="结果章节")
    use_literature_search: bool = Field(default=False, description="结果不需要文献搜索")
    use_data_insights: bool = Field(default=True, description="结果需要数据分析结果")
    use_document_insights: bool = Field(default=True, description="结果需要文档分析结果")
    use_rag: bool = Field(default=False, description="结果不需要RAG检索")
    use_completed_section: bool = Field(default=False, description="结果不需要参考已完成章节")
    require_citations: bool = Field(default=False, description="结果不需要引用")

class DiscussionSectionSpecification(SectionSpecification):
    """讨论章节配置"""
    section_name: str = Field(default="Discussion", description="讨论章节")
    use_literature_search: bool = Field(default=True, description="讨论需要文献搜索")
    use_data_insights: bool = Field(default=True, description="讨论需要数据分析结果")
    use_document_insights: bool = Field(default=True, description="讨论需要文档分析结果")
    use_rag: bool = Field(default=False, description="讨论不需要RAG检索")
    use_completed_section: bool = Field(default=True, description="讨论需要参考已完成章节")
    require_citations: bool = Field(default=True, description="讨论需要引用")


class SectionSpecificationManager:
    """章节配置管理器"""
    SECTION_MAPPING = {
        "Abstract": AbstractSectionSpecification,
        "Introduction": IntroductionSectionSpecification,
        "Methods": MethodsSectionSpecification,
        "Results": ResultsSectionSpecification,
        "Discussion": DiscussionSectionSpecification,
        "Background": IntroductionSectionSpecification,
        "Main Topics": MethodsSectionSpecification,
        "Ethics": MethodsSectionSpecification,
        "Case Presentation": ResultsSectionSpecification,
        "Conclusions": DiscussionSectionSpecification,
    }

    @classmethod
    def get_section_specification(cls, section_name: str, writing_llm: BaseLLM = GPT4o, polishing_llm: BaseLLM = GPT4o, **overrides) -> SectionSpecification:
        """获取章节配置"""
        spec_class = cls.SECTION_MAPPING.get(section_name, SectionSpecification)
        spec_kwargs = {
            "section_name": section_name,
            "writing_llm": writing_llm,
            "polishing_llm": polishing_llm,
            **overrides,
        }

        return spec_class(**spec_kwargs)

    @classmethod
    def list_available_sections(cls) -> List[str]:
        """列出所有可用的章节名称"""
        return list(cls.SECTION_MAPPING.keys())


class DatasetInfoForWriting(BaseModel):
    """写作用的数据集信息 - 只包含写作需要的数据"""
    data_preview: List[Dict[str, Any]] = Field(..., description="数据预览")
    data_structure: Dict[str, str] = Field(..., description="数据结构")
    analysis_summaries: List[str] = Field(default_factory=list, description="分析总结")
    key_findings: List[str] = Field(default_factory=list, description="关键发现")
    statistical_methods: List[str] = Field(default_factory=list, description="统计方法")


class WritingInput(BaseModel):
    """写作输入"""
    writing_purpose: WritingPurposeDetail = Field(..., description="写作目的")
    study_type: str = Field(..., description="研究类型")
    publication_type: str = Field(..., description="发表类型")
    target_journal: str = Field(..., description="目标期刊")
    outline: Optional[ManuscriptOutline] = Field(default=None, description="手稿大纲")
    dataset_info: List[DatasetInfoForWriting] = Field(..., description="数据集文件")
    document_info: List[Dict[str, Any]] = Field(default_factory=list, description="文档内容")
    completed_sections: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, 
        description="已完成章节的内容，格式：{'section_name': section_content}"
    )