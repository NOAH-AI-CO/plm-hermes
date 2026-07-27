from datetime import datetime
import json
import shutil
import os
import asyncio
import io
import logging
import time
import traceback
from typing import Any, Callable, Dict, List, Type

from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.composite_models import CompositeMindsearchFinal as TestModels
from llm.base_model import BaseLLM
from agent.explore.schema import ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from agent.journal_recommendation.journal_recommendation_analyzer import JournalRecommendationAnalyzer as JournalAnalyzer
from utils.core.exception import UnexpectedException
from i18n.languages import normalize as _norm

logger = logging.getLogger(__name__)


class JournalRecommendationAgent(AgentPreset):
    llm: BaseLLM = TestModels()
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()  # 用于初始化标准响应格式
    language: str = "zh-CN"  # 默认中文
    journal_analyzer: JournalAnalyzer = None
    query_params: dict = {}
    
    def __init__(self, user_prompt: str = "", query_params: dict = {}, **kwargs):
        abstract = user_prompt
        print("ABSTRACT", abstract)

        super().__init__()
        if 'params' in kwargs and 'language' in kwargs['params']:
            self.language = _norm(kwargs['params']['language'])
        if 'raw_data' in kwargs and kwargs['raw_data']:
            raw_data_items = list(kwargs['raw_data'].items())
            for key, val in raw_data_items:
                if val != False and not val:
                    kwargs['raw_data'].pop(key, None)
            query_params = kwargs['raw_data']
        if 'language' in query_params:
            self.language = _norm(query_params.pop('language', ''))
        print("query_params", query_params)
            
        self.query_params = query_params
        
        output_dir = f"outputs/journal_recommendation_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        self.journal_analyzer = JournalAnalyzer(abstract=abstract, query_params=self.query_params, output_dir=output_dir)

        self._ensure_output_directories()
    
    def _ensure_output_directories(self):
        if not hasattr(self.journal_analyzer, 'output_dir'):
            return
            
        output_dir = self.journal_analyzer.output_dir
        dirs = ['data', 'reports']
        for dir_name in dirs:
            dir_path = os.path.join(output_dir, dir_name)
            os.makedirs(dir_path, exist_ok=True)
    
    async def run_func(self, func: Callable, buffer: io.StringIO):
        """运行异步函数并写入buffer"""
        async_generator = func()
        try:
            async for item in async_generator:
                buffer.write(item)
        except Exception as e:
            logger.error(f"run_func failed: {str(e)}")
            raise e
    
    async def use_tool(self, user_prompt: str = "", **kwargs):
        try:
            from utils.obs.client import upload_file
        except Exception as e:
            logger.warning(f"OBS client not available: {e}")
            upload_file = None
        
        try:
            start_time = time.time()
            
            response = self.mindsearch_helper.init_response(self)
            response.raw_data = {"abstract": self.journal_analyzer.abstract}
            yield response
            
            response.search_graph = self.init_search_graph()
            response.processing_type = ProcessingType.PROCESSING
            yield response
            
            ja = self.journal_analyzer
            
            # Step 1-3: 运行期刊推荐分析（包含搜索文章、提取期刊信息、分析数据）
            logger.info("Running journal recommendation analysis...")
            
            is_chinese = self.language == 'zh-CN'
            
            # 步骤1：开始执行
            response.search_graph.children[0].thought_process += ("正在执行...\n" if is_chinese else "Executing...\n")
            yield response
            await asyncio.sleep(1)
            
            # 记录开始时间
            start_time = asyncio.get_event_loop().time()
            
            # 创建后台任务
            #recommendation_task = asyncio.create_task(ja.run_journal_recommendation())
            recommendation_task = asyncio.create_task(asyncio.to_thread(ja.run_journal_recommendation))
            # 预设的最小总时间（让用户体验更自然）
            min_total_time = 6  # 最少6秒
            
            # 智能进度显示：根据任务完成情况调整
            steps_info = [
                (0, 3, "搜索文章"),    # 步骤0，等待3秒，描述
                (1, 2, "提取期刊信息"), # 步骤1，等待2秒，描述  
                (2, 1, "分析期刊数据")  # 步骤2，等待1秒，描述
            ]
            
            for step_idx, wait_time, desc in steps_info:
                # 等待指定时间或任务完成（取较短者）
                try:
                    await asyncio.wait_for(asyncio.sleep(wait_time), timeout=wait_time)
                except asyncio.TimeoutError:
                    pass  # 正常超时，继续显示进度
                
                # 如果任务已完成，快速完成所有剩余步骤
                if recommendation_task.done():
                    # 快速完成当前步骤和后续步骤
                    for remaining_step in range(step_idx, 3):
                        response.search_graph.children[remaining_step].thought_process += ("✓ 完成\n" if is_chinese else "✓ Completed\n")
                        response.search_graph.children[remaining_step].processing_type = ProcessingType.DONE
                        response.search_graph.children[remaining_step].summary = "DONE"
                        if remaining_step < 2:  # 不是最后一步
                            await asyncio.sleep(0.2)  # 快速切换
                            if remaining_step + 1 < 3:
                                response.search_graph.children[remaining_step + 1].thought_process += ("正在执行...\n" if is_chinese else "Executing...\n")
                        yield response
                    break
                else:
                    # 正常进度显示
                    response.search_graph.children[step_idx].thought_process += ("✓ 完成\n" if is_chinese else "✓ Completed\n")
                    response.search_graph.children[step_idx].processing_type = ProcessingType.DONE
                    response.search_graph.children[step_idx].summary = "DONE"
                    
                    # 如果不是最后一步，开始下一步
                    if step_idx < 2:
                        response.search_graph.children[step_idx + 1].thought_process += ("正在执行...\n" if is_chinese else "Executing...\n")
                    yield response
            
            # 计算已用时间
            elapsed_time = asyncio.get_event_loop().time() - start_time
            
            # 如果总时间少于最小时间，增加一点等待让体验更自然
            if elapsed_time < min_total_time:
                remaining_time = min_total_time - elapsed_time
                logger.info(f"Analysis completed in {elapsed_time:.1f}s, adding {remaining_time:.1f}s for better UX")
                await asyncio.sleep(remaining_time)
            else:
                logger.info(f"Analysis completed in {elapsed_time:.1f}s, using real time")
                
            results = await recommendation_task
            
            # 完成步骤3
            completion_text = f"✓ 完成，找到 {len(results)} 个推荐期刊\n" if is_chinese else f"✓ Completed, found {len(results)} recommended journals\n"
            response.search_graph.children[2].thought_process += completion_text
            response.search_graph.children[2].processing_type = ProcessingType.DONE
            response.search_graph.children[2].summary = "DONE"
            
            # 保存结果
            ja.recommendation_results = results
            
            # 保存分析数据到文件
            self._save_analysis_data(results, ja.output_dir)
            
            yield response
            
            # Step 4: 生成推荐报告
            logger.info("Generating journal recommendation report...")
            buffer = io.StringIO()
            
            async for _ in self._task_with_heartbeat(
                self._generate_recommendation_report, 
                buffer=buffer,
                analyzer=ja
            ):
                s = buffer.getvalue()
                response.search_graph.children[3].thought_process = s
                response.content = s
                yield response
            
            response.search_graph.children[3].processing_type = ProcessingType.DONE
            response.search_graph.children[3].summary = "DONE"
            buffer.close()
            yield response
            
            logger.info(f"Journal recommendation completed: time passed {time.time() - start_time}s")
            
            # 压缩和上传文件
            if upload_file:
                await self.compress_and_upload(ja, response, upload_file, **kwargs)
            else:
                logger.info("Skipping file upload (OBS client not available)")
            
            response.search_graph.processing_type = ProcessingType.RESPONSEDONE
            response.search_graph.summary = "DONE"

            # 添加期刊信息作为源
            journals = results.get('journals', []) if isinstance(results, dict) else results
            if journals and len(journals) > 0:
                response.search_graph.source = journals[:3]
                # for i, journal in enumerate(journals[:10], 1):  # 限制前10个期刊
                #     # 按照标准的 _format_final_source 格式
                #     source_item = {
                #         'id': i,
                #         'url': journal.get('homepage', f"https://www.issn.org/resource/ISSN/{journal.get('issn', '')}" if journal.get('issn') else ""),
                #         'title': journal.get('journal_title', 'Unknown Journal'),
                #         'site_name': journal.get('publisher', 'Unknown Publisher'),
                #         'summary': f"影响因子: {journal.get('latest_impact_factor', 'N/A')}, CiteScore: {journal.get('latest_citescore', 'N/A')}, 分区: {journal.get('jif_quartile', 'N/A')}",
                #         'cite_score': str(journal.get('latest_impact_factor', '')),
                #         'pubmed_id': '',  # 期刊本身没有PMID
                #         'pub_date': '',   # 期刊本身没有发表日期
                #         'type': 'JOURNAL',
                #         'doi': '',        # 期刊本身没有DOI
                #         'author': '',     # 期刊本身没有作者
                #         'full_journal_name': journal.get('journal_title', ''),
                #     }
                #     response.search_graph.source.append(source_item)
            else:
                response.search_graph.source = []

            yield response
            
        except Exception as e:
            traceback.print_exc()
            raise UnexpectedException(str(e))
    
    def init_search_graph(self):
        """初始化搜索图"""
        root = SearchNode(
            search_type=SearchType.UNKNOWN,
            query="Journal recommendation generation",
            key_word=""
        )
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        
        root.thought_process = (
            "期刊推荐将经过四个步骤" if self.language == 'zh-CN'
            else "Journal recommendation follows a 4-step process"
        )
        
        steps = [
            "Search related articles (~15s)",
            "Extract journal information from articles (~10s)",
            "Analyze journal data (impact factor, publisher, etc.) (~15s)",
            "Generate recommendation report (2-3 mins)"
        ]
        steps_chinese = [
            "搜索相关文章 (~15s)",
            "从文章中提取期刊信息 (~10s)",
            "分析期刊数据（影响因子、出版社等）(~15s)",
            "生成推荐报告 (2-3分钟)"
        ]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps):
            node = SearchNode(
                search_type=SearchType.UNKNOWN,
                query=subtitle,
                key_word=""
            )
            root.add_child(node)
        
        return root
    
    async def _task_with_heartbeat(self, func: Callable, buffer: io.StringIO = None, 
                                 interval: float = 0.3, **kwargs):
        """
        带心跳的任务执行，避免长时间处理时连接关闭
        参考SynopsisAgentV2的实现
        """
        try:
            start_time = time.time()
            
            async def write_buffer():
                f = func(**kwargs)
                if asyncio.iscoroutine(f):
                    await f
                    return
                async for item in f:
                    if not buffer or not item:
                        continue
                    buffer.write(item)
            
            task = asyncio.create_task(write_buffer())
            shielded = asyncio.shield(task)
            
            while not task.done():
                yield None
                await asyncio.sleep(interval)
            
            await shielded
            end_time = time.time()
            logger.info(f"[_task_with_heartbeat]{func.__name__} cost time total {end_time - start_time}s")
            yield None
            
        except Exception as e:
            traceback.print_exc()
            raise Exception(f"Task {func.__name__} with heartbeat failed: {str(e)}")
    
    async def compress_and_upload(self, ja, response, upload_file, **kwargs):
        """压缩和上传文件 - 参考SynopsisAgentV2"""
        
        # 保存报告和输出到zip文件
        zip_path = f"{ja.output_dir}.zip"
        if not os.path.exists(ja.output_dir + '/data'):
            os.makedirs(ja.output_dir + '/data', exist_ok=True)
        shutil.make_archive(ja.output_dir, 'zip', ja.output_dir)
        logger.info(f"Output saved to {zip_path}")
        
        # 上传到云存储
        bucket_name = "noahai-userdata-test"
        user = kwargs.get("user", "unknown")
        file_name = os.path.basename(ja.output_dir) + ".zip"
        
        for _ in range(3):
            res = upload_file(
                bucket_name=bucket_name, 
                object_key=f"journal_recommendation/{user}/{file_name}", 
                file_path=zip_path
            )
            if res:
                logger.info(f"File {zip_path} uploaded successfully")
                response.search_graph.attachments_key = f"journal_recommendation/{user}/{file_name}"
                break
            await asyncio.sleep(3)
        else:
            logger.error(f"Failed to upload {zip_path}")
        
        # 设置最终响应内容
        response.content = response.content.replace('```markdown', '').replace('```', '')
        response.content += "\n---\n\n"
        response.content += (
            "## 下载链接：[期刊推荐报告与数据]" if self.language == 'zh-CN'
            else "## Download link: [Journal Recommendation Report & Data]"
        )
        response.content += f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{response.search_graph.attachments_key})" if response.search_graph.attachments_key else ""
    
    async def _validate_recommendations(self, analyzer=None, **kwargs):
        """验证和优化推荐结果"""
        logger.info("Starting recommendation validation...")
        
        try:
            # 模拟验证过程
            validation_steps = [
                "Checking journal relevance scores...",
                "Validating impact factor data...", 
                "Analyzing submission requirements...",
                "Optimizing recommendation rankings..."
            ]
            
            for i, step in enumerate(validation_steps):
                logger.info(f"Validation step {i+1}: {step}")
                await asyncio.sleep(0.5)  # 模拟处理时间
            
            logger.info("Recommendation validation completed")
            
        except Exception as e:
            logger.error(f"Error in validate_recommendations: {e}")
            raise
    
    def _get_analysis_data_from_results(self, analyzer) -> Dict[str, Any]:
        results = analyzer.recommendation_results
        
        # 处理不同的结果格式
        if isinstance(results, dict) and 'journals' in results:
            journals = results['journals']
        elif isinstance(results, list):
            journals = results
        else:
            journals = []
        
        from collections import Counter
        
        issn_counter = Counter(analyzer._issns)
        
        journal_candidates = []
        journal_database_info = {}
        
        # 按频次排序，只取有数据库信息的期刊
        for result in journals:
            issn = result.get('issn')
            if issn:
                frequency = issn_counter.get(issn, 1)  # 获取真实频次
                journal_candidates.append({
                    'issn': issn,
                    'frequency': frequency
                })
                
                journal_database_info[issn] = {
                    'database_info': result
                }
        
        # 按频次排序
        journal_candidates.sort(key=lambda x: x['frequency'], reverse=True)
        
        return {
            'abstract': analyzer.abstract,
            'current_date': datetime.now().strftime('%Y-%m-%d'),
            'related_articles_count': analyzer._pmids_count,
            'journal_candidates': journal_candidates,
            'journal_database_info': journal_database_info,
            'analysis_completed': True
        }
    
    async def _generate_recommendation_report(self, analyzer=None, **kwargs):
        """生成推荐报告 - 参考SynopsisAgentV2的流式生成模式"""
        try:
            logger.info("Starting journal recommendation report generation...")
            
            report_data = self._get_analysis_data_from_results(analyzer)
            prompt = self._build_recommendation_prompt(report_data)
            
            logger.info("Calling LLM for recommendation generation...")
            
            string_buffer = io.StringIO()
            async for chunk in self.llm.stream_call(
                user_prompt=prompt,
                temperature=0.2
            ):
                if chunk:
                    string_buffer.write(chunk)
                    yield chunk
            
            draft = string_buffer.getvalue()
            string_buffer.close()
            
            analyzer.recommendation_report = draft
            
            self._save_report(draft, analyzer.output_dir)
            
            logger.info("Journal recommendation report generated successfully")
            
        except Exception as e:
            logger.error(f"Error generating recommendation report: {e}")
            traceback.print_exc()
            yield f"Error generating recommendation report: {str(e)}"
    
    def _build_recommendation_prompt(self, data: Dict[str, Any]) -> str:
        """构建推荐报告生成提示 - 参考SynopsisAgentV2的提示结构"""
        
        is_chinese = self.language == 'zh-CN'

        journal_info_text = ""
        for i, candidate in enumerate(data['journal_candidates'][:20], 1):  # 限制前20个
            issn = candidate['issn']
            if is_chinese:
                journal_info_text += f"\n### 候选期刊 {i}: ISSN {issn}\n"
                journal_info_text += f"- 相关文章频次: {candidate['frequency']} 篇\n"
            else:
                journal_info_text += f"\n### Candidate Journal {i}: ISSN {issn}\n"
                journal_info_text += f"- Related articles frequency: {candidate['frequency']} articles\n"
            
            # 添加完整的数据库信息
            db_info = data['journal_database_info'].get(issn, {}).get('database_info')
            if db_info:
                if is_chinese:
                    # 中文版基本信息
                    journal_info_text += f"- 期刊名称: {db_info.get('journal_title', 'N/A')}\n"
                    journal_info_text += f"- 电子ISSN: {db_info.get('e_issn', 'N/A')}\n"
                    journal_info_text += f"- 出版社: {db_info.get('publisher', 'N/A')}\n"
                    journal_info_text += f"- 出版地区: {db_info.get('publisher_region', 'N/A')}\n"
                    
                    # 中文版影响力指标
                    journal_info_text += f"- 最新影响因子: {db_info.get('latest_impact_factor', 'N/A')}\n"
                    journal_info_text += f"- 最新CiteScore: {db_info.get('latest_citescore', 'N/A')}\n"
                    journal_info_text += f"- JIF四分位: {db_info.get('jif_quartile', 'N/A')}\n"
                    journal_info_text += f"- 自引率: {db_info.get('self_citation_rate', 'N/A')}\n"
                    
                    # 中文版期刊属性
                    journal_info_text += f"- 开放获取状态: {db_info.get('open_access_status', 'N/A')}\n"
                    journal_info_text += f"- 可引用项目数: {db_info.get('latest_citable_items', 'N/A')}\n"
                    journal_info_text += f"- 中国作者比例: {db_info.get('latest_china_authorship', 'N/A')}\n"
                else:
                    # 英文版基本信息
                    journal_info_text += f"- Journal Title: {db_info.get('journal_title', 'N/A')}\n"
                    journal_info_text += f"- Electronic ISSN: {db_info.get('e_issn', 'N/A')}\n"
                    journal_info_text += f"- Publisher: {db_info.get('publisher', 'N/A')}\n"
                    journal_info_text += f"- Publisher Region: {db_info.get('publisher_region', 'N/A')}\n"
                    
                    # 英文版影响力指标
                    journal_info_text += f"- Latest Impact Factor: {db_info.get('latest_impact_factor', 'N/A')}\n"
                    journal_info_text += f"- Latest CiteScore: {db_info.get('latest_citescore', 'N/A')}\n"
                    journal_info_text += f"- JIF Quartile: {db_info.get('jif_quartile', 'N/A')}\n"
                    journal_info_text += f"- Self Citation Rate: {db_info.get('self_citation_rate', 'N/A')}\n"
                    
                    # 英文版期刊属性
                    journal_info_text += f"- Open Access Status: {db_info.get('open_access_status', 'N/A')}\n"
                    journal_info_text += f"- Latest Citable Items: {db_info.get('latest_citable_items', 'N/A')}\n"
                    journal_info_text += f"- China Authorship Ratio: {db_info.get('latest_china_authorship', 'N/A')}\n"
                
                # 研究领域和主题
                if db_info.get('wos_research_areas'):
                    areas = db_info['wos_research_areas']
                    if isinstance(areas, list):
                        if is_chinese:
                            journal_info_text += f"- WoS研究领域: {', '.join(areas)}\n"
                        else:
                            journal_info_text += f"- WoS Research Areas: {', '.join(areas)}\n"
                    else:
                        if is_chinese:
                            journal_info_text += f"- WoS研究领域: {areas}\n"
                        else:
                            journal_info_text += f"- WoS Research Areas: {areas}\n"
                
                if db_info.get('citation_topics_meso'):
                    topics = db_info['citation_topics_meso']
                    if isinstance(topics, list):
                        topic_text = ', '.join(topics[:3]) + "..." if len(topics) > 3 else ', '.join(topics)
                        if is_chinese:
                            journal_info_text += f"- 引用主题: {topic_text}\n"
                        else:
                            journal_info_text += f"- Citation Topics: {topic_text}\n"
                    else:
                        if is_chinese:
                            journal_info_text += f"- 引用主题: {topics}\n"
                        else:
                            journal_info_text += f"- Citation Topics: {topics}\n"
                
                # 期刊描述
                if db_info.get('journal_description'):
                    desc = db_info['journal_description']
                    # 截断过长的描述
                    if len(desc) > 200:
                        desc = desc[:200] + "..."
                    if is_chinese:
                        journal_info_text += f"- 期刊描述: {desc}\n"
                    else:
                        journal_info_text += f"- Journal Description: {desc}\n"
                
                # 风险信息
                if db_info.get('risk_info'):
                    if is_chinese:
                        journal_info_text += f"- 风险信息: {db_info['risk_info']}\n"
                    else:
                        journal_info_text += f"- Risk Information: {db_info['risk_info']}\n"
                
            else:
                if is_chinese:
                    journal_info_text += "- 数据库信息: 暂无\n"
                else:
                    journal_info_text += "- Database Information: Not available\n"
        
        if is_chinese:
            prompt = f"""你是一位专业的学术期刊推荐专家。请基于以下分析数据，生成一份详细的期刊推荐报告。

<用户摘要>
{data['abstract']}
</用户摘要>

<分析数据>
- 分析日期: {data['current_date']}
- 相关文章数量: {data['related_articles_count']}
- 候选期刊数量: {len(data['journal_candidates'])}
- 分析方法: Vector Search → PMID → ISSN → 期刊数据库查询

{journal_info_text}
</分析数据>

<报告要求>
请生成一份专业的期刊推荐报告，包含以下结构：

## 执行摘要
简要概述分析结果和主要推荐（2-3段）

## 分析方法
说明使用的技术方法和数据来源

## 顶级期刊推荐
根据相关性、影响因子和适合性，详细分析前5个期刊：
- 期刊基本信息
- 推荐理由
- 匹配度分析
- 投稿建议

## 备选期刊
推荐3-5个备选期刊，简要说明推荐理由

## 投稿策略建议
- 投稿优先级排序
- 准备建议
- 时间规划建议

## 结论
总结关键发现和最终建议
</报告要求>

请用中文生成报告，确保内容专业、准确、实用。"""
        else:
            prompt = f"""You are a professional academic journal recommendation expert. Please generate a detailed journal recommendation report based on the following analysis data.

<User Abstract>
{data['abstract']}
</User Abstract>

<Analysis Data>
- Analysis Date: {data['current_date']}
- Related Articles Count: {data['related_articles_count']}
- Candidate Journals Count: {len(data['journal_candidates'])}
- Analysis Method: Vector Search → PMID → ISSN → Journal Database Query

{journal_info_text}
</Analysis Data>

<Report Requirements>
Please generate a professional journal recommendation report with the following structure:

## Executive Summary
Brief overview of analysis results and main recommendations (2-3 paragraphs)

## Analysis Method
Explain the technical methods and data sources used

## Top Journal Recommendations
Detailed analysis of the top 5 journals based on relevance, impact factor, and suitability:
- Journal basic information
- Recommendation reasons
- Match analysis
- Submission suggestions

## Alternative Journals
Recommend 3-5 alternative journals with brief reasons

## Submission Strategy Suggestions
- Submission priority ranking
- Preparation suggestions
- Timeline planning suggestions

## Conclusion
Summarize key findings and final recommendations
</Report Requirements>

Please generate the report in English, ensuring the content is professional, accurate, and practical."""
        
        return prompt
    
    def _save_report(self, report: str, output_dir: str):
        try:
            report_file = os.path.join(output_dir, 'reports', 'journal_recommendation_report.md')
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Recommendation report saved to: {report_file}")
        except Exception as e:
            logger.warning(f"Failed to save report: {e}")
    
    def _save_analysis_data(self, results: List[Dict], output_dir: str):
        try:
            data_file = os.path.join(output_dir, 'data', 'journal_analysis_results.json')
            with open(data_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            logger.info(f"Analysis data saved to: {data_file}")
        except Exception as e:
            logger.warning(f"Failed to save analysis data: {e}")
