import os
import json
import shutil
import asyncio
import io
import re
import logging
import time
import traceback
import tempfile
import aiohttp
from datetime import datetime
from typing import Any, Callable, List, Type, Dict

from agent.core.preset import AgentPreset
from llm.azure_models import GPT4o
from llm.base_model import BaseLLM
from llm.gcp_models import Gemini25Flash
from llm.composite_models import NSFCWritingModels
from agent.explore.helper import MindSearchHelper
from agent.nsfc.nsfc_prep_analyzer import NSFCPrepAnalyzer
from agent.nsfc.nsfc_docs_analyzer import NSFCDocsAnalyzer
from agent.nsfc.lite_llm_adapter import LiteLLMAdapter
from utils.utils.attachment import AttachmentManager

logger = logging.getLogger(__name__)

# Citation generation helper functions
def generate_pubmed_citation(rec: dict, idx: int) -> dict:
    """为PubMed文献生成简单的citation"""
    authors = rec.get('author', '') or rec.get('authors', '')
    if isinstance(authors, list):
        authors = ', '.join(authors[:3])  # 只取前3个作者
        if len(rec.get('authors', [])) > 3:
            authors += ' et al'
    
    year = str(rec.get('year_of_publication', '') or rec.get('pubdate', ''))
    title = rec.get('title', '未命名文献')
    journal = rec.get('journal', '') or rec.get('fulljournalname', '')
    pmid = rec.get('pmid', '')
    doi = rec.get('doi', '')
    
    # Vancouver风格的文本格式
    txt = f"{authors}. {title}. {journal}. {year}."
    if pmid:
        txt += f" PMID: {pmid}."
    if doi:
        txt += f" doi: {doi}."
    
    # BibTeX格式
    author_bib = authors.replace(' et al', ' and others')
    bib = f"""@article{{pubmed{idx},
  author = {{{author_bib}}},
  title = {{{title}}},
  journal = {{{journal}}},
  year = {{{year}}},
  pmid = {{{pmid}}},
  doi = {{{doi}}}
}}"""
    
    return {"txt": txt.strip(), "bib": bib}


def generate_nsfc_citation(proj: dict, idx: int) -> dict:
    """为NSFC项目生成简单的citation"""
    author = proj.get('projectAdmin', '')
    year = str(proj.get('researchTimeStart', '')).split('-')[0] if proj.get('researchTimeStart') else ''
    title = proj.get('projectName', '未命名项目')
    ratify_no = proj.get('ratifyNo', '')
    unit = proj.get('dependUnit', '')
    
    # Vancouver风格的文本格式
    txt = f"{author}. {title}. 国家自然科学基金. {year}."
    if ratify_no:
        txt += f" 批准号: {ratify_no}."
    if unit:
        txt += f" {unit}."
    
    # BibTeX格式
    note_parts = []
    if ratify_no:
        note_parts.append(f"批准号: {ratify_no}")
    if unit:
        note_parts.append(unit)
    note = ', '.join(note_parts)
    
    bib = f"""@misc{{nsfc{idx},
  author = {{{author}}},
  title = {{{title}}},
  year = {{{year}}},
  howpublished = {{国家自然科学基金委员会}},
  note = {{{note}}}
}}"""
    
    return {"txt": txt.strip(), "bib": bib}

def generate_pubmed_citation(rec: dict, idx: int) -> dict:
    authors = rec.get('author', '') or rec.get('authors', '')
    if isinstance(authors, list):
        cleaned_authors = []
        for author in authors[:3]:
            if isinstance(author, dict):
                name = author.get('name') or author.get('full_name') or author.get('last_name') or ""
                name = str(name).strip()
                if name:
                    cleaned_authors.append(name)
            else:
                name = str(author).strip()
                if name:
                    cleaned_authors.append(name)
        authors = ', '.join(cleaned_authors)  # 只取前3个作者
        if len(rec.get('authors', [])) > 3:
            authors += ' et al'
    
    year = str(rec.get('year_of_publication', '') or rec.get('pubdate', ''))
    title = rec.get('title', '未命名文献')
    journal = rec.get('journal', '') or rec.get('fulljournalname', '')
    pmid = rec.get('pmid', '')
    doi = rec.get('doi', '')
    
    txt = f"{authors}. {title}. {journal}. {year}."
    if pmid:
        txt += f" PMID: {pmid}."
    if doi:
        txt += f" doi: {doi}."
    
    author_bib = authors.replace(' et al', ' and others')
    bib = f"""@article{{pubmed{idx},
  author = {{{author_bib}}},
  title = {{{title}}},
  journal = {{{journal}}},
  year = {{{year}}},
  pmid = {{{pmid}}},
  doi = {{{doi}}}
}}"""
    
    return {"txt": txt.strip(), "bib": bib}


