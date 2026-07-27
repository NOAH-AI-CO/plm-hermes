#!/usr/bin/env python3
"""
阶段二：从 DB 读取已入库的 Guidance File/Pages，解析 flowchart 页的 nodes/edges 与 footnote 页，
合并脚注后入库 GuidanceNode / GuidanceEdgeRule / GuidanceCondition。

- 输入：DEFAULT_FILE_PATH 为阶段一入库时使用的 PDF 路径（DB 中 Guidance_file.file_path），用于查库并加载 pages。
- DEFAULT_PDF_PATH：实际 PDF 路径（用于渲染）；空则与 DEFAULT_FILE_PATH 相同。
- 依赖：需先运行 parse_guideline_file 完成阶段一。

运行方式：改下面两个路径后执行
  python -m noah_agent.agent.patient_like_me.parse_nodes_to_db
"""
# 阶段一入库时的 file_path（DB 查库用），直接改此路径即可
DEFAULT_FILE_PATH = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25nccn中文_副本/（2025.V1）NCCN临床实践指南：B细胞淋巴瘤中文版.pdf"
# 实际 PDF 路径（渲染流程图用）；留空则用 DEFAULT_FILE_PATH
DEFAULT_PDF_PATH = ""
import sys
from pathlib import Path

if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import asyncio
import os

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[2]

_gcp_key = _NOAH_AGENT_ROOT.parent / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from agent.patient_like_me.v1.indexing.parse_pages import PAGE_DPI, pdf_page_to_jpeg_bytes
from agent.patient_like_me.v1.indexing.parse_nodes import (
    extract_footnotes_with_vlm,
    extract_nodes_edges_with_vlm,
)
from agent.patient_like_me.v1.guideline import guidance_db

# VLM 单页超时（秒）与重试次数（已放宽，便于稳定跑完）
STAGE2_FLOWCHART_TIMEOUT_SEC = 600
STAGE2_FOOTNOTE_TIMEOUT_SEC = 900
STAGE2_VLM_MAX_RETRIES = 2


async def _with_timeout_retry(coro_factory, timeout_sec: int, max_retries: int, label: str):
    """对协程加超时与有限次重试。coro_factory 为无参可调用，每次返回新的协程。"""
    last_err = None
    for attempt in range(max_retries + 1):
        coro = coro_factory()
        try:
            return await asyncio.wait_for(coro, timeout=float(timeout_sec))
        except asyncio.TimeoutError as e:
            last_err = e
            if attempt < max_retries:
                print(f"  [超时] {label} {timeout_sec}s，第 {attempt + 1} 次重试…")
            else:
                print(f"  [超时] {label} 已达 {max_retries} 次重试，放弃")
                raise
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                print(f"  [错误] {label}: {e}，第 {attempt + 1} 次重试…")
            else:
                raise
    if last_err is not None:
        raise last_err


async def _process_one_flowchart_page(
    p: dict,
    pdf_path: Path,
    sem: asyncio.Semaphore,
    care_phase_codes: list[str] | None,
) -> tuple[str, dict]:
    """并发任务：解析单个 flowchart 页，返回 (page_code, nodes_edges_dict)。"""
    page_number = int(p.get("page_number", 0))
    page_code = (p.get("page_code") or "").strip() or f"p{page_number}"
    body_text = p.get("body_text", "")
    mermaid = p.get("mermaid", "")
    if not mermaid.strip() and not body_text.strip():
        print(f"  [nodes] 页 {page_number} ({page_code}) 无正文/图，跳过")
        return page_code, {"page_number": page_number, "page_code": page_code, "nodes": [], "edges": []}
    print(f"  [nodes] 正在解析 flowchart 页 {page_number} ({page_code})…")
    async with sem:
        loop = asyncio.get_running_loop()
        image_bytes = await loop.run_in_executor(
            None, pdf_page_to_jpeg_bytes, str(pdf_path), page_number - 1, PAGE_DPI,
        )
        # Capture locals to avoid closure issues across retries
        _ib, _pn, _pc, _bt, _mm, _cpc = image_bytes, page_number, page_code, body_text, mermaid, care_phase_codes
        result = await _with_timeout_retry(
            lambda: extract_nodes_edges_with_vlm(_ib, _pn, _pc, _bt, _mm, care_phase_codes=_cpc),
            STAGE2_FLOWCHART_TIMEOUT_SEC,
            STAGE2_VLM_MAX_RETRIES,
            f"flowchart 页 {page_number} ({page_code})",
        )
    print(f"  [nodes] flowchart 页 {page_number} ({page_code}): {len(result['nodes'])} 节点, {len(result['edges'])} 边")
    return page_code, result


