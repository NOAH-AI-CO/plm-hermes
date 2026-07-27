import asyncio
import io
import os
import re
import traceback
from typing import Optional, Any
from datetime import datetime
import pytz

from ..prompts.analysis_prompts_en import IntegratedReportPromptEn, OneStepReportGenerationPromptEn, TwoStepReportGenerationPromptEn
from utils.bio_quant.dummy_stream import dummy_stream
from ..prompts.analysis_prompts import IntegratedReportPrompt, OneStepReportGenerationPrompt, TwoStepReportGenerationPrompt
from .hallucination_checker import HallucinationChecker
from i18n.languages import normalize as _norm

class ReportGenerator:
    """Report generator for creating integrated investment reports"""

    def __init__(self, llm_model, language=""):
        """Initialize report generator"""
        self.model = llm_model
        language = _norm(language)
        self.prompt_template = IntegratedReportPrompt() if language == "zh-CN" else IntegratedReportPromptEn()
        self.one_step_prompt_template = OneStepReportGenerationPrompt() if language == "zh-CN" else OneStepReportGenerationPromptEn()
        self.two_step_prompt_template = TwoStepReportGenerationPrompt() if language == "zh-CN" else TwoStepReportGenerationPromptEn()
        self.language = language
        self.hallucination_checker = HallucinationChecker(language)
        
    def set_output_dir(self, output_dir: str):
        """Set output directory for report generation"""
        self.output_dir = output_dir
        
    async def generate_integrated_report(
        self,
        symbol: str,
        latest_price: float,
        market_cap: float,
        technical_analysis: str,
        financial_analysis: str,
        options_analysis: Optional[str] = None,
        catalyst_analysis: Optional[str] = None,
        model: Any = None,
    ) -> str:
        """Generate integrated investment report
        
        Args:
            symbol: Stock symbol
            technical_analysis: Technical analysis results
            financial_analysis: Financial analysis results
            options_analysis: Options analysis results (optional)
            model: LLM model for generating report
            
        Returns:
            Markdown formatted report
        """
        try:
            # Format symbol for display
            display_symbol = symbol
            
            print("\n正在生成综合分析报告...")

            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)
            
            if model:
                # Generate report using LLM with the prompt template
                prompt = self.prompt_template.format(
                    symbol=display_symbol,
                    report_date=now.strftime("%Y-%m-%d"),
                    latest_price=latest_price,
                    market_cap=market_cap,
                    technical_analysis=technical_analysis,
                    financial_analysis=financial_analysis,
                    options_analysis=options_analysis,
                    catalyst_analysis=catalyst_analysis
                )
                
                # Save prompt for debugging
                output_dir_prompts = f"{self.output_dir}/prompts"
                os.makedirs(output_dir_prompts, exist_ok=True)
                prompt_file = os.path.join(output_dir_prompts, 'integrated_report_prompt.txt')
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                print(f"- 分析提示已保存至：{prompt_file}")
                
                print("- 调用 AI 模型生成报告")
                report = await model.generate(prompt)

                # remove ```markdown and ```
                report = report.replace('```markdown', '').replace('```', '')

                # hallucination checking
                verified_report = await self.hallucination_checker.check_and_save(
                    model=model,
                    prompt=prompt,
                    response=report,
                    analysis_type="integrated_report"
                )
                
            else:
                # If no model provided, combine analysis results directly
                print("No model provided, failed to generate report")
                return None

            # Add report metadata
            header = f"""- 报告日期：{now.strftime("%Y-%m-%d")}
- 报告时间：{now.strftime("%H:%M:%S")} (美国东部时间)
- 分析对象：{display_symbol}
- 最新价格：${latest_price:.2f}
- 市值：${market_cap/1000000000:.2f}B
---

"""
            final_report = header + report

            # Add risk warning
            final_report += """

## 风险提示

1. 本报告基于公开数据分析，不构成投资建议
2. 投资有风险，入市需谨慎
3. 过往表现不代表未来收益"""
            
            if catalyst_analysis:
                final_report += f"""

## 附录：催化剂详细分析

{catalyst_analysis}
"""         

            final_report += f"""

## 附录：财务详细分析

{financial_analysis}
"""

            final_report += f"""

## 附录：技术详细分析

{technical_analysis}
"""

            if options_analysis:
                final_report += f"""

## 附录：期权详细分析

{options_analysis}
"""

            # Save report
            output_dir_reports = f"{self.output_dir}/reports"
            os.makedirs(output_dir_reports, exist_ok=True)
            
            # Save markdown version
            md_file = os.path.join(output_dir_reports, f'{symbol}_investment_report.md')
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(final_report)
            print(f"- 综合投资报告已保存至：{md_file}")
            
            return final_report
            
        except Exception as e:
            raise Exception(f"生成报告时出错：{str(e)}") 
        
    async def generate_one_step_report(
        self,
        symbol: str,
        latest_price: float,
        market_cap: float,
        technical_data: str,
        financial_data: str,
        options_data: str,
        catalyst_data: str,
        model: Any = None,
    ) -> str:
        """Generate one-step investment report"""
        try:
            # Format symbol for display
            display_symbol = symbol

            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            if model:
                # Generate report using LLM with the prompt template
                prompt = self.one_step_prompt_template.format(
                    symbol=display_symbol,
                    report_date=now.strftime("%Y-%m-%d"),
                    latest_price=latest_price,
                    market_cap=market_cap,
                    technical_data=technical_data,
                    financial_data=financial_data,
                    options_data=options_data,
                    catalyst_data=catalyst_data
                )
                
                # Save prompt for debugging
                output_dir_prompts = f"{self.output_dir}/prompts"
                os.makedirs(output_dir_prompts, exist_ok=True)
                prompt_file = os.path.join(output_dir_prompts, 'one_step_report_prompt.txt')
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                print(f"- 分析提示已保存至：{prompt_file}")
                
                print("- 调用 AI 模型生成报告")
                report = await model.generate(prompt)

                # remove ```markdown and ```
                report = report.replace('```markdown', '').replace('```', '')

            else:
                print("No model provided, failed to generate report")
                return None
            
            # Add report metadata
            header = f"""- 报告日期：{now.strftime("%Y-%m-%d")}
- 报告时间：{now.strftime("%H:%M:%S")} (美国东部时间)
- 分析对象：{display_symbol}
- 最新价格：${latest_price:.2f}
- 市值：${market_cap/1000000000:.2f}B
---
"""
            final_report = header + report

            # Save report
            output_dir_reports = f"{self.output_dir}/reports"
            os.makedirs(output_dir_reports, exist_ok=True)

            # Save markdown version
            md_file = os.path.join(output_dir_reports, f'{symbol}_investment_report.md')
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(final_report)
            print(f"- 综合投资报告已保存至：{md_file}")

            return final_report
        
        except Exception as e:
            raise Exception(f"生成报告时出错：{str(e)}") 

    async def generate_two_step_report(
        self,
        symbol: str,
        latest_price: float,
        market_cap: float,
        technical_data: str,
        financial_data: str,
        options_data: str,
        catalyst_analysis: str,
        model: Any = None,
    ) -> str:
        """Generate two-step investment report"""
        try:
            # Format symbol for display
            display_symbol = symbol
            
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            if model:
                # Generate report using LLM with the prompt template
                prompt = self.two_step_prompt_template.format(
                    symbol=display_symbol,
                    report_date=now.strftime("%Y-%m-%d"),
                    latest_price=latest_price,
                    market_cap=market_cap,
                    technical_data=technical_data,
                    financial_data=financial_data,
                    options_data=options_data,
                    catalyst_analysis=catalyst_analysis
                )
                
                # Save prompt for debugging
                output_dir_prompts = f"{self.output_dir}/prompts"
                os.makedirs(output_dir_prompts, exist_ok=True)
                prompt_file = os.path.join(output_dir_prompts, 'two_step_report_prompt.txt')
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                print(f"- 分析提示已保存至：{prompt_file}")
                
                print("- 调用 AI 模型生成报告")
                report = await model.generate(prompt)

                # remove ```markdown and ```
                report = report.replace('```markdown', '').replace('```', '')

                # hallucination checking
                print("- 进行幻觉检查")
                verified_report = await self.hallucination_checker.check_and_save(
                    model=model,
                    prompt=prompt,
                    response=report,
                    analysis_type="two_step_report",
                    output_dir=self.output_dir
                )

                # Extract verified report from verified_report, tagged by <report>...</report>
                search = re.search(r'<report>(.*?)</report>', verified_report, re.DOTALL)
                report = search.group(1) if search else verified_report

            else:
                print("No model provided, failed to generate report")
                return None
            
            # Add report metadata
            header = f"""- 报告日期：{now.strftime("%Y-%m-%d")}
- 报告时间：{now.strftime("%H:%M:%S")} (美国东部时间)
- 分析对象：{display_symbol}
- 最新价格：${latest_price:.2f}
- 市值：${market_cap/1000000000:.2f}B
---
"""
            final_report = header + report
            if catalyst_analysis:
                final_report += f"""

## 附录：催化剂详细分析

{catalyst_analysis}
"""         

            # Save report
            output_dir_reports = f"{self.output_dir}/reports"
            os.makedirs(output_dir_reports, exist_ok=True)

            # Save markdown version
            md_file = os.path.join(output_dir_reports, f'{symbol}_investment_report.md')
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(final_report)
            print(f"- 综合投资报告已保存至：{md_file}")
            
            return final_report 
        
        except Exception as e:
            raise Exception(f"生成报告时出错：{str(e)}") 
        
    async def generate_two_step_report_stream(
        self,
        symbol: str,
        latest_price: float,
        market_cap: float,
        technical_data: str,
        financial_data: str,
        options_data: str,
        catalyst_analysis: str,
    ):
        """Generate two-step investment report step one"""
        try:
            # Format symbol for display
            self.symbol = symbol
            self.latest_price = latest_price
            self.market_cap = market_cap
            self.catalyst_analysis = catalyst_analysis
            
            eastern = pytz.timezone('America/New_York')
            self.now = datetime.now(eastern)
            
            # Temporary specialized prompt template
            # self.two_step_prompt_template = SpecializedReportPrompt()

            if self.model:
                # Generate report using LLM with the prompt template
                self.prompt = prompt = self.two_step_prompt_template.format(
                    symbol=self.symbol,
                    report_date=self.now.strftime("%Y-%m-%d"),
                    latest_price=latest_price,
                    market_cap=market_cap,
                    technical_data=technical_data,
                    financial_data=financial_data,
                    options_data=options_data,
                    catalyst_analysis=catalyst_analysis
                )
                
                # Save prompt for debugging
                output_dir_prompts = f"{self.output_dir}/prompts"
                os.makedirs(output_dir_prompts, exist_ok=True)
                prompt_file = os.path.join(output_dir_prompts, 'two_step_report_prompt.txt')
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                print(f"- 分析提示已保存至：{prompt_file}")
                
                print("- 调用 AI 模型生成报告")
                report_gen = self.model.generate_stream(prompt)
                string_buffer = io.StringIO()
                async for chunk in report_gen:
                    if chunk:
                        string_buffer.write(chunk)
                        yield chunk
                report = string_buffer.getvalue()
                string_buffer.close()
                

                # remove ```markdown and ```
                self.report = report.replace('```markdown', '').replace('```', '')

            else:
                print("No model provided, failed to generate report")
            
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"生成报告时出错：{str(e)}") 
            
    async def check_hallucination(self, test=False, **kwargs):
        try:
            report_checker = dummy_stream("check_report_hallucination", stream_status=kwargs["stream_status"]) if test else self.hallucination_checker.check_and_save_stream(
                model=self.model,
                prompt=self.prompt,
                response=self.report,
                analysis_type="two_step_report",
                output_dir=self.output_dir
            )

            print("\n正在检查报告幻觉...")
            async for chunk in report_checker:
                if test:
                    await asyncio.sleep(0.1)
                yield chunk
            if test:
                self.verified_report = "** Verified Report"
                yield None
                return
                
            verified_response = getattr(self.hallucination_checker, "verified_response", None)
            if not verified_response:
                print("- 检查报告幻觉失败")
                self.verified_report = None
                return 
            
            print("- 检查报告幻觉成功")
            
            # Extract verified report from verified_report, tagged by <report>...</report>
            search = re.search(r'<report>(.*?)</report>', verified_response, re.DOTALL)
            # if not search.group(1):
            verified_report = search.group(1) if search else verified_response
            self.verified_report = verified_report
            
            # Add report metadata
            header = f"""- 报告日期：{self.now.strftime("%Y-%m-%d")}
- 报告时间：{self.now.strftime("%H:%M:%S")} (美国东部时间)
- 分析对象：{self.symbol}
- 最新价格：${self.latest_price:.2f}
- 市值：${self.market_cap/1000000000:.2f}B
---
"""
            final_report = header + verified_report
            if self.catalyst_analysis:
                final_report += f"""

## 附录：催化剂详细分析

{self.catalyst_analysis}
"""         

            # Save report
            output_dir_reports = f"{self.output_dir}/data"
            os.makedirs(output_dir_reports, exist_ok=True)

            # Save markdown version
            md_file = os.path.join(output_dir_reports, f'{self.symbol}_investment_report.md')
            with open(md_file, 'w', encoding='utf-8') as f:
                f.write(final_report)
            print(f"- 综合投资报告已保存至：{md_file}")
            
        except Exception as e:
            raise Exception(f"检查报告幻觉/保存时出错：{str(e)}") 

if __name__ == "__main__":
    rg = ReportGenerator(None)
    import dotenv
    dotenv.load_dotenv()
    from bio_quant.models.composite_model import CompositeModel
    rg.model = CompositeModel()
    # Read prompt from file
    async def test():
        with open('bio_quant/core/two_step_report_prompt.txt', 'r', encoding='utf-8') as f:
            prompt = f.read()
        report_gen = rg.model.generate_stream(prompt)
        string_buffer = io.StringIO()
        async for chunk in report_gen:
            if chunk:
                string_buffer.write(chunk)
        report = string_buffer.getvalue()
        with open('bio_quant/core/result.txt', 'w', encoding='utf-8') as f:
            prompt = f.write(report)
        string_buffer.close()
    asyncio.run(test())