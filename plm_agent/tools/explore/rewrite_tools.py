from typing import List
from pydantic import BaseModel, Field
from tools.core.base_tool import BaseTool
from tools.explore.mindsearch_tools import RegionWebSearchSubQueryInputSchema

class RewriteInputSchema(BaseModel):
    reason: str = Field(description="The detail reason of the rewrite.")
    check: str = Field(description="Information the user needs to confirm or supplement. This part could be empty.")
    rewrite: str = Field(description="The final rewrite prompt. This part may be empty.")
    sub_queries: List[RegionWebSearchSubQueryInputSchema] = Field(description='An array containing sub-queries and their respective keywords for web search. Empty when no need web searching.')


class Rewrite(BaseTool):
    name: str = 'Rewrite'
    description: str = 'Get the rewrite detail for a give content.'
    input_schema: BaseModel = RewriteInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        yield kwarg

class ConfirmingInputSchema(BaseModel):
    thought_process: str = Field(description="The detail reason of the confirmation.")
    requires_confirmation: bool = Field(description="Whether need confirmation, true means need, false means not.")
    confirmation_message: str = Field(description="Questions or details the user must confirm or supply, e.g., '1.Clarify the date range; 2. Provide clinical trial details requirements. 3. ... Please confirm the four points above, or reply with 'Skip elaboration'")

class Confirming(BaseTool):
    name: str = 'Confirming'
    description: str = 'Ask user to specify and confirm.'
    input_schema: BaseModel = ConfirmingInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        yield {
            "function": self.name,
            "params": kwarg
        }

class RewritingInputSchema(BaseModel):
    thought_process: str = Field(description="The detail reason of the rewriting.")
    rewrite: str = Field(description="The final rewrite prompt.")

class Rewriting(BaseTool):
    name: str = 'Rewriting'
    description: str = 'Final rewritten question.'
    input_schema: BaseModel = RewritingInputSchema
    strict: bool = True

    async def run(self, **kwarg):
        yield {
            "function": self.name,
            "params": kwarg
        }