import json
from typing import Dict, Any, List, Optional, Set, Iterable, Union
import logging
import asyncio
import re
from dataclasses import asdict

from llm.base_model import BaseLLM
from llm.composite_models import SlotFillingModels
from utils.pubmed_opt.pubmed_vector_search import PubMedVectorSearch
from utils.core.get_json_schema import get_openai_json_schema_v3
from utils.human_in_loop.helpers import function_call_with_retry
from agent.journal_recommendation.journal_query_pubmed import fetch_issns_from_es, search_journals
from agent.journal_recommendation.prompt import ABSTRACT_BILINGUAL_KEYWORDS_PROMPT, ABSTRACT_SUMMARY_PROMPT, INFER_ABSTRACT_RESEARCH_TYPE_PROMPT, JOURNAL_FIT_PROMPT
from agent.journal_recommendation.journal_query_pubmed import keywords_search_pubmed, abstract_search_pubmed
from agent.journal_recommendation.pubmed_search_with_issn import abstract_search_pubmed_with_issn_filter
from agent.journal_recommendation.journal_query_pubmed import fetch_issns_from_es, search_journals
from agent.journal_recommendation.schema import *

logger = logging.getLogger(__name__)

from collections import Counter

AREA_FIT_MAP = {
    "STRONG": 1.0,
    "MODERATE": 0.7,
    "WEAK": 0.3,
    "UNKNOWN": 0.5,
}

TIER_ALIGNMENT_MAP = {
    "WELL_MATCHED": 1.0,
    "SLIGHTLY_AMBITIOUS": 0.7,
    "OVERLY_AMBITIOUS": 0.3,
    "OVERQUALIFIED": 0.6,   
    "UNKNOWN": 0.5,
}

RELEVANCE_WEIGHTS = {
    "article_evidence": 0.35,
    "study_type": 0.25,
    "area_fit": 0.25,
    "tier_alignment": 0.15,
}


