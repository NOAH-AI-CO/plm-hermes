#!/usr/bin/env python3
"""
步骤 3：从单页「图片 + ES 中已提取内容」解析 node / edge，结果写回 ES。

- 输入：ES 中已入库的 file_path（由 parse_guideline_file 阶段写入）+ 页码。
- 对 flowchart 页：渲染该页图 + 传入 body_text / mermaid / page_code，一次 VLM 调用返回 nodes + edges 并写入 ES。
- 对 footnote 页：**不读 PDF 图**，仅用本页 body_text + anchor 页在 ES 中的 nodes/edges 做**纯文本** LLM 解析；
  产出 footnotes 并将脚注文本合并写入对应 anchor 节点/边的 content 字段。
- 同时将结果保存为本地 JSON 文件，便于调试。

运行方式（在 noah_agent 目录下）：
    cd noah_agent
    python agent/patient_like_me/parse_nodes.py

脚本内配置 DEFAULT_FILE_PATH 与 DEFAULT_PAGE，ES 中须已有该 file 的 pages 数据。
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
from agent.patient_like_me.v1.guideline import guidance_db

PAGE_DPI = 300

# ── 脚本配置（直接改这两行即可）──────────────────────────────────────────────────
# ES 中入库时使用的 file_path（对应 guidance_file.file_path）
DEFAULT_FILE_PATH = "/Users/andy/Downloads/NCCN-AML-2024 V3_13-22(1).pdf"
# 实际 PDF 路径（用于渲染页面图像）；留空则与 DEFAULT_FILE_PATH 相同
DEFAULT_PDF_PATH = ""
# 要解析的页码（1-based）
DEFAULT_PAGE = 1

# 步骤 3 单页 node/edge 结构化输出 schema（对齐业务：Node / EdgeRule / Condition）
NODES_EDGES_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "page_number": {
            "type": "INTEGER",
            "description": "页码，与输入一致",
        },
        "page_code": {
            "type": "STRING",
            "description": "页导航标识，与输入一致",
        },
        "nodes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {
                        "type": "STRING",
                        "description": "本页内唯一 id，与 Mermaid 中「作为步骤/状态」的节点 id 一致（如 A1,B1,C1,EndNode）；仅对「步骤/状态/动作」建 node，纯条件说明不建 node",
                    },
                    "title": {
                        "type": "STRING",
                        "description": "简短标题",
                    },
                    "content": {
                        "type": "STRING",
                        "description": "节点完整文案（该步骤/状态的内容）；若有脚注上标须以 <sup>g</sup>、<sup>m,n</sup> 等形式保留",
                    },
                    "node_type": {
                        "type": "STRING",
                        "description": "decision/evaluation/recommendation/action/information",
                    },
                    "is_entry": {"type": "BOOLEAN", "description": "是否为本页流程入口节点"},
                    "is_end": {"type": "BOOLEAN", "description": "是否为本页流程结束节点"},
                    "metadata": {
                        "type": "OBJECT",
                        "description": "可选扩展信息",
                    },
                    "care_phase_code": {
                        "type": "STRING",
                        "description": "节点所属阶段 code；应优先从输入提供的可用阶段中选择，无法判断可为空。",
                    },
                    "entry_conditions": {
                        "type": "ARRAY",
                        "description": "仅对入口节点（is_entry=true）填写：描述进入该入口节点适用条件；非入口节点可为空。",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "condition_text": {
                                    "type": "STRING",
                                    "description": "一个入口条件的基本单位：一条具体 if/when，不可再拆。",
                                },
                                "condition_type": {
                                    "type": "STRING",
                                    "description": "clinical/lab/demographic/time",
                                },
                                "symbol": {
                                    "type": "STRING",
                                    "description": "符号名，snake_case，如 low_ef、qtc_prolonged。",
                                },
                                "value_type": {
                                    "type": "STRING",
                                    "description": "取值类型：boolean / numeric / categorical",
                                },
                                "operator": {
                                    "type": "STRING",
                                    "description": "比较符：eq / ne / lt / le / gt / ge / in",
                                },
                                "threshold_value": {
                                    "type": "STRING",
                                    "description": "比较常量，如 true、70、high_risk。",
                                },
                            },
                            "required": [
                                "condition_text",
                                "condition_type",
                                "symbol",
                                "value_type",
                                "operator",
                                "threshold_value",
                            ],
                        },
                    },
                },
                "required": [
                    "id",
                    "title",
                    "content",
                    "node_type",
                    "is_entry",
                    "is_end",
                    "care_phase_code",
                    "entry_conditions",
                ],
            },
        },
        "edges": {
            "type": "ARRAY",
            "description": "边规则列表。每条 edge 有唯一 id 供脚注引用；由多个 condition 构成，一一对应",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {
                        "type": "STRING",
                        "description": "本页内唯一 id，供脚注等引用；须用 Edge 前缀（如 Edge1, Edge2）与 node id 区分，避免与 Mermaid 节点 E1/E2 等混淆；图中「条件/过渡块」对应的边必须赋 id",
                    },
                    "source_id": {"type": "STRING", "description": "源节点 id"},
                    "target_id": {
                        "type": "STRING",
                        "description": "目标节点 id；若指向下一页则用 __next:页code，如 __next:APL-5",
                    },
                    "rule_text": {
                        "type": "STRING",
                        "description": "必填。从 source 到 target 的跳转规则概括；具体条件拆到 conditions；若原文有脚注上标须以 <sup>m,n</sup> 等形式保留",
                    },
                    "relation_type": {
                        "type": "STRING",
                        "description": "decision/sequence/loop/reference",
                    },
                    "priority": {"type": "INTEGER", "description": "优先级，可选"},
                    "conditions": {
                        "type": "ARRAY",
                        "description": "本条 edge 对应的条件列表。Condition 是条件的基本单位；每条 condition 必填 symbol/value_type/operator/threshold_value，供规则求值使用。",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "condition_text": {
                                    "type": "STRING",
                                    "description": "一个条件的基本单位：一条具体的 if/when（不可再拆）；若原文有脚注上标须以 <sup>m,n</sup> 等形式保留",
                                },
                                "condition_type": {
                                    "type": "STRING",
                                    "description": "clinical/lab/demographic/time",
                                },
                                "symbol": {
                                    "type": "STRING",
                                    "description": "必填。符号名，snake_case，如 wbc_le_10、platelet_gt_100；用于规则求值时按 symbol 取值判断。本页内唯一即可；若与常见语义一致可复用通用命名（如 WBC≤10 用 wbc_le_10）便于跨页一致",
                                },
                                "value_type": {
                                    "type": "STRING",
                                    "description": "必填。取值类型：boolean / numeric / categorical",
                                },
                                "operator": {
                                    "type": "STRING",
                                    "description": "必填。比较符：eq / ne / lt / le / gt / ge / in",
                                },
                                "threshold_value": {
                                    "type": "STRING",
                                    "description": "必填。比较的常量，如 10、true、low_risk",
                                },
                            },
                            "required": ["condition_text", "condition_type", "symbol", "value_type", "operator", "threshold_value"],
                        },
                    },
                },
                "required": ["id", "source_id", "target_id", "rule_text", "relation_type"],
            },
        },
    },
    "required": ["page_number", "page_code", "nodes", "edges"],
}

# 步骤 3 footnote 页：按 ref 解析脚注列表，并标注每条对应的 node / edge / general / 文本段
FOOTNOTE_PAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "page_number": {"type": "INTEGER", "description": "页码"},
        "page_code": {"type": "STRING", "description": "本页导航标识（脚注页 code）"},
        "anchor_page_code": {
            "type": "STRING",
            "description": "被注解的流程图页的 page_code",
        },
        "footnotes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ref": {
                        "type": "STRING",
                        "description": "脚注引用标识，与流程图中的上标一致（字母或字母组合，如 b, g, m,n）",
                    },
                    "text": {
                        "type": "STRING",
                        "description": "该条脚注的完整正文",
                    },
                    "node_ids": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "当 target 为 node 时填：该脚注对应的节点 id 列表（如 A1, C1）",
                    },
                    "edge_ids": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "当 target 为 edge 时填：该脚注对应的边 id 列表（如 Edge1, Edge2）；上标若在过渡/条件块上则挂到 edge",
                    },
                    "target": {
                        "type": "STRING",
                        "description": "归属类型：node=属于图中某节点（填 node_ids）；edge=属于某条边/过渡条件（填 edge_ids）；general=整页或与图无关；text=属于某段正文，用 text_segment 描述",
                    },
                    "text_segment": {
                        "type": "STRING",
                        "description": "当 target 为 text 时可选：描述该脚注所属的正文段落（如页首标题、某小节）",
                    },
                },
                "required": ["ref", "text", "target"],
            },
        },
    },
    "required": ["page_number", "page_code", "anchor_page_code", "footnotes"],
}


# Phase 1 schema: LLM detects unique boundary substrings for each footnote; code extracts text.
FOOTNOTE_BOUNDARY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "footnotes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ref": {
                        "type": "STRING",
                        "description": "脚注引用标识，与正文上标一致（如 a, b, g, m）",
                    },
                    "start_substr": {
                        "type": "STRING",
                        "description": "该条脚注正文起始处的约 40 个原文字符（在整个 body_text 中唯一）",
                    },
                    "end_substr": {
                        "type": "STRING",
                        "description": "该条脚注正文结尾处的约 40 个原文字符（在整个 body_text 中唯一）",
                    },
                },
                "required": ["ref", "start_substr", "end_substr"],
            },
        }
    },
    "required": ["footnotes"],
}

# Phase 2 schema: LLM verifies extracted texts and matches refs to anchor node/edge IDs.
FOOTNOTE_MATCH_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "footnotes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ref": {"type": "STRING"},
                    "text_ok": {
                        "type": "BOOLEAN",
                        "description": "true 表示提供的 text 正确；false 时填 corrected_text",
                    },
                    "corrected_text": {
                        "type": "STRING",
                        "description": "仅当 text_ok=false 时填：完整的正确正文",
                    },
                    "node_ids": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "当 target 为 node 时填：对应节点 id 列表",
                    },
                    "edge_ids": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "当 target 为 edge 时填：对应边 id 列表",
                    },
                    "target": {
                        "type": "STRING",
                        "description": "node / edge / general / text",
                    },
                    "text_segment": {
                        "type": "STRING",
                        "description": "当 target 为 text 时描述所属段落",
                    },
                },
                "required": ["ref", "text_ok", "target"],
            },
        }
    },
    "required": ["footnotes"],
}


def _build_nodes_prompt(
    page_number: int,
    page_code: str,
    body_text: str,
    mermaid: str,
    care_phase_codes: list[str] | None = None,
) -> str:
    phase_codes = [str(c).strip() for c in (care_phase_codes or []) if str(c).strip()]
    phase_codes_hint = ", ".join(phase_codes) if phase_codes else "(无可用阶段，可留空)"
    return f"""你正在解析一份指南流程图页，产出将直接对应入库的三种实体：**Node（节点）**、**EdgeRule（边规则）**、**Condition（条件）**。其中：**Condition 是条件的基本单位**；**一条 EdgeRule 由多个 Condition 共同构成**；每条 edge 与属于它的 conditions 一一对应（output 里每条 edge 下带自己的 conditions 数组）。请按业务语义划分，不要简单地把 Mermaid 里「每个块」都当成一个 node。

