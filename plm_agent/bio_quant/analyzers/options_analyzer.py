import asyncio
from datetime import datetime
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple

from bio_quant.models.volcano_deepseek_model import VolcanoDeepSeekModel
from bio_quant.data_sources.composite_source import CompositeDataSource
from bio_quant.data_sources.fmp_source import FMPDataSource
from bio_quant.data_sources.polygon_source import PolygonOptionsSource
from bio_quant.data_sources.twitter_source import TwitterDataSource
from bio_quant.core.hallucination_checker import HallucinationChecker
from bio_quant.prompts.analysis_prompts_en import OptionsAnalysisPromptEn
from ..core.interfaces import Analyzer, LLMModel, DataSource
from ..prompts.analysis_prompts import OptionsAnalysisPrompt
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for NumPy data types"""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

class OptionsAnalyzer(Analyzer):
    def __init__(self, model: LLMModel, data_source: DataSource, language: str = 'zh-CN'):
        """Initialize options analyzer with LLM model and data source"""
        self.model = model
        self.data_source = data_source
        self.prompt_template = OptionsAnalysisPrompt() if language == 'zh-CN' else OptionsAnalysisPromptEn()
        self.output_dir = None
        self.language = language

    def set_output_dir(self, output_dir: str):
        """Set output directory for analysis results"""
        self.output_dir = output_dir

    def _prepare_options_data(self, options_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare options data for LLM analysis"""
        try:
            # Early validation
            if not self._validate_options_data(options_data):
                return {
                    'status': 'no_data',
                    'message': '无可用的期权数据'
                }

            calls_df = options_data['calls']
            puts_df = options_data['puts']
            stock_price = float(options_data['stock_price'])

            # Process data in chunks for better performance
            processed_data = {
                'summary': self._process_summary_data(calls_df, puts_df, stock_price),
                'options_analysis': self._process_options_analysis(calls_df, puts_df, stock_price),
                'greeks': self._process_greeks_data(calls_df, puts_df),
                'volume_oi': self._process_volume_oi_data(calls_df, puts_df),
                'market_sentiment': self._process_market_sentiment(calls_df, puts_df, stock_price)
            }

            return processed_data

        except Exception as e:
            print(f"Warning: Failed to prepare options data: {str(e)}")
            return {
                'status': 'error',
                'message': f'处理期权数据失败: {str(e)}'
            }

    def _validate_options_data(self, options_data: Dict[str, Any]) -> bool:
        """Validate input options data"""
        return (options_data and 
                'calls' in options_data and 
                'puts' in options_data and 
                'stock_price' in options_data and 
                not options_data['calls'].empty and 
                not options_data['puts'].empty and 
                options_data['stock_price'] is not None)
    
    def _filter_columns(self, calls_df, puts_df):
        """删除特定列和全空列"""
        # 显式删除exerciseStyle
        calls_df = calls_df.drop(columns=['exerciseStyle'], errors='ignore')
        puts_df = puts_df.drop(columns=['exerciseStyle'], errors='ignore')
        
        # 保留之前的全空列过滤逻辑
        common_cols = list(set(calls_df.columns) & set(puts_df.columns))
        cols_to_drop = [
            col for col in common_cols 
            if calls_df[col].isna().all() and puts_df[col].isna().all()
        ]
        
        return calls_df.drop(columns=cols_to_drop), puts_df.drop(columns=cols_to_drop)
    
    def _filter_options(self, df):
        # 创建空值检测条件（处理None和NaN）
        na_condition = df[['lastPrice', 'bid', 'ask']].fillna(np.nan).isna().all(axis=1)
        # 创建交易量条件
        volume_condition = (df['volume'] == 0) & (df['openInterest'] == 0)
        # 组合过滤条件并取反
        filtered_df = df[~(na_condition & volume_condition)]
        return filtered_df

    def _process_summary_data(self, calls_df: pd.DataFrame, puts_df: pd.DataFrame, 
                             stock_price: float) -> Dict[str, Any]:
        """Process summary data efficiently"""
        return {
            'total_calls': len(calls_df),
            'total_puts': len(puts_df),
            'stock_price': stock_price,
            'expiration_dates': sorted(list(set(calls_df['expiration'].unique()) | 
                                          set(puts_df['expiration'].unique()))),
            'near_money_options': {
                'calls': len(calls_df[abs(calls_df['strike'] - stock_price) < stock_price * 0.1]),
                'puts': len(puts_df[abs(puts_df['strike'] - stock_price) < stock_price * 0.1])
            }
        }

    async def analyze(self, data: Dict[str, Any], only_return_data: bool = False) -> str:
        """Analyze options data and return insights"""
        try:
            symbol = data['symbol']
            latest_price = data['latest_price']
            options_data = data['options_data']

            # 应用过滤
            # 先过滤行再过滤列
            options_data['calls'] = self._filter_options(options_data['calls'])
            options_data['puts'] = self._filter_options(options_data['puts'])

            options_data['calls'], options_data['puts'] = self._filter_columns(
                options_data['calls'], 
                options_data['puts']
                )
            
            del options_data['stock_price']  # 原始数据中为None且latest_price已有值
            del options_data['expiration_dates']
            
            # print("\n处理期权数据...")
            # processed_data = self._prepare_options_data(options_data)
            
            # if processed_data.get('status') in ['no_data', 'error']:
            #     return processed_data.get('message', '处理期权数据时出错')
            
            # processed_data['summary']['stock_price'] = float(latest_price)
            
            # Return processed data directly without JSON conversion if only_return_data is True
            # options_data_call = options_data['calls'].to_markdown()
            # options_data_put = options_data['puts'].to_markdown()
            # options_data = options_data_call + '\n\n' + options_data_put
            options_data['calls'] = options_data['calls'].drop('type', axis=1, errors='ignore')
            options_data['puts'] = options_data['puts'].drop('type', axis=1, errors='ignore')
            # Round all float columns to 4 decimal places
            float_cols = options_data['calls'].select_dtypes(include=['float64']).columns
            options_data['calls'][float_cols] = options_data['calls'][float_cols].round(4)
            options_data['puts'][float_cols] = options_data['puts'][float_cols].round(4)
            data_processed = ""
            for x in range(9,3,-1):
                x_months = datetime.now() + timedelta(days=30*x)
                options_data['calls'] = options_data['calls'][pd.to_datetime(options_data['calls']['expiration']) <= x_months]
                options_data['puts'] = options_data['puts'][pd.to_datetime(options_data['puts']['expiration']) <= x_months]
                data_processed = "calls:\n" + options_data['calls'].to_csv(header=True, index=False) + '\n\nputs:\n' + options_data['puts'].to_csv(header=True, index=False)
                if len(data_processed) < 32000:
                    break
            if only_return_data:
                return data_processed
            
            
            prompt = self.prompt_template.format(
                symbol=symbol,
                latest_price=latest_price,
                options_data=data_processed
            )
            
            self._save_prompt(prompt)
            
            print("- 调用 AI 模型进行分析")
            analysis = await self.model.generate(prompt)
            analysis = analysis.replace('```markdown', '').replace('```', '')
            
            return {
                'analysis': analysis,
                'raw_data': data_processed
            }
            
        except Exception as e:
            raise Exception(f"Options analysis failed: {str(e)}") 
        
    def _save_prompt(self, prompt: str):
        """Save prompt to file"""
        if self.output_dir:
            file_path = os.path.join(self.output_dir, 'options_prompt.txt')
            with open(file_path, 'w') as f:
                f.write(prompt)

