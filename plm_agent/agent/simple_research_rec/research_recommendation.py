import logging
import json
import traceback
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai.types import HttpOptions
from google.genai import types

from agent.explore.mindsearch_agent_v3_pubmed import (
    MindSearchPubMedHitlAgent,
    fetch_pubmed_articles_by_existing_logic,
)
from agent.simple_research_rec.output_schema import ResearchReport, llm_response_schema

logger = logging.getLogger(__name__)

RESEARCH_REC_SYSTEM_PROMPT = """你正在协助一位研究人员寻找科研选题推荐。
用户希望探索其感兴趣领域的最新科学文献，识别有潜力的研究方向、知识空白以及值得深入研究的领域。
请在PubMed上全面检索与用户主题相关的近期高质量文献，
并对当前研究现状提供全面综述。
"""

QUERY_SUMMARY_PROMPT = """你是一位资深医学科研顾问。请基于用户查询与检索结果，先输出一个“查询摘要”模块。

用户查询：{query}

请严格按以下格式输出，使用中文：

经分析您的临床诉求，核心矛盾聚焦于：<一句话总结核心问题>。
您提出了多维度发散问题，AI 提炼为以下关键方向：

- <方向1>
- <方向2>
- <方向3>
- <方向4，可选>

要求：
1) 方向要具体、可研究，不要空泛。
2) 3-4条即可。
3) 不要添加“参考文献”小节。
"""

REPORT_PROMPT = """你是一位科研顾问。请根据以下PubMed文献检索结果，针对用户的查询生成一份结构化的科研选题推荐报告。

用户查询：{query}

查询摘要（上一步已生成）：
{query_summary}

PubMed检索结果：
{pubmed_result}

你的报告必须包含以下内容，并用中文撰写：

## 科研选题推荐报告

### 一、研究现状概述
基于检索到的文献，总结该领域当前的研究现状。

### 二、主要研究发现
重点阐述文献中的重要发现，并以"[作者等, 年份]"或"[PMID: XXXXXXX]"格式在文中标注引用。

### 三、推荐研究方向与方法建议
结合文献，参考已生成的“查询摘要”中所提炼出的关键方向进行开发，设计具体的研究选题与方法建议。**请确保在此处推荐的研究方向数量与“查询摘要”中提炼的关键方向数量保持一致**（例如前面提炼了几个方向，这里就对应提供几个详细选题，做到数量一致，逐一对应展开/参考），不要多出或减少方向。每个方向须将选题描述与方法建议合并填写，不要拆成两个独立章节重复书写。请使用以下格式：

- 方向1
    - 标题：...
    - phase：... (必填，请指定具体的临床试验阶段，如 Phase I, Phase II, Phase III, Phase IV 等)
    - 研究设计：...（研究设计类型及详细说明）
    - 人群及样本：...（目标人群、纳排标准、关键协变量与样本量考量）
    - 暴露/干预：...
    - 对照：...
    - 终点及分析：...（采样方案、主要/次要终点测量方法及统计建模方案）
    - gap：...（核心未解决问题，可选）
    - objective：...（研究目标与价值，必填）

（按此格式依次列出方向2、方向3……）

### 四、参考文献
以结构化格式列出所有引用文献：
- 标题 | 作者 | 期刊 | 年份 | IF/Cite Score (如有) | URL (如有) | Preview (如有，摘要前200字即可) | PMID/PMCID（如有）


请保持内容具体、有据可查、简明扼要。
"""

STRUCTURIZE_PROMPT = """你是一位科研报告结构化助手。请将下面的 Markdown 报告转换为 JSON。

要求：
1) 只返回 JSON，不要附加解释。
2) 字段必须严格匹配给定 schema。
3) research_directions 数量为 3-5 条，每条包含以下所有字段（缺失字段不可省略）：
   title、phase（必填，不可为 null）、研究设计、人群及样本、暴露/干预、对照、终点及分析、gap（可 null）、objective
4) 若文献缺少 PMID，pmid 字段填 null。
5) key_findings 必须为字符串数组；references 必须为对象数组且每项包含 title、authors、journal、year、pmid、url、impact_factor、preview（对于缺失或不可用的字段填 null，切勿省略）。
6) 不要输出 schema 之外的字段。

Markdown 报告如下：
{report_markdown}
"""


