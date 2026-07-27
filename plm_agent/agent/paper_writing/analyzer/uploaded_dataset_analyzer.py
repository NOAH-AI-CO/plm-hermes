import pandas as pd
import asyncio
import json
from typing import Dict, Any, List, Optional
import os
from datetime import datetime

import logging
logging.basicConfig(level=logging.INFO)

from ..schema.manuscript import ManuscriptProfile, WritingPurposeDetail
from ..schema.data_insight import DatasetAnalysisResult, AnalysisResult, StatisticalToolResult, DataPreview
from ..tools.claude_tools import STATISTICAL_TOOLS, process_tool_call
from llm.azure_models import GPT5Mini


class UploadedDatasetAnalyzer:
    def __init__(self, llm=None, file_path=None, file_id=None):
        self.llm = llm or GPT5Mini()
        self.file_path = file_path
        self.file_id = file_id
        # Only read CSV if file_path is provided
        if file_path:
            self.df = pd.read_csv(file_path)
        else:
            self.df = None
    
    async def analyze_data(self, df: pd.DataFrame, manuscript_profile: Optional[ManuscriptProfile] = None) -> DatasetAnalysisResult:
        analysis_tasks = await self.generate_data_analysis_tasks(df, manuscript_profile)
        results = []
        for task in analysis_tasks:
            result = await self.call_statistical_tools(df, task, STATISTICAL_TOOLS)
            logging.info(f"Analysis result: {result}")
            results.append(result)
        
        # 直接返回格式化后的结果，传递df参数
        return self._format_results(results, df)
    
    async def generate_data_analysis_tasks(self, df: pd.DataFrame, manuscript_profile: Optional[ManuscriptProfile] = None) -> List[str]:
        data_preview = self._get_data_preview(df)
        analysis_forcus = self._get_analysis_forcus(manuscript_profile)

        if not analysis_forcus:
            return []
        
        task_prompt = f"""
        You are a data analysis expert. Based on the data preview and the recomended analysis forcus, generate a list of specific and appropriate data analysis tasks.

        Each task should clearly specify:
        1. The analysis objective (e.g., compare groups, assess associations, describe distributions)
        2. The columns involved (from the table below, based on names and types)
        3. The statistical method used
        
        Return the tasks as a numbered list of strings (3–5 items).

        ### Data structure:
        {chr(10).join(f"- {col}: {str(dtype)}" for col, dtype in data_preview['data_structure'].items())}

        ### Data preview (first 10 rows):
        {data_preview['data_preview']}

        ### Recommended analysis focus:
        {analysis_forcus['description']} Suggested key analysis tasks include:
        {chr(10).join(f"- {task}" for task in analysis_forcus.get('key_analyses', []))}

        ### Expected variable roles:
        {analysis_forcus['expected_variable_roles']}

        ### Recomended analysis methods:
        {analysis_forcus['statistical_methods']}
        """

        response = await self.llm.client.messages.create(
            model=self.llm.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": task_prompt}]
        )
        
        if response.content and hasattr(response.content[0], 'text'):
            content_text = response.content[0].text
            tasks = []
            lines = content_text.split('\n')
            for line in lines:
                line = line.strip()
                if line and (line[0].isdigit() or line.startswith('-') or line.startswith('•')):
                    task = line.lstrip('0123456789.-• ').strip()
                    if task:
                        tasks.append(task)
            return tasks  
        
        return []

    async def call_statistical_tools(self, df: pd.DataFrame, task: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:

        data_preview = self._get_data_preview(df)

        task_prompt = f"""
        Data structure:
        {chr(10).join(f"- {col}: {str(dtype)}" for col, dtype in data_preview['data_structure'].items())}

        Data preview (first 10 rows):
        {data_preview['data_preview']}

        Task:
        Based on the dataset above, please address the following question: {task}

        You may use available statistical tools to perform the necessary analysis.
        """

        response = await self.llm.client.messages.create(
            model=self.llm.model,
            max_tokens=4000,
            messages=[{"role": "user", "content": task_prompt}],
            tools=tools,
            tool_choice={"type": "auto"}
        )
        
        if response.content:
            tool_results = []
            for content_block in response.content:
                if hasattr(content_block, 'type') and content_block.type == 'tool_use':
                    tool_name = content_block.name
                    tool_args = content_block.input
                    logging.info(f"Executing tool: {tool_name} with args: {tool_args}")

                    result = process_tool_call(tool_name, tool_args, df)
                    tool_results.append({
                        'tool_name': tool_name,
                        'result': result
                    })
                    logging.info(f"Tool result: {result}")
        
        if tool_results:
            # 有工具被调用的情况
            follow_up_message = f"""
            Tool execution results:
            """
            for result in tool_results:
                follow_up_message += f"\n{result['tool_name']}: {result['result']}"

            logging.info(f"Sending tool results to Claude: {follow_up_message}")

            tool_result_messages = []
            tool_result_index = 0
            for content_block in response.content:
                if hasattr(content_block, 'type') and content_block.type == 'tool_use':
                    tool_result_messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": content_block.id,
                                "content": str(tool_results[tool_result_index]['result'])
                            }
                        ]
                    })
                    tool_result_index += 1

            follow_up_response = await self.llm.client.messages.create(
                model=self.llm.model,
                max_tokens=4000,
                messages=[
                    {"role": "user", "content": task_prompt},
                    {"role": "assistant", "content": response.content},
                    *tool_result_messages,
                    {"role": "user", "content": "Please summarize the results of the analysis."}
                ]
            )
            
            return {
                "success": True,
                "analysis_type": "with_tools",
                "tool_results": tool_results,
                "summary": follow_up_response.content
            }
        else:
            # 没有工具被调用的情况
            logging.info("No tools were called by the LLM")
            
            # 检查LLM是否提供了有意义的回答
            if response.content:
                # 提取文本内容
                text_content = ""
                for content_block in response.content:
                    if hasattr(content_block, 'type') and content_block.type == 'text':
                        text_content += content_block.text
                
                if text_content.strip():
                    return {
                        "success": True,
                        "analysis_type": "text_only",
                        "message": "LLM provided analysis without using statistical tools",
                        "content": text_content
                    }
                else:
                    return {
                        "success": False,
                        "analysis_type": "no_tools_no_content",
                        "message": "LLM did not call any tools and provided no meaningful content",
                        "suggestion": "Consider rephrasing the analysis task or checking if the data structure is suitable for the requested analysis"
                    }
            else:
                return {
                    "success": False,
                    "analysis_type": "no_response",
                    "message": "LLM provided no response content",
                    "suggestion": "Check the task description and data structure"
                }

    def _get_data_preview(self, df: pd.DataFrame) -> Dict[str, Any]:
        preview = {
            "data_preview": df.head(10).to_dict(orient="records"),
            "data_structure": df.dtypes.to_dict()
        }
        return preview

    def _get_analysis_forcus(self, manuscript_profile: Optional[ManuscriptProfile] = None) -> Optional[Dict]:
        if manuscript_profile:
            study_type = manuscript_profile.study_type
            from ..presets.analysis import DATA_ANALYSIS_GUIDE_WITH_STUDY_TYPE
            if study_type in DATA_ANALYSIS_GUIDE_WITH_STUDY_TYPE:
                return DATA_ANALYSIS_GUIDE_WITH_STUDY_TYPE.get(study_type)
        return None

    def _format_results(self, results: List[Dict[str, Any]], df: pd.DataFrame = None) -> DatasetAnalysisResult:
        """将分析结果格式化为 DatasetAnalysisResult 对象"""
        
        # 使用传入的df参数，如果没有则使用self.df
        data_df = df if df is not None else self.df
        
        if data_df is None:
            raise ValueError("No DataFrame provided for formatting results")
        
        # 创建 DataPreview
        data_preview = DataPreview(
            data_preview=data_df.head(5).to_dict(orient="records"),
            data_structure=data_df.dtypes.astype(str).to_dict()
        )
        
        # 创建 AnalysisResult 列表
        analysis_results = []
        successful_count = 0
        
        for i, result in enumerate(results, 1):
            # 创建 StatisticalToolResult 列表
            tools = []
            if result.get('success') and result.get('analysis_type') == 'with_tools':
                for tool_result in result.get('tool_results', []):
                    tools.append(StatisticalToolResult(
                        name=tool_result['tool_name'],
                        result=tool_result.get('result', {})
                    ))
            
            # 创建 AnalysisResult
            analysis_result = AnalysisResult(
                id=i,
                success=result.get('success', False),
                type=result.get('analysis_type', 'unknown'),
                tools=tools if tools else None,
                summary=result.get('summary'),
                content=result.get('content'),
                error=result.get('message') if not result.get('success') else None,
                suggestion=result.get('suggestion') if not result.get('success') else None
            )
            
            analysis_results.append(analysis_result)
            if result.get('success'):
                successful_count += 1
        
        # 提取关键发现和统计方法
        key_findings = self._extract_key_findings(analysis_results)
        statistical_methods = self._extract_statistical_methods(analysis_results)
        
        return DatasetAnalysisResult(
            file_id=self.file_id or "unknown",
            file_path=self.file_path or "unknown",
            file_name=os.path.basename(self.file_path) if self.file_path else "unknown",
            data_preview=data_preview,
            analysis_results=analysis_results,
            total_analyses=len(results),
            successful_analyses=successful_count,
            key_findings=key_findings,
            statistical_methods_used=statistical_methods
        )
    
    def _extract_key_findings(self, analysis_results: List[AnalysisResult]) -> List[str]:
        """从分析结果中提取关键发现"""
        findings = []
        for result in analysis_results:
            if result.success and result.summary:
                # 这里可以添加更复杂的逻辑来提取关键发现
                findings.append(str(result.summary))
        return findings
    
    def _extract_statistical_methods(self, analysis_results: List[AnalysisResult]) -> List[str]:
        """从分析结果中提取使用的统计方法"""
        methods = set()
        for result in analysis_results:
            if result.success and result.tools:
                for tool in result.tools:
                    methods.add(tool.name)
        return list(methods)


