#!/usr/bin/env python3
"""
阶段 care_phase_to_db：从 DB 读取已入库 pages，抽取并写入 Guidance_care_phase。

- 输入：DEFAULT_FILE_PATH（需与阶段一入库的 Guidance_file.file_path 一致）。
- 依赖：先运行 parse_guideline_file（阶段一）完成 pages 入库。
- 行为：读取 flowchart 页 -> LLM 提取 care phases -> 清空并重写该 guideline 的 care phase 表。
"""
DEFAULT_FILE_PATH = "/Users/wuyifu/NoahAgent/noah_agent/agent/patient_like_me/dify/data/25nccn中文_副本/（2025.V1）NCCN临床实践指南：B细胞淋巴瘤中文版.pdf"

import asyncio
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    _root = Path(__file__).resolve().parents[2]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

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

from agent.patient_like_me.v1.guideline import guidance_db
from agent.patient_like_me.v1.indexing.parse_care_phase import (
    build_flowchart_context,
    extract_care_phases_with_llm,
)


def _persist_care_phases(guideline_id: int, care_phases: list[dict]) -> None:
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


async def run_care_phase_pipeline(file_path: str) -> None:
    ok, err = guidance_db.check_guidance_tables_ready()
    if not ok:
        raise RuntimeError(f"解析前检查未通过: {err}")

    path_str = str(Path(file_path).resolve())
    loaded = guidance_db.load_file_and_pages_by_path(path_str)
    if loaded is None:
        raise RuntimeError(
            f"DB 中未找到 file_path={path_str} 的 File/Pages，请先运行阶段一。"
        )
    guideline_id, file_id, pages_by_num, _ = loaded
    print(f"从 DB 加载: Guideline id={guideline_id}, File id={file_id}, Pages={len(pages_by_num)}")

    pages_data = {"pages": pages_by_num}
    flowchart_rows = build_flowchart_context(pages_data)
    print(f"flowchart 页数量: {len(flowchart_rows)}")
    result = await extract_care_phases_with_llm(flowchart_rows)
    care_phases = result.get("care_phases") or []
    _persist_care_phases(guideline_id, care_phases)
    print(f"[DB] Guidance_care_phase 已写入 {len(care_phases)} 条（guideline_id={guideline_id}）")


if __name__ == "__main__":
    file_path = (DEFAULT_FILE_PATH or "").strip()
    if not file_path:
        raise SystemExit("请设置 parse_care_phase_to_db.py 顶部 DEFAULT_FILE_PATH")
    asyncio.run(run_care_phase_pipeline(file_path))
