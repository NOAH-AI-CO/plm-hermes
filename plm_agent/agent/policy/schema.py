from typing import List, Optional, Type
from pydantic import BaseModel, Field

class SelectFolder(BaseModel):
    folders: List[str] = Field(description="A list of folders identified as relevant to the query")
    
class SelectFile(BaseModel):
    files: List[str] = Field(description="A list of files identified as relevant to the query")
    
"""RAG模块的Schema定义"""

class ArticleAnalysisSchema(BaseModel):
    """文章分析结果Schema"""
    title: str = Field(description="文档的标题")
    description: str = Field(description="文档的简短描述，不超过100字")
    table_of_contents: str = Field(description="""目录字典的JSON字符串，格式为{"1":"凡例","8":"西药部分","68":"中成药部分"}，key为页码数字符串，value为章节标题。返回后会被转换为页码范围格式，若无目录则返回空字典{}""")

class PolicyRegionSchema(BaseModel):
    """政策适用地区Schema"""
    region: str = Field(description="政策适用省份或地区，目前只有北京、上海、重庆、浙江、天津、江苏、安徽、湖南、湖北、河南、河北、国家可选", examples=["北京", "上海", "重庆", "浙江", "天津", "江苏", "安徽", "湖南", "湖北", "河南", "河北", "国家"])

class FurtherSearchSchema(BaseModel):
    """是否需要进一步查询Schema"""
    needs_further_search: bool = Field(description="是否需要进一步查询知识库")
    region: Optional[str] = Field(description="政策适用省份或地区，目前只有北京、上海、重庆、浙江、天津、江苏、安徽、湖南、湖北、河南、河北、国家可选", examples=["北京", "上海", "重庆", "浙江", "天津", "江苏", "安徽", "湖南", "湖北", "河南", "河北", "国家"])
    question: Optional[str] = Field(description="需要进一步查询的补充问题")

class DrugPolicyRegionSchema(BaseModel):
    """政策适用地区Schema"""
    drug_region: str = Field(description="药物政策适用范围，只有中国，非中国两个选择", examples=["中国", "非中国"])

class DrugFurtherSearchSchema(BaseModel):
    """是否需要进一步查询Schema"""
    needs_further_search: bool = Field(description="是否需要进一步查询知识库")
    drug_region: Optional[str] = Field(description="药物政策适用范围，目前只有中国，非中国可选", examples=["中国", "非中国"])
    question: Optional[str] = Field(description="需要进一步查询的补充问题")

class WebSearchSchema(BaseModel):
    """是否需要进行网络搜索Schema"""
    needs_web_search: bool = Field(description="是否需要进行网络搜索以获取最新信息，需要则输出True，不需要则输出False",examples=[True, False])