# 测试代码
if __name__ == "__main__":
    import tempfile
    import os
    from ..schema.manuscript import WritingPurposeDetail
    from ..presets.enum import StudyType, PublicationType, WritingPurpose
    
    def create_sample_csv():
        """创建示例 CSV 数据"""
        data = {
            'Patient_ID': [f'P{i:03d}' for i in range(1, 101)],
            'Age': [25 + i % 50 for i in range(100)],  # 25-74岁
            'Gender': ['Male' if i % 2 == 0 else 'Female' for i in range(100)],
            'Treatment_Group': ['Treatment_A' if i % 3 == 0 else 'Treatment_B' if i % 3 == 1 else 'Placebo' for i in range(100)],
            'Baseline_Score': [50 + (i % 30) + (i % 10) for i in range(100)],  # 50-89
            'Week_4_Score': [55 + (i % 25) + (i % 8) for i in range(100)],     # 55-87
            'Week_8_Score': [60 + (i % 20) + (i % 6) for i in range(100)],     # 60-85
            'Adverse_Event': ['Yes' if i % 10 == 0 else 'No' for i in range(100)],
            'BMI': [20 + (i % 15) + (i % 5) * 0.5 for i in range(100)]        # 20-34.5
        }
        
        df = pd.DataFrame(data)
        
        # 创建临时 CSV 文件
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
        df.to_csv(temp_file.name, index=False)
        temp_file.close()
        
        return temp_file.name, df

    def create_sample_manuscript_profile():
        """创建示例 ManuscriptProfile"""
        # 创建 WritingPurposeDetail
        writing_purpose_detail = WritingPurposeDetail(
            primary_purpose=WritingPurpose.ORIGINAL_RESEARCH,
            secondary_purposes=[WritingPurpose.METHODOLOGY],
            summary="To evaluate the efficacy and safety of Treatment A vs Treatment B vs Placebo",
            target_journal="Clinical Trials Journal",
            key_messages=[
                "Treatment A shows significant improvement over placebo",
                "Treatment B demonstrates comparable efficacy to Treatment A",
                "Both treatments are well-tolerated with minimal adverse events"
            ],
            writing_style="Academic, evidence-based",
            tone="Objective and professional",
            focus_areas=["Efficacy analysis", "Safety assessment", "Statistical significance"],
            emphasis_points=["Primary endpoint results", "Secondary endpoint analysis", "Safety profile"]
        )
        
        return ManuscriptProfile(
            study_type=StudyType.RCT,
            publication_type=PublicationType.ORIGINAL_RESEARCH,
            writing_purpose=writing_purpose_detail,
            confidence_scores={
                "study_type": 0.95,
                "publication_type": 0.90,
                "writing_purpose": 0.85
            },
            reasoning={
                "study_type": "Randomized controlled trial with three treatment arms",
                "publication_type": "Original research presenting new clinical trial results",
                "writing_purpose": "Primary objective is to evaluate treatment efficacy and safety"
            },
            supporting_evidence={
                "study_type": ["Randomized design", "Three treatment groups", "Blinded assessment"],
                "publication_type": ["Clinical trial results", "Statistical analysis", "Safety data"],
                "writing_purpose": ["Primary endpoint analysis", "Secondary endpoint evaluation", "Safety assessment"]
            },
            file_paths=["sample_clinical_trial_data.csv"],
            analysis_metadata={
                "primary_endpoint": "Change in score from baseline to Week 8",
                "secondary_endpoints": [
                    "Change in score from baseline to Week 4",
                    "Proportion of patients with adverse events",
                    "Change in BMI from baseline to Week 8"
                ],
                "statistical_methods": [
                    "ANOVA for continuous variables",
                    "Chi-square test for categorical variables",
                    "Mixed-effects model for repeated measures",
                    "Logistic regression for adverse events"
                ],
                "key_variables": {
                    "primary_outcome": "Week_8_Score",
                    "baseline": "Baseline_Score",
                    "treatment": "Treatment_Group",
                    "demographics": ["Age", "Gender", "BMI"],
                    "safety": "Adverse_Event"
                }
            }
        )

    async def test_uploaded_dataset_analyzer():
        """测试 UploadedDatasetAnalyzer 类"""
        print("开始测试 UploadedDatasetAnalyzer...")
        
        # 创建示例数据
        csv_file_path, df = create_sample_csv()
        manuscript_profile = create_sample_manuscript_profile()
        
        print(f"创建了示例 CSV 文件: {csv_file_path}")
        print(f"数据形状: {df.shape}")
        print(f"数据列: {list(df.columns)}")
        print(f"前5行数据:")
        print(df.head())
        
        try:
            # 初始化 DataAnalyzer
            analyzer = UploadedDatasetAnalyzer(file_path=csv_file_path, file_id="sample_clinical_trial_data.csv")
            
            print("\n=== 测试数据分析 ===")
            
            # 执行数据分析
            formatted_results = await analyzer.analyze_data(df, manuscript_profile)
            
            print(f"\n分析完成，获得格式化结果:")
            print(json.dumps(formatted_results.model_dump(), indent=2, ensure_ascii=False, default=str))
            
            # 保存格式化输出到文件
            output_path = f"formatted_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(formatted_results.model_dump(), f, indent=2, ensure_ascii=False, default=str)
            print(f"\n格式化输出已保存到: {output_path}")
        
        except Exception as e:
            print(f"测试过程中出现错误: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # 清理临时文件
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)
                print(f"\n已删除临时文件: {csv_file_path}")

    async def test_single_analysis():
        """测试单个分析任务"""
        print("\n=== 测试单个分析任务 ===")
        
        csv_file_path, df = create_sample_csv()
        manuscript_profile = create_sample_manuscript_profile()
        
        try:
            analyzer = UploadedDatasetAnalyzer(file_path=csv_file_path, file_id="sample_clinical_trial_data.csv")
            
            # 测试单个任务
            task = "Compare the mean Week 8 scores between treatment groups using appropriate statistical test"
            
            print(f"执行任务: {task}")
            
            result = await analyzer.call_statistical_tools(df, task, STATISTICAL_TOOLS)
            
            print(f"单个任务结果:")
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
        except Exception as e:
            print(f"单个任务测试中出现错误: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            if os.path.exists(csv_file_path):
                os.unlink(csv_file_path)

    # 运行测试
    print("=== 运行 UploadedDatasetAnalyzer 测试 ===")
    asyncio.run(test_uploaded_dataset_analyzer())
    asyncio.run(test_single_analysis())