**本页信息**
- 页码：{page_number}
- 页导航标识（page_code）：{page_code}

**本页正文（body_text）**
```
{body_text}
```

**本页 Mermaid 流程图**
```
{mermaid}
```

**可用诊疗阶段 code（用于给节点打标签）**
{phase_codes_hint}

**业务约定（请严格遵守）**

1. **nodes（节点）**  
   - 仅当图中某块表示「一个可识别的临床步骤/状态/动作」时才建 node（如：诱导治疗、巩固治疗、评估血象、进入下一页）。  
   - 每个 node 需 id（与 Mermaid 中该步骤块 id 一致）、title、content、node_type、is_entry、is_end。  
   - 每个 node 需输出 `care_phase_code`：必须从「可用诊疗阶段 code」中选择一个最匹配的；若确实无法判断则填空字符串。不要自造 code。
   - 每个 node 还需输出 `entry_conditions`（数组）：仅当 `is_entry=true` 且该入口有人群/条件限制时填写；否则填空数组。
   - `entry_conditions` 的每项字段与 edge condition 相同：condition_text、condition_type、symbol、value_type、operator、threshold_value。
   - **content 须与 Mermaid/正文一致，保留脚注上标**：若原文有上标（如 g, h, i, m, n），请以 `<sup>g</sup>`、`<sup>m,n</sup>` 等形式写在 content 中，便于后续脚注页匹配。  
   - 若某块**主要是**「从 A 到 B 的过渡条件/判断说明」（整段是 if…then…; if…then…），**不要**为该块建 node，而应把内容归到对应 edge 的 rule_text 与 conditions。
   - **【并列治疗选项拆分——重要】** 若某叶子节点（`is_end=true`）的内容中，以 "or"/"or a" 明确分隔两种或以上**平行独立治疗方案**（即患者可选其一，而非联合使用），**须将其拆分为多个独立兄弟节点**，每个节点仅含一种方案：为每个兄弟节点分配独立 id（如原 id 为 C1 则拆为 C1a、C1b）、独立 title 与 content，均设 `is_end=true`；同时从同一父节点（原指向 C1 的 edge 的 source）各建一条独立 edge 分别指向各兄弟节点，每条 edge 的 rule_text 注明该分支适用场景（如 "anthracycline option" / "gemtuzumab ozogamicin option"）。**联合用药**（如 "ATRA + ATO"，以 "+" 连接，需同时使用）和**顺序步骤**不拆分。