class JournalRecommendationAnalyzer:
    slot_filling_llm: BaseLLM = SlotFillingModels(max_retries=2, timeout=15, first_chunk_timeout=10)
    llm: BaseLLM = SlotFillingModels(max_retries=2, timeout=15, first_chunk_timeout=10)

    def __init__(self, 
                 abstract: str = "", 
                 query_params={},
                 years_hot: List[int] = [2021, 2022, 2023, 2024, 2025],
                 top_k: int = 200,
                 size: int = 20,
                 output_dir: str = "",
                 **kwargs):
        self.abstract = abstract
        self.query_params = query_params
        self.years_hot = years_hot
        self.top_k = top_k
        self.size = size
        self.output_dir = output_dir

    async def slot_filling(self, schema, prompt):
        schema_format = get_openai_json_schema_v3(schema)
        function_name = schema_format[0]['function']['name']
        response = await self.slot_filling_llm(user_prompt=prompt, tools=schema_format, tool_choice={"type": "function", "function": {"name": function_name}}, temperature=0, max_tokens=8192)

        if hasattr(response, 'tool_calls') and response.tool_calls:
            args_str = response.tool_calls[0].function.arguments
            logger.debug(f"LLM tool call response: {args_str} (type: {type(args_str)})")
            try:
                return json.loads(args_str)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse tool call JSON: {args_str[:200]}... Error: {e}")
                # Don't raise here, try fallback instead
                pass
        elif hasattr(response, 'function_call'):
            args_str = response.function_call.arguments
            logger.debug(f"LLM function call response: {args_str} (type: {type(args_str)})")
            try:
                return json.loads(args_str)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse function call JSON: {args_str[:200]}... Error: {e}")
                # Don't raise here, try fallback instead
                pass

        # If we get here, try fallback parsing
        logger.warning("Trying fallback parsing...")
        try:
            if hasattr(response, 'choices') and response.choices and len(response.choices) > 0:
                raw_content = response.choices[0].message.content
                if raw_content and isinstance(raw_content, str):
                    logger.info(f"Attempting fallback parsing of raw response: {raw_content[:200]}...")
                    try:
                        # Try to extract JSON from the raw content
                        import re
                        json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                        if json_match:
                            parsed = json.loads(json_match.group())
                            logger.info("Fallback parsing succeeded")
                            return parsed
                    except (json.JSONDecodeError, Exception) as fallback_e:
                        logger.warning(f"Fallback parsing failed: {fallback_e}")
        except Exception as e:
            logger.warning(f"Error during fallback attempt: {e}")

        logger.error("All parsing attempts failed, returning None")
        return None

    def is_chinese(self, text):
        """Check if text is predominantly Chinese"""
        if not text:
            return False
        # Check for Chinese character ranges
        chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u2f00-\u2fdf\u3000-\u303f\u31c0-\u31ef\u3200-\u32ff\u3300-\u33ff\ufe30-\ufe4f\ufe10-\ufe1f\uf900-\ufaff]')
        chinese_chars = len(chinese_pattern.findall(text))
        # If more than 15% of characters are Chinese, consider it Chinese
        print(f"Chinese characters found: {chinese_chars}, Total characters: {len(text)}")
        return chinese_chars / len(text) > 0.15

    async def translate_abstract(self):
        """
        Translate abstract to English and Chinese
        """
        try:
            self.chinese_abstract = self.is_chinese(self.abstract)
            
            if self.chinese_abstract:
                # Chinese input: keep original and translate to English
                self.abstract_cn = self.abstract
                logger.info(f"Detected Chinese abstract, translating to English (length: {len(self.abstract)})")
                
                translation_prompt = (
                    "You are a professional academic translator. "
                    "Translate the following Chinese research abstract into English.\n\n"
                    "Requirements:\n"
                    "- Maintain academic tone and technical accuracy\n"
                    "- Use proper scientific terminology\n"
                    "- Keep the same structure and meaning\n"
                    "- Provide ONLY the English translation, no explanations\n\n"
                    f"Chinese Abstract:\n{self.abstract}\n\n"
                    "English Translation:"
                )
                
                # Direct LLM call, collect streaming response
                translation_stream = self.llm.stream_call(
                    user_prompt=translation_prompt,
                    temperature=0.3
                )
                
                self.abstract_en = ""
                async for chunk in translation_stream:
                    self.abstract_en += chunk
                
                self.abstract_en = self.abstract_en.strip()
                
                if not self.abstract_en or len(self.abstract_en) < 20:
                    logger.warning("English translation is empty or too short, using original text")
                    self.abstract_en = self.abstract
            else:
                # English input: keep original and translate to Chinese
                self.abstract_en = self.abstract
                logger.info(f"Detected English abstract, translating to Chinese (length: {len(self.abstract)})")
                
                translation_prompt = (
                    "你是一位专业的学术翻译。"
                    "将以下英文研究摘要翻译成中文。\n\n"
                    "要求：\n"
                    "- 保持学术语气和技术准确性\n"
                    "- 使用恰当的科学术语\n"
                    "- 保持相同的结构和含义\n"
                    "- 仅提供中文翻译，无需解释\n\n"
                    f"英文摘要：\n{self.abstract}\n\n"
                    "中文翻译："
                )
                
                # Direct LLM call, collect streaming response
                translation_stream = self.llm.stream_call(
                    user_prompt=translation_prompt,
                    temperature=0.3
                )
                
                self.abstract_cn = ""
                async for chunk in translation_stream:
                    self.abstract_cn += chunk
                
                self.abstract_cn = self.abstract_cn.strip()
                
                if not self.abstract_cn or len(self.abstract_cn) < 20:
                    logger.warning("Chinese translation is empty or too short, using original text")
                    self.abstract_cn = self.abstract
            
            logger.info(
                f"Translation completed successfully - "
                f"EN: {len(self.abstract_en)} chars, CN: {len(self.abstract_cn)} chars"
            )
            
        except Exception as e:
            logger.error(f"Translation failed: {str(e)}, using original text as fallback")
            # Fallback: use original text for both languages
            if self.chinese_abstract:
                self.abstract_cn = self.abstract
                self.abstract_en = self.abstract
            else:
                self.abstract_en = self.abstract
                self.abstract_cn = self.abstract

    async def summarize_abstract(self):
        try:
            abstract_text = self.abstract_cn if hasattr(self, 'abstract_cn') and self.abstract_cn else self.abstract
            
            prompt = ABSTRACT_SUMMARY_PROMPT + f"\n\nAbstract:\n{abstract_text}"
            
            logger.info("Generating abstract summary for journal recommendation")
            summary_stream = self.llm.stream_call(
                user_prompt=prompt,
                temperature=0.3,
                max_tokens=512
            )
            
            summary = ""
            async for chunk in summary_stream:
                summary += chunk
            
            self.abstract_summary = summary.strip()
            
            logger.info(f"Generated summary length: {len(self.abstract_summary)} chars")
            
            return self.abstract_summary
            
        except Exception as e:
            logger.error(f"Failed to generate abstract summary: {str(e)}")
            # 如果失败，返回摘要的前200字作为备用
            self.abstract_summary = abstract_text[:200] + "..." if len(abstract_text) > 200 else abstract_text
            return self.abstract_summary

    async def extract_keywords_from_abstract(self):
        prompt = ABSTRACT_BILINGUAL_KEYWORDS_PROMPT + f"\n\nAbstract:\n{self.abstract}"
        tool_filling_msg_json = await self.slot_filling(
            schema=AbstractKeywordsSchema, 
            prompt=prompt
        )
        self.keywords_cn = tool_filling_msg_json.get('keywords_cn', [])
        self.keywords_en = tool_filling_msg_json.get('keywords_en', [])
        return self.keywords_cn, self.keywords_en
  
    async def infer_abstract_research_type(self):
        prompt = INFER_ABSTRACT_RESEARCH_TYPE_PROMPT + f"\n\nAbstract:\n{self.abstract}"
        tool_filling_msg_json = await self.slot_filling(
            schema=AbstractStudyTypeSchema,
            prompt=prompt
        )

        # Ensure we have a valid response
        if not isinstance(tool_filling_msg_json, dict):
            logger.warning(f"Invalid response from slot_filling: {tool_filling_msg_json}")
            study_types = []
        else:
            study_types = tool_filling_msg_json.get('study_types', [])
        
        # 尝试将字符串转换为 StudyType 枚举成员
        raw_type = study_types[0] if study_types else ""

        # Validate and clean the raw_type to prevent format string issues
        if isinstance(raw_type, str):
            # Remove any curly braces or problematic characters that could interfere with string formatting
            raw_type = raw_type.replace('{', '').replace('}', '').replace('\n', ' ').replace('\r', ' ').strip()
            # Limit length to prevent issues
            raw_type = raw_type[:100] if len(raw_type) > 100 else raw_type
        else:
            raw_type = ""

        try:
            # 尝试通过值匹配枚举成员
            self.abstract_research_type = next(e for e in StudyType if e.value == raw_type)
        except (StopIteration, Exception):
            # 如果没找到匹配的枚举，或者 raw_type 为空，则保持为字符串或设置默认
            # 确保它是一个安全的字符串
            self.abstract_research_type = raw_type if raw_type else "Unknown"
            
        return self.abstract_research_type

    async def search_related_articles(self, journal_issns: list[str] | None = None,):
        """
        Returns:
            Dict: {
                'articles': List[Dict],  # 文章列表（按融合 rank 排序）
                'pmids': List[str],      # PMID列表
                'stats': Dict            # 统计信息
            }
        """
        logger.info("Starting dual search strategy (keywords + abstract, rank-based fusion)")

        if not hasattr(self, 'keywords_en') or not self.keywords_en:
            await self.extract_keywords_from_abstract()

        articles_dict = {}

        # ---------- keywords search ----------
        try:
            logger.info(f"Searching with keywords: {self.keywords_en[:5]}...")
            keywords_results = await keywords_search_pubmed(
                keywords=self.keywords_en,
                years=self.years_hot,
                size=self.top_k,
                fusion_method="rrf",
                bm25_weight=0.4,
                vector_weight=0.6
            )

            for rank, doc in enumerate(keywords_results, start=1):
                pmid = str(doc.get("pmid") or doc.get("uid") or "")
                if not pmid:
                    continue

                if pmid not in articles_dict:
                    articles_dict[pmid] = {
                        "pmid": pmid,
                        "title": doc.get("title", ""),
                        "abstract": doc.get("summary", "") or doc.get("abstract", ""),
                        "authors": doc.get("authors", []),
                        "journal": doc.get("fulljournalname", "") or doc.get("journal", ""),
                        "issn": doc.get("issn", ""),
                        "year": doc.get("year_of_publication", "") or doc.get("pub_date_year", ""),
                        "pub_date": doc.get("pubdate", "") or doc.get("pub_date", ""),
                        "doi": doc.get("doi", ""),
                        "pmc_id": doc.get("pmc_id", ""),
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "sources": set(),
                        "keyword_rank": None,
                        "abstract_rank": None,
                        "rrf_score": 0.0,
                    }

                articles_dict[pmid]["sources"].add("keywords")
                articles_dict[pmid]["keyword_rank"] = rank

            logger.info(f"Keywords search found {len(keywords_results)} articles")

        except Exception as e:
            logger.warning(f"Keywords search failed: {e}")
            keywords_results = []

        # ---------- abstract search ----------
        try:
            logger.info(f"Searching with abstract (length: {len(self.abstract)})")
            abstract_results = await abstract_search_pubmed(
                abstract=self.abstract,
                years=self.years_hot,
                size=self.top_k,
                fusion_method="rrf",
                bm25_weight=0.3,
                vector_weight=0.7
            )

            for rank, doc in enumerate(abstract_results, start=1):
                pmid = str(doc.get("pmid") or doc.get("uid") or "")
                if not pmid:
                    continue

                if pmid not in articles_dict:
                    articles_dict[pmid] = {
                        "pmid": pmid,
                        "title": doc.get("title", ""),
                        "abstract": doc.get("summary", "") or doc.get("abstract", ""),
                        "authors": doc.get("authors", []),
                        "journal": doc.get("fulljournalname", "") or doc.get("journal", ""),
                        "issn": doc.get("issn", ""),
                        "year": doc.get("year_of_publication", "") or doc.get("pub_date_year", ""),
                        "pub_date": doc.get("pubdate", "") or doc.get("pub_date", ""),
                        "doi": doc.get("doi", ""),
                        "pmc_id": doc.get("pmc_id", ""),
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "sources": set(),
                        "keyword_rank": None,
                        "abstract_rank": None,
                        "rrf_score": 0.0,
                    }

                articles_dict[pmid]["sources"].add("abstract")
                articles_dict[pmid]["abstract_rank"] = rank

            logger.info(f"Abstract search found {len(abstract_results)} articles")

        except Exception as e:
            logger.warning(f"Abstract search failed: {e}")
            abstract_results = []

        # ---------- RRF fusion ----------
        K = 60  # 平滑常数，可调

        for article in articles_dict.values():
            score = 0.0
            if article["keyword_rank"]:
                score += 1.0 / (K + article["keyword_rank"])
            if article["abstract_rank"]:
                score += 1.0 / (K + article["abstract_rank"])
            article["rrf_score"] = score
            article["sources"] = list(article["sources"])

        # ---------- sort ----------
        sorted_articles = sorted(
            articles_dict.values(),
            key=lambda x: x["rrf_score"],
            reverse=True
        )

        pmid_list = [a["pmid"] for a in sorted_articles]

        both_sources = sum(1 for a in sorted_articles if len(a["sources"]) == 2)
        keywords_only = sum(1 for a in sorted_articles if a["sources"] == ["keywords"])
        abstract_only = sum(1 for a in sorted_articles if a["sources"] == ["abstract"])

        stats = {
            "total_articles": len(sorted_articles),
            "both_sources": both_sources,
            "keywords_only": keywords_only,
            "abstract_only": abstract_only,
            "keywords_search_count": len(keywords_results),
            "abstract_search_count": len(abstract_results),
        }

        logger.info(
            f"Dual search completed (rank fusion): {stats['total_articles']} articles | "
            f"Both: {both_sources}, Keywords: {keywords_only}, Abstract: {abstract_only}"
        )

        return {
            "articles": sorted_articles,
            "pmids": pmid_list,
            "stats": stats
        }
    
    def format_articles_for_display(self, articles: List[Dict], max_articles: int = 5) -> List[Dict]:
        """
        格式化文章信息用于前端展示
        返回简化的文章信息，只保留必要字段
        
        Args:
            articles: 完整的文章列表
            max_articles: 最多返回多少篇文章
        
        Returns:
            格式化后的文章列表（简化格式）
        """
        formatted_articles = []
        
        for article in articles[:max_articles]:
            # 格式化作者列表为字符串数组（取前3个作者的姓氏）
            authors_list = []
            if isinstance(article.get("authors"), list) and article["authors"]:
                for author in article["authors"][:3]:
                    if isinstance(author, dict):
                        # 提取姓氏（通常是name的最后一个单词或last_name字段）
                        name = author.get("name", "") or author.get("last_name", "")
                        if name:
                            # 如果是 "Last FM" 格式，取第一个单词作为姓氏
                            last_name = name.split()[0] if " " in name else name
                            authors_list.append(last_name)
                    elif isinstance(author, str):
                        last_name = author.split()[0] if " " in author else author
                        authors_list.append(last_name)
            
            # 构建PubMed URL
            pmid = article.get("pmid", "")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else article.get("url", "")
            
            # 返回简化的文章信息
            formatted = {
                "title": article.get("title", ""),
                "authors": authors_list,  # 作者姓氏列表
                "journal": article.get("journal", ""),
                "year": str(article.get("year", "")),
                "pmid": str(pmid),
                "relevance_score": round(article.get("search_score", 0), 2),
                "url": url
            }
            
            formatted_articles.append(formatted)
        
        return formatted_articles
    
    def _clean_journal_data(self, journal: Dict) -> Dict:
        """
        清理期刊数据：保留ES中的所有原始字段 + 添加推荐相关字段
        
        不过滤ES字段，因为前端可能需要任何字段
        只移除内部临时字段和敏感字段
        """
        # 需要移除的内部临时字段和向量数据
        remove_fields = [
            "related_articles",      # 原始文章列表（已转换为similar_articles）
            "_publishability_score", # 内部临时计算字段
            "_raw_relevance",        # 原始相关性分数（已转为百分制）
            "_raw_academic",         # 原始学术分数（已转为百分制）
            "_raw_publishability",   # 原始可发表性分数（已转为百分制）
            "semantic_vector",       # 期刊语义向量（1536维，太大且前端不需要）
            "title_vector",          # 标题向量
            "title_cn_vector",       # 中文标题向量
            "title_en_vector",       # 英文标题向量
            "description_vector",    # 描述向量
            "embedding",             # 通用嵌入向量
        ]
        
        # 创建副本以避免修改原始数据
        cleaned = journal.copy()
        
        # 移除显式指定的字段
        for field in remove_fields:
            cleaned.pop(field, None)

        keys_to_remove = []
        for key in cleaned.keys():
            key_lower = key.lower()
            if 'vector' in key_lower or 'embedding' in key_lower or key_lower.endswith('_vec'):
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            cleaned.pop(key, None)
        
        if keys_to_remove:
            logger.debug(f"Removed vector fields from journal data: {keys_to_remove}")
        
        if "recommendation_reason" not in cleaned:
            cleaned["recommendation_reason"] = ""
        if "similar_articles" not in cleaned:
            cleaned["similar_articles"] = []
        if "tier" not in cleaned:
            cleaned["tier"] = ""
        if "tier_name" not in cleaned:
            cleaned["tier_name"] = ""
        
        return cleaned

    def collect_journals_from_articles(self, articles, pmids, query_params, size):
        logger.info("Collecting journals from articles")

        # ---------- PMID → ISSNs ----------
        pmid_to_issns = fetch_issns_from_es(pmids, return_mapping=True)
        if not pmid_to_issns:
            logger.warning("No ISSNs extracted from PMIDs")
            return {"journals": [], "issns": [], "stats": {}}

        # ---------- enrich articles ----------
        for article in articles:
            pmid = str(article.get("pmid", ""))
            article["issns"] = pmid_to_issns.get(pmid, [])

        # ---------- collect unique ISSNs ----------
        issns = sorted({
            issn.strip().upper()
            for issn_list in pmid_to_issns.values()
            for issn in issn_list
            if issn
        })

        logger.info(f"Using {len(issns)} unique ISSNs for journal recall")

        # ---------- query journals ----------
        db_results = search_journals(
            issns=issns,
            **query_params,
            size=size,
        )
        journals_raw = db_results.get("journals", [])
        if not journals_raw:
            logger.warning("No journals found from ISSN recall")
            return {"journals": [], "issns": issns, "stats": {}}

        # ---------- build issn → journal_id map ----------
        issn_to_journal_ids = {}
        for journal in journals_raw:
            journal_id = journal.get("journal_id")
            if not journal_id:
                continue
            for j_issn in filter(None, [journal.get("issn"), journal.get("e_issn")]):
                j_issn = j_issn.strip().upper()
                issn_to_journal_ids.setdefault(j_issn, set()).add(journal_id)

        # ---------- evidence aggregation ----------
        journal_evidence = {}  # journal_id -> evidence

        for article in articles:
            pmid = article["pmid"]
            rrf_score = article.get("rrf_score", 0.0)

            for issn in article.get("issns", []):
                issn = issn.strip().upper()
                for journal_id in issn_to_journal_ids.get(issn, []):
                    entry = journal_evidence.setdefault(
                        journal_id,
                        {
                            "related_pmids": set(),
                            "related_article_count": 0,
                            "related_article_weight": 0.0,
                        }
                    )

                    if pmid not in entry["related_pmids"]:
                        entry["related_pmids"].add(pmid)
                        entry["related_article_count"] += 1
                        entry["related_article_weight"] += rrf_score

        # ---------- merge evidence back to journals ----------
        journals_by_id = {}
        for journal in journals_raw:
            journal_id = journal.get("journal_id")
            if not journal_id:
                continue

            evidence = journal_evidence.get(journal_id, {
                "related_pmids": set(),
                "related_article_count": 0,
                "related_article_weight": 0.0,
            })

            journals_by_id[journal_id] = {
                **journal,
                "related_pmids": list(evidence["related_pmids"]),
                "related_article_count": evidence["related_article_count"],
                "related_article_weight": round(evidence["related_article_weight"], 6),
            }

        journals = list(journals_by_id.values())

        stats = {
            "total_journals": len(journals),
            "journals_with_evidence": sum(
                1 for j in journals if j["related_article_count"] > 0
            ),
            "total_articles": len(articles),
        }

        logger.info(
            f"Collected {len(journals)} journals, "
            f"{stats['journals_with_evidence']} with supporting articles"
        )

        return {
            "journals": journals,
            "issns": issns,
            "stats": stats,
        }

    def _wos_structural_exclusion(self, journal: Dict, study_type: StudyType) -> Optional[str]:
        wos_docs = journal.get("latest_document_types")
        article_pct = _get_pct(wos_docs, "article")
        review_pct = _get_pct(wos_docs, "review")

        if study_type in {
            StudyType.CLINICAL_STUDY,
            StudyType.CLINICAL_TRIAL,
            StudyType.OBSERVATIONAL_STUDY,
            StudyType.CLINICAL_TRIAL_PROTOCOL,
        }:
            if review_pct > 85 and article_pct < 15:
                return "Journal is structurally review-only (WoS)"

        if study_type in {
            StudyType.SYSTEMATIC_REVIEW,
            StudyType.META_ANALYSIS,
            StudyType.SCOPING_REVIEW,
        }:
            if article_pct > 95 and review_pct < 3:
                return "Journal is structurally original-research dominant (WoS)"
        return None

    def _get_pubmed_study_count(self, journal: Dict, study_type: Any) -> int:
        pub_types = journal.get("pubmed_stats", {}).get("pub_types_total", [])
        target_value = study_type.value if hasattr(study_type, 'value') else study_type

        for p in pub_types:
            if p.get("pub_type") == target_value:
                return int(p.get("count", 0))

        return 0
     
    def compute_study_journal_compatibility(self, journal: Dict, study_type: StudyType) -> StudyJournalCompatibilityResult:
        exclusion_reason = self._wos_structural_exclusion(journal, study_type)

        journal_id = journal.get("journal_id", "UNKNOWN")
        if exclusion_reason:
            return StudyJournalCompatibilityResult(
                journal_id=journal_id,
                is_excluded=True,
                exclusion_reason=exclusion_reason,
                pubmed_count=0,
                score=0.0,
            )

        pubmed_count = self._get_pubmed_study_count(journal, study_type)

        score = 0.0
        score += min(pubmed_count, 5) * 2.0   # max = 10

        return StudyJournalCompatibilityResult(
            journal_id=journal_id,
            is_excluded=False,
            exclusion_reason=None,
            pubmed_count=pubmed_count,
            score=score,
        )

    
    async def infer_journal_fit(self, journal: dict) -> dict:
        journal_title = journal.get("journal_title", "")
        logger.debug(f"Starting journal fit inference for: {journal_title}")

        # Debug: check abstract_research_type at the very beginning
        logger.debug(f"abstract_research_type at start: {repr(getattr(self, 'abstract_research_type', 'NOT_SET'))} (type: {type(getattr(self, 'abstract_research_type', None))})")

        # Also check if it's being accessed as a dict anywhere
        try:
            test_access = self.abstract_research_type['test']
            logger.error(f"ERROR: abstract_research_type is being accessed as dict! Value: {repr(self.abstract_research_type)}")
        except (TypeError, AttributeError):
            pass  # This is expected
        except Exception as e:
            logger.error(f"Unexpected error when testing dict access: {e}")

        # Ensure abstract_research_type is available and valid
        if not hasattr(self, 'abstract_research_type') or self.abstract_research_type is None:
            logger.debug("abstract_research_type not set, inferring now...")
            await self.infer_abstract_research_type()

        # Debug logging
        logger.debug(f"Current abstract_research_type: {repr(self.abstract_research_type)} (type: {type(self.abstract_research_type)})")

        # Ensure abstract_research_type is a safe string - be very strict
        original_value = self.abstract_research_type
        if not isinstance(self.abstract_research_type, str):
            logger.warning(f"abstract_research_type is not a string: {original_value} (type: {type(original_value)})")
            self.abstract_research_type = "Unknown"
        else:
            # Clean any potentially problematic characters
            cleaned = self.abstract_research_type.replace('{', '').replace('}', '').replace('\n', ' ').replace('\r', ' ').replace('\t', ' ').strip()
            if len(cleaned) == 0 or len(cleaned) > 100:
                cleaned = "Unknown"
            self.abstract_research_type = cleaned

            if original_value != self.abstract_research_type:
                logger.warning(f"Cleaned abstract_research_type from {repr(original_value)} to {repr(self.abstract_research_type)}")

        logger.debug(f"Final abstract_research_type: {repr(self.abstract_research_type)}")

        def format_jif_category_metrics(metrics: list[dict]) -> str:
            if not metrics:
                return "Not available"

            parts = []
            for m in metrics:
                category = m.get("category", "")
                quartile = m.get("quartile", "")
                rank = m.get("rank_raw", "")
                s = category
                if quartile:
                    s += f": {quartile}"
                if rank:
                    s += f" (rank {rank})"
                parts.append(s)

            return "; ".join(parts)

        def format_zky_quartile(zky: dict) -> str:
            if not zky:
                return "Not available"

            parts = []

            for item in zky.get("major", []):
                cat = item.get("category", "")
                q = item.get("quartile", "")
                if cat and q:
                    parts.append(f"Major: {cat} Q{q}")

            for item in zky.get("minor", []):
                cat = item.get("category", "")
                q = item.get("quartile", "")
                if cat and q:
                    parts.append(f"Minor: {cat} Q{q}")

            return "; ".join(parts) if parts else "Not available"

        jif_category_metrics = format_jif_category_metrics(journal.get("jif_category_metrics", []))
        zky_quartile = format_zky_quartile(journal.get("zky_quartile", {}))

        # Ensure all format arguments are strings
        format_args = {
            'study_type': str(self.abstract_research_type) if self.abstract_research_type is not None else "Unknown",
            'abstract': str(self.abstract),
            'journal_title': str(journal.get("journal_title", "")),
            'publisher_region': str(journal.get("publisher_region", "")),
            'wos_research_areas': ", ".join(str(area) for area in journal.get("wos_research_areas", [])),
            'citation_topics_meso': ", ".join(str(topic) for topic in journal.get("citation_topics_meso", [])),
            'latest_impact_factor': str(journal.get("latest_impact_factor", 0)),
            'jif_category_metrics': str(jif_category_metrics),
            'zky_quartile': str(zky_quartile),
            'latest_citescore': str(journal.get("latest_citescore", 0)),
        }
        logger.debug(f"Format args: {format_args}")
        for k, v in format_args.items():
            logger.debug(f"  {k}: {repr(v)} (type: {type(v)})")

        prompt = JOURNAL_FIT_PROMPT.format(**format_args)


        result = await self.slot_filling(
            schema=JournalFitResult,
            prompt=prompt
        )

        if result is None:
            raise ValueError("LLM failed to return valid JSON response after all parsing attempts")

        return result

    
    async def _infer_one_journal_fit(self, journal: dict, semaphore: asyncio.Semaphore):
        async with semaphore:
            try:
                fit_result = await self.infer_journal_fit(journal)

                journal["area_fit"] = fit_result["area_fit"]
                journal["area_fit_explanation"] = fit_result["area_fit_explanation"]

                journal["tier_alignment"] = fit_result["tier_alignment"]
                journal["tier_alignment_explanation"] = fit_result["tier_alignment_explanation"]

            except Exception as e:
                logger.warning(
                    f"LLM journal fit failed for {journal.get('journal_title')}: {e}"
                )
                journal["area_fit"] = "UNKNOWN"
                journal["area_fit_explanation"] = []
                journal["tier_alignment"] = "UNKNOWN"
                journal["tier_alignment_explanation"] = []

            return journal

    
    def score_article_evidence(self, journal: dict) -> float:
        weight = journal.get("related_article_weight", 0.0)
        count = journal.get("related_article_count", 0)

        # 经验上 weight 很小，用 log 或 cap
        weight_score = min(weight / 0.05, 1.0)        # 0.05 ≈ 强证据
        count_score = min(count / 10, 1.0)            # ≥10 篇即封顶

        return 0.6 * weight_score + 0.4 * count_score

    
    def score_study_type(self, journal: dict) -> float:
        if journal.get("compatibility_is_excluded"):
            return 0.0

        pubmed_count = journal.get("compatibility_pubmed_count", 0)

        if pubmed_count == 0:
            return 0.4        # 未见证据 ≠ 不收
        elif pubmed_count < 5:
            return 0.7
        else:
            return 1.0

    def score_area_fit(self, journal: dict) -> float:
        return AREA_FIT_MAP.get(journal.get("area_fit"), 0.5)

    def score_tier_alignment(self, journal: dict) -> float:
        return TIER_ALIGNMENT_MAP.get(journal.get("tier_alignment"), 0.5)

    
    def compute_relevance_priority_score(self, journal: dict) -> float:
        s_article = self.score_article_evidence(journal)
        s_study = self.score_study_type(journal)
        s_area = self.score_area_fit(journal)
        s_tier = self.score_tier_alignment(journal)

        score = (
            RELEVANCE_WEIGHTS["article_evidence"] * s_article +
            RELEVANCE_WEIGHTS["study_type"] * s_study +
            RELEVANCE_WEIGHTS["area_fit"] * s_area +
            RELEVANCE_WEIGHTS["tier_alignment"] * s_tier
        )

        return round(score, 3)

    
    def compute_impact_score(self, journal: dict) -> float:
        """
        Compute journal impact score in [0, 1]
        based on JIF quartile, JIF rank, CiteScore, and CAS (ZKY) quartile.
        """
        # ---------- JIF quartile ----------
        JIF_Q_SCORE = {
            "Q1": 1.0,
            "Q2": 0.75,
            "Q3": 0.5,
            "Q4": 0.25,
        }
        s_jif_q = JIF_Q_SCORE.get(journal.get("jif_quartile"), 0.5)

        # ---------- JIF rank within category ----------
        s_jif_rank = 0.5
        metrics = journal.get("jif_category_metrics", [])
        if metrics:
            best = min(
                metrics,
                key=lambda m: m.get("rank_position") or 9999
            )
            pos = best.get("rank_position")
            total = best.get("rank_total")
            if pos and total:
                s_jif_rank = max(0.0, 1.0 - (pos - 1) / total)

        # ---------- CiteScore ----------
        cs = journal.get("latest_citescore")
        if cs:
            s_citescore = min(cs / 50.0, 1.0)
        else:
            s_citescore = 0.5

        # ---------- CAS (ZKY) quartile ----------
        s_zky = 0.5
        zky = journal.get("zky_quartile", {})
        major = zky.get("major", [])
        minor = zky.get("minor", [])

        if major:
            q = major[0].get("quartile")
            s_zky_major = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}.get(q, 0.5)
        else:
            s_zky_major = 0.5

        if minor:
            q = minor[0].get("quartile")
            s_zky_minor = {1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25}.get(q, 0.5)
        else:
            s_zky_minor = 0.5

        s_zky = 0.7 * s_zky_major + 0.3 * s_zky_minor

        # ---------- final weighted sum ----------
        impact_score = (
            0.4 * s_jif_q +
            0.25 * s_jif_rank +
            0.2 * s_citescore +
            0.15 * s_zky
        )

        return round(impact_score, 3)

    
    def compute_publishability_score(self, journal: dict) -> float:
        """
        Compute publishability score in [0, 1]
        """

        score = 0.0
        weight_sum = 0.0

        # ---------- 最近一年发文量 ----------
        recent_docs = journal.get("latest_citable_items", 0) or 0
        logger.info(f"recent_docs: {recent_docs}")
        volume_score = 0.0
        if recent_docs > 0:
            volume_score = min(recent_docs / 200.0, 1.0)
            score += volume_score * 0.5
            weight_sum += 0.5
        logger.info(f"volume_score: {volume_score}")

        # ---------- 中国作者占比 ----------
        china_authorship_pct = journal.get("latest_china_authorship", 0) or 0
        china_authorship = china_authorship_pct / 100.0
        logger.info(f"china_authorship: {china_authorship}")
        china_score = min(china_authorship / 0.30, 1.0)
        score += china_score * 0.3
        weight_sum += 0.3
        logger.info(f"china_score: {china_score}")
        # ---------- 开放获取 ----------
        oa_status = journal.get("open_access_status", "").lower()
        is_oa = any(k in oa_status for k in ["gold", "diamond", "full"])
        score += (1.0 if is_oa else 0.0) * 0.2
        weight_sum += 0.2
        logger.info(f"is_oa: {is_oa}")
        base_score = score / weight_sum if weight_sum > 0 else 0.5

        # ---------- 审稿周期：只加分 ----------
        bonus = 0.0
        days = (
            journal.get("submission_to_acceptance_days")
            or journal.get("time_to_first_decision_days")
        )

        if days and days > 0:
            weeks = days / 7.0
            if weeks <= 6:
                bonus = 0.05
            elif weeks <= 10:
                bonus = 0.03
            elif weeks <= 14:
                bonus = 0.01

        return min(base_score + bonus, 1.0)

    def compute_final_score(self, relevance: float, impact: float, publishability: float,) -> float:
        """
        Final score in [0, 1]
        """
        return (
            relevance * 0.8 +        
            impact * 0.1 +           
            publishability * 0.1     
        )

    def select_similar_articles(self, articles: list, score_key: str = "final_score", min_score: float = 0.35, max_keep: int = 20):
        ranked = sorted(
            articles,
            key=lambda x: x.get(score_key, 0),
            reverse=True
        )
        filtered = [
            a for a in ranked
            if a.get(score_key, 0) >= min_score
        ]
        return filtered[:max_keep]

    
    async def generate_llm_recommendation_reason(self, journal: Dict) -> str:
        try:
            area_fit_result = journal.get("infer_area_fit", {})
            
            area_fit = journal.get("area_fit") or area_fit_result.get("area_fit", "不确定")
            area_fit_expl = journal.get("area_fit_explanation") or area_fit_result.get("area_fit_explanation", [])

            tier_align = journal.get("tier_alignment") or area_fit_result.get("tier_alignment", "不明确")
            tier_expl = journal.get("tier_alignment_explanation") or area_fit_result.get("tier_alignment_explanation", [])

            compatibility_result = journal.get("compatibility_result")
            if hasattr(compatibility_result, "pubmed_count"):
                pubmed_count = getattr(compatibility_result, "pubmed_count", 0)
                compatibility_reason = getattr(compatibility_result, "exclusion_reason", "")
            elif isinstance(compatibility_result, dict):
                pubmed_count = compatibility_result.get("pubmed_count", 0)
                compatibility_reason = compatibility_result.get("exclusion_reason", "")
            else:
                pubmed_count = journal.get("compatibility_pubmed_count", 0)
                compatibility_reason = journal.get("compatibility_reason") or journal.get("compatibility_exclusion_reason", "")

            recent_volume = journal.get("latest_citable_items", 0) or 0
            china_ratio = journal.get("latest_china_authorship", 0.0) or 0.0
            china_ratio_percent = round(china_ratio, 1)

            impact_factor = journal.get("latest_impact_factor", "未知")
            quartile = journal.get("jif_quartile", "未知")

            # -------- 构造 Prompt --------
            prompt = f"""
            你是一名熟悉医学期刊投稿的资深编辑。请根据下面的匹配情况和期刊信息，用自然流畅的中文写一段简短说明，向作者解释该期刊与其研究的契合度。

            写作要求：
            - 先突出研究方向与期刊领域/定位的匹配，再补充档位和发表难度/友好性
            - 从下列数据中自然选取 1–3 个关键数字（如 IF、分区、近一年发文量、中国作者占比、PubMed 支持篇数），增强说服力，但不要生硬堆砌
            - 语气专业克制，像期刊编辑给作者的中肯评价，不夸张、不口号化
            - 全文不超过 100 字，仅输出一段话，不要列点，不要加“推荐理由”“建议投稿”等字样

            【用户研究与期刊匹配情况】
            - 用户提供的研究摘要：{self.abstract}
            - 研究方向匹配等级：{area_fit}
            - 匹配说明：{"；".join(area_fit_expl[:2]) or "无"}
            - 档位匹配判断：{tier_align}
            - 档位说明：{"；".join(tier_expl[:2]) or "无"}
            - 研究类型发文支持：{pubmed_count} 篇；说明：{compatibility_reason or "无"}

            【期刊基础信息】
            - 影响因子：{impact_factor}
            - 分区：{quartile}
            - 最近一年发文量：{recent_volume} 篇
            - 中国作者占比：{china_ratio_percent}%

            请综合以上信息，写出一段自然、有说服力的中文说明：
            """
            response = ""
            async for chunk in self.llm.stream_call(
                user_prompt=prompt.strip()
            ):
                response += chunk

            # -------- 清理输出 --------
            reason = response.strip().strip("“”\"")
            return reason

        except Exception as e:
            logger.warning(f"LLM推荐理由生成失败，使用默认模板：{e}")
            return "该期刊在研究方向与发文类型上与当前研究具有一定契合度，可作为投稿候选。"

    
    async def retrieve_similar_articles_in_journal(self, abstract: str, journal: dict, search_size: int = 500, min_score: float = 0.01, max_keep: int = 20,):
        def norm_one(x):
            if x is None:
                return None
            # if it's not a string (e.g. int), make it a string
            if not isinstance(x, str):
                x = str(x)
            x = x.strip().upper().replace("-", "").replace(" ", "")
            return x or None

        def norm_set(v):
            if v is None:
                return set()
            # support list/tuple/set
            if isinstance(v, (list, tuple, set)):
                return {n for n in (norm_one(i) for i in v) if n}
            # single value
            n = norm_one(v)
            return {n} if n else set()

        # target journal ISSNs
        journal_issns = set()
        journal_issns |= norm_set(journal.get("issn"))
        journal_issns |= norm_set(journal.get("e_issn"))
        if not journal_issns:
            return []

        # Use the new search function with ISSN filtering at query level
        results = await abstract_search_pubmed_with_issn_filter(
            abstract=abstract,
            journal_issns=list(journal_issns),
            size=search_size,
            fusion_method="rrf",
            bm25_weight=0.4,
            vector_weight=0.6,
            min_score_threshold=min_score,
        )

        if not results:
            return []

        # Results are already filtered and sorted, just limit to max_keep
        return results[:max_keep]

    async def run_journal_recommendation(self, search_results: Dict = None, max_journals: int = 10):
        logger.info("Starting journal recommendation process")

        articles = search_results["articles"]
        pmids = search_results["pmids"]

        self._articles = articles
        self._pmids = pmids
        self._pmids_count = len(pmids)
        logger.info(f"Found {len(articles)} related articles")

        journals_from_articles = []
        journal_result = self.collect_journals_from_articles(
            articles=articles,
            pmids=pmids,
            query_params=self.query_params,
            size = 10000
        )

        journals = journal_result["journals"]

        logger.info(f"Collected {len(journals)} journal candidates")

        # ---------- sort journals ----------
        journals = sorted(
            journals,
            key=lambda j: (
                j.get("related_article_weight", 0.0),
                j.get("related_article_count", 0),
                j.get("annual_impact_factors", [{}])[-1].get("value", 0),
            ),
            reverse=True,
        )
        journals_from_articles = journals
        logger.info(f"journals_from_articles: {journals_from_articles}")


        # study type compatibility
        study_type = getattr(self, "abstract_research_type", None)
        if study_type is None:
            logger.warning("abstract_research_type is not set, inferring now...")
            study_type = await self.infer_abstract_research_type()

        for journal in journals_from_articles:
            compatibility_result = self.compute_study_journal_compatibility(journal, study_type)
            journal["compatibility_result"] = asdict(compatibility_result)
            journal["compatibility_score"] = compatibility_result.score
            journal["compatibility_reason"] = compatibility_result.exclusion_reason
            journal["compatibility_pubmed_count"] = compatibility_result.pubmed_count
            journal["compatibility_is_excluded"] = compatibility_result.is_excluded

        
        kept_journals = []
        excluded_journals = []

        for journal in journals_from_articles:
            if journal["compatibility_is_excluded"]:
                excluded_journals.append(journal)
            else:
                kept_journals.append(journal)
        
        logger.info(f"Running LLM journal fit on {len(kept_journals)} journals")
        semaphore = asyncio.Semaphore(5)
        tasks = [
            self._infer_one_journal_fit(journal, semaphore)
            for journal in kept_journals
        ]
        kept_journals = await asyncio.gather(*tasks)

        for journal in kept_journals:
            journal["relevance_dimension"] = self.compute_relevance_priority_score(journal) * 100
            journal["academic_dimension"] = self.compute_impact_score(journal) * 100
            journal["publishability_dimension"] = self.compute_publishability_score(journal) * 100
            journal["total_score"] = self.compute_final_score(
                relevance=journal["relevance_dimension"],
                impact=journal["academic_dimension"],
                publishability=journal["publishability_dimension"],
            )

        kept_journals = sorted(kept_journals, key=lambda j: j.get("total_score", 0), reverse=True)

        if max_journals is not None:
            kept_journals = kept_journals[:max_journals]

        sem = asyncio.Semaphore(5)

        async def enrich(journal):
            async with sem:
                similar_articles = await self.retrieve_similar_articles_in_journal(
                    abstract=self.abstract, journal=journal
                )
                journal["similar_articles"] = similar_articles

                logger.info(f"relevance_dimension: {journal['relevance_dimension']}")
                logger.info(f"academic_dimension: {journal['academic_dimension']}")
                logger.info(f"publishability_dimension: {journal['publishability_dimension']}")
                logger.info(f"total_score: {journal['total_score']}")
                logger.info(f"top 5 similar articles: {similar_articles[:5]}")

                journal["recommendation_reason"] = await self.generate_llm_recommendation_reason(journal)

        await asyncio.gather(*(enrich(j) for j in kept_journals))

        return kept_journals

    
    def _vector_search_related_articles(self, abstract: str):
        searcher = PubMedVectorSearch()

        input_type = self._determine_input_type(abstract)
        results = searcher.search_years(inputs=[abstract], years=self.years_hot, size=self.top_k, input_type=input_type, force_load_partitions=True)
        pmid_list = []
        for hits in results:
            for h in hits:
                pmid = h.get("pmid")
                if pmid:
                    pmid_list.append(str(pmid))

        return pmid_list
    
    def _determine_input_type(self, text: str) -> str:
        """
        根据文本长度判断输入类型：
        - 短文本（<100字符）：关键词查询，使用 'query'
        - 长文本（>=100字符）：摘要文本，使用 'article'
        """
        return "query" if len(text.strip()) < 100 else "article"

def _get_pct(doc_types, target):
    if not doc_types:
        return 0.0
    for d in doc_types:
        if d.get("doc_type", "").lower() == target:
            return d.get("pct", 0.0)
    return 0.0