async def _process_one_footnote_page(
    p: dict,
    sem: asyncio.Semaphore,
    nodes_edges_by_page_code: dict,
) -> tuple[str, list]:
    """并发任务：解析单个 footnote 页，返回 (page_code, footnotes_list)。"""
    page_number = int(p.get("page_number", 0))
    page_code = (p.get("page_code") or "").strip() or f"p{page_number}"
    anchor_page_code = (p.get("anchor_page_code") or "").strip()
    body_text = p.get("body_text", "")
    if not anchor_page_code:
        print(f"  [footnote] 页 {page_number} ({page_code}) 无 anchor_page_code，跳过")
        return page_code, []
    anchor_page = nodes_edges_by_page_code.get(anchor_page_code)
    if not anchor_page:
        print(f"  [footnote] 页 {page_number} anchor {anchor_page_code} 无解析结果，跳过")
        return page_code, []
    print(f"  [footnote] 正在解析脚注页 {page_number} ({page_code})，anchor={anchor_page_code}，约 1–3 分钟…")
    async with sem:
        _pn, _pc, _apc, _bt, _ap = page_number, page_code, anchor_page_code, body_text, anchor_page
        result = await _with_timeout_retry(
            lambda: extract_footnotes_with_vlm(_pn, _pc, _apc, _bt, _ap, footnote_image_bytes=None, anchor_image_bytes=None),
            STAGE2_FOOTNOTE_TIMEOUT_SEC,
            STAGE2_VLM_MAX_RETRIES,
            f"脚注页 {page_number} ({page_code})",
        )
    footnotes = result.get("footnotes") or []
    print(f"  [footnote] 页 {page_number} ({page_code}): {len(footnotes)} 条脚注")
    return page_code, footnotes


async def _parse_nodes_flowchart_then_footnote(
    pdf_path: Path,
    pages_by_num: dict,
    sem: asyncio.Semaphore,
    care_phase_codes: list[str] | None = None,
) -> tuple[dict, dict]:
    """返回 (nodes_edges_by_page_code, footnotes_by_page_code)。"""
    page_keys_sorted = sorted(pages_by_num.keys(), key=lambda k: int(k))
    flowchart_keys = [
        k for k in page_keys_sorted
        if (pages_by_num[k].get("page_type") or "flowchart").strip().lower() == "flowchart"
    ]
    footnote_keys = [
        k for k in page_keys_sorted
        if (pages_by_num[k].get("page_type") or "").strip().lower() == "footnote"
    ]
    content_keys = [
        k for k in page_keys_sorted
        if (pages_by_num[k].get("page_type") or "").strip().lower() == "content"
    ]

    nodes_edges_by_page_code: dict[str, dict] = {}
    print(f"  [nodes] 共 {len(flowchart_keys)} 个 flowchart 页、{len(footnote_keys)} 个脚注页、{len(content_keys)} 个 content 页待处理。")

    # content 页：整页文本直接作为单节点，无需 VLM 解析。
    for page_key in content_keys:
        p = pages_by_num[page_key]
        page_number = int(p.get("page_number", 0))
        page_code = (p.get("page_code") or "").strip() or f"p{page_number}"
        body_text = (p.get("body_text") or "").strip()

        inferred_phase_code = (p.get("care_phase_code") or "").strip().lower()
        if not inferred_phase_code and care_phase_codes:
            body_lower = body_text.lower()
            for code in care_phase_codes:
                if code in body_lower:
                    inferred_phase_code = code
                    break
            if not inferred_phase_code:
                inferred_phase_code = care_phase_codes[0]

        nodes_edges_by_page_code[page_code] = {
            "page_number": page_number,
            "page_code": page_code,
            "nodes": [
                {
                    "id": f"{page_code}_content",
                    "title": page_code,
                    "content": body_text,
                    "node_type": "information",
                    "is_entry": True,
                    "is_end": False,
                    "care_phase_code": inferred_phase_code,
                    "entry_conditions": [],
                    "metadata": {},
                }
            ],
            "edges": [],
        }
        print(f"  [content] 页 {page_number} ({page_code}): 整页文本作为单节点入库 (care_phase_code={inferred_phase_code!r})")

    # flowchart 页：并发解析（受 sem 限速）
    flowchart_tasks = [
        _process_one_flowchart_page(pages_by_num[k], pdf_path, sem, care_phase_codes)
        for k in flowchart_keys
    ]
    for page_code, result in await asyncio.gather(*flowchart_tasks):
        nodes_edges_by_page_code[page_code] = result

    # footnote 页：在 flowchart 全部完成后并发解析（依赖 nodes_edges_by_page_code）
    if footnote_keys:
        print(f"  [footnote] 开始并发解析 {len(footnote_keys)} 个脚注页（每页约 1–3 分钟，请耐心等待）。")
    footnote_tasks = [
        _process_one_footnote_page(pages_by_num[k], sem, nodes_edges_by_page_code)
        for k in footnote_keys
    ]
    footnotes_by_page_code: dict[str, list] = {}
    for result in await asyncio.gather(*footnote_tasks, return_exceptions=True):
        if isinstance(result, BaseException):
            print(f"  [footnote] 某脚注页解析失败（已跳过）: {result}")
            continue
        page_code, footnotes = result
        if footnotes:
            footnotes_by_page_code[page_code] = footnotes

    return nodes_edges_by_page_code, footnotes_by_page_code


