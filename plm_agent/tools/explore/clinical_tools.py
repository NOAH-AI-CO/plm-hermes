import logging

from pydantic import BaseModel, Field

from tools.core.base_tool import BaseTool

logger = logging.getLogger(__name__)


class GetClinicalGuidelineSubTreeInputSchema(BaseModel):
    reasoning: str = Field(description="Provide the rationale, in the default language, for choosing these subtrees, considering both the user's question and the description of each subtree.")
    sub_tree_index: list[int] = Field(description='The sub tree ids.')


class GetClinicalGuidelineSubTree(BaseTool):
    name: str = 'GetClinicalGuidelineSubTree'
    description: str = 'Get clinical guideline sub trees detail by the given sub tree ids.'
    input_schema: BaseModel = GetClinicalGuidelineSubTreeInputSchema

    async def run(self, **kwarg):
        logger.info(f"Get clinical guideline sub tree result {kwarg}")
        yield kwarg

class GetClinicalGuidelineSubTreeInputSchema(BaseModel):
    is_relevant: bool = Field(description='Whether the current subtree is relevant to user question. True means relevant, False means not.')
    reasoning: str = Field(description="Provide the rationale, in the default language, for choosing these subtrees, considering both the user's question and the description of each subtree.")
    sub_tree_index: list[int] = Field(description='The suggestion sub tree ids.')

class CheckCurrentSubTree(BaseTool):
    name: str = 'CheckCurrentSubTree'
    description: str = 'Check the current subtree is relevant to the question.'
    input_schema: BaseModel = GetClinicalGuidelineSubTreeInputSchema

    async def run(self, **kwarg):
        logger.info(f"Get clinical guideline review sub tree result {kwarg}")
        yield kwarg

