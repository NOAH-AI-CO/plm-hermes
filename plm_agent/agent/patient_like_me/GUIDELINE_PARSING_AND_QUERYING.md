# 指南解析与查询——设计文档

## 概述

本系统将临床指南 PDF（如 NCCN）解析并转化为结构化、可查询的知识图谱，存储于 Elasticsearch 中。给定患者自由文本描述后，系统遍历该图谱并调用 LLM，为患者匹配最合适的临床路径与推荐方案。

整体流程分为两个阶段：**解析**（离线，每份指南执行一次）和**查询**（在线，每次患者问询时执行）。

---

## 第一部分：解析流水线

解析分为四个顺序阶段，每阶段的输出作为下一阶段的输入。

```
PDF
 │
 ▼ 阶段 1a：parse_pages.py
 │  → 逐页 VLM 提取（body_text、mermaid、page_code、page_type 等）
 │  → 输出 _pages.json（本地调试文件）
 │
 ▼ 阶段 1b：parse_guideline_file.py
 │  → 将 Guideline / GuidanceFile / GuidancePage / GuidancePageLink /
 │    GuidancePageGlobalRule 写入 Elasticsearch
 │
 ▼ 阶段 2a：parse_care_phase.py  +  parse_care_phase_to_db.py
 │  → LLM 读取所有流程图页，提取有序诊疗阶段词表
 │    （如诱导、巩固、维持、监测）
 │  → 写入 GuidanceCarePhase
 │
 ▼ 阶段 2b：parse_nodes.py  +  parse_nodes_to_db.py
    → 对每个流程图页：VLM 提取节点 + 边 + 条件
    → 对每个脚注页：两阶段 LLM 提取，将脚注文本合并到对应 anchor
      节点 / 边的 content 字段
    → 写入 GuidanceNode / GuidanceEdgeRule / GuidanceCondition /
      GuidanceNodeEntryCondition
```

### 阶段 1a — 逐页提取（`parse_pages.py`）

每页 PDF 被渲染为高清 JPEG（300 DPI），连同 PyMuPDF 提取的原始文字（保留上标脚注标记）一起发送给 Gemini 1.5 Pro。每页一次 VLM 调用，返回如下结构化 JSON：

| 字段 | 含义 |
|---|---|
| `body_text` | 页面正文，脚注上标以 `<sup>g</sup>` 形式保留 |
| `mermaid` | 流程图转写为 Mermaid 字符串 |
| `page_code` | 页面导航标识（如 `APL-3`，或纯数字页码） |
| `page_type` | `flowchart` / `footnote` / `content` / `citations` / `toc` / `intro` |
| `anchor_page_code` | 脚注页专用：被注解的流程图页标识 |
| `is_entry` | 是否为指南流程的根入口页 |
| `next_page_codes` | 本页流程可跳转的下一页页码列表 |
| `global_rule_body` | 本页包含的全局规则（适用于所有患者） |
| `flowchart_footnotes` | 与流程图在同一页面的内联脚注区域 |

最多 3 页并发处理（信号量控制），结果写入本地 `_pages.json` 供调试。

### 阶段 1b — 页面入库（`parse_guideline_file.py`）

`_pages.json` 输出（或其内存等价物）以每份指南一个文档的形式写入 Elasticsearch（索引名 `guidance_guidelines`）。文档将所有子实体以嵌套数组形式存储：

- **Guideline** — 名称、机构、版本、年份。
- **GuidanceFile** — 源 PDF 路径及解析状态。
- **GuidancePage** — 每页一条记录，存储 `page_number`、`code`、`page_type`、`raw_text`、`layout_json`（body_text + mermaid）、`flowchart_footnotes`，以及脚注页对应的 `anchor_page_id`。
- **GuidancePageLink** — 页面间有向边（source → target），由 `next_page_codes` 推导。
- **GuidancePageGlobalRule** — 每个含 `global_rule_body` 的页面对应一条记录。

### 阶段 2a — 诊疗阶段提取（`parse_care_phase.py` + `parse_care_phase_to_db.py`）

将所有流程图页的 `body_text` 和 `mermaid` 拼接后，通过单次 LLM 调用提取有序诊疗阶段列表，每个阶段包含：