@dataclass
class ResearchRecContext:
    pubmed_result: Optional[str] = field(default=None)


def _format_articles_for_prompt(articles: list[dict], document_contents: list[dict]) -> str:
    """Serialise structured PubMed articles into plain text for the Gemini prompt."""
    lines: list[str] = []
    for i, article in enumerate(articles, 1):
        pmid = article.get("uid") or article.get("pmid") or ""
        title = article.get("title") or ""
        summary = article.get("summary") or ""
        journal = article.get("fulljournalname") or ""
        pubdate = article.get("pubdate") or ""
        authors = article.get("authors") or []
        author_names = [a.get("name", "") for a in authors[:3] if isinstance(a, dict)]
        author_str = ", ".join(filter(None, author_names))
        if len(authors) > 3:
            author_str += " et al."
        lines.append(f"{i}. [PMID: {pmid}] {title}")
        if author_str:
            lines.append(f"   Authors: {author_str}")
        
        cite_score = article.get("cite_score") or ""
        url = article.get("url") or (f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")
        preview = summary[:200]
        journal_info = f"   {journal} ({pubdate})"
        if cite_score:
            journal_info += f" | IF/Cite Score: {cite_score}"
        if url:
            journal_info += f" | URL: {url}"
        if preview:
            journal_info += f" | Preview: {preview}"
        lines.append(journal_info)

        if summary:
            lines.append(f"   Abstract: {summary[:600]}")
        lines.append("")

    if document_contents:
        lines.append("--- Full Text Excerpts ---")
        for dc in document_contents:
            dc_pmid = dc.get("pubmed_id") or ""
            dc_title = dc.get("title") or ""
            dc_content = (dc.get("content") or "")[:1200]
            lines.append(f"\n[PMID: {dc_pmid}] {dc_title}")
            lines.append(dc_content)

    return "\n".join(lines)


async def _structurize_report(client: genai.Client, report_markdown: str) -> Optional[dict]:
    """Convert markdown report into structured JSON validated by `ResearchReport`."""
    if not report_markdown.strip():
        return None

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.5-flash",
            contents=STRUCTURIZE_PROMPT.format(report_markdown=report_markdown),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=llm_response_schema(),
                temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        payload = json.loads(response.text or "{}")
        validated = ResearchReport.model_validate(payload)
        return validated.model_dump()
    except Exception as e:
        logger.warning(
            "[ResearchRec] Structurize report failed: %s\n%s",
            str(e),
            traceback.format_exc(),
        )
        return None


async def stream_research_rec(user_query: str):
    """
    Async generator that yields status dicts at each phase and streams the final report.

    Yielded dict shapes:
      {"status": "processing", "content": "<status message>"}                          — progress update
      {"status": "processing", "content": "...", "references": {"articles": [...], "document_contents": [...]}}  — phase 2 start, carries structured PubMed JSON
            {"status": "processing", "content": "...", "summary_section": "..."}          — emitted after query summary is ready
      {"status": "streaming",  "content": "<text chunk>"}                              — incremental report text
    {"status": "done",       "content": "", "json": {...}|None, "references": {"articles": [...], "document_contents": [...]}}     — completion signal
      {"status": "error",      "content": "<message>"}                                 — fatal error
    """
    augmented_query = f"{RESEARCH_REC_SYSTEM_PROMPT}\n\nUser Research Topic: {user_query}"
    client = genai.Client(http_options=HttpOptions(api_version="v1"))

    # Phase 1: Query summarization
    yield {"status": "processing", "content": "正在提炼查询摘要..."}

    query_summary = ""
    summary_prompt = QUERY_SUMMARY_PROMPT.format(
        query=user_query,
    )
    try:
        summary_resp = await client.aio.models.generate_content(
            model="gemini-3.5-flash",
            contents=summary_prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        query_summary = (summary_resp.text or "").strip()
    except Exception as e:
        logger.warning(
            "[ResearchRec] Query summarization failed, fallback to plain summary: %s\n%s",
            str(e),
            traceback.format_exc(),
        )

    if not query_summary:
        query_summary = (
            f"经分析您的临床诉求，核心矛盾聚焦于：{user_query}。\n"
            "您提出了多维度发散问题，AI 提炼为以下关键方向：\n\n"
            f"- 围绕“{user_query}”明确可检验的临床或机制假设\n"
            "- 识别现有证据中的样本、分层与随访不足\n"
            "- 设计可落地的回顾性/前瞻性研究路径"
        )

    summary_section = f"## AI 分析摘要\n\n{query_summary}\n\n"

    # Phase 2: PubMed search
    yield {
        "status": "processing",
        "content": "查询摘要完成，正在检索PubMed相关文献...",
        "summary_section": summary_section,
    }

    pubmed_result = None
    articles: list[dict] = []
    document_contents: list[dict] = []
    try:
        result = await fetch_pubmed_articles_by_existing_logic(
            query=augmented_query,
            language="EN",
        )
        articles = result.get("articles") or []
        document_contents = result.get("document_contents") or []
        pubmed_result = _format_articles_for_prompt(articles, document_contents)
    except Exception as e:
        logger.error(
            "[ResearchRec] fetch_pubmed_articles_by_existing_logic failed: %s\n%s",
            str(e),
            traceback.format_exc(),
        )
        yield {
            "status": "error",
            "content": f"PubMed检索失败：{str(e)}",
            "summary_section": summary_section,
        }
        return

    if not pubmed_result:
        logger.warning("[ResearchRec] No PubMed results returned for query: %s", user_query)
        yield {
            "status": "error",
            "content": "未找到与该查询相关的PubMed文献。",
            "summary_section": summary_section,
        }
        return

    references_payload = {"articles": articles, "document_contents": document_contents}

    # Phase 3: Gemini streaming report generation
    yield {
        "status": "processing",
        "content": "查询摘要已完成，正在生成科研推荐报告...",
        "references": references_payload,
        "summary_section": summary_section,
    }

    report_prompt = REPORT_PROMPT.format(
        query=user_query,
        query_summary=query_summary,
        pubmed_result=pubmed_result,
    )
    report_accumulated = ""
    try:
        async for chunk in await client.aio.models.generate_content_stream(
            model="gemini-3.5-flash",
            contents=report_prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        ):
            if chunk.text:
                report_accumulated += chunk.text
                yield {
                    "status": "streaming",
                    "content": summary_section + report_accumulated,
                    "summary_section": summary_section,
                }

        final_report = summary_section + report_accumulated
        yield {
            "status": "processing",
            "content": "报告已生成，正在结构化结果...",
            "summary_section": summary_section,
        }
        report_json = await _structurize_report(client, final_report)
        if report_json is not None:
            report_json["query_summary"] = query_summary

        yield {
            "status": "done",
            "content": final_report,
            "json": report_json,
            "references": references_payload,
            "summary_section": summary_section,
        }
    except Exception as e:
        logger.error(
            "[ResearchRec] LLM report generation failed: %s\n%s",
            str(e),
            traceback.format_exc(),
        )
        # Fall back: emit raw pubmed result as the report
        fallback_report = summary_section + pubmed_result
        yield {
            "status": "streaming",
            "content": fallback_report,
            "summary_section": summary_section,
        }
        yield {
            "status": "processing",
            "content": "报告已生成，正在结构化结果...",
            "summary_section": summary_section,
        }
        report_json = await _structurize_report(client, fallback_report)
        if report_json is not None:
            report_json["query_summary"] = query_summary

        yield {
            "status": "done",
            "content": fallback_report,
            "json": report_json,
            "references": references_payload,
            "summary_section": summary_section,
        }


async def recommend_research_topic(user_query: str) -> str:
    """
    Convenience wrapper that collects all streamed chunks and returns the full report.
    Used by tests and non-streaming callers.
    """
    report_parts: list[str] = []
    async for event in stream_research_rec(user_query):
        if event["status"] == "streaming":
            report_parts.append(event["content"])
        elif event["status"] == "error":
            if not report_parts:
                return event["content"]
    return "".join(report_parts) or "No relevant PubMed literature was found for the given query."
