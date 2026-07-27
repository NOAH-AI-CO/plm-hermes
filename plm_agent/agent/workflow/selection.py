from typing import List

from pydantic import BaseModel, Field
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from llm.deepseek_models import CompositeDeepseekChat, SiliconflowDeepseekChat
from llm.ali_models import CompositeQwen3
from llm.composite_models import IDSelectionModels
from utils.core.get_json_schema import get_openai_json_schema_v2, get_openai_json_schema_v3
from tools.core.base_tool import BaseTool


class IdSelectionSchema(BaseModel):
    id_list: List[str] = Field(description="List of ids selected")

class IdSelectionAgent(AgentPreset):
    # llm: BaseLLM = GPT4o
    llm: BaseLLM = IDSelectionModels
    tools: List[BaseTool] = [
        # GetTechnicalAnalysis
        ]
    response_format: str = get_openai_json_schema_v3(IdSelectionSchema)
    temperature: float = 0.05
    
    async def use_tool(self, user_prompt, **kwargs):
        function_name = self.response_format[0]['function']['name']
        llm = self.llm(max_retries=0, timeout=45, first_chunk_timeout=10)
        return await llm(user_prompt=user_prompt, tools=self.response_format, tool_choice={"type": "function", "function": {"name": function_name}})
