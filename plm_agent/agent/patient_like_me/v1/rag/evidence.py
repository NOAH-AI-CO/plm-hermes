"""
Generic guideline evidence retrieval for PLM v1.

The goal is deliberately disease-agnostic: first identify the right guideline
documents, then retrieve small, high-signal passages for the clinical question.
It avoids sending whole PDFs to the LLM while still finding cross-section rules
such as contraindications, sequencing constraints, toxicity management, dose
modification, monitoring, and special-population caveats.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable


# sahzu vs public 隔离 + 付费门禁: 由 workflow 入口在处理请求时设置,
# 底层 search_guideline_documents 若未显式传参则自动读取, 避免每个 caller 都改签名。
current_product_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "plm_product_scope", default=None,
)
current_accessible_paid_doc_ids: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "plm_accessible_paid_doc_ids", default=None,
)

from agent.patient_like_me.v1.es.plm_index import (
    PLM_CHUNK_INDEX,
    PLM_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)

DocSelector = Callable[[str, str, list[dict]], Awaitable[list[str]]]
LLMCaller = Callable[[str, str], Awaitable[str]]

# Truncation caps removed — keep symbolic names for backwards compat
# but treat them as "no limit" everywhere downstream. The PLM workflow
# is meant to give the answer LLM the full retrieved evidence so it
# can pull out fine-print clinical details (retesting conditions,
# decision-tree branches, etc.) without us pre-deciding what fits.
MAX_EVIDENCE_TEXT_CHARS = 0  # 0 = no per-chunk cap
MAX_CONTEXT_CHARS = 0        # 0 = no evidence_pack cap

# 纯参考文献块识别 (heuristic): 这种 chunk 全是 "434. Metcalfe K, ... pubmed/15197194"
# 之类的论文引文列表, 对临床决策无价值, 还浪费 prompt 长度 + 误导 reasoning 模型。
# 不依赖 section_title (可能为空/不规范), 直接看 chunk 内容的密度特征。
_PUBMED_URL_RE = re.compile(r'ncbi\.nlm\.nih\.gov/pubmed|doi\.org/|Available at:\s*http', re.IGNORECASE)
_CITATION_LINE_RE = re.compile(r'^\s*\d{1,4}\.\s+[A-Z][a-zA-Z]+\s+[A-Z]', re.MULTILINE)


def _looks_like_pure_references(text: str) -> bool:
    """启发式: 判断 chunk 是不是纯论文引文列表。

    通过 3 个指标综合判断, 防止误杀混合 chunk:
      - PubMed URL 密度 (≥5 个)
      - 引文行数 ("N. Author X" 格式) (≥8 行)
      - 任一条件触发即视为纯引文
    保守起见对短 chunk (<500 字) 不判断, 避免误杀小段决策。
    """
    if not text or len(text) < 500:
        return False
    url_hits = len(_PUBMED_URL_RE.findall(text))
    citation_lines = len(_CITATION_LINE_RE.findall(text))
    return url_hits >= 5 or citation_lines >= 8
HARD_EVIDENCE_TYPES = {
    "ABSOLUTE_STOP",
    "CONTRAINDICATION",
    "SEQUENCING_RULE",
    "DOSE_MODIFICATION",
    "TOXICITY_MANAGEMENT",
}
GUIDELINE_KEY_ALIASES = {
    "castleman病": "卡斯尔曼病",
    "卡斯尔曼病": "卡斯尔曼病",
    "小儿中枢神经系统癌症": "儿童中枢神经系统肿瘤",
    "儿童中枢神经系统肿瘤": "儿童中枢神经系统肿瘤",
    "华氏巨球蛋白血症淋巴浆细胞淋巴瘤": "巨球蛋白血症/淋巴浆细胞性淋巴瘤",
    "巨球蛋白血症/淋巴浆细胞性淋巴瘤": "巨球蛋白血症/淋巴浆细胞性淋巴瘤",
    "aml": "急性髓性白血病",
    "acutemyeloidleukemia": "急性髓性白血病",
    "b-celllymphomas": "B细胞淋巴瘤",
    "hodgkinlymphoma": "霍奇金淋巴瘤",
    "t-celllymphomas": "T细胞淋巴瘤",
}


@dataclass
class EvidenceQuery:
    query: str
    intent: str
    evidence_type: str


@dataclass
class EvidenceChunk:
    chunk_id: str
    doc_id: int
    filename: str
    page_start: int
    page_end: int
    section_title: str
    text: str
    score: float = 0.0
    evidence_types: list[str] = field(default_factory=list)
    matched_queries: list[str] = field(default_factory=list)
    source_rank: int = 0


# Publisher 归属: 5 类分类, 前 4 大能做主指南, OTHER 只能做补充指南。
#   - NCCN / CSCO / ESMO / CACA — 主指南候选
#   - OTHER — 其他机构 (中华医学会 / BSH / EHA / ILROG / WHO / IMS / 无组织共识 等)
# 联合共识如 "CACA、中华医学会、CSCO 指南..." 会同时归 CACA + CSCO —
# 通过 infer_all_organizations_from_filename 返回全部, 用户选任一 publisher 都能召回。
_ORG_PATTERNS = [
    (re.compile(r"NCCN", re.IGNORECASE), "NCCN"),
    (re.compile(r"CSCO|中国临床肿瘤学会", re.IGNORECASE), "CSCO"),
    (re.compile(r"ESMO", re.IGNORECASE), "ESMO"),
    (re.compile(r"CACA|中国抗癌协会", re.IGNORECASE), "CACA"),
]
# 主指南能选的 publisher 白名单; OTHER 只作补充指南, 不允许作为主指南。
PRIMARY_PUBLISHERS = ["NCCN", "CSCO", "ESMO", "CACA"]
OTHER_PUBLISHER = "OTHER"


def infer_organization_from_filename(filename: str) -> str:
    """按 5 类归属: 4 大匹配到就返对应值; 都匹配不到返 OTHER (纯补充指南类)。"""
    text = filename or ""
    for pattern, org in _ORG_PATTERNS:
        if pattern.search(text):
            return org
    return OTHER_PUBLISHER


def infer_all_organizations_from_filename(filename: str) -> list[str]:
    """列出文件名里出现的**全部** publisher(联合共识时用)。都匹配不到返 ["OTHER"]。"""
    text = filename or ""
    out = []
    for pattern, org in _ORG_PATTERNS:
        if pattern.search(text) and org not in out:
            out.append(org)
    return out or [OTHER_PUBLISHER]


def fetch_orgs_for_doc_ids(doc_ids: list[int]) -> dict[str, list[str]]:
    """Given a list of plm_guidelines doc ids, return {org: [filename, ...]}.

    Used by case_qa / quick_qa to mark which organizations the retrieval actually hit,
    so the response can label primary vs. supplementary.
    """
    if not doc_ids:
        return {}
    client = get_es_client()
    try:
        resp = client.mget(index=PLM_INDEX, body={"ids": [str(d) for d in doc_ids]})
    except Exception as e:
        logger.warning("[fetch_orgs] mget failed: %s", e)
        return {}
    out: dict[str, list[str]] = {}
    for doc in resp.get("docs", []) or []:
        src = doc.get("_source") or {}
        fname = src.get("filename") or ""
        org = src.get("organization") or infer_organization_from_filename(fname)
        if not org:
            continue
        out.setdefault(org, []).append(fname)
    return out


def normalize_guideline_name(name: str) -> str:
    name = re.sub(r"\.pdf$", "", name or "", flags=re.IGNORECASE).strip()
    name = re.sub(r"[（(]\d{4}\.V\d+[）)]", "", name)
    name = re.sub(r"\s+V\d+\.\d{4}\s*$", "", name)
    name = re.sub(r"\s*(中文版|中文|英文版|英文|zh|en)\s*$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^\s*NCCN临床实践指南[：:]\s*", "", name)
    name = re.sub(r"\s+", "", name)
    name = name.replace("／", "/")
    return GUIDELINE_KEY_ALIASES.get(name.lower(), GUIDELINE_KEY_ALIASES.get(name, name)).strip()


def _format_citation_label(chunk: EvidenceChunk) -> str:
    """Standardized citation label with a real page or synthetic fragment locator."""
    name = re.sub(r"\.pdf$", "", chunk.filename or "", flags=re.IGNORECASE).strip()
    name = re.sub(r"\s*(中文版|英文版|zh|en)\s*$", "", name, flags=re.IGNORECASE).strip()
    parts = [name] if name else ["unknown source"]
    section = (chunk.section_title or "").strip()
    synthetic_window = section == "legacy_content_window"
    if section and section.lower() != "unknown" and not synthetic_window:
        if len(section) > 50:
            section = section[:47].rstrip() + "..."
        parts.append(section)
    if chunk.page_start and chunk.page_start > 0:
        locator = "检索内容片段" if synthetic_window else "page"
        if chunk.page_end and chunk.page_end > chunk.page_start:
            parts.append(f"{locator} {chunk.page_start}-{chunk.page_end}")
        else:
            parts.append(f"{locator} {chunk.page_start}")
    return " | ".join(parts)


def _shorten(text: str, limit: int = MAX_EVIDENCE_TEXT_CHARS) -> str:
    """Normalize whitespace only. Truncation has been removed so the
    answer LLM sees every chunk in full. The ``limit`` argument is
    kept for callsite compatibility but ignored when 0 (the default
    after the no-truncation refactor)."""
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "\n...[truncated]"
    return text


def _extract_focus_terms(text: str) -> list[str]:
    terms: list[str] = []
    if not text:
        return terms

    # Preserve common regimen/drug abbreviations and mixed letter-number biomarkers.
    for match in re.findall(r"\b[A-Z][A-Z0-9+\-/]{1,}\b", text):
        if match not in terms and len(match) <= 30:
            terms.append(match)

    cn_drug_terms = re.findall(
        r"[\u4e00-\u9fffA-Za-z0-9+\-/]*(?:"
        r"替尼|单抗|珠单抗|昔单抗|妥昔|利妥昔|尤单抗|布单抗|"
        r"贝伐珠|帕博利珠|纳武利尤|阿替利珠|度伐利尤|伊匹木|"
        r"阿糖胞苷|柔红霉素|达诺鲁比星|伊达比星|砷|维甲酸|"
        r"甲氨蝶呤|环磷酰胺|紫杉醇|多西他赛|长春新碱|长春瑞滨|"
        r"铂|卡铂|顺铂|奥沙利铂|吉西他滨|培美曲塞|氟尿嘧啶|卡培他滨|"
        r"伊立替康|依托泊苷|多柔比星|表柔比星|米托蒽醌|博来霉素|"
        r"来那度胺|沙利度胺|泊马度胺|硼替佐米|卡非佐米|"
        r"伊布替尼|奥拉帕尼|维奈克拉|阿扎胞苷|地西他滨|"
        r"索拉非尼|仑伐替尼|瑞戈非尼|阿帕替尼|舒尼替尼|"
        r"吉妥珠|奥妥珠|维布妥昔|泽布替尼|阿可替尼|"
        r"西达本胺|信迪利|特瑞普利|卡瑞利珠|替雷利珠"
        r")[\u4e00-\u9fffA-Za-z0-9+\-/]*",
        text,
    )
    for term in cn_drug_terms:
        if term and term not in terms:
            terms.append(term)

    return terms[:16]


def _build_template_queries(
    user_query: str,
    diagnosis: str = "",
    key_features: str = "",
    patient_text: str = "",
    intent: str = "treatment",
) -> list[EvidenceQuery]:
    """Fallback: rule-based evidence query generation."""
    diagnosis = (diagnosis or "").strip()
    key_features = (key_features or "").strip()
    base = " ".join(x for x in [diagnosis, key_features] if x).strip() or user_query
    focus_terms = " ".join(_extract_focus_terms(" ".join([user_query, patient_text, key_features])))
    rich_base = " ".join(x for x in [base, focus_terms] if x).strip()

    queries = [
        EvidenceQuery(user_query, intent, "PRIMARY_QUESTION"),
        EvidenceQuery(f"{rich_base} guideline recommendation", intent, "TREATMENT_OPTION"),
    ]

    if _looks_like_plan_audit(user_query, patient_text):
        queries.extend([
            EvidenceQuery(f"{rich_base} evaluate plan correct incorrect error contraindication", intent, "PLAN_AUDIT"),
            EvidenceQuery(f"{rich_base} immediately start treatment waiting confirmation do not delay", intent, "URGENT_ACTION"),
            EvidenceQuery(f"{rich_base} invasive procedure catheter lumbar puncture platelet coagulation contraindication", intent, "PROCEDURE_SAFETY"),
        ])

    if intent in {"diagnosis", "diagnosis_check"}:
        queries.extend([
            EvidenceQuery(f"{rich_base} diagnosis criteria classification staging risk stratification", intent, "DIAGNOSIS_CRITERIA"),
            EvidenceQuery(f"{rich_base} diagnostic workup testing pathology molecular imaging", intent, "WORKUP"),
        ])
    elif intent == "examination":
        queries.extend([
            EvidenceQuery(f"{rich_base} workup evaluation testing baseline organ function monitoring", intent, "WORKUP"),
            EvidenceQuery(f"{rich_base} special population renal hepatic cardiac age monitoring", intent, "SPECIAL_POPULATION"),
        ])
    else:
        queries.extend([
            EvidenceQuery(f"{rich_base} contraindication discontinue stop avoid not recommended", intent, "CONTRAINDICATION"),
            EvidenceQuery(f"{rich_base} toxicity adverse event management neurologic renal hepatic cardiac", intent, "TOXICITY_MANAGEMENT"),
            EvidenceQuery(f"{rich_base} dose modification dose reduction adjust renal age elderly", intent, "DOSE_MODIFICATION"),
            EvidenceQuery(f"{rich_base} sequence switch consolidation maintenance protocol regimen do not mix", intent, "SEQUENCING_RULE"),
            EvidenceQuery(f"{rich_base} alternative regimen after intolerance toxicity", intent, "ALTERNATIVE_OPTION"),
            EvidenceQuery(f"{rich_base} monitoring response assessment follow-up", intent, "MONITORING"),
        ])

    seen = set()
    deduped: list[EvidenceQuery] = []
    for item in queries:
        key = re.sub(r"\s+", " ", item.query.strip().lower())
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[:10]


async def _generate_queries_with_llm(
    llm_caller: LLMCaller,
    user_query: str,
    diagnosis: str,
    key_features: str,
    patient_text: str,
    intent: str,
) -> list[EvidenceQuery] | None:
    from agent.patient_like_me.v1.rag import prompts

    prompt = prompts.EVIDENCE_QUERY_GEN_USER.format(
        user_query=user_query,
        diagnosis=diagnosis or "未明确",
        key_features=key_features or "无",
        patient_text=patient_text or user_query,
        intent=intent,
    )
    try:
        raw = await llm_caller(prompts.EVIDENCE_QUERY_GEN_SYSTEM, prompt)
        data = json.loads((raw or "").strip().removeprefix("```json").removesuffix("```"))
        queries: list[EvidenceQuery] = []
        for item in data.get("queries", []):
            q = (item.get("query") or "").strip()
            et = (item.get("evidence_type") or "PRIMARY_QUESTION").strip()
            if q:
                queries.append(EvidenceQuery(q, intent, et))
        if queries:
            logger.info("[query_gen] LLM generated %d queries", len(queries))
            return queries[:10]
    except Exception:
        logger.warning("[query_gen] LLM query generation failed, will use template fallback")
    return None


async def _detect_evidence_gaps(
    llm_caller: LLMCaller,
    diagnosis: str,
    key_features: str,
    patient_text: str,
    chunks: list["EvidenceChunk"],
) -> list[EvidenceQuery]:
    from agent.patient_like_me.v1.rag import prompts

    summary_lines = []
    for i, chunk in enumerate(chunks, 1):
        types_str = ", ".join(chunk.evidence_types[:3])
        preview = chunk.text[:120].replace("\n", " ")
        summary_lines.append(f"{i}. [{types_str}] {chunk.section_title or 'unknown'} — {preview}")
    evidence_summary = "\n".join(summary_lines)

    prompt = prompts.EVIDENCE_GAP_DETECT_USER.format(
        diagnosis=diagnosis or "未明确",
        key_features=key_features or "无",
        patient_text=patient_text or "",
        evidence_summary=evidence_summary,
    )
    try:
        raw = await llm_caller(prompts.EVIDENCE_GAP_DETECT_SYSTEM, prompt)
        data = json.loads((raw or "").strip().removeprefix("```json").removesuffix("```"))
        queries: list[EvidenceQuery] = []
        for item in data.get("gap_queries", []):
            q = (item.get("query") or "").strip()
            et = (item.get("evidence_type") or "PRIMARY_QUESTION").strip()
            if q:
                queries.append(EvidenceQuery(q, "treatment", et))
        logger.info("[gap_detect] found %d gap queries", len(queries))
        return queries[:4]
    except Exception:
        logger.warning("[gap_detect] evidence gap detection failed")
        return []


def _extract_specific_terms(queries: list[EvidenceQuery]) -> list[str]:
    """Extract specific biomedical terms from queries for targeted keyword retrieval."""
    terms: list[str] = []
    seen: set[str] = set()
    stop = {"the", "and", "for", "with", "from", "not", "all", "nccn", "who", "eln",
            "aml", "apl", "all", "mds", "hct", "bmt", "cns", "tlx", "pcr", "ngs"}

    for q in queries:
        for m in re.findall(r"\b[A-Z][A-Za-z0-9\-]{2,}(?:\-\d+)?\b", q.query):
            low = m.lower()
            if low not in seen and low not in stop:
                seen.add(low)
                terms.append(m)
        for m in re.findall(r"t\([^)]+\)", q.query):
            if m not in seen:
                seen.add(m)
                terms.append(m)
        for m in re.findall(r"[A-Z][A-Z0-9]+::[A-Z][A-Z0-9]+", q.query):
            low = m.lower()
            if low not in seen:
                seen.add(low)
                terms.append(m)
    return terms


async def _missing_term_retrieval(
    doc_ids: list[int],
    evidence_queries: list[EvidenceQuery],
    existing_chunks: list[EvidenceChunk],
    max_extra: int = 6,
) -> list[EvidenceChunk]:
    """Find chunks containing specific terms from queries that are absent in all existing chunks."""
    query_terms = _extract_specific_terms(evidence_queries)
    if not query_terms:
        return []

    all_chunk_text_lower = " ".join(c.text.lower() for c in existing_chunks)
    missing = [t for t in query_terms if t.lower() not in all_chunk_text_lower]
    if not missing:
        return []

    logger.info("[missing_terms] %d terms not in any chunk: %s", len(missing), missing[:10])

    client = get_es_client()
    merged: dict[str, EvidenceChunk] = {}

    for term in missing[:8]:
        body = {
            "query": {
                "bool": {
                    "filter": [{"terms": {"doc_id": doc_ids}}],
                    "must": [
                        {"multi_match": {
                            "query": term,
                            "fields": ["text^3", "section_title"],
                            "type": "phrase",
                        }},
                    ],
                }
            },
            "size": 3,
        }
        try:
            hits = await asyncio.to_thread(
                lambda b=body: client.search(index=PLM_CHUNK_INDEX, body=b).get("hits", {}).get("hits", [])
            )
            for hit in hits:
                source = hit.get("_source", {}) or {}
                chunk_id = str(source.get("chunk_id") or hit.get("_id") or "")
                if not chunk_id or chunk_id in merged:
                    continue
                text = source.get("text") or ""
                merged[chunk_id] = EvidenceChunk(
                    chunk_id=chunk_id,
                    doc_id=int(source.get("doc_id") or 0),
                    filename=source.get("filename") or "",
                    page_start=int(source.get("page_start") or 0),
                    page_end=int(source.get("page_end") or source.get("page_start") or 0),
                    section_title=source.get("section_title") or "",
                    text=text,
                    score=float(hit.get("_score") or 0.0) + 5.0,
                    evidence_types=classify_evidence(text),
                    matched_queries=[term],
                )
        except Exception:
            logger.warning("[missing_terms] search failed for term: %s", term)

    return list(merged.values())[:max_extra]


def _looks_like_plan_audit(user_query: str, patient_text: str) -> bool:
    text = f"{user_query}\n{patient_text}"
    return bool(re.search(r"是否正确|对不对|错误|致命|评估|判断|doctor|plan|incorrect|correct", text, re.IGNORECASE))


def classify_evidence(text: str) -> list[str]:
    t = (text or "").lower()
    rules = [
        ("ABSOLUTE_STOP", r"\b(discontinue|stop|stopped|should not be rechallenged|rechallenge .* should not|must not|contraindicated|avoid)\b|停用|禁用|不得|不应再"),
        ("SEQUENCING_RULE", r"not mix|consistently through all components|same regimen|sequence|following|after completion|prior to|跨.*(方案|路径)|混搭|序贯|同一方案"),
        ("URGENT_ACTION", r"immediately|promptly|without delay|do not delay|suspected|initiate|立即|尽快|不得等待|不应等待|高度怀疑"),
        ("PROCEDURE_SAFETY", r"lumbar puncture|central venous|catheter|invasive|platelet|coagulation|fibrinogen|bleeding|腰椎穿刺|中心静脉|导管|有创|血小板|凝血|纤维蛋白原|出血"),
        ("DOSE_MODIFICATION", r"dose (modification|reduction|adjust|restricted|reduce)|\b100\s*to\s*200\s*mg|mg/m|剂量.*(调整|折减|降低|限制)|减量"),
        ("TOXICITY_MANAGEMENT", r"toxicity|adverse|neurologic|cerebellar|nystagmus|ataxia|dysmetria|renal dysfunction|creatinine|毒性|不良反应|肾功能|小脑|共济失调"),
        ("CONTRAINDICATION", r"contraindicat|not recommended|ineligible|avoid|禁忌|不推荐|不适合"),
        ("SPECIAL_POPULATION", r"elderly|older|age|renal|hepatic|cardiac|pregnan|pediatric|>\s*60|≥\s*60|老年|肾|肝|心|妊娠|儿童"),
        ("MONITORING", r"monitor|assessment|follow-up|pcr|mrd|evaluate|surveillance|监测|随访|评估"),
        ("TREATMENT_OPTION", r"preferred regimen|recommended regimen|useful in certain circumstances|therapy|treatment|consolidation|induction|maintenance|治疗|方案|巩固|诱导|维持"),
        ("DIAGNOSIS_CRITERIA", r"diagnos|classification|risk group|staging|criteria|分型|分期|诊断|危险分层"),
    ]
    labels = [label for label, pattern in rules if re.search(pattern, t, flags=re.IGNORECASE)]
    return labels or ["SUPPORTING_TEXT"]


async def _embed(text: str):
    from agent.iit.utils.guidelines.embedding import get_embedding

    if not text or not text.strip():
        return None
    return await asyncio.to_thread(get_embedding, text)


async def search_guideline_documents(
    query: str,
    diagnosis: str = "",
    selector: DocSelector | None = None,
    max_docs: int = 5,
    multi_org: bool = False,
    filter_doc_ids: list[int] | None = None,
    allowed_publishers: list[str] | None = None,
    product_scope: str | None = None,
    accessible_paid_doc_ids: list[str] | None = None,
) -> list[dict]:
    """product_scope: 'sahzu_only' | 'public' | None (兼容旧调用, 不过滤).

    accessible_paid_doc_ids: 已解锁的付费 doc_id 列表; ES 里 paid=true 的文档
    只有 id 在此列表里才可被检索命中。
    """
    client = get_es_client()
    query_vector = await _embed(query.strip())

    # ES 侧硬过滤: product_scope + 付费门禁 + publisher 白名单.
    # 先过滤后 KNN, 避免"想要的 publisher 排在 KNN 20 名外被截掉" 的问题.
    if product_scope is None:
        product_scope = current_product_scope.get()
    if accessible_paid_doc_ids is None:
        accessible_paid_doc_ids = current_accessible_paid_doc_ids.get()
    accessible_set: set[str] = {str(d) for d in (accessible_paid_doc_ids or []) if d}
    scope = (product_scope or "").strip().lower() or None

    allowed_pub_set: set[str] | None = None
    if allowed_publishers:
        allowed_pub_set = {p.upper() for p in allowed_publishers if p}

    def _build_es_filter():
        clauses = []
        if scope == "sahzu_only":
            clauses.append({"term": {"product_scope": "sahzu_only"}})
        elif scope == "public":
            clauses.append({"bool": {"should": [
                {"term": {"product_scope": "public"}},
                {"bool": {"must_not": [{"exists": {"field": "product_scope"}}]}},
            ], "minimum_should_match": 1}})
        elif scope:
            # 任意显式 scope(如 yiyong)按精确值硬过滤, 只搜该产品的专属库
            clauses.append({"term": {"product_scope": scope}})
        # 付费门禁: 未解锁的 paid=true 文档一律屏蔽; 免费文档不受影响。
        allow_paid = list(accessible_set)
        if allow_paid:
            clauses.append({"bool": {"should": [
                {"bool": {"must_not": [{"term": {"paid": True}}]}},
                {"terms": {"_id": allow_paid}},
            ], "minimum_should_match": 1}})
        else:
            clauses.append({"bool": {"must_not": [{"term": {"paid": True}}]}})
        # publisher 白名单: 5 类分类硬过滤. OTHER 展开为"organization 是空/不存在/等于 OTHER".
        if allowed_pub_set:
            pub_clauses = []
            non_other = [p for p in allowed_pub_set if p != OTHER_PUBLISHER]
            if non_other:
                pub_clauses.append({"terms": {"organization": non_other}})
            if OTHER_PUBLISHER in allowed_pub_set:
                pub_clauses.append({"bool": {"should": [
                    {"term": {"organization": OTHER_PUBLISHER}},
                    {"term": {"organization": ""}},
                    {"bool": {"must_not": [{"exists": {"field": "organization"}}]}},
                ], "minimum_should_match": 1}})
            clauses.append({"bool": {"should": pub_clauses, "minimum_should_match": 1}})
        return {"bool": {"filter": clauses}} if clauses else None

    es_filter = _build_es_filter()

    async def _knn(field: str, vector, k: int = 10):
        def _do():
            try:
                knn_body = {"field": field, "query_vector": vector, "k": k, "num_candidates": max(k * 2, 20)}
                if es_filter is not None:
                    knn_body["filter"] = es_filter
                return client.search(
                    index=PLM_INDEX,
                    knn=knn_body,
                    size=k,
                ).get("hits", {}).get("hits", [])
            except Exception:
                logger.exception("Document KNN search failed on %s", field)
                return []

        return await asyncio.to_thread(_do)

    tasks = []
    if query_vector is not None:
        tasks.extend([_knn("title_vector", query_vector), _knn("toc_vector", query_vector), _knn("summary_vector", query_vector)])
    if diagnosis.strip():
        diagnosis_vector = await _embed(diagnosis.strip())
        if diagnosis_vector is not None:
            tasks.append(_knn("title_vector", diagnosis_vector, k=6))

    all_hits = await asyncio.gather(*tasks)
    merged: dict[str, dict] = {}
    for hits in all_hits:
        for hit in hits:
            doc_id = str(hit.get("_id") or "")
            if not doc_id:
                continue
            source = hit.get("_source", {}) or {}
            fname = source.get("filename") or source.get("title_cn") or ""
            org = source.get("organization") or infer_organization_from_filename(fname)
            current = merged.setdefault(doc_id, {
                "id": doc_id,
                "name": fname,
                "summary": (source.get("summary") or "")[:700],
                "guideline_key": source.get("guideline_key") or normalize_guideline_name(fname),
                "organization": org,
                "year": source.get("year"),
                "version": source.get("version"),
                "is_cn_content": bool(source.get("is_cn_content")),
                "score": 0.0,
            })
            current["score"] += float(hit.get("_score") or 0.0)

    if not merged:
        return []

    candidates = sorted(merged.values(), key=lambda item: item.get("score", 0), reverse=True)
    selected_ids: list[str]
    selector_ran = False
    if selector:
        try:
            selected_ids = await selector(diagnosis, query, candidates)
            selector_ran = True
        except Exception:
            logger.exception("LLM document selector failed; falling back to ranked candidates")
            selected_ids = []
    else:
        selected_ids = []

    if not selected_ids:
        # selector 明确判定"候选里没有真正匹配的" (返空 list 且没抛异常) → 尊重它, 返空。
        # 否则 (没传 selector, 或 selector 抛异常) → fallback 到 KNN top.
        if selector_ran:
            return []
        selected_ids = [item["id"] for item in candidates[:max_docs]]

    selected = [merged[str(doc_id)] for doc_id in selected_ids if str(doc_id) in merged]
    selected = _prefer_original_language(selected, candidates)

    if filter_doc_ids is not None:
        # filter_doc_ids 是硬约束: 只允许这些 doc。交集为空时**绝不**回退到全库 top,
        # 否则会把主指南以外的指南(如中文 CACA)泄漏进主报告的诊断/检查证据里。
        filter_set = {str(d) for d in filter_doc_ids}
        selected = [d for d in selected if str(d.get("id")) in filter_set]
        if not selected:
            selected = [c for c in candidates if str(c.get("id")) in filter_set]
        if not selected:
            # 本次 query 的 doc 级 KNN 没召回这些指定 doc → 直接按 id 取其元数据,
            # 让下游 chunk 检索仍严格限定在指定 doc 内进行。
            selected = await _fetch_doc_meta_by_ids(sorted(filter_set))

    # 有 filter_doc_ids 时不允许回退到 candidates[:max_docs](硬约束); 无则维持老兜底。
    _fallback = [] if filter_doc_ids is not None else candidates[:max_docs]
    if multi_org:
        selected = _dedupe_documents_multi_org(selected or _fallback)
    else:
        selected = _dedupe_documents(selected or _fallback)
    return selected[:max_docs]


async def _fetch_doc_meta_by_ids(doc_ids: list[str]) -> list[dict]:
    """按 doc_id 直接从 PLM_INDEX 取 doc 元数据, 形状对齐 search 的候选 dict。
    用于 filter_doc_ids 硬约束下、doc 级 KNN 未召回指定 doc 时的兜底取数。"""
    if not doc_ids:
        return []
    client = get_es_client()

    def _load():
        return client.mget(index=PLM_INDEX, ids=[str(d) for d in doc_ids]).get("docs", [])

    docs = await asyncio.to_thread(_load)
    out: list[dict] = []
    for d in docs:
        if not d.get("found"):
            continue
        s = d.get("_source", {}) or {}
        fname = s.get("filename") or ""
        out.append({
            "id": str(s.get("doc_id") or d.get("_id")),
            "name": fname,
            "summary": (s.get("summary") or "")[:700],
            "guideline_key": s.get("guideline_key") or normalize_guideline_name(fname),
            "organization": s.get("organization"),
            "year": s.get("year"),
            "version": s.get("version"),
            "is_cn_content": bool(s.get("is_cn_content")),
            "score": 0.0,
        })
    return out


def _dedupe_documents(docs: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for doc in docs:
        key = doc.get("guideline_key") or normalize_guideline_name(doc.get("name", ""))
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = doc
            continue
        # Preserve the earlier v1 preference: keep the original/English content when both exist.
        if existing.get("is_cn_content") and not doc.get("is_cn_content"):
            by_key[key] = doc
    return list(by_key.values())


def _dedupe_documents_multi_org(docs: list[dict]) -> list[dict]:
    by_key_org: dict[tuple[str, str], dict] = {}
    for doc in docs:
        gk = doc.get("guideline_key") or normalize_guideline_name(doc.get("name", ""))
        org = doc.get("organization") or infer_organization_from_filename(doc.get("name", ""))
        key = (gk, org)
        existing = by_key_org.get(key)
        if existing is None:
            by_key_org[key] = doc
            continue
        e_year = existing.get("year") or 0
        e_ver = existing.get("version") or 0
        d_year = doc.get("year") or 0
        d_ver = doc.get("version") or 0
        if (d_year, d_ver) > (e_year, e_ver):
            by_key_org[key] = doc
        elif (d_year, d_ver) == (e_year, e_ver):
            if existing.get("is_cn_content") and not doc.get("is_cn_content"):
                by_key_org[key] = doc
    return list(by_key_org.values())


def group_docs_by_organization(docs: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for doc in docs:
        org = doc.get("organization") or infer_organization_from_filename(doc.get("name", ""))
        groups.setdefault(org or "unknown", []).append(doc)
    return groups


def _prefer_original_language(selected: list[dict], candidates: list[dict]) -> list[dict]:
    by_key_original = {
        (doc.get("guideline_key") or normalize_guideline_name(doc.get("name", ""))): doc
        for doc in candidates
        if not doc.get("is_cn_content")
    }
    out = []
    for doc in selected:
        key = doc.get("guideline_key") or normalize_guideline_name(doc.get("name", ""))
        out.append(by_key_original.get(key, doc) if doc.get("is_cn_content") else doc)
    return out


async def _llm_rerank_chunks(
    llm_caller: LLMCaller,
    user_query: str,
    chunks: list[EvidenceChunk],
    top_k: int,
    candidate_pool: int = 60,
) -> list[EvidenceChunk]:
    """Show the LLM each candidate chunk's section title + short preview, let
    it pick the top ones for the actual user question. This replaces having
    to hand-engineer query-generation prompts that anticipate every clinical
    angle (e.g., 'how-to / retesting / principles'). The LLM sees the real
    candidate vocabulary and selects what's actually relevant — no upstream
    prompt rule needed.
    """
    from agent.patient_like_me.v1.rag import prompts

    if not chunks or not user_query.strip():
        return chunks

    # Use chunk lexical/vector score as the initial ordering, then expose the
    # top candidate_pool to the reranker. Anything past that pool is too
    # noisy to be worth the LLM's attention.
    ranked = sorted(chunks, key=lambda c: c.score, reverse=True)[:candidate_pool]
    lines: list[str] = []
    for i, c in enumerate(ranked, 1):
        title = (c.section_title or "(no title)").strip()[:80]
        preview = re.sub(r"\s+", " ", c.text)[:160].strip()
        lines.append(f"{i}. [{title}] {preview}")
    candidates_str = "\n".join(lines)

    prompt = prompts.CHUNK_RERANK_USER.format(
        user_query=user_query.strip()[:1500],
        candidates=candidates_str,
        top_k=top_k,
    )
    try:
        raw = await llm_caller(prompts.CHUNK_RERANK_SYSTEM, prompt)
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        data = json.loads(text)
        selected_idx = data.get("selected") or []
        if not isinstance(selected_idx, list):
            return chunks
        seen: set[int] = set()
        picked: list[EvidenceChunk] = []
        for raw_idx in selected_idx:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= len(ranked) and idx not in seen:
                seen.add(idx)
                picked.append(ranked[idx - 1])
        if not picked:
            return chunks
        # Boost the LLM-picked chunks' scores so downstream balanced
        # selection keeps them. Don't drop the unpicked ones entirely —
        # leave the safety net for the balanced selector.
        for c in picked:
            c.score += 100.0  # large bump but not infinite
        logger.info(
            "[chunk_rerank] LLM picked %d of %d candidates (pool=%d)",
            len(picked), top_k, len(ranked),
        )
        return chunks
    except Exception:
        logger.warning("[chunk_rerank] LLM rerank failed; falling back to score-based selection")
        return chunks


async def search_guideline_chunks(
    doc_ids: list[int],
    evidence_queries: list[EvidenceQuery],
    max_chunks: int = 10,
    user_query: str = "",
    llm_caller: LLMCaller | None = None,
    boost_doc_ids: set[int] | None = None,
    boost_weight: float = 6.0,
) -> list[EvidenceChunk]:
    if not doc_ids:
        return []

    client = get_es_client()
    merged: dict[str, EvidenceChunk] = {}

    def _merge_hit(hit: dict, query_item: EvidenceQuery, rank_bonus: float = 0.0):
        source = hit.get("_source", {}) or {}
        chunk_id = str(source.get("chunk_id") or hit.get("_id") or "")
        if not chunk_id:
            return
        text = source.get("text") or ""
        # 启发式: 跳过纯论文引文 chunk (e.g. "434. Metcalfe K, ... pubmed/15197194")
        # 这种 chunk 对临床决策无价值, 还会让 reasoning 模型反复 cross-check
        if _looks_like_pure_references(text):
            logger.info("[evidence] skip pure-references chunk: %s | %s",
                        chunk_id, (source.get("section_title") or "")[:60])
            return
        chunk = merged.get(chunk_id)
        if chunk is None:
            chunk = EvidenceChunk(
                chunk_id=chunk_id,
                doc_id=int(source.get("doc_id") or 0),
                filename=source.get("filename") or "",
                page_start=int(source.get("page_start") or 0),
                page_end=int(source.get("page_end") or source.get("page_start") or 0),
                section_title=source.get("section_title") or "",
                text=text,
                score=0.0,
                evidence_types=classify_evidence(text),
            )
            merged[chunk_id] = chunk
        chunk.score += float(hit.get("_score") or 0.0) + rank_bonus
        chunk.source_rank += 1
        if query_item.query not in chunk.matched_queries:
            chunk.matched_queries.append(query_item.query)
        if query_item.evidence_type not in chunk.evidence_types:
            chunk.evidence_types.append(query_item.evidence_type)

    for query_item in evidence_queries:
        lexical_body = {
            "query": {
                "bool": {
                    "filter": [{"terms": {"doc_id": doc_ids}}],
                    "should": [
                        {"multi_match": {"query": query_item.query, "fields": ["text^4", "section_title^2", "filename_text"], "type": "best_fields"}},
                        {"match_phrase": {"text": {"query": query_item.query, "boost": 2}}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": max(8, math.ceil(max_chunks / 2)),
        }
        try:
            lexical_hits = await asyncio.to_thread(lambda: client.search(index=PLM_CHUNK_INDEX, body=lexical_body).get("hits", {}).get("hits", []))
            for rank, hit in enumerate(lexical_hits):
                _merge_hit(hit, query_item, rank_bonus=max(0.0, 2.0 - rank * 0.1))
        except Exception:
            logger.exception("Chunk lexical search failed for query: %s", query_item.query[:120])

        try:
            vector = await _embed(query_item.query)
            if vector is not None:
                vector_hits = await asyncio.to_thread(
                    lambda: client.search(
                        index=PLM_CHUNK_INDEX,
                        knn={
                            "field": "text_vector",
                            "query_vector": vector,
                            "k": max(6, math.ceil(max_chunks / 2)),
                            "num_candidates": max(30, max_chunks * 3),
                            "filter": {"terms": {"doc_id": doc_ids}},
                        },
                        size=max(6, math.ceil(max_chunks / 2)),
                    ).get("hits", {}).get("hits", [])
                )
                for rank, hit in enumerate(vector_hits):
                    _merge_hit(hit, query_item, rank_bonus=max(0.0, 1.5 - rank * 0.08))
        except Exception:
            logger.info("Chunk vector search unavailable for query: %s", query_item.query[:120])

    candidate_chunks = list(merged.values())

    # 用户选定指南软加权: 命中 boost_doc_ids 的 chunk 加分, 让它们排到前面(占大头),
    # 但不删同机构其它 doc 的 chunk(够分仍可进)—— 软加权, 非硬锁。放在 rerank/平衡选择前,
    # 让下游排序都吃到加权后的分数。
    if boost_doc_ids:
        for c in candidate_chunks:
            if c.doc_id in boost_doc_ids:
                c.score += boost_weight

    # Insert an LLM-driven section-title rerank before the deterministic
    # balanced selection. Without this, the balanced selector keys off
    # evidence_type/query-hit counts only — which means decision-tree pages
    # whose titles match the user question (e.g. NSCL-17 Recurrence,
    # PRINCIPLES OF BIOMARKER TESTING) often get out-ranked by chunks that
    # merely hit high-weight "contraindication/sequencing" tags. Letting the
    # LLM see candidate section titles lets it route based on what the user
    # actually asked, not on per-rule heuristics in the planner prompt.
    if llm_caller and user_query.strip() and len(candidate_chunks) > max_chunks:
        candidate_chunks = await _llm_rerank_chunks(
            llm_caller=llm_caller,
            user_query=user_query,
            chunks=candidate_chunks,
            top_k=max_chunks,
            candidate_pool=min(60, max(40, max_chunks * 2)),
        )

    chunks = _select_balanced_chunks(candidate_chunks, evidence_queries, max_chunks=max_chunks)
    if chunks:
        return chunks
    return await _fallback_page_search(doc_ids, evidence_queries, max_chunks=max_chunks)


def _select_balanced_chunks(
    chunks: list[EvidenceChunk],
    evidence_queries: list[EvidenceQuery],
    max_chunks: int,
) -> list[EvidenceChunk]:
    """Pick the top ``max_chunks`` purely by score.

    The score already encodes:
      - per-query ES lexical/vector hit strength (rank-bonus weighted)
      - LLM-rerank boost (+100 for chunks the section-title reranker picked)
      - HARD_EVIDENCE_TYPES bump (+8 per match) — kept because the bump comes
        from classify_evidence() reading the chunk text itself, not from LLM
        tagging, so it's still a reliable safety signal.
      - source_rank (how many queries matched the chunk)

    The earlier "every HARD label gets one mandatory slot" and "every
    evidence_query gets one mandatory slot" loops were dropped because they
    forced under-relevant chunks into the top set just to fill a label
    category, and they relied on the LLM's evidence_type tag (now removed
    from the query planner prompt) to define what counts as a match.
    """
    if not chunks:
        return []
    for chunk in chunks:
        hard_hits = len(HARD_EVIDENCE_TYPES.intersection(chunk.evidence_types))
        query_hits = len(set(chunk.matched_queries))
        chunk.score += hard_hits * 8.0 + query_hits * 1.2 + chunk.source_rank * 0.15

    by_score = sorted(chunks, key=lambda item: item.score, reverse=True)
    return by_score[:max_chunks]


async def _fallback_page_search(doc_ids: list[int], evidence_queries: list[EvidenceQuery], max_chunks: int) -> list[EvidenceChunk]:
    client = get_es_client()
    query_terms = set()
    for item in evidence_queries:
        for term in re.findall(r"[A-Za-z0-9\-+/]{3,}|[\u4e00-\u9fff]{2,}", item.query):
            query_terms.add(term.lower())
    if not query_terms:
        return []

    def _load_docs():
        return client.mget(index=PLM_INDEX, ids=[str(doc_id) for doc_id in doc_ids]).get("docs", [])

    docs = await asyncio.to_thread(_load_docs)
    chunks: list[EvidenceChunk] = []
    for doc in docs:
        if not doc.get("found"):
            continue
        source = doc.get("_source", {}) or {}
        filename = source.get("filename") or ""
        text_pages = source.get("text_pages") or _content_to_synthetic_pages(source.get("content") or "")
        for page in text_pages:
            text = page.get("text") or ""
            # 启发式: 同 _merge_hit, 跳过纯论文引文页
            if _looks_like_pure_references(text):
                continue
            lower = text.lower()
            score = sum(1 for term in query_terms if term in lower)
            if score <= 0:
                continue
            page_num = int(page.get("page") or 0)
            chunks.append(EvidenceChunk(
                chunk_id=f"{source.get('doc_id') or doc.get('_id')}:{page_num}",
                doc_id=int(source.get("doc_id") or doc.get("_id")),
                filename=filename,
                page_start=page_num,
                page_end=page_num,
                section_title=page.get("section_title") or "",
                text=text,
                score=float(score),
                evidence_types=classify_evidence(text),
                matched_queries=[evidence_queries[0].query],
            ))
    return _select_balanced_chunks(chunks, evidence_queries, max_chunks=max_chunks)


def _content_to_synthetic_pages(content: str, page_size: int = 3500, overlap: int = 250) -> list[dict]:
    content = (content or "").strip()
    if not content:
        return []
    pages = []
    start = 0
    page_num = 1
    while start < len(content):
        end = min(len(content), start + page_size)
        text = content[start:end]
        pages.append({"page": page_num, "section_title": "legacy_content_window", "text": text})
        if end >= len(content):
            break
        start = max(end - overlap, start + 1)
        page_num += 1
    return pages


async def expand_neighbor_pages(chunks: list[EvidenceChunk], neighbor_pages: int = 1) -> list[EvidenceChunk]:
    if not chunks:
        return []
    client = get_es_client()
    doc_ids = sorted({chunk.doc_id for chunk in chunks if chunk.doc_id})

    def _load_docs():
        return client.mget(index=PLM_INDEX, ids=[str(doc_id) for doc_id in doc_ids]).get("docs", [])

    docs = await asyncio.to_thread(_load_docs)
    page_maps: dict[int, dict[int, dict]] = {}
    for doc in docs:
        if not doc.get("found"):
            continue
        source = doc.get("_source", {}) or {}
        doc_id = int(source.get("doc_id") or doc.get("_id"))
        page_maps[doc_id] = {int(p.get("page") or 0): p for p in source.get("text_pages") or []}

    expanded: list[EvidenceChunk] = []
    for chunk in chunks:
        page_map = page_maps.get(chunk.doc_id, {})
        if not page_map:
            expanded.append(chunk)
            continue
        start = max(1, chunk.page_start - neighbor_pages)
        end = chunk.page_end + neighbor_pages
        pages = [page_map[p] for p in range(start, end + 1) if p in page_map]
        if not pages:
            expanded.append(chunk)
            continue
        merged_text = "\n\n".join(f"<Page {p.get('page')}>\n{p.get('text', '')}\n</Page {p.get('page')}>" for p in pages)
        expanded.append(EvidenceChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            filename=chunk.filename,
            page_start=start,
            page_end=end,
            section_title=chunk.section_title,
            text=merged_text,
            score=chunk.score,
            evidence_types=chunk.evidence_types,
            matched_queries=chunk.matched_queries,
            source_rank=chunk.source_rank,
        ))
    return expanded


def _compact_duplicate_pages(chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
    """页级去重:
    - 先按 chunk 内容指纹去重(老逻辑,处理 chunk 完全重复)
    - 再按 (doc_id, page) 去重:同一页面文本只保留 1 次,合并到 score 最高的 chunk
    - 重写 chunk.text,从每个 chunk 的页文本里剔除已被其他 chunk 占领的页
    """
    # 1) chunk 指纹去重(老逻辑)
    best: dict[tuple[int, int, int, int], EvidenceChunk] = {}
    for chunk in chunks:
        text_fingerprint = re.sub(r"\s+", " ", chunk.text[:240]).strip()
        key = (chunk.doc_id, chunk.page_start, chunk.page_end, hash(text_fingerprint))
        old = best.get(key)
        if old is None or chunk.score > old.score:
            best[key] = chunk
    deduped = sorted(best.values(), key=lambda item: item.score, reverse=True)

    # 2) (doc_id, page_number) 页级去重:每页全局只能出现 1 次
    #    遍历顺序按 score 降序,谁先占领某页就归谁;后面的 chunk 重写 text 移除该页
    PAGE_TAG_RE = re.compile(r"<Page (\d+)>(.*?)</Page \d+>", re.DOTALL)
    seen_pages: set[tuple[int, int]] = set()
    out: list[EvidenceChunk] = []
    for chunk in deduped:
        # 抽 chunk.text 里所有 <Page N>...</Page N> 段
        page_segments = PAGE_TAG_RE.findall(chunk.text)
        if not page_segments:
            # 文本没分页标记,直接保留(防御性)
            out.append(chunk)
            continue
        keep_segments = []
        for page_str, content in page_segments:
            try:
                pnum = int(page_str)
            except Exception:
                keep_segments.append((page_str, content))
                continue
            key = (chunk.doc_id, pnum)
            if key in seen_pages:
                continue
            seen_pages.add(key)
            keep_segments.append((page_str, content))
        if not keep_segments:
            # 整个 chunk 都被其他 chunk 占领,丢弃
            continue
        # 重写 chunk.text
        new_text = "\n\n".join(
            f"<Page {ps}>{ct}</Page {ps}>" for ps, ct in keep_segments
        )
        chunk.text = new_text
        out.append(chunk)
    return out


def format_evidence_pack(
    documents: list[dict],
    evidence_queries: list[EvidenceQuery],
    chunks: list[EvidenceChunk],
    user_query: str,
    diagnosis: str = "",
    intent: str = "treatment",
) -> str:
    # 注: 之前这里会写一段 "# 通用指南证据包 / ## 检索任务 / ## 候选指南文档" 头部,
    # 包含 intent / diagnosis / user_query / doc_id 等元信息,
    # 但 user_query 重复了下游 patient_info 段的内容, doc_id 对 LLM 决策无价值, 已删除。
    lines: list[str] = []
    chunks = _compact_duplicate_pages(chunks)
    # Flat ordering by score (rerank-boosted chunks land at top). The old
    # priority-bucket layout grouped chunks by classify_evidence() tags
    # like 'SEQUENCING_RULE' / 'PROCEDURE_SAFETY', which silently routed
    # generic clinical text (e.g. HER2 retesting in PRINCIPLES OF BIOMARKER
    # TESTING) under a section header that signalled 'treatment ordering /
    # safety' to the answering LLM. The LLM then skipped that block when
    # answering a 'how each test is performed' question. Showing each chunk
    # with its true section_title lets the LLM route by what the chapter
    # actually is.
    ordered_chunks = sorted(chunks, key=lambda c: getattr(c, "score", 0.0), reverse=True)

    lines.append("## 检索到的原文证据")
    char_count = sum(len(line) + 1 for line in lines)
    for idx, chunk in enumerate(ordered_chunks, 1):
        evidence_id = f"E{idx}"
        source_line = f"[{evidence_id}] {_format_citation_label(chunk)}"
        # Don't expose evidence_type/types in the prompt — those labels come
        # from a heuristic classifier (classify_evidence) plus accumulated
        # LLM query tags, and they were misleading the answer LLM into
        # treating biomarker chapters as "urgent action / safety" buckets.
        # The citation label (guideline name | section | pages) already gives
        # the answer LLM the routing signal it needs.
        header = source_line
        body = _shorten(chunk.text)
        addition = f"\n{header}\n{body}\n"
        if MAX_CONTEXT_CHARS and char_count + len(addition) > MAX_CONTEXT_CHARS:
            lines.append("[remaining evidence omitted due to context budget]")
            return "\n".join(lines)
        lines.append(addition)
        char_count += len(addition)

    # 注: 之前这里会追加一段 "## 证据来源索引" + "## 回答约束",
    # 其中索引用 [citation:E*] 格式, 回答约束又重复推 [citation:E*],
    # 跟 prompts.py 主 prompt 的 Citation Rules ("使用 [N]") 冲突,
    # reasoning 模型会反复 cross-check 该用哪种格式 → 删除。
    return "\n".join(lines)


def _primary_label(labels: Iterable[str]) -> str:
    priority = [
        "ABSOLUTE_STOP", "CONTRAINDICATION", "SEQUENCING_RULE", "DOSE_MODIFICATION",
        "TOXICITY_MANAGEMENT", "URGENT_ACTION", "PROCEDURE_SAFETY", "SPECIAL_POPULATION", "TREATMENT_OPTION", "DIAGNOSIS_CRITERIA",
        "WORKUP", "MONITORING",
    ]
    labels_set = set(labels)
    for label in priority:
        if label in labels_set:
            return label
    return next(iter(labels_set), "SUPPORTING_TEXT")


async def retrieve_guideline_evidence_pack(
    user_query: str,
    diagnosis: str = "",
    key_features: str = "",
    patient_text: str = "",
    intent: str = "treatment",
    selector: DocSelector | None = None,
    llm_caller: LLMCaller | None = None,
    max_docs: int = 5,
    max_chunks: int = 10,
    multi_org: bool = False,
    filter_doc_ids: list[int] | None = None,
    allowed_publishers: list[str] | None = None,
    product_scope: str | None = None,
    accessible_paid_doc_ids: list[str] | None = None,
    boost_doc_ids: list[int] | None = None,
) -> tuple[str, list[int]]:
    # Step 1: Generate queries — LLM first, template fallback
    evidence_queries = None
    if llm_caller:
        evidence_queries = await _generate_queries_with_llm(
            llm_caller, user_query, diagnosis, key_features, patient_text, intent,
        )
    if not evidence_queries:
        evidence_queries = _build_template_queries(
            user_query=user_query, diagnosis=diagnosis,
            key_features=key_features, patient_text=patient_text, intent=intent,
        )

    # Step 2: Document retrieval
    doc_query = " ".join(x for x in [diagnosis, user_query, key_features] if x).strip() or user_query
    documents = await search_guideline_documents(
        doc_query, diagnosis=diagnosis, selector=selector, max_docs=max_docs,
        multi_org=multi_org, filter_doc_ids=filter_doc_ids, allowed_publishers=allowed_publishers,
        product_scope=product_scope, accessible_paid_doc_ids=accessible_paid_doc_ids,
    )
    doc_ids = [int(doc["id"]) for doc in documents if str(doc.get("id", "")).isdigit()]

    # Step 3: First-round chunk retrieval (with LLM section-title rerank inside)
    _boost_set = {int(d) for d in boost_doc_ids} if boost_doc_ids else None
    chunks = await search_guideline_chunks(
        doc_ids, evidence_queries, max_chunks=max_chunks,
        user_query=user_query, llm_caller=llm_caller, boost_doc_ids=_boost_set,
    )

    # Step 4: Gap detection — second-round retrieval if needed
    if llm_caller and chunks:
        gap_queries = await _detect_evidence_gaps(
            llm_caller, diagnosis, key_features, patient_text, chunks,
        )
        if gap_queries:
            extra_chunks = await search_guideline_chunks(
                doc_ids, gap_queries, max_chunks=max(6, max_chunks // 3),
                boost_doc_ids=_boost_set,
            )
            existing_ids = {c.chunk_id for c in chunks}
            added = 0
            for c in extra_chunks:
                if c.chunk_id not in existing_ids:
                    chunks.append(c)
                    existing_ids.add(c.chunk_id)
                    added += 1
            evidence_queries = evidence_queries + gap_queries
            logger.info("[evidence_pack] gap round: %d extra retrieved, %d new added", len(extra_chunks), added)

    # Step 4.5: Missing term retrieval — find chunks for specific terms absent from results
    missing_chunks = await _missing_term_retrieval(doc_ids, evidence_queries, chunks, max_extra=6)
    if missing_chunks:
        existing_ids = {c.chunk_id for c in chunks}
        added = 0
        for c in missing_chunks:
            if c.chunk_id not in existing_ids:
                chunks.append(c)
                existing_ids.add(c.chunk_id)
                added += 1
        if added:
            logger.info("[evidence_pack] missing term round: %d found, %d new added", len(missing_chunks), added)

    # Step 5: Expand neighbors and format
    chunks = await expand_neighbor_pages(chunks, neighbor_pages=1)
    context = format_evidence_pack(
        documents=documents,
        evidence_queries=evidence_queries,
        chunks=chunks,
        user_query=user_query,
        diagnosis=diagnosis,
        intent=intent,
    )
    logger.info("[evidence_pack] docs=%d chunks=%d chars=%d", len(documents), len(chunks), len(context))
    return context, doc_ids
