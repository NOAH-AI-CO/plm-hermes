---
name: plm-search-guidelines
description: >
  PLM 流程第①步。根据患者病情描述,从 yiyong 指南库检索并返回 TOP-5 候选临床指南
  (含机构 NCCN/CSCO/ESMO、指南名、年份、doc_id),供用户从中选择一份。凡用户描述了
  患者病情/临床问题并要做循证诊疗时,先用本 skill 拿候选指南列表。
---

# PLM 搜索候选指南 (TOP-5)

**Endpoint:** `POST http://plm-engine:8002/plm_evidence_based/select_guideline`

## 输入 / 输出
用户消息开头的 `【完整报告模式·指南NCCN】` 前缀里带了 **指南范围机构**(NCCN/CSCO/ESMO/CACA,必有一个,默认 NCCN)。把它作为 `guideline_priority_order` 传入,TOP-5 就限定在该机构。
```json
// 请求(compact: 后端缓存候选并返回 guidelines_id, 你不必再重吐候选)
{ "patient_input": "65岁女性，HER2阳性乳腺癌，术后想了解辅助治疗", "product_scope": "yiyong", "guideline_priority_order": ["NCCN"], "compact": true }

// 响应
{
  "guidelines_id": "a1b2c3d4e5f6",
  "patient_info": { "primary_diagnosis": "HER2阳性乳腺癌", ... },
  "candidates_brief": [ {"n":1,"doc_id":161725599028213213,"name":"（2026.V1）CSCO诊疗指南：乳腺癌.pdf","organization":"CSCO"}, ...共5条... ]
}
```
`candidates_brief` 只给你用来把用户"选第 N 个"映射回 `doc_id`+`organization`;**卡片由前端凭 guidelines_id 自行渲染, 你不用管**。

## 调用
```bash
curl -s --max-time 120 -X POST http://plm-engine:8002/plm_evidence_based/select_guideline \
  -H 'Content-Type: application/json' \
  -d '{"patient_input": "<患者病情纯文字描述>", "product_scope": "yiyong", "guideline_priority_order": ["<用户选的指南范围机构>"], "compact": true}'
```

## 何时用
- 用户描述了患者病情/临床问题、要做循证诊疗时的**第①步之后**(已拿到病情+模式)。
- `product_scope` 固定传 `"yiyong"`;`guideline_priority_order` 传用户在【…·指南X】里选的那个机构(默认 NCCN)。

## 用完怎么做:只输出一个极小的 plm-guidelines 块(前端凭 id 自己拉候选渲染)
先写一句**中性**引导语(如"请从下方卡片中选择一份"),然后**只输出这个只含 guidelines_id 的小块**:

```plm-guidelines
{"__plm_guidelines__": true, "guidelines_id": "<curl 返回的 guidelines_id>"}
```

要点:
- ⛔ **中性,不替用户选**:不要推荐/排序/评判哪份"最对口最合适"、不要解释哪份属于哪个大类。选择权完全归用户(排除我们选错的责任)。
- ⛔ **绝不**把候选逐条写成 JSON / 表格 / 编号列表 —— 前端会用 `guidelines_id` 去后端拉 TOP-5 渲染成卡片。你重吐既慢又会吐错/漏/截断,还会把原始 JSON 暴露给用户。
- 只写一句中性引导语 + 这个小块,其余什么都不写。
- 用户点卡片后会回复"我选定第 N 个:<name>";你用 curl 返回的 `candidates_brief`(n ↔ doc_id/organization)记住该条 `doc_id` + `organization`,进入 plm-clarify。
- 🚧 用户没选定之前,不要调 plm-clarify / plm-run-report。

## 注意
- 若 `candidates_brief` 为空:说明该病情在 yiyong 库无匹配指南,如实告知用户,不要编造。
