from typing import List, Optional, Type
from pydantic import BaseModel, Field


class UserInputTranslationSchema(BaseModel):
    translated_text: str = Field(description="Translated user input into english")


class UserInputKeywordExtractionSchema(BaseModel):
    keywords: List[str] = Field(description="List of keywords extracted from user input")
    core_keywords: List[str] = Field(description="List of core keywords extracted from user input")

class UserInputKeywordTranslationSchema(BaseModel):
    keywords: List[str] = Field(description="List of keywords translated to english")
    core_keywords: List[str] = Field(description="List of core keywords translated to english")