def _merge_footnotes_into_anchor(nodes_edges: dict, footnotes: list[dict]) -> None:
    """就地修改 nodes_edges 的 nodes[].content、edges[].rule_text。"""
    if not footnotes:
        return
    nodes = nodes_edges.get("nodes") or []
    edges = nodes_edges.get("edges") or []
    nodes_by_id = {n["id"]: n for n in nodes}
    edges_by_id = {e["id"]: e for e in edges}
    for fn in footnotes:
        ref = fn.get("ref", "")
        text = (fn.get("text") or "").strip()
        if not text:
            continue
        suffix = f"\n\n[脚注{ref}] {text}"
        target = (fn.get("target") or "general").strip().lower()
        if target == "node":
            for nid in fn.get("node_ids") or []:
                if nid in nodes_by_id:
                    nodes_by_id[nid]["content"] = (nodes_by_id[nid].get("content") or "") + suffix
        elif target == "edge":
            for eid in fn.get("edge_ids") or []:
                if eid in edges_by_id:
                    edges_by_id[eid]["rule_text"] = (edges_by_id[eid].get("rule_text") or "") + suffix


def _build_condition_expr_from_conditions(conditions: list[dict]) -> dict:
    """
    从 conditions 列表（每项可有 symbol）生成 condition_expr 树。
    默认多个 condition 为 AND；无 symbol 的 condition 不参与树，仅入库 Condition 表。
    """
    symbols = [
        (c.get("symbol") or "").strip()
        for c in conditions
        if (c.get("symbol") or "").strip()
    ]
    if not symbols:
        return {}
    if len(symbols) == 1:
        return {"symbol": symbols[0]}
    return {"op": "and", "children": [{"symbol": s} for s in symbols]}


