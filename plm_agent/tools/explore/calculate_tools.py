import logging

from pydantic import BaseModel, Field
import numexpr

from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)

class CalculateInputSchema(BaseModel):
    expression: str = Field(description="a math expression")

class Calculate(BaseTool):
    name: str = 'Calculate'
    description: str = """
        Useful to answer questions about simple calculations.
        translate user question to a math expression that can be evaluated by numexpr.
    """
    input_schema: BaseModel = CalculateInputSchema

    async def run(self, **kwarg):
        try:
            ret = str(numexpr.evaluate(kwarg.get("expression")))
        except Exception as e:
            ret = f"Calculate Error: {e}"

        yield ret
