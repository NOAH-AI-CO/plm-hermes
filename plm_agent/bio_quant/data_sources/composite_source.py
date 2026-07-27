from typing import Dict, Any, Optional, List
import pandas as pd
from ..core.interfaces import DataSource
from .twitter_source import TwitterDataSource

class CompositeDataSource(DataSource):
    """Composite data source that combines multiple data sources"""
    
    def __init__(self, 
                 primary_source: DataSource, 
                 options_source: Optional[DataSource] = None,
                 twitter_source: Optional[DataSource] = None):
        """Initialize composite data source
        
        Args:
            primary_source: Primary data source for stock data and technical indicators
            options_source: Data source for options data (optional)
        """
        self.primary_source = primary_source
        # Default to PolygonOptionsSource if no options source provided
        if options_source is None:
            from .polygon_source import PolygonOptionsSource
            try:
                options_source = PolygonOptionsSource()
            except Exception as e:
                print(f"Warning: Failed to initialize PolygonOptionsSource: {str(e)}")
                print("Options data will be fetched from primary source")
        self.options_source = options_source
        
        # Initialize Twitter source
        if twitter_source is not None:
            self.twitter_source = twitter_source
        else:
            self.twitter_source = None
            
        self.output_dir = None
    
    def set_output_dir(self, output_dir: str):
        """Set output directory for all data sources"""
        self.output_dir = output_dir
        self.primary_source.set_output_dir(output_dir)
        if self.options_source:
            self.options_source.set_output_dir(output_dir)

    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Get company profile information from primary source"""
        return await self.primary_source.get_company_info(symbol)
    
    async def get_stock_data(self, symbol: str, period: str = '6mo') -> pd.DataFrame:
        """Get stock price data from primary source"""
        return await self.primary_source.get_stock_data(symbol, period)
    
    async def get_technical_indicator(self, symbol: str, indicator_type: str, period: int = 14,
                              timeframe: str = '1day', start_date: str = None, 
                              end_date: str = None) -> pd.DataFrame:
        """Get technical indicator data from primary source"""
        return await self.primary_source.get_technical_indicator(
            symbol=symbol,
            indicator_type=indicator_type,
            period=period,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date
        )
    
    async def get_all_technical_indicators(self, symbol: str, period: int = 14) -> Dict[str, pd.DataFrame]:
        """Get all technical indicators from primary source"""
        return await self.primary_source.get_all_technical_indicators(symbol, period)
    
    async def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Get options data from Polygon options source if available, otherwise from primary source"""
        if self.options_source:
            try:
                print(f"\n尝试从 Polygon API 获取期权数据...")
                # Use get_options_chain for Polygon source
                if hasattr(self.options_source, 'get_options_chain'):
                    print("调用 get_options_chain 方法...")
                    data = await self.options_source.get_options_chain(symbol)
                    if data.get('calls') is not None and not data['calls'].empty:
                        print("成功获取期权数据")
                        return data
                    else:
                        print("未获取到期权数据，尝试使用备选数据源")
                # Fallback to get_options_data for other sources
                print("调用 get_options_data 方法...")
                return await self.options_source.get_options_data(symbol)
            except Exception as e:
                print(f"Warning: Failed to get options data from options source: {str(e)}")
                print("Falling back to primary source...")
        return await self.primary_source.get_options_data(symbol)
    
    async def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Get financial data from primary source"""
        return await self.primary_source.get_financial_data(symbol)
        
    async def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """Get stock news from primary source"""
        return await self.primary_source.get_stock_news(symbol, limit, from_date, to_date)
        
    async def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get press releases from primary source"""
        return await self.primary_source.get_press_releases(symbol, limit)

    async def get_tweets(self, symbol: str) -> Dict[str, List[Dict[str, Any]]]:
        """Get tweets data from Twitter source if available"""
        if self.twitter_source:
            try:
                return self.twitter_source.get_tweets(symbol)
            except Exception as e:
                print(f"Warning: Failed to get tweets data: {str(e)}")
        return {'latest': [], 'top': []} 