"""
Guideline CRUD operations backed by Elasticsearch.

Now uses the unified plm_guidelines index (shared with Path 1 text+vectors).
Graph data (pages, nodes, edge_rules, conditions, care_phases, etc.) is stored
as nested arrays in the same document that holds the PDF text and embeddings.

Document _id = doc_id = int(md5(filename)[:15], 16).
"""
import logging
import os
from datetime import datetime

from elasticsearch import NotFoundError

from agent.patient_like_me.v1.es.plm_index import (
    PLM_INDEX,
    get_es_client,
    ensure_plm_index,
    make_doc_id,
)

logger = logging.getLogger(__name__)

INDEX = PLM_INDEX

# Expose ES client for external callers that reference guidance_db.client
client = property(lambda self: get_es_client())


# ---------------------------------------------------------------------------
# Low-level document helpers
# ---------------------------------------------------------------------------

def _scan_all_guidelines() -> list[dict]:
    """Return all guideline documents that have graph data, sorted by doc_id ascending."""
    try:
        resp = get_es_client().search(
            index=INDEX,
            body={"query": {"term": {"has_graph": True}}, "size": 10000},
        )
        docs = [h["_source"] for h in resp.get("hits", {}).get("hits", [])]
        docs.sort(key=lambda d: d.get("id", d.get("doc_id", 0)))
        return docs
    except Exception as exc:
        logger.error("_scan_all_guidelines failed: %s", exc)
        return []


def _get_guideline_doc(guideline_id: int) -> dict | None:
    try:
        resp = get_es_client().get(index=INDEX, id=str(guideline_id))
        return resp["_source"]
    except NotFoundError:
        return None
    except Exception as exc:
        logger.error("_get_guideline_doc(%d) failed: %s", guideline_id, exc)
        return None


def _save_guideline_doc(guideline_id: int, doc: dict) -> None:
    doc["updated_at"] = datetime.now().isoformat()
    try:
        get_es_client().index(index=INDEX, id=str(guideline_id), document=doc, refresh=True)
    except Exception as exc:
        logger.error("_save_guideline_doc(%d) failed: %s", guideline_id, exc)
        raise


def save_guideline_doc(guideline_id: int, doc: dict) -> None:
    """Public wrapper — save a modified guideline document back to ES."""
    _save_guideline_doc(guideline_id, doc)


def _get_next_id(doc: dict) -> int:
    next_id = doc.get("next_id", 1)
    doc["next_id"] = next_id + 1
    return next_id


# ---------------------------------------------------------------------------
# Public raw-document accessor (used by search_guideline_phase)
# ---------------------------------------------------------------------------

def get_guideline_doc(guideline_id: int) -> dict | None:
    """Return the raw ES source document for a guideline (all sub-entities included)."""
    return _get_guideline_doc(guideline_id)


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------

def check_guidance_tables_ready() -> tuple[bool, str | None]:
    """Verify ES connectivity and ensure the plm_guidelines index is ready."""
    try:
        if not get_es_client().ping():
            return False, "Elasticsearch 连接失败（ping 超时）"
        ensure_plm_index()
        return True, None
    except Exception as exc:
        return False, f"Elasticsearch 连接或索引创建失败: {exc}"


# ---------------------------------------------------------------------------
# Guideline — create or update graph data on an existing unified doc
# ---------------------------------------------------------------------------

def create_guideline(
    name: str,
    organization: str = "",
    version: str = "",
    year: int | None = None,
    description: str = "",
    doc_id: int | None = None,
) -> int:
    """Initialise graph data on a unified document.

    If doc_id is given, use it directly. Otherwise compute from name + ".pdf".
    If the document already exists (from PDF indexing), update it with graph
    metadata and set has_graph=True. Otherwise create a new document.
    """
    ensure_plm_index()
    if doc_id is None:
        filename = name if name.lower().endswith(".pdf") else name + ".pdf"
        doc_id = make_doc_id(filename)

    existing = _get_guideline_doc(doc_id)
    if existing is not None:
        existing["id"] = doc_id
        existing["has_graph"] = True
        existing["guideline_name"] = name
        existing["organization"] = organization or ""
        existing["version"] = version or ""
        existing["year"] = year
        existing["description"] = description or ""
        existing.setdefault("next_id", 1)
        for key in [
            "files", "pages", "page_links", "page_global_rules",
            "care_phases", "nodes", "edge_rules", "conditions",
            "node_entry_conditions",
        ]:
            existing.setdefault(key, [])
        _save_guideline_doc(doc_id, existing)
    else:
        doc = {
            "id": doc_id,
            "doc_id": doc_id,
            "filename": name,
            "has_graph": True,
            "guideline_name": name,
            "organization": organization or "",
            "version": version or "",
            "year": year,
            "description": description or "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "next_id": 1,
            "files": [],
            "pages": [],
            "page_links": [],
            "page_global_rules": [],
            "care_phases": [],
            "nodes": [],
            "edge_rules": [],
            "conditions": [],
            "node_entry_conditions": [],
        }
        get_es_client().index(index=INDEX, id=str(doc_id), document=doc, refresh=True)

    return doc_id


