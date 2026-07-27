"""
统一的枚举定义

包含系统中使用的所有枚举类型，避免重复定义
"""

from enum import Enum


class FileType(str, Enum):
    """文件类型枚举"""
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    HTML = "html"
    MARKDOWN = "markdown"
    EXCEL = "xlsx"
    CSV = "csv"


class StudyType(str, Enum):
    """研究类型枚举"""
    RCT = "Randomized Controlled Trial"
    NON_RANDOMIZED_INTERVENTION = "Non-Randomized Intervention Study"
    COHORT = "Cohort Study"
    CASE_CONTROL = "Case-Control Study"
    CROSS_SECTIONAL = "Cross-Sectional Study"
    CASE_OBSERVATION = "Case Report / Series"
    PROGNOSTIC = "Prognostic Study"
    DIAGNOSTIC = "Diagnostic Study"
    SYSTEMATIC_REVIEW = "Systematic Review"
    NARRATIVE_REVIEW = "Narrative Review"
    META_ANALYSIS = "Meta-Analysis"


class PublicationType(str, Enum):
    """发表类型枚举"""
    ORIGINAL_RESEARCH = "Original Research"       # 包含 RCT, Cohort, Case-Control, Modeling 等
    BRIEF_REPORT = "Brief Report"                 # 精简型 Original Research
    CASE_REPORT = "Case Report"                   # 单例报告（结构自由）
    CASE_SERIES = "Case Series"                   # 多例观察（结构自由）
    REVIEW = "Review Article"                     # Narrative Review, Systematic Review, Meta-analysis 可映射为 StudyType
    PROTOCOL = "Protocol"                         # 描述研究设计，无结果
    DATA_NOTE = "Data Note"                       # 强调数据描述/数据库
    TECHNICAL_REPORT = "Technical Report"         # 偏算法/建模/工具说明
    LETTER = "Letter to the Editor"               # 有回应性，可为评论、意见等
    OPINION = "Opinion / Commentary / Perspective" # 合并 editorial, commentary, perspective 等栏目


class WritingPurpose(str, Enum):
    """写作目的或方向"""
    ORIGINAL_RESEARCH = "Original Research"
    LITERATURE_REVIEW = "Literature Review"
    METHODOLOGY = "Methodology Development"
    CASE_STUDY = "Case Study"
    META_ANALYSIS = "Meta-Analysis"
    SYSTEMATIC_REVIEW = "Systematic Review"
    PROTOCOL = "Study Protocol"
    DATA_DESCRIPTION = "Data Description"
    TECHNICAL_REPORT = "Technical Report"
    OPINION_COMMENTARY = "Opinion/Commentary"
    LETTER_RESPONSE = "Letter/Response"
    BRIEF_COMMUNICATION = "Brief Communication"


class ResearchField(str, Enum):
    """研究领域"""
    CLINICAL_MEDICINE = "Clinical Medicine"
    BASIC_SCIENCE = "Basic Science"
    EPIDEMIOLOGY = "Epidemiology"
    PUBLIC_HEALTH = "Public Health"
    BIOSTATISTICS = "Biostatistics"
    PHARMACOLOGY = "Pharmacology"
    SURGERY = "Surgery"
    PEDIATRICS = "Pediatrics"
    PSYCHIATRY = "Psychiatry"
    NEUROLOGY = "Neurology"
    ONCOLOGY = "Oncology"
    CARDIOVASCULAR = "Cardiovascular"
    RESPIRATORY = "Respiratory"
    ENDOCRINOLOGY = "Endocrinology"
    GASTROENTEROLOGY = "Gastroenterology"
    OTHER = "Other"


class ConfidenceLevel(str, Enum):
    """置信度级别"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WritingStatus(str, Enum):
    """写作状态"""
    DRAFT = "draft"                    # 草稿
    IN_REVIEW = "in_review"            # 审核中
    REVISION = "revision"              # 修改中
    FINAL = "final"                    # 最终版
    PUBLISHED = "published"            # 已发表


class ManuscriptType(str, Enum):
    """手稿类型（基于分析结果）"""
    RESEARCH_PAPER = "research_paper"
    REVIEW_ARTICLE = "review_article"
    CASE_REPORT = "case_report"
    PROTOCOL = "protocol"
    DATA_NOTE = "data_note"
    TECHNICAL_REPORT = "technical_report"
    LETTER = "letter"
    OPINION = "opinion"


class WritingStage(str, Enum):
    """写作阶段枚举"""
    ANALYSIS = "analysis"           # 文档分析阶段
    OUTLINE_GENERATION = "outline"  # 大纲生成阶段
    CONTENT_EXTRACTION = "extraction"  # 内容提取阶段
    WRITING_GUIDANCE = "guidance"   # 写作指导阶段
    MANUSCRIPT_CREATION = "creation"  # 手稿创建阶段


class FileCategory(str, Enum):
    """文件分类枚举"""
    EXPERIMENTAL_RESULTS = "experimental_results"  # 实验结果
    EXPERIMENTAL_DESIGN = "experimental_design"    # 实验设计
    LITERATURE_REVIEW = "literature_review"        # 文献综述
    BACKGROUND_MATERIAL = "background_material"    # 背景材料
    STATISTICAL_ANALYSIS = "statistical_analysis"  # 统计分析
    CASE_DATA = "case_data"                        # 病例数据
    PROTOCOL = "protocol"                          # 研究方案
    OTHER = "other"                                # 其他 