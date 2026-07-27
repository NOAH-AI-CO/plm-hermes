import os
from typing import Optional, List, Dict, Any
from openai import OpenAI, AsyncOpenAI
from ..core.interfaces import LLMModel

class DeepSeekModel(LLMModel):
    def __init__(self, test_mode: bool = False):
        """Initialize DeepSeek model with API keys
        
        Args:
            test_mode (bool): If True, use DeepSeek-V3 model for testing, otherwise use DeepSeek-R1
        """
        self.sf_client = None
        self.deepseek_client = None
        self.models = ["deepseek-reasoner", "deepseek-chat"]
        self.test_mode = test_mode
        self.max_tokens = 2000 if test_mode else 8000
        
        try:
            # Initialize SF DeepSeek client
            sf_api_key = os.getenv('SF_API_KEY')
            if sf_api_key:
                self.sf_client = AsyncOpenAI(
                    api_key=sf_api_key,
                    base_url="https://api.siliconflow.cn/v1"
                )
            
            # Initialize backup DeepSeek client
            self.deepseek_client = AsyncOpenAI(
                api_key=os.getenv('DEEPSEEK_API_KEY'),
                base_url="https://api.deepseek.com/v1"
            )
            if self.sf_client:
                self.client = self.sf_client
                self.model = 'deepseek-ai/DeepSeek-V3' if self.test_mode else 'Pro/deepseek-ai/DeepSeek-R1'
            else:
                self.client = self.deepseek_client
                self.model = 'deepseek-chat' if self.test_mode else 'deepseek-reasoner'
            
        except Exception as e:
            raise ValueError(f"Failed to initialize DeepSeek model: {str(e)}")

    async def generate(self, prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None, **kwargs) -> str:
        """Generate response using DeepSeek model
        
        Args:
            prompt (str): The input prompt
            temperature (float): Sampling temperature
            max_tokens (Optional[int]): Maximum tokens to generate. If None, uses the default based on test mode.
        """
        messages = [
            {"role": "system", "content": "You are a professional financial analyst specializing in biotech companies."},
            {"role": "user", "content": prompt}
        ]
        
        # Use instance max_tokens if not explicitly provided
        if max_tokens is None:
            max_tokens = self.max_tokens
        
        # Try SF DeepSeek first
        if self.sf_client:
            try:
                model = 'deepseek-ai/DeepSeek-V3' if self.test_mode else 'Pro/deepseek-ai/DeepSeek-R1'
                response = await self.sf_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if response and response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content
            except Exception as e:
                print(f"SF DeepSeek failed: {str(e)}")
        
        # Try backup models
        for model in self.models:
            try:
                response = await self.deepseek_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                if response and response.choices and response.choices[0].message.content:
                    return response.choices[0].message.content
            except Exception as e:
                print(f"Model {model} failed: {str(e)}")
                continue
        
        raise Exception("All models failed to generate response") 