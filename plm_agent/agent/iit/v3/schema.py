from typing import List, Optional, Type
from pydantic import BaseModel, Field

class Section(BaseModel):
    section: str = Field(description="章节标题")
    page_range: str = Field(description="章节所在页码区间")

class SectionsToRead(BaseModel):
    sections: List[Section] = Field(description="需要阅读的章节列表")