- `code` — snake_case 机器可读标识（如 `induction`、`consolidation_low_risk`）。
- `display_name_zh` / `display_name_en` — 中英文展示名。
- `sort_order` — 在治疗序列中的位置。
- `description` 和 `aliases`（别名）。

结果以 **GuidanceCarePhase** 形式写入指南文档，并在阶段 2b 中用于为每个解析出的节点打上所属临床阶段标签。

### 阶段 2b — 节点 / 边 / 条件提取（`parse_nodes.py` + `parse_nodes_to_db.py`）

本阶段处理阶段 1b 入库的所有页面。

#### 流程图页

每页的 JPEG、`body_text`、`mermaid` 发送给 Gemini 1.5 Pro，提示词要求 LLM 产出：

**节点（Node）** 代表临床步骤、状态或动作：
- `id` — 与 Mermaid 块 id 一致。
- `title`、`content`（保留脚注上标）。
- `node_type`：`decision` / `evaluation` / `recommendation` / `action` / `information`。
- `is_entry` / `is_end`。
- `care_phase_code` — 从阶段 2a 的词表中选取。
- `entry_conditions` — 仅入口节点填写，描述哪类患者可进入该节点（结构与边条件相同）。

**边（Edge）** 代表节点间的跳转：
- `id` — 以 `Edge` 为前缀（如 `Edge1`），避免与节点 id 冲突。
- `source_id`、`target_id`。
- `rule_text` — 跳转条件的自然语言概括。
- `relation_type`：`decision` / `sequence` / `loop` / `reference`。
- `conditions` — 原子条件列表，每条包含：`condition_text`、`condition_type`、`symbol`（snake_case，如 `wbc_le_10`）、`value_type`（boolean/numeric/categorical）、`operator`（eq/ne/lt/le/gt/ge/in）、`threshold_value`。

提示词强制的建模规则：
- Mermaid 中的过渡 / 条件块**不建节点**，其内容归入对应边的 conditions。
- 以 "or" 分隔的并列治疗方案拆分为兄弟叶子节点，各有独立边指向父节点。
- 跨页引用使用 `target_id = "__next:PAGE_CODE"`。

每页结果先清除再写入 ES（`delete_page_nodes_edges_conditions` 后重新插入），使本阶段具有幂等性。

#### 脚注页 — 两阶段提取

脚注页在**所有流程图页处理完毕后**执行，此时 anchor 页的节点 / 边已入库。

**阶段一 — 边界定位（LLM，输出极小）**  
LLM 仅接收 `body_text`，对每条脚注 ref（如 `g`、`m,n`）返回一对约 40 字符的唯一边界子串（`start_substr`、`end_substr`）。代码用 `str.find()` 精确提取脚注正文——LLM 响应中不含大段文本。

**阶段二 — 核验 + 匹配（LLM）**  
LLM 接收已提取的文本及 anchor 页的节点 / 边列表（id + title / id + symbol，裁剪以节省 token），确认每条提取文本是否正确（若有误则给出更正），并将每个 ref 映射到对应的 `node_ids` 或 `edge_ids`。

脚注文本随后追加到 ES 中对应节点 / 边的 `content` / `rule_text` 字段，确保下游查询时可见完整注释内容。

若阶段一失败，系统回退到传统单次调用方案。

#### 内容页（Content pages）

`page_type = "content"` 的页面（如支持治疗页）以整页 `body_text` 存为单个 `information` 节点，无需 VLM 调用；诊疗阶段通过关键词匹配阶段词表推断。

---

## 第二部分：Elasticsearch 数据模型

每份指南的所有数据存储在 `guidance_guidelines` 索引的**单个 ES 文档**中（文档 `_id` 为指南 id 的字符串形式）。子实体以嵌套数组形式直接存放在文档上，结构上等价于关系型数据库中的多张表。

