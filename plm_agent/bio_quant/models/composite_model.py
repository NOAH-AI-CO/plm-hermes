import os
import traceback
from typing import List, Optional, Iterator, Union
from ..core.interfaces import LLMModel
from .volcano_deepseek_model import VolcanoDeepSeekModel
from .azure_deepseek_model import AzureDeepSeekModel
from .deepseek_model import DeepSeekModel

class CompositeModel(LLMModel):
    """Composite model implementing priority chain: Volcano -> Azure -> DeepSeek"""
    
    def __init__(self, test_mode: bool = False):
        """Initialize composite model with fallback chain
        
        Args:
            test_mode (bool): If True, use test mode for all models
        """
        self.test_mode = test_mode
        self.current_model = None
        self.models = []
        
        # Initialize all models in priority order           
        try:
            print("Initializing Volcano DeepSeek model...")
            self.models.append(VolcanoDeepSeekModel(test_mode=test_mode))
            if not self.current_model:
                self.current_model = self.models[-1]
        except Exception as e:
            print(f"Failed to initialize Volcano model: {str(e)}")
            
        try:
            print("Initializing DeepSeek model...")
            self.models.append(DeepSeekModel(test_mode=test_mode))
            if not self.current_model:
                self.current_model = self.models[-1]
        except Exception as e:
            traceback.print_exc()
            print(f"Failed to initialize DeepSeek model: {str(e)}")
            
        # try:
        #     print("Initializing Azure DeepSeek model...")
        #     self.models.append(AzureDeepSeekModel(test_mode=test_mode))
        #     if not self.current_model:
        #         self.current_model = self.models[-1]
        # except Exception as e:
        #     print(f"Failed to initialize Azure model: {str(e)}")
            
            
        if not self.models:
            raise RuntimeError("Failed to initialize any model in the chain")

    def _try_next_model(self):
        """Try to switch to the next available model in the chain"""
        current_index = self.models.index(self.current_model)
        if current_index >= len(self.models) - 1 and len(self.models):
            current_index = 0
        if current_index < len(self.models) - 1:
            self.current_model = self.models[current_index + 1]
            model_names = [
                # "4o",
                "Volcano"
                "DeepSeek",
                # "Azure", 
            ]
            print(f"Switching to {model_names[current_index + 1]} model...")
            return True
        return False

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate response using the model chain
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        last_error = None
        while True:
            try:
                return await self.current_model.generate(prompt, **kwargs)
            except Exception as e:
                last_error = e
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")

    async def generate_stream(self, prompt: str, **kwargs):
        """Generate response using the model chain
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        last_error = None
        while True:
            try:
                async for chunk in self.current_model.generate_stream(prompt, **kwargs):
                    yield chunk
                return
            except Exception as e:
                print(f"Error: {str(e)}")
                print("Retrying with next model...")
                last_error = e
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")

    async def stream_call(self, user_prompt: str, **kwargs):
        """Generate response using the model chain
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        last_error = None
        while True:
            try:
                async for chunk in self.current_model.stream_call(user_prompt=user_prompt, **kwargs):
                    yield chunk
                return
            except Exception as e:
                print(f"Error: {str(e)}")
                print("Retrying with next model...")
                last_error = e
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")


    def chat_completion(
        self,
        messages: List[dict],
        stream: bool = True,
        max_tokens: int = 2048,
    ) -> Union[str, Iterator[str]]:
        """Get chat completion using the model chain
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            stream: Whether to stream the response
            max_tokens: Maximum tokens in response
            
        Returns:
            If stream=True, returns an iterator of response chunks
            If stream=False, returns complete response as string
        """
        last_error = None
        while True:
            try:
                return self.current_model.chat_completion(
                    messages=messages,
                    stream=stream,
                    max_tokens=max_tokens
                )
            except Exception as e:
                last_error = e
                print(f"Error: {str(last_error)}")
                if not self._try_next_model():
                    raise RuntimeError(f"All models in chain failed. Last error: {str(last_error)}")
    
    def close(self):
        """Close all model connections"""
        for model in self.models:
            try:
                model.close()
            except:
                pass
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 