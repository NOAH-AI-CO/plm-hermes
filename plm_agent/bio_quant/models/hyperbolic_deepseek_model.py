import os
import traceback
from typing import Optional, List, Dict, Any
from openai import OpenAI, AsyncOpenAI
from ..core.interfaces import LLMModel

class HyperbolicDeepSeekModel(LLMModel):
    def __init__(self, test_mode: bool = False):
        """Initialize DeepSeek model with API keys

        Args:
            test_mode (bool): If True, use DeepSeek-V3 model for testing, otherwise use DeepSeek-R1
        """
        self.test_mode = test_mode
        self.hb_client = None
        self.max_tokens = 2000 if test_mode else 8000
        
        try:
            # Initialize HB DeepSeek client
            hb_api_key = os.getenv('HB_API_KEY')
            if hb_api_key:
                self.hb_client = AsyncOpenAI(
                    api_key=hb_api_key,
                    # model="deepseek-ai/DeepSeek-R1",
                    base_url="https://api.hyperbolic.xyz/v1/"
                )
            else:
                print("HB_API_KEY not found in environment variables")
        except Exception as e:
            raise ValueError(f"Failed to initialize DeepSeek model: {str(e)}")

    def generate(self, prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None) -> str:
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
        
        try:
            # model = 'deepseek-ai/DeepSeek-V3' if self.test_mode else 'deepseek-ai/DeepSeek-R1'
            model = "meta-llama/Meta-Llama-3.1-8B-Instruct"
            response = self.hb_client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens
            )
            if response and response.choices and response.choices[0].message.content:
                return response.choices[0].message.content
        except Exception as e:
            traceback.print_exc()
            print(f"HB DeepSeek failed: {str(e)}")
                
        raise Exception("All models failed to generate response") 