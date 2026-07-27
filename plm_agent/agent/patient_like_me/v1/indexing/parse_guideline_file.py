#!/usr/bin/env python3
"""
阶段一：指南 PDF 逐页解析（VLM）并入库。

- 输入：一个 PDF 文件路径（单病症指南，如 APL）。
- 流程：逐页解析 pages（VLM，含 global_rule_body）→ 入库 Guideline / GuidanceFile / GuidancePage / GuidancePageLink / GuidancePageGlobalRule。
- 不包含 nodes/edges 解析；阶段二请单独运行 parse_nodes_to_db。

与 translation 一致：通过 guidance_db 写入 Elasticsearch（guidance_guidelines 索引），不依赖 Backend 路径。
索引不存在时会自动创建。

运行方式：改下面 DEFAULT_PDF_PATH 后执行
  python -m noah_agent.agent.patient_like_me.parse_guideline_file
"""
# 直接改此路径即可
DEFAULT_PDF_PATH = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25nccn中文_副本/（2025.V1）NCCN临床实践指南：B细胞淋巴瘤中文版.pdf"

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

# GCP 环境（与 parse_pages 一致）
_gcp_key = _NOAH_AGENT_ROOT.parent / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from agent.patient_like_me.v1.indexing.parse_pages import (
    PAGE_DPI,
    extract_page_with_vlm,
    pdf_page_to_jpeg_bytes,
    pdf_page_to_text_with_superscripts,
)
import pymupdf
from agent.patient_like_me.v1.guideline import guidance_db
from agent.patient_like_me.v1.es.plm_index import make_doc_id


# ---------- 阶段一：逐页解析 pages（内存） ----------


async def _parse_all_pages(pdf_path: Path, sem: asyncio.Semaphore) -> dict:
    """逐页调用 VLM 解析，返回 pages_by_num（key 为页码字符串）。"""
    doc = pymupdf.open(str(pdf_path))
    num_pages = len(doc)
    doc.close()

    async def process_one(page_index: int) -> tuple[int, dict]:
        async with sem:
            page_num = page_index + 1
            loop = asyncio.get_event_loop()
            image_bytes = await loop.run_in_executor(
                None,
                pdf_page_to_jpeg_bytes,
                str(pdf_path),
                page_index,
                PAGE_DPI,
            )
            pdf_page_text = await loop.run_in_executor(
                None,
                pdf_page_to_text_with_superscripts,
                str(pdf_path),
                page_index,
            )
            data = await extract_page_with_vlm(
                image_bytes, page_num, pdf_page_text=pdf_page_text
            )
            print(f"  [pages] 页 {page_num}/{num_pages} 完成")
            return page_num, data

    tasks = [process_one(i) for i in range(num_pages)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    pages_by_num = {}
    for r in results:
        if isinstance(r, Exception):
            raise r
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
    return pages_by_num


def _persist_pages(pdf_path: Path, pages_by_num: dict) -> tuple[int, int, dict]:
    """将 pages 写入 DB，返回 (guideline_id, file_id, code_to_page)。
    code_to_page: code 或 p{page_number} -> page_id (int)。
    """
    guideline_id = guidance_db.create_guideline(
        name=pdf_path.stem,
        organization="",
        version="",
        doc_id=make_doc_id(pdf_path.name),
        year=None,
        description="",
    )
    file_id = guidance_db.create_guidance_file(
        guideline_id=guideline_id,
        file_path=str(pdf_path),
        parse_status="done",
    )

    code_to_page: dict[str, int] = {}
    page_num_to_page_id: dict[int, int] = {}
    for page_key, p in sorted(pages_by_num.items(), key=lambda x: int(x[0])):
        raw = p.get("raw_text", "")
        code = (p.get("page_code") or "").strip()
        page_type = (p.get("page_type") or "flowchart").strip().lower()
        if page_type not in ("flowchart", "footnote", "content", "citations", "toc", "intro"):
            page_type = "flowchart"
        page_number = int(p.get("page_number", 0))
        is_entry = bool(p.get("is_entry", False))
        layout = {"body_text": p.get("body_text", ""), "mermaid": p.get("mermaid", "")}

        page_id = guidance_db.create_guidance_page(
            file_id=file_id,
            page_number=page_number,
            code=code,
            page_type=page_type,
            anchor_page_id=None,
            is_entry=is_entry,
            raw_text=raw,
            summary=p.get("summary", ""),
            layout_json=layout,
            flowchart_footnotes=p.get("flowchart_footnotes", ""),
            guideline_id=guideline_id,
        )
        page_num_to_page_id[page_number] = page_id
        guidance_db.upsert_guidance_page_global_rule(
            guideline_id=guideline_id,
            page_id=page_id,
            body=p.get("global_rule_body") or "",
        )
        if code:
            code_to_page[code] = page_id
        code_to_page[f"p{page_number}"] = page_id

    for page_key, p in pages_by_num.items():
        anchor_code = (p.get("anchor_page_code") or "").strip()
        if not anchor_code:
            continue
        page_number = int(p.get("page_number", 0))
        footnote_page_id = page_num_to_page_id.get(page_number)
        anchor_page_id = code_to_page.get(anchor_code)
        if footnote_page_id is not None and anchor_page_id is not None:
            guidance_db.update_guidance_page_anchor(footnote_page_id, anchor_page_id, guideline_id=guideline_id)

    for page_key, p in pages_by_num.items():
        page_number = int(p.get("page_number", 0))
        source_page_id = page_num_to_page_id.get(page_number)
        if source_page_id is None:
            continue
        for next_code in (p.get("next_page_codes") or []):
            next_code = (next_code or "").strip()
            if not next_code:
                continue
            target_page_id = code_to_page.get(next_code)
            if target_page_id is None:
                continue
            guidance_db.create_guidance_page_link(source_page_id, target_page_id, guideline_id=guideline_id)

    print(f"  [DB] Guideline id={guideline_id}, File id={file_id}, Pages={len(page_num_to_page_id)}")
    return guideline_id, file_id, code_to_page


# ---------- main ----------


async def run_pipeline(pdf_path: Path) -> None:
    """只执行阶段一：解析 pages → 入库 Guideline/File/Pages/PageLink。"""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    ok, err = guidance_db.check_guidance_tables_ready()
    if not ok:
        raise RuntimeError(
            f"解析前检查未通过（避免浪费 token），请先修复数据库连接或表结构后再运行。\n{err}"
        )
    print("数据库连接与 Guidance 表检查通过。")

    print(f"阶段一：逐页解析 pages → 入库（{pdf_path.name}）")
    sem = asyncio.Semaphore(3)
    pages_by_num = await _parse_all_pages(pdf_path, sem)
    guideline_id, file_id, code_to_page = _persist_pages(pdf_path, pages_by_num)

    print("阶段一完成。")
    print(
        f"  已入库 Guideline id={guideline_id}, File id={file_id}, Pages={len(pages_by_num)}。"
    )
    print(
        "  解析 care phase：改 parse_care_phase_to_db.py 顶部 DEFAULT_FILE_PATH 后运行。"
    )
    print(
        "  解析 nodes/edges/conditions：改 parse_nodes_to_db.py 顶部 DEFAULT_FILE_PATH 后运行。"
    )


if __name__ == "__main__":
    pdf_path = Path(DEFAULT_PDF_PATH).resolve()
    asyncio.run(run_pipeline(pdf_path))
