import io
import os
from typing import List, Optional, Iterator, Union
from openai import OpenAI, AsyncOpenAI
from ..core.interfaces import LLMModel
class VolcanoDeepSeekModel(LLMModel):
    """Volcano DeepSeek model wrapper"""
    
    def __init__(self, test_mode: bool = False):
        """Initialize Volcano DeepSeek model
        
        Args:
            test_mode (bool): If True, use reduced token limit for testing
        """
        self.api_key = os.getenv("ARK_API_KEY")
        if not self.api_key:
            raise ValueError("ARK_API_KEY environment variable not set")
            
        self.base_url = "https://ark.cn-beijing.volces.com/api/v3"
        self.model = "ep-20250206113149-ddgqg"
        self.test_mode = test_mode
        self.max_tokens = 2000 if test_mode else 8192
        
        try:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
        except Exception as e:
            raise ConnectionError(f"Failed to initialize Volcano client: {str(e)}")

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate response from the model
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        try:
            messages = [
                {"role": "system", "content": "You are a professional financial analyst specializing in biotech companies."},
                {"role": "user", "content": prompt}
            ]
            
            max_tokens = kwargs.get('max_tokens', self.max_tokens)
            
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.6
            )
            
            return completion.choices[0].message.content
                
        except Exception as e:
            raise RuntimeError(f"Volcano API error: {str(e)}")
            
    def close(self):
        """Close the client connection"""
        if hasattr(self, 'client'):
            self.client = None
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 