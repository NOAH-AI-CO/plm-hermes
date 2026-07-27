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
import config

logger = logging.getLogger(__name__)

# Citation generation helper functions
def _compress_json(obj: dict) -> str:
    res = ''
    try:
        res = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Invalid compress {e}")
    return res

def generate_pubmed_citation(rec: dict, idx: int) -> dict:
    authors = rec.get('author', '') or rec.get('authors', '')
    if isinstance(authors, list):
        cleaned_authors = []     
        for author in authors[:3]:
            if isinstance(author, dict):
                name = author.get("name") or author.get("full_name") or author.get("last_name") or ""
            else:
                name = author or ""

            name = str(name).strip()
            if not name:
                continue

            m = re.match(r"^\s*([^\s,]+)\s+.*\s+([A-Z]{1,5})\s*$", name)
            if m:
                name = f"{m.group(1)} {m.group(2)}"
                
            cleaned_authors.append(name)

        authors = ', '.join(cleaned_authors)  # 只取前3个作者
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


tool_names = {
            'query_analysis': {
                'zh-CN': '写作意图分析',
                'en-US': 'Writing Intent Analysis',
            },
            'nsfc_search': {
                'zh-CN': 'NSFC项目检索',
                'en-US': 'NSFC Project Search',
            },
            'nsfc_landscape': {
                'zh-CN': 'NSFC整体格局分析',
                'en-US': 'NSFC Landscape Analysis',
            },
            'nsfc_pathway': {
                'zh-CN': 'NSFC研究路径分析',
                'en-US': 'NSFC Pathway Analysis',
            },
            'nsfc_gap': {
                'zh-CN': 'NSFC研究空白分析',
                'en-US': 'NSFC Gap Analysis',
            },
            'pubmed_search': {
                'zh-CN': 'PubMed文献检索',
                'en-US': 'PubMed Search',
            },
            'pubmed_analysis': {
                'zh-CN': 'PubMed文献分析',
                'en-US': 'PubMed Literature Analysis',
            },
            'blueprint': {
                'zh-CN': '候选题目方案生成',
                'en-US': 'Blueprint Generation',
            },
            'outline': {
                'zh-CN': '申请书大纲生成',
                'en-US': 'Outline Generation',
            },
            'literature_pool': {
                'zh-CN': '文献池构建',
                'en-US': 'Literature Pool Building',
            },
            'lixiang_yiyi': {
                'zh-CN': '研究意义撰写',
                'en-US': 'Research Significance Writing',
            },
            'lixiang_xianzhuang': {
                'zh-CN': '研究现状撰写',
                'en-US': 'Research Status Writing',
            },
            'lixiang_wenti': {
                'zh-CN': '关键科学问题凝练',
                'en-US': 'Key Scientific Problems',
            },
            'lixiang_mubiao': {
                'zh-CN': '研究目标撰写',
                'en-US': 'Research Objectives Writing',
            },
            'lixiang_neirong': {
                'zh-CN': '研究内容撰写',
                'en-US': 'Research Content Writing',
            },
            'yanjiu_fangan': {
                'zh-CN': '研究方案撰写',
                'en-US': 'Research Plan Writing',
            },
            'jishu_luxian': {
                'zh-CN': '技术路线撰写',
                'en-US': 'Technical Route Writing',
            },
            'guanjian_jishu': {
                'zh-CN': '关键技术撰写',
                'en-US': 'Key Technologies Writing',
            },
            'kexingxing': {
                'zh-CN': '可行性分析撰写',
                'en-US': 'Feasibility Analysis Writing',
            },
            'lixiang_chuangxin': {
                'zh-CN': '创新点撰写',
                'en-US': 'Innovation Points Writing',
            },
            'yanjiu_jihua': {
                'zh-CN': '年度研究计划撰写',
                'en-US': 'Annual Research Plan Writing',
            },
            'yuqi_chengguo': {
                'zh-CN': '预期研究成果撰写',
                'en-US': 'Expected Results Writing',
            },
            'yanjiu_jichu': {
                'zh-CN': '研究基础撰写',
                'en-US': 'Research Foundation Writing',
            },
            'gongzuo_tiaojian': {
                'zh-CN': '工作条件撰写',
                'en-US': 'Working Conditions Writing',
            },
            'keyan_xiangmu': {
                'zh-CN': '科研项目情况撰写',
                'en-US': 'Research Projects Writing',
            },
            'nsfc_xiangmu': {
                'zh-CN': '已完成基金项目情况撰写',
                'en-US': 'Completed NSFC Projects Writing',
            },
            'other_notes': {
                'zh-CN': '其他说明撰写',
                'en-US': 'Other Notes Writing',
            },
        }
def get_tool_name(key: str) -> str:
    return tool_names.get(key, {}).get('zh-CN', 'Unknown')

