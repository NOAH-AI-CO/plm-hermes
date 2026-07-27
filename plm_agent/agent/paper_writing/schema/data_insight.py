from token import OP
from typing import List, Dict, Any, Optional, Union, Tuple
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime

class PandasDType(str, Enum):
    """Pandas data type categories"""
    INT = "int"
    INT64 = "int64"
    FLOAT = "float"
    FLOAT64 = "float64"
    DATETIME = "datetime"
    DATETIME64 = "datetime64"
    STRING = "string"
    OBJECT = "object"

class DataType(str, Enum):
    """Data type categories for analysis purposes"""
    # Continuous numerical data suitable for statistical analysis
    CONTINUOUS = "continuous"  # e.g., age, height, temperature, scores
    # Discrete numerical data with limited distinct values
    DISCRETE = "discrete"  # e.g., number of children, rating scales, counts
    # Categorical data with limited distinct categories
    CATEGORICAL = "categorical"  # e.g., gender, education level, country
    # Binary/boolean data
    BINARY = "binary"  # e.g., yes/no, true/false, 0/1
    # Text data requiring NLP analysis
    TEXT = "text"  # e.g., comments, descriptions, open-ended responses
    # Temporal data for time series analysis
    TEMPORAL = "temporal"  # e.g., dates, timestamps, time periods
    # Identifier data (not suitable for analysis)
    IDENTIFIER = "identifier"  # e.g., IDs, names, codes
    # Unknown or mixed data types
    UNKNOWN = "unknown"

class Column(BaseModel):
    """Information about a single column"""
    name: str = Field(..., description="Column name")
    dtype: PandasDType = Field(..., description="Pandas data type")
    data_type: DataType = Field(..., description="Data type")
    missing_count: int = Field(..., description="Number of missing values in this column")
    unique_count: int = Field(..., description="Number of unique values")

class Datasheet(BaseModel):
    """Basic information about the raw CSV data"""
    file_id: str = Field(..., description="File ID from upload service")
    file_name: str = Field(..., description="Original CSV file name")
    number_of_rows: int = Field(..., description="Number of rows in the dataset")
    number_of_columns: int = Field(..., description="Number of columns in the dataset")
    columns: List[Column] = Field(..., description="Column information (name, type, and quality metrics)")
    data_preview: Dict[str, List[str]] = Field(..., description="First few rows as preview")

class UnivariateContinuousDetail(BaseModel):
    mean: Optional[float] = Field(None, description="Arithmetic mean")
    std: Optional[float] = Field(None, description="Standard deviation")
    min: Optional[float] = Field(None, description="Minimum value")
    max: Optional[float] = Field(None, description="Maximum value")
    median: Optional[float] = Field(None, description="Median (50th percentile)")
    q25: Optional[float] = Field(None, description="25th percentile")
    q75: Optional[float] = Field(None, description="75th percentile")
    missing_rate: Optional[float] = Field(None, description="Percentage of missing values")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateDiscreteDetail(BaseModel):
    unique_values: Optional[List[str]] = Field(None, description="Unique values")
    percentage_of_unique_values: Optional[Dict[str, float]] = Field(None, description="Percentage of each unique value")
    missing_rate: Optional[float] = Field(None, description="Percentage of missing values")
    mode: Optional[str] = Field(None, description="Most frequent value")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateCategoricalDetail(BaseModel):
    unique_values: Optional[List[str]] = Field(None, description="Unique values")
    percentage_of_unique_values: Optional[Dict[str, float]] = Field(None, description="Percentage of each unique value")
    missing_rate: Optional[float] = Field(None, description="Percentage of missing values")
    mode: Optional[str] = Field(None, description="Most frequent category")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateBinaryDetail(BaseModel):
    unique_values: Optional[List[str]] = Field(None, description="Unique values")
    percentage_of_unique_values: Optional[Dict[str, float]] = Field(None, description="Percentage of each unique value")
    missing_rate: Optional[float] = Field(None, description="Percentage of missing values")
    mode: Optional[str] = Field(None, description="Most frequent category")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateTextDetail(BaseModel):
    avg_length: float = Field(..., description="Average text length")
    missing_rate: float = Field(..., description="Percentage of missing values")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateTemporalDetail(BaseModel):
    min_date: str = Field(..., description="Earliest date")
    max_date: str = Field(..., description="Latest date")
    missing_rate: float = Field(..., description="Percentage of missing values")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateIdentifierDetail(BaseModel):
    unique_count: int = Field(..., description="Number of unique identifiers")
    missing_rate: float = Field(..., description="Percentage of missing values")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

