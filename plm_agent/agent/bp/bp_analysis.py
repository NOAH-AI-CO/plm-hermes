import os
import json
import re
import logging
import asyncio
from urllib.parse import quote
import logging

from agent.core.preset import AgentPreset
from llm.gcp_models import Gemini31Pro, Gemini3Flash
from llm.base_model import BaseLLM
from agent.explore.schema import MindSearchResponse, ProcessingType, SearchNode, SearchType, WebSearchLink, WebSearchSubject
from agent.explore.helper import MindSearchHelper
from agent.bp.pp import fetch_context, select_sections
from utils.core.exception import UnexpectedException
from agent.human_in_loop.utils import *
from utils.utils.attachment import AttachmentManager
from config import settings
from datetime import datetime, timedelta, timezone as tz
from agent.bp.db import read_bp_context, write_bp_context
from agent.bp.evaluate import evaluate_bp_json_text, key_mapping
from pathlib import Path

logger = logging.getLogger(__name__)

# 设置 Google Cloud 环境变量（如果需要）
gcp_key_path = "/Users/chenzichu/Desktop/NoahServer/NoahAgent/noah_agent/gcp_key.json"
if not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''):
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = gcp_key_path

os.environ['GOOGLE_CLOUD_PROJECT'] = "noahai-440408"
os.environ['GOOGLE_CLOUD_LOCATION'] = "global"
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = "true"


# 定义 BP 解析的 JSON Schema
bp_extraction_schema = {
    "type": "OBJECT",
    "properties": {
        "company_name": {
            "type": "STRING",
            "description": "公司名称"
        },
        "company_intro": {
            "type": "STRING",
            "description": "公司简介，包括公司定位、主营业务、核心价值等"
        },
        "team_info": {
            "type": "STRING",
            "description": "团队情况，包括核心团队成员、背景、经验等"
        },
        "tech_platform": {
            "type": "STRING",
            "description": "技术平台，包括核心技术、技术优势、技术壁垒等"
        },
        "pipeline_info": {
            "type": "STRING",
            "description": "管线情况，包括产品管线、研发进展、临床阶段等"
        },
        "financing_info": {
            "type": "STRING",
            "description": "融资情况，包括融资轮次、融资金额、投资方、估值等"
        }
    },
    "required": [
        "company_name",
        "company_intro",
        "team_info",
        "tech_platform",
        "pipeline_info",
        "financing_info"
    ]
}

bp_summary_extraction_schema = {
     "type": "OBJECT",
    "properties": {
        "team_analysis": {"type": "STRING", "description": "团队-AI分析"},
        "tech_analysis": {"type": "STRING", "description": "技术平台-AI分析"},
        "pipeline_analysis": {"type": "STRING", "description": "管线情况-AI分析"},
        "financing_analysis": {"type": "STRING", "description": "融资情况-AI分析"},
        "risk_analysis": {"type": "STRING", "description": "风险提示-AI分析"},
        "overall_analysis": {"type": "STRING", "description": "综合评估-AI分析"}
    },
    "required": ["team_analysis", "tech_analysis", "pipeline_analysis", "financing_analysis", "risk_analysis", "overall_analysis"]

}

bp_assessment_schema = {
    "type": "OBJECT",
    "properties": {
        "team_assessment": {"type": "STRING", "description": "团队-AI评估（一句话）"},
        "tech_assessment": {"type": "STRING", "description": "技术-AI评估（一句话）"},
        "pipeline_assessment": {"type": "STRING", "description": "管线-AI评估（一句话）"},
        "financing_assessment": {"type": "STRING", "description": "融资情况-AI评估（一句话）"},
        "overall_assessment": {"type": "STRING", "description": "综合评估-AI评估"},
        "suggestion": {"type": "STRING", "description": "跟进建议-AI评估（一句话）"}
    },
    "required": ["team_assessment", "tech_assessment", "pipeline_assessment", "financing_assessment", "overall_assessment", "suggestion"]
}