2. **edges（边规则）与 conditions（条件）的对应关系**
   - **每条 edge 必须带唯一 id**，供后续脚注解析引用；**须用 Edge 前缀**（如 Edge1, Edge2），与 node id（A1, B1, E1 等）区分，避免与 Mermaid 块命名重复影响判断。图中对应「条件/过渡块」的那条边必须赋此类 id。
   - **Condition 是条件的基本单位**；**一条 edge rule 由多个 condition 共同构成**。
   - 每条有向连接（包括「某节点 → 下一页」）对应**一条** edge。每条 edge 下带**仅属于该 edge** 的 conditions 数组；output 中 **edge 与 condition 一一对应**：某个 condition 只出现在它所归属的那条 edge 的 conditions 里，不要混在不同 edge 下。
   - **rule_text** 必填：用自然语言概括「在什么情况下从 source 走到 target」；**具体的一条条条件**必须拆成多个 condition，填在该 edge 的 **conditions** 数组中。
   - **每个 condition 必填**：condition_text（一条不可再拆的 if/when）、condition_type（clinical/lab/demographic/time）、**symbol**（snake_case，本页内唯一即可，如 wbc_le_10、platelet_gt_100；相同语义可复用通用命名便于跨页一致）、**value_type**（boolean/numeric/categorical）、**operator**（eq/ne/lt/le/gt/ge/in）、**threshold_value**（如 10、true、low_risk）。用于后续「用户输入 → symbol 取值」与规则求值。
   - **保留脚注上标**：若 Mermaid/正文中该边或条件块带有脚注上标（如 m,n、n,o,p、n），请在 rule_text 或 condition_text 中以 `<sup>m,n</sup>`、`<sup>n,o,p</sup>` 等形式原样保留，便于后续脚注页挂到 edge。
   - **relation_type**：decision/sequence/loop/reference。

3. **conditions 何时为空 vs 必填（核心规则——严格执行）**
   - **凡是同一父节点出度 ≥ 2 的分支边，每条分支边的 conditions 必填（不允许空数组）**。多分支本身即代表"按某条件选择走哪条"，每条分支都需要 condition 描述其触发条件。
   - 边的 condition 不限于显式 `if...then...` 句式。**箭头标签、条件标签、流程图中位于父节点与子节点之间的标注文本**（如"High risk (WBC > 10)"、"Stage IIIA"、"pMMR/MSS"、"≥6 mm"），都是条件，必须抽成 condition 项。
   - 节点 content 中的入口限定（如 "MSI-H/dMMR"、"BRCA carrier"）属于 entry_conditions，不是 edge condition；不要重复填。
   - 只有**唯一分支的顺序边 / 仅"Proceed to ..." / "See PAGE-CODE" 的纯导航边**才允许 conditions 为空数组；其他情况一律必须有 condition。
   - 对 `target_id="__next:PAGE_CODE"` 的跨页边：若图中能明确识别进入下一页的前置条件，应提取到该 edge 的 conditions；若图中无明确条件，允许 conditions 为空数组。
   - **自检**：完成后回顾 edges 列表，对每个 source_id 检查"同一 source 是否有多条 outgoing edges 且其中任意一条 conditions 为空"——若有，必须补全（从 Mermaid 标签 / 图中分支注释 / 节点 title 重新提取）。

**示例**  
- 图中一块写：「If blood count recovery by day 28 (platelet >100, ANC >1) proceed with consolidation; if full course not given or counts not recovered by day 28–35, BM aspirate and biopsy recommended」。该块在流程上连接「评估」→「巩固」：**不**建 node；为「评估→巩固」建**一条** edge，**id 填 Edge1**（或 Edge2…），rule_text 概括「根据血象恢复与疗程完成情况决定是否进入巩固或需 BM 检查」，**该 edge 的 conditions** 里每条 condition 必须包含 6 个字段，例如：① condition_text "Blood count recovery by day 28 (platelet >100×10⁹/L, ANC >1×10⁹/L)"、condition_type "lab"、**symbol "blood_recovery_day28"**、**value_type "boolean"**、**operator "eq"**、**threshold_value "true"**；② condition_text "Full course not given or counts not recovered by day 28–35"、condition_type "clinical"、**symbol "induction_incomplete_or_no_recovery"**、**value_type "boolean"**、**operator "eq"**、**threshold_value "true"**。  
- 图中一块写：「Consolidation: arsenic trioxide 0.15 mg/kg… + ATRA…」：建 **node**；从上一节点到该块的箭头建**一条** **edge**（赋 id 如 Edge2），该 edge 的 conditions 里每条都填 condition_text、condition_type、symbol、value_type、operator、threshold_value。

