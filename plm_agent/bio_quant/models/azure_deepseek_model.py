import os
from typing import List, Optional, Iterator, Union
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from ..core.interfaces import LLMModel
from .deepseek_model import DeepSeekModel

class AzureDeepSeekModel(LLMModel):
    """Azure DeepSeek model wrapper with fallback to regular DeepSeek"""
    
    def __init__(self, test_mode: bool = False):
        """Initialize the Azure DeepSeek model client with fallback
        
        Args:
            test_mode (bool): If True, use DeepSeek-V3 model for testing, otherwise use DeepSeek-R1
        """
        self.api_key = os.getenv("AZURE_DS_KEY")
        if not self.api_key:
            raise ValueError("AZURE_DS_KEY environment variable not set")
            
        self.endpoint = "https://andy-m6mfrfc1-francecentral.services.ai.azure.com/models"
        self.test_mode = test_mode
        self.model_name = "DeepSeek-R1"  # Azure only supports DeepSeek-R1 currently
        self.max_tokens = 2000 if test_mode else 8000
        
        # Initialize fallback model
        self.fallback_model = None
        
        try:
            self.client = ChatCompletionsClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.api_key),
            )
        except AzureError as e:
            print(f"Failed to initialize Azure client: {str(e)}")
            print("Initializing fallback DeepSeek model...")
            self._init_fallback_model()

    def _init_fallback_model(self):
        """Initialize the fallback DeepSeek model"""
        try:
            self.fallback_model = DeepSeekModel(test_mode=self.test_mode)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize both Azure and fallback models: {str(e)}")

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate response from the model with fallback
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        try:
            messages = [
                SystemMessage(content="You are a helpful assistant specialized in stock analysis."),
                UserMessage(content=prompt)
            ]
            
            max_tokens = kwargs.get('max_tokens', self.max_tokens)
            
            response = self.client.complete(
                stream=False,
                messages=messages,
                max_tokens=max_tokens,
                model=self.model_name,
                timeout=300
            )
            
            return response.choices[0].message.content
                
        except AzureError as e:
            print(f"Azure API error: {str(e)}")
            print("Falling back to DeepSeek model...")
            
            # Initialize fallback model if not already done
            if not self.fallback_model:
                self._init_fallback_model()
                
            # Try with fallback model
            return await self.fallback_model.generate(prompt, max_tokens=max_tokens)
            
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            if not self.fallback_model:
                self._init_fallback_model()
            return self.fallback_model.generate(prompt, max_tokens=max_tokens)

    def chat_completion(
        self,
        messages: List[dict],
        stream: bool = True,
        max_tokens: int = 2048,
    ) -> Union[str, Iterator[str]]:
        """Get chat completion with fallback to DeepSeek
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            stream: Whether to stream the response
            max_tokens: Maximum tokens in response
            
        Returns:
            If stream=True, returns an iterator of response chunks
            If stream=False, returns complete response as string
        """
        try:
            azure_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    azure_messages.append(SystemMessage(content=msg["content"]))
                elif msg["role"] == "user":
                    azure_messages.append(UserMessage(content=msg["content"]))
            
            response = self.client.complete(
                stream=stream,
                messages=azure_messages,
                max_tokens=max_tokens,
                model=self.model_name,
                timeout=300
            )
            
            if stream:
                def response_iterator():
                    for update in response:
                        if update.choices:
                            chunk = update.choices[0].delta.content
                            if chunk:
                                yield chunk
                return response_iterator()
            else:
                return response.choices[0].message.content
                
        except (AzureError, Exception) as e:
            print(f"Azure API error: {str(e)}")
            print("Falling back to DeepSeek model...")
            
            if not self.fallback_model:
                self._init_fallback_model()
                
            # Convert messages to DeepSeek format if needed
            if stream:
                print("Warning: Streaming not supported in fallback mode")
            return self.fallback_model.generate(messages[-1]["content"], max_tokens=max_tokens)
            
    def close(self):
        """Close all model connections"""
        if hasattr(self, 'client'):
            self.client.close()
        if self.fallback_model:
            self.fallback_model.close()
            
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 