# ---------------------------------------------------------------------------
# Guidance File
# ---------------------------------------------------------------------------

def create_guidance_file(guideline_id: int, file_path: str, parse_status: str = "done") -> int:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return 0
    new_id = _get_next_id(doc)
    doc.setdefault("files", []).append({
        "id": new_id,
        "guideline_id": guideline_id,
        "file_path": file_path,
        "parse_status": parse_status,
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


# ---------------------------------------------------------------------------
# Guidance Page
# ---------------------------------------------------------------------------

def _find_guideline_for_file(file_id: int) -> tuple[int, dict] | None:
    """Return (guideline_id, doc) for the guideline that owns file_id, or None."""
    for doc in _scan_all_guidelines():
        if any(f.get("id") == file_id for f in doc.get("files", [])):
            return int(doc.get("id", doc.get("doc_id", 0))), doc
    return None


def create_guidance_page(
    file_id: int,
    page_number: int,
    code: str = "",
    page_type: str = "flowchart",
    anchor_page_id: int | None = None,
    is_entry: bool = False,
    raw_text: str = "",
    summary: str = "",
    layout_json: dict | None = None,
    flowchart_footnotes: str = "",
    guideline_id: int | None = None,
) -> int:
    # 老实现: 靠 file_id 在全库 has_graph=True 里遍历 doc 反查其属主。
    # 一批 pdf 顺序建图谱时, 大量 doc 都会出现 file_id=1, 遍历返回第一个匹配的
    # 未必是当前 doc, 结果 pages 挂到别人身上。所以显式传入 guideline_id 时,
    # 直接按 id 取, 跳过遍历。
    if guideline_id is not None:
        doc = _get_guideline_doc(int(guideline_id))
        if doc is None:
            return 0
    else:
        found = _find_guideline_for_file(file_id)
        if not found:
            return 0
        guideline_id, doc = found
    new_id = _get_next_id(doc)
    doc.setdefault("pages", []).append({
        "id": new_id,
        "file_id": file_id,
        "page_number": page_number,
        "code": code,
        "page_type": page_type,
        "anchor_page_id": anchor_page_id,
        "is_entry": is_entry,
        "raw_text": raw_text or "",
        "summary": summary or "",
        "layout_json": layout_json or {},
        "flowchart_footnotes": flowchart_footnotes or "",
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


def upsert_guidance_page_global_rule(guideline_id: int, page_id: int, body: str) -> None:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return
    rules = doc.setdefault("page_global_rules", [])
    for r in rules:
        if r.get("page_id") == page_id:
            r["body"] = body or ""
            r["guideline_id"] = guideline_id
            r["updated_at"] = datetime.now().isoformat()
            _save_guideline_doc(guideline_id, doc)
            return
    new_id = _get_next_id(doc)
    rules.append({
        "id": new_id,
        "guideline_id": guideline_id,
        "page_id": page_id,
        "body": body or "",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)


def update_guidance_page_anchor(page_id: int, anchor_page_id: int | None, guideline_id: int | None = None) -> None:
    if guideline_id is not None:
        doc = _get_guideline_doc(int(guideline_id))
        if doc is None:
            return
        for p in doc.get("pages", []):
            if p.get("id") == page_id:
                p["anchor_page_id"] = anchor_page_id
                _save_guideline_doc(int(guideline_id), doc)
                return
        return
    for doc in _scan_all_guidelines():
        for p in doc.get("pages", []):
            if p.get("id") == page_id:
                p["anchor_page_id"] = anchor_page_id
                _save_guideline_doc(int(doc.get("id", doc.get("doc_id", 0))), doc)
                return


def create_guidance_page_link(source_page_id: int, target_page_id: int, guideline_id: int | None = None) -> None:
    def _do(doc: dict, gid: int) -> None:
        links = doc.setdefault("page_links", [])
        if not any(
            l.get("source_page_id") == source_page_id
            and l.get("target_page_id") == target_page_id
            for l in links
        ):
            new_id = _get_next_id(doc)
            links.append({
                "id": new_id,
                "source_page_id": source_page_id,
                "target_page_id": target_page_id,
                "created_at": datetime.now().isoformat(),
            })
            _save_guideline_doc(gid, doc)

    if guideline_id is not None:
        doc = _get_guideline_doc(int(guideline_id))
        if doc is None:
            return
        _do(doc, int(guideline_id))
        return
    for doc in _scan_all_guidelines():
        if any(p.get("id") == source_page_id for p in doc.get("pages", [])):
            _do(doc, int(doc.get("id", doc.get("doc_id", 0))))
            return


# ---------------------------------------------------------------------------
# Guidance Node
# ---------------------------------------------------------------------------

def create_guidance_node(
    guideline_id: int,
    page_id: int | None,
    title: str,
    content: str,
    node_type: str = "information",
    is_entry: bool = False,
    is_end: bool = False,
    care_phase_id: int | None = None,
    metadata_json: dict | None = None,
) -> int:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return 0
    new_id = _get_next_id(doc)
    doc.setdefault("nodes", []).append({
        "id": new_id,
        "guideline_id": guideline_id,
        "page_id": page_id,
        "title": (title or "")[:512],
        "content": content or "",
        "node_type": (node_type or "information").strip().lower() or "information",
        "is_entry": is_entry,
        "is_end": is_end,
        "care_phase_id": care_phase_id,
        "metadata_json": metadata_json or {},
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


def delete_nodes_edges_conditions_for_guideline(guideline_id: int) -> None:
    doc = _get_guideline_doc(guideline_id)
    if doc:
        for key in ["nodes", "edge_rules", "conditions", "node_entry_conditions"]:
            doc[key] = []
        _save_guideline_doc(guideline_id, doc)


# ---------------------------------------------------------------------------
# Care Phase
# ---------------------------------------------------------------------------

def delete_care_phases_for_guideline(guideline_id: int) -> None:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return
    doc["care_phases"] = []
    _save_guideline_doc(guideline_id, doc)


def create_guidance_care_phase(
    guideline_id: int,
    code: str,
    display_name_zh: str = "",
    display_name_en: str = "",
    sort_order: int = 0,
    description: str = "",
    enabled: bool = True,
) -> int:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return 0
    new_id = _get_next_id(doc)
    doc.setdefault("care_phases", []).append({
        "id": new_id,
        "guideline_id": guideline_id,
        "code": (code or "").strip()[:128],
        "display_name_zh": (display_name_zh or "").strip()[:256],
        "display_name_en": (display_name_en or "").strip()[:256],
        "sort_order": int(sort_order),
        "description": (description or "").strip(),
        "enabled": bool(enabled),
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


def upsert_guidance_care_phase(
    guideline_id: int,
    code: str,
    display_name_zh: str = "",
    display_name_en: str = "",
    sort_order: int = 0,
    description: str = "",
    enabled: bool = True,
) -> int:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return 0
    for p in doc.setdefault("care_phases", []):
        if p.get("guideline_id") == guideline_id and p.get("code") == code:
            p["display_name_zh"] = (display_name_zh or "").strip()[:256]
            p["display_name_en"] = (display_name_en or "").strip()[:256]
            p["sort_order"] = int(sort_order)
            p["description"] = (description or "").strip()
            p["enabled"] = bool(enabled)
            _save_guideline_doc(guideline_id, doc)
            return p.get("id")
    return create_guidance_care_phase(
        guideline_id, code, display_name_zh, display_name_en, sort_order, description, enabled
    )


def list_guidance_care_phases(guideline_id: int) -> list[dict]:
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return []
    phases = sorted(
        doc.get("care_phases", []),
        key=lambda x: (x.get("sort_order", 0), x.get("id", 0)),
    )
    return [
        {
            "id": p.get("id"),
            "code": p.get("code"),
            "display_name_zh": p.get("display_name_zh"),
            "display_name_en": p.get("display_name_en"),
            "sort_order": p.get("sort_order"),
            "description": p.get("description"),
            "enabled": p.get("enabled"),
        }
        for p in phases
    ]


# ---------------------------------------------------------------------------
# Global rules text (merged from all pages)
# ---------------------------------------------------------------------------

def merged_guideline_global_rules_text(guideline_id: int) -> str:
    """合并指南"全局规则"文本喂给 LLM。
    只保留 page_type='flowchart' 的页(决策图脚注),跳过 content(封面/编委/章节说明)和
    citations(参考文献) — 后两者跟决策无关,只会让 prompt 爆掉(乳腺癌实测全本 127 万字符,
    其中 content+citations 占 87% 都是垃圾)。
    """
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return ""
    pages = {p.get("id"): p for p in doc.get("pages", [])}
    content_parts: list[tuple[int, int, str, str]] = []
    # 建图阶段历史 bug 会导致同 (page_number, page_code) 出现多条 page 记录;
    # 这里用 (page_number, page_code) 做最终去重,避免 prompt 翻倍。
    seen_key: set[tuple[int, str]] = set()
    for r in doc.get("page_global_rules", []):
        p = pages.get(r.get("page_id"))
        if not p:
            continue
        page_type = (p.get("page_type") or "flowchart").strip().lower()
        # 只塞 flowchart(决策图)的脚注;content / citations 跳过 — 临床决策不需要看封面
        # 编委会名单、参考文献列表,塞进去只会撑爆 prompt 让 LLM reasoning 失焦。
        if page_type != "flowchart":
            continue
        body = (r.get("body") or "").strip()
        page_code = (p.get("code") or "").strip()
        page_number = p.get("page_number") or 0
        key = (int(page_number), page_code)
        if key in seen_key:
            continue
        seen_key.add(key)
        footnotes = (p.get("flowchart_footnotes") or "").strip()
        if footnotes:
            body = (body + "\n\n" + footnotes).strip() if body else footnotes
        label = (
            f"（第 {int(page_number)} 页 {page_code}）"
            if page_code
            else f"（第 {int(page_number)} 页）"
        )
        content_parts.append((page_number, r.get("id"), label, body))
    content_parts.sort()
    parts = [
        f"{label}\n{body.strip()}"
        for pn, rid, label, body in content_parts
        if body and body.strip()
    ]
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Edge Rule
# ---------------------------------------------------------------------------

def create_guidance_edge_rule(
    source_node_id: int,
    target_node_id: int,
    rule_text: str,
    relation_type: str = "sequence",
    priority: int = 0,
    rule_signature: str = "",
    source_page_number: int | None = None,
    rule_status: str = "draft",
    condition_expr: dict | None = None,
    guideline_id: int | None = None,
) -> int:
    def _do(doc: dict, gid: int) -> int:
        new_id = _get_next_id(doc)
        doc.setdefault("edge_rules", []).append({
            "id": new_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "rule_text": rule_text or "",
            "relation_type": (relation_type or "sequence").strip().lower() or "sequence",
            "priority": priority,
            "rule_signature": rule_signature or "",
            "source_page_number": source_page_number,
            "rule_status": (rule_status or "draft").strip().lower() or "draft",
            "condition_expr": condition_expr or {},
            "created_at": datetime.now().isoformat(),
        })
        _save_guideline_doc(gid, doc)
        return new_id

    if guideline_id is not None:
        doc = _get_guideline_doc(int(guideline_id))
        if doc is None:
            return 0
        return _do(doc, int(guideline_id))

    for doc in _scan_all_guidelines():
        if any(n.get("id") == source_node_id for n in doc.get("nodes", [])):
            new_id = _get_next_id(doc)
            doc.setdefault("edge_rules", []).append({
                "id": new_id,
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "rule_text": rule_text or "",
                "relation_type": (relation_type or "sequence").strip().lower() or "sequence",
                "priority": priority,
                "rule_signature": rule_signature or "",
                "source_page_number": source_page_number,
                "rule_status": (rule_status or "draft").strip().lower() or "draft",
                "condition_expr": condition_expr or {},
                "created_at": datetime.now().isoformat(),
            })
            _save_guideline_doc(int(doc.get("id", doc.get("doc_id", 0))), doc)
            return new_id
    return 0


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------

def create_guidance_condition(
    condition_text: str,
    condition_type: str = "clinical",
    guideline_id: int | None = None,
    edge_rule_id: int | None = None,
    symbol: str = "",
    value_type: str = "",
    operator: str = "",
    threshold_value: str = "",
    structured_json: dict | None = None,
) -> int:
    if guideline_id is None and edge_rule_id is not None:
        for doc in _scan_all_guidelines():
            if any(er.get("id") == edge_rule_id for er in doc.get("edge_rules", [])):
                guideline_id = int(doc.get("id", doc.get("doc_id", 0)))
                break
    if guideline_id is None:
        return 0
    doc = _get_guideline_doc(guideline_id)
    if not doc:
        return 0
    new_id = _get_next_id(doc)
    doc.setdefault("conditions", []).append({
        "id": new_id,
        "guideline_id": guideline_id,
        "edge_rule_id": edge_rule_id,
        "symbol": (symbol or "").strip()[:128],
        "condition_text": (condition_text or "").strip(),
        "condition_type": (condition_type or "clinical").strip().lower() or "clinical",
        "value_type": (value_type or "").strip()[:32],
        "operator": (operator or "").strip()[:16],
        "threshold_value": (threshold_value or "").strip()[:256],
        "structured_json": structured_json or {},
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


# ---------------------------------------------------------------------------
# Node Entry Condition
# ---------------------------------------------------------------------------

def create_guidance_node_entry_condition(
    node_id: int,
    condition_text: str,
    condition_type: str = "clinical",
    guideline_id: int | None = None,
    symbol: str = "",
    value_type: str = "",
    operator: str = "",
    threshold_value: str = "",
    structured_json: dict | None = None,
) -> int:
    if guideline_id is None:
        for doc in _scan_all_guidelines():
            if any(n.get("id") == node_id for n in doc.get("nodes", [])):
                guideline_id = int(doc.get("id", doc.get("doc_id", 0)))
                break
    if guideline_id is None:
        return 0
    doc = _get_guideline_doc(guideline_id)
    if not doc:
        return 0
    new_id = _get_next_id(doc)
    doc.setdefault("node_entry_conditions", []).append({
        "id": new_id,
        "guideline_id": guideline_id,
        "node_id": node_id,
        "symbol": (symbol or "").strip()[:128],
        "condition_text": (condition_text or "").strip(),
        "condition_type": (condition_type or "clinical").strip().lower() or "clinical",
        "value_type": (value_type or "").strip()[:32],
        "operator": (operator or "").strip()[:16],
        "threshold_value": (threshold_value or "").strip()[:256],
        "structured_json": structured_json or {},
        "created_at": datetime.now().isoformat(),
    })
    _save_guideline_doc(guideline_id, doc)
    return new_id


# ---------------------------------------------------------------------------
# Query helpers (used by search_guideline_phase and parse_care_phase_to_db)
# ---------------------------------------------------------------------------

def load_file_and_pages_by_path(file_path: str):
    path_norm = str(file_path).strip()
    if not path_norm:
        return None
    for doc in _scan_all_guidelines():
        target_f = next(
            (
                f
                for f in sorted(doc.get("files", []), key=lambda x: x.get("id", 0), reverse=True)
                if f.get("file_path") == path_norm
            ),
            None,
        )
        if not target_f:
            continue
        g_id = int(doc.get("id", doc.get("doc_id", 0)))
        file_id = target_f.get("id")
        f_pages = sorted(
            [p for p in doc.get("pages", []) if p.get("file_id") == file_id],
            key=lambda x: x.get("page_number", 0),
        )
        if not f_pages:
            continue
        id_to_code: dict[int, str] = {}
        code_to_page: dict[str, int] = {}
        anchor_map: dict[int, str] = {}
        for p in f_pages:
            code = (p.get("code") or "").strip() or f"p{p.get('page_number')}"
            id_to_code[p.get("id")] = code
            code_to_page[code] = p.get("id")
            code_to_page[f"p{p.get('page_number')}"] = p.get("id")
            if (p.get("page_type") or "").strip().lower() == "footnote" and p.get("anchor_page_id"):
                anchor_map[p.get("anchor_page_id")] = code
        source_to_targets = {
            p.get("id"): [
                id_to_code[l.get("target_page_id")]
                for l in doc.get("page_links", [])
                if l.get("source_page_id") == p.get("id")
                and l.get("target_page_id") in id_to_code
            ]
            for p in f_pages
        }
        pages_by_num = {
            str(p.get("page_number")): {
                "page_number": p.get("page_number"),
                "page_code": id_to_code[p.get("id")],
                "page_type": (p.get("page_type") or "flowchart").strip().lower(),
                "body_text": (p.get("layout_json") or {}).get("body_text", ""),
                "mermaid": (p.get("layout_json") or {}).get("mermaid", ""),
                "anchor_page_code": id_to_code.get(p.get("anchor_page_id"), ""),
                "footnote_page_code": anchor_map.get(p.get("id"), ""),
                "next_page_codes": source_to_targets.get(p.get("id"), []),
                "raw_text": p.get("raw_text") or "",
                "summary": p.get("summary") or "",
                "is_entry": bool(p.get("is_entry")),
            }
            for p in f_pages
        }
        return g_id, file_id, pages_by_num, code_to_page
    return None


def load_graph_by_doc_id(doc_id: int) -> dict | None:
    """Load graph data directly by doc_id (for generic Path 2 search).

    Returns (guideline_id, file_id) or None if no graph data exists.
    """
    doc = _get_guideline_doc(doc_id)
    if doc is None or not doc.get("has_graph"):
        return None
    files = doc.get("files", [])
    if not files:
        return None
    latest_file = max(files, key=lambda f: f.get("id", 0))
    return doc_id, latest_file.get("id")


def get_entry_page_code(file_id: int, guideline_id: int | None = None):
    if guideline_id is not None:
        docs = [_get_guideline_doc(guideline_id)]
    else:
        docs = _scan_all_guidelines()
    for doc in docs:
        if doc is None:
            continue
        pages = sorted(
            [p for p in doc.get("pages", []) if p.get("file_id") == file_id],
            key=lambda x: x.get("page_number", 0),
        )
        if not pages:
            continue
        target = (
            next((p for p in pages if p.get("is_entry") and (p.get("page_type") or "").strip().lower() == "flowchart"), None)
            or next((p for p in pages if p.get("is_entry")), None)
            or next((p for p in pages if (p.get("page_type") or "").strip().lower() == "flowchart"), None)
        )
        if target:
            return (
                target.get("id"),
                (target.get("code") or "").strip() or f"p{target.get('page_number')}",
                target.get("page_number"),
            )
    return None


def list_entry_pages(file_id: int, guideline_id: int | None = None) -> list[dict]:
    """返回该 file 下所有 is_entry=True 的 flowchart 页(可能多个独立路径入口)。
    每项: {id, code, page_number, summary_text}。
    summary_text = body_text 前 600 字 + mermaid 前 600 字,供 LLM 选择时阅读。
    """
    if guideline_id is not None:
        docs = [_get_guideline_doc(guideline_id)]
    else:
        docs = _scan_all_guidelines()
    out: list[dict] = []
    for doc in docs:
        if doc is None:
            continue
        pages = [p for p in doc.get("pages", []) if p.get("file_id") == file_id]
        flow_entries = [
            p for p in pages
            if p.get("is_entry") and (p.get("page_type") or "").strip().lower() == "flowchart"
        ]
        if not flow_entries:
            flow_entries = [p for p in pages if p.get("is_entry")]
        for p in sorted(flow_entries, key=lambda x: x.get("page_number", 0)):
            layout = p.get("layout_json") or {}
            body = (layout.get("body_text") or "")[:600] if isinstance(layout, dict) else ""
            mermaid = (layout.get("mermaid") or "")[:600] if isinstance(layout, dict) else ""
            raw = (p.get("raw_text") or "")[:600]
            summary = body or mermaid or raw
            out.append({
                "id": p.get("id"),
                "code": (p.get("code") or "").strip() or f"p{p.get('page_number')}",
                "page_number": p.get("page_number"),
                "summary_text": summary,
            })
        if out:
            return out
    return out


def get_page_context_for_search(file_id: int, page_code: str) -> dict | None:
    code_norm = (page_code or "").strip()
    if not code_norm:
        return None
    for doc in _scan_all_guidelines():
        target_p = next(
            (
                p
                for p in doc.get("pages", [])
                if p.get("file_id") == file_id
                and (
                    (p.get("code") or "").strip() == code_norm
                    or f"p{p.get('page_number')}" == code_norm
                )
            ),
            None,
        )
        if not target_p:
            continue
        page_id = target_p.get("id")
        next_codes = [
            (p.get("code") or "").strip() or f"p{p.get('page_number')}"
            for p in doc.get("pages", [])
            if p.get("id")
            in [
                l.get("target_page_id")
                for l in doc.get("page_links", [])
                if l.get("source_page_id") == page_id
            ]
        ]
        p_nodes = sorted(
            [
                {
                    "id": n.get("id"),
                    "title": (n.get("title") or "").strip(),
                    "content": (n.get("content") or "").strip(),
                    "node_type": (n.get("node_type") or "information").strip().lower(),
                    "is_entry": bool(n.get("is_entry")),
                    "is_end": bool(n.get("is_end")),
                }
                for n in doc.get("nodes", [])
                if n.get("page_id") == page_id
            ],
            key=lambda x: x["id"],
        )
        node_ids = {n["id"] for n in p_nodes}
        er_ids_for_page = {
            e.get("id")
            for e in doc.get("edge_rules", [])
            if e.get("source_node_id") in node_ids
        }
        cond_map: dict[int, list] = {}
        for c in doc.get("conditions", []):
            if c.get("edge_rule_id") in er_ids_for_page:
                cond_map.setdefault(c.get("edge_rule_id"), []).append({
                    "symbol": (c.get("symbol") or "").strip(),
                    "condition_text": (c.get("condition_text") or "").strip(),
                    "condition_type": (c.get("condition_type") or "clinical").strip().lower(),
                    "value_type": (c.get("value_type") or "").strip(),
                    "operator": (c.get("operator") or "").strip(),
                    "threshold_value": (c.get("threshold_value") or "").strip(),
                })
        p_edges = [
            {
                "edge_id": e.get("id"),
                "source_node_id": e.get("source_node_id"),
                "target_node_id": e.get("target_node_id"),
                "source_title": next(
                    (n.get("title") or "" for n in p_nodes if n.get("id") == e.get("source_node_id")),
                    "",
                ),
                "target_title": next(
                    (n.get("title") or "" for n in doc.get("nodes", []) if n.get("id") == e.get("target_node_id")),
                    "",
                ),
                "rule_text": (e.get("rule_text") or "").strip(),
                "relation_type": (e.get("relation_type") or "sequence").strip().lower(),
                "priority": e.get("priority", 0),
                "condition_expr": e.get("condition_expr") or {},
                "conditions": cond_map.get(e.get("id"), []),
            }
            for e in sorted(
                [e for e in doc.get("edge_rules", []) if e.get("source_node_id") in node_ids],
                key=lambda x: (-x.get("priority", 0), x.get("id")),
            )
        ]
        return {
            "page_id": page_id,
            "page_code": (target_p.get("code") or "").strip() or f"p{target_p.get('page_number')}",
            "page_number": target_p.get("page_number"),
            "page_type": (target_p.get("page_type") or "flowchart").strip().lower(),
            "body_text": (target_p.get("layout_json") or {}).get("body_text", ""),
            "mermaid": (target_p.get("layout_json") or {}).get("mermaid", ""),
            "nodes": p_nodes,
            "edges": p_edges,
            "next_page_codes": next_codes,
        }
    return None


def get_conditions_by_guideline(guideline_id: int) -> list[dict]:
    doc = _get_guideline_doc(guideline_id)
    if not doc:
        return []
    seen: set[str] = set()
    unique: list[dict] = []
    for c in sorted(doc.get("conditions", []), key=lambda x: x.get("id", 0)):
        s = (c.get("symbol") or "").strip()
        if s and s not in seen:
            seen.add(s)
            unique.append({
                "symbol": s,
                "condition_text": (c.get("condition_text") or "").strip(),
                "condition_type": (c.get("condition_type") or "clinical").strip().lower(),
                "value_type": (c.get("value_type") or "").strip(),
                "operator": (c.get("operator") or "").strip(),
                "threshold_value": (c.get("threshold_value") or "").strip(),
            })
    return unique


def get_node_info(node_id: int) -> dict | None:
    for doc in _scan_all_guidelines():
        n = next((n for n in doc.get("nodes", []) if n.get("id") == node_id), None)
        if n:
            p = next((p for p in doc.get("pages", []) if p.get("id") == n.get("page_id")), None)
            if p:
                return {
                    "id": n.get("id"),
                    "page_id": n.get("page_id"),
                    "title": (n.get("title") or "").strip(),
                    "content": (n.get("content") or "").strip(),
                    "is_entry": bool(n.get("is_entry")),
                    "is_end": bool(n.get("is_end")),
                    "page_code": (p.get("code") or "").strip() or f"p{p.get('page_number')}",
                    "page_number": p.get("page_number"),
                }
    return None


def delete_page_nodes_edges_conditions(guideline_id: int, page_id: int) -> None:
    """Delete all nodes, edge_rules, conditions, and node_entry_conditions for a specific page."""
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return
    page_node_ids = {n["id"] for n in doc.get("nodes", []) if n.get("page_id") == page_id}
    if not page_node_ids:
        return
    doc["nodes"] = [n for n in doc.get("nodes", []) if n.get("page_id") != page_id]
    removed_edge_ids = {
        e["id"] for e in doc.get("edge_rules", [])
        if e.get("source_node_id") in page_node_ids or e.get("target_node_id") in page_node_ids
    }
    doc["edge_rules"] = [e for e in doc.get("edge_rules", []) if e["id"] not in removed_edge_ids]
    doc["conditions"] = [c for c in doc.get("conditions", []) if c.get("edge_rule_id") not in removed_edge_ids]
    doc["node_entry_conditions"] = [c for c in doc.get("node_entry_conditions", []) if c.get("node_id") not in page_node_ids]
    _save_guideline_doc(guideline_id, doc)


def get_page_nodes_edges_for_anchor(guideline_id: int, page_id: int) -> dict:
    """Return nodes and edges for a page in VLM-compatible format."""
    doc = _get_guideline_doc(guideline_id)
    if doc is None:
        return {"nodes": [], "edges": []}

    page_obj = next((p for p in doc.get("pages", []) if p.get("id") == page_id), None)
    page_code = (page_obj.get("code") or "").strip() if page_obj else ""
    page_number = page_obj.get("page_number", 0) if page_obj else 0

    page_nodes = [n for n in doc.get("nodes", []) if n.get("page_id") == page_id]
    node_id_set = {n["id"] for n in page_nodes}

    nodes_out = [
        {
            "id": str(n["id"]),
            "title": (n.get("title") or "").strip(),
            "content": (n.get("content") or "").strip(),
            "node_type": (n.get("node_type") or "information").strip(),
            "is_entry": bool(n.get("is_entry")),
            "is_end": bool(n.get("is_end")),
            "care_phase_code": "",
            "entry_conditions": [],
        }
        for n in page_nodes
    ]

    page_edges = [e for e in doc.get("edge_rules", []) if e.get("source_node_id") in node_id_set]
    edge_conditions: dict[int, list[dict]] = {}
    for c in doc.get("conditions", []):
        eid = c.get("edge_rule_id")
        if eid is not None:
            edge_conditions.setdefault(eid, []).append(c)

    edges_out = [
        {
            "id": f"Edge{e['id']}",
            "source_id": str(e.get("source_node_id", "")),
            "target_id": str(e.get("target_node_id", "")),
            "rule_text": (e.get("rule_text") or "").strip(),
            "relation_type": (e.get("relation_type") or "sequence").strip(),
            "priority": e.get("priority", 0),
            "conditions": [
                {
                    "condition_text": (c.get("condition_text") or "").strip(),
                    "condition_type": (c.get("condition_type") or "clinical").strip(),
                    "symbol": (c.get("symbol") or "").strip(),
                    "value_type": (c.get("value_type") or "").strip(),
                    "operator": (c.get("operator") or "").strip(),
                    "threshold_value": (c.get("threshold_value") or "").strip(),
                }
                for c in edge_conditions.get(e["id"], [])
            ],
        }
        for e in page_edges
    ]

    return {
        "page_number": page_number,
        "page_code": page_code,
        "nodes": nodes_out,
        "edges": edges_out,
    }
