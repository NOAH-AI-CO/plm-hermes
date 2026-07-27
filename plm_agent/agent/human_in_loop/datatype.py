from dataclasses import dataclass
from enum import Enum
from typing import Literal


class MessageType(str, Enum):
    """消息类型"""
    CHAT = 'chat'
    SIMPLE_THOUGHT = 'simpleThought'
    STATUS_UPDATE = 'statusUpdate'
    PLAN_UPDATE = 'planUpdate'
    THOUGHT = 'thought'
    SUMMARY = 'summary'
    REFERENCE = 'reference'


@dataclass
class Base:
    tool_uses: str
    agent: str
    hitl_mode: str
    sender: str
    current_step: str
    current_tool: str
    feedback: str
    saveChat: str


# ---------- chat ----------
@dataclass
class ChatBase(Base):
    type: MessageType.CHAT = MessageType.CHAT


# 这是将 Chat1, Chat2, ... 合并后的完整结构，我也不清楚 Chat 能都代替 Chat1, Chat2, ...
@dataclass
class Chat(ChatBase):
    language: str
    message: str
    chunkIdx: str
    rewrite_question: str
    editable: str
    plan: str


@dataclass
class Chat1(ChatBase):
    language: str
    message: str


@dataclass
class Chat2(ChatBase):
    chunkIdx: str
    message: str
    rewrite_question: str
    editable: str


@dataclass
class Chat3(ChatBase):
    chunkIdx: str
    message: str
    plan: str


@dataclass
class Chat4(ChatBase):
    message: str
    plan: str


@dataclass
class Chat5(ChatBase):
    chunkIdx: str
    message: str


# ---------- simpleThought ----------
@dataclass
class SimpleThoughtBase(Base):
    type: MessageType.SIMPLE_THOUGHT = MessageType.SIMPLE_THOUGHT


# 这是将 SimpleThought1, SimpleThought2 合并后的完整结构，我也不清楚 SimpleThought 能都代替 SimpleThought1, SimpleThought2
@dataclass
class SimpleThought(SimpleThoughtBase):
    language: str
    chunkIdx: str
    message: str


@dataclass
class SimpleThought1(SimpleThoughtBase):
    language: str
    chunkIdx: str
    message: str


@dataclass
class SimpleThought2(SimpleThoughtBase):
    chunkIdx: str
    message: str


# ---------- thought ----------
@dataclass
class ThoughtBase(Base):
    type: MessageType.THOUGHT = MessageType.THOUGHT


# 这是将 Thought1, Thought2 合并后的完整结构，我也不清楚 Thought 能都代替 Thought1, Thought2
@dataclass
class Thought(ThoughtBase):
    chunkIdx: str
    message: str
    plan: str


@dataclass
class Thought1(ThoughtBase):
    chunkIdx: str
    message: str
    plan: str


@dataclass
class Thought2(ThoughtBase):
    chunkIdx: str
    message: str


# ---------- statusUpdate ----------
@dataclass
class StatusUpdateBase(Base):
    type: MessageType.STATUS_UPDATE = MessageType.STATUS_UPDATE


# 这是将 StatusUpdate1, StatusUpdate2, ... 合并后的完整结构，我也不清楚 StatusUpdate 能都代替 StatusUpdate1, StatusUpdate2, ...
@dataclass
class StatusUpdate(StatusUpdateBase):
    language: str
    chunkIdx: str
    message: str
    rewrite_result: str
    agentStatus: str
    stepQuestion: str
    plan: str
    countDown: str


@dataclass
class StatusUpdate1(StatusUpdateBase):
    language: str
    chunkIdx: str
    message: str
    rewrite_result: str
    agentStatus: str


@dataclass
class StatusUpdate2(StatusUpdateBase):
    chunkIdx: str
    message: str
    stepQuestion: str
    agentStatus: str


@dataclass
class StatusUpdate3(StatusUpdateBase):
    plan: str
    agentStatus: str
    countDown: str


@dataclass
class StatusUpdate4(StatusUpdateBase):
    plan: str
    agentStatus: str


@dataclass
class StatusUpdate5(StatusUpdateBase):
    agentStatus: str


# ---------- planUpdate ----------
@dataclass
class PlanUpdate(Base):
    type: MessageType.PLAN_UPDATE = MessageType.PLAN_UPDATE
    plan: str


# ---------- confirmTool ----------
@dataclass
class ConfirmTool(Base):
    type: MessageType.CONFIRM_TOOL = MessageType.CONFIRM_TOOL
    plan: str
    message: str
    accept: str


# ---------- reference ----------
@dataclass
class ReferenceBase(Base):
    type: MessageType.REFERENCE = MessageType.REFERENCE


# 这是将 Reference1, Reference2 合并后的完整结构，我也不清楚 Reference 能都代替 Reference1, Reference2
@dataclass
class Reference(ReferenceBase):
    plan: str
    chunkIdx: str
    message: str


@dataclass
class Reference1(ReferenceBase):
    plan: str
    chunkIdx: str
    message: str


@dataclass
class Reference2(ReferenceBase):
    chunkIdx: str
    message: str


# ---------- summary ----------
@dataclass
class Summary:
    type: MessageType.SUMMARY = MessageType.SUMMARY
    message: str
