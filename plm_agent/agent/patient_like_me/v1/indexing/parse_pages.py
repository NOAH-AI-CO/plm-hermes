#!/usr/bin/env python3
"""
步骤 2：按页解析 PDF → 单页图送 VLM，一次调用返回结构化 JSON。

- 整页渲染为高清图 + PyMuPDF 提取本页全文（含版面/字体信息，用于识别上标）→ 一并给 Gemini 3 Pro，提取正文、Mermaid、页代码等；prompt 要求**保留所有信息包括上标**（如 <sup>g</sup>）。
- 产出 guideline / file / pages（每页含 body_text, mermaid, page_code, page_type, anchor_page_code, is_entry, next_page_codes），按页码 key 写入 JSON，不落库。

运行方式（在 noah_agent 目录下）：
    cd noah_agent
    python agent/patient_like_me/parse_pages.py [PDF路径]

默认 PDF：同目录下的 DEFAULT_PDF_NAME
输出：同目录下 {pdf_stem}_pages.json
"""
import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

# 将 noah_agent 目录加入 path
_SCRIPT_DIR = Path(__file__).resolve().parent
_NOAH_AGENT_ROOT = _SCRIPT_DIR.parents[1]
if str(_NOAH_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOAH_AGENT_ROOT))

import os
_gcp_key = _SCRIPT_DIR.parents[1] / "gcp_key.json"
if _gcp_key.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_gcp_key)
if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
    os.environ["GOOGLE_CLOUD_PROJECT"] = "noahai-440408"
if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
if not os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

import pymupdf
from PIL import Image

from llm.gcp_models import Gemini31Pro

DEFAULT_PDF_NAME = "NCCN-AML-2024 V3_APL-2.pdf"

# 整页渲染 DPI，尽量接近人眼观感（150–300 常用，200 平衡清晰度与体积）
PAGE_DPI = 300

# 步骤 2 单页结构化输出 schema（一次 VLM 调用返回）
PAGE_EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "body_text": {
            "type": "STRING",
            "description": "正文，不含 Mermaid；按阅读顺序提取",
        },
        "mermaid": {
            "type": "STRING",
            "description": "流程图 Mermaid 字符串，完整节点与边，不合并相同节点",
        },
        "page_code": {
            "type": "STRING",
            "description": "页导航标识：可为纯数字页码（如 1、2）或字母+数字代码（如 APL-3），依文档而定；无则空字符串",
        },
        "page_type": {
            "type": "STRING",
            "description": "flowchart=流程图页 / footnote=脚注页 / content=正文内容页（原则、支持治疗、补充说明等）/ citations=参考文献列表页（[1] xxx 等引用列表）",
        },
        "anchor_page_code": {
            "type": "STRING",
            "description": "仅当 page_type 为 footnote 时填「被注解的那一页」的导航标识（数字或代码），否则空字符串",
        },
        "is_entry": {
            "type": "BOOLEAN",
            "description": "是否为本流程入口页（root page）",
        },
        "next_page_codes": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "本页流程/导航上「下一步可跳转」的页的 page_code 列表（仅含流程图页、内容页等，不含脚注页）",
        },
        "footnote_page_code": {
            "type": "STRING",
            "description": "仅当本页为 flowchart 且文档中存在单独脚注页注解本页时，填该脚注页的 page_code（如 APL-2A），否则空字符串；脚注页勿填入 next_page_codes",
        },
        "global_rule_body": {
            "type": "STRING",
            "description": "若本页出现以下任一类型的说明，提取为净文本：①适用于整份指南的前提/禁忌/定义（如诊断前提、人群排除标准）；②跨多个流程分支均适用的约束（如「诱导与巩固方案必须保持同一路径，不得混搭」、「治疗相关性与原发性同病种采用相同治疗方案」、「特定分子标志物阳性时不推荐对应靶向药」）；③跨阶段的安全与时序规则（如「某类药物治疗结束后须等待特定时间再行相关检测以避免假阳性」、「单次阳性检测须在规定时间窗内复查确认，不得单次即判定复发」、「关键疗效评估须在血象恢复达标后进行，不可提前」）。无上述内容则空字符串。不要把只解释某一个具体框的局部说明写入此处。",
        },
        "flowchart_footnotes": {
            "type": "STRING",
            "description": "仅当 page_type 为 flowchart 时：将本页出现的所有脚注**定义**（如 <sup>a</sup> FLT3 inhibitors are not recommended…、b. Dose reduction…）原文逐行提取，保留上标标签与完整文字，多条用换行分隔；若本页无内联脚注定义或 page_type 非 flowchart，则空字符串。",
        },
    },
    "required": [
        "body_text",
        "mermaid",
        "page_code",
        "page_type",
        "anchor_page_code",
        "is_entry",
        "next_page_codes",
        "footnote_page_code",
        "global_rule_body",
        "flowchart_footnotes",
    ],
}

