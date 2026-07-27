#!/usr/bin/env python3
"""
阶段 care_phase：从 pages 数据中提取诊疗阶段词表（不落库）。

- 输入：_pages.json（通常由 parse_pages.py 产出，或 DB 还原出的同结构数据）。
- 处理：聚合所有 flowchart 页的 body_text + mermaid，调用 LLM 抽取阶段定义。
- 输出：{pdf_stem}_care_phases.json，包含 care_phases 列表。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[1]
if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

_gcp_key = _SCRIPT_DIR.parents[1] / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

from llm.gcp_models import Gemini31Pro

DEFAULT_PAGES_JSON_PATH = _SCRIPT_DIR / "NCCN-AML-2024 V3_13-22_pages.json"

CARE_PHASE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "care_phases": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "code": {
                        "type": "STRING",
                        "description": "机器可读阶段 code，snake_case。",
                    },
                    "display_name_zh": {
                        "type": "STRING",
                        "description": "中文展示名。",
                    },
                    "display_name_en": {
                        "type": "STRING",
                        "description": "英文展示名（可空）。",
                    },
                    "sort_order": {
                        "type": "INTEGER",
                        "description": "从前到后的顺序，0 开始递增。",
                    },
                    "description": {
                        "type": "STRING",
                        "description": "阶段说明（可空）。",
                    },
                    "enabled": {
                        "type": "BOOLEAN",
                        "description": "是否启用，默认 true。",
                    },
                    "aliases": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "可选别名，便于后续节点匹配。",
                    },
                },
                "required": [
                    "code",
                    "display_name_zh",
                    "display_name_en",
                    "sort_order",
                    "description",
                    "enabled",
                    "aliases",
                ],
            },
        }
    },
    "required": ["care_phases"],
}


def _build_prompt(flowchart_payload: str) -> str:
    return f"""你是临床指南结构化助手。请从以下 flowchart 页数据中抽取「诊疗阶段（care phase）」词表。

目标：
1. 提取该指南中稳定的阶段（例如 induction / consolidation / maintenance / relapse 等）。
2. 同义写法合并到同一阶段（放到 aliases）。
3. 给每个阶段生成稳定 code（snake_case），并给出排序 sort_order（0 开始）。
4. 仅输出阶段词表，不要输出节点或边。
5. 若没有明确阶段，也返回空数组。

输入数据（按页，包含 page_code/body_text/mermaid）：
```json
{flowchart_payload}
```
"""


def load_pages_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_flowchart_context(pages_data: dict) -> list[dict]:
    pages = pages_data.get("pages") or {}
    rows: list[dict] = []
    for k in sorted(pages.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        p = pages.get(k) or {}
        page_type = str(p.get("page_type", "flowchart")).strip().lower()
        if page_type != "flowchart":
            continue
        rows.append(
            {
                "page_number": int(p.get("page_number", 0) or 0),
                "page_code": str(p.get("page_code", "") or "").strip(),
                "body_text": str(p.get("body_text", "") or ""),
                "mermaid": str(p.get("mermaid", "") or ""),
            }
        )
    return rows


def _normalize_care_phases(care_phases: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, row in enumerate(care_phases or []):
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "") or "").strip().lower()
        if not code:
            continue
        aliases = row.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        out.append(
            {
                "code": code[:128],
                "display_name_zh": str(row.get("display_name_zh", "") or "")[:256],
                "display_name_en": str(row.get("display_name_en", "") or "")[:256],
                "sort_order": (
                    int(row.get("sort_order", i))
                    if str(row.get("sort_order", i)).strip()
                    else i
                ),
                "description": str(row.get("description", "") or ""),
                "enabled": bool(row.get("enabled", True)),
                "aliases": [str(x).strip() for x in aliases if str(x).strip()],
            }
        )
    out.sort(key=lambda x: (x["sort_order"], x["code"]))
    return out


async def extract_care_phases_with_llm(flowchart_rows: list[dict]) -> dict:
    llm = Gemini31Pro()
    payload = json.dumps(flowchart_rows, ensure_ascii=False)
    prompt = _build_prompt(payload[:120000])
    content = await llm(
        user_prompt=prompt,
        images=[],
        temperature=0.1,
        response_mime_type="application/json",
        response_schema=CARE_PHASE_SCHEMA,
        # thinking_budget="low",
    )
    text = (content or "").strip()
    if not text:
        return {"care_phases": []}
    data = json.loads(text)
    return {"care_phases": _normalize_care_phases(data.get("care_phases") or [])}


async def main() -> None:
    pages_json_path = Path(DEFAULT_PAGES_JSON_PATH).resolve()
    if len(sys.argv) >= 2:
        pages_json_path = Path(sys.argv[1]).resolve()
    if not pages_json_path.is_file():
        raise FileNotFoundError(f"pages JSON 不存在: {pages_json_path}")

    pages_data = load_pages_json(pages_json_path)
    flowchart_rows = build_flowchart_context(pages_data)
    print(f"flowchart 页数量: {len(flowchart_rows)}")
    result = await extract_care_phases_with_llm(flowchart_rows)

    out = {
        "file_path": str(pages_json_path),
        "care_phases": result.get("care_phases") or [],
    }
    out_path = _SCRIPT_DIR / f"{pages_json_path.stem.replace('_pages', '')}_care_phases.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已保存: {out_path}，共 {len(out['care_phases'])} 个阶段")


if __name__ == "__main__":
    asyncio.run(main())
