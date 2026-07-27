from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

class BaseTool(BaseModel):
    name: str
    description: str
    input_schema: BaseModel
    agent: Optional[BaseModel] = None
    strict: bool = False
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    