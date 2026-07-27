from typing import List, Type
from tools.examples.example_tools import GetWeather, NameExplanation
from agent.core.preset import AgentPreset
from llm.base_model import BaseLLM
from llm.gcp_models import ClaudeSonnet45
from tools.core.base_tool import BaseTool


class ChatAgent(AgentPreset):
    llm: BaseLLM = ClaudeSonnet45
    sys_prompt: str = "You are a chat agent that can answer questions about anything."
    tools: List[BaseTool] = []

class WeatherAgent(AgentPreset):
    llm: BaseLLM = ClaudeSonnet45
    sys_prompt: str = "You are a weather agent that can answer questions about the weather."
    tools: List[BaseTool] = [
        GetWeather
    ]
    tool_choice: str = "auto"
    
class NameAgent(AgentPreset):
    llm: BaseLLM = ClaudeSonnet45
    sys_prompt: str = "You are a name agent that can answer questions about the origin and meaning behind users name."
    tools: List[BaseTool] = [
        NameExplanation
    ]
    tool_choice: str = "auto"