```
guidance_guidelines 文档
├── id, name, organization, version, year, description
├── files[]              — GuidanceFile
├── pages[]              — GuidancePage（body_text、mermaid、raw_text、layout_json 等）
├── page_links[]         — GuidancePageLink（source_page_id → target_page_id）
├── page_global_rules[]  — 每页全局规则文本
├── care_phases[]        — GuidanceCarePhase（code、display_name_zh/en、sort_order 等）
├── nodes[]              — GuidanceNode（id、page_id、title、content、node_type、is_entry、is_end、care_phase_id）
├── edge_rules[]         — GuidanceEdgeRule（id、source_node_id、target_node_id、rule_text、relation_type、condition_expr）
├── conditions[]         — GuidanceCondition（edge_rule_id、symbol、condition_text、value_type、operator、threshold_value）
└── node_entry_conditions[]  — GuidanceNodeEntryCondition（node_id、symbol 等）
```

脚注文本已在解析时合并到节点的 `content` 和边的 `rule_text` / `conditions` 中，查询时无需单独的脚注表。

---

## 第三部分：查询逻辑（`search_guideline_phase.py`）

给定患者自由文本（`patient_text`）和已入库指南的 `file_path`，`run_search_phase` 按以下流水线执行：

### 步骤 1 — 阶段分诊（LLM）

LLM（`_ask_phase`）接收患者文本和该指南的完整 `GuidanceCarePhase` 列表，返回：

- `primary_phase_code` — 该患者最可能所处的治疗阶段。
- `secondary_phase_code` — 备选阶段。
- `additional_phase_codes` — 其他相关阶段（用于综合多阶段问题）。
- `confidence` 和 `missing_dimensions` — 置信度低时，系统向调用方暴露缺失信息。

特殊情形：若 `primary_phase_code = "out_of_scope"`，表示患者不属于本指南适用范围。系统调用专属 LLM（`_ask_out_of_scope_analysis`）评估排除诊断前的初始治疗操作是否正确，并生成推测性说明。

### 步骤 2 — 图加载与反向路径遍历

通过 `_load_file_graph` 从 ES 加载文件的完整节点 / 边图，`_build_reverse_graph` 构建：

- `node_by_id` — 每个节点的元数据。
- `out_adj` / `rev_adj` — 正向和反向邻接表。
- `root_nodes` — 入口页的入口节点集合。
- 跨页边：当终端节点没有任何出边时，从 `page_links` 补充启发式跨页边，将源页终端节点连接到目标页的入口节点。

**目标节点选取**：`care_phase_id` 与所选阶段 id 匹配的节点构成目标集合，并进一步扩展到目标阶段页面直接链接的页面上的节点（捕获没有显式阶段标签的支持治疗页）。

**路径枚举**：对每个目标节点，`_reverse_paths_to_root` 沿 `rev_adj` 反向 DFS，找到最多 `MAX_PATHS_PER_TARGET`（默认 3）条从目标到根的路径，深度上限为 `MAX_PATH_DEPTH`（默认 14）。

**紧凑表示**：为减少 LLM prompt token，`node_registry` 去重后每个节点的元数据只存一次；每条路径仅存节点 id 序列和边标签；目标节点额外携带 `content`（截断至 600 字符）和 `entry_conditions`。

### 步骤 3 — 脚注与全局规则收集

调用 LLM 前，预先组装两个上下文块：

**全局规则**：`guidance_db.merged_guideline_global_rules_text` 将所有 `GuidancePageGlobalRule` 拼接为单一文本块，LLM 必须优先通读。

**页面脚注**：系统收集以下页面的脚注文本：
1. 所有候选页（含目标节点的页面）。
2. 兄弟页（与候选页共享同一父节点的页面）。
3. 祖先页（父页、祖父页直至根页，最多向上 6 层）。

这确保跨分支脚注（如"各治疗组件须保持方案一致"）在其位于根级脚注页而非叶子候选页时，仍能被 LLM 看到。

### 步骤 4 — 路径选择（LLM）

`_ask_path_select` 调用 Gemini 1.5 Pro，输入：
- 患者文本。
- 完整 `node_registry` + 紧凑 `paths` 列表。
- `condition_hints` — 指南所有条件的 `symbol` / `value_type` / `operator` / `threshold_value` 去重列表，供结构化维度提取参考。
- 全局规则文本块。
- 组装好的页面脚注。