请严格按 JSON schema 输出，且 page_number、page_code 与上面一致；每条 condition 必须带 symbol、value_type、operator、threshold_value。"""


def _build_footnote_prompt(
    page_number: int,
    page_code: str,
    anchor_page_code: str,
    body_text: str,
    anchor_page: dict,
    footnote_image_provided: bool = False,
    anchor_image_provided: bool = False,
) -> str:
    """anchor_page 为步骤 3 单页解析结果（来自同一份 _nodes.json），含 keys: nodes, edges。"""
    nodes = anchor_page.get("nodes") or []
    edges = anchor_page.get("edges") or []
    steps_str = _format_anchor_nodes_for_prompt(nodes)
    rules_str = _format_anchor_edges_for_prompt(edges)

    if footnote_image_provided:
        image_hint = (
            "**第一张图是脚注页**，**第二张图是 anchor 页（流程图页）**；下方给出该页的「步骤/状态」与「边规则」列表，请结合图中的**上标**进行对应。"
            if anchor_image_provided
            else "**仅提供一张图：脚注页**。请根据下方 **anchor 页解析结果**（步骤/状态列表 + 边规则列表）及本页正文，匹配脚注 ref（上标字母）与 id。"
        )
    else:
        image_hint = "**纯文本解析**：不提供任何图片。请根据下方**本页正文（body_text）**与 **anchor 页解析结果**（步骤/状态列表 + 边规则列表），将每条脚注的 ref（上标字母）匹配到对应的 node_id 或 edge_id；anchor 中 content/rule_text/conditions 里含某上标即表示该 ref 属于该节点或该边。"
    return f"""你正在解析一份指南的「脚注页」。本页的脚注所属的 **anchor 页（被注解的流程图页）** 的解析结果已给到：{image_hint}

**本页（脚注页）信息**
- 页码：{page_number}
- 本页导航标识（page_code）：{page_code}
- 被注解的流程图页（anchor_page_code）：{anchor_page_code}

**本页正文（body_text）**
```
{body_text}
```

**Anchor 页解析结果 - 步骤/状态列表（id 即步骤块 id，如 A1、C1；供匹配上标）**
```
{steps_str}
```

**Anchor 页解析结果 - 边规则列表（id 为 Edge1、Edge2 等；上标若在过渡/条件块上则对应此处）**
```
{rules_str}
```

请根据「上述正文与步骤/边规则列表」完成：
1. 提取所有脚注条目（ref + text）。ref 与流程图中的**上标**一致（特别注意上标 g, h, i, j, k, l, m, n 等）。
2. 对每条脚注，判断其归属：
   - 若属于**某个或某些节点**（上标在步骤/状态块上）：target 填 "node"，**node_ids** 填对应的节点 id 列表（如 ["A1","C1"]），edge_ids 为空数组。
   - 若属于**某条或某几条边**（上标在过渡/条件块上，或解释「何时走这条边」）：target 填 "edge"，**edge_ids** 填对应的边 id 列表（如 ["Edge1","Edge2"]），node_ids 为空数组。
   - 若**不属于图**、为整页通用说明：target 填 "general"，node_ids 与 edge_ids 均为空数组。
   - 若属于**某段正文**（如页首标题、某小节）而非图中节点/边：target 填 "text"，**text_segment** 中简要描述所属段落。
3. 保持 **page_number**、**page_code**、**anchor_page_code** 与上面一致。

请严格按 JSON schema 输出。"""


def _format_anchor_nodes_for_prompt(nodes: list[dict]) -> str:
    """将 anchor 页的 nodes 格式化为 prompt 中的文本块（仅保留 id + title，不传 content 以最小化 token）。"""
    lines = []
    for n in nodes or []:
        nid = n.get("id", "")
        title = n.get("title") or ""
        lines.append(f"[id={nid}] {title}")
    return "\n".join(lines) if lines else "(无节点)"


def _format_anchor_edges_for_prompt(edges: list[dict]) -> str:
    """将 anchor 页的 edges 格式化为 prompt 中的文本块（仅保留 id + source→target + 条件该项 symbol，不传全文）。"""
    lines = []
    for e in edges or []:
        eid = e.get("id", "")
        src = e.get("source_id", "")
        tgt = e.get("target_id", "")
        conds = e.get("conditions") or []
        symbols = ", ".join(
            s for s in ((c.get("symbol") or "") for c in conds) if s
        )
        suffix = f" [{symbols}]" if symbols else ""
        lines.append(f"[id={eid}] {src} → {tgt}{suffix}")
    return "\n".join(lines) if lines else "(无边)"


def _build_footnote_boundary_prompt(page_number: int, page_code: str, body_text: str) -> str:
    """Phase 1 prompt: ask LLM to identify boundary substrings only — no text output, no anchor."""
    return f"""你正在处理一份指南脚注页正文。请识别正文中每条脚注的边界，仅输出起止子串供代码精确定位，**不要输出脚注全文**。

**页码**：{page_number}
**页标识**：{page_code}

**正文（body_text）**
```
{body_text}
```

**任务**：
对正文中每条脚注（ref 为上标字母，如 a, b, g, h, m, n 等）：
1. `ref`：该条脚注的引用标识（上标字母），与流程图上标一致。
2. `start_substr`：该条脚注正文**起始处**的约 40 个原文字符（必须在整个 body_text 中唯一出现一次）。
3. `end_substr`：该条脚注正文**结尾处**的约 40 个原文字符（必须在整个 body_text 中唯一出现一次）。

注意：
- start_substr 和 end_substr 必须是 body_text 中的**原文字符**，不得删改任何字符。
- 若某条脚注正文很短（< 40 字符），start_substr 与 end_substr 可设为相同的完整正文。
- 若 body_text 中有重复片段导致无法唯一定位，请适当延长子串（可到 60 字符）直到唯一。

