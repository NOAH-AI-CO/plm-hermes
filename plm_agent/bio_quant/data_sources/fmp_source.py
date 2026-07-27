import asyncio
import os
import json
import ssl
import aiohttp
import requests
import pandas as pd
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List, Tuple
from ..core.interfaces import DataSource
import pytz
import time
import dotenv
dotenv.load_dotenv()

class FMPDataSource(DataSource):
    """Financial Modeling Prep (FMP) data source"""
    
    def __init__(self):
        """Initialize FMP data source with API key"""
        self.api_key = os.getenv('FMP_API_KEY')
        if not self.api_key:
            raise ValueError("FMP_API_KEY environment variable not found")
        
        self.base_url = "https://financialmodelingprep.com/api"
        self.v3_url = f"{self.base_url}/v3"
        self.v4_url = f"{self.base_url}/v4"
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
            elif isinstance(data, dict):
                # Create a copy of the data to avoid modifying the original
                data_copy = data.copy()
                # Convert date objects to strings
                for key, value in data_copy.items():
                    if isinstance(value, (datetime, date)):  # Fixed type check
                        data_copy[key] = value.strftime('%Y-%m-%d')
                    
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data_copy, f, indent=4, ensure_ascii=False)
            
            print(f"数据已保存至：{filepath}")
        except Exception as e:
            print(f"保存数据失败 {filename}: {str(e)}")
            print(data)
        
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Any:
        """Make an async request to the FMP API with enhanced error handling
        
        Args:
            endpoint: API endpoint
            params: Query parameters (optional)
            
        Returns:
            JSON response data
        """
        try:
            # Ensure params is a dictionary
            if params is None:
                params = {}
            
            # Add API key to parameters
            params['apikey'] = self.api_key
            
            # 最多重试3次
            max_retries = 3
            retry_count = 0
            
            async with aiohttp.ClientSession() as session:
                while retry_count < max_retries:
                    try:
                        # 设置较长的超时时间
                        timeout = aiohttp.ClientTimeout(total=30)
                        async with session.get(endpoint, params=params, timeout=timeout) as response:
                            response.raise_for_status()
                            data = await response.json()
                            
                            if not data and not isinstance(data, list):
                                return []
                                
                            return data
                            
                    except aiohttp.ClientSSLError as e:
                        print(f"\n警告: SSL连接错误 (尝试 {retry_count + 1}/{max_retries}): {str(e)}")
                        if retry_count == max_retries - 1:  # 最后一次尝试
                            print("尝试禁用SSL验证...")
                            ssl_context = ssl.create_default_context()
                            ssl_context.check_hostname = False
                            ssl_context.verify_mode = ssl.CERT_NONE
                            async with session.get(endpoint, params=params, timeout=timeout, ssl=ssl_context) as response:
                                response.raise_for_status()
                                return await response.json()
                                
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        if retry_count == max_retries - 1:
                            raise
                        print(f"\n警告: 请求错误 (尝试 {retry_count + 1}/{max_retries}): {str(e)}")
                        
                    retry_count += 1
                    if retry_count < max_retries:
                        sleep_time = 2 ** retry_count  # 指数退避
                        print(f"等待 {sleep_time} 秒后重试...")
                        await asyncio.sleep(sleep_time)
                
                raise Exception("达到最大重试次数")
                
        except aiohttp.ClientError as e:
            raise Exception(f"API请求失败: {str(e)}")
        except Exception as e:
            raise Exception(f"处理API响应时出错: {str(e)}")
            
    def _format_symbol(self, symbol: str) -> str:
        """Format symbol for FMP API"""
        symbol = symbol.strip().upper()
        
        return symbol

    async def _get_historical_data(self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        """Get historical price data from FMP API
        
        Args:
            symbol: Stock symbol
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            
        Returns:
            DataFrame with historical price data
        """
        try:
            # Build API URL - use v3 endpoint
            url = f"{self.v3_url}/historical-price-full/{symbol}"
            params = {'apikey': self.api_key}
            
            # Only add date parameters if they are valid and not in the future
            today = datetime.now().date()
            if start_date:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                if start_date_obj <= today:
                    params['from'] = start_date
            if end_date:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                if end_date_obj <= today:
                    params['to'] = end_date
            
            # Make API request
            data = await self._make_request(endpoint=url, params=params)
            
            if 'historical' not in data:
                raise ValueError(f"No historical data found for symbol {symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(data['historical'])
            
            # Convert date column to datetime
            df['date'] = pd.to_datetime(df['date'])
            
            # Sort by date in ascending order
            df = df.sort_values('date')
            
            # Set date as index
            df.set_index('date', inplace=True)
            
            # Rename columns to match standard format
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'adjClose': 'Adj Close',
                'volume': 'Volume'
            })
            
            # Select only necessary columns
            df = df[['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']]
            
            return df
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching data from FMP API: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing FMP data: {str(e)}")

    async def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Get company profile information from FMP API
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary containing company information including:
            - Basic info (name, symbol, exchange, sector, industry)
            - Financial metrics (price, beta, market cap, etc.)
            - Contact info (address, phone, website)
            - Company description and leadership
        """
        try:
            symbol = self._format_symbol(symbol)
            
            # Make API request
            response = await self._make_request(
                endpoint=f"{self.v3_url}/profile/{symbol}"
            )
            
            if not response:
                raise ValueError(f"No company information found for symbol {symbol}")
                
            # Get first (and only) item from response
            info = response[0]
            
            # Format employee count as integer
            if info.get('fullTimeEmployees'):
                info['fullTimeEmployees'] = int(info['fullTimeEmployees'].replace(',', ''))
                
            # Format date fields
            if info.get('ipoDate'):
                info['ipoDate'] = datetime.strptime(info['ipoDate'], '%Y-%m-%d').date()
                
            # Print summary
            print("\n公司概况：")
            print(f"公司名称：{info.get('companyName')}")
            print(f"交易所：{info.get('exchange')} ({info.get('exchangeShortName')})")
            print(f"行业：{info.get('sector')} - {info.get('industry')}")
            print(f"CEO：{info.get('ceo')}")
            print(f"员工人数：{info.get('fullTimeEmployees'):,}")
            print(f"总部：{info.get('city')}, {info.get('state')}, {info.get('country')}")
            print(f"网站：{info.get('website')}")
            
            if info.get('ipoDate'):
                print(f"上市日期：{info['ipoDate']}")
                
            print(f"\n市场数据：")
            print(f"当前股价：${info.get('price', 0):.2f}")
            print(f"52周区间：{info.get('range')}")
            print(f"市值：${info.get('mktCap', 0)/1e9:.2f}B")
            print(f"Beta：{info.get('beta', 0):.2f}")
            print(f"平均成交量：{info.get('volAvg', 0):,}")
            if info.get('lastDiv'):
                print(f"股息：${info.get('lastDiv'):.2f}")
                
            # if info.get('description'):
            #     print(info['description'])
                
            # Save to file
            info.pop('image', None)  # Remove image URL, as it contains the name of the api service we use
            self._save_data(info, 'company_info.json')        
            return info
    
        except Exception as e:
            raise Exception(f"Error fetching company information: {str(e)}")

    async def get_stock_data(self, symbol: str, period: str = '6mo') -> pd.DataFrame:
        """Get stock price data for the specified period
        
        Args:
            symbol: Stock symbol
            period: Time period (e.g., '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max')
            
        Returns:
            DataFrame with stock price data
        """
        try:
            symbol = self._format_symbol(symbol)
            
            # Calculate start date based on period
            end_date = datetime.now()
            
            if period == '1d':
                start_date = end_date - timedelta(days=1)
            elif period == '5d':
                start_date = end_date - timedelta(days=5)
            elif period == '1mo':
                start_date = end_date - timedelta(days=30)
            elif period == '3mo':
                start_date = end_date - timedelta(days=90)
            elif period == '6mo':
                start_date = end_date - timedelta(days=180)
            elif period == '1y':
                start_date = end_date - timedelta(days=365)
            elif period == '2y':
                start_date = end_date - timedelta(days=730)
            elif period == '5y':
                start_date = end_date - timedelta(days=1825)
            elif period == '10y':
                start_date = end_date - timedelta(days=3650)
            elif period == 'ytd':
                start_date = datetime(end_date.year, 1, 1)
            else:  # 'max' or invalid period
                start_date = end_date - timedelta(days=1825)  # Default to 5 years
            
            # Format dates for API
            start_date_str = start_date.strftime('%Y-%m-%d')
            end_date_str = end_date.strftime('%Y-%m-%d')
            
            # Get data from FMP
            df = await self._get_historical_data(symbol, start_date_str, end_date_str)
            
            if df.empty:
                raise ValueError(f"No data found for symbol {symbol}")
            
            # Save raw price data
            self._save_data(df, 'price_history.csv')
            
            print("\n股价数据概览：")
            print(f"数据时间范围：{df.index[0].strftime('%Y-%m-%d')} 至 {df.index[-1].strftime('%Y-%m-%d')}")
            print(f"交易日数量：{len(df)}")
            print(f"最新收盘价：{df['Close'].iloc[-1]:.2f}")
            print(f"52周最高：{df['High'].max():.2f}")
            print(f"52周最低：{df['Low'].min():.2f}")
            
            return df
            
        except Exception as e:
            raise Exception(f"Error fetching stock data: {str(e)}")
    
    async def _get_financial_statement(self, symbol: str, statement_type: str, period: str = 'annual') -> json:
        """Get financial statement data from FMP API
        
        Args:
            symbol: Stock symbol
            statement_type: Type of statement ('income-statement', 'balance-sheet-statement', 'cash-flow-statement')
            period: Period ('annual' or 'quarter')
            
        Returns:
            json with financial statement data
        """
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.v3_url}/{statement_type}/{symbol}"
            
            params = {
                'apikey': self.api_key,
                'period': period
            }
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                raise ValueError(f"No {statement_type} data found for symbol {symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(data)

            # save to file
            self._save_data(df, f"{statement_type}.csv")
            
            # # Convert date column to datetime
            # df['date'] = pd.to_datetime(df['date'])
            
            # # Sort by date in descending order (most recent first)
            # df = df.sort_values('date', ascending=False)
            
            return data
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching {statement_type}: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing {statement_type} data: {str(e)}")
    
    def _calculate_ttm(self, quarterly_data: pd.DataFrame, field: str) -> float:
        """Calculate TTM (Trailing Twelve Months) value for a given field
        
        Args:
            quarterly_data: DataFrame with quarterly data (most recent first)
            field: Field name to calculate TTM for
            
        Returns:
            TTM value
        """
        if len(quarterly_data) >= 4:
            return quarterly_data[field].head(4).sum()
        return 0

    async def _get_key_metrics(self, symbol: str, period: str = 'quarter') -> pd.DataFrame:
        """Get key metrics from FMP API
        
        Args:
            symbol: Stock symbol
            period: Period ('annual' or 'quarter')
            
        Returns:
            DataFrame with key metrics
        """
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.v3_url}/key-metrics/{symbol}"
            
            params = {
                'apikey': self.api_key,
                'period': period
            }
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                raise ValueError(f"No key metrics data found for symbol {symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            
            # Convert date column to datetime
            df['date'] = pd.to_datetime(df['date'])
            
            # Sort by date in descending order (most recent first)
            df = df.sort_values('date', ascending=False)
            
            return df
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching key metrics: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing key metrics data: {str(e)}")
    
    async def _get_key_metrics_ttm(self, symbol: str) -> dict:
        """Get TTM key metrics from FMP API
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with TTM key metrics
        """
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.v3_url}/key-metrics-ttm/{symbol}"
            
            params = {
                'apikey': self.api_key
            }
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                raise ValueError(f"No TTM key metrics data found for symbol {symbol}")
            
            return data[0]  # Return first (and only) item
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching TTM key metrics: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing TTM key metrics data: {str(e)}")

    async def _get_revenue_segments(self, symbol: str) -> Tuple[Dict, Dict]:
        """Get revenue segmentation data from FMP API
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Tuple containing:
            - Product segmentation data
            - Geographic segmentation data
        """
        try:
            symbol = self._format_symbol(symbol)
            
            # Common parameters
            params = {
                'symbol': symbol,
                'structure': 'flat',
                'period': 'annual',
                'apikey': self.api_key
            }
            
            # Get product segments
            product_url = f"{self.v4_url}/revenue-product-segmentation"
            product_data = await self._make_request(endpoint=product_url, params=params)  # Directly get data
            
            # Get geographic segments
            geo_url = f"{self.v4_url}/revenue-geographic-segmentation"
            geo_data = await self._make_request(endpoint=geo_url, params=params)  # Directly get data
            
            return product_data, geo_data
            
        except Exception as e:
            print(f"Warning: Could not fetch revenue segments: {str(e)}")
            return None, None

    def _process_revenue_segments(self, product_data: List, geo_data: List) -> Dict[str, Any]:
        """Process revenue segmentation data
        
        Args:
            product_data: Product segmentation data (last 2 years)
            geo_data: Geographic segmentation data (last 2 years)
            
        Returns:
            Dictionary containing processed segment data for the last 2 years
        """
        if not product_data or not geo_data:
            return {}
            
        try:
            # Get last 2 years of data
            product_data = product_data[:2]  # Limit to last 2 years
            geo_data = geo_data[:2]  # Limit to last 2 years
            
            segments_by_year = []
            
            for year_product, year_geo in zip(product_data, geo_data):
                product_date = list(year_product.keys())[0]
                geo_date = list(year_geo.keys())[0]
                
                if product_date != geo_date:
                    continue
                    
                year_data = {
                    'date': product_date,
                    'products': year_product[product_date],
                    'regions': year_geo[geo_date]
                }
                segments_by_year.append(year_data)
            
            return {
                'segments_by_year': segments_by_year
            }
            
        except Exception as e:
            print(f"Warning: Error processing revenue segments: {str(e)}")
            return {}

    async def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Get financial data from FMP API
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary containing financial data and analysis
        """
        try:
            print("\n获取财务数据...")
            # # Get company info
            # company_info = await self.get_company_info(symbol)
            # market_cap = company_info.get('mktCap', 'N/A')

            # Get financial statements
            # income_annual = await self._get_financial_statement(symbol, 'income-statement', period='annual')
            income_quarter = await self._get_financial_statement(symbol, 'income-statement', period='quarter')
            balance_sheets_quarter = await self._get_financial_statement(symbol, 'balance-sheet-statement', period='quarter')
            # cash_flows_annual = await self._get_financial_statement(symbol, 'cash-flow-statement', period='annual')
            cash_flows_quarter = await self._get_financial_statement(symbol, 'cash-flow-statement', period='quarter')

            # Get the latest 4 quarters of income statements, balance sheets, and cash flows
            income_quarter = income_quarter[:4]
            balance_sheets_quarter = balance_sheets_quarter[:4]
            cash_flows_quarter = cash_flows_quarter[:4]

            # Income statements: keep only the key fields
            fields_for_analysis = [
                "date",
                "reportedCurrency",
                "revenue",
                "costOfRevenue",
                "grossProfit",
                "grossProfitRatio",
                "researchAndDevelopmentExpenses",
                "sellingGeneralAndAdministrativeExpenses",
                "operatingExpenses",
                "costAndExpenses",
                "ebitda",
                "ebitdaratio",
                "operatingIncome",
                "operatingIncomeRatio",
                "incomeBeforeTax",
                "incomeBeforeTaxRatio",
                "incomeTaxExpense",
                "netIncome",
                "netIncomeRatio",
                "eps",
                "epsdiluted"
            ]
            # print(f"DEBUG: {income_quarter}")
            income_quarter = [
                {k: v for k, v in item.items() if k in fields_for_analysis} 
                for item in income_quarter
            ]

            # Balance sheets: keep only the key fields
            fields_for_analysis = [
                "date",
                "reportedCurrency",
                "cashAndCashEquivalents",
                "shortTermInvestments",
                "netReceivables",
                "inventory",
                "totalCurrentAssets",
                "propertyPlantEquipmentNet",
                "goodwill",
                "intangibleAssets",
                "goodwillAndIntangibleAssets",
                "longTermInvestments",
                "taxAssets",
                "totalNonCurrentAssets",
                "totalAssets",
                "accountPayables",
                "shortTermDebt",
                "taxPayables",
                "deferredRevenue",
                "totalCurrentLiabilities",
                "longTermDebt",
                "deferredTaxLiabilitiesNonCurrent",
                "totalNonCurrentLiabilities",
                "totalLiabilities",
                "commonStock",
                "retainedEarnings",
                "accumulatedOtherComprehensiveIncomeLoss",
                "totalStockholdersEquity",
                "totalEquity",
                "totalDebt",
                "netDebt"
            ]
            balance_sheets_quarter = [
                {k: v for k, v in item.items() if k in fields_for_analysis} 
                for item in balance_sheets_quarter
            ]

            # Cash flows: keep only the key fields
            fields_for_analysis = [
                "date",
                "reportedCurrency",
                "netIncome",
                "depreciationAndAmortization",
                "deferredIncomeTax",
                "stockBasedCompensation",
                "changeInWorkingCapital",
                "netCashProvidedByOperatingActivities",
                "investmentsInPropertyPlantAndEquipment",
                "netCashUsedForInvestingActivites",
                "debtRepayment",
                "dividendsPaid",
                "netCashUsedProvidedByFinancingActivities",
                "effectOfForexChangesOnCash",
                "netChangeInCash",
                "cashAtEndOfPeriod",
                "cashAtBeginningOfPeriod",
                "operatingCashFlow",
                "capitalExpenditure",
                "freeCashFlow"
            ]
            cash_flows_quarter = [
                {k: v for k, v in item.items() if k in fields_for_analysis} 
                for item in cash_flows_quarter
            ]

            # Get key metrics
            # key_metrics = await self._get_key_metrics(symbol)
            key_metrics_ttm = await self._get_key_metrics_ttm(symbol)
            
            # Get latest earnings call transcript
            print("- 获取最新财报会议记录")
            transcript_data = await self.get_latest_transcript(symbol)
            if transcript_data:
                print(f"  * 找到 {transcript_data['year']}年第{transcript_data['quarter']}季度的财报会议记录")
                print(f"  * 记录日期: {transcript_data['date']}")
            else:
                print("  * 未找到最近一年内的财报会议记录")
            
            # # Calculate TTM metrics
            # ttm_revenue = self._calculate_ttm(income_quarter, 'revenue')
            # ttm_net_income = self._calculate_ttm(income_quarter, 'netIncome')
            # ttm_operating_income = self._calculate_ttm(income_quarter, 'operatingIncome')
            # ttm_rd_expense = self._calculate_ttm(income_quarter, 'researchAndDevelopmentExpenses')
            # ttm_sga_expense = self._calculate_ttm(income_quarter, 'sellingGeneralAndAdministrativeExpenses')
            
            # # Calculate cash flow TTM metrics
            # ttm_operating_cash_flow = self._calculate_ttm(cash_flows_quarter, 'operatingCashFlow')
            # ttm_investing_cash_flow = self._calculate_ttm(cash_flows_quarter, 'netCashUsedForInvestingActivites')
            # ttm_financing_cash_flow = self._calculate_ttm(cash_flows_quarter, 'netCashUsedProvidedByFinancingActivities')
            # ttm_free_cash_flow = self._calculate_ttm(cash_flows_quarter, 'freeCashFlow')
            # ttm_capital_expenditure = self._calculate_ttm(cash_flows_quarter, 'capitalExpenditure')
            
            # # Get latest statements
            # latest_income = income_annual.iloc[0]
            # latest_balance = balance_sheets.iloc[0]
            # latest_cash = cash_flows_annual.iloc[0]
            # latest_metrics = key_metrics
            
            # Create financial summary with more metrics
            summary = {

                # latest 4 quarters financial data
                'income_quarter': income_quarter,
                'balance_sheets_quarter': balance_sheets_quarter,
                'cash_flows_quarter': cash_flows_quarter,
                'key_metrics_ttm': key_metrics_ttm,
                
                # # 估值指标 (Valuation Metrics)
                # 'market_cap': market_cap,
                # 'enterprise_value': latest_metrics['enterpriseValue'][0],
                # # 'pe_ratio': latest_metrics['peRatio'],
                # # 'pb_ratio': latest_metrics['pbRatio'],
                # # 'ps_ratio': latest_metrics['priceToSalesRatio'],
                # 'pfcf_ratio': latest_metrics['pfcfRatio'][0],
                # 'ev_to_ebitda': latest_metrics['enterpriseValueOverEBITDA'][0],
                # 'ev_to_sales': latest_metrics['evToSales'][0],
                # 'ev_to_fcf': latest_metrics['evToFreeCashFlow'][0],
                # 'earnings_yield': latest_metrics['earningsYield'][0],
                # 'fcf_yield': latest_metrics['freeCashFlowYield'][0],
                # # 'dividend_yield': latest_metrics.get('dividendYield', 0),
                # # 'payout_ratio': latest_metrics.get('payoutRatio', 0),
                
                # # 收益率指标 (Return Metrics)
                # 'roe': latest_metrics['roe'][0],
                # 'roic': latest_metrics['roic'][0],
                # 'rota': latest_metrics['returnOnTangibleAssets'][0],
                
                # # TTM 指标 (TTM Metrics)
                # # 'pe_ratio_ttm': key_metrics_ttm['peRatioTTM'],
                # # 'ps_ratio_ttm': key_metrics_ttm['priceToSalesRatioTTM'],
                # # 'pfcf_ratio_ttm': key_metrics_ttm['pfcfRatioTTM'],
                # 'ev_to_ebitda_ttm': key_metrics_ttm['enterpriseValueOverEBITDATTM'],
                # 'roe_ttm': key_metrics_ttm['roeTTM'],
                # 'dividend_yield_ttm': key_metrics_ttm['dividendYieldTTM'],
                
                # # 元数据 (Metadata)
                # 'period': latest_income['period'],
                # 'calendar_year': latest_income['calendarYear'],
                # 'currency': latest_income['reportedCurrency'],
                # 'filing_date': latest_income['fillingDate']
            }
            
            # Add transcript data if available
            if transcript_data:
                summary['earnings_call'] = transcript_data
            else:
                summary['earnings_call'] = 'Not provided' 
            
            # Save financial data using _save_data
            # self._save_data(income_annual, 'income_statements.csv')
            self._save_data(income_quarter, 'income_statements_quarterly.csv')
            # self._save_data(balance_sheets, 'balance_sheets.csv')
            self._save_data(balance_sheets_quarter, 'balance_sheets_quarterly.csv')
            # self._save_data(cash_flows_annual, 'cash_flows.csv')
            self._save_data(cash_flows_quarter, 'cash_flows_quarterly.csv')
            # self._save_data(key_metrics, 'key_metrics.csv')
            self._save_data(key_metrics_ttm, 'key_metrics_ttm.csv')
            # Save transcript if available using _save_data
            if transcript_data:
                self._save_data(transcript_data, 'latest_earnings_call.txt')
                print(f"财报会议记录已保存至：{self.output_dir}/latest_earnings_call.txt")
            else:
                print("财报会议记录未找到")
            
            # # Print enhanced summary
            # print("\n财务数据概览：")
            # print(f"报告期间: {summary['calendar_year']} {summary['period']}")
            # print(f"货币单位: {summary['currency']}")
            # print(f"报告日期: {summary['filing_date']}")
            
            # print(f"\n估值指标：")
            # # print(f"DEBUG: {summary['market_cap']}")
            # # print(f"- 市值: {summary['market_cap']:,.0f}")
            # print(f"- P/E (TTM): {summary['pe_ratio_ttm']:.2f}")
            # print(f"- P/B: {summary['pb_ratio']:.2f}")
            # print(f"- P/S (TTM): {summary['ps_ratio_ttm']:.2f}")
            # print(f"- EV/EBITDA (TTM): {summary['ev_to_ebitda_ttm']:.2f}")
            # print(f"- 股息收益率 (TTM): {summary['dividend_yield_ttm']*100:.2f}%")
            
            # print(f"DEBUG: {summary}")

            # print(f"\n收入和利润：")
            # print(f"- 营业收入: {summary['revenue']:,.0f} (TTM: {summary['revenue_ttm']:,.0f})")
            # print(f"- 每股收入: {summary['revenue_per_share']:.2f}")
            # print(f"- 净利润: {summary['net_income']:,.0f} (TTM: {summary['net_income_ttm']:,.0f})")
            # print(f"- 每股收益: {summary['eps']:.2f} (稀释后: {summary['eps_diluted']:.2f})")
            # print(f"- 毛利率: {summary['gross_profit_margin']*100:.1f}%")
            # print(f"- 营业利润率: {summary['operating_margin']*100:.1f}%")
            # print(f"- 净利率: {summary['net_profit_margin']*100:.1f}%")
            
            # print(f"\n运营效率：")
            # print(f"- 研发支出: {summary['rd_expense']:,.0f} (TTM: {summary['rd_expense_ttm']:,.0f})")
            # print(f"- 研发支出占比: {summary['rd_ratio']*100:.1f}%")
            # # print(f"- 应收账款周转天数: {summary['days_sales_outstanding']:.1f}")
            # # print(f"- 存货周转天数: {summary['days_inventory']:.1f}")
            # # print(f"- 应付账款周转天数: {summary['days_payables']:.1f}")
            
            # print(f"\n资产负债：")
            # print(f"- 总资产: {summary['total_assets']:,.0f}")
            # print(f"- 总负债: {summary['total_liabilities']:,.0f}")
            # print(f"- 所有者权益: {summary['total_equity']:,.0f}")
            # print(f"- 每股净资产: {summary['book_value_per_share']:.2f}")
            # print(f"- 资产负债率: {summary['debt_to_assets']*100:.1f}%")
            # print(f"- 流动比率: {summary['current_ratio']:.2f}")
            
            # print(f"\n现金流量：")
            # print(f"- 经营现金流: {summary['operating_cash_flow']:,.0f} (TTM: {summary['operating_cash_flow_ttm']:,.0f})")
            # print(f"- 每股经营现金流: {summary['ocf_per_share']:.2f}")
            # print(f"- 自由现金流: {summary['free_cash_flow']:,.0f} (TTM: {summary['free_cash_flow_ttm']:,.0f})")
            # print(f"- 每股自由现金流: {summary['fcf_per_share']:.2f}")
            # print(f"- 资本支出: {summary['capital_expenditure']:,.0f} (TTM: {summary['capital_expenditure_ttm']:,.0f})")
            
            # Get revenue segments
            print("- 获取收入细分数据")
            product_data, geo_data = await self._get_revenue_segments(symbol)
            segments_data = self._process_revenue_segments(product_data, geo_data)
            
            # Add segments to summary
            if segments_data:
                summary['revenue_segments'] = segments_data
                
                # Print segments summary
                segments_by_year = segments_data['segments_by_year']
                
                print("\n收入细分概览：")
                for segment in segments_by_year:
                    print(f"报告期间: {segment['date']}")
                    print(f"产品收入：")
                    total_product = sum(segment['products'].values())
                    for product, revenue in sorted(segment['products'].items(), key=lambda x: x[1], reverse=True):
                        percentage = (revenue / total_product) * 100
                        print(f"- {product}: {revenue:,.0f} ({percentage:.1f}%)")
                    print(f"地区收入：")
                    total_geo = sum(segment['regions'].values())
                    for region, revenue in sorted(segment['regions'].items(), key=lambda x: x[1], reverse=True):
                        percentage = (revenue / total_geo) * 100
                        print(f"- {region}: {revenue:,.0f} ({percentage:.1f}%)")
            else:
                summary['revenue_segments'] = 'Not provided'
            
            # return {
            #     'income_statements': income_annual,
            #     'income_statements_quarterly': income_quarter,
            #     'balance_sheets': balance_sheets,
            #     'cash_flows': cash_flows_annual,
            #     'key_metrics': key_metrics,
            #     'key_metrics_ttm': key_metrics_ttm,
            #     'summary': summary
            # }
            return summary
            
        except Exception as e:
            raise Exception(f"Error fetching financial data: {str(e)}")
    
    async def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Get options data (not supported by FMP)"""
        return {
            'calls': pd.DataFrame(),
            'puts': pd.DataFrame(),
            'expiration_dates': [],
            'stock_price': None
        }
    
    async def get_technical_indicator(self, symbol: str, indicator_type: str, period: int = 10, 
                              timeframe: str = '1day', start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Get technical indicator data from FMP API
        
        Args:
            symbol: Stock symbol
            indicator_type: One of 'sma', 'ema', 'wma', 'dema', 'tema', 'williams', 'rsi', 'adx', 'standardDeviation'
            period: Number of periods for calculation (default: 14)
            timeframe: Time interval ('1min', '5min', '15min', '30min', '1hour', '4hour', '1day')
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
        
        Returns:
            DataFrame with indicator values
        """
        try:
            # Validate timeframe
            valid_timeframes = ['1min', '5min', '15min', '30min', '1hour', '4hour', '1day']
            if timeframe not in valid_timeframes:
                timeframe = '1day'  # Default to daily if invalid
            
            # Validate indicator type
            valid_indicators = ['sma', 'ema', 'wma', 'dema', 'tema', 'williams', 'rsi', 'adx', 'standardDeviation']
            if indicator_type.lower() not in valid_indicators:
                raise ValueError(f"Invalid indicator type. Must be one of: {', '.join(valid_indicators)}")
            
            symbol = self._format_symbol(symbol)
            url = f"{self.v3_url}/technical_indicator/{timeframe}/{symbol}"
            
            params = {
                'apikey': self.api_key,
                'type': indicator_type.lower(),
                'period': period
            }
            
            # Only add date parameters if they are valid and not in the future
            today = datetime.now().date()
            if start_date:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                if start_date_obj <= today:
                    params['from'] = start_date
            if end_date:
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                if end_date_obj <= today:
                    params['to'] = end_date
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                raise ValueError(f"No data returned for {indicator_type} indicator")
            
            df = pd.DataFrame(data)
            
            # Convert date column to datetime
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            
            # Sort by date in ascending order
            df = df.sort_index()
            
            return df
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error fetching technical indicator data: {str(e)}")
        except Exception as e:
            raise Exception(f"Error processing technical indicator data: {str(e)}")

    async def get_all_technical_indicators(self, symbol: str, period: int = 10, timeframe: str = '1day') -> Dict[str, pd.DataFrame]:
        """Get all relevant technical indicators for analysis
        
        Args:
            symbol: Stock symbol
            period: Number of periods for calculations
            timeframe: Time interval ('1min', '5min', '15min', '30min', '1hour', '4hour', '1day')
            
        Returns:
            Dictionary of DataFrames with all technical indicators
        """
        try:
            print("\n获取技术指标...")
            
            indicators = {
                'sma': None,   # 简单移动平均线
                'ema': None,   # 指数移动平均线
                'rsi': None,   # 相对强弱指标
                'williams': None,  # 威廉指标
                'adx': None    # 平均趋向指标
            }
            
            for indicator_type in indicators.keys():
                try:
                    indicators[indicator_type] = await self.get_technical_indicator(
                        symbol=symbol,
                        indicator_type=indicator_type,
                        period=period,
                        timeframe=timeframe
                    )
                    print(f"- 已获取 {indicator_type.upper()} 指标数据")
                except Exception as e:
                    print(f"Warning: Failed to get {indicator_type.upper()} indicator: {str(e)}")
            
            # Save indicators to CSV
            for name, df in indicators.items():
                if df is not None and not df.empty:
                    self._save_data(df, f'{name}_indicator.csv')
            
            print(f"技术指标数据已保存至：{self.output_dir}")
            
            return indicators
            
        except Exception as e:
            print(f"Warning: Failed to get FMP indicators: {str(e)}")
            print("Falling back to local calculations...")
            return {}

    async def _get_transcript_dates(self, symbol: str) -> list:
        """Get list of available transcript dates
        
        Args:
            symbol: Stock symbol
            
        Returns:
            List of transcript dates
        """
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.v4_url}/earning_call_transcript"
            
            params = {
                'symbol': symbol,
                'apikey': self.api_key
            }
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                return []
            
            # Convert to list of [quarter, year, date] lists
            return data
            
        except Exception as e:
            print(f"Warning: Failed to get transcript dates: {str(e)}")
            return []
    
    async def _get_transcript(self, symbol: str, year: int, quarter: int) -> dict:
        """Get earnings call transcript
        
        Args:
            symbol: Stock symbol
            year: Year of transcript
            quarter: Quarter of transcript
            
        Returns:
            Dictionary containing transcript data
        """
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.v3_url}/earning_call_transcript/{symbol}"
            
            params = {
                'year': year,
                'quarter': quarter,
                'apikey': self.api_key
            }
            
            data = await self._make_request(endpoint=url, params=params)
            
            if not data:
                return {}
            
            return data[0]  # Return first (and only) item
            
        except Exception as e:
            print(f"Warning: Failed to get transcript: {str(e)}")
            return {}
    
    async def get_latest_transcript(self, symbol: str) -> Dict[str, Any]:
        """Get latest earnings call transcript within the past year
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary containing:
            - date: Date of transcript
            - content: Transcript content
            - quarter: Quarter number
            - year: Year
        """
        try:
            # Get current time in US Eastern timezone
            eastern = pytz.timezone('US/Eastern')
            current_time = datetime.now(eastern)
            one_year_ago = current_time - timedelta(days=365)
            
            # Get list of available transcripts
            transcript_dates = await self._get_transcript_dates(symbol)
            
            if not transcript_dates:
                return {}
            
            # Find most recent transcript within the past year
            latest_transcript = None
            for quarter, year, date_str in transcript_dates:
                transcript_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                transcript_date = eastern.localize(transcript_date)
                
                if transcript_date > one_year_ago:
                    latest_transcript = {
                        'quarter': quarter,
                        'year': year,
                        'date': date_str
                    }
                    break
            
            if not latest_transcript:
                return {}
            
            # Get full transcript
            transcript_data = await self._get_transcript(
                symbol,
                latest_transcript['year'],
                latest_transcript['quarter']
            )
            
            if not transcript_data:
                return {}
            
            return {
                'date': transcript_data['date'],
                'content': transcript_data['content'],
                'quarter': transcript_data['quarter'],
                'year': transcript_data['year']
            }
            
        except Exception as e:
            print(f"Warning: Failed to get latest transcript: {str(e)}")
            return {}

    async def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """Get latest stock news from FMP API
        
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
        try:
            symbol = self._format_symbol(symbol)
            
            # Build query parameters
            params = {
                'tickers': symbol,
                'limit': min(limit, 100)  # API limit is 100
            }
            
            if from_date:
                params['from'] = from_date
            if to_date:
                params['to'] = to_date
            
            # Make API request
            response = await self._make_request(
                endpoint=f"{self.v3_url}/stock_news",
                params=params
            )
            
            if not response:
                print(f"Warning: No news data available for {symbol}")
                return []
            
            # Process and clean news data
            news_data = []
            for article in response:
                if article.get('symbol') == symbol:  # Only include exact symbol matches
                    news_data.append({
                        'symbol': article.get('symbol'),
                        'publishedDate': article.get('publishedDate'),
                        'title': article.get('title'),
                        'summary': article.get('text'),
                        'url': article.get('url'),
                        'source': article.get('source')
                    })
            
            # Remove duplicate news defined by title
            unique_titles = []
            news_data_rm_dup = []
            for article in news_data:
                if article['title'] not in unique_titles:
                    unique_titles.append(article['title'])
                    news_data_rm_dup.append(article)
            return news_data_rm_dup
            
        except Exception as e:
            print(f"Error fetching news data: {str(e)}")
            return []

    async def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get company press releases from FMP API
        
        Args:
            symbol: Stock symbol
            limit: Number of press releases to return (default: 100)
            
        Returns:
            List of press releases with fields:
            - symbol: Stock symbol
            - date: Publication date
            - title: Press release title
            - text: Press release content
        """
        try:
            symbol = self._format_symbol(symbol)
            
            # Make API request
            response = await self._make_request(
                endpoint=f"{self.v3_url}/press-releases/{symbol}",
                params={'page': 0}  # Get first page
            )
            
            if not response:
                print(f"Warning: No press releases available for {symbol}")
                return []
            
            # Process and clean press release data
            releases = []
            for release in response[:limit]:  # Limit the number of releases
                releases.append({
                    'symbol': release.get('symbol'),
                    'publishedDate': release.get('date'),
                    'title': release.get('title'),
                    'summary': release.get('text'),
                    'source': 'Press Release'  # Add type to distinguish from news
                })

            # Remove duplicate press releases defined by title
            unique_titles = []
            releases_rm_dup = []
            for release in releases:
                if release['title'] not in unique_titles:
                    unique_titles.append(release['title'])
                    releases_rm_dup.append(release)
            return releases_rm_dup
            
        except Exception as e:
            print(f"Error fetching press releases: {str(e)}")
            return [] 
        
if __name__ == '__main__':
    fmp = FMPDataSource()
    symbol = 'ARVN'
    news_data = asyncio.run(fmp.get_stock_news(symbol))
    print(news_data)