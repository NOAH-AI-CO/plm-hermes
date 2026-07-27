import asyncio
import traceback
from typing import Dict, Any, Optional
import os
from datetime import datetime

from utils.bio_quant.dummy_stream import dummy_stream
from .report_generator import ReportGenerator
from concurrent.futures import ThreadPoolExecutor, as_completed
from .hallucination_checker import HallucinationChecker

class StockAnalyzer:
    def __init__(
        self,
        symbol: str,
        llm_model: Any,
        data_source: Any,
        period: str = '6mo',
        target_year: Optional[int] = None,
        output_dir: str = None,
        one_step: bool = False,
        two_step: bool = False,
        language: str = 'zh-CN'
    ):
        from ..analyzers.catalyst_analyzer import CatalystAnalyzer
        from ..analyzers.technical_analyzer import TechnicalAnalyzer
        from ..analyzers.financial_analyzer import FinancialAnalyzer
        from ..analyzers.options_analyzer import OptionsAnalyzer
        """Initialize stock analyzer
        
        Args:
            symbol: Stock symbol
            llm_model: LLM model for analysis
            data_source: Data source for fetching stock data
            period: Analysis period
            target_year: Target year for options analysis
            output_dir: Directory for saving analysis outputs
        """
        self.symbol = symbol
        self.llm_model = llm_model
        self.data_source = data_source
        self.period = period
        self.target_year = target_year or datetime.now().year + 1
        self.one_step = one_step
        self.two_step = two_step
        self.language = language

        # Set output directory
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = output_dir or f"outputs/{symbol}_{current_time}"
        self.file_name = f"{symbol}_{current_time}.zip"
        if not data_source.output_dir:
            data_source.set_output_dir(self.output_dir)
        # Initialize analyzers
        self.technical_analyzer = TechnicalAnalyzer(llm_model, data_source, language)
        self.financial_analyzer = FinancialAnalyzer(llm_model, language)
        self.options_analyzer = OptionsAnalyzer(llm_model, data_source, language)
        self.catalyst_analyzer = CatalystAnalyzer(llm_model, data_source, language)
        
        # Pass output directory to analyzers
        self.technical_analyzer.set_output_dir(self.output_dir)
        self.financial_analyzer.set_output_dir(self.output_dir)
        self.options_analyzer.set_output_dir(self.output_dir)
        self.catalyst_analyzer.set_output_dir(self.output_dir)
        
        # Initialize report generator
        self.report_generator = ReportGenerator(llm_model, language)
        self.report_generator.set_output_dir(self.output_dir)

        # Initialize hallucination checker
        self.hallucination_checker = HallucinationChecker(language)

    async def _run_analysis_task(self, analysis_type: str, params: dict) -> tuple:
        """运行单个分析任务"""
        try:
            # Get the original response
            if analysis_type == 'catalyst':
                result = await self.catalyst_analyzer.analyze(params)
                response = result['analysis']
            elif analysis_type == 'technical':
                result = await self.technical_analyzer.analyze(params)
                response = result['analysis']
            elif analysis_type == 'financial':
                result = await self.financial_analyzer.analyze(params)
                response = result['analysis']
            elif analysis_type == 'options':
                result = await self.options_analyzer.analyze(params)
                response = result['analysis']
            else:
                raise ValueError(f"Unknown analysis type: {analysis_type}")
            
            # Get the prompt from the saved file
            prompt_file = os.path.join(self.output_dir, "prompts", f'{analysis_type}_analysis_prompt.txt')
            if os.path.exists(prompt_file):
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    prompt = f.read()
            else:
                prompt = "Prompt not saved"
            
            # Already checked for hallucinations in catalyst analysis
            if analysis_type == 'catalyst':
                return analysis_type, response
            
            # Check for hallucinations and save results
            verified_response = await self.hallucination_checker.check_and_save(
                model=self.llm_model,
                prompt=prompt,
                response=response,
                analysis_type=analysis_type,
                output_dir=self.output_dir
            )
            
            self._save_analysis(verified_response, f'{analysis_type}_analysis_result.md')
            return analysis_type, verified_response
            
        except Exception as e:
            traceback.print_exc()
            print(f"{analysis_type}分析出错: {str(e)}")
            return analysis_type, None

    async def analyze(self) -> Dict[str, str]:
        """Perform comprehensive analysis"""
        try:
            results = {}
            # Get company info
            print("\n获取公司信息...")
            company_info = await self.data_source.get_company_info(self.symbol)
            market_cap = company_info.get('mktCap', 'N/A')
            company_description = company_info.get('description', 'N/A')
            latest_price = company_info.get('price', 'N/A')
            
            # Get stock data
            print("\n获取股票数据...")
            price_data = await self.data_source.get_stock_data(self.symbol, self.period)
            latest_price = price_data.iloc[-1]['Close']
            print(f"\n当前股价: ${latest_price:.2f}")
            print(f"\n市值: ${market_cap/1000000000:.2f}B")

            # Save stock data
            print("\n保存股票数据...")
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            data_file = os.path.join(data_dir, 'stock_data.csv')
            price_data.to_csv(data_file, index=False)
            print(f"股票数据已保存到：{data_file}")
            
            if self.one_step:
                catalyst_data = await self.catalyst_analyzer.analyze({'symbol': self.symbol}, only_return_data=True)
                technical_data = await self.technical_analyzer.analyze({'symbol': self.symbol, 'price_data': price_data, 'latest_price': latest_price}, only_return_data=True)
                financial_data = await self.financial_analyzer.analyze({'symbol': self.symbol, 'financial_data': await self.data_source.get_financial_data(self.symbol), 'latest_price': latest_price, 'market_cap': market_cap}, only_return_data=True)
                options_data = await self.options_analyzer.analyze({'symbol': self.symbol, 'options_data': await self.data_source.get_options_data(self.symbol), 'latest_price': latest_price}, only_return_data=True)
                await self._one_step_generate_report(latest_price, market_cap, technical_data, financial_data, options_data, catalyst_data)           
            elif self.two_step:
                technical_data = await self.technical_analyzer.analyze({'symbol': self.symbol, 'price_data': price_data, 'latest_price': latest_price}, only_return_data=True)
                financial_data = await self.financial_analyzer.analyze({'symbol': self.symbol, 'financial_data': await self.data_source.get_financial_data(self.symbol), 'latest_price': latest_price, 'market_cap': market_cap}, only_return_data=True)
                options_data = await self.options_analyzer.analyze({'symbol': self.symbol, 'options_data': await self.data_source.get_options_data(self.symbol), 'latest_price': latest_price}, only_return_data=True)
                catalyst_analysis = await self.catalyst_analyzer.analyze({'symbol': self.symbol}, only_return_data=False)['analysis']
                self._save_analysis(catalyst_analysis, 'catalyst_analysis_result.md')
                await self._two_step_generate_report(latest_price, market_cap, technical_data, financial_data, options_data, catalyst_analysis)
            else:
                # 准备所有分析任务的参数
                analysis_tasks = {
                    'catalyst': {'symbol': self.symbol},
                    'technical': {
                        'symbol': self.symbol,
                        'price_data': price_data,
                        'latest_price': latest_price
                    },
                    'financial': {
                        'symbol': self.symbol,
                            'financial_data': await self.data_source.get_financial_data(self.symbol),
                            'latest_price': latest_price,
                            'market_cap': market_cap
                        }
                    }

                # 如果有期权数据，添加期权分析任务
                options_data = await self.data_source.get_options_data(self.symbol)
                if options_data.get('calls') is not None and not options_data['calls'].empty:
                    options_data['stock_price'] = latest_price
                    analysis_tasks['options'] = {
                        'symbol': self.symbol,
                        'options_data': options_data,
                        'latest_price': latest_price
                    }

                print("\n开始并行执行分析任务...")
                # 使用线程池并行执行分析任务
                # Use coroutines for concurrency
                # Create coroutines for each analysis task
                coroutines = [
                    self._run_analysis_task(analysis_type, params)
                    for analysis_type, params in analysis_tasks.items()
                ]

                # Gather and execute all coroutines
                analysis_results = await asyncio.gather(*coroutines, return_exceptions=True)

                # Process results
                for analysis_type, result in zip(analysis_tasks.keys(), analysis_results):
                    if isinstance(result, Exception):
                        print(f"\n{analysis_type}分析失败: {str(result)}")
                    else:
                        _, analysis = result
                        if analysis is not None:
                            results[f'{analysis_type}_analysis'] = analysis
                            print(f"\n{analysis_type}分析完成")

                # Generate comprehensive report
                await self._generate_report(
                    latest_price=latest_price,
                    market_cap=market_cap,
                    technical_analysis=results.get('technical_analysis', ''),
                    financial_analysis=results.get('financial_analysis', ''),
                    options_analysis=results.get('options_analysis', ''),
                    catalyst_analysis=results.get('catalyst_analysis', '')
                )
                
                return results
            
        except Exception as e:
            print(f"\n错误详情：")
            import traceback
            print(traceback.format_exc())
            raise Exception(f"Analysis failed: {str(e)}")
        
    async def analyze_catalyst_stream(self, test = False, stream_status = {}):
        """Perform comprehensive analysis"""
        try:
            if test:
                async for chunk in dummy_stream("analyze_catalyst_stream", stream_status=stream_status):
                    yield chunk
                self.catalyst_analyzer.analysis = "analyze_catalyst_stream"
                
                self.technical_data = "Dummy"
                self.financial_data = "Dummy"
                self.options_data = "Dummy"
                return
            # Get company info
            print("\n获取公司信息...")
            company_info = await self.data_source.get_company_info(self.symbol)
            self.market_cap = market_cap = company_info.get('mktCap', 'N/A')
            company_description = company_info.get('description', 'N/A')
            latest_price = company_info.get('price', 'N/A')
            
            # Get stock data
            print("\n获取股票数据...")
            price_data = await self.data_source.get_stock_data(self.symbol, self.period)
            self.latest_price = latest_price = price_data.iloc[-1]['Close']
            print(f"\n当前股价: ${latest_price:.2f}")
            print(f"\n市值: ${market_cap/1000000000:.2f}B")

            # Save stock data
            print("\n保存股票数据...")
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            data_file = os.path.join(data_dir, 'stock_data.csv')
            price_data.to_csv(data_file, index=False)
            print(f"股票数据已保存到：{data_file}")
            
            # if not test:
            self.technical_data = await self.technical_analyzer.analyze({'symbol': self.symbol, 'price_data': price_data, 'latest_price': latest_price}, only_return_data=True)
            self.financial_data = await self.financial_analyzer.analyze({'symbol': self.symbol, 'financial_data': await self.data_source.get_financial_data(self.symbol), 'latest_price': latest_price, 'market_cap': market_cap}, only_return_data=True)
            self.options_data = await self.options_analyzer.analyze({'symbol': self.symbol, 'options_data': await self.data_source.get_options_data(self.symbol), 'latest_price': latest_price}, only_return_data=True)
            catalyst_analysis_generator = self.catalyst_analyzer.analyze_stream({'symbol': self.symbol}, stream_status=stream_status)
            async for chunk in catalyst_analysis_generator:
                yield chunk
            self._save_analysis(self.catalyst_analyzer.analysis, 'catalyst_analysis_result.md')
            # else:
            #     async for chunk in dummy_stream("analyze_catalyst_stream", stream_status=stream_status):
            #         yield chunk
            #     self.catalyst_analyzer.analysis = "analyze_catalyst_stream"
                
            #     self.technical_data = "Dummy"
            #     self.financial_data = "Dummy"
            #     self.options_data = "Dummy"
                # yield None
        except Exception as e:
            print(f"\n错误详情：")
            import traceback
            print(traceback.format_exc())
            raise Exception(str(e))
        
    async def generate_report_stream(self, test=False, **kwargs):
        report_generator_stream = dummy_stream("generate_report_stream", stream_status=kwargs['stream_status'] if 'stream_status' in kwargs else {}) if test else self.report_generator.generate_two_step_report_stream(
            symbol=self.symbol,
            latest_price=self.latest_price,
            market_cap=self.market_cap,
            technical_data=self.technical_data,
            financial_data=self.financial_data,
            options_data=self.options_data,
            catalyst_analysis=self.catalyst_analyzer.analysis
        )
        print("\n正在生成报告...")
        async for chunk in report_generator_stream:
            if test:
                await asyncio.sleep(0.1)
            yield chunk
        print("\n生成报告成功")
            
    def _save_analysis(self, analysis: str, filename: str):
        """Save analysis results to file"""
        output_dir_reports = f"{self.output_dir}/reports"
        os.makedirs(output_dir_reports, exist_ok=True)
        filepath = os.path.join(output_dir_reports, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {self.symbol} 分析结果\n\n")
            f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(analysis)

    async def _one_step_generate_report(self, latest_price: float, market_cap: float, technical_data: str, financial_data: str, options_data: str = None, catalyst_data: str = None) -> None:
        """Generate final analysis report"""
        try:
            print("\n正在生成最终分析报告...")
            
            # Generate integrated report using report generator
            final_report = await self.report_generator.generate_one_step_report(
                symbol=self.symbol,
                latest_price=latest_price,
                market_cap=market_cap,
                technical_data=technical_data,
                financial_data=financial_data,
                options_data=options_data,
                catalyst_data=catalyst_data,
                model=self.llm_model,
                output_dir=self.output_dir
            )
            
            print("\n分析完成！所有报告已保存到目录：", self.output_dir)

        except Exception as e:
            print(f"生成报告时出错：{str(e)}")
            raise 
            
    
    async def _two_step_generate_report(self, latest_price: float, market_cap: float, technical_data: str, financial_data: str, options_data: str = None, catalyst_analysis: str = None) -> None:
        """Generate final analysis report"""
        try:
            print("\n正在生成最终分析报告...")
            
            # Generate integrated report using report generator
            final_report = await self.report_generator.generate_two_step_report(
                symbol=self.symbol,
                latest_price=latest_price,
                market_cap=market_cap,
                technical_data=technical_data,
                financial_data=financial_data,
                options_data=options_data,
                catalyst_analysis=catalyst_analysis,
                model=self.llm_model,
                output_dir=self.output_dir
            )           
            print("\n分析完成！所有报告已保存到目录：", self.output_dir)
            
            
        except Exception as e:
            print(f"生成报告时出错：{str(e)}")
            raise 

    async def _generate_report(self, latest_price: float, market_cap: float, technical_analysis: str, financial_analysis: str, options_analysis: str = None, catalyst_analysis: str = None) -> None:
        """Generate final analysis report"""
        try:
            print("\n正在生成最终分析报告...")
            
            # Generate integrated report using report generator
            final_report = await self.report_generator.generate_integrated_report(
                symbol=self.symbol,
                latest_price=latest_price,
                market_cap=market_cap,
                technical_analysis=technical_analysis,
                financial_analysis=financial_analysis,
                options_analysis=options_analysis,
                catalyst_analysis=catalyst_analysis,
                model=self.llm_model,
            )
            
            print("\n分析完成！所有报告已保存到目录：", self.output_dir)
            
        except Exception as e:
            print(f"生成报告时出错：{str(e)}")
            raise 