from datetime import datetime
import io
import traceback
import pandas as pd
from typing import Dict, Any
import json

import pytz

from ..prompts.analysis_prompts_en import CatalystAnalysisPromptEn
from utils.catalyst.retrieve import get_company_catalysts_and_related_info
from utils.bio_quant.dummy_stream import dummy_stream
from ..core.interfaces import Analyzer, DataSource, LLMModel
from ..prompts.analysis_prompts import CatalystAnalysisPrompt, IncludingPastCatalystAnalysisPrompt
# from utils.catalyst.retrieve import get_company_catalysts_and_related_info
from ..models.hyperbolic_deepseek_model import HyperbolicDeepSeekModel
from ..models.volcano_deepseek_model import VolcanoDeepSeekModel
from ..core.hallucination_checker import HallucinationChecker
import os
import requests
import re
import asyncio

class CatalystAnalyzer(Analyzer):
    def __init__(self, model: LLMModel, data_source: DataSource, language: str = "zh-CN"):
        """Initialize catalyst analyzer with LLM model"""
        self.model = model
        self.data_source = data_source
        self.prompt_template = CatalystAnalysisPrompt() if language == "zh-CN" else CatalystAnalysisPromptEn()
        self.output_dir = None
        self.hallucination_checker = HallucinationChecker(language)
        self.language = language

    def set_output_dir(self, output_dir: str):
        """Set output directory for analysis results"""
        self.output_dir = output_dir

    async def analyze(self, data: Dict[str, Any], only_return_data: bool = False) -> str:
        """Analyze catalyst data and return insights"""
        try:
            symbol = data['symbol']
            # Import asyncio if not already imported at the top
            # Run async function synchronously
            # catalyst_data, company_name = get_company_catalysts_and_related_info(symbol)
            
            catalyst_by_company_url = f"https://test.noahai.co/api/workflow/catalyst-company/"
            data = {"ticker": symbol}
            try:
                catalyst_data, company_name = await get_company_catalysts_and_related_info(symbol)
            except Exception as e:
                catalyst_data = requests.post(catalyst_by_company_url, json=data, timeout=10).json()
                catalyst_data, company_name = catalyst_data['data'], catalyst_data['name']
            print("\n处理催化剂信息...")
            
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            catalyst_data_file = os.path.join(data_dir, 'catalyst_analysis_data.json')
            with open(catalyst_data_file, 'w', encoding='utf-8') as f:
                f.write(json.dumps(catalyst_data, indent=4, ensure_ascii=False))
            print(f"- 催化剂事件数据已保存至：{catalyst_data_file}")
            
            # Convert to string
            # 不带indent，压缩上下文
            catalyst_str = json.dumps(catalyst_data, ensure_ascii=False, separators=(',', ':'))
            print("len(catalyst_str)", len(catalyst_str))

            if only_return_data:
                return catalyst_str
            
            print("- 生成分析提示")
            # Generate prompt
            prompt = self.prompt_template.format(
                symbol=symbol,
                current_time=datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S %Z'),
                company_name=company_name,
                catalyst_data=catalyst_str
            )
            self.prompt = prompt
            
            # Save prompt to file
            prompt_dir = os.path.join(self.output_dir, "prompts")
            os.makedirs(prompt_dir, exist_ok=True)
            prompt_file = os.path.join(prompt_dir, 'catalyst_analysis_prompt.txt')
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(prompt)
            print(f"- 分析提示已保存至：{prompt_file}")
            
            print("- 调用 AI 模型进行分析")
            # Get analysis from LLM
            # analysis = ""
            analysis = await self.model.generate(prompt, stream=True)
            analysis = analysis.replace('```markdown', '').replace('```', '')
            self.analysis = analysis

            # hallucination checking
            verified_analysis = await self.hallucination_checker.check_and_save(
                model=self.model,
                prompt=self.prompt,
                response=self.analysis,
                analysis_type="catalyst",
                output_dir=self.output_dir
            )

            # Extract verified analysis from verified_analysis, tagged by <report>...</report>
            verified_analysis = re.search(r'<report>(.*?)</report>', verified_analysis, re.DOTALL).group(1)
            
            catalyst_data_file = os.path.join(data_dir, 'catalyst_analysis.md')
            with open(catalyst_data_file, 'w', encoding='utf-8') as f:
                f.write(verified_analysis)
            print(f"- 催化剂事件分析已保存至：{catalyst_data_file}")

            print("- 催化剂分析完成")
            return {
                'analysis': verified_analysis,
                'raw_data': catalyst_data
            }
            
        except Exception as e:
            raise Exception(str(e)) 
        
    async def analyze_stream(self, data: Dict[str, Any], stream_status={}, include_past=False):
        """Analyze catalyst data and return insights"""
        try:
            symbol = data['symbol']
            # Import asyncio if not already imported at the top
            # Run async function synchronously
            # catalyst_data, company_name = get_company_catalysts_and_related_info(symbol)
            
            catalyst_by_company_url = f"https://test.noahai.co/api/workflow/catalyst-company/"
            data = {"ticker": symbol}
            try:
                # catalyst_data, company_name = await get_company_catalysts_and_related_info(symbol)
                catalyst_data, company_name = await get_company_catalysts_and_related_info(symbol, include_past=include_past)
            except Exception as e:
                traceback.print_exc()
                catalyst_data = requests.post(catalyst_by_company_url, json=data, timeout=10).json()
                catalyst_data, company_name = catalyst_data['data'], catalyst_data['name']
            print("\n处理催化剂信息...")

            # Convert to string
            # 不带indent，压缩上下文
            
            data_dir = os.path.join(self.output_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            catalyst_data_file = os.path.join(data_dir, 'catalyst_analysis_data.json')
            with open(catalyst_data_file, 'w', encoding='utf-8') as f:
                json.dump(catalyst_data, f, indent=4, ensure_ascii=False)
            print(f"- 催化剂事件数据已保存至：{catalyst_data_file}")
            
            
            catalyst_str = json.dumps(catalyst_data, ensure_ascii=False, separators=(',', ':'))
            print("len(catalyst_str)", len(catalyst_str))

            # if only_return_data:
            #     return catalyst_str
            
            print("- 生成分析提示")
            # Generate prompt
            prompt = self.prompt_template.format(
                symbol=symbol,
                current_time=datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S %Z'),
                company_name=company_name,
                catalyst_data=catalyst_str
            )
            
            if self.output_dir:
                # Save prompt to file
                prompt_dir = os.path.join(self.output_dir, "prompts")
                os.makedirs(prompt_dir, exist_ok=True)
                prompt_file = os.path.join(prompt_dir, 'catalyst_analysis_prompt.txt')
                with open(prompt_file, 'w', encoding='utf-8') as f:
                    f.write(prompt)
                print(f"- 分析提示已保存至：{prompt_file}")
            self.prompt = prompt
            
            stream_status['catalyst_data_obtained'] = True
            print("- 调用 AI 模型进行分析")
            # Get analysis from LLM
            analysis_gen = self.model.generate_stream(prompt, stream=True, stream_status=stream_status)
            string_buffer = io.StringIO()
            async for chunk in analysis_gen:
                if chunk:
                    string_buffer.write(chunk)
                    yield chunk
            draft = string_buffer.getvalue()
            string_buffer.close()
            self.analysis = draft.replace('```markdown', '').replace('```', '')
            
        except Exception as e:
            raise Exception(str(e)) 
        
    async def check_hallucination(self, test=False, **kwargs):
        try:
            # hallucination checking
            verified_analysis = dummy_stream("check_hallucination", stream_status=kwargs["stream_status"]) if test else self.hallucination_checker.check_and_save_stream(
                model=self.model,
                prompt=self.prompt,
                response=self.analysis,
                analysis_type="catalyst",
                output_dir=self.output_dir
            ) 
            
            async for chunk in verified_analysis:
                if test:
                    await asyncio.sleep(0.1)
                yield chunk

            analysis_result = getattr(self.hallucination_checker, "verified_response", None)
            if not analysis_result:
                print("催化剂幻觉检查失败")
                return
            
            # Extract verified analysis from verified_analysis, tagged by <report>...</report>
            verified_analysis_search = re.search(r'<report>(.*?)</report>', analysis_result, re.DOTALL)
            self.analysis = verified_analysis_search.group(1) if verified_analysis_search else ""
            if not self.analysis:
                raise Exception("催化剂幻觉检查失败,未能匹配<report>")
            
            data_dir = os.path.join(self.output_dir, "data")
            catalyst_data_file = os.path.join(data_dir, 'catalyst_analysis.md')
            with open(catalyst_data_file, 'w', encoding='utf-8') as f:
                f.write(self.analysis)
            print(f"- 催化剂事件分析已保存至：{catalyst_data_file}")
            
            print("- 催化剂幻觉检查完成")
        except Exception as e:
            traceback.print_exc()
            raise Exception(str(e))
            
if __name__ == "__main__":   
    ca = CatalystAnalyzer(VolcanoDeepSeekModel(test_mode=True), data_source=None)
    ca.set_output_dir('./outputs')
    # async def test():
    #     res = await ca.analyze({'symbol':'OMER'})
    #     print("res", res)
    # asyncio.run(test())
        
    async def test():
        result_gen = ca.analyze_stream({'symbol':'OMER'})
        async for result in result_gen:
            print(result)
                
    asyncio.run(test())