请严格按 JSON schema 输出，不要输出脚注全文。"""


def _build_footnote_match_prompt(
    page_number: int,
    page_code: str,
    anchor_page_code: str,
    extracted_footnotes: list[dict],
    anchor_page: dict,
) -> str:
    """Phase 2 prompt: verify pre-extracted texts and match refs to anchor node/edge IDs."""
    nodes = anchor_page.get("nodes") or []
    edges = anchor_page.get("edges") or []
    steps_str = _format_anchor_nodes_for_prompt(nodes)
    rules_str = _format_anchor_edges_for_prompt(edges)
    footnotes_str = "\n".join(
        f"[ref={f['ref']}] {f['text']}" for f in extracted_footnotes
    )
    return f"""你正在处理一份指南脚注页的「核验与匹配」任务。已通过代码从正文中自动提取了各条脚注文本，请对每条脚注：
1. 确认提供的 text 是否正确（`text_ok`）；若有截断或错误，给出 `corrected_text`。
2. 将 ref（上标字母）匹配到 anchor 页的 node_id 或 edge_id。

**页码**：{page_number}
**本页标识（page_code）**：{page_code}
**Anchor 页标识（anchor_page_code）**：{anchor_page_code}

**已提取的脚注（ref + text）**
```
{footnotes_str}
```

**Anchor 页 - 步骤/状态列表（id 如 A1、C1）**
```
{steps_str}
```

**Anchor 页 - 边规则列表（id 如 Edge1、Edge2）**
```
{rules_str}
```

**匹配规则**：
- 若上标出现在某节点的 content 中 → target="node"，填 node_ids。
- 若上标出现在某边的 rule_text/conditions 中 → target="edge"，填 edge_ids。
- 若无明确归属 → target="general"。

请严格按 JSON schema 输出。"""


def _extract_footnotes_by_substrings(body_text: str, boundaries: list[dict]) -> list[dict]:
    """Code-side: locate each footnote's text in body_text using start/end substrings."""
    extracted = []
    for b in boundaries:
        ref = str(b.get("ref", "")).strip()
        start_substr = (b.get("start_substr") or "").strip()
        end_substr = (b.get("end_substr") or "").strip()
        if not ref or not start_substr:
            continue
        start_idx = body_text.find(start_substr)
        if start_idx == -1:
            print(f"  [boundary] ref={ref!r}: start_substr 未找到，跳过")
            continue
        if end_substr and end_substr != start_substr:
            end_idx = body_text.find(end_substr, start_idx)
            if end_idx == -1:
                end_idx = body_text.find(end_substr)
            if end_idx != -1:
                text = body_text[start_idx : end_idx + len(end_substr)]
            else:
                print(f"  [boundary] ref={ref!r}: end_substr 未找到，取 start 到末尾")
                text = body_text[start_idx:]
        else:
            # Very short footnote: start_substr == end_substr == full text
            text = start_substr
        text = text.strip()
        if text:
            extracted.append({"ref": ref, "text": text})
    return extracted


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


def _build_condition_expr_from_conditions(conditions: list[dict]) -> dict:
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


def _persist_flowchart_page_to_es(
    guideline_id: int,
    page_id: int,
    page_number: int,
    result: dict,
    phase_code_to_id: dict[str, int],
) -> None:
    """Clear then re-persist nodes/edges/conditions for a single flowchart page in ES."""
    guidance_db.delete_page_nodes_edges_conditions(guideline_id, page_id)

    nodes = result.get("nodes") or []
    edges = result.get("edges") or []

    node_id_to_db_id: dict[str, int] = {}
    entry_nodes: list[int] = []
    min_db_id: int | None = None

    for n in nodes:
        phase_code = (n.get("care_phase_code") or "").strip().lower()
        care_phase_id = phase_code_to_id.get(phase_code)
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
            entry_nodes.append(db_id)
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
            )
        if min_db_id is None or db_id < min_db_id:
            min_db_id = db_id

    if not entry_nodes and min_db_id is not None:
        entry_nodes = [min_db_id]

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
        # Cross-page edges (e.g. __next:APL-2) are not resolved here for single-page runs.

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
            )
            for c in conditions_list:
                guidance_db.create_guidance_condition(
                    condition_text=c.get("condition_text") or "",
                    condition_type=(c.get("condition_type") or "clinical").strip().lower() or "clinical",
                    guideline_id=guideline_id,
                    edge_rule_id=edge_rule_id,
                    symbol=c.get("symbol") or "",
                    value_type=c.get("value_type") or "",
                    operator=c.get("operator") or "",
                    threshold_value=c.get("threshold_value") or "",
                )

    print(f"  [ES] page_id={page_id}: {len(nodes)} nodes, {len(edges)} edges 已写入 ES")


def _persist_footnotes_to_es(
    guideline_id: int,
    anchor_page_id: int,
    footnotes: list[dict],
) -> None:
    """Append footnote texts to the content of their matched nodes/edges in ES."""
    if not footnotes:
        return
    doc = guidance_db._get_guideline_doc(guideline_id)
    if doc is None:
        return

    nodes_by_id = {str(n["id"]): n for n in doc.get("nodes", [])}
    edges_by_id = {f"Edge{e['id']}": e for e in doc.get("edge_rules", [])}

    changed = False
    for fn in footnotes:
        ref = fn.get("ref", "")
        text = (fn.get("text") or "").strip()
        if not text:
            continue
        suffix = f"\n\n[脚注{ref}] {text}"
        target = (fn.get("target") or "general").strip().lower()
        if target == "node":
            for nid in fn.get("node_ids") or []:
                node = nodes_by_id.get(str(nid))
                if node and node.get("page_id") == anchor_page_id:
                    node["content"] = (node.get("content") or "") + suffix
                    changed = True
        elif target == "edge":
            for eid in fn.get("edge_ids") or []:
                edge = edges_by_id.get(str(eid))
                if edge:
                    edge["rule_text"] = (edge.get("rule_text") or "") + suffix
                    changed = True

    if changed:
        guidance_db._save_guideline_doc(guideline_id, doc)
        print(f"  [ES] 脚注文本已合并写入 anchor page_id={anchor_page_id} 的节点/边")


