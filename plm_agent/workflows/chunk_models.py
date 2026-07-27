from enum import Enum
from typing import Any
from pydantic import BaseModel


class MessageType(str, Enum):
    CHAT = "chat"
    TOOL = "tool"
    SYSTEM = "system"


class MessageStatus(str, Enum):
    DOING = "doing"
    DONE = "done"
    ERROR = "error"

class SegmentType(str, Enum):
    OUTLINE = "outline"
    SECTION = "section"
    THESIS = "thesis"        # 生成论文正文
    SUMMARY = "summary"        # 摘要
    CONCLUSION = "conclusion"  # 结论
    ABSTRACT = "abstract"     # 摘要
    DISCUSS = "discuss"      # 讨论
    METADATA = "metadata"  
    FINAL_THESIS = "final_thesis"     # 最终论文


class MessageChunk(BaseModel):
    type: MessageType
    status: MessageStatus
    segment_type: SegmentType
    segment_info: dict = dict[Any, Any]()  # segment额外信息
    message: Any