from typing import List

from pydantic import BaseModel, Field
from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.gcp_models import Gemini15Flash, Gemini15Pro
from llm.base_model import BaseLLM
from utils.core.get_json_schema import get_openai_json_schema
from tools.core.base_tool import BaseTool


class AnalysisBreakdownSchema(BaseModel):
    price: str = ''
    volume: str = ''
    rsi: str = ''
    macd: str = ''
    future_scenario: str = ''

class TechnicalAnalysisSchema(BaseModel):
    analysis: AnalysisBreakdownSchema = AnalysisBreakdownSchema()
    conclusion: str = ''
    rating: int = ''

class TechnicalAnalysisAgent(AgentPreset):
    # llm: BaseLLM = GPT4o
    llm: BaseLLM = GPT4o
    sys_prompt: str = """
    You are a technical analysis agent that can perform technical analysis on US stocks. 
    We will provide you with an image of a stock market chart including RSI, MACD, price and volume for a stock ticker.
    Pay attention to the price chart and look for patterns. Include a short description of the patterns and the implications if patterns are found.
    The output should contain detailed analyses of the different indicator charts (cover both the line graph and the histograms) with emphasis on the most recent values (to the right), possible future scenario, an overall conclusion and a recommendation rating on whether to buy, sell, or hold the stock, ranging from 0-10, with 0 being to confidently sell and 10 being to confidently buy.
    """
    tools: List[BaseTool] = [
        # GetTechnicalAnalysis
        ]
    # tool_choice: str = "required"
    response_format: str = get_openai_json_schema(TechnicalAnalysisSchema())
    temperature: float = 0.05
    # Pay attention to the price shape and look for patterns like wedges, triangles, head and shoulders, double tops, double bottoms, etc. Include a short description of the patterns and the implication if possible.
    # The output should contain an analysis of the different indicator charts, a conclusion and a recommendation rating on whether to buy, sell, or hold the stock, ranging from 0-10, with 0 being to confidently sell and 10 being to confidently buy.