async def main() -> None:
    file_path = DEFAULT_FILE_PATH
    pdf_path = Path(DEFAULT_PDF_PATH or file_path).resolve()
    page_key = str(DEFAULT_PAGE)

    # ── 从 ES 加载页面数据 ────────────────────────────────────────────────────
    loaded = guidance_db.load_file_and_pages_by_path(file_path)
    if loaded is None:
        raise ValueError(
            f"ES 中未找到 file_path={file_path!r}，请先运行 parse_guideline_file 入库。"
        )
    guideline_id, file_id, pages_by_num, code_to_page = loaded

    page_data = pages_by_num.get(page_key)
    if not page_data:
        raise ValueError(
            f"ES 中无页码 {page_key}，可用键: {sorted(pages_by_num.keys(), key=int)}"
        )

    page_number = page_data.get("page_number", DEFAULT_PAGE)
    page_code = page_data.get("page_code", "")
    page_type = page_data.get("page_type", "flowchart")
    anchor_page_code = page_data.get("anchor_page_code", "")
    body_text = page_data.get("body_text", "")
    mermaid = page_data.get("mermaid", "")

    care_phases = guidance_db.list_guidance_care_phases(guideline_id)
    care_phase_codes = [p["code"] for p in care_phases if p.get("enabled")]
    phase_code_to_id = {p["code"]: p["id"] for p in care_phases}

    if page_type == "footnote":
        if not anchor_page_code:
            raise ValueError(f"页 {page_number} 为 footnote 页但无 anchor_page_code，请检查 ES 数据。")
        anchor_page_id = code_to_page.get(anchor_page_code)
        if anchor_page_id is None:
            raise ValueError(f"anchor_page_code={anchor_page_code!r} 在 ES 中无对应页面。")

        # 从 ES 加载 anchor 页的 nodes/edges（使用 DB 整数 id 作为 VLM 标识）
        anchor_page = guidance_db.get_page_nodes_edges_for_anchor(guideline_id, anchor_page_id)
        if not anchor_page.get("nodes"):
            raise ValueError(
                f"anchor 页 {anchor_page_code}（page_id={anchor_page_id}）在 ES 中无节点，"
                "请先解析该 flowchart 页。"
            )

        print(
            f"正在解析页 {page_number}（{page_code}）脚注（纯文本：body_text + anchor 页 {anchor_page_code}，"
            f"{len(anchor_page['nodes'])} 个节点）…"
        )
        result = await extract_footnotes_with_vlm(
            page_number,
            page_code,
            anchor_page_code,
            body_text,
            anchor_page,
            footnote_image_bytes=None,
            anchor_image_bytes=None,
        )
        print(f"  得到 {len(result.get('footnotes', []))} 条脚注。")

        # 将脚注文本合并写入 ES 中 anchor 页的节点/边
        _persist_footnotes_to_es(guideline_id, anchor_page_id, result.get("footnotes") or [])

    elif not mermaid.strip() and not body_text.strip():
        result = _default_page_nodes_edges(page_number, page_code)
        print(f"页 {page_number} 无流程图/正文，跳过 VLM。")

    else:
        # ── flowchart 页 ────────────────────────────────────────────────────
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF 文件不存在: {pdf_path}")
        page_index = page_number - 1
        doc_tmp = pymupdf.open(str(pdf_path))
        total = len(doc_tmp)
        doc_tmp.close()
        if page_index < 0 or page_index >= total:
            raise ValueError(f"PDF 共 {total} 页，无法取第 {page_number} 页")

        image_bytes = await asyncio.get_event_loop().run_in_executor(
            None,
            pdf_page_to_jpeg_bytes,
            str(pdf_path),
            page_index,
            PAGE_DPI,
        )
        print(f"正在调用 VLM 解析页 {page_number}（{page_code}）的 node/edge…")
        result = await extract_nodes_edges_with_vlm(
            image_bytes, page_number, page_code, body_text, mermaid,
            care_phase_codes=care_phase_codes,
        )
        print(f"  得到 {len(result['nodes'])} 个节点、{len(result['edges'])} 条边。")

        # 写入 ES
        page_id = code_to_page.get(page_code)
        if page_id is not None:
            _persist_flowchart_page_to_es(guideline_id, page_id, page_number, result, phase_code_to_id)
        else:
            print(f"  [警告] page_code={page_code!r} 在 ES 中无对应 page_id，跳过写入。")

    # ── 同时保存为本地 JSON（供调试）────────────────────────────────────────
    out = {"pages": {page_key: result}}
    pdf_stem = Path(file_path).stem
    out_path = _SCRIPT_DIR / f"{pdf_stem}_nodes_p{page_key}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"已保存调试 JSON: {out_path}")


def _default_page_nodes_edges(page_number: int, page_code: str) -> dict:
    return {
        "page_number": page_number,
        "page_code": page_code,
        "nodes": [],
        "edges": [],
    }


def _default_footnote_result(
    page_number: int, page_code: str, anchor_page_code: str
) -> dict:
    return {
        "page_number": page_number,
        "page_code": page_code,
        "anchor_page_code": anchor_page_code,
        "nodes": [],
        "edges": [],
        "footnotes": [],
    }


def _normalize_footnotes(footnotes: list[dict]) -> list[dict]:
    """补全 footnotes 项：ref, text, node_ids, edge_ids, target, text_segment。"""
    out = []
    for f in footnotes or []:
        if not isinstance(f, dict):
            continue
        ref = str(f.get("ref", "")).strip()
        text = str(f.get("text", "")).strip()
        target = str(f.get("target", "general")).strip().lower()
        if target not in ("node", "edge", "general", "text"):
            target = "general"
        node_ids = f.get("node_ids")
        if not isinstance(node_ids, list):
            node_ids = []
        node_ids = [str(x).strip() for x in node_ids if str(x).strip()]
        edge_ids = f.get("edge_ids")
        if not isinstance(edge_ids, list):
            edge_ids = []
        edge_ids = [str(x).strip() for x in edge_ids if str(x).strip()]
        text_segment = str(f.get("text_segment", "")).strip()
        out.append({
            "ref": ref or "",
            "text": text,
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "target": target,
            "text_segment": text_segment or "",
        })
    return out