async def extract_bp_info_no_limit(markdown_text: str) -> dict:
    """
    Stage 1: 从商业BP的markdown格式文本中提取信息（无字数限制）
    Prompt: bp-提取（非字数限制）1.0
    """
    try:
        model = Gemini3Flash()
        
        prompt = f"""# Role
你是一位资深的生物医药/硬科技行业投资分析师，具备极强的信息解构与数据归纳能力。

# Task
请从提供的商业计划书 (BP) Markdown 文本中，进行“地毯式”的信息提取。不要考虑字数限制，核心目标是：**在结构化输出的同时，尽可能保留所有关键细节、技术参数和原始数据。**

# Extraction Framework (深度提取框架)

1. **公司名称**：
   - 包含正式中英文全称、简称、品牌名。

2. **公司定位与简介 (全量提取)**：
   - 提取公司的愿景、使命、核心业务板块。
   - 详细列出公司解决的行业痛点、核心价值主张（Value Proposition）。
   - 提取公司所处的细分赛道位置。

3. **核心团队背景 (无损提取)**：
   - 提取所有高管及核心技术人员：姓名 | 职位。
   - 详细学术背景（本科至博士学校、专业）。
   - 详细工作履历（曾任职企业、具体负责的项目/角色、主导过哪些产品的临床或上市）。
   - 荣誉奖励（论文发表、专利拥有量、国家级头衔等）。

4. **技术平台与研发优势 (技术细节提取)**：
   - 提取核心技术原理、平台名称、底层逻辑。
   - **重点**：记录所有技术突破点、壁垒说明。
   - **关键数据**：提取平台相关的验证数据、实验对比（如与竞品的对比倍数、渗透率、稳定性提升百分比等）。

5. **产品管线与研发进展 (全线扫描)**：
   - 按管线编号（如 OC-101）依次列出。
   - **包含维度**：靶点（Target）、作用机制（MoA）、适应症（Indication）、Modality（单抗/ADC/小分子等）。
   - **研发状态**：PCC、IND-Enabling、临床阶段（Phase I/II/III）。
   - **核心数据**：提取关键的动物实验（In Vivo）或临床试验数据（如 TGI、ORR、DCR、完全缓解率、安全性指标等）。

6. **融资与财务情况 (事实提取)**：
   - 历史所有融资轮次、具体时间、融资金额、领投及跟投方名单。
   - 公司估值（投前/投后）。
   - 本轮融资计划：拟融金额、出让比例、资金用途明细。

# Requirements
- **不要概括**：如果文中提到了具体数值、百分比或专业术语，请原样保留。
- **结构化**：使用清晰的 Markdown 层级（##, ###, -）进行排版。
- **标注缺失**：如果文档中完全未提及某维度，请写“该项在原文中未涉及”。

# BP原始文本内容
{markdown_text}
"""
        
        response_text = await model(
            user_prompt=prompt,
            json_mode=True,
            response_schema=bp_extraction_schema,
            temperature=0,
            thinking_budget="low"
        )
        
        logger.info(f"BP extraction response text: {response_text}")
        json_content = json.loads(response_text)
        logger.info(f"Parsed JSON content: {json_content}")
        
        return json_content
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        logger.error(f"Response text: {response_text if 'response_text' in locals() else 'N/A'}")
        # 返回默认结构，避免程序崩溃
        return {
            "company_name": "",
            "company_intro": "",
            "team_info": "",
            "tech_platform": "",
            "pipeline_info": "",
            "financing_info": ""
        }
    except Exception as e:
        logger.error(f"Error extracting BP info: {e}")
        raise

# Backward compatibility alias
extract_bp_info = extract_bp_info_no_limit