class NSFCAgentPhaseOne(AgentPreset):
    llm: BaseLLM = GPT4o
    sys_prompt: str = ""
    mindsearch_helper: MindSearchHelper = MindSearchHelper()
    prep_analyzer_class: Type[NSFCPrepAnalyzer] = NSFCPrepAnalyzer
    nsfc_prep_analyzer: NSFCPrepAnalyzer = None
    docs_analyzer_class: Type[NSFCDocsAnalyzer] = NSFCDocsAnalyzer
    nsfc_docs_analyzer: NSFCDocsAnalyzer = None
    language: str = "zh-CN"
    scene: str = "default"
    env: str = "default"
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
        params = kwargs.get('params', {})
        query_params.update(params.get('raw_data', {}))
        
        from i18n.languages import normalize as _norm; self.language = _norm(params.get('language', ''))
        self.scene = params.get('scene', 'default')
        self.env = config.settings.get('ENV', 'default')
        
        title = query_params.get("user_title", "") or ""
        query = query_params.get("user_query", "") or ""
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
        
        if model is None:
            try:
                from lite_llm.aliyun_models import AliyunQwen3Max
                model = AliyunQwen3Max()
                logger.info("使用默认模型: AliyunQwen3Max")
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
                    'status': 'done' if save else 'doing',
                    'tool': tool_name
                })
            else:
                plan_updates[-1]['reason'] = summary
                plan_updates[-1]['status'] = 'done' if save else 'doing'
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
            # Only save the first response for frontend reconnection display
            rsp['save'] = True
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
            nsfc_projects = sa.run_search_nsfc(start_year=2020, top_k=50)
            project_count = len(nsfc_projects)
            logger.info(f"相关基金项目已检索完成，共 {project_count} 项")
            projects_preview = self._build_nsfc_preview(nsfc_projects, max_items=5)
            content = projects_preview
            
            # 构建 NSFC reference 数据（取前20个用于展示）
            for idx, proj in enumerate(nsfc_projects[:20], start=1):
                project_id = proj.get('_id', '')
                ratify_no = proj.get('ratifyNo', '')

                if self.scene == 'roche':
                    if self.env != 'prod':
                        url = f"https://test.roche.noahai.co/tool/nsfc/{project_id}"
                    else:
                        url = f"https://roche.noahai.co/tool/nsfc/{project_id}"
                else:
                    if self.env != 'prod':
                        url = f"https://test.noahai.co/detail/nsfc/{project_id}"
                    else:
                        url = f"https://noahai.co/detail/nsfc/{project_id}"
                # 生成citation
                citation = generate_nsfc_citation(proj, idx)
                citation_json = _compress_json(citation)
                
                nsfc_reference.append({
                    # 必须字段
                    'id': idx,
                    'title': proj.get('projectName', '未命名项目'),
                    'url': url if project_id else "",
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
                    # Citation
                    'citation': citation_json,
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
            last_chunk = rsp
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
            last_chunk = rsp
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
            pubmed_records = await sa.run_search_pubmed_by_keywords(search_years=[2025, 2024, 2023], top_k=50)
            logger.info(f"PubMed检索完成: {len(pubmed_records)} 篇文献")
            pubmed_preview = self._build_pubmed_preview(pubmed_records, max_items=5)
            content = pubmed_preview
            
            # 构建 PubMed reference 数据（取前20个用于展示）
            for idx, rec in enumerate(pubmed_records[:20], start=1):
                pmid = rec.get('pmid', '')
                
                citation = generate_pubmed_citation(rec, idx)
                citation_json = _compress_json(citation)
                
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
                    # Citation
                    'citation': citation_json,
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
        num_blueprints = 3

        blueprints: list[dict] = []
        content = ""
        
        try:
            blueprints = await sa.generate_nsfc_project_blueprints(
                summarized_docs=self.summarized_docs,  
                num_blueprints=num_blueprints,
                temperature=0.5,
            )
            
            blueprints = sa.nsfc_project_blueprints or blueprints or []
            if blueprints:
                #
                steps = steps - 1

                logger.info(f"候选题目方案生成完成，共 {len(blueprints)} 个方案")         
                blueprints_preview = self._build_blueprints_preview(blueprints, streaming=False, with_header=True, start_index=1,)
                
                context = {
                    "query_params": sa.query_params,
                    "nsfc_statistics": nsfc_statistics,
                    "nsfc_sample_projects": nsfc_sample_projects,
                    "nsfc_overview": nsfc_overview,
                    "nsfc_mechanism": nsfc_mechanism,
                    "nsfc_gap": nsfc_gap,
                    "nsfc_insights": getattr(sa, "nsfc_insights", ""),
                    "pubmed_records": pubmed_records,
                    "pubmed_overview": pubmed_overview,
                    "pubmed_insights": getattr(sa, "pubmed_insights", ""),
                    "summarized_docs": getattr(sa, "summarized_docs", ""),
                    "nsfc_project_blueprints": blueprints,
                    "plan_updates": plan_updates
                }
                
                yield {
                    "agent": 'article_nsfc_writing',
                    "type": "nsfc_confirm",
                    "sender": "assistant",
                    "chunkIdx": 0,
                    "message": "候选课题方案生成完成，正在逐一展示。",
                    "data": context,
                    "id": f"{steps}-nbc-0",
                    "startedAt": started_at,
                    "save": True,
                }
                
                # 逐个发送三个候选课题方案的 chat 事件
                for idx, bp in enumerate(blueprints):
                    single_bp_preview = self._build_blueprints_preview([bp], streaming=False, with_header=False, start_index=idx + 1)
                    yield {
                        'agent': 'article_nsfc_writing',
                        'type': 'chat',
                        'sender': 'assistant',
                        'chunkIdx': 0,
                        'message': single_bp_preview,
                        'id': f'{steps}-bp-{idx}',
                        'startedAt': started_at,
                        'save': True, 
                    }
                    await asyncio.sleep(0)
                
                # 发送一个最终的event内容
                yield {
                    'agent': 'article_nsfc_writing',
                    'type': 'statusUpdate',
                    'sender': 'assistant',
                    'chunkIdx': 0,
                    'need_future_steps': True,
                    'id': f'{steps}-w-0',
                    'startedAt': started_at,
                    'save': True,
                }
                await asyncio.sleep(0)
            else:
                summary = "候选课题方案生成失败"
                content = "当前未生成任何国自然备选课题方案，请稍后重试或调整输入。"
                for rsp in stream_response(True, tool_name=get_tool_name('blueprint')):
                    yield rsp
                    await asyncio.sleep(0)
        except Exception as e:
            logger.warning(f"候选题目生成过程异常: {e}")
            self.nsfc_project_blueprints = []
            blueprints = []
            summary = "候选课题方案生成失败（发生异常）"
            content = "候选课题方案生成过程中发生错误，请稍后重试。"
            for rsp in stream_response(True, tool_name=get_tool_name('blueprint')):
                yield rsp
                await asyncio.sleep(0)

    
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
    
    async def _process_user_docs(self, django_files):
        da = self.nsfc_docs_analyzer
        da.load_raw_files_from_request(django_files)

        await da.convert_documents()
        await da.batch_summarize_docs()
        
        self.summarized_docs = da.summarized_docs
        return da.summarized_docs
    
    def event_formatter(self, summary: str, content: str, id: int, started_at: int, plan_updates: list[dict], save: bool = False, reference: list = None, tool_name=None):
        tool = tool_name or (plan_updates[id]["tool"] if id < len(plan_updates) else "Writing-Preparation")

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
                    "tool":tool
                },
            'type': 'chat',
            'sender': 'assistant',
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
    
    
    def _build_blueprints_preview(self,
                                  blueprints,
                                  streaming: bool = True,
                                  total_expected: int = None,
                                  with_header: bool = True,
                                  start_index: int = 1) -> str:
        if not blueprints:
            if streaming:
                return "正在生成国自然备选课题方案预览，请稍候……"
            else:
                return "当前未生成任何国自然备选课题方案"

        current = len(blueprints)
        lines: list[str] = []

        if with_header:
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

        for idx, bp in enumerate(blueprints, start=start_index):
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
    
class NSFCAgentPhaseTwo(AgentPreset):
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
    nsfc_selected_blueprint_id: int = 0
    pre_plan_updates: List[Dict] = [] # 前一步的plan updates，前端需要使用这个plan updates数组用来更新步骤内容
    
    def __init__(self, query_params={}, query_mode=False, gemini_mode=False, model=None, **kwargs):
        super().__init__()

        params = kwargs.get('params', {})
        from i18n.languages import normalize as _norm; self.language = _norm(params.get('language', ''))
        self.nsfc_selected_blueprint_id = params.get('nsfc_selected_blueprint_id', 0)
        
        context = params.get('nsfc_context', {})
        self.nsfc_project_blueprints = context.get('nsfc_project_blueprints', [])
        nsfc_insights = context.get('nsfc_insights', "")
        pubmed_insights = context.get('pubmed_insights', "")
        query_params = context.get('query_params', {})
        self.pre_plan_updates = context.get('plan_updates', [])
            
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
        
        # 检查是否使用 lite_llm 模型（通过检查是否有 stream_generate 方法）
        use_lite_llm = hasattr(model, 'stream_generate') and not hasattr(model, 'generate_stream')
        
        if use_lite_llm:
            logger.info(f"检测到 lite_llm 模型: {model.__class__.__name__}，使用适配器")
            # 使用适配器包装 lite_llm 模型，用于主要内容生成
            adapted_model = LiteLLMAdapter(model)
            # JSON 生成任务固定使用 GPT4o
            json_model = GPT4o()
            logger.info(f"主模型: {adapted_model}, JSON模型: {json_model.__class__.__name__}")
        else:
            # 使用传统模型，不需要适配
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
        
        self.nsfc_prep_analyzer.query_params = query_params
        # 安全获取选中的方案
        if self.nsfc_project_blueprints and 0 <= self.nsfc_selected_blueprint_id < len(self.nsfc_project_blueprints):
            self.nsfc_prep_analyzer.nsfc_selected_blueprint = self.nsfc_project_blueprints[self.nsfc_selected_blueprint_id]
        else:
            logger.warning(f"Invalid blueprint ID {self.nsfc_selected_blueprint_id}, using first blueprint or empty dict")
            self.nsfc_prep_analyzer.nsfc_selected_blueprint = self.nsfc_project_blueprints[0] if self.nsfc_project_blueprints else {}
        self.nsfc_prep_analyzer.nsfc_insights = nsfc_insights
        self.nsfc_prep_analyzer.pubmed_insights = pubmed_insights
        
    async def use_tool(self, user_prompt: str = "", **kwargs):
        sa = self.nsfc_prep_analyzer
        
        summary = ''
        content = ''
        started_at = int(time.time())
        # add pre plan updates
        steps = len(self.pre_plan_updates)
        plan_updates = self.pre_plan_updates
        
        def stream_response(save: bool = False, tool_name: str = 'Writing-Preparation', reference: list = None):
            nonlocal summary, content, steps, started_at, plan_updates
            
            if steps >= len(plan_updates):
                plan_updates.append({
                    'id': f'step_{steps}',
                    'reason': summary,
                    'startedAt': started_at,
                    'status': 'done' if save else 'doing',
                    'tool': tool_name
                })
            else:
                plan_updates[-1]['reason'] = summary
                plan_updates[-1]['status'] = 'done' if save else 'doing'
                plan_updates[-1]['tool'] = tool_name
            for rsp in self.event_formatter(summary, content, steps, started_at, plan_updates, save=save, reference=reference):
                yield rsp
            if save:
                steps = steps + 1
                started_at = int(time.time())
                summary = ''
                content = ''
                
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
            logger.exception(f"申请书大纲生成过程异常: {e}")
            self.nsfc_proposal_outline = []
            content = f"生成国自然申请书大纲时发生错误：{e}"

        summary = (
            "国自然申请书大纲生成完成" if self.nsfc_proposal_outline else "国自然申请书大纲生成失败"
        )

        for rsp in stream_response(True, tool_name=get_tool_name('outline')):
            yield rsp
            await asyncio.sleep(0)
            
        
        # ========== 第一章写作：立项依据与研究内容 ==========
        # 构建文献池（只需要构建一次，供所有小节使用）
        summary = "正在构建PubMed文献池用于立项依据撰写..."
        for rsp in stream_response(tool_name=get_tool_name('literature_pool')):
            yield rsp
            await asyncio.sleep(0)

        literature_snippets = ""
        pubmed_records = []
        try:
            pubmed_records = await sa.build_pubmed_pool(max_papers=120)
            literature_snippets = sa.build_literature_snippets(pubmed_records, max_items=40)
            preview_count = 40
            display_count = min(10, len(pubmed_records))
            preview_lines = []
            for idx, rec in enumerate(pubmed_records[:preview_count], start=1):
                citation = generate_pubmed_citation(rec, idx)
                logger.info(f"[{idx}] {citation.get('txt', '').strip()}")
                if idx <= display_count:
                    preview_lines.append(f"[{idx}] {citation.get('txt', '').strip()}")
            logger.info(f"PubMed文献池构建完成，共 {len(pubmed_records)} 篇文献，将使用前40篇作为参考文献")
            preview_text = "\n".join(preview_lines) if preview_lines else "（无可展示文献）"
            content = (
                "## 文献池构建完成\n\n"
                f"已为立项依据撰写准备 {len(pubmed_records)} 篇高质量文献（将使用前40篇作为参考文献）。\n\n"
                f"文献池预览（前 {display_count} 篇）：\n{preview_text}"
            )
            
        except Exception as e:
            logger.error(f"文献池构建失败: {e}")
            content = "文献池构建失败，将尝试继续撰写（可能影响引用质量）"

        summary = f"文献池构建完成（共 {len(pubmed_records)} 篇）" if pubmed_records else "文献池构建失败"
        for rsp in stream_response(True, tool_name=get_tool_name('literature_pool')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 1.1 研究意义 ==========
        summary = "正在撰写【1.1 研究意义】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_yiyi')):
            yield rsp
            await asyncio.sleep(0)

        yiyi_success = False
        try:
            yanjiu_yiyi = await sa.generate_yanjiu_yiyi(literature_snippets, model=sa.model)
            content = f"### 1.1 研究意义\n\n{yanjiu_yiyi}\n\n✓ 完整内容已生成（共 {len(yanjiu_yiyi)} 字）"
            yiyi_success = True
            logger.info("研究意义撰写完成")
        except Exception as e:
            logger.error(f"研究意义生成失败: {e}")
            content = "❌ 研究意义生成失败"

        summary = "【1.1 研究意义】撰写完成" if yiyi_success else "【1.1 研究意义】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_yiyi')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 1.2 研究现状 ==========
        summary = "正在撰写【1.2 国内外研究现状及发展动态】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_xianzhuang')):
            yield rsp
            await asyncio.sleep(0)

        xianzhuang_success = False
        try:
            yanjiu_xianzhuang = await sa.generate_yanjiu_xianzhuang(literature_snippets, model=sa.model)
            content = f"### 1.2 国内外研究现状及发展动态\n\n{yanjiu_xianzhuang}"
            xianzhuang_success = True
            logger.info("研究现状撰写完成")
        except Exception as e:
            logger.error(f"研究现状生成失败: {e}")
            content = "❌ 研究现状生成失败"

        summary = "【1.2 研究现状】撰写完成" if xianzhuang_success else "【1.2 研究现状】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_xianzhuang')):
            yield rsp
            await asyncio.sleep(0)

        # 重排序参考文献并生成完整的1.1+1.2+参考文献
        lixiang_yiju_parts = None
        if yiyi_success and xianzhuang_success:
            try:
                lixiang_yiju_parts = await sa.new_generate_lixiang_yiju_parts(literature_snippets, model=sa.model)
                logger.info("立项依据第1部分（研究意义+研究现状+参考文献）整合完成")
            except Exception as e:
                logger.error(f"立项依据第1部分整合失败: {e}")

        # ========== 生成研究现状摘要（用于后续章节） ==========
        try:
            if xianzhuang_success:
                await sa._generate_yanjiu_yiju_brief(yanjiu_xianzhuang, model=sa.model)
                logger.info("研究现状摘要生成完成")
        except Exception as e:
            logger.warning(f"研究现状摘要生成失败: {e}")

        # ========== 2. 拟解决的关键科学问题 ==========
        summary = "正在凝练【拟解决的关键科学问题】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_wenti')):
            yield rsp
            await asyncio.sleep(0)

        wenti_success = False
        kexue_wenti = ""
        try:
            kexue_wenti = await sa._generate_kexue_wenti_parts(model=sa.model)
            content = f"### 拟解决的关键科学问题\n\n{kexue_wenti}"
            wenti_success = True
            logger.info("关键科学问题凝练完成")
        except Exception as e:
            logger.error(f"关键科学问题生成失败: {e}")
            content = "❌ 关键科学问题生成失败"

        summary = "【关键科学问题】凝练完成" if wenti_success else "【关键科学问题】凝练失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_wenti')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 3. 研究目标 ==========
        summary = "正在撰写【研究目标】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_mubiao')):
            yield rsp
            await asyncio.sleep(0)

        mubiao_success = False
        yanjiu_mubiao = ""
        try:
            yanjiu_mubiao = await sa._generate_yanjiu_mubiao_parts(model=sa.model)
            content = f"### 研究目标\n\n{yanjiu_mubiao}"
            mubiao_success = True
            logger.info("研究目标撰写完成")
        except Exception as e:
            logger.error(f"研究目标生成失败: {e}")
            content = "❌ 研究目标生成失败"

        summary = "【研究目标】撰写完成" if mubiao_success else "【研究目标】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_mubiao')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 4. 研究内容 ==========
        summary = "正在撰写【研究内容】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_neirong')):
            yield rsp
            await asyncio.sleep(0)

        neirong_success = False
        try:
            yanjiu_neirong = await sa._generate_yanjiu_neirong_parts(model=sa.model)
            # 保存到 sa 对象，供后续步骤使用
            sa.yanjiu_neirong_breakdown = yanjiu_neirong
            content = f"### 研究内容\n\n{yanjiu_neirong}"
            neirong_success = True
            logger.info("研究内容撰写完成")
        except Exception as e:
            logger.error(f"研究内容生成失败: {e}")
            content = "❌ 研究内容生成失败"

        summary = "【研究内容】撰写完成" if neirong_success else "【研究内容】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_neirong')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 5. 研究方案与可行性分析 ==========
        # 5.1 研究方案
        summary = "正在撰写【3.2 研究方案】..."
        for rsp in stream_response(tool_name=get_tool_name('yanjiu_fangan')):
            yield rsp
            await asyncio.sleep(0)

        yanjiu_fangan_parts = ""
        try:
            yanjiu_fangan_parts = await sa._generate_yanjiu_fangan_parts(model=sa.model)
            content = f"### 3.2 研究方案\n\n{yanjiu_fangan_parts}"
            logger.info("研究方案撰写完成")
        except Exception as e:
            logger.error(f"研究方案生成失败: {e}")
            content = "❌ 研究方案生成失败"

        summary = "【3.2 研究方案】撰写完成" if yanjiu_fangan_parts else "【3.2 研究方案】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('yanjiu_fangan')):
            yield rsp
            await asyncio.sleep(0)

        # 5.2 技术路线
        summary = "正在撰写【3.1 技术路线】..."
        for rsp in stream_response(tool_name=get_tool_name('jishu_luxian')):
            yield rsp
            await asyncio.sleep(0)

        jishu_luxian_parts = ""
        try:
            jishu_luxian_parts = await sa._generate_jishu_luxian_parts(yanjiu_fangan=yanjiu_fangan_parts, model=sa.model)
            content = f"### 3.1 技术路线\n\n{jishu_luxian_parts}"
            logger.info("技术路线撰写完成")
        except Exception as e:
            logger.error(f"技术路线生成失败: {e}")
            content = "❌ 技术路线生成失败"

        summary = "【3.1 技术路线】撰写完成" if jishu_luxian_parts else "【3.1 技术路线】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('jishu_luxian')):
            yield rsp
            await asyncio.sleep(0)

        # 5.3 关键技术
        summary = "正在撰写【3.3 关键技术】..."
        for rsp in stream_response(tool_name=get_tool_name('guanjian_jishu')):
            yield rsp
            await asyncio.sleep(0)

        guanjian_jishu_parts = ""
        try:
            guanjian_jishu_parts = await sa._generate_guanjian_jishu_parts(yanjiu_fangan=yanjiu_fangan_parts, model=sa.model)
            content = f"### 3.3 关键技术\n\n{guanjian_jishu_parts}"
            logger.info("关键技术撰写完成")
        except Exception as e:
            logger.error(f"关键技术生成失败: {e}")
            content = "❌ 关键技术生成失败"

        summary = "【3.3 关键技术】撰写完成" if guanjian_jishu_parts else "【3.3 关键技术】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('guanjian_jishu')):
            yield rsp
            await asyncio.sleep(0)

        # 5.4 可行性分析
        summary = "正在撰写【3.4 可行性分析】..."
        for rsp in stream_response(tool_name=get_tool_name('kexingxing')):
            yield rsp
            await asyncio.sleep(0)

        kexingxing_parts = ""
        try:
            kexingxing_parts = await sa._generate_kexingxing_parts(model=sa.model)
            content = f"### 3.4 可行性分析\n\n{kexingxing_parts}"
            logger.info("可行性分析撰写完成")
        except Exception as e:
            logger.error(f"可行性分析生成失败: {e}")
            content = "❌ 可行性分析生成失败"

        summary = "【3.4 可行性分析】撰写完成" if kexingxing_parts else "【3.4 可行性分析】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('kexingxing')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 6. 创新点 ==========
        summary = "正在撰写【本项目的特色与创新之处】..."
        for rsp in stream_response(tool_name=get_tool_name('lixiang_chuangxin')):
            yield rsp
            await asyncio.sleep(0)

        chuangxin_success = False
        chuangxin_parts = ""
        try:
            chuangxin_parts = await sa.generate_chuangxinxing_parts(model=sa.model)
            content = f"### 本项目的特色与创新之处\n\n{chuangxin_parts}"
            chuangxin_success = True
            logger.info("创新点撰写完成")
        except Exception as e:
            logger.error(f"创新点生成失败: {e}")
            content = "❌ 创新点生成失败"

        summary = "【创新点】撰写完成" if chuangxin_success else "【创新点】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('lixiang_chuangxin')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 7. 年度计划与预期成果 ==========
        # 7.1 年度研究计划
        summary = "正在撰写【5.1 年度研究计划】..."
        for rsp in stream_response(tool_name=get_tool_name('yanjiu_jihua')):
            yield rsp
            await asyncio.sleep(0)

        yanjiu_jihua_parts = ""
        try:
            yanjiu_jihua_parts = await sa._generate_yanjiu_jihua_parts(model=sa.model)
            content = f"### 5.1 年度研究计划\n\n{yanjiu_jihua_parts}"
            logger.info("年度研究计划撰写完成")
        except Exception as e:
            logger.error(f"年度研究计划生成失败: {e}")
            content = "❌ 年度研究计划生成失败"

        summary = "【5.1 年度研究计划】撰写完成" if yanjiu_jihua_parts else "【5.1 年度研究计划】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('yanjiu_jihua')):
            yield rsp
            await asyncio.sleep(0)

        # 7.2 预期研究成果
        summary = "正在撰写【5.2 预期研究成果】..."
        for rsp in stream_response(tool_name=get_tool_name('yuqi_chengguo')):
            yield rsp
            await asyncio.sleep(0)

        yuqi_chengguo_parts = ""
        try:
            yuqi_chengguo_parts = await sa._generate_yuqi_chengguo_parts(model=sa.model)
            content = f"### 5.2 预期研究成果\n\n{yuqi_chengguo_parts}"
            logger.info("预期研究成果撰写完成")
        except Exception as e:
            logger.error(f"预期研究成果生成失败: {e}")
            content = "❌ 预期研究成果生成失败"

        summary = "【5.2 预期研究成果】撰写完成" if yuqi_chengguo_parts else "【5.2 预期研究成果】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('yuqi_chengguo')):
            yield rsp
            await asyncio.sleep(0)

        # ========== 第二章写作：研究基础与工作条件 ==========
        # 2.1 研究基础
        summary = "正在撰写【2.1 研究基础】..."
        for rsp in stream_response(tool_name=get_tool_name('yanjiu_jichu')):
            yield rsp
            await asyncio.sleep(0)

        yanjiu_jichu_success = False
        try:
            yanjiu_jichu_parts = await sa._generate_yanjiu_jichu_parts(model=sa.model)
            content = f"### 2.1 研究基础\n\n{yanjiu_jichu_parts}"
            yanjiu_jichu_success = True
            logger.info("研究基础撰写完成")
        except Exception as e:
            logger.error(f"研究基础生成失败: {e}")
            content = "❌ 研究基础生成失败"

        summary = "【2.1 研究基础】撰写完成" if yanjiu_jichu_success else "【2.1 研究基础】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('yanjiu_jichu')):
            yield rsp
            await asyncio.sleep(0)

        # 2.2 工作条件
        summary = "正在撰写【2.2 工作条件】..."
        for rsp in stream_response(tool_name=get_tool_name('gongzuo_tiaojian')):
            yield rsp
            await asyncio.sleep(0)

        gongzuo_tiaojian_success = False
        try:
            gongzuo_tiaojian_parts = await sa._generate_gongzuo_tiao_parts(model=sa.model)
            content = f"### 2.2 工作条件\n\n{gongzuo_tiaojian_parts}"
            gongzuo_tiaojian_success = True
            logger.info("工作条件撰写完成")
        except Exception as e:
            logger.error(f"工作条件生成失败: {e}")
            content = "❌ 工作条件生成失败"

        summary = "【2.2 工作条件】撰写完成" if gongzuo_tiaojian_success else "【2.2 工作条件】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('gongzuo_tiaojian')):
            yield rsp
            await asyncio.sleep(0)

        # 2.3 正在承担的科研项目情况
        summary = "正在撰写【2.3 正在承担的科研项目情况】..."
        for rsp in stream_response(tool_name=get_tool_name('keyan_xiangmu')):
            yield rsp
            await asyncio.sleep(0)

        keyan_xiangmu_success = False
        try:
            keyan_xiangmu_parts = await sa._generate_keyan_xiangmu_qingkuang_parts(model=sa.model)
            content = f"### 2.3 正在承担的科研项目情况\n\n{keyan_xiangmu_parts}"
            keyan_xiangmu_success = True
            logger.info("科研项目情况撰写完成")
        except Exception as e:
            logger.error(f"科研项目情况生成失败: {e}")
            content = "❌ 科研项目情况生成失败"

        summary = "【2.3 科研项目情况】撰写完成" if keyan_xiangmu_success else "【2.3 科研项目情况】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('keyan_xiangmu')):
            yield rsp
            await asyncio.sleep(0)

        # 2.4 完成国家自然科学基金项目情况
        summary = "正在撰写【2.4 完成国家自然科学基金项目情况】..."
        for rsp in stream_response(tool_name=get_tool_name('nsfc_xiangmu')):
            yield rsp
            await asyncio.sleep(0)

        nsfc_xiangmu_success = False
        try:
            nsfc_xiangmu_parts = await sa._generate_nsfc_projects_qingkuang_parts(model=sa.model)
            content = f"### 2.4 完成国家自然科学基金项目情况\n\n{nsfc_xiangmu_parts}"
            nsfc_xiangmu_success = True
            logger.info("已完成基金项目情况撰写完成")
        except Exception as e:
            logger.error(f"已完成基金项目情况生成失败: {e}")
            content = "❌ 已完成基金项目情况生成失败"

        summary = "【2.4 已完成基金项目情况】撰写完成" if nsfc_xiangmu_success else "【2.4 已完成基金项目情况】撰写失败"
        for rsp in stream_response(True, tool_name=get_tool_name('nsfc_xiangmu')):
            yield rsp
            await asyncio.sleep(0)

        # 其他说明写作
        summary = "正在为您撰写《三、其他说明》部分，请稍候..."
        for rsp in stream_response(tool_name=get_tool_name('other_notes')):
            yield rsp
            await asyncio.sleep(0)
        
        other_section_success = False
        qita_shuoming = None
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
        full_markdown = ""
        try:
            logger.info("开始导出完整申请书...")
            full_markdown = await self._export_full_proposal(
                sa,
                lixiang_yiju_parts=lixiang_yiju_parts,
                kexue_wenti=kexue_wenti if wenti_success else "",
                yanjiu_mubiao=yanjiu_mubiao if mubiao_success else "",
                yanjiu_neirong=yanjiu_neirong if neirong_success else "",
                jishu_luxian_parts=jishu_luxian_parts,
                yanjiu_fangan_parts=yanjiu_fangan_parts,
                guanjian_jishu_parts=guanjian_jishu_parts,
                kexingxing_parts=kexingxing_parts,
                chuangxin_parts=chuangxin_parts if chuangxin_success else "",
                yanjiu_jihua_parts=yanjiu_jihua_parts,
                yuqi_chengguo_parts=yuqi_chengguo_parts,
                yanjiu_jichu_parts=yanjiu_jichu_parts if yanjiu_jichu_success else "",
                gongzuo_tiaojian_parts=gongzuo_tiaojian_parts if gongzuo_tiaojian_success else "",
                keyan_xiangmu_parts=keyan_xiangmu_parts if keyan_xiangmu_success else "",
                nsfc_xiangmu_parts=nsfc_xiangmu_parts if nsfc_xiangmu_success else "",
                qita_shuoming=qita_shuoming if other_section_success else None
            )
            logger.info(f"申请书导出完成，总长度: {len(full_markdown)} 字符, {len(full_markdown.encode('utf-8'))} 字节")
            logger.info(f"Full markdown: {full_markdown}")
            
            # 额外检查：确保内容完整性
            if not full_markdown:
                logger.error("致命错误：full_markdown为空！")
                raise ValueError("生成的申请书内容为空")
            
            if len(full_markdown) < 1000:
                logger.warning(f"警告：full_markdown长度异常短：{len(full_markdown)} 字符")
            
            yield {
                'agent': 'article_nsfc_writing',
                'type': 'article_writing',
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
            'sender': 'assistant',
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
                logger.warning(f"outline包含非字典根元素: {type(root).__name__} = {str(root)[:100]}")

        return "\n".join(lines)
    
    
    def _fix_less_than_symbol(self, text: str) -> str:
        """将 < 转换为 &lt; 用于前端Markdown渲染，导出Word时会转换回来"""
        if not text:
            return text
        text = text.replace('<', '&lt;')
        return text
    
    async def _export_full_proposal(
        self, sa,
        lixiang_yiju_parts=None,
        kexue_wenti="",
        yanjiu_mubiao="",
        yanjiu_neirong="",
        jishu_luxian_parts="",
        yanjiu_fangan_parts="",
        guanjian_jishu_parts="",
        kexingxing_parts="",
        chuangxin_parts="",
        yanjiu_jihua_parts="",
        yuqi_chengguo_parts="",
        yanjiu_jichu_parts="",
        gongzuo_tiaojian_parts="",
        keyan_xiangmu_parts="",
        nsfc_xiangmu_parts="",
        qita_shuoming=None
    ):
        """将所有生成的内容导出为完整的Markdown和Word文档"""
        
        # 修复字符串参数中的 < 符号（lixiang_yiju_parts和qita_shuoming是列表，通过_render_markdown处理）
        kexue_wenti = self._fix_less_than_symbol(kexue_wenti)
        yanjiu_mubiao = self._fix_less_than_symbol(yanjiu_mubiao)
        yanjiu_neirong = self._fix_less_than_symbol(yanjiu_neirong)
        jishu_luxian_parts = self._fix_less_than_symbol(jishu_luxian_parts)
        yanjiu_fangan_parts = self._fix_less_than_symbol(yanjiu_fangan_parts)
        guanjian_jishu_parts = self._fix_less_than_symbol(guanjian_jishu_parts)
        kexingxing_parts = self._fix_less_than_symbol(kexingxing_parts)
        chuangxin_parts = self._fix_less_than_symbol(chuangxin_parts)
        yanjiu_jihua_parts = self._fix_less_than_symbol(yanjiu_jihua_parts)
        yuqi_chengguo_parts = self._fix_less_than_symbol(yuqi_chengguo_parts)
        yanjiu_jichu_parts = self._fix_less_than_symbol(yanjiu_jichu_parts)
        gongzuo_tiaojian_parts = self._fix_less_than_symbol(gongzuo_tiaojian_parts)
        keyan_xiangmu_parts = self._fix_less_than_symbol(keyan_xiangmu_parts)
        nsfc_xiangmu_parts = self._fix_less_than_symbol(nsfc_xiangmu_parts)
        
        markdown_parts = []
        
        # 标题和项目信息
        blueprint = getattr(sa, "nsfc_selected_blueprint", {}) or {}
        title = blueprint.get("title", "国自然申请书")
        fund_type = sa.query_params.get('fund_type', '青年科学基金项目')
        duration_years = sa.query_params.get('duration_years', 3)
        
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        
        markdown_parts.append("![nsfc logo](https://noahai-online.obs.cn-east-3.myhuaweicloud.com/nsfc_logo.png)\n（国家自然科学基金官方正文 Word 模板，请仅在指定区域编辑；**标题不可修改**，否则可能导出失败。）\n\n")
        markdown_parts.append(f"# {indent}&nbsp;&nbsp;国家自然科学基金申请书\n\n")
        markdown_parts.append("&nbsp;\n\n")
        
        
        markdown_parts.append(f"#### {indent}资助类别：{fund_type}\n")
        markdown_parts.append(f"#### {indent}亚类说明：______________________________\n")
        markdown_parts.append(f"#### {indent}附注说明：______________________________\n")
        markdown_parts.append(f"#### {indent}项目名称：{title}\n")
        markdown_parts.append(f"#### {indent}申请者：_____________ 电话：_____________\n")
        markdown_parts.append(f"#### {indent}依托单位：______________________________\n")
        markdown_parts.append(f"#### {indent}通讯地址：______________________________\n")
        markdown_parts.append(f"#### {indent}邮政编码：___________ 单位电话：___________\n")
        markdown_parts.append(f"#### {indent}电子邮件：______________________________\n\n")
        markdown_parts.append(f"#### {indent}申报日期：{datetime.now().strftime('%Y年%m月%d日')}\n\n")
        markdown_parts.append("\n---\n\n")
        
        # 所有内容都通过参数传入，不再从sa对象获取
        
        logger.info(f"文档组装：" + 
                   f"lixiang_yiju_parts={'有内容' if lixiang_yiju_parts else '空'}, " +
                   f"kexue_wenti={'有内容' if kexue_wenti else '空'}, " +
                   f"yanjiu_mubiao={'有内容' if yanjiu_mubiao else '空'}, " +
                   f"yanjiu_neirong={'有内容' if yanjiu_neirong else '空'}, " +
                   f"jishu_luxian_parts={'有内容' if jishu_luxian_parts else '空'}, " +
                   f"yanjiu_fangan_parts={'有内容' if yanjiu_fangan_parts else '空'}, " +
                   f"guanjian_jishu_parts={'有内容' if guanjian_jishu_parts else '空'}, " +
                   f"kexingxing_parts={'有内容' if kexingxing_parts else '空'}, " +
                   f"chuangxin_parts={'有内容' if chuangxin_parts else '空'}, " +
                   f"yanjiu_jihua_parts={'有内容' if yanjiu_jihua_parts else '空'}, " +
                   f"yuqi_chengguo_parts={'有内容' if yuqi_chengguo_parts else '空'}, " +
                   f"yanjiu_jichu_parts={'有内容' if yanjiu_jichu_parts else '空'}, " +
                   f"gongzuo_tiaojian_parts={'有内容' if gongzuo_tiaojian_parts else '空'}, " +
                   f"keyan_xiangmu_parts={'有内容' if keyan_xiangmu_parts else '空'}, " +
                   f"nsfc_xiangmu_parts={'有内容' if nsfc_xiangmu_parts else '空'}, " +
                   f"qita_shuoming={'有内容' if qita_shuoming else '空'}")
        
        full_markdown = "".join(markdown_parts)
        logger.info(f"markdown_parts 拼接完成，当前长度: {len(full_markdown)} 字符")
        
        # 2026新模板：根据fund_type决定标题格式（面上项目有冒号，青年基金没有冒号）
        colon_suffix = "：" if fund_type == '面上项目' else ""
        
        # 2026新模板：第一章 - 立项依据（独立章节）
        full_markdown += f"\n\n## （一）立项依据{colon_suffix}\n\n"
        full_markdown += "（为什么要开展此项研究，研究的科学技术价值如何）\n\n"
        
        # 项目的立项依据（研究意义+研究现状+参考文献）
        if lixiang_yiju_parts:
            rendered_lixiang = sa._render_markdown(lixiang_yiju_parts, level_offset=0)
            logger.info(f"立项依据渲染完成，长度: {len(rendered_lixiang)} 字符")
            full_markdown += rendered_lixiang
            logger.info(f"添加立项依据后总长度: {len(full_markdown)} 字符")

        # 添加第二章：研究内容
        logger.info(f"准备添加第二章，当前总长度: {len(full_markdown)} 字符")

        full_markdown += f"\n\n## （二）研究内容{colon_suffix}\n\n"
        full_markdown += "（提纲不做限制，请按照研究工作的自身逻辑撰写。应提炼出特色与创新点、年度研究计划）\n\n"

        if kexue_wenti or yanjiu_mubiao or yanjiu_neirong:
            full_markdown += "\n\n### 1. 项目的研究内容、研究目标，以及拟解决的关键科学问题；\n\n"

            if yanjiu_neirong:
                full_markdown += "#### 1.1 研究内容\n\n"
                full_markdown += yanjiu_neirong + "\n\n"

            if yanjiu_mubiao:
                full_markdown += "#### 1.2 研究目标\n\n"
                full_markdown += yanjiu_mubiao + "\n\n"

            if kexue_wenti:
                full_markdown += "#### 1.3 拟解决的关键科学问题\n\n"
                full_markdown += kexue_wenti + "\n\n"

        if jishu_luxian_parts or yanjiu_fangan_parts or guanjian_jishu_parts or kexingxing_parts:
            full_markdown += "\n### 2. 拟采取的研究方案（包括研究方法、技术路线、实验手段、关键技术等说明）；\n\n"
            
            if jishu_luxian_parts:
                full_markdown += "#### 2.1 技术路线\n\n"
                full_markdown += jishu_luxian_parts + "\n\n"

            if yanjiu_fangan_parts:
                full_markdown += "#### 2.2 研究方案\n\n"
                full_markdown += yanjiu_fangan_parts + "\n\n"
            
            if guanjian_jishu_parts:
                full_markdown += "#### 2.3 关键技术\n\n"
                full_markdown += guanjian_jishu_parts + "\n\n"

        if chuangxin_parts:
            full_markdown += "\n### 3. 本项目的特色与创新之处；\n\n"
            full_markdown += chuangxin_parts + "\n\n"

        if yanjiu_jihua_parts or yuqi_chengguo_parts:
            full_markdown += "\n### 4. 年度研究计划及预期研究结果（包括拟组织的重要学术交流活动、国际合作与交流计划等）。\n\n"

            if yanjiu_jihua_parts:
                full_markdown += "#### 4.1 年度研究计划\n\n"
                full_markdown += yanjiu_jihua_parts + "\n\n"
            
            if yuqi_chengguo_parts:
                full_markdown += "#### 4.2 预期研究成果\n\n"
                full_markdown += yuqi_chengguo_parts + "\n\n"
        
        # 添加第三章：研究基础与工作条件
        logger.info(f"准备添加第三章，当前总长度: {len(full_markdown)} 字符")
        if yanjiu_jichu_parts or gongzuo_tiaojian_parts or keyan_xiangmu_parts or nsfc_xiangmu_parts:
            full_markdown += f"\n\n## （三）研究基础{colon_suffix}\n\n"
            
            # 1. 研究基础
            full_markdown += "### 1．研究基础与可行性分析（与本项目相关的研究工作积累和已取得的研究工作成绩，研究风险的应对措施等）；\n\n"

            if yanjiu_jichu_parts:
                full_markdown += "#### 1.1 研究基础\n\n"
                full_markdown += yanjiu_jichu_parts + "\n\n"

            if kexingxing_parts:
                full_markdown += "#### 1.2 可行性分析\n\n"
                full_markdown += kexingxing_parts + "\n\n"
            
            # 2. 工作条件
            if gongzuo_tiaojian_parts:
                logger.info(f"添加工作条件，长度: {len(gongzuo_tiaojian_parts)} 字符")
                full_markdown += "### 2．工作条件（包括已具备的实验条件，尚缺少的实验条件和拟解决的途径，包括利用国家实验室、全国重点实验室和部门重点实验室等研究基地的计划与落实情况）；\n\n"
                full_markdown += gongzuo_tiaojian_parts + "\n\n"
                logger.info(f"添加工作条件后总长度: {len(full_markdown)} 字符")
            
            # 3. 正在承担的科研项目情况
            if keyan_xiangmu_parts:
                logger.info(f"添加科研项目情况，长度: {len(keyan_xiangmu_parts)} 字符")
                if fund_type == '面上项目':
                    full_markdown += "### 3. 正在承担的与本项目相关的科研项目情况（申请人和主要参与者正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；\n\n"
                else:
                    full_markdown += "### 3. 正在承担的与本项目相关的科研项目情况（申请人正在承担的与本项目相关的科研项目情况，包括国家自然科学基金的项目和国家其他科技计划项目，要注明项目的资助机构、项目类别、批准号、项目名称、获资助金额、起止年月、与本项目的关系及负责的内容等）；\n\n"
                full_markdown += keyan_xiangmu_parts + "\n\n"
                logger.info(f"添加科研项目情况后总长度: {len(full_markdown)} 字符")
            
            # 4. 完成国家自然科学基金项目情况
            if nsfc_xiangmu_parts:
                logger.info(f"添加已完成基金项目，长度: {len(nsfc_xiangmu_parts)} 字符")
                full_markdown += "### 4. 完成国家自然科学基金项目情况（对申请人负责的前一个已资助期满的科学基金项目（项目名称及批准号）完成情况、后续研究进展及与本申请项目的关系加以详细说明。另附该项目的研究工作总结摘要（限500字）和相关成果详细目录）。\n\n"
                full_markdown += nsfc_xiangmu_parts + "\n\n"
                logger.info(f"添加已完成基金项目后总长度: {len(full_markdown)} 字符")
        
        # 添加第四章：其他说明
        logger.info(f"准备添加第四章，当前总长度: {len(full_markdown)} 字符")
        if fund_type == '面上项目':
            official_qita_shuoming_titles = [
                "1. 申请人同年申请不同类型的国家自然科学基金项目情况（列明同年申请的其他项目的项目类型、项目名称信息，并说明与本项目之间的区别与联系；已收到自然科学基金委不予受理或不予资助决定的，无需列出）。",
                "2. 具有高级专业技术职务（职称）的申请人或者主要参与者是否存在同年申请或者参与申请国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，申请或参与申请的其他项目的项目类型、项目名称、单位名称、上述人员在该项目中是申请人还是参与者，并说明单位不一致原因。",
                "3. 具有高级专业技术职务（职称）的申请人或者主要参与者是否存在与正在承担的国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，正在承担项目的批准号、项目类型、项目名称、单位名称、起止年月，并说明单位不一致原因。",
                "4. 申请人和主要参与者同年以不同专业技术职务（职称）申请或参与申请科学基金项目的情况（应详细说明原因）。",
                "5. 申请人在撰写本申请书时使用生成式人工智能的情况，请详细说明申请书中使用的位置和内容。",
                "6. 其他（包括但不限于使用以他人名义申报过的申请书；如有，请详细说明）。"
            ]
        else:
            official_qita_shuoming_titles = [
                "1. 申请人同年申请不同类型的国家自然科学基金项目情况（列明同年申请的其他项目的项目类型、项目名称信息，并说明与本项目之间的区别与联系；已收到自然科学基金委不予受理或不予资助决定的，无需列出）。",
                "2. 具有高级专业技术职务（职称）的申请人是否存在同年申请或者参与申请国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，申请或参与申请的其他项目的项目类型、项目名称、单位名称、上述人员在该项目中是申请人还是参与者，并说明单位不一致原因。",
                "3. 具有高级专业技术职务（职称）的申请人是否存在与正在承担的国家自然科学基金项目的单位不一致的情况；如存在上述情况，列明所涉及人员的姓名，正在承担项目的批准号、项目类型、项目名称、单位名称、起止年月，并说明单位不一致原因。",
                "4. 同年以不同专业技术职务（职称）申请或参与申请科学基金项目的情况（应详细说明原因）。",
                "5. 申请人在撰写本申请书时使用生成式人工智能的情况，请详细说明申请书中使用的位置和内容。",
                "6. 其他（包括但不限于使用以他人名义申报过的申请书；如有，请详细说明）。"
            ]
        if qita_shuoming:
            if isinstance(qita_shuoming, list):
                for idx, section in enumerate(qita_shuoming):
                    if not isinstance(section, dict):
                        continue
                    if idx < len(official_qita_shuoming_titles):
                        section["title"] = official_qita_shuoming_titles[idx]
                
            full_markdown += "\n\n" + sa._render_markdown(qita_shuoming, root_title=f"（四）其他需要说明的情况{colon_suffix}")
        
        logger.info(f"添加第四章后总长度: {len(full_markdown)} 字符")
        return full_markdown
    
    async def _process_user_docs(self, django_files):
        da = self.nsfc_docs_analyzer
        da.load_raw_files_from_request(django_files)

        await da.convert_documents()
        await da.batch_summarize_docs()
        
        self.summarized_docs = da.summarized_docs
        return da.summarized_docs 
        