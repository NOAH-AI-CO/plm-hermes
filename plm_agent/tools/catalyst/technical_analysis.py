from typing import Optional, Type
from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool

class AnalysisBreakdownSchema(BaseModel):
    price: Optional[str] = Field(description='Detailed analysis of the price and chart pattern (if found) of the stock')
    volume: Optional[str] = Field(description='Detailed analysis of the volume of the stock')
    rsi: Optional[str] = Field(description='Detailed analysis of the Relative Strength Index (RSI) of the stock')
    macd: Optional[str] = Field(description='Detailed analysis of the Moving Average Convergence Divergence (MACD) of the stock')

class GetTechnicalAnalysisSchema(BaseModel):
    details: AnalysisBreakdownSchema = Field(description='A dictionary of the breakdown of the technical analysis')
    conclusion: str = Field(description="Conclusion of the technical analysis, should include potential scenarios")
    rating: int = Field(description='Recommendation rating on whether to buy, sell, or hold the stock, ranging from 0-10, with 0 being to confidently sell and 10 being to confidently buy')


class GetTechnicalAnalysis(BaseTool):
    name: str = 'GetWeather'
    description: str = 'Perform technical analysis on US stocks and return formatted results'
    input_schema: BaseModel = GetTechnicalAnalysisSchema       

    async def run(self, **kwargs):
        yield kwargs