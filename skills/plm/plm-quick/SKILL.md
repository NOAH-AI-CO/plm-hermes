---
name: plm-quick
description: >
  PLM 快速循证问答:针对某个具体临床问题给出简明循证回答(不生成完整五分区报告)。
  两种场景用它:①用户选了"快速模式"、只想快速解答某个具体问题;②完整报告已出后,
  用户就报告/病情继续追问(如"这个方案老年人怎么调""能不能换二线""对比另一个指南")。
---

# PLM 快速问答 / 报告后追问

**Endpoint:** `POST http://plm-engine:8002/plm_evidence_based`(`entry_mode:"quick"`, **非 compact, 阻塞返回答案**)

## 调用(约 1-2 分钟返回)
```bash
curl -s --max-time 200 -X POST http://plm-engine:8002/plm_evidence_based \
  -H 'Content-Type: application/json' \
  -d '{"patient_input":"<患者病情 + 本次具体问题, 一段文字>","selected_doc_id":<已选指南 doc_id, 有就带>,"guideline_priority_order":["<机构,如 NCCN>"],"product_scope":"yiyong","mode":"complex","entry_mode":"quick","stream":false}'
```
- `patient_input`:把**患者病情**和**用户这次的具体问题**合成一段(如"62岁女性DLBCL III期…问:该一线方案对65岁以上老人如何调整?")。
- `selected_doc_id`:**本对话若已选定/已出报告用的那份指南 doc_id,一定带上**,让追问严格基于同一份指南。快速模式首次问答时用用户从 TOP-5 选定的 doc_id。
- `guideline_priority_order`:该指南机构。

## 返回
```json
{ "output": "<循证回答的 markdown 正文>", "route": "full_case", "mode": "case_question_qa", ... }
```

## 用完怎么做
1. 把返回的 **`output` 原样作为普通聊天消息**呈现给用户(它是 markdown 正文,直接贴出来即可)。
2. ⛔ **不要**输出 ```plm-report 代码块(那是完整报告用的,会被前端渲成分栏)。快速问答就是普通 markdown 回答。
3. ⛔ 不要存文件、不要 python 解析——直接取 `output` 字段贴出。
4. 若 `output` 为空或返回 clarification_required:说明信息不足,简短向用户追问关键信息后再调。

## 何时用
- 用户选**快速模式**、只问一个具体问题 → 选定指南后直接用本 skill(不走澄清+完整报告)。
- **完整报告已生成后**,用户继续追问 → 直接用本 skill(带上之前那份 `selected_doc_id`),**不要**重新走选指南/澄清/出报告流程。
