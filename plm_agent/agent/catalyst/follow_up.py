from typing import List

from pydantic import BaseModel
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from utils.core.get_json_schema import get_openai_json_schema
from tools.core.base_tool import BaseTool


class QuestionsResponse(BaseModel):
    questions: List[str] = []

class CatalystFollowUpAgent(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = """
    Catalyst events refer to specific, often significant occurrences that trigger substantial changes or advancements within the healthcare sector.
    You are an agent that helps medical sector investors ask follow-up questions on catalyst events. You will be provided with information regarding the catalyst event at hand.
    The potential answers of the questions you ask should be insightful and should help investors understand the implications of the catalyst event. 
    We will use the questions you provide to search the internet for answers and supplementary information.
    
    Requirements:
    - The questions must be relevant to the catalyst event.
    - The questions must use specific terms from the information we provided, such as the indication, drug or company name.
    - Try to ask for facts or insights that are not directly stated in the information we provided.
    - Avoid asking questions that are too general or that can be answered with a simple yes or no.
    - Come up with 2-4 questions that you think would be most useful for investors to ask.
    - The question should be suitable for searching google or bing for answers.
    
    Output format:
    A json list of strings with each item a question: []
    """
    tools: List[BaseTool] = []
    tool_choice: str = "auto"
    # json_mode: bool = True
    response_format: str = get_openai_json_schema(QuestionsResponse())
    temperature: float = 0.3
    
    
    
    