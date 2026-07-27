---
name: plm-clarify
description: >
  PLM 流程第③步。用户从 TOP-5 里选定一份指南后,按该指南的 doc_id 生成澄清内容
  (已掌握哪些信息、还需补充什么),供用户确认或补充。必须在用户明确选定指南之后调用。
---

# PLM 澄清 (按用户选定的指南)

**Endpoint:** `POST http://plm-engine:8002/plm_evidence_based/clarify_sync` (非流式, 直接返回 JSON)

## 输入
```json
{
  "patient_input": "<与第①步相同的患者病情描述>",
  "doc_id": "<本轮用户选定指南的 doc_id>",
  "guideline_priority_order": ["<用户选的指南范围机构>"],
  "product_scope": "yiyong"
}
```

## 调用
```bash
curl -s --max-time 180 -X POST http://plm-engine:8002/plm_evidence_based/clarify_sync \
  -H 'Content-Type: application/json' \
  -d '{"patient_input": "<患者病情>", "doc_id": <用户选的 doc_id>, "product_scope": "yiyong"}'
```

## 输出 (JSON, 约 60 秒返回)
```json
{
  "status": "ok",
  "no_graph": false,
  "clarify_markdown": "## 已掌握信息\n...\n## 仍需澄清\n1. ...\n2. ...",
  "clarify_session_id": "clarify_xxxx",
  "patient_info": { ... }
}
```

## 用完怎么做(务必照做)
1. **直接把返回的 `clarify_markdown` 原样贴给用户**(它就是"已掌握信息 / 仍需澄清"两段),请用户**确认或补充**。开头最多加一句自然引导语(如"已为您整理如下,请确认或补充:")。
2. ⛔ **绝不向用户复述任何技术字段 / 内部状态** —— 不要出现 `no_graph`、`status`、`clarify_session_id`、"JSON"、"接口返回"、字段名等字样。用户只应看到澄清正文本身。
3. 记住 `clarify_session_id`,第④步 plm-run-report 要用(**不要显示给用户**)。
4. ⛔ **不要**把结果存成文件、不要用 python 解析——返回本身就是干净 JSON,直接取 `clarify_markdown` 字段贴出来即可。
5. 若该指南**无决策图谱**(返回里 no_graph 为真):用**平实的话**告诉用户"该指南暂无决策图谱,无法生成完整报告,请改选其它指南",**不要**出现 "no_graph" 之类字样,也不要继续。
6. 🚧 用户没确认之前,不要调 plm-run-report。

## 何时用
- **仅在用户从 TOP-5 明确选定一份指南之后**。必须传该指南的 `doc_id`(不传会退回自动选,违背"用户选择")。
- `doc_id` 必须取自本轮候选卡的服务端候选列表或可信选择上下文，绝不能复用示例、历史轮次或其他患者的 doc_id。