class NSFCAgent(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    prep_analyzer_class: Type[NSFCPrepAnalyzer] = NSFCPrepAnalyzer
    nsfc_prep_analyzer: NSFCPrepAnalyzer = None
    docs_analyzer_class: Type[NSFCDocsAnalyzer] = NSFCDocsAnalyzer
    nsfc_docs_analyzer: NSFCDocsAnalyzer = None
    language: str = "zh-CN"
    test: bool = False
    query_mode: bool = False
    query_params: dict = {}
    summarized_docs: List[Dict[str, Any]] = []  # 初始化用户文档摘要列表
    nsfc_project_preview: str = ""
    nsfc_proposal_outline: List[Dict] = []
    nsfc_project_blueprints: List[Dict] = []  # 添加缺失的字段声明
    attachment_manager: AttachmentManager = AttachmentManager()
    
    def __init__(self, query_params={}, query_mode=False, gemini_mode=False, model=None, **kwargs):
        super().__init__()

        print(kwargs)

        params = kwargs.get('params', {})
        from i18n.languages import normalize as _norm
        self.language = _norm(params.get('language', ''))

        query_params.update(params.get('raw_data', {}))
        title = query_params.get("user_title", "") or ""
        query  = query_params.get("user_query", "") or ""
        if title or query:
            query_params["user_input"] = f"{title}\n\n{query}".strip()
        else:
            query_params["user_input"] = kwargs.get('user_prompt', '')

        self.query_params = query_params
        logger.info(f"Nsfc writing query_params {query_params}")
            
        if 'test' in kwargs and type(kwargs['test']) == bool:
            self.test = kwargs.pop('test',False)
  
        output_dir = f"outputs/nsfc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.query_mode = query_mode

        # 允许传入自定义模型
        # 默认使用 lite_llm 的 AliyunQwen3Max（固定配置，不受外部影响）
        if model is None:
            try:
                from lite_llm.aliyun_models import AliyunQwen3Max
                model = AliyunQwen3Max()
                logger.info("使用默认模型: AliyunQwen3Max (lite_llm)")
            except Exception as e:
                logger.warning(f"lite_llm AliyunQwen3Max 加载失败: {e}，降级使用传统模型")
                model = Gemini25Flash() if gemini_mode else NSFCWritingModels()
        
        use_lite_llm = hasattr(model, 'stream_generate') and not hasattr(model, 'generate_stream')
        
        if use_lite_llm:
            logger.info(f"检测到 lite_llm 模型: {model.__class__.__name__}，使用适配器")
            adapted_model = LiteLLMAdapter(model)
            json_model = GPT4o()
            logger.info(f"主模型: {adapted_model}, JSON模型: {json_model.__class__.__name__}")
        else:
            adapted_model = model
            json_model = model
            logger.info(f"使用传统 llm 模型: {model.__class__.__name__}")
        
        self.nsfc_prep_analyzer = self.prep_analyzer_class(
            model=adapted_model, 
            query_params=query_params, 
            language=self.language,
            json_model=json_model  # 传入 JSON 专用模型
        )
        self.nsfc_prep_analyzer.set_output_dir(output_dir)
        self.nsfc_docs_analyzer = self.docs_analyzer_class(model=adapted_model, language=self.language)
        
    async def run_func(self, func: Callable, buffer: io.StringIO):
        async_generator = func()
        try:
            async for item in async_generator:
                buffer.write(item)
        except Exception as e:
            logger.error(f"run_func failed: {str(e)}")
            raise e

    async def use_tool(self, user_prompt: str = "", **kwargs):
        params = kwargs.get('params', {})
        files = await self.get_raw_files(params.get('files', {}))

        # 工具名称映射表（支持中英文）
        tool_names = {
            'query_analysis': {
                'zh-CN': '步骤 1：写作意图分析',
                'en-US': 'Step 1: Writing Intent Analysis',
            },
            'nsfc_search': {
                'zh-CN': '步骤 2：NSFC项目检索',
                'en-US': 'Step 2: NSFC Project Search',
            },
            'nsfc_landscape': {
                'zh-CN': '步骤 3：NSFC整体格局分析',
                'en-US': 'Step 3: NSFC Landscape Analysis',
            },
            'nsfc_pathway': {
                'zh-CN': '步骤 4：NSFC研究路径分析',
                'en-US': 'Step 4: NSFC Pathway Analysis',
            },
            'nsfc_gap': {
                'zh-CN': '步骤 5：NSFC研究空白分析',
                'en-US': 'Step 5: NSFC Gap Analysis',
            },
            'pubmed_search': {
                'zh-CN': '步骤 6：PubMed文献检索',
                'en-US': 'Step 6: PubMed Search',
            },
            'pubmed_analysis': {
                'zh-CN': '步骤 7：PubMed文献分析',
                'en-US': 'Step 7: PubMed Literature Analysis',
            },
            'blueprint': {
                'zh-CN': '步骤 8：候选题目方案生成',
                'en-US': 'Step 8: Blueprint Generation',
            },
            'outline': {
                'zh-CN': '步骤 9：申请书大纲生成',
                'en-US': 'Step 9: Outline Generation',
            },
            'lixiang_yiju': {
                'zh-CN': '步骤 10：立项依据撰写',
                'en-US': 'Step 10: Lixiang Yiju Writing',
            },
            'lixiang_other': {
                'zh-CN': '步骤 11：立项依据后续章节撰写',
                'en-US': 'Step 11: Lixiang Yiju Extended Writing',
            },
            'research_basis': {
                'zh-CN': '步骤 12：研究基础撰写',
                'en-US': 'Step 12: Research Basis Writing',
            },
            'other_notes': {
                'zh-CN': '步骤 13：其他说明撰写',
                'en-US': 'Step 13: Other Notes Writing',
            },
        }

        def get_tool_name(key: str) -> str:
            return tool_names.get(key, {}).get(self.language, tool_names.get(key, {}).get('zh-CN', 'Unknown'))

        # 解析并处理用户文档
        docs_task = None
        if files:
            docs_task = asyncio.create_task(self._process_user_docs(files))
            logger.info(f"已启动后台文档解析任务，共 {len(files)} 个文件")

        sa = self.nsfc_prep_analyzer
        
        summary = ''
        content = ''
        steps = 0
        started_at = int(time.time())
        plan_updates = []
        def stream_response(save: bool = False, tool_name: str = 'Writing-Preparation', reference: list = None):
            nonlocal summary, content, steps, started_at, plan_updates
            if steps >= len(plan_updates):
                plan_updates.append({
                    'id': f'step_{steps}',
                    'reason': summary,
                    'startedAt': started_at,
                    'status': 'done' if save else 'todo',
                    'tool': tool_name
                })
            else:
                plan_updates[-1]['reason'] = summary
                plan_updates[-1]['status'] = 'done' if save else 'todo'
                plan_updates[-1]['tool'] = tool_name
            for rsp in self.event_formatter(summary, content, steps, started_at, plan_updates, save=save, reference=reference):
                yield rsp
            if save:
                steps = steps + 1
                started_at = int(time.time())
                summary = ''
                content = ''
        
        summary = "正在解析您的写作意图并提炼关键信息..."
        for rsp in stream_response(tool_name=get_tool_name('query_analysis')):
            logger.info(f"get first resposne {rsp}")
            yield rsp
            await asyncio.sleep(0)
            
        await sa.translate_user_input()
        logger.info(f"翻译完成: CN={sa.query_params.get('user_input_cn', '')}, EN={sa.query_params.get('user_input_en', '')}")
        await sa.extract_and_expand_keywords()
        logger.info(f"关键词提取及扩写完成: {len(sa.query_params.get('keywords', []))} 个关键词")
        summary = f"写作意图解析完成（提取 {len(sa.query_params.get('keywords', []))} 个关键词）"
        content = ("## 写作意图解析已完成\n\n"
                            f"- 根据您的描述，系统提炼出的核心主题/关键词：{', '.join(sa.query_params.get('keywords', []))}\n")
        for rsp in stream_response(True, tool_name=get_tool_name('query_analysis')):
            yield rsp
            await asyncio.sleep(0)
        
        summary = "正在根据您的研究主题检索相关国自然基金资助项目..."
        for rsp in stream_response(tool_name=get_tool_name('nsfc_search')):
            yield rsp
            await asyncio.sleep(0)

        project_count = 0
        nsfc_reference = []
        # 国自然项目检索
        try:
            nsfc_projects = sa.run_search_nsfc(start_year=2019, end_year=2024, top_k=50)
            project_count = len(nsfc_projects)
            logger.info(f"相关基金项目已检索完成，共 {project_count} 项")
            projects_preview = self._build_nsfc_preview(nsfc_projects, max_items=5)
            content = projects_preview
            
            # 构建 NSFC reference 数据（取前20个用于展示）
            for idx, proj in enumerate(nsfc_projects[:20], start=1):
                project_id = proj.get('_id', '')
                ratify_no = proj.get('ratifyNo', '')
                
                # 生成citation
                citation = generate_nsfc_citation(proj, idx)
                
                nsfc_reference.append({
                    # 必须字段
                    'id': idx,
                    'title': proj.get('projectName', '未命名项目'),
                    'url': f"https://test.roche.noahai.co/tool/nsfc/{project_id}" if project_id else "",
                    # 推荐字段
                    'author': proj.get('projectAdmin', ''),
                    'pub_date': str(proj.get('researchTimeStart', '')).split('-')[0] if proj.get('researchTimeStart') else '',
                    'site_name': '国家自然科学基金委',
                    'type': 'nsfc',
                    'summary': (proj.get('projectAbstractC', '') or '')[:200],
                    # NSFC 特有字段
                    'ratify_no': ratify_no,
                    'unit': proj.get('dependUnit', ''),
                    'project_type': proj.get('type', ''),
                    'code': proj.get('code', ''),
                    # Citation 字段
                    'citation': citation,
                })
        except Exception as e:
            logger.warning(f"NSFC检索失败: {e}")
        summary = (
            f"相关基金项目检索完成（共 {project_count} 项）" if project_count else "未检索到相关国自然基金项目"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('nsfc_search'), reference=nsfc_reference if nsfc_reference else None):
            yield rsp
            await asyncio.sleep(0)

        nsfc_statistics = sa.prepare_nsfc_projects_statistics(score_threshold=15.0)
        nsfc_statistics_json = json.dumps(nsfc_statistics, ensure_ascii=False, indent=2)
        nsfc_sample_projects = sa.prepare_related_nsfc_projects(max_projects_for_llm=30)
        nsfc_sample_projects_json = json.dumps(nsfc_sample_projects, ensure_ascii=False, indent=2)

        # 国自然项目分析
        summary = "正在分析该方向国自然基金项目的整体研究格局..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('nsfc_landscape')):
            last_chunk = rsp
            yield rsp
            await asyncio.sleep(0)

        nsfc_overview = ""
        try:
            async for item in sa.generate_nsfc_overview_insights(nsfc_statistics_json, nsfc_sample_projects_json, last_chunk):
                nsfc_overview = item['message']
                yield item
            content = "## 相关基金项目分布\n\n"
            content += nsfc_overview
        except Exception as e:
            logger.warning(f"国自然项目整体研究格局分析失败: {e}")     
        summary = (
            "国自然项目整体研究格局分析完成" if nsfc_overview else "国自然项目整体研究格局分析失败"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('nsfc_landscape')):
            yield rsp
            await asyncio.sleep(0)
        
        summary = "正在分析该方向国自然基金项目的重点研究路径..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('nsfc_pathway')):
            yield rsp
            await asyncio.sleep(0)

        nsfc_mechanism = ""
        try:
            async for item in sa.generate_nsfc_mechanism_insights(nsfc_statistics_json, nsfc_sample_projects_json, last_chunk):
                nsfc_mechanism = item['message']
                yield item
            content = "## 相关基金项目重点研究路径\n\n"
            content += nsfc_mechanism
        except Exception as e:
            logger.warning(f"国自然项目重点研究路径失败: {e}")
        summary = (
            "国自然项目重点研究路径分析完成" if nsfc_mechanism else "国自然项目重点研究路径分析失败"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('nsfc_pathway')):
            yield rsp
            await asyncio.sleep(0)
        
        summary = "正在分析该方向国自然基金项目的研究空白与机会..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('nsfc_gap')):
            last_chunk = rsp
            yield rsp
            await asyncio.sleep(0)

        nsfc_gap = ""
        try:
            async for item in sa.generate_nsfc_insights(nsfc_statistics_json, nsfc_sample_projects_json, nsfc_overview, nsfc_mechanism, last_chunk):
                nsfc_gap = item['message']
                yield item
            content = "## 相关基金项目研究空白与机会\n\n"
            content += nsfc_gap
        except Exception as e:
            logger.warning(f"国自然项目研究空白与机会分析失败: {e}")
            # 确保属性初始化
            if not hasattr(sa, 'nsfc_insights') or not sa.nsfc_insights:
                sa.nsfc_insights = "国自然项目分析暂时不可用"
        summary = (
            "国自然项目研究空白分析完成" if nsfc_gap else "国自然项目研究空白分析失败"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('nsfc_gap')):
            yield rsp
            await asyncio.sleep(0)

        # PubMed检索
        summary = "正在根据您的研究主题检索相关PubMed文献..."
        for rsp in stream_response(tool_name=get_tool_name('pubmed_search')):
            yield rsp
            await asyncio.sleep(0)
        pubmed_records = []
        pubmed_reference = []
        try:
            pubmed_records = await sa.run_search_pubmed_by_keywords(search_years=[2020, 2021, 2022, 2023, 2024, 2025], top_k=50)
            logger.info(f"PubMed检索完成: {len(pubmed_records)} 篇文献")
            pubmed_preview = self._build_pubmed_preview(pubmed_records, max_items=5)
            content = pubmed_preview
            
            # 构建 PubMed reference 数据（取前20个用于展示）
            for idx, rec in enumerate(pubmed_records[:20], start=1):
                pmid = rec.get('pmid', '')
                
                # 生成citation
                citation = generate_pubmed_citation(rec, idx)
                
                pubmed_reference.append({
                    # 必须字段
                    'id': idx,
                    'title': rec.get('title', '未命名文献'),
                    'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    # 推荐字段
                    #'author': rec.get('authors', '') or rec.get('author', ''),
                    'pub_date': str(rec.get('year_of_publication', '') or rec.get('pubdate', '')),
                    'site_name': 'PubMed',
                    'type': 'pubmed',
                    'summary': (rec.get('abstract', '') or rec.get('summary', ''))[:200],
                    # PubMed 特有字段
                    'pubmed_id': pmid,
                    'doi': rec.get('doi', ''),
                    'full_journal_name': rec.get('journal', '') or rec.get('fulljournalname', ''),
                    'pmc': rec.get('pmc', ''),
                    # Citation 字段
                    'citation': citation,
                })
        except Exception as e:
            logger.warning(f"PubMed检索失败: {e}")
        summary = (
            f"PubMed 检索完成（共 {len(pubmed_records)} 篇）" if pubmed_records else "未检索到相关 PubMed 文献"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('pubmed_search'), reference=pubmed_reference if pubmed_reference else None):
            yield rsp
            await asyncio.sleep(0)

        # PubMed文献分析
        summary = "正在分析该方向PubMed文献的整体研究格局..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('pubmed_analysis')):
            last_chunk = rsp
            yield rsp
            await asyncio.sleep(0)
        if pubmed_records:
            pubmed_overview = ""
            try:
                async for item in sa.generate_pubmed_overview_insights(pubmed_records, last_chunk):
                    pubmed_overview = item['message']
                    yield item
                content = "## PubMed文献分析\n\n"
                content += pubmed_overview
            except Exception as e:
                logger.warning(f"PubMed文献整体研究格局分析失败: {e}")
                if not hasattr(sa, 'pubmed_insights'):
                    sa.pubmed_insights = "PubMed文献分析暂时不可用"
        else:
            sa.pubmed_insights = "未检索到PubMed文献"
        summary = (
            "PubMed 文献整体分析完成" if pubmed_records else "PubMed 文献整体分析跳过（无文献）"
        )
        for rsp in stream_response(True, tool_name=get_tool_name('pubmed_analysis')):
            yield rsp
            await asyncio.sleep(0)
        
        if docs_task is not None:
            try:
                await docs_task
                logger.info("用户文档解析任务已完成")
                # 将summarized_docs列表转换为字符串摘要供prompt使用
                if self.summarized_docs:
                    # 将文档列表格式化为简短摘要字符串
                    brief_parts = []
                    for idx, doc in enumerate(self.summarized_docs[:5], 1):  # 最多取前5个文档
                        name = doc.get('name', f'文档{idx}')
                        summary = doc.get('summary', '')
                        if summary:
                            # 限制每个摘要长度
                            summary_brief = summary[:300] + ('...' if len(summary) > 300 else '')
                            brief_parts.append(f"{idx}. {name}\n   {summary_brief}")
                    sa.summarized_docs = "\n\n".join(brief_parts) if brief_parts else "用户提供了文档但摘要为空"
                else:
                    sa.summarized_docs = "用户未提供前期研究基础文档"
            except Exception as e:
                logger.warning(f"用户文档解析失败: {e}")
                sa.summarized_docs = "用户未提供前期研究基础文档"
        else:
            # 没有提供文档时
            sa.summarized_docs = "用户未提供前期研究基础文档"
            

        summary = "正在为您构思候选题目及研究方案…"
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('blueprint')):
            last_chunk = rsp
            await asyncio.sleep(0)
            yield rsp

        num_blueprints = 3

        blueprints_json_text = ""
        blueprints: list[dict] = []
        last_preview = ""
        content = ""
        
        try:
            blueprints = await sa.generate_nsfc_project_blueprints(
                summarized_docs=self.summarized_docs,  
                num_blueprints=num_blueprints,
                temperature=0.5,
            )

            final_blueprints = sa.nsfc_project_blueprints or blueprints or []

            if final_blueprints:
                # 构建一个人类可读的 Markdown 预览
                blueprints_preview = self._build_blueprints_preview(
                    final_blueprints,
                    streaming=False,
                )
                self.nsfc_project_preview = blueprints_preview
                content = blueprints_preview

                # 自动选择第一个题目
                selected_blueprint_msg = sa.select_blueprint(0)
                content += f"\n\n{selected_blueprint_msg}\n"

                logger.info(f"候选题目及研究方案生成完成: {len(final_blueprints)} 个候选")
            else:
                content = "当前未生成任何国自然备选课题方案，请稍后重试或调整输入。"
                logger.warning("候选题目生成失败：未能解析出有效蓝图")

        except Exception as e:
            logger.warning(f"候选题目生成过程异常: {e}")
            self.nsfc_project_blueprints = []
            blueprints = []
            content = "候选课题方案生成过程中发生错误，请稍后重试。"

        summary = (
            f"候选课题方案生成完成（{len(blueprints)} 个）"
            if blueprints else "候选课题方案生成失败"
        )

        for rsp in stream_response(True, tool_name=get_tool_name('blueprint')):
            yield rsp
            await asyncio.sleep(0)
        
        # 写作大纲生成
        summary = "正在为您生成国自然申请书大纲..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('outline')):
            last_chunk = rsp
            yield rsp
            await asyncio.sleep(0)

        outline = []
        try:
            outline = await sa.generate_nsfc_proposal_outline(
                last_chunk=last_chunk,
            )
            final_outline = sa.nsfc_proposal_outline or outline or []

            if final_outline:
                self.nsfc_proposal_outline = final_outline
                content = self._build_proposal_outline_preview(final_outline)
                logger.info("申请书大纲生成完成")
            else:
                self.nsfc_proposal_outline = []
                content = "当前尚未生成国自然写作大纲，请稍后重试或调整输入。"
                logger.warning("申请书大纲生成失败：未解析到有效大纲结构")

        except Exception as e:
            logger.error("申请书大纲生成过程异常: %s", e, exc_info=True)
            self.nsfc_proposal_outline = []
            content = "生成国自然申请书大纲时发生错误，请稍后重试。"

        summary = (
            "国自然申请书大纲生成完成" if self.nsfc_proposal_outline else "国自然申请书大纲生成失败"
        )

        for rsp in stream_response(True, tool_name=get_tool_name('outline')):
            yield rsp
            await asyncio.sleep(0)
        
        # 立项依据写作
        lixiang_part1_success = False
        summary = "正在为您撰写《一、立项依据与研究内容》第一部分，请稍候..."
        last_chunk = None
        for rsp in stream_response(tool_name=get_tool_name('lixiang_yiju')):
            last_chunk = rsp
            yield rsp
            await asyncio.sleep(0)
        
        try:
            pubmed_records = await sa.build_pubmed_pool()
            literature_snippets = sa.build_literature_snippets(pubmed_records)

            lixiang_yiju = await sa.generate_lixiang_yiju_parts(literature_snippets)
            sa.lixiang_yiju = lixiang_yiju  # 保存到sa对象
            logger.info(f"立项依据撰写完成")
            
            lixiang_yiju_preview = sa._render_markdown(lixiang_yiju, root_title="1. 项目的立项依据")
            content = lixiang_yiju_preview
            lixiang_part1_success = True
        except Exception as e:
            logger.warning(f"立项依据撰写失败: {e}")
        summary = "\"1. 项目的立项依据\"撰写完成" if lixiang_part1_success else "\"1. 项目的立项依据\"撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_yiju')):
            yield rsp
            await asyncio.sleep(0)
        
        # 完整立项依据写作
        summary = "正在为您撰写《一、立项依据与研究内容》后续章节（第 2–5 部分），请稍候..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_other')):
            yield rsp
            await asyncio.sleep(0)
        
        lixiang_other_success = False
        try: 
            lixiang_yiju_other = await sa.generate_lixiang_yiju_other_parts(model=sa.model)
            sa.lixiang_yiju_other = lixiang_yiju_other  # 保存到sa对象
            logger.info(f"立项依据后续章节撰写完成")
            lixiang_yiju_other_preview = sa._render_markdown(lixiang_yiju_other)
            content = lixiang_yiju_other_preview
            lixiang_other_success = True
        except Exception as e:
            logger.warning(f"立项依据后续章节撰写失败: {e}")
        summary = "\"立项依据\"后续章节撰写完成" if lixiang_other_success else "\"立项依据\"后续章节撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_other')):
            yield rsp
            await asyncio.sleep(0)
        
        # 研究基础写作
        summary = "正在为您撰写《二、研究基础》部分，请稍候..."
        for rsp in stream_response(tool_name=get_tool_name('research_basis')):
            yield rsp
            await asyncio.sleep(0)
        
        research_basis_success = False
        try:
            research_basis = await sa.generate_yanjiu_jichu_parts()
            sa.research_basis = research_basis  # 保存到sa对象
            logger.info(f"研究基础撰写完成")
            research_basis_preview = sa._render_markdown(research_basis, root_title="二、研究基础")
            content = research_basis_preview
            research_basis_success = True
        except Exception as e:
            logger.warning(f"研究基础撰写失败: {e}")
        summary = "《二、研究基础》撰写完成" if research_basis_success else "《二、研究基础》撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('research_basis')):
            yield rsp
            await asyncio.sleep(0)
        
        # 其他说明写作
        summary = "正在为您撰写《三、其他说明》部分，请稍候..."
        for rsp in stream_response(tool_name=get_tool_name('other_notes')):
            yield rsp
            await asyncio.sleep(0)
        
        other_section_success = False
        try:
            qita_shuoming = await sa.generate_qita_shuoming_parts()
            logger.info(f"其他说明撰写完成")
            qita_shuoming_preview = sa._render_markdown(qita_shuoming, root_title="三、其他说明")
            content = qita_shuoming_preview
            other_section_success = True
        except Exception as e:
            logger.warning(f"其他说明撰写失败: {e}") 
        summary = "《三、其他说明》撰写完成" if other_section_success else "《三、其他说明》撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('other_notes')):
            yield rsp
            await asyncio.sleep(0)

        # 导出完整申请书为Markdown和Word
        try:
            full_markdown = await self._export_full_proposal(sa)
            logger.info("申请书导出完成")
            
            """
            # 如果不是测试模式，上传 Word 文档到 OBS
            if not self.test and word_path and os.path.exists(word_path):
                try:
                    from utils.obs.client import upload_file
                    bucket_name = "noahai-userdata-test"
                    user = kwargs.get("user", "unknown")
                    
                    # 只上传 Word 文档
                    file_name = os.path.basename(word_path)
                    object_key = f"nsfc/{user}/{file_name}"
                    uploaded = False
                    
                    for _ in range(3):
                        res = upload_file(
                            bucket_name=bucket_name,
                            object_key=object_key,
                            file_path=word_path,
                        )
                        if res:
                            logger.info(f"Word 文档已上传到 OBS: {file_name}")
                            uploaded = True
                            break
                        await asyncio.sleep(3)
                    
                    if uploaded:
                        # 使用 OBS URL 作为 Word 文档路径
                        obs_url = f"https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{object_key}"
                        word_download = obs_url
                        full_markdown += f"\n\n---\n\n## 下载链接：[国自然申请书]({word_path})"
                        logger.info(f"OBS 下载链接: {word_path}")
                except Exception as e:
                    logger.warning(f"OBS 上传失败: {e}")
            """
            
            yield {
                'agent': 'article_nsfc_writing',
                'type': 'article_writing',
                'hitl_mode': 'always',
                'sender': 'assistant',
                'chunkIdx': 0,
                'message': full_markdown,
                'id': f'{steps}-w-0',
                'startedAt': started_at,
                'save': True,
            }
            # Return task finished event to avoid backend rewrit last event data
            yield {
                'agent': 'article_nsfc_writing',
                'type': 'statusUpdate',
                'hitl_mode': 'always',
                'sender': 'assistant',
                'chunkIdx': 0,
                'id': f'{steps}-w-0',
                'startedAt': started_at,
                'save': True,
            }
            await asyncio.sleep(0)
        except Exception as e:
            logger.warning(f"申请书导出失败: {e}")
            logger.debug(traceback.format_exc())
        

    def init_search_graph(self, query_mode=False):
        from agent.explore.schema import SearchNode, SearchType, WebSearchSubject, ProcessingType
        
        root = SearchNode(search_type=SearchType.UNKNOWN,
                    query="NSFC Application Preparation" if self.language == 'en-US' else "国自然申请准备",
                    key_word="")
        subject = WebSearchSubject.UNKNOWN.value
        root.subject = WebSearchSubject(subject)
        
        if query_mode:
            root.thought_process = "申请书生成将经过以下步骤" if self.language == 'zh-CN' else "Application generation will proceed as follows"
            steps = ["数据准备 (~30s)"] if self.language == 'zh-CN' else ["Data preparation (~30s)"]
            for subtitle in steps:
                node = SearchNode(search_type=SearchType.UNKNOWN,
                        query=subtitle,
                        key_word="")
                root.add_child(node)
            return root
        
        root.thought_process = "申请书生成即将开始" if self.language == 'zh-CN' else "Application generation will commence shortly"
        
        steps_chinese = [
            "步骤1：主题理解 — 翻译、概念提炼与关键词抽取（~30秒）",
            "步骤2：NSFC检索 — 自动搜索近年相关国家自然科学基金项目（~30秒）",
            "步骤3：NSFC分析 — 归纳领域研究格局、热点方向与典型模型（~1分钟）",
            "步骤4：NSFC机制分析 — 提炼主要研究路径、关键机制与常用技术路线（~1分钟）",
            "步骤5：NSFC空白分析 — 识别研究空白、薄弱环节与潜在科学问题（~1分钟）",
            "步骤6：PubMed检索 — 自动检索近年国际相关文献（~1分钟）",
            "步骤7：PubMed分析 — 提取国际研究结构、前沿机制与典型研究链条（~1分钟）",
            "步骤8：生成题目 — 输出3个候选项目题目及核心研究思路（~2分钟）",
            "步骤9：生成大纲 — 基于题目构建完整章节结构与科学问题链（~1分钟）",
            "步骤10：撰写立项依据（部分1）— 背景、意义与现状分析（~3分钟）",
            "步骤11：撰写立项依据（部分2–5）— 内容、目标、方案、创新与可行性（~3分钟）",
            "步骤12：整理研究基础 — 总结前期工作、团队积累与支撑条件（~2分钟）",
            "步骤13：补充说明 — 完成“其他需要说明的情况”部分（~1分钟）"
        ]
        
        steps_english = [
            "Step 1: Topic understanding — translation, concept extraction, and keyword generation (~30s)",
            "Step 2: NSFC search — automatically retrieve recent NSFC projects related to the topic (~30s)",
            "Step 3: NSFC analysis — summarize overall research landscape, hotspots, and common models (~1 min)",
            "Step 4: NSFC mechanism analysis — extract key biological mechanisms, research pathways, and technical routes (~1 min)",
            "Step 5: NSFC gap analysis — identify research gaps, weak links, and potential scientific questions (~1 min)",
            "Step 6: PubMed search — automatically retrieve recent international publications (~1 min)",
            "Step 7: PubMed analysis — extract global research structure, frontier mechanisms, and typical mechanistic chains (~1 min)",
            "Step 8: Title generation — produce three candidate project titles with core research ideas (~2 min)",
            "Step 9: Outline generation — build a complete proposal outline based on the selected title (~1 min)",
            "Step 10: Writing the Proposal (Part I) — background, significance, and current progress (~3 min)",
            "Step 11: Writing the Proposal (Parts II–V) — research aims, methodology, innovation, and feasibility (~3 min)",
            "Step 12: Research foundation — summarize previous work, team strengths, and supporting conditions (~2 min)",
            "Step 13: Additional statements — complete the 'Other Information' section (~1 min)"
        ]
        
        for subtitle in (steps_chinese if self.language == "zh-CN" else steps_english):
            node = SearchNode(search_type=SearchType.UNKNOWN,
                    query=subtitle,
                    key_word="")
            root.add_child(node)
        
        return root
    
    async def compress_and_upload(self, sa, response, **kwargs):
        zip_path = f"{sa.output_dir}.zip"
        if not os.path.exists(sa.output_dir + '/data'):
            os.makedirs(sa.output_dir + '/data', exist_ok=True)
        shutil.make_archive(sa.output_dir, 'zip', sa.output_dir)
        logger.info(f"Output saved to {zip_path}")
        
        # 尝试上传（本地测试时可能失败）
        uploaded = False
        try:
            from utils.obs.client import upload_file
            bucket_name = "noahai-userdata-test"
            user = kwargs.get("user", "unknown")
            file_name = sa.output_dir + ".zip"
            for _ in range(3):
                res = upload_file(bucket_name=bucket_name, object_key=f"nsfc/{user}/{file_name}", file_path=zip_path)
                if res: 
                    logger.info(f"File {zip_path} uploaded successfully")
                    response.search_graph.attachments_key = f"nsfc/{user}/{file_name}"
                    uploaded = True
                    break
                await asyncio.sleep(3)
            else:
                logger.warning(f"Failed to upload {zip_path}")
        except Exception as e:
            logger.warning(f"OBS upload skipped: {e}")
            
        response.content = response.content.replace('```markdown', '').replace('```', '')
        response.content += "\n---\n\n"
        
        if uploaded:
            response.content += ("## 下载链接：[国自然申请书]" if self.language == 'zh-CN' else "## Download link: [NSFC Application]") + f"(https://{bucket_name}.obs.cn-south-1.myhuaweicloud.com/{response.search_graph.attachments_key})"
        else:
            response.content += ("## 📦 本地文件：" if self.language == 'zh-CN' else "## 📦 Local File: ") + f"`{zip_path}`\n⚠️  上传已跳过（本地测试）"
    
    
    async def _export_full_proposal(self, sa):
        """将所有生成的内容导出为完整的Markdown和Word文档"""
        
        # 1. 组装完整的Markdown内容
        markdown_parts = []
        
        # 标题和项目信息
        blueprint = getattr(sa, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "国自然申请书")
        fund_type = sa.query_params.get('fund_type', '青年科学基金项目')
        duration_years = sa.query_params.get('duration_years', 3)
        
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;"
        
        markdown_parts.append("![nsfc logo](https://noahai-online.obs.cn-east-3.myhuaweicloud.com/nsfc_logo.png)&nbsp;\n\n")
        markdown_parts.append(f"# {indent}国家自然科学基金\n")
        markdown_parts.append(f"## {indent}&nbsp;&nbsp;申请书&nbsp;\n\n")
        
        markdown_parts.append(f"#### {indent}资助类别：{fund_type}\n")
        markdown_parts.append(f"#### {indent}亚类说明：______________________________\n")
        markdown_parts.append(f"#### {indent}附注说明：______________________________\n")
        markdown_parts.append(f"#### {indent}项目名称：{title}\n")
        markdown_parts.append(f"#### {indent}申请者：_____________ 电话：_____________\n")
        markdown_parts.append(f"#### {indent}依托单位：______________________________\n")
        markdown_parts.append(f"#### {indent}通讯地址：______________________________\n")
        markdown_parts.append(f"#### {indent}邮政编码：___________单位电话：___________\n")
        markdown_parts.append(f"#### {indent}电子邮件：______________________________\n\n")
        markdown_parts.append(f"#### {indent}申报日期：{datetime.now().strftime('%Y年%m月%d日')}\n\n")
        markdown_parts.append("\n---\n\n")
        
        # 2. 获取各章节内容（从sa对象的属性中提取）
        lixiang_yiju = getattr(sa, "lixiang_yiju", None)
        lixiang_yiju_other = getattr(sa, "lixiang_yiju_other", None)
        research_basis = getattr(sa, "research_basis", None)
        qita_shuoming = getattr(sa, "qita_shuoming", None)
        
        # 调试日志：检查各章节内容是否存在
        logger.info(f"文档组装：lixiang_yiju={'有内容' if lixiang_yiju else '空'}, " + 
                   f"lixiang_yiju_other={'有内容' if lixiang_yiju_other else '空'}, " +
                   f"research_basis={'有内容' if research_basis else '空'} (type={type(research_basis).__name__}, len={len(research_basis) if isinstance(research_basis, list) else 'N/A'}), " +
                   f"qita_shuoming={'有内容' if qita_shuoming else '空'}")
        
        # 3. 组装完整的Markdown（仅包含正文章节）
        full_markdown = "".join(markdown_parts)
        
        # 添加第一章：立项依据与研究内容（包含一级标题）
        if lixiang_yiju or lixiang_yiju_other:
            full_markdown += "\n\n## （一）立项依据与研究内容（建议8000字以内）：\n"
            
            if lixiang_yiju:
                full_markdown += ("\n### 1. 项目的立项依据（研究意义、国内外研究现状及发展动态分析，"
                                  "需结合科学研究发展趋势来论述科学意义；或结合国民经济和社会发展中迫切需要解决的关键科技问题来论述其应用前景。"
                                  "附主要参考文献目录）；\n\n")
                full_markdown += sa._render_markdown(lixiang_yiju, level_offset=1)
                
            if lixiang_yiju_other:
                official_titles = [
                    "2. 项目的研究内容、研究目标，以及拟解决的关键科学问题（此部分为重点阐述内容）；",
                    "3. 拟采取的研究方案及可行性分析（包括研究方法、技术路线、实验手段、关键技术等说明）；",
                    "4. 本项目的特色与创新之处；",
                    "5. 年度研究计划及预期研究结果（包括拟组织的重要学术交流活动、国际合作与交流计划等）。",
                ]
                
                if isinstance(lixiang_yiju_other, list):
                    for idx, section in enumerate(lixiang_yiju_other):
                        if not isinstance(section, dict):
                            continue
                        if idx < len(official_titles):
                            # 强制用官方模板标题覆盖
                            section["title"] = official_titles[idx]

                full_markdown += "\n\n" + sa._render_markdown(lixiang_yiju_other, level_offset=1)
        
        # 添加第二章：研究基础与工作条件
        official_research_basis_titles = [
            "1. 研究基础（与本项目相关的研究工作积累和已取得的研究工作成绩）；",
            "2. 工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；",
            "3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；",
            "4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。",
        ]
        if research_basis:
            if isinstance(research_basis, list):
                for idx, section in enumerate(research_basis):
                    if isinstance(section, dict) and idx < len(official_research_basis_titles):
                        section["title"] = official_research_basis_titles[idx]
            full_markdown += "\n\n" + sa._render_markdown(research_basis, root_title="（二）研究基础与工作条件")
        
        # 添加第三章：其他说明
        official_qita_shuoming_titles = [
            "1. 申请人同年申请不同类型的国家自然科学基金项目情况（列明同年申请的其他项目的项目类型、项目名称信息，并说明与本项目之间的区别与联系；已收到自然科学基金委不予受理或不予资助决定的，无需列出）。",
            "2. 具有高级专业技术职务（职称）的申请人是否存在同年申请或者参与申请国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，申请或参与申请的其他项目的项目类型、项目名称、单位名称、上述人员在该项目中是申请人还是参与者，并说明单位不一致原因。",
            "3. 具有高级专业技术职务（职称）的申请人是否存在与正在承担的国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，正在承担项目的批准号、项目类型、项目名称、单位名称、起止年月，并说明单位不一致原因。",
            "4. 同年以不同专业技术职务（职称）申请或参与申请科学基金项目的情况（应详细说明原因）。",
            "5. 其他。"
        ]
        if qita_shuoming:
            if isinstance(qita_shuoming, list):
                for idx, section in enumerate(qita_shuoming):
                    if not isinstance(section, dict):
                        continue
                    if idx < len(official_qita_shuoming_titles):
                        section["title"] = official_qita_shuoming_titles[idx]
                
            full_markdown += "\n\n" + sa._render_markdown(qita_shuoming, root_title="（三）其他需要说明的情况")

        return full_markdown
    
    async def _process_user_docs(self, django_files):
        da = self.nsfc_docs_analyzer
        da.load_raw_files_from_request(django_files)

        await da.convert_documents()
        await da.batch_summarize_docs()
        
        self.summarized_docs = da.summarized_docs
        return da.summarized_docs
    
    
    def _build_nsfc_preview(self, nsfc_projects: List[Dict[str, Any]], max_items: int = 5):
        if not nsfc_projects:
            return "当前未检索到相关国自然基金项目。"
        
        total = len(nsfc_projects)
        show_n = min(max_items, total)
        
        lines: List[str] = []
        # 总标题
        lines.append("## 相关国自然基金项目概览\n")
        lines.append(
            f"已根据您的研究主题检索到 {total} 项相关国自然基金项目。"
            f"下方优先展示前 {show_n} 项代表性项目，便于您快速了解该方向的资助布局和研究重点。\n")
        
        for idx, project in enumerate(nsfc_projects[:show_n], start=1):
            project_name = project.get("projectName") or "未命名项目"
            project_admin = project.get("projectAdmin") or "未知负责人"
            keywords = project.get("keywordList") or []
            depend_unit = project.get("dependUnit") or "未知单位"
            approval_year = (str(project.get("researchTimeStart")).split("-")[0] if project.get("researchTimeStart") else "未知起始时间")
            completed_year = (str(project.get("researchTimeEnd")).split("-")[0] if project.get("researchTimeEnd") else "未知结束时间")
            abstract = project.get("projectAbstractC") or "暂无摘要信息"
            conclusion = project.get("conclusionAbstract") or "暂无结题摘要"
            
            if completed_year and completed_year != "未知结束时间":
                status = "已结题"
            else:
                status = "未结题"
                
            if isinstance(keywords, (list, tuple)):
                kw_list = [str(k).strip() for k in keywords if k]
            else:
                kw_list = [str(keywords).strip()] if keywords else []
                
            # === 结构化“卡片” ===
            lines.append(f"### {idx}）{project_name}")
            lines.append(f"- 负责人：{project_admin}")
            lines.append(f"- 立项年份：{approval_year}")
            lines.append(f"- 结题年份：{completed_year}")
            lines.append(f"- 依托单位：{depend_unit}")
            lines.append(f"- 关键词：{'；'.join(kw_list) if kw_list else '暂无关键词'}")
            lines.append("")
            lines.append(f"**项目摘要**：{abstract}")
            if conclusion and conclusion != "暂无结题摘要":
                lines.append("")
                lines.append(f"**结题摘要**：{conclusion}")
            lines.append("")
            lines.append("---")
            lines.append("")
            
        return "\n".join(lines)
    
    def _build_pubmed_preview(self, pubmed_records: List[Dict[str, Any]], max_items: int = 5):
        if not pubmed_records:
            return "当前未检索到相关PubMed文献。"
        
        total = len(pubmed_records)
        show_n = min(max_items, total)
        lines: List[str] = []
        # 总标题
        lines.append("## 相关PubMed文献概览\n")
        lines.append(
            f"已根据您的研究主题检索到 {total} 篇相关PubMed文献。"
            f"下方优先展示前 {show_n} 篇代表性文献，便于您快速了解该方向的最新研究进展和热点。\n")
        
        for idx, record in enumerate(pubmed_records[:show_n], start=1):
            pmid = record.get("pmid") or "未知PMID"
            title = record.get("title") or "未命名文献"
            journal = record.get("journal") or record.get("fulljournalname") or "未知期刊"
            year = record.get("year_of_publication") or record.get("pubdate") or "未知年份"
            abstract = record.get("abstract") or record.get("summary") or "暂无摘要信息"
            
            # === 结构化“卡片” ===
            lines.append(f"### {idx}）{title} ({year})")
            lines.append(f"- PMID：{pmid}")
            lines.append(f"- 期刊：{journal}")
            lines.append("")
            lines.append(f"**摘要**：{abstract}")
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)

    def _build_blueprints_preview(self, blueprints, streaming: bool = True, total_expected: int = None,) -> str:
        if not blueprints:
            if streaming:
                return "正在生成国自然备选课题方案预览，请稍候……"
            else:
                return "当前未生成任何国自然备选课题方案"

        current = len(blueprints)

        lines: list[str] = []
        lines.append("## 国自然备选课题方案预览\n")

        if streaming:
            if total_expected and total_expected >= current:
                lines.append(
                    f"目前已生成 {current}/{total_expected} 个备选课题方案，"
                    f"系统仍在继续完善后续方案内容，请稍候刷新片刻。\n"
                )
            else:
                lines.append(
                    f"目前已生成 {current} 个备选课题方案，"
                    f"系统仍在继续完善后续方案内容，请稍候刷新片刻。\n"
                )
        else:
            lines.append(
                f"已根据您的研究方向生成 {current} 个备选课题方案，"
                f"包含题目、立项理由、研究目标和创新点，便于您后续筛选和修改。\n"
            )

        for idx, bp in enumerate(blueprints, start=1):
            title = bp.get("title") or f"未命名备选课题方案 {idx}"
            rationale = (bp.get("rationale") or "").strip()
            objectives = bp.get("objectives") or []
            contents = bp.get("contents") or []
            methods = bp.get("methods") or []
            innovations = bp.get("innovations") or []

            lines.append(f"### {idx}）{title}")

            if rationale:
                lines.append(f"**立项理由：**{rationale}")
                lines.append("")

            if objectives:
                lines.append("**研究目标：**")
                for o in objectives:
                    lines.append(f"- {o}")
                lines.append("")

            if contents:
                lines.append("**研究内容：**")
                for c in contents:
                    lines.append(f"- {c}")
                lines.append("")

            if methods:
                lines.append("**拟采用方法：**")
                for m in methods:
                    lines.append(f"- {m}")
                lines.append("")

            if innovations:
                lines.append("**创新点：**")
                for inn in innovations:
                    lines.append(f"- {inn}")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _parse_blueprints_partial(self, text: str, last_blueprints: list = None) -> list[dict]:
        if not text:
            return last_blueprints or []

        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        last_bracket = cleaned.rfind(']')
        if last_bracket != -1:
            candidate = cleaned[: last_bracket + 1]
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return data
            except Exception:
                pass

        last_brace = cleaned.rfind('}')
        if last_brace != -1:
            candidate = cleaned[: last_brace + 1]
            if candidate.strip().startswith('['):
                candidate2 = candidate + ']'
                try:
                    data = json.loads(candidate2)
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass
        return last_blueprints or []
    
    def _build_proposal_outline_preview(self, outline: list, max_level: int = 4) -> str:
        if not outline:
            return "当前尚未生成国自然写作大纲。"

        lines = []
        lines.append("## 国自然申请书写作大纲预览\n")

        def render_node(node: dict):
            # 安全检查：确保node是字典
            if not isinstance(node, dict):
                logger.warning(f"⚠️ render_node收到非字典元素: {type(node).__name__} = {str(node)[:100]}")
                return
            
            title = node.get("title", "").strip()
            level = int(node.get("level", 1))
            bullets = node.get("bullets") or []
            children = node.get("children") or []

            if level > max_level:
                return
            if level == 1:
                lines.append(f"### {title}")
            elif level == 2:
                lines.append(f"#### {title}")
            elif level == 3:
                lines.append(f"##### {title}")
            else:  # level >= 4
                lines.append(f"###### {title}")

            if bullets:
                for b in bullets:
                    b = str(b).strip()
                    if not b:
                        continue
                    lines.append(f"- {b}")
            for child in children:
                if isinstance(child, dict):  # 安全检查children
                    render_node(child)

            lines.append("")

        for root in outline:
            if isinstance(root, dict):  # 安全检查root元素
                render_node(root)
            else:
                logger.warning(f"⚠️ outline包含非字典根元素: {type(root).__name__} = {str(root)[:100]}")

        return "\n".join(lines)

    def _parse_outline_partial(self, text: str, last_outline: list = None) -> list:
        if not text:
            return last_outline or []
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                # 验证列表元素都是字典
                valid_items = [item for item in data if isinstance(item, dict)]
                if len(valid_items) != len(data):
                    logger.warning(f"⚠️ _parse_outline_partial: 过滤掉 {len(data) - len(valid_items)} 个非字典元素")
                return valid_items
            if isinstance(data, dict) and "outline" in data and isinstance(data["outline"], list):
                outline = data["outline"]
                valid_items = [item for item in outline if isinstance(item, dict)]
                if len(valid_items) != len(outline):
                    logger.warning(f"⚠️ _parse_outline_partial: 从字典提取outline，过滤掉 {len(outline) - len(valid_items)} 个非字典元素")
                return valid_items
        except Exception as e:
            logger.debug(f"_parse_outline_partial: JSON解析失败 ({type(e).__name__}), 尝试部分解析")

        last_bracket = cleaned.rfind(']')
        if last_bracket != -1:
            candidate = cleaned[: last_bracket + 1]
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return data
            except:
                pass

        last_brace = cleaned.rfind('}')
        if last_brace != -1:
            candidate = cleaned[: last_brace + 1]

            if candidate.strip().startswith('['):
                candidate2 = candidate + "]"
                try:
                    data = json.loads(candidate2)
                    if isinstance(data, list):
                        return data
                except:
                    pass
        return last_outline or []
    
    
    def _build_full_nsfc_tree(part1_1_text: str,   # 1. 项目的立项依据 正文
                              part1_2_text: str,   # 2. 项目的研究内容、研究目标... 正文
                              part1_3_text: str,   # 3. 拟采取的研究方案及可行性分析 正文
                              part1_4_text: str,   # 4. 本项目的特色与创新之处 正文
                              part1_5_text: str,   # 5. 年度研究计划及预期研究结果 正文
                              part2_1_text: str,   # 1. 研究基础 正文
                              part2_2_text: str,   # 2. 工作条件 正文
                              part2_3_text: str,   # 3. 正在承担的与本项目相关的科研项目情况 正文
                              part2_4_text: str,   # 4. 完成国家自然科学基金项目情况 正文
                              part3_items: List[Dict[str, str]],  # generate_other_info_parts 输出的 5 条 [{"title", "content"}...] 
                             ) -> List[Dict]:
        tree: List[Dict] = []
        # =============（一）立项依据与研究内容=============
        part1 = {
            "title": "（一）立项依据与研究内容（建议8000字以内）：",
            "level": 1,
            "content": "",
            "children": [
                {
                    "title": (
                        "1. 项目的立项依据（研究意义、国内外研究现状及发展动态分析，需结合科学研究发展趋势来论述科学意义；或结合国民经济和社会发展中迫切需要解决的关键科技问题来论述其应用前景。附主要参考文献目录）；"
                    ),
                    "level": 2,
                    "content": part1_1_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "2. 项目的研究内容、研究目标，以及拟解决的关键科学问题（此部分为重点阐述内容）；"
                    ),
                    "level": 2,
                    "content": part1_2_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "3. 拟采取的研究方案及可行性分析（包括研究方法、技术路线、实验手段、关键技术等说明）；"
                    ),
                    "level": 2,
                    "content": part1_3_text.strip(),
                    "children": [],
                },
                {
                    "title": "4. 本项目的特色与创新之处；",
                    "level": 2,
                    "content": part1_4_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "5. 年度研究计划及预期研究结果（包括拟组织的重要学术交流活动、国际合作与交流计划等）。"
                    ),
                    "level": 2,
                    "content": part1_5_text.strip(),
                    "children": [],
                },
            ],
        }
        tree.append(part1)

        # =============（二）研究基础与工作条件=============
        part2 = {
            "title": "（二）研究基础与工作条件",
            "level": 1,
            "content": "",
            "children": [
                {
                    "title": "1. 研究基础（与本项目相关的研究工作积累和已取得的研究工作成绩）；",
                    "level": 2,
                    "content": part2_1_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "2. 工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；"
                    ),
                    "level": 2,
                    "content": part2_2_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）;"
                    ),
                    "level": 2,
                    "content": part2_3_text.strip(),
                    "children": [],
                },
                {
                    "title": (
                        "4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。"
                    ),
                    "level": 2,
                    "content": part2_4_text.strip(),
                    "children": [],
                },
            ],
        }
        tree.append(part2)

        # =============（三）其他需要说明的情况=============
        # part3_items: [{"title": "...", "content": "..."}] 已经由 generate_other_info_parts 生成
        part3_children: List[Dict] = []
        for item in part3_items:
            part3_children.append(
                {
                    "title": item.get("title", "").strip(),
                    "level": 2,
                    "content": (item.get("content") or "无相关情况需要说明。").strip(),
                    "children": [],
                }
            )

        part3 = {
            "title": "（三）其他需要说明的情况",
            "level": 1,
            "content": "",
            "children": part3_children,
        }
        tree.append(part3)

        return tree

    def event_formatter(self, summary: str, content: str, id: int, started_at: int, plan_updates: list[dict], save: bool = False, reference: list = None):
        yield {
            'agent': 'article_nsfc_writing',
            'type': 'planUpdate',
            'sender': 'assistant',
            'plan': plan_updates,
            'chunkIdx': 0,
            'id': f'{id}-p-0',
            'startedAt': started_at,
            'save': save, 
        }
        
        yield {
            'agent': 'article_nsfc_writing',
                "current_tool":{
                    "reason":summary,
                    "startedAt":started_at,
                    "status":"done" if save else "doing",
                    "tool":"Writing-Preparation"
                },
            'type': 'chat',
            'hitl_mode': 'always',
            'sender': 'assistant',
            'translations': {},
            'chunkIdx': 0,
            'message': content,
            'id': f'{id}-c-0',
            'startedAt': started_at,
            'save': save, 
        }
        
        if reference and len(reference) > 0:
            yield {
                'agent': 'article_nsfc_writing',
                'type': 'reference',
                'sender': 'assistant',
                'chunkIdx': 1,
                'message': json.dumps(reference, ensure_ascii=False),
                'id': f'{id}-r-0',
                'startedAt': started_at,
                'save': save,
            }
        
        if save:
            yield {
                'agent': 'article_nsfc_writing',
                'chunkIdx': 0,
                'id': f'{id}-s-0',
                'sender': 'assistant',
                'startedAt': started_at,
                'type': 'statusUpdate',
                #"status": "DONE",
                'save': True,
            }

    async def get_raw_files(self, files: list[str]) -> list:
        attachments = self.attachment_manager.fetch_attachments(files)
        files = []
        for attachment in attachments:
            title = attachment.get('name', '')
            url = attachment.get('url', '')
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=title) as temp_file:
                    temp_path = temp_file.name
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        response.raise_for_status()
                        data = await response.read()
                        with open(temp_path, 'wb') as f:
                            f.write(data)
                files.append((title, temp_path))
            except Exception as e:
                logger.warning(f"load file failed {e}")
        return files