def _persist_nodes_edges(
    guideline_id: int,
    code_to_page: dict[str, int],
    nodes_edges_by_page_code: dict,
    footnotes_by_page_code: dict,
    pages_by_num: dict,
    phase_code_to_id: dict[str, int] | None = None,
) -> None:
    """将合并脚注后的 nodes/edges/conditions 写入 DB。"""
    page_rows: list[tuple[str, int, dict]] = []
    local_to_db_by_page: dict[str, dict[str, int]] = {}
    entry_nodes_by_page_code: dict[str, list[int]] = {}
    min_id_by_page_code: dict[str, int] = {}
    edges_by_page: dict[str, list[dict]] = {}
    # Tracks which condition symbols have already been written as entry conditions per
    # node db-id, so Pass-2 can propagate edge conditions without creating duplicates.
    node_entry_condition_symbols: dict[int, set[str]] = {}

    # Pass-1: 先全量落 node（含脚注合并），确保后续跨页目标节点可被解析。
    for page_key, p in pages_by_num.items():
        page_type = (p.get("page_type") or "flowchart").strip().lower()
        if page_type not in ("flowchart", "content"):
            continue
        page_code = (p.get("page_code") or "").strip() or f"p{p.get('page_number', 0)}"
        page_number = int(p.get("page_number", 0))
        nodes_edges = nodes_edges_by_page_code.get(page_code)
        if not nodes_edges:
            continue
        page_id = code_to_page.get(page_code)
        if page_id is None:
            continue

        footnote_page_code = (p.get("footnote_page_code") or "").strip()
        if footnote_page_code:
            footnotes = footnotes_by_page_code.get(footnote_page_code) or []
            _merge_footnotes_into_anchor(nodes_edges, footnotes)

        nodes = nodes_edges.get("nodes") or []
        edges = nodes_edges.get("edges") or []
        node_id_to_db_id: dict[str, int] = {}

        for n in nodes:
            phase_code = (n.get("care_phase_code") or "").strip().lower()
            care_phase_id = (phase_code_to_id or {}).get(phase_code)
            db_id = guidance_db.create_guidance_node(
                guideline_id=guideline_id,
                page_id=page_id,
                title=(n.get("title") or "")[:512],
                content=n.get("content") or "",
                node_type=(n.get("node_type") or "information").strip().lower() or "information",
                is_entry=bool(n.get("is_entry", False)),
                is_end=bool(n.get("is_end", False)),
                care_phase_id=care_phase_id,
                metadata_json=n.get("metadata") if isinstance(n.get("metadata"), dict) else {},
            )
            node_id_to_db_id[n.get("id", "")] = db_id
            if n.get("is_entry", False):
                entry_nodes_by_page_code.setdefault(page_code, []).append(db_id)
            for c in n.get("entry_conditions") or []:
                guidance_db.create_guidance_node_entry_condition(
                    node_id=db_id,
                    guideline_id=guideline_id,
                    condition_text=c.get("condition_text") or "",
                    condition_type=(c.get("condition_type") or "clinical").strip().lower() or "clinical",
                    symbol=c.get("symbol") or "",
                    value_type=c.get("value_type") or "",
                    operator=c.get("operator") or "",
                    threshold_value=c.get("threshold_value") or "",
                    structured_json=c.get("structured_json") if isinstance(c.get("structured_json"), dict) else {},
                )
                symbol = (c.get("symbol") or "").strip()
                if symbol:
                    node_entry_condition_symbols.setdefault(db_id, set()).add(symbol)
            cur_min = min_id_by_page_code.get(page_code)
            if cur_min is None or db_id < cur_min:
                min_id_by_page_code[page_code] = db_id

        local_to_db_by_page[page_code] = node_id_to_db_id
        edges_by_page[page_code] = edges
        page_rows.append((page_code, page_number, nodes_edges))
        print(f"  [DB] 页 {page_code}: {len(nodes)} nodes 已入库，待写 {len(edges)} edges")

    # 补齐无 entry 标记页面：退化到该页最小 id 节点。
    for page_code, node_id in min_id_by_page_code.items():
        if page_code not in entry_nodes_by_page_code:
            entry_nodes_by_page_code[page_code] = [node_id]

    # Pass-2: 再落 edge（支持 __next:PAGE_CODE 跨页边）。
    total_edges_written = 0
    for page_code, page_number, _nodes_edges in page_rows:
        node_id_to_db_id = local_to_db_by_page.get(page_code) or {}
        edges = edges_by_page.get(page_code) or []
        page_edges_written = 0
        for e in edges:
            src_id = (e.get("source_id") or "").strip()
            tgt_id = (e.get("target_id") or "").strip()
            src_db_id = node_id_to_db_id.get(src_id)
            if src_db_id is None:
                continue

            target_db_ids: list[int] = []
            same_page_tgt = node_id_to_db_id.get(tgt_id)
            if same_page_tgt is not None:
                target_db_ids = [same_page_tgt]
            elif tgt_id.startswith("__next:"):
                next_code = (tgt_id.split(":", 1)[1] or "").strip()
                target_db_ids = list(entry_nodes_by_page_code.get(next_code) or [])

            if not target_db_ids:
                continue

            conditions_list = e.get("conditions") or []
            condition_expr = _build_condition_expr_from_conditions(conditions_list)
            for tgt_db_id in target_db_ids:
                edge_rule_id = guidance_db.create_guidance_edge_rule(
                    source_node_id=src_db_id,
                    target_node_id=tgt_db_id,
                    rule_text=e.get("rule_text") or "",
                    relation_type=(e.get("relation_type") or "sequence").strip().lower() or "sequence",
                    priority=int(e.get("priority", 0)) if e.get("priority") is not None else 0,
                    rule_signature="",
                    source_page_number=page_number,
                    rule_status="draft",
                    condition_expr=condition_expr,
                    guideline_id=guideline_id,
                )
                for c in e.get("conditions") or []:
                    guidance_db.create_guidance_condition(
                        condition_text=c.get("condition_text") or "",
                        condition_type=(c.get("condition_type") or "clinical").strip().lower() or "clinical",
                        guideline_id=guideline_id,
                        edge_rule_id=edge_rule_id,
                        symbol=c.get("symbol") or "",
                        value_type=c.get("value_type") or "",
                        operator=c.get("operator") or "",
                        threshold_value=c.get("threshold_value") or "",
                        structured_json=c.get("structured_json") if isinstance(c.get("structured_json"), dict) else {},
                    )
                    # Propagate edge conditions to the target node's entry conditions so
                    # that the path-matching LLM can see them without traversing edge lists.
                    symbol = (c.get("symbol") or "").strip()
                    if symbol:
                        existing = node_entry_condition_symbols.setdefault(tgt_db_id, set())
                        if symbol not in existing:
                            guidance_db.create_guidance_node_entry_condition(
                                node_id=tgt_db_id,
                                guideline_id=guideline_id,
                                condition_text=c.get("condition_text") or "",
                                condition_type=(c.get("condition_type") or "clinical").strip().lower() or "clinical",
                                symbol=symbol,
                                value_type=c.get("value_type") or "",
                                operator=c.get("operator") or "",
                                threshold_value=c.get("threshold_value") or "",
                                structured_json=c.get("structured_json") if isinstance(c.get("structured_json"), dict) else {},
                            )
                            existing.add(symbol)
                page_edges_written += 1
                total_edges_written += 1
        print(f"  [DB] 页 {page_code}: {page_edges_written}/{len(edges)} edges 已入库")

    print(f"  [DB] 总计写入 edges: {total_edges_written}")

    # Pass-3: Cross-page reference linking.
    # Scan flowchart pages' text (raw_text, body_text, footnotes, node content)
    # for references to other pages' codes.  Targets include ALL page types with
    # nodes (content, flowchart, etc.) — not just content pages.  For flowchart
    # targets, edges point to entry nodes; for content targets, to all nodes.
    target_code_to_node_ids: dict[str, list[int]] = {}
    for page_key, p in pages_by_num.items():
        page_type = (p.get("page_type") or "").strip().lower()
        if page_type in ("footnote", "citations"):
            continue
        page_code = (p.get("page_code") or "").strip() or f"p{p.get('page_number', 0)}"
        all_db_ids = list((local_to_db_by_page.get(page_code) or {}).values())
        if not all_db_ids:
            continue
        if page_type == "flowchart":
            entry_ids = entry_nodes_by_page_code.get(page_code, [])
            target_code_to_node_ids[page_code] = entry_ids if entry_ids else all_db_ids
        else:
            target_code_to_node_ids[page_code] = all_db_ids

    footnote_text_by_anchor: dict[str, str] = {}
    for page_key, p in pages_by_num.items():
        if (p.get("page_type") or "").strip().lower() != "footnote":
            continue
        anchor_code = (p.get("anchor_page_code") or "").strip()
        if anchor_code:
            footnote_text_by_anchor[anchor_code] = (
                footnote_text_by_anchor.get(anchor_code, "")
                + " " + (p.get("raw_text") or "") + " " + (p.get("body_text") or "")
            )

    if target_code_to_node_ids:
        total_links = 0
        total_ref_edges = 0
        for page_key, p in pages_by_num.items():
            if (p.get("page_type") or "flowchart").strip().lower() != "flowchart":
                continue
            page_code = (p.get("page_code") or "").strip() or f"p{p.get('page_number', 0)}"
            page_id = code_to_page.get(page_code)
            if page_id is None:
                continue
            search_text = (
                (p.get("raw_text") or "") + " "
                + (p.get("body_text") or "") + " "
                + footnote_text_by_anchor.get(page_code, "")
            )
            node_data = nodes_edges_by_page_code.get(page_code)
            if node_data:
                for n in node_data.get("nodes") or []:
                    search_text += " " + (n.get("title") or "") + " " + (n.get("content") or "")
            entry_db_ids = entry_nodes_by_page_code.get(page_code) or []
            for target_code, target_node_ids in target_code_to_node_ids.items():
                if target_code not in search_text:
                    continue
                target_page_id = code_to_page.get(target_code)
                if not target_page_id or target_page_id == page_id:
                    continue
                guidance_db.create_guidance_page_link(page_id, target_page_id, guideline_id=guideline_id)
                print(f"  [link] page_link: {page_code}({page_id}) → {target_code}({target_page_id})")
                total_links += 1
                for src_db_id in entry_db_ids:
                    for tgt_db_id in target_node_ids:
                        guidance_db.create_guidance_edge_rule(
                            source_node_id=src_db_id,
                            target_node_id=tgt_db_id,
                            rule_text=f"See {target_code} (Supportive Care / Reference)",
                            relation_type="reference",
                            priority=0,
                            rule_signature="",
                            source_page_number=int(p.get("page_number", 0)),
                            rule_status="draft",
                            condition_expr={},
                            guideline_id=guideline_id,
                        )
                        total_ref_edges += 1
                        print(f"  [link] edge_rule: node {src_db_id} ({page_code}) → node {tgt_db_id} ({target_code})")
        print(f"  [DB] Pass-3: {total_links} page_links, {total_ref_edges} reference edge_rules 已入库")


