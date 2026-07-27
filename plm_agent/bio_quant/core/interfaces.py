from abc import ABC, abstractmethod
import io
from typing import Any, Dict, List, Optional
import pandas as pd

class LLMModel(ABC):
    """Base interface for LLM models"""
    @abstractmethod
    async def generate(self, prompt: str, **kwargs):
        """Generate response from the model"""
        pass

    async def generate_stream(self, prompt: str, stream: bool = True, stream_status: dict = {}, temperature = 0.6, **kwargs):
        """Generate response from the model
        
        Args:
            prompt: The input prompt
            **kwargs: Additional arguments passed to the model
            
        Returns:
            The model's response as a string
        """
        try:
            sys_prompt = ('system_prompt' not in kwargs or kwargs['system_prompt'])
            messages = [
                {"role": "system", "content": "You are a professional financial analyst specializing in biotech companies."},
                {"role": "user", "content": prompt}
            ]  if sys_prompt else [{"role": "user", "content": prompt}]
            
            max_tokens = kwargs.get('max_tokens', self.max_tokens if hasattr(self, 'max_tokens') else 8192)
            
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=15
            )
            print(f'using temp: {temperature}')
            
            if stream:
                if 'enabled' in stream_status and stream_status['enabled']:
                    stream_status['reasoning_content'] = io.StringIO()
                    stream_status['answer_content'] = io.StringIO() 
                reasoning_flag = False
                async for chunk in completion:
                    if len(chunk.choices) > 0:
                        chunk_content = None
                        content = getattr(chunk.choices[0].delta, 'content', None)
                        reasoning_content = getattr(chunk.choices[0].delta, 'reasoning_content', None)

                        # Huoshan and deepseek original put thinking in reasoning_content
                        if reasoning_content is not None and reasoning_content != '':
                            if not reasoning_flag:
                                reasoning_flag = True
                                chunk_content = f"<think>\n{reasoning_content}"
                            else:
                                chunk_content = reasoning_content
                            if 'reasoning_content' in stream_status:
                                stream_status['reasoning_content'].write(reasoning_content)
                                

                        # Get chunk_content, while in the reasoning stream there may be empty chunk, check content is 
                        if content is not None and content != '':
                            if reasoning_flag:
                                reasoning_flag = False
                                stream_status['reasoning_end_flag'] = True
                                chunk_content = f"</think>\n{content}"
                            else:
                                chunk_content = content
                            if 'answer_content' in stream_status:
                                stream_status['answer_content'].write(content)
                            
                        if chunk_content:
                            yield chunk_content
            else:
                yield completion.choices[0].message.content
            
        except Exception as e:
            print("error", e)
            raise RuntimeError(f"Volcano API error: {str(e)}")

class DataSource(ABC):
    """Base interface for data sources"""
    @abstractmethod
    async def get_stock_data(self, symbol: str, period: str) -> pd.DataFrame:
        """Get stock price data"""
        pass
    
    @abstractmethod
    async def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Get financial data"""
        pass
    
    @abstractmethod
    async def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Get options data"""
        pass
        
    @abstractmethod
    async def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """Get stock news data
        
        Args:
            symbol: Stock symbol
            limit: Number of news articles to return (default: 100)
            from_date: Start date in YYYY-MM-DD format (optional)
            to_date: End date in YYYY-MM-DD format (optional)
            
        Returns:
            List of news articles with fields:
            - symbol: Stock symbol
            - publishedDate: Publication date
            - title: News title
            - summary: News summary
            - url: Source URL
            - source: Source website
        """
        pass
        
    @abstractmethod
    async def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get company press releases
        
        Args:
            symbol: Stock symbol
            limit: Number of press releases to return (default: 100)
            
        Returns:
            List of press releases with fields:
            - symbol: Stock symbol
            - publishedDate: Publication date
            - title: Press release title
            - summary: Press release content
            - type: 'press_release'
        """
        pass

    def set_output_dir(self, output_dir: str):
        """Set output directory for data files"""
        self.output_dir = output_dir

class Analyzer(ABC):
    """Base interface for analyzers"""
    @abstractmethod
    def analyze(self, data: Any) -> str:
        """Analyze the data and return insights"""
        pass

class PromptTemplate(ABC):
    """Base interface for prompt templates"""
    @abstractmethod
    def format(self, **kwargs) -> str:
        """Format the prompt template with given parameters"""
        pass 