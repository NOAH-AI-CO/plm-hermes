from pydantic import BaseModel
from typing import List, Dict, Any
import logging
import time
import subprocess
import json
import os
import asyncio
import urllib.parse
from datetime import datetime, timedelta, timezone

from llm.base_model import BaseLLM
from agent.core.preset import AgentPreset
from llm.composite_models import JournalRecommendationModels
from agent.journal_recommendation.constants import JournalRecommendationTaskStatus
from agent.journal_recommendation.journal_recommendation_analyzer import JournalRecommendationAnalyzer
from agent.journal_recommendation.db import write_journal_recommendation_context

logger = logging.getLogger(__name__)

def _clean_similar_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理similar_article数据，只保留PDF和前端需要的字段
    """
    cleaned = {}
    if 'title' in article:
        cleaned['title'] = article['title']
    if 'pmid' in article:
        cleaned['pmid'] = article['pmid']
    if 'year_of_publication' in article:
        cleaned['year'] = article['year_of_publication']
    elif 'year' in article:
        cleaned['year'] = article['year']
    if 'authors' in article:
        cleaned['authors'] = article['authors']
    elif 'author' in article:
        cleaned['authors'] = article['author']
    if 'journal_title' in article:
        cleaned['journal_title'] = article['journal_title']
    elif 'journal' in article:
        cleaned['journal_title'] = article['journal']
    elif 'fulljournalname' in article:
        cleaned['journal_title'] = article['fulljournalname']

    display_parts = []
    
    authors = cleaned.get('authors', [])
    author_names = []
    
    if isinstance(authors, str):
        author_names = [a.strip() for a in authors.replace(';', ',').split(',') if a.strip()]
    elif isinstance(authors, list):
        for author in authors:
            if isinstance(author, dict):
                name = author.get('name', '')
                if name:
                    author_names.append(name)
            elif isinstance(author, str):
                author_names.append(author)
    
    if author_names:
        author_str = ', '.join(author_names[:3])
        original_authors = cleaned.get('authors', [])
        if isinstance(original_authors, list) and len(original_authors) > 3:
            author_str += ' et al.'
        display_parts.append(author_str)
    
    year = cleaned.get('year')
    if year:
        display_parts.append(str(year))
    
    title = cleaned.get('title', '')
    if title:
        truncated_title = title[:10] + ('...' if len(title) > 10 else '')
        display_parts.append(truncated_title)
    
    pmid = cleaned.get('pmid')
    if pmid:
        display_parts.append(f"PMID: {pmid}")
    
    cleaned['display'] = ' '.join(display_parts)

    cleaned['url'] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    
    return cleaned

def _clean_journal_for_output(journal: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理期刊数据，移除vector、embedding等不必要的大字段
    保留PDF生成和前端显示需要的字段
    """
    # 需要移除的字段列表
    remove_fields = [
        # 向量和嵌入字段（占用大量空间）
        "semantic_vector",
        "title_vector",
        "title_cn_vector",
        "title_en_vector",
        "description_vector",
        "embedding",
        "annual_citations",
        "annual_citable_items",
        "annual_impact_factors",
        "annual_impact_factors_5y",
        "annual_document_types",
        "journal_description",
        "journal_description_cn",
        # 内部临时字段
        "related_articles",  # 已转换为similar_articles
        "_publishability_score",
        "_raw_relevance",
        "_raw_academic",
        "_raw_publishability",
        # 搜索相关的临时字段
        "bm25_score",
        "vector_score",
        "bm25_rank",
        "vector_rank",
        "rrf_score",
        "hybrid_score",
    ]
    
    # 创建副本
    cleaned = journal.copy()
    
    # 移除显式指定的字段
    for field in remove_fields:
        cleaned.pop(field, None)
    
    # 移除所有包含vector、embedding的字段（不区分大小写）
    keys_to_remove = []
    for key in cleaned.keys():
        key_lower = key.lower()
        if 'vector' in key_lower or 'embedding' in key_lower or key_lower.endswith('_vec'):
            keys_to_remove.append(key)
    
    for key in keys_to_remove:
        cleaned.pop(key, None)
    
    # 清理similar_articles数组
    if 'similar_articles' in cleaned and isinstance(cleaned['similar_articles'], list):
        cleaned['similar_articles'] = [
            _clean_similar_article(article) 
            for article in cleaned['similar_articles']
        ]
    
    return cleaned

