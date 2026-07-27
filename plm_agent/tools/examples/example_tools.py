from typing import Optional, Type
from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool
from utils.example import get_name_meaning, get_weather


class GetWeatherInputSchema(BaseModel):
    city: Optional[str] = Field(description='Name of city')
    date: str = Field(description='Date of weather, format: yyyy-mm-dd')


class GetWeather(BaseTool):
    name: str = 'GetWeather'
    description: str = 'Return weather information of certain city and date'
    input_schema: BaseModel = GetWeatherInputSchema       

    async def run(self, city, date):
        yield {"intermediary results": get_weather(city, date)}
        # from agent.example_agent.example_agent import NameAgent
        # next_agent = NameAgent()
        self.agent.tools = [NameExplanation]
        async for res in self.agent.use_tool('Explain of my name Andrew?'):
            yield res
        # yield "complete"
    
class NameExplanationInputSchema(BaseModel):
    name: str = Field(description='Name that user is asking for explanation, leave as unknown if not provided')

class NameExplanation(BaseTool):
    name: str = 'NameExplanation'
    description: str = 'Explain origin and meaning behind users name'
    input_schema: BaseModel = NameExplanationInputSchema

    async def run(self, name):
        yield get_name_meaning(name)

