import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from ..core.interfaces import DataSource
import json
import time
import aiohttp
import asyncio

class PolygonOptionsSource(DataSource):
    """Polygon.io data source for options data"""
    
    def __init__(self):
        """Initialize Polygon data source with API key"""
        self.api_key = os.getenv('POLYGON_API_KEY')
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY environment variable not found")
        
        self.base_url = "https://api.polygon.io/v3"
        self.output_dir = None
        
    def set_output_dir(self, output_dir: str):
        """Set output directory for data files"""
        self.output_dir = output_dir

    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None, max_retries: int = 3, retry_delay: int = 2) -> Any:
        """Make an async request to the Polygon API with retry mechanism
        
        Args:
            endpoint: API endpoint
            params: Query parameters (optional)
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 2)
            
        Returns:
            JSON response data
        """

        attempt = 0
        last_error = None
        
        while attempt < max_retries:
            try:
                # Ensure params is a dictionary
                if params is None:
                    params = {}
                
                # Add API key to parameters
                params['apiKey'] = self.api_key
                
                # Make async request
                url = f"{self.base_url}{endpoint}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        response.raise_for_status()
                        data = await response.json()
                        
                if data.get('status') != 'OK':
                    raise ValueError(f"API error: {data.get('error')}")
                    
                return data
                
            except (aiohttp.ClientError, ValueError) as e:
                last_error = str(e)
                attempt += 1
                if attempt < max_retries:
                    print(f"Request failed (attempt {attempt}/{max_retries}): {last_error}. Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                continue
                
        raise Exception(f"API request failed after {max_retries} attempts. Last error: {last_error}")

    def _save_data(self, data: Any, filename: str):
        """Save data to file"""
        try:
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            filepath = os.path.join(data_dir, filename)
            
            if isinstance(data, pd.DataFrame):
                data.to_csv(filepath, index=False)
            elif isinstance(data, dict):
                pd.DataFrame(data).to_csv(filepath, index=False)
            
            print(f"数据已保存至：{filepath}")
        except Exception as e:
            print(f"保存数据失败 {filename}: {str(e)}")

    def _calculate_market_metrics(self, calls_df: pd.DataFrame, puts_df: pd.DataFrame, stock_price: float) -> Dict[str, Any]:
        """Calculate additional market sentiment metrics
        
        Args:
            calls_df: DataFrame with call options data
            puts_df: DataFrame with put options data
            stock_price: Current stock price
            
        Returns:
            Dictionary containing market metrics
        """
        try:
            metrics = {}
            
            # 1. IV Skew Analysis
            if not calls_df.empty and not puts_df.empty:
                # Get ATM options (closest to current stock price)
                atm_calls = calls_df[abs(calls_df['strike'] - stock_price).idxmin()]
                atm_puts = puts_df[abs(puts_df['strike'] - stock_price).idxmin()]
                
                metrics['iv_skew'] = {
                    'atm_call_iv': atm_calls['impliedVolatility'],
                    'atm_put_iv': atm_puts['impliedVolatility'],
                    'skew_ratio': atm_puts['impliedVolatility'] / atm_calls['impliedVolatility']
                }
                
            # 2. Put/Call Ratio Analysis
            total_call_volume = calls_df['volume'].sum()
            total_put_volume = puts_df['volume'].sum()
            total_call_oi = calls_df['openInterest'].sum()
            total_put_oi = puts_df['openInterest'].sum()
            
            metrics['put_call_ratios'] = {
                'volume_ratio': total_put_volume / total_call_volume if total_call_volume > 0 else 0,
                'oi_ratio': total_put_oi / total_call_oi if total_call_oi > 0 else 0
            }
            
            # 3. Strike Price Concentration Analysis
            call_oi_by_strike = calls_df.groupby('strike')['openInterest'].sum()
            put_oi_by_strike = puts_df.groupby('strike')['openInterest'].sum()
            
            metrics['strike_concentration'] = {
                'max_call_oi_strike': call_oi_by_strike.idxmax(),
                'max_put_oi_strike': put_oi_by_strike.idxmax()
            }
            
            # 4. Expiration Concentration Analysis
            call_oi_by_exp = calls_df.groupby('expiration')['openInterest'].sum()
            put_oi_by_exp = puts_df.groupby('expiration')['openInterest'].sum()
            
            metrics['expiration_concentration'] = {
                'max_call_oi_date': call_oi_by_exp.idxmax(),
                'max_put_oi_date': put_oi_by_exp.idxmax()
            }
            
            # 5. IV Term Structure
            call_iv_by_exp = calls_df.groupby('expiration')['impliedVolatility'].mean()
            put_iv_by_exp = puts_df.groupby('expiration')['impliedVolatility'].mean()
            
            metrics['iv_term_structure'] = {
                'call_iv_term': call_iv_by_exp.to_dict(),
                'put_iv_term': put_iv_by_exp.to_dict()
            }
            
            return metrics
            
        except Exception as e:
            print(f"Warning: Failed to calculate market metrics: {str(e)}")
            return {}

    async def get_options_chain(self, symbol: str, stock_price: float = None, max_retries: int = 3, retry_delay: int = 2) -> Dict[str, Any]:
        """Get options chain data for a symbol with retry mechanism"""
        try:
            print(f"\n获取{symbol}期权数据...")
            
            # Get options with pagination to handle more than 250 contracts
            all_results = []
            next_url = None
            
            endpoint = f"/snapshot/options/{symbol}"
            params = {
                'limit': 250,
                'sort': 'expiration_date',
                'order': 'asc'
            }
            
            while True:
                attempt = 0
                while attempt < max_retries:
                    try:
                        if next_url:
                            response = requests.get(next_url, params={'apiKey': self.api_key})
                            response.raise_for_status()
                            response = response.json()
                        else:
                            response = await self._make_request(endpoint, params)
                        
                        if not response or 'results' not in response:
                            break
                            
                        all_results.extend(response['results'])
                        next_url = response.get('next_url')
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        attempt += 1
                        if attempt < max_retries:
                            print(f"Failed to fetch options data (attempt {attempt}/{max_retries}): {str(e)}. Retrying in {retry_delay} seconds...")
                            await asyncio.sleep(retry_delay)
                        else:
                            print(f"Failed to fetch options data after {max_retries} attempts: {str(e)}")
                            raise
                
                if not next_url:
                    break

            if not all_results:
                print("No options data found")
                return self._empty_response()

            # Process options data more efficiently
            calls_data = []
            puts_data = []
            expiration_dates = set()

            # Extract stock price once if not provided
            if stock_price is None:
                for contract in all_results:
                    if 'underlying_asset' in contract and 'price' in contract['underlying_asset']:
                        stock_price = float(contract['underlying_asset']['price'])
                        break

            # Process contracts in bulk
            for contract in all_results:
                details = contract.get('details', {})
                day = contract.get('day', {})
                greeks = contract.get('greeks', {})
                last_quote = contract.get('last_quote', {})
                
                contract_data = {
                    'expiration': details.get('expiration_date'),
                    'strike': details.get('strike_price'),
                    'type': details.get('contract_type'),
                    'volume': day.get('volume', 0),
                    'openInterest': contract.get('open_interest', 0),
                    'lastPrice': day.get('close'),
                    'bid': last_quote.get('bid'),
                    'ask': last_quote.get('ask'),
                    'impliedVolatility': contract.get('implied_volatility'),
                    'delta': greeks.get('delta'),
                    'gamma': greeks.get('gamma'),
                    'theta': greeks.get('theta'),
                    'vega': greeks.get('vega'),
                    'inTheMoney': None,  # Will be calculated below
                    'breakEvenPrice': contract.get('break_even_price'),
                    'exerciseStyle': details.get('exercise_style')
                }

                # Calculate inTheMoney if we have stock price
                if stock_price is not None and contract_data['strike'] is not None:
                    strike = float(contract_data['strike'])
                    contract_data['inTheMoney'] = (
                        (contract_data['type'] == 'call' and stock_price > strike) or
                        (contract_data['type'] == 'put' and stock_price < strike)
                    )

                if contract_data['type'] == 'call':
                    calls_data.append(contract_data)
                elif contract_data['type'] == 'put':
                    puts_data.append(contract_data)
                    
                if contract_data['expiration']:
                    expiration_dates.add(contract_data['expiration'])

            # Convert to DataFrames efficiently
            calls_df = pd.DataFrame(calls_data)
            puts_df = pd.DataFrame(puts_data)
            
            # Sort DataFrames if not empty
            for df in [calls_df, puts_df]:
                if not df.empty:
                    df.sort_values(['expiration', 'strike'], inplace=True)
                    df.reset_index(drop=True, inplace=True)

            return {
                'calls': calls_df,
                'puts': puts_df,
                'expiration_dates': sorted(list(expiration_dates)),
                'stock_price': stock_price
            }
            
        except Exception as e:
            print(f"获取期权数据失败: {str(e)}")
            return self._empty_response()

    def _empty_response(self):
        """Return empty response structure"""
        return {
            'calls': pd.DataFrame(),
            'puts': pd.DataFrame(),
            'expiration_dates': [],
            'stock_price': None
        }

    async def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Get options data (interface method that calls get_options_chain)"""
        print(f"\nPolygonOptionsSource.get_options_data called for {symbol}")
        try:
            # Get stock price from the data passed to analyze()
            stock_price = None
            if hasattr(self, 'latest_price'):
                stock_price = self.latest_price
            
            data = await self.get_options_chain(symbol, stock_price)
            print(f"Got options data: {len(data.get('calls', []))} calls, {len(data.get('puts', []))} puts")
            return data
        except Exception as e:
            print(f"Error in get_options_data: {str(e)}")
            return self._empty_response()

    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Not implemented - using primary source"""
        return {}
    
    async def get_stock_data(self, symbol: str, period: str = '6mo') -> pd.DataFrame:
        """Not implemented - using primary source"""
        return pd.DataFrame()
    
    async def get_technical_indicator(self, symbol: str, indicator_type: str, period: int = 14,
                              timeframe: str = '1day', start_date: str = None, 
                              end_date: str = None) -> pd.DataFrame:
        """Not implemented - using primary source"""
        return pd.DataFrame()
    
    async def get_all_technical_indicators(self, symbol: str, period: int = 14) -> Dict[str, pd.DataFrame]:
        """Not implemented - using primary source"""
        return {}
    
    async def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Not implemented - using primary source"""
        return {}
    
    async def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """Not implemented - using primary source"""
        return []
    
    async def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Not implemented - using primary source"""
        return [] 