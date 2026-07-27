#!/usr/bin/env python3
"""
AML/APL 图谱索引：Stage 1 → 1.5 → 2，高并发。

用法：
    cd noah_agent
    python -m agent.patient_like_me.v1.indexing.run_graph_indexing
"""
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[4]  # indexing → v1 → patient_like_me → agent → noah_agent

_gcp_key = _NOAH_AGENT_ROOT / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

import asyncio
import time

PDFS = [
    "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25年nccn英文_副本/（2026.V3）NCCN临床实践指南：急性髓性白血病.pdf",
]

STAGE1_CONCURRENCY = 8
STAGE2_CONCURRENCY = 3
SKIP_STAGE1 = True
SKIP_STAGE15 = True


async def run_one_pdf(pdf_path_str: str) -> None:
    pdf_path = Path(pdf_path_str).resolve()
    if not pdf_path.is_file():
        print(f"[SKIP] PDF 不存在: {pdf_path}")
        return

    print(f"\n{'='*80}")
    print(f"开始处理: {pdf_path.name}")
    print(f"{'='*80}")

    from agent.patient_like_me.v1.guideline import guidance_db
    from agent.patient_like_me.v1.es.plm_index import make_doc_id
    from agent.patient_like_me.v1.indexing.parse_pages import (
        PAGE_DPI,
        extract_page_with_vlm,
        pdf_page_to_jpeg_bytes,
        pdf_page_to_text_with_superscripts,
    )
    from agent.patient_like_me.v1.indexing.parse_care_phase import (
        build_flowchart_context,
        extract_care_phases_with_llm,
    )
    from agent.patient_like_me.v1.indexing.parse_nodes import (
        extract_footnotes_with_vlm,
        extract_nodes_edges_with_vlm,
    )
    import pymupdf

    ok, err = guidance_db.check_guidance_tables_ready()
    if not ok:
        raise RuntimeError(f"ES 检查未通过: {err}")

    doc_id = make_doc_id(pdf_path.name)
    file_path_str = str(pdf_path)

    t0 = time.time()

    if not SKIP_STAGE1:
        # ── Stage 1: 逐页 VLM 解析 ──────────────────────────────────
        print(f"\n[Stage 1] 逐页解析 pages (concurrency={STAGE1_CONCURRENCY})...")

        doc = pymupdf.open(str(pdf_path))
        num_pages = len(doc)
        doc.close()
        print(f"  共 {num_pages} 页")

        sem1 = asyncio.Semaphore(STAGE1_CONCURRENCY)

        async def parse_one_page(page_index: int) -> tuple[int, dict]:
            async with sem1:
                page_num = page_index + 1
                loop = asyncio.get_event_loop()
                image_bytes = await loop.run_in_executor(
                    None, pdf_page_to_jpeg_bytes, str(pdf_path), page_index, PAGE_DPI,
                )
                pdf_page_text = await loop.run_in_executor(
                    None, pdf_page_to_text_with_superscripts, str(pdf_path), page_index,
                )
                data = await extract_page_with_vlm(image_bytes, page_num, pdf_page_text=pdf_page_text)
                print(f"  [Stage 1] 页 {page_num}/{num_pages} 完成")
                return page_num, data

        results = await asyncio.gather(*[parse_one_page(i) for i in range(num_pages)], return_exceptions=True)

        pages_by_num = {}
        for r in results:
            if isinstance(r, Exception):
                print(f"  [Stage 1] 错误: {r}")
                continue
            page_num, data = r
            body_text = data.get("body_text", "")
            mermaid = data.get("mermaid", "")
            pages_by_num[str(page_num)] = {
                "page_number": page_num,
                "body_text": body_text,
                "mermaid": mermaid,
                "raw_text": f"{body_text}\n\n{mermaid}".strip() if (body_text or mermaid) else "",
                "summary": "",
                "page_code": data.get("page_code", ""),
                "page_type": data.get("page_type", "flowchart"),
                "anchor_page_code": data.get("anchor_page_code", ""),
                "is_entry": data.get("is_entry", False),
                "next_page_codes": data.get("next_page_codes") or [],
                "footnote_page_code": data.get("footnote_page_code", ""),
                "global_rule_body": (data.get("global_rule_body") or "").strip(),
                "flowchart_footnotes": (data.get("flowchart_footnotes") or "").strip(),
            }

        from agent.patient_like_me.v1.indexing.parse_guideline_file import _persist_pages
        guideline_id, file_id, code_to_page = _persist_pages(pdf_path, pages_by_num)
        print(f"  [Stage 1] 完成 — {len(pages_by_num)} pages, guideline_id={guideline_id}, 耗时 {time.time()-t0:.0f}s")
    else:
        print("\n[Stage 1] 跳过（已完成）")

    if not SKIP_STAGE15:
        # ── Stage 1.5: Care Phases ──────────────────────────────────
        t1 = time.time()
        print(f"\n[Stage 1.5] 提取 care phases...")

        loaded = guidance_db.load_file_and_pages_by_path(file_path_str)
        if loaded is None:
            raise RuntimeError(f"DB 中未找到 file_path={file_path_str}")
        guideline_id, file_id, pages_by_num, code_to_page = loaded

        pages_data = {"pages": pages_by_num}
        flowchart_rows = build_flowchart_context(pages_data)
        print(f"  flowchart 页数量: {len(flowchart_rows)}")
        result = await extract_care_phases_with_llm(flowchart_rows)
        care_phases = result.get("care_phases") or []

        guidance_db.delete_care_phases_for_guideline(guideline_id)
        for row in care_phases:
            guidance_db.create_guidance_care_phase(
                guideline_id=guideline_id,
                code=row.get("code") or "",
                display_name_zh=row.get("display_name_zh") or "",
                display_name_en=row.get("display_name_en") or "",
                sort_order=int(row.get("sort_order", 0) or 0),
                description=row.get("description") or "",
                enabled=bool(row.get("enabled", True)),
            )
        print(f"  [Stage 1.5] 完成 — {len(care_phases)} phases, 耗时 {time.time()-t1:.0f}s")
    else:
        print("[Stage 1.5] 跳过（已完成）")

    # ── 加载 DB 数据（Stage 2 需要） ──────────────────────────
    if SKIP_STAGE1 or SKIP_STAGE15:
        loaded = guidance_db.load_file_and_pages_by_path(file_path_str)
        if loaded is None:
            raise RuntimeError(f"DB 中未找到 file_path={file_path_str}")
        guideline_id, file_id, pages_by_num, code_to_page = loaded
        print(f"  从 DB 加载: guideline_id={guideline_id}, pages={len(pages_by_num)}")

    # ── Stage 2: Nodes/Edges/Conditions ──────────────────────────
    t2 = time.time()
    print(f"\n[Stage 2] 解析 nodes/edges/conditions (concurrency={STAGE2_CONCURRENCY})...")

    phases = guidance_db.list_guidance_care_phases(guideline_id)
    phase_code_to_id = {(p.get("code") or "").strip().lower(): p["id"] for p in phases}
    care_phase_codes = list(phase_code_to_id.keys())
    print(f"  care_phase_codes: {care_phase_codes}")

    from agent.patient_like_me.v1.indexing.parse_nodes_to_db import (
        _parse_nodes_flowchart_then_footnote,
        _persist_nodes_edges,
    )

    sem2 = asyncio.Semaphore(STAGE2_CONCURRENCY)
    nodes_edges_by_page_code, footnotes_by_page_code = await _parse_nodes_flowchart_then_footnote(
        pdf_path, pages_by_num, sem2, care_phase_codes=care_phase_codes,
    )

    guidance_db.delete_nodes_edges_conditions_for_guideline(guideline_id)
    _persist_nodes_edges(
        guideline_id, code_to_page,
        nodes_edges_by_page_code, footnotes_by_page_code,
        pages_by_num, phase_code_to_id=phase_code_to_id,
    )

    total_nodes = sum(len(v.get("nodes", [])) for v in nodes_edges_by_page_code.values())
    total_edges = sum(len(v.get("edges", [])) for v in nodes_edges_by_page_code.values())
    print(f"  [Stage 2] 完成 — {total_nodes} nodes, {total_edges} edges, 耗时 {time.time()-t2:.0f}s")

    # ── Stage 2.5: Cross-page edge resolution ──────────────────────
    t25 = time.time()
    print(f"\n[Stage 2.5] 跨页边补全...")
    from agent.patient_like_me.v1.indexing.resolve_cross_page_edges import (
        resolve_cross_page_edges,
    )
    stage25_stats = resolve_cross_page_edges(guideline_id)
    print(f"  [Stage 2.5] 完成 — {stage25_stats}, 耗时 {time.time()-t25:.0f}s")

    print(f"\n[DONE] {pdf_path.name} 全部完成, 总耗时 {time.time()-t0:.0f}s")


async def main():
    total_start = time.time()
    for pdf in PDFS:
        try:
            await run_one_pdf(pdf)
        except Exception as e:
            print(f"\n[ERROR] {Path(pdf).name} 失败: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{'='*80}")
    print(f"全部处理完成, 总耗时 {time.time()-total_start:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
