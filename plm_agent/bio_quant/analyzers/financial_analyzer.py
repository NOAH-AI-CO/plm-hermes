import pandas as pd
import json
from typing import Dict, Any
from ..core.interfaces import Analyzer, LLMModel
from ..prompts.analysis_prompts import FinancialAnalysisPrompt
from ..prompts.analysis_prompts_en import FinancialAnalysisPromptEn
import os

class FinancialAnalyzer(Analyzer):
    def __init__(self, model: LLMModel, language: str = "zh-CN"):
        """Initialize financial analyzer with LLM model"""
        self.model = model
        self.language = language
        self.prompt_template = FinancialAnalysisPrompt() if language == "zh-CN" else FinancialAnalysisPromptEn()
        self.output_dir = None

    def set_output_dir(self, output_dir: str):
        """Set output directory for analysis results"""
        self.output_dir = output_dir

    def _format_number(self, value: float) -> str:
        """Format number for display"""
        try:
            if isinstance(value, (pd.Series, pd.DataFrame)):
                return "N/A"  # Handle pandas Series/DataFrame
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

    def _calculate_growth_rate(self, current: float, previous: float) -> float:
        """Calculate year-over-year growth rate"""
        if previous and previous != 0:
            return ((current - previous) / abs(previous)) * 100
        return 0.0

    def _process_financial_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process and format financial data from FMP API
        
        Args:
            data: Dictionary containing:
                - income_statements: DataFrame of income statements
                - balance_sheets: DataFrame of balance sheets
                - cash_flows: DataFrame of cash flow statements
                - key_metrics: DataFrame of key metrics
                - key_metrics_ttm: Dictionary of TTM key metrics
                - summary: Dictionary of key financial metrics
        """
        try:
            processed = {}
            
            # Get the latest data
            summary = data['summary']
            
            # Profitability metrics
            processed['盈利能力'] = {
                '营业收入': self._format_number(summary['revenue']),
                '营业收入(TTM)': self._format_number(summary['revenue_ttm']),
                '每股收入': f"{summary['revenue_per_share']:.2f}",
                '净利润': self._format_number(summary['net_income']),
                '净利润(TTM)': self._format_number(summary['net_income_ttm']),
                '每股收益': f"{summary['eps']:.2f}",
                '每股收益(稀释后)': f"{summary['eps_diluted']:.2f}",
                '毛利率': f"{summary['gross_profit_margin']*100:.1f}%",
                '营业利润率': f"{summary['operating_margin']*100:.1f}%",
                '净利率': f"{summary['net_profit_margin']*100:.1f}%"
            }
            
            # Operating efficiency metrics
            processed['运营效率'] = {
                '研发支出': self._format_number(summary['rd_expense']),
                '研发支出(TTM)': self._format_number(summary['rd_expense_ttm']),
                '研发支出占比': f"{summary['rd_ratio']*100:.1f}%",
                # '应收账款周转天数': f"{summary['days_sales_outstanding']:.1f}天",
                # '存货周转天数': f"{summary['days_inventory']:.1f}天",
                # '应付账款周转天数': f"{summary['days_payables']:.1f}天",
                # '应收账款周转率': f"{summary['receivables_turnover']:.2f}",
                # '存货周转率': f"{summary['inventory_turnover']:.2f}",
                # '应付账款周转率': f"{summary['payables_turnover']:.2f}"
            }
            
            # Balance sheet metrics
            processed['资产负债'] = {
                '总资产': self._format_number(summary['total_assets']),
                '总负债': self._format_number(summary['total_liabilities']),
                '所有者权益': self._format_number(summary['total_equity']),
                '每股净资产': f"{summary['book_value_per_share']:.2f}",
                '有形资产价值': self._format_number(summary['tangible_book_value']),
                '营运资金': self._format_number(summary['working_capital']),
                '资产负债率': f"{summary['debt_to_assets']*100:.1f}%",
                '流动比率': f"{summary['current_ratio']:.2f}",
                '资产负债比': f"{summary['debt_to_equity']:.2f}"
            }
            
            # Cash flow metrics
            processed['现金状况'] = {
                '经营现金流': self._format_number(summary['operating_cash_flow']),
                '每股经营现金流': f"{summary['ocf_per_share']:.2f}",
                '自由现金流': self._format_number(summary['free_cash_flow']),
                '每股自由现金流': f"{summary['fcf_per_share']:.2f}",
                '资本支出': self._format_number(summary['capital_expenditure'])
            }
            
            # Valuation metrics
            processed['估值指标'] = {
                '市值': self._format_number(summary['market_cap']),
                '企业价值': self._format_number(summary['enterprise_value']),
                'P/E (TTM)': f"{summary['market_cap']/summary['net_income_ttm']:.2f}",
                'P/B': f"{summary['market_cap']/summary['total_equity']:.2f}",
                'P/S (TTM)': f"{summary['market_cap']/summary['revenue_ttm']:.2f}",
                'P/FCF': f"{summary['pfcf_ratio']:.2f}",  # 使用已计算好的 pfcf_ratio
                'EV/EBITDA (TTM)': f"{summary['ev_to_ebitda_ttm']:.2f}",  # 使用 TTM 版本
                'EV/Sales': f"{summary['ev_to_sales']:.2f}",
                'EV/FCF': f"{summary['ev_to_fcf']:.2f}",
                '股息收益率': f"{summary['dividend_yield_ttm']*100:.2f}%",
                # '派息比率': f"{summary['payout_ratio']*100:.1f}%"
            }
            
            # Return metrics
            processed['收益率指标'] = {
                'ROE (TTM)': f"{summary['roe_ttm']*100:.1f}%",
                'ROIC': f"{summary['roic']*100:.1f}%",
                '有形资产回报率': f"{summary['rota']*100:.1f}%",
                '收益率': f"{summary['earnings_yield']*100:.1f}%",
                '自由现金流收益率': f"{summary['fcf_yield']*100:.1f}%"
            }
            
            # Add revenue segments if available
            if 'revenue_segments' in summary:
                segments_data = summary['revenue_segments']
                if segments_data and 'segments_by_year' in segments_data:
                    processed['收入结构'] = {}
                    
                    for i, year_data in enumerate(segments_data['segments_by_year']):
                        year = year_data['date']
                        year_key = f"{year}年度"
                        
                        # Process product segments
                        products = year_data['products']
                        total_product = sum(products.values())
                        product_segments = {}
                        for product, revenue in sorted(products.items(), key=lambda x: x[1], reverse=True):
                            percentage = (revenue / total_product) * 100
                            product_segments[product] = f"{self._format_number(revenue)} ({percentage:.1f}%)"
                        
                        # Process geographic segments
                        regions = year_data['regions']
                        total_geo = sum(regions.values())
                        geo_segments = {}
                        for region, revenue in sorted(regions.items(), key=lambda x: x[1], reverse=True):
                            percentage = (revenue / total_geo) * 100
                            geo_segments[region] = f"{self._format_number(revenue)} ({percentage:.1f}%)"
                        
                        processed['收入结构'][year_key] = {
                            '产品收入': product_segments,
                            '地区收入': geo_segments
                        }
            
            # Add earnings call transcript if available
            if 'earnings_call' in summary:
                earnings_call = summary['earnings_call']
                processed['earnings_call'] = {
                    'date': earnings_call['date'],
                    'quarter': earnings_call['quarter'],
                    'year': earnings_call['year'],
                    'content': earnings_call['content']
                }
            
            # Add cash analysis
            cash_analysis = self._analyze_cash_position(summary)
            if cash_analysis:
                processed['现金分析'] = cash_analysis
            
            return processed
            
        except Exception as e:
            print(f"Error processing financial data: {str(e)}")
            return {}

    def _analyze_cash_position(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze cash position and burn rate using FMP data"""
        try:
            cash_analysis = {}
            
            # Get key metrics
            total_cash = summary['cash_and_equivalents'] + summary['short_term_investments']
            operating_cash_flow = summary['operating_cash_flow']
            free_cash_flow = summary['free_cash_flow']
            
            # Calculate monthly metrics
            monthly_ocf = operating_cash_flow / 12
            monthly_fcf = free_cash_flow / 12
            
            if monthly_fcf < 0:
                months_of_runway = abs(total_cash / monthly_fcf) if monthly_fcf != 0 else float('inf')
                cash_analysis.update({
                    '现金流状态': '负向',
                    '月度现金消耗': self._format_number(abs(monthly_fcf)),
                    '预计可维持月数': f"{months_of_runway:.1f} 个月" if months_of_runway != float('inf') else "现金充足",
                    '计算依据': '自由现金流'
                })
            else:
                cash_analysis.update({
                    '现金流状态': '正向',
                    '月度现金生成': self._format_number(monthly_fcf),
                    '计算依据': '自由现金流'
                })
            
            cash_analysis.update({
                '总现金储备': self._format_number(total_cash),
                '经营现金流(月)': self._format_number(monthly_ocf),
                '自由现金流(月)': self._format_number(monthly_fcf)
            })
            
            return cash_analysis
            
        except Exception as e:
            print(f"Cash analysis failed: {str(e)}")
            return {}

    async def analyze(self, data: Dict[str, Any], only_return_data: bool = False) -> str:
        """Analyze financial data and return insights"""
        try:
            symbol = data['symbol']
            financial_data = data['financial_data']
            latest_price = data['latest_price']
            market_cap = data['market_cap']
            revenuePerShareTTM = financial_data['key_metrics_ttm']['revenuePerShareTTM']
            netIncomePerShareTTM = financial_data['key_metrics_ttm']['netIncomePerShareTTM']
            bookValuePerShareTTM = financial_data['key_metrics_ttm']['bookValuePerShareTTM']
            peRatioTTM = latest_price / netIncomePerShareTTM
            pbRatioTTM = latest_price / bookValuePerShareTTM
            psRatioTTM = latest_price / revenuePerShareTTM
            
            
            print("\n处理财务数据...")
            print("- 格式化财务指标")
            # Process financial data
            # 提取重要的字段
            important_fields_income = [
                "date", 
                "reportedCurrency",
                "netIncome", 
                "revenue", 
                "costOfRevenue", 
                "researchAndDevelopmentExpenses", 
                "sellingGeneralAndAdministrativeExpenses"
            ]

            important_fields_balance = [
                "date",
                "reportedCurrency",
                "totalAssets", 
                "totalLiabilities", 
                "totalEquity", 
                "netDebt", 
                "cashAndCashEquivalents", 
                "shortTermInvestments"
            ]

            important_fields_cashflow = [
                "date",
                "reportedCurrency",
                "netCashProvidedByOperatingActivities", 
                "netCashUsedForInvestingActivites", 
                "netCashUsedProvidedByFinancingActivities",
                "freeCashFlow",
                "netChangeInCash",
                "operatingCashFlow",
            ]

            # Extract fields that are available
            income_df = pd.DataFrame(financial_data["income_quarter"])[important_fields_income]
            balance_df = pd.DataFrame(financial_data["balance_sheets_quarter"])[important_fields_balance]
            cashflow_df = pd.DataFrame(financial_data["cash_flows_quarter"])[important_fields_cashflow]
            
            income_md = income_df.to_markdown()
            balance_md = balance_df.to_markdown()
            cashflow_md = cashflow_df.to_markdown()

            # processed_data = self._process_financial_data(financial_data)
            processed_data = {
                'income_statements_quarterly': income_md,
                'balance_sheets_latest': balance_md,
                'cash_flows_quarterly': cashflow_md,
                'revenue_segments': financial_data['revenue_segments'],
                'earnings_call': financial_data['earnings_call'],
                'peRatioTTM': peRatioTTM,
                'pbRatioTTM': pbRatioTTM,
                'psRatioTTM': psRatioTTM,
                'market_cap': market_cap
            }
            
            # Convert to JSON string
            financial_json = json.dumps(processed_data, ensure_ascii=False, indent=2)

            if only_return_data:
                return financial_json
            
            print("- 生成分析提示")
            # Generate prompt
            prompt = self.prompt_template.format(
                symbol=symbol,
                financial_data=financial_json,
                latest_price=latest_price
            )
            
            # Save prompt to file
            prompt_dir = os.path.join(self.output_dir, "prompts")
            os.makedirs(prompt_dir, exist_ok=True)
            prompt_file = os.path.join(prompt_dir, 'financial_analysis_prompt.txt')
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"- 分析提示已保存至：{prompt_file}")
        
            print("- 调用 AI 模型进行分析")
            # Get analysis from LLM
            analysis = await self.model.generate(prompt)
            analysis = analysis.replace('```markdown', '').replace('```', '')

            print("- 财务分析完成")
            return {
                'analysis': analysis,
                'raw_data': financial_json
            }
            
        except Exception as e:
            raise Exception(str(e)) 