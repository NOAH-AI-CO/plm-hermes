from pydantic import BaseModel, Field
from tools.core.base_tool import BaseTool
from tools.explore.mindsearch_tools_v3 import FunctionCallResult


class ClarificationInputSchema(BaseModel):
    prompt_to_user: str = Field(
        description="A concise message to the user asking for missing details. Use numbered questions and allow a 'Skip' option."
    )


class Clarification(BaseTool):
    name: str = 'Clarification'
    description: str = 'This tool is used to request clarification when a user’s prompt is ambiguous, underspecified, or missing critical constraints. Call this tool when you cannot proceed reliably without additional details, or when proceeding would significantly increase the risk of misunderstanding or rework.'
    input_schema: BaseModel = ClarificationInputSchema
    strict: bool = True

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)

        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={
                "prompt_to_user": kwargs.get('prompt_to_user', '')
            }
        )


class RewrittenUserPromptInputSchema(BaseModel):
    rewritten_question: str = Field(
        description="The final rewritten user request, fully specified and ready for execution."
    )


class RewrittenUserPrompt(BaseTool):
    name: str = 'RewrittenUserPrompt'
    description: str = 'This tool is used to return the rewritten and fully specified user request after clarification or refinement. Call this tool when you have successfully rewritten the user\'s prompt with all necessary details and constraints.'
    input_schema: BaseModel = RewrittenUserPromptInputSchema
    strict: bool = True

    async def run(self, **kwargs):
        context = kwargs.pop("_context", None)

        yield FunctionCallResult(
            id=context.id if hasattr(context, 'id') else '',
            call_id=context.call_id if hasattr(context, 'call_id') else '',
            args=kwargs,
            name=self.name,
            result={
                "rewritten_question": kwargs.get('rewritten_question', '')
            }
        )