def _build_page_extract_prompt(pdf_page_text: str) -> str:
    """拼装步骤 2 的 prompt：含 PyMuPDF 提取的页内全文，并要求保留上标。"""
    return f"""请结合「图片」与「下方由 PyMuPDF 从本页 PDF 提取的全文」完成提取。输出中**必须保留所有信息包括上标**：正文与 Mermaid 里若出现脚注引用（如字母 g, h, i, m, n 等上标），请以 <sup>g</sup>、<sup>h,i</sup> 等形式原样保留，便于后续与脚注页对应。

**本页 PDF 提取的全文（PyMuPDF，供与图片对照）**
```
{pdf_page_text[:14000]}
```

请完成以下提取并严格按 JSON 格式输出：

1. **正文 body_text**：按阅读顺序提取**全部**正文，不含流程图。**详略与 PDF 一致**：不要概括或省略，标题、列表、每条 regimen 的完整句子（如 ATRA 45 mg/m²…、or…）等均需保留；脚注引用等**上标请用 <sup>ref</sup> 保留**（如 <sup>g</sup>、<sup>m,n</sup>）。
2. **流程图 mermaid**：若本页为流程图则用 Mermaid 表示，完整保留所有节点与边；节点/边含大量文字时完整保留，不合并相同节点；**节点标签中的上标请用 <sup>g</sup> 等形式保留**。若 page_type 为 content 或 citations，则 mermaid 填空字符串。
3. **页导航标识 page_code**：本页在流程/正文中用于被引用的标识（数字页码或字母数字代码等）；无则空字符串。
4. **页类型 page_type**：四选一。
   - **flowchart**：含流程图（节点、箭头、分支）的页。
   - **footnote**：脚注定义页，列出各上标（如 g, h, i）对应的说明，用于注解另一页（anchor）。
   - **content**：正文内容页，无流程图、非脚注；如「Principles of Supportive Care」、支持治疗要点、补充条款等，指南中有用的说明性正文。
   - **citations**：参考文献/引用列表页，仅列出本指南所引文献（如 [1] Author, et al. Journal year;vol:pages），无临床正文，导航中通常不展示。
5. **anchor_page_code**：仅当 page_type 为 footnote 时填被注解页的导航标识，否则空字符串。
6. **is_entry**：本页是否为该流程的入口页（root page）。
7. **next_page_codes**：本页**流程/导航**上「下一步可跳转」的页的 page_code 列表（如流程图箭头指向的下一页、正文中的「见 XX 页」）。**仅填真正的跳转目标**（流程图页、内容页等），**不要包含脚注页**；脚注页单独用 footnote_page_code 表示。
8. **footnote_page_code**：仅当本页为 **flowchart** 且文档中有**单独一页**列出本页脚注（脚注定义页）时，填该脚注页的 page_code（如 APL-2A）；无或非流程图页则空字符串。后续解析时用此字段即可找到本页对应的脚注页，勿将脚注页填入 next_page_codes。
9. **global_rule_body**：若本页出现以下任一类型的说明，提取为净文本（可含上标标签）：①适用于整份指南的前提/禁忌/定义（如「确诊该疾病的前提条件」「适用人群排除标准」）；②跨多个流程分支均适用的约束（典型例子：「诱导与巩固方案必须保持同一路径，不得将一个试验的诱导与另一个试验的巩固混搭」「治疗相关性（therapy-related）与原发性（de novo）同病种采用相同治疗方案」「特定分子标志物阳性时不推荐对应靶向药」）；③跨阶段的安全与时序规则（典型例子：「某类药物治疗结束后须等待特定时间再行相关检测以避免假阳性」「关键疗效评估须在血象恢复达标后方可进行，不可提前」「单次阳性检测结果须在规定时间窗内于可靠实验室复查确认，不得单次即判定复发」）。无上述内容则空字符串。不要把只解释某一个具体框或仅适用于某一分支的局部说明写入此处。
10. **flowchart_footnotes**：仅当 page_type 为 **flowchart** 时，将本页**内联脚注定义**（如 `<sup>a</sup> FLT3 inhibitors are not recommended for FLT3-positive APL`、`b. Dose reduction…`）**逐行**原文提取，保留上标标签与完整文字，多条用换行分隔；非流程图页或本页无此类定义则**空字符串**。

不要添加额外序号或说明，直接输出符合上述字段的 JSON。"""


def pdf_page_to_jpeg_bytes(pdf_path: str, page_index: int, dpi: int = PAGE_DPI) -> bytes:
    """将 PDF 指定页渲染为高清图，返回 JPEG 字节。"""
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()
    finally:
        doc.close()


_HEADER_Y_THRESHOLD = 70   # blocks with y1 <= 70 are header (watermark + title + nav)
_FOOTER_Y_THRESHOLD = 560  # blocks with y0 >= 560 are footer (category note + copyright)