def _normalize_nodes(nodes: list[dict]) -> list[dict]:
    """补全 node 字段默认值。"""
    out = []
    for n in nodes or []:
        out.append({
            "id": str(n.get("id", "")).strip(),
            "title": str(n.get("title", "")),
            "content": str(n.get("content", "")),
            "node_type": str(n.get("node_type", "information")),
            "is_entry": bool(n.get("is_entry", False)),
            "is_end": bool(n.get("is_end", False)),
            "metadata": n.get("metadata") if isinstance(n.get("metadata"), dict) else {},
            "care_phase_code": str(n.get("care_phase_code", "")).strip().lower(),
            "entry_conditions": [
                {
                    "condition_text": str(c.get("condition_text", "")),
                    "condition_type": str(c.get("condition_type", "clinical")),
                    "symbol": str(c.get("symbol", "")).strip(),
                    "value_type": str(c.get("value_type", "")).strip(),
                    "operator": str(c.get("operator", "")).strip(),
                    "threshold_value": str(c.get("threshold_value", "")).strip(),
                }
                for c in (n.get("entry_conditions") or [])
                if isinstance(c, dict)
            ],
        })
    return out


def _normalize_edges(edges: list[dict]) -> list[dict]:
    """补全 edge 字段默认值（含 id，缺则用 source_id->target_id 生成）。"""
    out = []
    for i, e in enumerate(edges or []):
        eid = str(e.get("id", "")).strip()
        if not eid:
            eid = f"Edge{i+1}"
        conds = e.get("conditions") or []
        out.append({
            "id": eid,
            "source_id": str(e.get("source_id", "")).strip(),
            "target_id": str(e.get("target_id", "")).strip(),
            "rule_text": str(e.get("rule_text", "")),
            "relation_type": str(e.get("relation_type", "sequence")),
            "priority": int(e.get("priority", 0)) if e.get("priority") is not None else 0,
            "conditions": [
                {
                    "condition_text": str(c.get("condition_text", "")),
                    "condition_type": str(c.get("condition_type", "clinical")),
                    "symbol": str(c.get("symbol", "")).strip(),
                    "value_type": str(c.get("value_type", "")).strip(),
                    "operator": str(c.get("operator", "")).strip(),
                    "threshold_value": str(c.get("threshold_value", "")).strip(),
                }
                for c in conds
                if isinstance(c, dict)
            ],
        })
    return out


