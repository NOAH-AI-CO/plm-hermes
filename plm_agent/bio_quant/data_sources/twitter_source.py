import os
import http.client
import json
import pandas as pd
from typing import Dict, Any, List
from ..core.interfaces import DataSource
import aiohttp

class TwitterDataSource(DataSource):
    """Twitter data source for social media sentiment analysis"""
    
    def __init__(self):
        """Initialize Twitter data source with API key"""
        self.api_key = os.getenv('TWITTER_API_KEY')
        if not self.api_key:
            raise ValueError("TWITTER_API_KEY environment variable not found")
        
        self.api_host = "twitter-api45.p.rapidapi.com"
        self.output_dir = None
        
    def set_output_dir(self, output_dir: str):
        """Set output directory for data files"""
        self.output_dir = output_dir

    def _save_data(self, data: Any, filename: str):
        """Save data to file"""
        try:
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            filepath = os.path.join(data_dir, filename)
            
            if isinstance(data, pd.DataFrame):
                data.to_csv(filepath, index=False)
            elif isinstance(data, (dict, list)):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            
            print(f"数据已保存至：{filepath}")
        except Exception as e:
            print(f"保存数据失败 {filename}: {str(e)}")

    async def _make_request(self, query: str, search_type: str = 'Latest') -> List[Dict[str, Any]]:
        """Make an async request to the Twitter API
        
        Args:
            query: Search query (e.g. "$TSLA") 
            search_type: Type of search ('Latest' or 'Top')
            
        Returns:
            List of tweets
        """
        try:
            
            headers = {
                'x-rapidapi-key': self.api_key,
                'x-rapidapi-host': self.api_host
            }
            
            url = f"https://{self.api_host}/search.php?query={query}&search_type={search_type}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    data = await response.json()
                    return data.get('timeline', [])[:15]  # Return top 15 tweets
                    
        except Exception as e:
            print(f"Twitter API request failed: {str(e)}")
            return []

    async def get_tweets(self, symbol: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get latest and top tweets for a symbol
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary containing latest and top tweets
        """
        try:
            print(f"\n获取{symbol}相关推文...")
            
            # Format query
            query = f"%24{symbol}"  # Add $ symbol and encode
            
            # Get latest tweets
            latest_tweets = await self._make_request(query, 'Latest')
            print(f"获取到 {len(latest_tweets)} 条最新推文")
            
            # Get top tweets
            top_tweets = await self._make_request(query, 'Top')
            print(f"获取到 {len(top_tweets)} 条热门推文")
            
            # Save data
            tweets_data = {
                'latest': latest_tweets,
                'top': top_tweets
            }
            # self._save_data(tweets_data, 'tweets.json')
            
            return tweets_data
            
        except Exception as e:
            print(f"获取推文数据失败: {str(e)}")
            return {'latest': [], 'top': []}

    # Required interface methods (not implemented)
    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        return {}
    
    async def get_stock_data(self, symbol: str, period: str = '6mo') -> pd.DataFrame:
        return pd.DataFrame()
    
    async def get_technical_indicator(self, symbol: str, indicator_type: str, period: int = 14,
                              timeframe: str = '1day', start_date: str = None, 
                              end_date: str = None) -> pd.DataFrame:
        return pd.DataFrame()
    
    async def get_all_technical_indicators(self, symbol: str, period: int = 14) -> Dict[str, pd.DataFrame]:
        return {}
    
    async def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        return {'calls': pd.DataFrame(), 'puts': pd.DataFrame()}
    
    async def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        return {}
    
    async def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        return []
    
    async def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        return [] 