def _is_header_or_footer_block(block: dict) -> bool:
    """Check if a text block falls in the header or footer region of an NCCN PDF page."""
    bbox = block.get("bbox") or (0, 0, 0, 0)
    y0, y1 = bbox[1], bbox[3]
    return y1 <= _HEADER_Y_THRESHOLD or y0 >= _FOOTER_Y_THRESHOLD


def pdf_page_to_text_with_superscripts(pdf_path: str, page_index: int, strip_header_footer: bool = True) -> str:
    """用 PyMuPDF 提取本页全部文本；对明显小于正文的字体（上标）用 <sup>...</sup> 包裹后拼接，便于 VLM 保留上标。
    strip_header_footer=True 时跳过 NCCN PDF 的页眉/页脚区域。"""
    doc = pymupdf.open(pdf_path)
    try:
        page = doc[page_index]
        raw = page.get_text("dict")
        blocks = raw.get("blocks") or []

        content_blocks = []
        for block in blocks:
            if strip_header_footer and _is_header_or_footer_block(block):
                continue
            content_blocks.append(block)

        sizes = []
        for block in content_blocks:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    s = span.get("size")
                    if s and s > 0:
                        sizes.append(s)
        median_size = float(sorted(sizes)[len(sizes) // 2]) if sizes else 10.0
        superscript_threshold = median_size * 0.75

        block_texts = []
        for block in content_blocks:
            line_texts = []
            for line in block.get("lines", []):
                line_parts = []
                for span in line.get("spans", []):
                    text = span.get("text") or ""
                    if not text:
                        continue
                    size = span.get("size") or 0
                    if size > 0 and size < superscript_threshold:
                        line_parts.append(f"<sup>{text}</sup>")
                    else:
                        line_parts.append(text)
                if line_parts:
                    line_texts.append("".join(line_parts))
            if line_texts:
                block_texts.append("\n".join(line_texts))
        if block_texts:
            return "\n\n".join(block_texts)
        return page.get_text() or ""
    finally:
        doc.close()


def _default_page_extract() -> dict:
    """结构化解析失败时的默认返回值。"""
    return {
        "body_text": "",
        "mermaid": "",
        "page_code": "",
        "page_type": "flowchart",
        "anchor_page_code": "",
        "is_entry": False,
        "next_page_codes": [],
        "footnote_page_code": "",
        "global_rule_body": "",
        "flowchart_footnotes": "",
    }


async def extract_page_with_vlm(
    image_bytes: bytes,
    page_num: int,
    pdf_page_text: str = "",
) -> dict:
    """单页图片 + 本页 PyMuPDF 全文送 VLM，一次调用返回结构化 JSON（含保留上标）。"""
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    llm = Gemini31Pro()
    prompt = _build_page_extract_prompt(pdf_page_text)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            content = await llm(
                user_prompt=prompt,
                images=[img_b64],
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=PAGE_EXTRACT_SCHEMA,
            )
            text = (content or "").strip()
            if not text:
                return _default_page_extract()
            data = json.loads(text)
            # 校验并补全字段
            out = _default_page_extract()
            for key in out:
                if key in data:
                    out[key] = data[key]
            if not isinstance(out.get("next_page_codes"), list):
                out["next_page_codes"] = []
            return out
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(
                    f"Page {page_num} VLM 返回非 JSON: {e}"
                ) from e
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(f"Page {page_num} VLM 调用失败: {e}") from e
    return _default_page_extract()


async def main() -> None:
    if len(sys.argv) >= 2:
        pdf_path = Path(sys.argv[1]).resolve()
    else:
        pdf_path = _SCRIPT_DIR / DEFAULT_PDF_NAME

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF 不存在: {pdf_path}")

    doc = pymupdf.open(str(pdf_path))
    num_pages = len(doc)
    doc.close()

    print(f"正在按页解析 PDF（每页 {PAGE_DPI} DPI → Gemini 3 Pro）: {pdf_path.name}，共 {num_pages} 页。")

    sem = asyncio.Semaphore(3)

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
            print(f"  页 {page_num}/{num_pages} 完成")
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
            "raw_text": f"{body_text}\n\n{mermaid}".strip()
            if (body_text or mermaid)
            else "",
            "summary": "",
            "page_code": data.get("page_code", ""),
            "page_type": data.get("page_type", "flowchart"),
            "anchor_page_code": data.get("anchor_page_code", ""),
            "is_entry": data.get("is_entry", False),
            "next_page_codes": data.get("next_page_codes") or [],
            "footnote_page_code": data.get("footnote_page_code", ""),
            "global_rule_body": (data.get("global_rule_body") or "").strip(),
        }

    guideline = {
        "name": pdf_path.stem,
        "organization": "",
        "version": "",
        "year": None,
        "description": "",
    }
    file_data = {
        "file_path": str(pdf_path),
        "parse_status": "done",
    }
    out = {
        "guideline": guideline,
        "file": file_data,
        "toc": "",
        "pages": pages_by_num,
    }

    out_path = _SCRIPT_DIR / f"{pdf_path.stem}_pages.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已保存: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