async def extract_nodes_edges_with_vlm(
    image_bytes: bytes,
    page_number: int,
    page_code: str,
    body_text: str,
    mermaid: str,
    care_phase_codes: list[str] | None = None,
) -> dict:
    """单页图片 + 已提取内容送 VLM，返回 { page_number, page_code, nodes, edges }。"""
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    llm = Gemini31Pro()
    prompt = _build_nodes_prompt(
        page_number,
        page_code,
        body_text,
        mermaid,
        care_phase_codes=care_phase_codes,
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            content = await llm(
                user_prompt=prompt,
                images=[img_b64],
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=NODES_EDGES_SCHEMA,
                # thinking_budget="low",
            )
            text = (content or "").strip()
            if not text:
                return _default_page_nodes_edges(page_number, page_code)
            data = json.loads(text)
            return {
                "page_number": int(data.get("page_number", page_number)),
                "page_code": str(data.get("page_code", page_code)),
                "nodes": _normalize_nodes(data.get("nodes")),
                "edges": _normalize_edges(data.get("edges")),
            }
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(f"Page {page_number} VLM 返回非 JSON: {e}") from e
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(f"Page {page_number} VLM 调用失败: {e}") from e
    return _default_page_nodes_edges(page_number, page_code)


async def _extract_footnotes_legacy(
    page_number: int,
    page_code: str,
    anchor_page_code: str,
    body_text: str,
    anchor_page: dict,
    footnote_image_bytes: bytes | None = None,
    anchor_image_bytes: bytes | None = None,
) -> dict:
    """Legacy single-call approach (kept as fallback): sends full body_text + anchor in one call."""
    images: list[str] = []
    if footnote_image_bytes is not None:
        images.append(base64.b64encode(footnote_image_bytes).decode("utf-8"))
    if anchor_image_bytes is not None:
        images.append(base64.b64encode(anchor_image_bytes).decode("utf-8"))
    llm = Gemini31Pro()
    prompt = _build_footnote_prompt(
        page_number,
        page_code,
        anchor_page_code,
        body_text,
        anchor_page,
        footnote_image_provided=(footnote_image_bytes is not None),
        anchor_image_provided=(anchor_image_bytes is not None),
    )

    FOOTNOTE_VLM_TIMEOUT = 300
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt == 0:
                hint = "纯文本解析，请稍候" if not images else "含图，可能 1–3 分钟"
                print(f"  [legacy] 调用中（{hint}）…")
            content = await asyncio.wait_for(
                llm(
                    user_prompt=prompt,
                    images=images,
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=FOOTNOTE_PAGE_SCHEMA,
                    # thinking_budget="low",
                ),
                timeout=FOOTNOTE_VLM_TIMEOUT,
            )
            text = (content or "").strip()
            if not text:
                return _default_footnote_result(page_number, page_code, anchor_page_code)
            data = json.loads(text)
            return {
                "page_number": int(data.get("page_number", page_number)),
                "page_code": str(data.get("page_code", page_code)),
                "anchor_page_code": str(data.get("anchor_page_code", anchor_page_code)),
                "nodes": [],
                "edges": [],
                "footnotes": _normalize_footnotes(data.get("footnotes")),
            }
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(f"Page {page_number} footnote VLM 返回非 JSON: {e}") from e
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                print(f"  [legacy] 超时（{FOOTNOTE_VLM_TIMEOUT}s），重试 {attempt + 1}/{max_retries}…")
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(
                    f"Page {page_number} footnote VLM 超时（{FOOTNOTE_VLM_TIMEOUT}s）"
                ) from None
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(f"Page {page_number} footnote VLM 调用失败: {e}") from e
    return _default_footnote_result(page_number, page_code, anchor_page_code)


async def extract_footnotes_with_vlm(
    page_number: int,
    page_code: str,
    anchor_page_code: str,
    body_text: str,
    anchor_page: dict,
    footnote_image_bytes: bytes | None = None,
    anchor_image_bytes: bytes | None = None,
) -> dict:
    """2-phase footnote extraction to reduce LLM output size and latency.

    Phase 1 — boundary detection (body_text only, tiny output):
        LLM identifies unique start/end substrings (~40 chars each) per footnote ref.
        Code uses str.find() to extract the actual text — no large text output from LLM.

    Phase 2 — verify + match (extracted texts + anchor, focused output):
        LLM verifies each extracted text is correct (corrects if needed) and maps
        each ref to its anchor node_ids / edge_ids.  No footnote text in the output.

    Falls back to legacy single-call approach on any unrecoverable phase-1 failure,
    or when footnote_image_bytes is provided (image-based path unchanged).
    """
    # Image path: fall back to legacy (images not used in new flow)
    if footnote_image_bytes is not None or anchor_image_bytes is not None:
        return await _extract_footnotes_legacy(
            page_number, page_code, anchor_page_code,
            body_text, anchor_page,
            footnote_image_bytes, anchor_image_bytes,
        )

    if not body_text.strip():
        return _default_footnote_result(page_number, page_code, anchor_page_code)

    llm = Gemini31Pro()
    _max_retries = 2

    # ── Phase 1: boundary detection ──────────────────────────────────────────
    BOUNDARY_TIMEOUT = 120
    boundary_prompt = _build_footnote_boundary_prompt(page_number, page_code, body_text)
    boundaries: list[dict] = []
    phase1_ok = False
    for attempt in range(_max_retries):
        try:
            if attempt == 0:
                print(f"  [footnote p1] 边界检测中（仅 body_text，输出极小）…")
            raw = await asyncio.wait_for(
                llm(
                    user_prompt=boundary_prompt,
                    images=[],
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=FOOTNOTE_BOUNDARY_SCHEMA,
                    # thinking_budget="low",
                ),
                timeout=BOUNDARY_TIMEOUT,
            )
            data = json.loads((raw or "").strip() or "{}")
            boundaries = data.get("footnotes") or []
            phase1_ok = True
            break
        except asyncio.TimeoutError:
            if attempt < _max_retries - 1:
                print(f"  [footnote p1] 超时（{BOUNDARY_TIMEOUT}s），重试 {attempt + 1}…")
                await asyncio.sleep(2 ** attempt)
            else:
                print(f"  [footnote p1] 超时，回退至 legacy 方法")
        except (json.JSONDecodeError, Exception) as e:
            if attempt < _max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                print(f"  [footnote p1] 失败 ({e})，回退至 legacy 方法")

    if not phase1_ok or not boundaries:
        return await _extract_footnotes_legacy(
            page_number, page_code, anchor_page_code, body_text, anchor_page,
        )

    # ── Code extraction ───────────────────────────────────────────────────────
    extracted = _extract_footnotes_by_substrings(body_text, boundaries)
    print(f"  [footnote p1] 代码提取 {len(extracted)}/{len(boundaries)} 条脚注")

    if not extracted:
        return await _extract_footnotes_legacy(
            page_number, page_code, anchor_page_code, body_text, anchor_page,
        )

    # ── Phase 2: verify + match ───────────────────────────────────────────────
    MATCH_TIMEOUT = 500
    match_prompt = _build_footnote_match_prompt(
        page_number, page_code, anchor_page_code, extracted, anchor_page,
    )
    matched: list[dict] = []
    for attempt in range(_max_retries):
        try:
            if attempt == 0:
                print(f"  [footnote p2] 核验与匹配（{len(extracted)} 条）…")
            raw = await asyncio.wait_for(
                llm(
                    user_prompt=match_prompt,
                    images=[],
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_schema=FOOTNOTE_MATCH_SCHEMA,
                    # thinking_budget="low",
                ),
                timeout=MATCH_TIMEOUT,
            )
            data = json.loads((raw or "").strip() or "{}")
            matched = data.get("footnotes") or []
            break
        except asyncio.TimeoutError:
            if attempt < _max_retries - 1:
                print(f"  [footnote p2] 超时（{MATCH_TIMEOUT}s），重试 {attempt + 1}…")
                await asyncio.sleep(2 ** attempt)
            else:
                print(f"  [footnote p2] 超时，使用已提取文本，归类为 general")
                matched = [{"ref": f["ref"], "text_ok": True, "target": "general"} for f in extracted]
        except (json.JSONDecodeError, Exception) as e:
            if attempt < _max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                print(f"  [footnote p2] 失败 ({e})，使用已提取文本，归类为 general")
                matched = [{"ref": f["ref"], "text_ok": True, "target": "general"} for f in extracted]

    # ── Combine extracted texts with match results ────────────────────────────
    text_by_ref: dict[str, str] = {f["ref"]: f["text"] for f in extracted}
    footnotes: list[dict] = []
    for m in matched:
        ref = str(m.get("ref", "")).strip()
        if not ref:
            continue
        text_ok = bool(m.get("text_ok", True))
        corrected = (m.get("corrected_text") or "").strip()
        text = corrected if (not text_ok and corrected) else text_by_ref.get(ref, "")
        target = str(m.get("target", "general")).strip().lower()
        if target not in ("node", "edge", "general", "text"):
            target = "general"
        node_ids = [str(x).strip() for x in (m.get("node_ids") or []) if str(x).strip()]
        edge_ids = [str(x).strip() for x in (m.get("edge_ids") or []) if str(x).strip()]
        footnotes.append({
            "ref": ref,
            "text": text,
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "target": target,
            "text_segment": str(m.get("text_segment", "")).strip(),
        })

    # Include any extracted refs that had no match entry (safety net)
    matched_refs = {f["ref"] for f in footnotes}
    for f in extracted:
        if f["ref"] not in matched_refs:
            footnotes.append({
                "ref": f["ref"],
                "text": f["text"],
                "node_ids": [],
                "edge_ids": [],
                "target": "general",
                "text_segment": "",
            })

    print(f"  [footnote] 完成：{len(footnotes)} 条脚注（2-phase）")
    return {
        "page_number": page_number,
        "page_code": page_code,
        "anchor_page_code": anchor_page_code,
        "nodes": [],
        "edges": [],
        "footnotes": footnotes,
    }


if __name__ == "__main__":
    asyncio.run(main())