async def extract_bp_info_with_limit(bp_info_no_limit: dict) -> dict:
    """Stage 2: BP关键信息（含字数限制）"""
    try:
        model = Gemini31Pro()
        formatted_res = []
        for k, v in bp_info_no_limit.items():
            display_key = key_mapping.get(k, k)
            formatted_res.append(f"**{display_key}**:\n{v}")
        formatted_bp_info_no_limit = "\n\n".join(formatted_res)
        prompt = f"""# Role
你是一位专业的生物医药行业研究员，擅长将零散素材转化为客观、严谨、基于事实的结构化摘要。

# Style Requirement: 纯客观陈述
1. **去修饰化**：严禁使用“领先”、“顶尖”、“卓越”、“颠覆性”等主观形容词。
2. **事实驱动**：所有表述必须基于数据、实验结果、学术/职场履历或融资事实。
3. **陈述语调**：使用中性、平铺直叙的职业术语（如：该技术通过...实现...，实验数据显示...）。
4. **术语标准**：准确引用靶点（Target）、适应症（Indication）、临床阶段、统计学指标等。

# Constraints & Word Counts (强制执行)
请在严格遵守以下字数上限的同时，**尽量填满字数空间**以确保信息密度：

1. **公司名称**：正式全称。
2. **公司简介 (140-150字)**：包含公司定位、业务范围、核心技术定义、解决的临床痛点。
3. **团队情况 (240-260字)**：格式：姓名 | 职位 + 详细背景。客观列出学历、过往任职、主导项目及科研成果。
4. **技术平台 (240-260字)**：包含原理、作用机制、关键验证数据、专利布局。突出客观差异。
5. **管线情况 (330-350字)**：包含编号、MoA、适应症、进度、关键动物/临床数据。详细陈述事实。
6. **融资情况 (240-260字)**：包含时间、轮次、金额、投资方、估值及具体资金投向。

---

# Style Reference (风格参考锚点)
> [公司名称: 艾威药业 (IVIEW Therapeutics Inc.)

公司简介：艾威药业是一家立足中美、面向全球的创新眼科药物研发领军企业，致力于通过原创递送技术与前沿靶点发现，构建覆盖全眼科疾病谱的创新药矩阵。公司针对干眼症起效慢、病毒性结膜炎无药可用、青光眼依从性差等临床痛点，开发了包括TRPM8激动剂、M1受体拮抗剂及长效基因疗法在内的多元化管线。凭借Eyelid眼睑递送、i-Gel离子敏感凝胶及纳米胶束等核心平台，艾威药业实现了药物渗透率与生物利用度的跨越式提升，旨在为全球患者提供更安全、更便捷、更具临床获益的眼科治疗方案，填补多项国际临床空白。

团队情况: Bo Liang, PhD, MBA | 创始人、董事长兼CEO
•连续创业者，曾将项目以3亿美元现金出售给世界500强企业；
•拥有北京大学、宾夕法尼亚大学及纽约大学斯特恩商学院背景，具备深厚的学术底蕴与卓越的商业化落地能力；
•核心团队曾主导开发6个重磅新药上市，累计年销售额超50亿美元。
Houman D. Hemmati, MD, PhD | 董事兼首席医学顾问
•资深眼科医生，曾任Vyluma/Nevaka首席医疗官，拥有极强的临床转化与医学策略经验。

技术平台: 艾威药业构建了三大差异化递送平台与一个前沿基因治疗平台。Eyelid Drug Delivery：颠覆性眼睑擦拭给药技术，药物经上眼睑血管流向海绵窦或经巩膜渗透，避开眼表刺激并解决眼后部递送难题。PK数据显示，给药4小时后视网膜/脉络膜药物浓度反超传统滴眼液。
i-Gel离子敏感型原位凝胶：利用入眼后溶胶-凝胶转化原理，实现药物长效缓释，显著降低刺激性并提升生物利用度。
Nanomicelle纳米胶束：通过自组装疏水核壳结构，大幅提高环孢素等难溶药物的溶解度与组织穿透力。
创新基因治疗平台：采用scAAV载体与人源化启动子，结合突变衣壳技术，特异性靶向小梁网组织，转染效率较传统技术提升10倍以上，为青光眼等慢性眼病提供“一次给药、长期有效”的解决方案。

管线情况: 
1. IVW-1001 (干眼症, Phase III Ready)：First-in-Class TRPM8激动剂，通过眼睑给药激活冷觉感受器促进自然泪液分泌。临床II期数据显示，0.2%剂量组在第4周显著改善角膜荧光素染色（p=0.0499），SANDE评分显著降低（p=0.0017），实现5分钟内极速起效且凉感持续2小时，安全性极佳，计划2027年提交NDA。
2. IVIEW-1201/1201D (结膜炎, Phase III)：基于PVP-I的原位凝胶，覆盖病毒、细菌及真菌。细菌性结膜炎II期治愈率达35.9%（优于氧氟沙星26.6%）；病毒性管线已获FDA三期IND默许，参考数据显示治愈率高达95.8%。
3. IVW-1802 (近视, IND-Enabling)：M1受体选择性拮抗剂，相比阿托品具有更优的安全性，不抑制DNA合成，散瞳副作用极小，预计2026年初申报IND。
4. IVIEW-1701 (白内障术后炎症)：纳米胶束滴眼液，获FDA允许直接开展III期临床，预计2025年底申报。
5. IVW-2001 (青光眼, IIT阶段)：scAAV2递送dnRhoA基因，动物模型显示降低眼压达20%-50%，2025年启动IIT，2026年申报FDA IND。

融资情况: 艾威药业历史累计筹集约4,000万美元，股东阵容豪华，包括比邻星创投、同创伟业、华海药业、分享投资、ALPHA BIOVENTURE及BioAdvance等知名机构，并获美国SBIR近百万美元资助。目前公司正式启动4,000万美元B轮融资，旨在加速核心管线的临床推进与商业化布局。
资金用途规划：
临床开发（2,500万美元）：重点投入IVW-1001的全球多中心三期临床试验（1,800万）、IVW-1802的IND准备工作（300万）及IVIEW-1201D的临床推进（400万）。
运营与研发（800万美元）：用于中美双研发中心的日常运营、知识产权全球布局及早期基因治疗平台的持续迭代。
资本市场准备（700万美元）：用于IPO规范化审计、法律合规及上市前准备，公司计划于2026年启动香港HKEX或美国NASDAQ上市进程，并同步寻求与全球大药企的BD授权合作。]

---

# Source Material (原始素材内容)
{formatted_bp_info_no_limit}

---

# Final Action
请参考【风格参考锚点】的语感，对【原始素材内容】进行二次加工。注意：在确保字数接近上限的同时，必须剔除所有宣传性、夸张性的主观表述。
"""
        response_text = await model(
            user_prompt=prompt,
            json_mode=True,
            response_schema=bp_extraction_schema,
            temperature=0,
            thinking_budget="low"
        )
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in extract_bp_info_with_limit: {e}")
        return bp_info_no_limit