class UnivariateUnknownDetail(BaseModel):
    reason: str = Field(..., description="Reason why data type could not be determined")
    ai_suggestions: Optional[Dict[str, Any]] = Field(None, description="Additional analysis results suggested by AI based on data characteristics")

UnivariateDetail = Union[
    UnivariateContinuousDetail,
    UnivariateDiscreteDetail,
    UnivariateCategoricalDetail,
    UnivariateBinaryDetail,
    UnivariateTextDetail,
    UnivariateTemporalDetail,
    UnivariateIdentifierDetail,
    UnivariateUnknownDetail
]

class UnivariateSummary(BaseModel):
    """Summary of univariate analysis"""
    column_name: str = Field(..., description="Column name")
    data_type: DataType = Field(..., description="Data type")
    detail: UnivariateDetail = Field(..., description="Detailed analysis")
    quality_score: float = Field(..., description="Quality score")
    insight: str = Field(..., description="Insight")

class UnivariateReport(BaseModel):
    """Report of univariate analysis"""
    summary: List[UnivariateSummary] = Field(..., description="Summary of univariate analysis")

class MultivariateSummary(BaseModel):
    """Multivariate analysis detail"""
    column_names: List[str] = Field(..., description="Column names")
    column_data_types: List[DataType] = Field(..., description="Data types of columns")
    detail: List[Dict[str, Any]] = Field(..., description="Detailed analysis results")
    quality_score: float = Field(..., description="Quality score")
    insight: str = Field(..., description="Insight")

class MultivariateReport(BaseModel):
    """Report of multivariate analysis"""
    summary: List[MultivariateSummary] = Field(..., description="Summary of multivariate analysis")

class StatisticalToolResult(BaseModel):
    """统计工具结果"""
    name: str = Field(..., description="工具名称")
    result: Dict[str, Any] = Field(..., description="工具执行结果")


class AnalysisResult(BaseModel):
    """单个分析任务的结果"""
    id: int = Field(..., description="分析任务ID")
    success: bool = Field(..., description="分析是否成功")
    type: str = Field(..., description="分析类型：with_tools, text_only, no_tools_no_content, no_response")
    
    # 成功情况下的字段
    tools: Optional[List[StatisticalToolResult]] = Field(default=None, description="使用的统计工具")
    summary: Optional[Any] = Field(default=None, description="分析总结")
    content: Optional[str] = Field(default=None, description="文本分析内容")
    
    # 失败情况下的字段
    error: Optional[str] = Field(default=None, description="错误信息")
    suggestion: Optional[str] = Field(default=None, description="建议")


class DataPreview(BaseModel):
    """数据预览"""
    data_preview: List[Dict[str, Any]] = Field(..., description="数据前5行预览")
    data_structure: Dict[str, str] = Field(..., description="数据结构（列名和数据类型）")


class DatasetAnalysisResult(BaseModel):
    """单个数据集的分析结果"""
    file_id: str = Field(..., description="文件ID")
    file_path: str = Field(..., description="文件路径")
    file_name: Optional[str] = Field(default=None, description="文件名")
    data_preview: DataPreview = Field(..., description="数据预览")
    analysis_results: List[AnalysisResult] = Field(..., description="分析结果列表")
    
    # 元数据
    analysis_timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="分析时间戳")
    total_analyses: Optional[int] = Field(default=None, description="总分析任务数")
    successful_analyses: Optional[int] = Field(default=None, description="成功分析任务数")
    
    # 统计摘要
    key_findings: Optional[List[str]] = Field(default=None, description="关键发现")
    statistical_methods_used: Optional[List[str]] = Field(default=None, description="使用的统计方法")
    data_quality_notes: Optional[str] = Field(default=None, description="数据质量说明")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
    
    def get_successful_results(self) -> List[AnalysisResult]:
        """获取成功的分析结果"""
        return [result for result in self.analysis_results if result.success]
    
    def get_tool_results(self) -> List[StatisticalToolResult]:
        """获取所有工具结果"""
        tool_results = []
        for result in self.analysis_results:
            if result.success and result.tools:
                tool_results.extend(result.tools)
        return tool_results
    
    def get_summary_text(self) -> str:
        """获取分析总结文本"""
        summaries = []
        for result in self.analysis_results:
            if result.success and result.summary:
                summaries.append(str(result.summary))
        return "\n\n".join(summaries)
    
    def get_key_statistics(self) -> Dict[str, Any]:
        """获取关键统计信息"""
        stats = {}
        for tool_result in self.get_tool_results():
            if tool_result.name == "descriptive_statistics":
                stats.update(tool_result.result)
        return stats