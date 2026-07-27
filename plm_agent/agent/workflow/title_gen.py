from typing import List

from pydantic import BaseModel
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from utils.core.get_json_schema import get_openai_json_schema
from tools.core.base_tool import BaseTool

class TitleResponse(BaseModel):
    title: str = ""

class WorkflowTitleGenAgent(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = """
    You are an agent that is tasked with generating a title for a workflow task. We will provide you with information of the workflow.
    Workflows have different types, but all pertain to retrieving and/or summarizing medical field research data.
    Requirements:
    - Generate a title that is relevant to the task.
    - The title must use specific terms from the parameters we provided, such as the indication, drug, company name etc., and they preferably should lead the title.
    - Title should be concise and contain less than 10 words.
    
    Output format:
    A json object containing the title.
    """
    tools: List[BaseTool] = []
    tool_choice: str = "auto"
    # json_mode: bool = True
    response_format: str = get_openai_json_schema(TitleResponse())
    temperature: float = 0.1
    
    
    
    