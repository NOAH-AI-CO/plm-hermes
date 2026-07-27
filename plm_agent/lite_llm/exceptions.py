# -*- coding: utf-8 -*-
from enum import Enum
from dataclasses import dataclass

class LiteLLMErrorCode(Enum):
    UNKNOWN_ERROR = "unknown_error"
    CONTEXT_WINDOW_EXCEEDED = "context_window_exceeded"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    NO_MODEL_AVAILABLE = "no_model_available"
    INCOMPLETE = "incomplete"
    STREAM_ENDED_WITHOUT_RESPONSE = "stream_ended_without_response"
    FAILED = "failed"

@dataclass
class LiteLLMError(Exception):
    provider: str
    message: str
    code: LiteLLMErrorCode = LiteLLMErrorCode.UNKNOWN_ERROR

class LLMContextWindowExceeded(LiteLLMError):
    def __init__(self, provider: str, message: str = "Context window exceeded"):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.CONTEXT_WINDOW_EXCEEDED)

class LLMRateLimited(LiteLLMError):
    def __init__(self, provider: str, message: str = "Rate limited",):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.RATE_LIMITED)

class LLMTimeout(LiteLLMError):
    def __init__(self, provider: str, message: str = "Timeout", ):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.TIMEOUT)

class LLMNoModelAvailable(LiteLLMError):
    def __init__(self, provider: str, message: str = "No model available"):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.NO_MODEL_AVAILABLE)

class LLMIncomplete(LiteLLMError):
    def __init__(self, provider: str, message: str = "Incomplete"):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.INCOMPLETE)

class LLMStreamEndedWithoutResponse(LiteLLMError):
    def __init__(self, provider: str, message: str = "Stream ended without response"):
        super().__init__(provider=provider, message=message, code=LiteLLMErrorCode.STREAM_ENDED_WITHOUT_RESPONSE)