提示词强制执行严格的决策协议，包括：
- **多重禁忌交集分析**：患者同时存在多个禁忌时，合并所有禁用药物 / 操作集合，逐一扫描每个候选节点（包括各 "or" 分支），凡有任一分支无禁忌项即视为有效候选。
- **剂量折减 vs 指南空白**：宣告 `guideline_gap` 前，须先检查注脚是否允许减量而保持在同一路径内。
- **评估性问句**：问题含"是否正确"时，LLM 须客观逐项核查，不得捏造偏差。
- **年龄 / 肾功能剂量变体**：含年龄或肾功能分层剂量的节点，须将每个阈值与患者实际值明确比较。

LLM 返回三种 `decision_type` 之一：
- `match` — 存在满足患者条件的一个或多个 `matched_node_ids`。
- `insufficient` — 信息不足；`missing_dimensions` 一次列出所有需要补充的维度。
- `guideline_gap` — 穷举分析后所有候选节点均无可用选项。

### 步骤 5 — 后链路分析（LLM）

决策为 `match` 时，第二次 LLM 调用（`_ask_post_chain_analysis`）在更宽泛的上下文中执行一轮复核：

**后续页面子图**：`_build_post_page_subgraph` 从匹配节点所在页面出发，通过 `page_links` 和跨节点边做正向 BFS，生成所有可达页面的 Mermaid 图及元数据（页面代码、节点标题摘要）。

**兄弟上下文节点**：与匹配节点位于同一页面但未被选中的入口节点单独列出，用于识别医生方案中数值来自并列（但不同）方案的混淆陷阱。

后链路提示词要求 LLM：
1. 先通读全局规则，再复核分析。
2. 不改变 `decision_type` 和 `matched_node_ids`，仅补充和精化分析内容。
3. 反幻觉规则：所有"指南规定 X"的陈述须在节点 `content`、全局规则或脚注中有字面依据，否则注明"节点未覆盖，无法评估"。
4. 保留第一轮中正确的临床安全原则（如有创操作禁忌），即使当前子图节点正文未明确写出——保留并标注"基于通用临床实践，非本指南节点原文"。

### 步骤 6 — 补充轮次

整个流水线可迭代执行。决策为 `insufficient` 时，调用方收集 `missing_dimensions`，向用户追问后以补充信息再次调用 `run_search_phase`，最多允许 `MAX_SUPPLEMENT_ROUNDS`（默认 1）轮。

补充轮次结束后，可对任意"潜在匹配节点"调用 `run_post_analysis_for_potential_nodes`，即使初始轮返回 `insufficient` 也能执行完整后链路分析。

### 输出结构

```python
{
    "guideline_id": int,
    "file_id": int,
    "phase_decision": { "primary_phase_code": ..., "confidence": ..., ... },
    "phase_codes": ["induction", ...],
    "decision_type": "match" | "insufficient" | "guideline_gap",
    "analysis": str,                    # 第一轮 LLM 分析
    "speculative_note": str,
    "missing_dimensions": [...],
    "matched_nodes": [                  # 步骤 4 选中的节点
        { "node_id": int, "title": str, "content": str, "page_id": int, ... }
    ],
    "matched_node_full_chains": [       # 后续页面子图（步骤 5）
        { "page_id": int, "page_number": int, "code": str, ... }
    ],
    "post_chain_analysis": str,         # 第二轮 LLM 分析
    "post_chain_speculative_note": str,
    "candidate_path_count": int,
}
```

---

## 各文件职责速查

| 文件 | 职责 |
|---|---|
| `parse_pages.py` | 阶段 1a — 逐页 VLM 提取，输出 JSON |
| `parse_guideline_file.py` | 阶段 1b — 页面及全局规则写入 ES |
| `parse_care_phase.py` | 阶段 2a（提取）— LLM 从页面提取诊疗阶段词表 |
| `parse_care_phase_to_db.py` | 阶段 2a（入库）— 诊疗阶段写入 ES |
| `parse_nodes.py` | 阶段 2b（提取）— VLM 节点 / 边 / 脚注提取逻辑 |
| `parse_nodes_to_db.py` | 阶段 2b（入库）— 编排所有页面处理，节点 / 边写入 ES |
| `guidance_db.py` | 所有 ES CRUD；指南单文档数据模型 |
| `search_guideline_phase.py` | 查询侧：阶段分诊 → 图遍历 → LLM 路径选择 → 后链路分析 |
