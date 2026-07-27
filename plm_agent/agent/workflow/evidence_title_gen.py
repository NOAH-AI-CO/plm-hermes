"""循证诊疗任务标题生成器。

供 Backend `Task.display_title` 自动起标题用——主接口完成后异步调一次，
按"年龄 + 性别 + 诊断 + 关键分期/分子"格式起 ≤ 15 字中文标题。

调用方传 `{patient_input, diagnosis, primary_organization}`，例如：

    {
      "patient_input": "患者，男，65岁，确诊套细胞淋巴瘤(MCL)，Ann Arbor III期...",
      "diagnosis": "套细胞淋巴瘤",
      "primary_organization": "NCCN"
    }

返回 `{"title": "65岁男 MCL III期"}` 之类。
"""
from typing import List

from pydantic import BaseModel
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from utils.core.get_json_schema import get_openai_json_schema
from tools.core.base_tool import BaseTool


class TitleResponse(BaseModel):
    title: str = ""


class EvidenceTitleGenAgent(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = """
    你是一个为循证诊疗任务生成简短中文标题的助手。给定一份病例的关键信息，
    你要起一个 ≤ 15 字的标题，方便医生在历史列表里一眼认出是哪个病例。

    规则：
    - 标题用中文（专有名词 / 缩写如 APL/MCL/IPI 可保留英文）。
    - 通常按 "年龄 + 性别 + 诊断 + 关键分期/分子标志" 顺序写。
    - 不写"诊疗""分析""病例"等冗余词。
    - 不写完整句子，不加标点结尾。
    - 不超过 15 个字（含数字字母）。

    好例子：
    - "65岁男 MCL III期"
    - "28岁男 高危APL"
    - "72岁女 AML FLT3+"
    - "55岁男 CLL TP53突变"
    - "高危APL一线诱导"  ← 病例不指向具体人时

    输出格式：
    一个 JSON 对象，仅含 `title` 字段。
    """
    tools: List[BaseTool] = []
    tool_choice: str = "auto"
    response_format: str = get_openai_json_schema(TitleResponse())
    temperature: float = 0.0