if __name__ == "__main__":
    fmp_source = FMPDataSource()  # Primary source for stock data and technical indicators
    polygon_source = PolygonOptionsSource()  # Source for options data
    twitter_source = TwitterDataSource()  # Source for tweets data
    ds = CompositeDataSource(
        primary_source=fmp_source,
        options_source=polygon_source,
        twitter_source=twitter_source
    )
    checker = HallucinationChecker(language)
    oa = OptionsAnalyzer(VolcanoDeepSeekModel(test_mode=True), data_source=None)
    symbol = 'AMGN'
    output_dir = './outputs'
    oa.set_output_dir('./outputs')
    async def test():
        company_info = await ds.get_company_info(symbol)
        latest_price = company_info.get('price', 'N/A')
        data = await ds.get_options_data(symbol)
        # Drop index and reset it
        data['calls'] = oa._filter_options(data['calls'])
        data['puts'] = oa._filter_options(data['puts'])

        data['calls'], data['puts'] = oa._filter_columns(
            data['calls'], 
            data['puts']
            )
        del data['stock_price']  # 原始数据中为None且latest_price已有值
        del data['expiration_dates']
        options_data_call = data['calls'].to_markdown(index=False)
        options_data_put = data['puts'].to_markdown(index=False)
        options_data = "calls\n" + options_data_call + '\n\nputs\n' + options_data_put
        with open('options_data_markdown.txt', 'w') as f:
            f.write(options_data)
            print("- 调用 AI 模型进行分析")
            
        prompt = oa.prompt_template.format(
            symbol=symbol,
            latest_price=latest_price,
            options_data=options_data
        )
        analysis = await oa.model.generate(prompt)
        analysis = analysis.replace('```markdown', '').replace('```', '')
            # Check for hallucinations and save results
        save_analysis(analysis, f'markdown_analysis_result.md', symbol)
        
        await checker.check_and_save(
            model=oa.model,
            prompt=prompt,
            response=analysis,
            analysis_type='markdown_options',
            output_dir=output_dir
        )
        
        
    def save_analysis(analysis, filename, symbol):
        output_dir_reports = f"./reports"
        os.makedirs(output_dir_reports, exist_ok=True)
        filepath = os.path.join(output_dir_reports, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {symbol} 分析结果\n\n")
            f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(analysis)
            
    async def test2():
        company_info = await ds.get_company_info(symbol)
        latest_price = company_info.get('price', 'N/A')
        data = await ds.get_options_data(symbol)
        # Drop index and reset it
        data['calls'] = oa._filter_options(data['calls'])
        data['puts'] = oa._filter_options(data['puts'])

        data['calls'], data['puts'] = oa._filter_columns(
            data['calls'], 
            data['puts']
            )
        # only keep first unique date in expiration column
        # for df in [data['calls'], data['puts']]:
        #     exp_mask = df.duplicated(subset=['expiration'], keep='first')
        #     df.loc[exp_mask, 'expiration'] = ''
        del data['stock_price']  # 原始数据中为None且latest_price已有值
        del data['expiration_dates']
        data['calls'] = data['calls'].drop('type', axis=1, errors='ignore')
        data['puts'] = data['puts'].drop('type', axis=1, errors='ignore')
        # Round all float columns to 4 decimal places
        float_cols = data['calls'].select_dtypes(include=['float64']).columns
        data['calls'][float_cols] = data['calls'][float_cols].round(4)
        data['puts'][float_cols] = data['puts'][float_cols].round(4)
        
        for x in range(9,3,-1):
            x_months = datetime.now() + timedelta(days=30*x)
            data['calls'] = data['calls'][pd.to_datetime(data['calls']['expiration']) <= x_months]
            data['puts'] = data['puts'][pd.to_datetime(data['puts']['expiration']) <= x_months]
            buffer = "calls:\n" + data['calls'].to_csv(header=True, index=False) + '\n\nputs:\n' + data['puts'].to_csv(header=True, index=False)
            len_buffer = len(buffer)
            print("len_buffer", len_buffer)
            if len_buffer < 32000:
                break
            
        with open('options_data_csv.txt', 'w') as f:
            f.write(buffer)
            print("- 调用 AI 模型进行分析")
            
        # prompt = oa.prompt_template.format(
        #     symbol=symbol,
        #     latest_price=latest_price,
        #     options_data=buffer
        # )
        # analysis = await oa.model.generate(prompt)
        # analysis = analysis.replace('```markdown', '').replace('```', '')
        # save_analysis(analysis, f'csv_analysis_result.md', symbol)
        
        # await checker.check_and_save(
        #     model=oa.model,
        #     prompt=prompt,
        #     response=analysis,
        #     analysis_type='csv_options',
        #     output_dir=output_dir
        # )
    async def test3():
        company_info = await ds.get_company_info(symbol)
        latest_price = company_info.get('price', 'N/A')
        data = await ds.get_options_data(symbol)
        
        params = {
            'symbol': symbol,
            'options_data': data,
            'latest_price': latest_price
        }
        await oa.analyze(params, only_return_data=False)
    # asyncio.run(test())
    # asyncio.run(test2())
    asyncio.run(test3())