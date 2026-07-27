import yfinance as yf
import pandas as pd
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from ..prompts.analysis_prompts_en import IntegratedReportPromptEn
from ..core.interfaces import DataSource, LLMModel
from ..prompts.analysis_prompts import IntegratedReportPrompt

class YFinanceDataSource(DataSource):
    def __init__(self, language):
        """Initialize YFinance data source"""
        self.integrated_prompt = IntegratedReportPrompt() if language == 'zh-CN' else IntegratedReportPromptEn()
        self.output_dir = None

    def set_output_dir(self, output_dir: str):
        """Set output directory for data files"""
        self.output_dir = output_dir

    def _format_symbol(self, symbol: str) -> str:
        """Format symbol for YFinance"""
        symbol = symbol.strip().upper()
        
        # Handle special cases
        if symbol in ['XAUUSD', 'GOLD']:
            return 'GC=F'
        if symbol in ['TENCENT', '腾讯', '0700', '700']:
            return '0700.HK'
        
        # Handle different markets
        if '.' not in symbol:
            if symbol.isdigit():
                if len(symbol) == 6:
                    if symbol.startswith(('0', '3')):
                        symbol += '.SZ'
                    elif symbol.startswith('6'):
                        symbol += '.SS'
                elif len(symbol) == 4:
                    symbol = symbol.zfill(4) + '.HK'
        
        return symbol

    def _format_number(self, value: Any) -> str:
        """Format number for display"""
        try:
            if pd.isna(value) or value is None:
                return "N/A"
            if isinstance(value, str):
                return value
            if value == 0:
                return "0"
            if abs(value) >= 1e9:
                return f"{value/1e9:.2f}B"
            if abs(value) >= 1e6:
                return f"{value/1e6:.2f}M"
            if abs(value) >= 1e3:
                return f"{value/1e3:.2f}K"
            return f"{value:.2f}"
        except Exception:
            return str(value)

    def _convert_to_number(self, value: Any) -> float:
        """Convert string value to number"""
        try:
            if pd.isna(value) or value is None:
                return 0.0
            if isinstance(value, str):
                # Remove any commas and spaces
                value = value.replace(',', '').strip()
                # Handle suffixes
                if value.endswith('B'):
                    return float(value[:-1]) * 1e9
                elif value.endswith('M'):
                    return float(value[:-1]) * 1e6
                elif value.endswith('K'):
                    return float(value[:-1]) * 1e3
                else:
                    return float(value)
            return float(value)
        except Exception:
            return 0.0

    def _save_data(self, data: pd.DataFrame, filename: str) -> None:
        """Save data to CSV file"""
        try:
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            filepath = os.path.join(data_dir, filename)
            data.to_csv(filepath)
            print(f"数据已保存至：{filepath}")
        except Exception as e:
            print(f"保存数据失败 {filename}: {str(e)}")

    def get_stock_data(self, symbol: str, period: str = '1y') -> pd.DataFrame:
        """Get stock price data from YFinance"""
        try:
            symbol = self._format_symbol(symbol)
            stock = yf.Ticker(symbol)
            
            # Always get 1 year of data for better analysis
            df = stock.history(period='1y')
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

    def get_financial_data(self, symbol: str) -> Dict[str, Any]:
        """Get financial data from YFinance"""
        try:
            symbol = self._format_symbol(symbol)
            stock = yf.Ticker(symbol)
            info = stock.info
            
            # Get market data
            market_price = info.get('regularMarketPrice', info.get('currentPrice'))
            market_cap = info.get('marketCap')
            shares_outstanding = info.get('sharesOutstanding')
            
            # Get currency information
            financial_currency = info.get('financialCurrency', 'USD')
            market_currency = 'USD'  # Default market data currency
            
            # Determine market currency based on symbol
            if symbol.endswith(('.SS', '.SZ')):  # A-shares
                market_currency = 'CNY'
            elif symbol.endswith('.HK'):  # Hong Kong stocks
                market_currency = 'HKD'
            
            # Check if currency conversion is needed
            need_conversion = False
            if market_currency == 'USD' and financial_currency != 'USD':
                need_conversion = True
                print(f"\n注意：美股市场数据为USD，财务数据为{financial_currency}，需要转换")
            
            # Get exchange rate if needed
            exchange_rate = 1.0
            if need_conversion:
                try:
                    currency_pair = f"{financial_currency}USD=X"
                    currency_ticker = yf.Ticker(currency_pair)
                    exchange_rate = currency_ticker.info.get('regularMarketPrice', None)
                    if exchange_rate:
                        print(f"当前汇率：1 {financial_currency} = {exchange_rate:.4f} USD")
                    else:
                        # Use approximate rates if exchange rate not available
                        approximate_rates = {
                            'CNY': 0.14,   # RMB
                            'HKD': 0.13,   # HKD
                            'EUR': 1.10,   # Euro
                            'GBP': 1.27,   # GBP
                            'JPY': 0.0067  # Yen
                        }
                        exchange_rate = approximate_rates.get(financial_currency, 1.0)
                        print(f"警告：无法获取实时汇率，使用近似值：1 {financial_currency} = {exchange_rate:.4f} USD")
                except Exception as e:
                    print(f"获取汇率失败：{str(e)}")
            
            # Get financial statements
            income_stmt = stock.income_stmt
            balance_sheet = stock.balance_sheet
            cash_flow = stock.cashflow
            
            # Get quarterly statements
            quarterly_income = stock.quarterly_income_stmt
            quarterly_balance = stock.quarterly_balance_sheet
            quarterly_cashflow = stock.quarterly_cashflow
            
            # Save raw financial statements
            if not income_stmt.empty:
                self._save_data(income_stmt, 'income_statement_annual.csv')
            if not balance_sheet.empty:
                self._save_data(balance_sheet, 'balance_sheet_annual.csv')
            if not cash_flow.empty:
                self._save_data(cash_flow, 'cash_flow_annual.csv')
            if not quarterly_income.empty:
                self._save_data(quarterly_income, 'income_statement_quarterly.csv')
            if not quarterly_balance.empty:
                self._save_data(quarterly_balance, 'balance_sheet_quarterly.csv')
            if not quarterly_cashflow.empty:
                self._save_data(quarterly_cashflow, 'cash_flow_quarterly.csv')
            
            # Process TTM data
            ttm_data = {}
            if not quarterly_income.empty and len(quarterly_income.columns) >= 4:
                # Calculate TTM using last 4 quarters
                recent_quarters = quarterly_income.iloc[:, :4]
                ttm_data = recent_quarters.sum(axis=1)
                if need_conversion:
                    ttm_data = ttm_data * exchange_rate
                print("\n使用最近四个季度数据计算TTM")
            elif not income_stmt.empty:
                # Use latest annual data if quarterly not available
                ttm_data = income_stmt.iloc[:, 0]
                if need_conversion:
                    ttm_data = ttm_data * exchange_rate
                print("\n使用最新年度数据作为TTM")
            
            # Get latest balance sheet data
            latest_balance = None
            if not quarterly_balance.empty:
                latest_balance = quarterly_balance.iloc[:, 0]
                print("\n使用最新季度资产负债表数据")
            elif not balance_sheet.empty:
                latest_balance = balance_sheet.iloc[:, 0]
                print("\n使用最新年度资产负债表数据")
            
            if latest_balance is not None and need_conversion:
                latest_balance = latest_balance * exchange_rate
            
            # Process cash flow data
            ttm_cash_flow = None
            if not quarterly_cashflow.empty and len(quarterly_cashflow.columns) >= 4:
                recent_quarters = quarterly_cashflow.iloc[:, :4]
                ttm_cash_flow = recent_quarters.sum(axis=1)
                print("\n使用最近四个季度数据计算现金流TTM")
            elif not cash_flow.empty:
                ttm_cash_flow = cash_flow.iloc[:, 0]
                print("\n使用最新年度现金流数据作为TTM")
            
            if ttm_cash_flow is not None and need_conversion:
                ttm_cash_flow = ttm_cash_flow * exchange_rate
            
            # Organize financial data
            financial_data = {
                '基本信息': {
                    '公司名称': str(info.get('longName', 'N/A')),
                    '行业': str(info.get('industry', 'N/A')),
                    '板块': str(info.get('sector', 'N/A')),
                    '公司简介': str(info.get('longBusinessSummary', 'N/A'))
                },
                '市场数据': {
                    '市值': self._format_number(market_cap),
                    '当前股价': self._format_number(market_price),
                    '总股本': self._format_number(shares_outstanding),
                    '52周最高': self._format_number(info.get('fiftyTwoWeekHigh', 0)),
                    '52周最低': self._format_number(info.get('fiftyTwoWeekLow', 0)),
                    '交易量': self._format_number(info.get('volume', 0)),
                    '平均交易量': self._format_number(info.get('averageVolume', 0))
                }
            }
            
            # Add financial metrics if available
            if ttm_data is not None:
                financial_data['运营情况'] = {
                    '总收入(TTM)': self._format_number(ttm_data.get('Total Revenue', 0)),
                    '研发支出(TTM)': self._format_number(ttm_data.get('Research And Development', 0)),
                    '营业利润(TTM)': self._format_number(ttm_data.get('Operating Income', 0)),
                    '净利润(TTM)': self._format_number(ttm_data.get('Net Income', 0)),
                    '毛利率': self._format_number(info.get('grossMargins', 0)),
                    '营业利润率': self._format_number(info.get('operatingMargins', 0))
                }
            
            if latest_balance is not None:
                financial_data['资产负债'] = {
                    '总资产': self._format_number(latest_balance.get('Total Assets', 0)),
                    '总负债': self._format_number(latest_balance.get('Total Liabilities Net Minority Interest', 0)),
                    '长期债务': self._format_number(latest_balance.get('Long Term Debt And Capital Lease Obligation', 0)),
                    '股东权益': self._format_number(latest_balance.get('Total Equity Gross Minority Interest', 0))
                }
            
            if ttm_cash_flow is not None:
                operating_cash_flow = ttm_cash_flow.get('Operating Cash Flow', 0)
                cash_and_equivalents = latest_balance.get('Cash And Cash Equivalents', 0) if latest_balance is not None else 0
                
                financial_data['现金状况'] = {
                    '现金及现金等价物': self._format_number(cash_and_equivalents),
                    '经营活动现金流(TTM)': self._format_number(operating_cash_flow),
                    '投资活动现金流(TTM)': self._format_number(ttm_cash_flow.get('Investing Cash Flow', 0)),
                    '筹资活动现金流(TTM)': self._format_number(ttm_cash_flow.get('Financing Cash Flow', 0)),
                    '自由现金流(TTM)': self._format_number(ttm_cash_flow.get('Free Cash Flow', 0))
                }
                
                # Only calculate months of runway if cash flow is negative
                if operating_cash_flow < 0:
                    monthly_burn_rate = abs(operating_cash_flow) / 12
                    months_of_runway = round(cash_and_equivalents / monthly_burn_rate, 1) if monthly_burn_rate > 0 else float('inf')
                    financial_data['现金状况']['月度现金消耗'] = self._format_number(monthly_burn_rate)
                    financial_data['现金状况']['预计可维持月数'] = f"{months_of_runway} 个月" if months_of_runway != float('inf') else "现金充足"
                else:
                    financial_data['现金状况']['现金流状态'] = "正向"
                    financial_data['现金状况']['月度现金生成'] = self._format_number(operating_cash_flow / 12)
            
            # Print key data for debugging
            print("\n关键财务数据（将传递给LLM）：")
            print(f"总市值：{financial_data['市场数据']['市值']}")
            if '运营情况' in financial_data:
                print(f"营收(TTM)：{financial_data['运营情况']['总收入(TTM)']}")
                print(f"研发支出(TTM)：{financial_data['运营情况']['研发支出(TTM)']}")
                print(f"净利润(TTM)：{financial_data['运营情况']['净利润(TTM)']}")
            if '现金状况' in financial_data:
                print(f"现金及等价物：{financial_data['现金状况']['现金及现金等价物']}")
                print(f"经营现金流(TTM)：{financial_data['现金状况']['经营活动现金流(TTM)']}")
                if '月度现金消耗' in financial_data['现金状况']:
                    print(f"月度现金消耗：{financial_data['现金状况']['月度现金消耗']}")
                    print(f"预计可维持：{financial_data['现金状况']['预计可维持月数']}")
                elif '月度现金生成' in financial_data['现金状况']:
                    print(f"月度现金生成：{financial_data['现金状况']['月度现金生成']}")
            
            return financial_data
            
        except Exception as e:
            raise Exception(f"Error fetching financial data: {str(e)}")

    def get_options_data(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Get options data from YFinance"""
        try:
            symbol = self._format_symbol(symbol)
            stock = yf.Ticker(symbol)
            
            # Get options expiration dates
            exp_dates = stock.options
            
            if not exp_dates:
                return {'calls': pd.DataFrame(), 'puts': pd.DataFrame()}
            
            # Get options chain for the first expiration date
            options = stock.option_chain(exp_dates[0])
            
            # Save options data
            if not options.calls.empty:
                self._save_data(options.calls, 'options_calls.csv')
            if not options.puts.empty:
                self._save_data(options.puts, 'options_puts.csv')
            
            return {
                'calls': options.calls,
                'puts': options.puts,
                'expiration_dates': exp_dates,
                'stock_price': stock.info.get('regularMarketPrice', stock.info.get('currentPrice', 0))
            }
        except Exception as e:
            raise Exception(f"Error fetching options data: {str(e)}")

    def get_press_releases(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get press releases (not supported by YFinance)"""
        return []

    async def generate_integrated_report(self, symbol: str, financial_analysis: str, technical_analysis: str, 
                                 options_analysis: str, model: LLMModel) -> str:
        """Generate integrated analysis report using LLM to synthesize all analysis results
        
        Args:
            symbol: Stock symbol
            financial_analysis: Financial analysis result
            technical_analysis: Technical analysis result
            options_analysis: Options analysis result
            model: LLM model instance for generating the final report
            
        Returns:
            Integrated report in markdown format
        """
        try:
            # Format symbol for display
            display_symbol = symbol
            if symbol.endswith('.SS'):
                display_symbol = f"{symbol[:-3]} (上证)"
            elif symbol.endswith('.SZ'):
                display_symbol = f"{symbol[:-3]} (深证)"
            elif symbol.endswith('.HK'):
                display_symbol = f"{symbol[:-3]} (港股)"
            
            print("\n正在生成综合分析报告...")
            
            # Generate report using LLM with the prompt template
            prompt = self.integrated_prompt.format(
                symbol=display_symbol,
                technical_analysis=technical_analysis,
                financial_analysis=financial_analysis,
                options_analysis=options_analysis
            )
            report = await model.generate(prompt)
            
            # Add report metadata
            now = datetime.now()
            header = f"""# {display_symbol} 投资分析报告

- 报告日期：{now.strftime("%Y-%m-%d")}
- 报告时间：{now.strftime("%H:%M:%S")}
- 分析对象：{display_symbol}

---

"""
            final_report = header + report
            
            # Save report
            output_dir = f"{symbol}_analysis"
            os.makedirs(output_dir, exist_ok=True)
            report_file = os.path.join(output_dir, 'investment_report.md')
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(final_report)
            print(f"\n综合投资报告已保存至：{report_file}")
            
            return final_report
            
        except Exception as e:
            print(f"生成综合报告时出错：{str(e)}")
            return "生成综合报告失败"

    def get_stock_news(self, symbol: str, limit: int = 100, from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
        """Get stock news (not supported by YFinance)"""
        print(f"Warning: News data not available for {symbol} through YFinance")
        return [] 