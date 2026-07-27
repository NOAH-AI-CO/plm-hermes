from typing import List, Optional, Type, Dict
from pydantic import BaseModel, Field


class ExtractionSchema(BaseModel):
    opinions_1: List[str] = Field(description="评审意见1的提取列表")
    opinions_2: List[str] = Field(description="评审意见2的提取列表")
    opinions_3: List[str] = Field(description="评审意见3的提取列表")
    opinions_4: List[str] = Field(description="评审意见4的提取列表")
    opinions_5: List[str] = Field(description="评审意见5的提取列表")
    
class ExtractionSchemaV2(BaseModel):
    opinions: List[str] = Field(description="评审意见的提取列表")

class ClassificationSchema(BaseModel):
    classifications: List[str] = Field(description="分类结果列表，数组长度与输入意见列表一致")

class ClassificationSchemaNum(BaseModel):
    classifications: List[int] = Field(description="分类结果列表，维度对应的数字，数组长度与输入意见列表一致")
    
class ClusteringSchema(BaseModel):
    # clusters: str = Field(description="JSON字符串格式，key为聚类名称，值为聚类中包含的意见索引数组，如{'聚类名称1': [0, 2, 5], '聚类名称2': [1, 3, 4]} }")
    # clusters: str = Field(description="JSON字符串格式，key为聚类名称，值为聚类中包含的意见数量，如{'聚类名称1': 3, '聚类名称2': 3} }")
    clusters: List[str] = Field(description="聚类结果列表，值为聚类名称")