class JournalRecommendationContext(BaseModel):
    abstract_id: int = 0
    processing_status: str = ""
    content: Dict[str, Any] = {}
    abstract: str = ""
    abstract_summary: str = ""
    url: str = ""  # download url
    progress: int = 0
    status: str = ""
    language: str = "zh-CN"
    journals: List[dict] = []
    error_message: str = ""
    total_journals: int = 0
    stats: Dict[str, Any] = {}
    query_params: Dict[str, Any] = {}  # 期刊筛选条件


class JournalRecommendationAgentV2(AgentPreset):
    llm: BaseLLM = JournalRecommendationModels()
    journal_requests: List[dict] = []
    cache_key: str = ""
    output_dir: str = ""

    def __init__(self, **kwargs):
        super().__init__()
        self.journal_requests = kwargs.get("journal_requests", [])
        self.cache_key = kwargs.get("cache_key", "default_journal_recommendation_agent_v2_lock_key")
        self.output_dir = kwargs.get("output_dir", f"outputs/journal_recommendation_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

    async def use_tool(self, language="zh-CN", years_hot=None, top_k=200, size=10, **kwargs):
        # 设置默认值
        if years_hot is None:
            years_hot = [2021, 2022, 2023, 2024, 2025]
        
        if language in ['zh']:
            language = 'zh-CN'

        for request in self.journal_requests:
            ctx = await self._process_single_request(
                request, 
                default_language=language,
                default_years_hot=years_hot,
                default_top_k=top_k,
                default_size=size
            )
            yield ctx
    
    async def _process_single_request(
        self, 
        request: dict,
        default_language: str = "zh-CN",
        default_years_hot: List[int] = None,
        default_top_k: int = 200,
        default_size: int = 20
    ) -> JournalRecommendationContext:
        if default_years_hot is None:
            default_years_hot = [2021, 2022, 2023, 2024, 2025]
            
        ctx = JournalRecommendationContext()
        ctx.abstract_id = request.get("abstract_id", 0)
        ctx.abstract = request.get("abstract", "")
        
        language = request.get("language", default_language).lower()
        if language in ['zh']:
            language = 'zh-CN'
        ctx.language = language
        ctx.status = JournalRecommendationTaskStatus.RUNNING
        
        years_hot = request.get('years_hot', default_years_hot)
        top_k = request.get('top_k', default_top_k)
        size = request.get('size', default_size)
        
        # 提取筛选参数
        query_params = request.get('query_params', {})
        
        # 保存用户筛选参数到 context
        ctx.query_params = query_params
        
        logger.info(f"Processing request for abstract_id={ctx.abstract_id} with params: "
                   f"language={language}, years_hot={years_hot}, top_k={top_k}, "
                   f"size={size}, query_params={query_params}")
        
        if not ctx.abstract or len(ctx.abstract.strip()) < 20:
            ctx.status = JournalRecommendationTaskStatus.ERROR
            ctx.error_message = "摘要内容过短或为空" if ctx.language == "zh-CN" else "Abstract is too short or empty"
            ctx.processing_status = ctx.error_message
            await write_journal_recommendation_context(ctx)
            logger.error(f"Abstract validation failed: {ctx.error_message}")
            return ctx
        
        try:
            # 步骤 1/4: 分析摘要（初始化、翻译、总结、提取关键词）
            ctx.processing_status = "正在分析摘要..." if ctx.language == "zh-CN" else "Analyzing abstract..."
            ctx.progress = 25
            await write_journal_recommendation_context(ctx)
            logger.info(f"Starting journal recommendation for abstract_id={ctx.abstract_id}")
            
            analyzer = JournalRecommendationAnalyzer(
                abstract=ctx.abstract,
                query_params=query_params,
                years_hot=years_hot,
                top_k=top_k,
                size=size,
                output_dir=self.output_dir
            )
            
            await analyzer.translate_abstract()
            abstract_summary = await analyzer.summarize_abstract()
            logger.info(f"Generated summary: {abstract_summary}")
            keywords_cn, keywords_en = await analyzer.extract_keywords_from_abstract()
            logger.info(f"Generated keywords: CN={keywords_cn}, EN={keywords_en}")
            analyzer.abstract_summary = abstract_summary
            
            # 提取研究类型
            await analyzer.infer_abstract_research_type()
            logger.info(f"Inferred research type: {analyzer.abstract_research_type}")
            
            # 步骤 2/4: 搜索相关文章
            ctx.processing_status = "正在搜索相关文章..." if ctx.language == "zh-CN" else "Searching related articles..."
            ctx.progress = 50
            await write_journal_recommendation_context(ctx)
            logger.info("Searching for related articles")
            
            search_results = await analyzer.search_related_articles()
            articles = search_results.get("articles", [])
            logger.info(f"The top 5 articles: {articles[:5]}")
            ctx.stats = search_results.get("stats", {})
            logger.info(f"Found {len(articles)} related articles")
            
            # 步骤 3/4: 推荐期刊
            ctx.processing_status = "正在推荐期刊..." if ctx.language == "zh-CN" else "Recommending journals..."
            ctx.progress = 75
            await write_journal_recommendation_context(ctx)
            logger.info("Running journal recommendation")
            
            recommended_journals = await analyzer.run_journal_recommendation(search_results=search_results)
            
            if not recommended_journals:
                logger.warning(f"run_journal_recommendation返回空列表!")
                logger.warning(f"search_results articles数量: {len(search_results.get('articles', []))}")
                logger.warning(f"search_results pmids数量: {len(search_results.get('pmids', []))}")
                # 不抛出错误，继续执行，但PDF会为空
            
            cleaned_journals = []
            if recommended_journals:
                original_keys_count = len(recommended_journals[0].keys()) if recommended_journals else 0
                for journal in recommended_journals:
                    cleaned_journal = _clean_journal_for_output(journal)
                    cleaned_journals.append(cleaned_journal)
                cleaned_keys_count = len(cleaned_journals[0].keys()) if cleaned_journals else 0
                logger.info(f"期刊数据清理完成: 原始字段数={original_keys_count}, 清理后字段数={cleaned_keys_count}, 移除字段数={original_keys_count - cleaned_keys_count}")
            
            # 更新 context（使用清理后的数据）
            ctx.journals = cleaned_journals
            ctx.total_journals = len(cleaned_journals)
            ctx.stats.update({
                "recommended_count": len(cleaned_journals)
            })
            ctx.abstract_summary = abstract_summary
            
            keywords_str = ", ".join(keywords_cn) if keywords_cn else ", ".join(keywords_en) if keywords_en else ""

            ctx.content = {
                "abstract_id": ctx.abstract_id,
                "abstract": ctx.abstract,  
                "abstract_summary": abstract_summary,
                "keywords_cn": keywords_cn,
                "keywords_en": keywords_en,
                "keywords": keywords_str,  
                "total_journals": ctx.total_journals,
                "stats": ctx.stats,
                "top_journals": cleaned_journals,
            }
            logger.info(f"the top 3 journals: {cleaned_journals[:3]}")

            
            # 步骤 4/5: 生成报告并上传
            ctx.processing_status = "正在生成报告..." if ctx.language == "zh-CN" else "Generating report..."
            ctx.progress = 90
            await write_journal_recommendation_context(ctx)
            logger.info("Generating and uploading report files")
            
            # 完成
            abstract_id = ctx.abstract_id
            upload_result_dir = f"outputs/journal_recommendation_{abstract_id}_{int(time.time())}"
            await upload_result(upload_result_dir, ctx=ctx)
            ctx.processing_status = f"完成！找到 {ctx.total_journals} 个推荐期刊" if ctx.language == "zh-CN" else f"Completed! Found {ctx.total_journals} recommended journals"
            ctx.progress = 100
            ctx.status = JournalRecommendationTaskStatus.SUCCESS
            await write_journal_recommendation_context(ctx)
            logger.info(
                f"Journal recommendation completed successfully: "
                f"abstract_id={ctx.abstract_id}, journals={ctx.total_journals}, "
                f"stats={ctx.stats}, download_url={ctx.url}"
            )
            
        except Exception as e:
            ctx.status = JournalRecommendationTaskStatus.ERROR
            ctx.error_message = str(e)
            ctx.processing_status = f"错误: {str(e)}" if ctx.language == "zh-CN" else f"Error: {str(e)}"
            await write_journal_recommendation_context(ctx)
            logger.error(f"Journal recommendation failed: {str(e)}", exc_info=True)
        
        return ctx

def generate_report_with_node(content: Dict[str, Any], output_pdf_path: str) -> str:
    try:
        # 获取当前脚本所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 指向 generatePdf.js 的绝对路径
        node_script_path = os.path.join(current_dir, "generatePdf.js")
        abs_output_path = os.path.abspath(output_pdf_path)
        
        proc = subprocess.Popen(
            ["node", node_script_path, abs_output_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=current_dir  # 确保在脚本所在目录运行，以便找到 report.hbs
        )

        input_json = json.dumps(content, ensure_ascii=False)
        stdout, stderr = proc.communicate(input=input_json)
        print(stdout)
        return output_pdf_path

    except Exception as e:
        raise RuntimeError(f"PDF生成出错：{str(e)}")

async def upload_result(output_dir, ctx):
    from utils.azure.blob_client import upload_file
    
    datetime_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d%H%M")
    title_str = "期刊推荐报告"
    file_name_base = f"{title_str}-{datetime_str}"
    file_name = f"{output_dir}/{file_name_base}"
    
    content = ctx.content
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    pdf_path = f"{file_name}.pdf"
    logger.info(f"Generating PDF report at: {pdf_path}")
    
    try:
        generate_report_with_node(content, pdf_path)
    except Exception as e:
        logger.error(f"Failed to generate report: {str(e)}")
    
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found after generation: {pdf_path}")
        return

    # 上传到 Azure
    object_key = f"{file_name}.pdf"
    for attempt in range(3):
        try:
            logger.info(f"Uploading PDF to Azure (attempt {attempt + 1}): {object_key}")
            res = upload_file(bucket="", object_key=object_key, file_path=pdf_path)
            if res: 
                logger.info(f"File {pdf_path} uploaded successfully")
                # URL
                encoded_key = urllib.parse.quote(object_key)
                ctx.url = f"https://noahdata.blob.core.windows.net/nudata/{encoded_key}"
                logger.info(f"Set download URL: {ctx.url}")
                break
        except Exception as e:
            logger.error(f"Upload attempt {attempt + 1} failed: {str(e)}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))
    else:
        logger.error(f"Failed to upload {pdf_path} after 3 attempts")

    # PDF文件保留在本地，不会被删除（删除逻辑已注释）
    logger.info(f"PDF文件已保存在本地，可以查看: {os.path.abspath(pdf_path)}")

    # 清理临时文件
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            logger.info(f"Successfully deleted the temporary pdf file: {pdf_path}")
        except Exception as delete_error:
            logger.warning(f"Failed to delete temporary file {pdf_path}: {str(delete_error)}")

