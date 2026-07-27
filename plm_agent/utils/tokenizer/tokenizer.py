import os
import logging
import transformers
import tiktoken
from typing import List, Union

from anthropic import AnthropicVertex
from config import api_config

logger = logging.getLogger(__name__)


class Tokenizer:
    
    def __init__(self):
        r"""
        init local tokenizer 
        """
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
        deepseek_v3_tokenizer_path = os.path.join(STATIC_DIR, "tokenizer/deepseek-v3")
        self.deepseekv3_tokenizer = transformers.AutoTokenizer.from_pretrained(deepseek_v3_tokenizer_path, trust_remote_code=True)
        
        # Initialize Claude client for token counting (lazy initialization)
        # Use a dedicated sync client to avoid interfering with async clients
        self._claude_client = None
    
    def _get_claude_client(self) -> AnthropicVertex:
        """Get or create Claude client for token counting."""
        if self._claude_client is None:
            self._claude_client = AnthropicVertex(
                region=api_config.VERTEX_CLAUDEOPUS4_REGION,
                project_id=api_config.VERTEX_PROJECT_ID,
                timeout=30
            )
        return self._claude_client

    def _connect_messages(self, user_prompt: str, history_messages: List[dict] = None) -> str:
        if history_messages is None:
            history_messages = []
            
        user_message = {
            "role": "user",
            "content": user_prompt,
        }

        messages = history_messages + [user_message]

        full_prompt = ""
        for message in messages:
            # just convert message to string, for llm response
            full_prompt += str(message)

        return full_prompt

    def deepseek_v3(self, user_prompt: str, history_messages: List[dict] = None):
        if history_messages is None:
            history_messages = []
        return self.deepseekv3_tokenizer.encode(self._connect_messages(user_prompt, history_messages))

    def openai(self, user_prompt: str, history_messages: List[dict] = None, model: str = 'openai'):
        if history_messages is None:
            history_messages = []
        if model == 'openai':
            enc = tiktoken.encoding_for_model("gpt-4o")
        else:
            enc = tiktoken.get_encoding("o200k_base")
        return enc.encode(self._connect_messages(user_prompt, history_messages))
    
    def get_token_count(self, text: Union[str, bytes], model: str) -> int:
        """Get the actual token count for a given text."""
        # Convert bytes to string if necessary
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        
        if 'deepseek' in model:
            return len(self.deepseekv3_tokenizer.encode(text))
        elif 'openai-o3' in model:
            enc = tiktoken.get_encoding("o200k_base")
            return len(enc.encode(text))
        elif 'openai' in model:
            enc = tiktoken.encoding_for_model("gpt-4o")
            return len(enc.encode(text))
        elif 'claude' in model:
            return self._get_claude_token_count(text)
        else:
            raise ValueError(f"Unsupported model: {model}")
    
    def _get_claude_token_count(self, text: str) -> int:
        """Get token count for text using Claude Haiku's tokenizer via Vertex AI."""
        try:
            client = self._get_claude_client()
            # Use Haiku model for token counting (more cost-effective)
            response = client.messages.count_tokens(
                model=api_config.VERTEX_CLAUDEHAIKU45_MODEL_ID,
                messages=[{"role": "user", "content": text}]
            )
            return response.input_tokens
        except Exception as e:
            logger.warning(f"Claude token counting failed: {e}, falling back to char estimate")
            # Fallback: estimate ~3.5 chars per token for Claude
            return len(text) // 3
    
    def calculate_token_ratio(self, text: str, model: str) -> float:
        """Calculate the ratio of characters to tokens for a given text."""
        tokens = self.get_token_count(text, model)
        chars = len(text)
        return chars / tokens if tokens > 0 else 1

    def truncate_by_tokens(self, text: Union[str, bytes], max_tokens: int, model: str, max_iterations: int = 5) -> str:
        """Truncate text to fit within max_tokens with iterative refinement."""
        # Convert bytes to string if necessary
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')

        if len(text) == 0 or max_tokens <= 0:
            return text

        truncated = text
        current_tokens = self.get_token_count(text, model)
                
        for i in range(max_iterations):
            if current_tokens <= max_tokens:
                return truncated

            # Avoid division by zero
            if current_tokens == 0:
                return ""
            
            # Calculate target length based on token ratio
            ntl = max_tokens * len(truncated) / current_tokens
            new_length = int(ntl)
            
            # Ensure we're making progress (at least reduce by 1 character)
            if new_length >= len(truncated):
                new_length = max(0, len(truncated) - 1)
            
            truncated = truncated[:new_length]
            
            # If truncated to empty, return empty string
            if len(truncated) == 0:
                return ""
            
            current_tokens = self.get_token_count(truncated, model)
        
        # If iterations exhausted and still over limit, use binary search
        # to find the maximum length that fits within max_tokens
        if current_tokens > max_tokens:
            low, high = 0, len(truncated)
            best_truncated = ""
            
            while low <= high:
                mid = (low + high) // 2
                test_truncated = text[:mid]
                if len(test_truncated) == 0:
                    low = mid + 1
                    continue
                    
                test_tokens = self.get_token_count(test_truncated, model)
                
                if test_tokens <= max_tokens:
                    best_truncated = test_truncated
                    low = mid + 1
                else:
                    high = mid - 1
            
            return best_truncated
        
        return truncated[:3000]


tokenizer = Tokenizer()