attachment_manager: AttachmentManager = AttachmentManager()

async def batch_process_bp(bp_requests: list = []):
    files = [f["file"] for f in bp_requests]
    bp_ids = [f["bp_id"] for f in bp_requests]
    attachments = []
    attachments = attachment_manager.fetch_attachments(files, False)
    context = await fetch_context([att.get('url', '') for att in attachments],
                    [att.get('name', "Untitled") for att in attachments],
                    [str(att.get('id', '')) for att in attachments],
                        include_toc=True, detailed=4)
    
    coroutines = []
    for i, bp_id in enumerate(bp_ids):
        content, toc = context[i]
        url = attachments[i].get('url', '')
        logger.info(f"bp content preview: {str(content)[:1000]}")
        coroutines.append(process_bp(content=content, bp_id=bp_id, toc=toc, url=url))
    
    return await asyncio.gather(*coroutines)


async def process_bp(content=None, bp_id=None, toc=None, url=None):
    try:
        bp_context = await read_bp_context(bp_id)  # 读取现有上下文，确保数据库连接正常
        status = bp_context.get("status", "")
        if status == "done":
            logger.info(f"BP {bp_id} already processed. Skipping.")
            return

        pages = content if isinstance(content, list) else [content]
        
        if status == "extracted" or status == "analyzing":
            logger.info(f"BP {bp_id} already extracted. Proceeding to evaluation.")
            
            # Helper to remove citation links like [1](val#page=1&text=foo)
            def remove_citations(text):
                if not text: return ""
                # This regex matches [digits](...) where the part inside () contains #page=
                return re.sub(r'\[\d+\]\([^)]*#page=[^)]*\)', '', text)

            json_content = {
                key: remove_citations(bp_context.get(key, "")) 
                for key in bp_extraction_schema["properties"].keys()
            }
            
            # Stage 3-5: Agent Summary, Extraction and Evaluation
            evaluation_result = await evaluate_bp_json_text(json_content)
            ctx = {"status": "done", **evaluation_result}
            ctx['analyzed_at'] = datetime.now(tz=tz(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
            await write_bp_context(ctx, bp_id)
            return

        full_text = "\n".join(pages) if isinstance(content, list) else pages[0]
        
        ctx = {"status": "extracting"}
        if isinstance(pages, list):
            ctx['page_count'] = len(pages)
        await write_bp_context(ctx, bp_id)

        # Stage 1: 无字数限制提取
        # Use existing context if available to skip step (optional optimization, but let's re-run or check specific keys)
        # For simplicity, assuming full re-run if not 'done' or specific keys missing.
        # But to be safe with existing 'extracted' status (legacy), we should handle it.
        
        bp_info_no_limit = bp_context.get("bp_info_no_limit")
        if not bp_info_no_limit:
            # If migrating from legacy, check root keys? 
            # If legacy has keys but not 'bp_info_no_limit', treat legacy keys as no_limit?
            # Or just re-extract. Re-extract is safer for the new flow.
            bp_info_no_limit = await extract_bp_info_no_limit(full_text)
            await write_bp_context({"bp_info_no_limit": bp_info_no_limit}, bp_id)

        # Stage 2: 含字数限制提取
        bp_info_with_limit = await extract_bp_info_with_limit(bp_info_no_limit)
        
        # Identify related pages and add citations to bp_info_with_limit
        fields_to_cite = ["company_intro", "team_info", "tech_platform", "pipeline_info", "financing_info"]
        citation_logs = {}

        async def process_single_field(field):
            val = bp_info_with_limit.get(field)
            if val:
                related_pages = await find_related_pages(val, toc, pages)
                if related_pages:
                    cited_text = await insert_citations(val, related_pages, url)
                    return field, val, cited_text
            return field, None, None

        citation_results = await asyncio.gather(*[process_single_field(f) for f in fields_to_cite])
        
        for field, original_val, cited_text in citation_results:
            if cited_text:
                citation_logs[field] = {"before": original_val, "after": cited_text}
                bp_info_with_limit[field] = cited_text
        
        if citation_logs:
            log_dir = Path("logs/bp_citations")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"bp_{bp_id}_citations.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(citation_logs, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved citation logs to {log_file}")
            
        # Write Stage 2 result to context (this matches the legacy root keys for UI compatibility)
        # Update: We should keep the legacy keys populated with the "With Limit" version for UI.
        update_data = {"status": "extracted", **bp_info_with_limit}
        update_data['extracted_at'] = datetime.now(tz=tz(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        await write_bp_context(update_data, bp_id)
        
    except Exception as e:
        logger.error(f"process bp error: {str(e)}")
        raise e
    
async def find_related_pages(report_section, bp_toc, bp_pages):
    """
    Select related pages from BP using TOC matching and return as dict list.

    Args:
        report_section: Text from a BP evaluation report section.
        bp_toc: BP document table of contents.
        bp_pages: List of BP page texts (1-based indexing implied in page ranges).

    Returns:
        List of dicts: [{"page": str, "title": str, "text": str}, ...]
    """
    logger.info(f"insert_citations called: report_section/{report_section[:100]} bp_toc/{str(bp_toc)[:100]} bp_pages/{str(bp_pages)[:100]}")
    if not report_section or not bp_toc or not bp_pages:
        return []

    if not isinstance(bp_pages, list):
        logger.warning("bp_pages should be a list of page strings")
        return []

    try:
        selected_sections = await select_sections(report_section, bp_toc)
    except Exception as e:
        logger.error(f"select_sections failed: {e}")
        return []

    if not selected_sections:
        return []

    page_range_map = {}
    for item in selected_sections:
        page_range = item.get("page_range")
        section_title = item.get("section", "")
        if not page_range:
            continue
        page_range_map.setdefault(page_range, []).append(section_title)

    results = []
    for page_range, titles in page_range_map.items():
        try:
            if "-" in page_range:
                start_page, end_page = map(int, page_range.split("-"))
                if start_page < 1:
                    start_page = 1
                if end_page > len(bp_pages):
                    end_page = len(bp_pages)
                if start_page > end_page:
                    continue
                merged_titles = " / ".join([t for t in titles if t]) if titles else ""
                for page_num in range(start_page, end_page + 1):
                    results.append({
                        "page": str(page_num),
                        "title": merged_titles,
                        "text": bp_pages[page_num - 1],
                    })
            else:
                page_num = int(page_range)
                if page_num < 1 or page_num > len(bp_pages):
                    continue
                section_text = bp_pages[page_num - 1]

            merged_titles = " / ".join([t for t in titles if t]) if titles else ""
            if "-" not in page_range:
                results.append({
                    "page": str(page_num),
                    "title": merged_titles,
                    "text": section_text,
                })
        except Exception as e:
            logger.error(f"Error processing page range {page_range}: {e}")
            continue

    return results

async def insert_citations(report_section: str, reference_text: list, url: str) -> str:
    """
    使用 LLM (Gemini) 在报告章节中插入引用。
    引用包含页码和来自参考文本的原始片段。

    Args:
        report_section: 报告章节文本
        reference_text: 参考资料列表，每个元素包含 'page', 'title', 'text'

    Returns:
        str: 插入引用后的文本
    """
    logger.info(f"insert_citations called: report_section/{report_section[:100]} reference_text/{str(reference_text)[:100]}")
    if not report_section or not reference_text:
        return report_section

    try:
        model = Gemini3Flash()

        # 格式化参考资料
        context_str = ""
        for i, ref in enumerate(reference_text):
            p = ref.get('page', 'Unknown')
            t = ref.get('title', 'N/A')
            c = ref.get('text', '')
            context_str += f"Reference {i+1} (Page {p}, {t}): {c}\n\n"

        prompt = f"""你是一名专业的 BP（商业计划书）报告编辑。你的任务是在给定的“报告章节”中插入引用（Citations）。

## 规则：
1. 引用格式：`[Page X: "原文片段"]`。
   - `X` 是参考资料中的页码。
   - `"原文片段"` 是来自参考资料的直接简短引述（控制在 20 个字左右），用于支撑报告中的论点。
2. 插入位置：将引用紧跟在报告章节中对应的句子或断言之后。
3. 文本保持：严禁修改“报告章节”原有的文字内容，只能在合适位置添加引用。
4. 匹配原则：如果没有找到合适的参考资料支撑某部分内容，则不添加引用。
5. 必须返回插入引用后的完整文本。

## 参考资料：
{context_str}

## 报告章节：
{report_section}
"""

        schema = {
            "type": "OBJECT",
            "properties": {
                "cited_report_section": {
                    "type": "STRING",
                    "description": "插入引用后的完整报告章节文本"
                }
            },
            "required": ["cited_report_section"]
        }

        response_text = await model(
            user_prompt=prompt,
            json_mode=True,
            response_schema=schema,
            temperature=0,
            thinking_budget="low"
        )

        if response_text:
            content = json.loads(response_text)
            cited_report_section = content.get("cited_report_section", report_section)
            
            counter = 0
            def replace_citation(m):
                nonlocal counter
                counter += 1
                encoded_text = quote(m.group(2))
                return f'[{counter}]({url}#page={m.group(1)}&text={encoded_text})'
            
            report_section = re.sub(
                r'\[Page\s+(\d+):\s*"([^"]*)"\]',
                replace_citation,
                cited_report_section,
            )
        
        return report_section

    except Exception as e:
        logger.error(f"Error in insert_citations: {e}")
        return report_section
    
    

if __name__ == "__main__":
    pass
    # related_pages = asyncio.run(find_related_pages(report_section, bp_toc, bp_pages))
    # report_section_w_citation = asyncio.run(insert_citations(report_section, related_pages))