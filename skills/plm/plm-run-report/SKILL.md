---
name: plm-run-report
description: >
  PLM 流程第④步(最后一步)。用户确认澄清后, 生成循证诊疗报告。报告分区呈现:
  诊断/检查/治疗/综合报告/次要指南补充。必须在用户确认澄清之后调用。
---

# PLM 出报告 (最终步)

**Endpoint:** `POST http://plm-engine:8002/plm_evidence_based`(带 `compact:true`, **秒回一个 report_id**)

## 拿到用户确认后【两步】然后本轮结束
### 第一步:curl 一次(秒回, 不阻塞)
```bash
curl -s -X POST http://plm-engine:8002/plm_evidence_based \
  -H 'Content-Type: application/json' \
  -d '{"patient_input":"<患者病情 + 澄清阶段用户确认/补充的全部信息, 合并成一段>","clarify_session_id":"<plm-clarify 返回的 id>","selected_doc_id":<用户选定指南 doc_id>,"guideline_priority_order":["<机构,如 NCCN>"],"product_scope":"yiyong","mode":"complex","entry_mode":"report","compact":true,"stream":false}'
```
- ⭐ `patient_input` **必须把第①步病情 + 用户在澄清阶段补充/确认的信息合并**成一段完整文字(如用户补充了"有肝转移/ECOG 1分/拟自体移植",都要并进去)。后端据此还原患者信息, 漏掉就等于丢失用户的补充。
- **不要**传 confirmed_patient_info / age / gender 等 —— 后端会用 patient_input 自动还原, 传了反而啰嗦。
- `entry_mode`: 快速→`"quick"`, 完整报告→`"report"`。
- 秒回 `{"status":"generating","report_id":"abc123..."}`。若回 `{"status":"error","error":"clarification_required"}`:回第③步让用户确认澄清。

### 第二步:写一句引导语 + 输出这个极小代码块(只放 report_id)
> "报告正在生成,下方会分栏显示,请稍候。"(**不要**写具体时长/分钟数)

```plm-report
{"__plm_report__":true,"report_id":"<curl 返回的 report_id>"}
```

## ⛔ 绝对禁止
- ⛔ 拿到 report_id 就**立即输出小块、本轮结束**。**不要** sleep / 轮询 / 再 curl 去查报告是否完成 —— 前端会自动流式加载。
- ⛔ **不要**用 python/jq 解析, **不要**把报告正文读回来或存文件(报告数十KB)。
- ⛔ 看到 `"status":"generating"` 是**正常**的, 不是错误, 不要重试。
- 前端 noah-plm-panels 扩展会用这个 report_id 实时流式渲染成 诊断/检查/治疗/综合报告/次要指南补充 五个 Tab。

## 何时用
- **仅在用户确认澄清之后**。`selected_doc_id` + `guideline_priority_order` 一起传, 报告才严格用用户选的那份指南。