async def run_nodes_pipeline(file_path: str, pdf_path: Path) -> None:
    """
    从 DB 按 file_path 加载已入库的 File/Pages，解析 nodes/edges/footnotes 并入库。
    file_path：阶段一入库时写入的 Guidance_file.file_path，用于查库。
    pdf_path：PDF 文件路径，用于渲染流程图页（需存在）。
    """
    # Suppress noisy SSL teardown errors from aiohttp connection pool cleanup.
    # These are benign: the SSL socket closes abruptly after a response is received,
    # causing ClientConnectionError in a background Future that nobody awaits.
    loop = asyncio.get_running_loop()

    def _suppress_ssl_shutdown_errors(loop, context):
        exc = context.get("exception")
        try:
            from aiohttp import ClientConnectionError as _CCE
            if isinstance(exc, _CCE):
                return
        except ImportError:
            pass
        import ssl as _ssl
        if isinstance(exc, _ssl.SSLError):
            return
        loop.default_exception_handler(context)

    loop.set_exception_handler(_suppress_ssl_shutdown_errors)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在（用于渲染流程图页）: {pdf_path}")

    ok, err = guidance_db.check_guidance_tables_ready()
    if not ok:
        raise RuntimeError(
            f"解析前检查未通过: {err}"
        )
    print("数据库连接与 Guidance 表检查通过。")

    path_str = str(Path(file_path).resolve())
    loaded = guidance_db.load_file_and_pages_by_path(path_str)
    if loaded is None:
        raise RuntimeError(
            f"DB 中未找到 file_path={path_str} 的已入库 File/Pages。请先运行 parse_guideline_file 完成阶段一。"
        )
    guideline_id, file_id, pages_by_num, code_to_page = loaded
    print(f"从 DB 加载: Guideline id={guideline_id}, File id={file_id}, Pages={len(pages_by_num)}")

    phases = guidance_db.list_guidance_care_phases(guideline_id)
    phase_code_to_id = {(p.get("code") or "").strip().lower(): p["id"] for p in phases}
    care_phase_codes = list(phase_code_to_id.keys())
    if care_phase_codes:
        print(f"已加载 care phases: {care_phase_codes}")
    else:
        print("未加载到 care phases，nodes 将不绑定 care_phase_id。")

    sem = asyncio.Semaphore(10)
    print("解析 flowchart 页 nodes/edges，再解析 footnote 页")
    nodes_edges_by_page_code, footnotes_by_page_code = await _parse_nodes_flowchart_then_footnote(
        pdf_path,
        pages_by_num,
        sem,
        care_phase_codes=care_phase_codes,
    )

    print("合并脚注并入库 Node/EdgeRule/Condition")
    guidance_db.delete_nodes_edges_conditions_for_guideline(guideline_id)
    _persist_nodes_edges(
        guideline_id,
        code_to_page,
        nodes_edges_by_page_code,
        footnotes_by_page_code,
        pages_by_num,
        phase_code_to_id=phase_code_to_id,
    )

    print("阶段二完成。可在 DB 查看。")


if __name__ == "__main__":
    file_path = (DEFAULT_FILE_PATH or "").strip()
    if not file_path:
        raise SystemExit("请设置 parse_nodes_to_db.py 顶部 DEFAULT_FILE_PATH")
    pdf_path = Path((DEFAULT_PDF_PATH or file_path).strip()).resolve()
    asyncio.run(run_nodes_pipeline(file_path, pdf_path))
