from typing import List, Optional
from pydantic import BaseModel


class ClinicalTrialDesignComparison(BaseModel):
    indication_name: dict = {},
    lead_company: List[str] = [],
    target: dict = {},
    drug_name: dict = {},
    nctids: List[str] = [],
    gender: str = "",
    current_status: List[str] = [],
    phase: List[str] = [],
    locations: dict = {},
    top_n: int = 10

class RunPromptTest(BaseModel):
    prompt: str
    nctids: List[str] = []
    testset: List[dict] = []
    select_fields: List[str] = []
    
# class Chat(BaseModel):
#     history_messages: List[dict] = []
#     user_prompt: str
#     agent: str # preset including model, sys_prompt tool usage and tools defined in agent folder
#     images: List[str] = []
    
    