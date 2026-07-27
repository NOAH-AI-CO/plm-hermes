"""
PLM 澄清(clarification) 流式接口 — 决策树驱动版。

设计原则
========

澄清的核心目标:**只问图谱里真正缺的判断点**(missing_dimensions),
绝不让 LLM 凭常识"再发挥"几条。

流程:
  Step 1) 从原始 patient_input 抽出 patient_info (复用 step_extract_patient_info)
  Step 2) 用 primary_diagnosis 检索主指南文档 (search_guideline_documents)
         - 取相关度第一名
         - 若第一名无图谱 → 诚实地告诉用户"该指南尚未建图",
           不去候选里挑次优;否则会用一份不那么相关的指南去蒙混
  Step 3) 跑 graph_path 搜索 (run_search_phase_by_doc_id)
         - 拿 matched_nodes / missing_dimensions
  Step 4) LLM 流式产出 Markdown
         - 已掌握信息(展示从 patient_info 抽到的)
         - 仍需澄清(严格只列 missing_dimensions 里的项)
         - 怎么补充 (1. 2. 3. 引导)

事件协议:
  - started              {model}
  - extracting_info      {}
  - patient_info_done    {patient_info}
  - searching_guideline  {query}
  - guideline_resolved   {doc_id, filename, has_graph}
  - no_graph             {primary_diagnosis, filename, reason}
  - graph_searching      {doc_id}
  - graph_done           {decision_type, matched_node_count, missing_count}
  - markdown_chunk       {text}
  - complete             {model, full_markdown, primary_diagnosis, doc_id,
                          filename, has_graph, missing_dimensions, matched_nodes,
                          elapsed_seconds}
  - error                {code, message}
"""
from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from agent.patient_like_me.v1.rag import prompts

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "glm-5.2-flash"


def _load_glm52_pro():
    from llm.ali_models import Glm52Pro
    return Glm52Pro()


def _load_glm52_flash():
    from llm.ali_models import Glm52Flash
    return Glm52Flash()


_MODEL_LOADERS = {
    "glm-5.2-pro": _load_glm52_pro,
    "glm-5.2-flash": _load_glm52_flash,
    # 兼容旧 caller: 仍写 "gemini-3.5-flash" 也走 GLM Flash
    "gemini-3.5-flash": _load_glm52_flash,
}


# ────────────────────── helpers ──────────────────────


def _render_dict_value(v: Any) -> str:
    if v in (None, "", [], {}):
        return ""
    if isinstance(v, (list, tuple)):
        return "、".join(str(x) for x in v if x not in (None, "", [], {}))
    if isinstance(v, dict):
        return "、".join(f"{ik}: {iv}" for ik, iv in v.items() if iv)
    return str(v)


def _format_structured_hint(structured_hint: dict | None) -> str:
    if not structured_hint or not isinstance(structured_hint, dict):
        return "（无）"
    lines: list[str] = []
    for k, v in structured_hint.items():
        rendered = _render_dict_value(v)
        if rendered:
            lines.append(f"- {k}: {rendered}")
    return "\n".join(lines) if lines else "（无）"


def _format_patient_info(patient_info: dict | None) -> str:
    """从 step_extract_patient_info 拿到的 patient_info 渲染给 LLM。"""
    if not patient_info or not isinstance(patient_info, dict):
        return "（系统未能从原始描述里抽出结构化字段）"
    labels = {
        "primary_diagnosis": "主诊断",
        "has_clear_diagnosis": "诊断是否已明确",
        "current_symptoms": "当前症状",
        "test_results": "已有检查结果",
        "current_medications": "当前用药",
    }
    lines: list[str] = []
    for key, label in labels.items():
        rendered = _render_dict_value(patient_info.get(key))
        if rendered:
            lines.append(f"- {label}: {rendered}")
    return "\n".join(lines) if lines else "（无）"


def _format_missing_dimensions(missing: list[dict] | None) -> str:
    """missing_dimensions → LLM 易消化的列表文本。"""
    if not missing:
        return "（无缺失项 — 系统判断当前临床路径上的关键判断点都已充分。）"
    lines: list[str] = []
    for i, m in enumerate(missing, 1):
        if not isinstance(m, dict):
            continue
        key = (m.get("key") or "").strip()
        question = (m.get("question") or "").strip()
        reason = (m.get("reason") or "").strip()
        expected = (m.get("expected_type") or "").strip()
        head = f"{i}. " + (f"[{key}] {question}" if key else question)
        block = [head]
        if reason:
            block.append(f"   - 临床意义: {reason}")
        if expected:
            block.append(f"   - 期望取值类型: {expected}")
        lines.append("\n".join(block))
    return "\n".join(lines)


def _render_known_info_section(patient_info: dict | None, primary_diagnosis: str | None) -> str:
    """方案 A: 把 patient_info 渲染成给医生看的 '## 已掌握信息' Markdown 段(无 LLM)。"""
    labels = {
        "age": "年龄",
        "gender": "性别",
        "primary_diagnosis": "主诊断",
        "current_symptoms": "当前症状",
        "test_results": "已有检查结果",
        "current_medications": "当前用药",
    }
    lines: list[str] = ["## 已掌握信息", ""]
    found = False
    for key, label in labels.items():
        if patient_info and isinstance(patient_info, dict):
            rendered = _render_dict_value(patient_info.get(key))
        else:
            rendered = ""
        if not rendered and key == "primary_diagnosis" and primary_diagnosis:
            rendered = primary_diagnosis
        if rendered:
            lines.append(f"- **{label}**: {rendered}")
            found = True
    if not found:
        lines.append("- (系统未能从原始描述里抽出结构化字段)")
    return "\n".join(lines)


def _format_matched_nodes(matched_nodes: list[dict] | None) -> str:
    """patient 在图谱上已匹配的节点 → 让 LLM 知道"已经到哪一步"。"""
    if not matched_nodes:
        return "（暂未匹配到决策路径上的明确节点）"
    lines: list[str] = []
    for n in matched_nodes:
        if not isinstance(n, dict):
            continue
        title = (n.get("title") or n.get("text") or "").strip()
        code = (n.get("page_code") or n.get("code") or "").strip()
        if not title:
            continue
        lines.append(f"- [{code}] {title}" if code else f"- {title}")
    return "\n".join(lines) if lines else "（无）"


async def _resolve_filename_and_has_graph(doc_id: int) -> tuple[str, bool]:
    """通过 doc_id 拿 filename + has_graph 标志。

    search_guideline_documents 返回的 dict 字段有限(没 filename / has_graph),
    这里用 guidance_db 提供的统一接口去查最新 doc。
    """
    from agent.patient_like_me.v1.guideline import guidance_db
    doc = guidance_db._get_guideline_doc(doc_id)
    if not doc:
        return "", False
    filename = (doc.get("filename") or doc.get("guideline_name") or "").strip()
    has_graph = bool(doc.get("has_graph"))
    return filename, has_graph


async def _llm_select_best_doc(
    diagnosis: str,
    query: str,
    candidates: list[dict],
) -> list[str]:
    """`search_guideline_documents` 的 LLM selector:从 KNN 候选里精确挑出最相关的疾病指南。

    为什么需要:doc-level KNN 在中文医学短语上向量歧义大
    (例如 "非小细胞肺癌-腺癌" 可能 KNN 命中 "小肠腺癌" 或 "小细胞肺癌");
    让 Flash 看每个候选的文件名 + 摘要,选真正匹配主诊断的那一个。

    返回:被选中 doc_id 的字符串列表 (search_guideline_documents 期望的格式)。
    selector 失败时返回空 list,让 search_guideline_documents 自动 fallback
    到 KNN 排序结果。
    """
    if not candidates:
        return []

    # 渲染候选列表给 LLM 看
    lines = []
    for d in candidates:
        did = str(d.get("id", "")).strip()
        name = (d.get("name") or "").strip()
        summary = (d.get("summary") or "").replace("\n", " ").strip()[:200]
        if not did:
            continue
        lines.append(f"- doc_id={did} | 文件名: {name}\n  摘要: {summary}")
    candidates_text = "\n".join(lines)

    sys_prompt = (
        "你是临床指南匹配助手。给定患者的主诊断和一组候选指南, 请挑出最能指导该患者诊疗的 1 份。\n"
        "判断时**文件名和摘要都要看**, 摘要往往覆盖了文件名未写明的亚型/病种。\n"
        "匹配规则:\n"
        "- 主诊断是具体亚型, 候选是包含它的上位大类指南 → 视为匹配 (大类涵盖亚型的诊疗)。\n"
        "- 主诊断是宽泛类目, 候选是其下具体亚型指南 → 视为匹配。\n"
        "- 仅词面相似但病种不同 (如'肺腺癌' vs '小肠腺癌') → 不算匹配。\n"
        "只有当所有候选都跟主诊断病种脱钩时才返回空。"
    )
    user_prompt = (
        f"# 主诊断\n{diagnosis or '(未明确)'}\n\n"
        f"# 病例查询\n{query}\n\n"
        f"# 候选指南列表\n{candidates_text}\n\n"
        f"# 输出格式\n"
        f"仅返回一个 JSON 对象,格式: {{\"selected_doc_id\": \"<doc_id>\"}}\n"
        f"如果候选里没有真正匹配主诊断的指南,返回 {{\"selected_doc_id\": \"\"}}。\n"
    )

    import json
    try:
        llm = _load_glm52_flash()
        raw = await llm(
            sys_prompt=sys_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            response_mime_type="application/json",
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        parsed = json.loads(text)
        chosen = (parsed.get("selected_doc_id") or "").strip()
        if chosen:
            return [chosen]
    except Exception:
        logger.exception("[clarification] LLM doc selector failed")
    return []


# ────────────────────── main flow ──────────────────────


async def stream_clarification(
    patient_input: str,
    structured_hint: dict | None = None,
    model: str | None = None,
    guideline_priority_order: list[str] | None = None,
    product_scope: str | None = None,
    doc_id: int | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """决策树驱动的澄清流。yield (event_name, payload)。

    guideline_priority_order: 前端选的主指南机构白名单 (["NCCN"] / ["CSCO"] 等),
        非空时限定 KNN 检索只在这些 publisher 的指南里挑, 跟主接口对齐。
        None / 空列表 → 全局搜 (兼容老前端).
    product_scope: 'sahzu_only' / 'public' / 'yiyong' ... 指南库范围。**必须在本
        生成器内部设 contextvar**: caller 在外层设的 contextvar 不会传进本异步
        生成器的检索帧 (async gen + create_task 的 context 捕获时机), 导致 sahzu
        澄清曾漏搜到 yiyong/public 库的指南。
    """
    t0 = time.perf_counter()
    model = (model or _DEFAULT_MODEL).strip()
    patient_input = (patient_input or "").strip()

    if not patient_input:
        yield "error", {"code": "MISSING_INPUT", "message": "patient_input is required."}
        return

    # 在本生成器帧里落实 product_scope, 保证 Step2 检索 + Step3 图谱搜索都按同一
    # 库范围过滤 (与主报告一致)。
    if product_scope:
        from agent.patient_like_me.v1.rag.evidence import current_product_scope
        current_product_scope.set(product_scope)

    loader = _MODEL_LOADERS.get(model)
    if loader is None:
        supported = ", ".join(sorted(_MODEL_LOADERS))
        yield "error", {"code": "UNKNOWN_MODEL", "message": f"Unknown model {model!r}. Supported: {supported}"}
        return

    yield "started", {"model": model}

    # ── Step 1: 抽 patient_info ──
    yield "extracting_info", {}
    try:
        from agent.patient_like_me.v1.rag.workflow import step_extract_patient_info
        patient_info, _ = await step_extract_patient_info(patient_input)
    except Exception as exc:
        logger.exception("[clarification] extract_patient_info failed")
        yield "error", {"code": "EXTRACT_FAILED", "message": str(exc)[:300]}
        return
    yield "patient_info_done", {"patient_info": patient_info or {}}

    primary_diagnosis = (patient_info.get("primary_diagnosis") or "").strip()
    current_symptoms = patient_info.get("current_symptoms") or ""
    if isinstance(current_symptoms, list):
        current_symptoms = "、".join(str(x) for x in current_symptoms)
    elif isinstance(current_symptoms, dict):
        current_symptoms = ", ".join(f"{k}: {v}" for k, v in current_symptoms.items() if v)
    else:
        current_symptoms = str(current_symptoms)

    test_results = patient_info.get("test_results") or ""
    if isinstance(test_results, (list, tuple)):
        test_results = "、".join(str(x) for x in test_results if x)
    elif isinstance(test_results, dict):
        test_results = ", ".join(f"{k}: {v}" for k, v in test_results.items() if v)
    else:
        test_results = str(test_results)

    # 检索 query 构造 — 与主流程 _run_multi_guide_branch 完全一致:
    #   diagnosis + key_features(current_symptoms + test_results)拼成一句完整描述,
    #   让 KNN 同时看到诊断词 + 主诉 + 检查结果三方面信号,
    #   避免"NSCLC-腺癌 → 误命中小肠腺癌"这种因为单一词向量歧义导致的误检。
    key_features = " ".join(x for x in [current_symptoms, test_results] if x).strip()
    doc_query = " ".join(x for x in [primary_diagnosis, key_features] if x).strip()
    if not doc_query:
        doc_query = patient_input  # 兜底:抽取一无所获时用原文

    # ── Step 2: 找主指南 doc ──
    # 用户已在前端 TOP-5 选定 doc_id → 直接用这一份, 不再自动检索(保证澄清与报告同一份指南);
    # 否则用 LLM selector 检索(KNN 向量歧义大, Flash 看候选文件名/摘要复审更稳)。
    try:
        doc_id = int(doc_id) if doc_id else 0
    except Exception:
        doc_id = 0
    filename_from_search = ""
    if doc_id:
        yield "searching_guideline", {"query": doc_query, "selected_doc_id": doc_id}
    else:
        allowed_publishers = [p for p in (guideline_priority_order or []) if p] or ["NCCN"]
        yield "searching_guideline", {"query": doc_query, "allowed_publishers": allowed_publishers}
        try:
            from agent.patient_like_me.v1.rag.evidence import search_guideline_documents
            docs = await search_guideline_documents(
                query=doc_query,
                diagnosis=primary_diagnosis,
                max_docs=1,
                multi_org=False,
                selector=_llm_select_best_doc,   # ← LLM 帮 KNN 复审
                allowed_publishers=allowed_publishers,
            )
        except Exception as exc:
            logger.exception("[clarification] search_guideline_documents failed")
            yield "error", {"code": "GUIDELINE_SEARCH_FAILED", "message": str(exc)[:300]}
            return

        if not docs:
            # 指南库里完全没匹配:这是真的"无指南可参考"
            yield "no_graph", {
                "primary_diagnosis": primary_diagnosis,
                "filename": "",
                "reason": "指南库中未找到与该病例相关的指南文档",
            }
            async for ev in _emit_no_graph_markdown(
                model=model,
                primary_diagnosis=primary_diagnosis,
                filename="",
                patient_info=patient_info,
                t0=t0,
            ):
                yield ev
            return

        top_doc = docs[0]
        doc_id = int(top_doc.get("id") or 0)
        filename_from_search = (top_doc.get("name") or "").strip()

    # ── Step 3: 检查图谱是否存在(以 has_graph 为准) ──
    filename, has_graph = await _resolve_filename_and_has_graph(doc_id)
    if not filename:
        filename = filename_from_search

    yield "guideline_resolved", {
        "doc_id": doc_id,
        "filename": filename,
        "has_graph": has_graph,
    }

    if not has_graph:
        # 最相关的指南没图谱 — 诚实地告诉用户,不去找次优替代品
        yield "no_graph", {
            "primary_diagnosis": primary_diagnosis,
            "filename": filename,
            "reason": "匹配的指南文档尚未建立决策图谱",
        }
        async for ev in _emit_no_graph_markdown(
            model=model,
            primary_diagnosis=primary_diagnosis,
            filename=filename,
            patient_info=patient_info,
            t0=t0,
        ):
            yield ev
        return

    # ── Step 4: 走图谱搜索(真流式) ──
    # 用 asyncio.Queue 桥接 search 内部的 text_stream_cb → yield 给前端
    yield "graph_searching", {"doc_id": doc_id}

    import asyncio as _asyncio
    import uuid as _uuid
    text_queue: _asyncio.Queue = _asyncio.Queue()
    _SENTINEL = object()

    async def _on_text(chunk: str):
        await text_queue.put(chunk)

    # 拼给 clarify LLM 的 patient_text: 前置结构化输入 (前端下拉/开关等填的字段),
    # 让 LLM 有机会对比"结构化 vs 原文", 冲突时在澄清里提醒医生。
    # 只在 clarify 分支拼, 不动前面的 KNN 检索/patient_info 抽取, 避免污染检索信号。
    structured_block = _format_structured_hint(structured_hint)
    if structured_block and structured_block != "（无）":
        clarify_input = (
            "[前端结构化输入]\n" + structured_block + "\n\n"
            "[医生填写原文]\n" + patient_input
        )
    else:
        clarify_input = patient_input

    async def _do_search():
        try:
            from agent.patient_like_me.v1.guideline.search import run_search_phase_by_doc_id
            return await run_search_phase_by_doc_id(
                clarify_input, doc_id, mode="clarify",
                text_stream_cb=_on_text,
            )
        finally:
            await text_queue.put(_SENTINEL)

    search_task = _asyncio.create_task(_do_search())

    first_chunk_time = None
    full_md_parts: list[str] = []
    while True:
        item = await text_queue.get()
        if item is _SENTINEL:
            break
        if first_chunk_time is None:
            first_chunk_time = time.perf_counter() - t0
        full_md_parts.append(item)
        yield "markdown_chunk", {"text": item}

    try:
        graph_result = await search_task
    except Exception as exc:
        logger.exception("[clarification] graph search failed")
        yield "error", {"code": "GRAPH_SEARCH_FAILED", "message": str(exc)[:300]}
        return

    if "error" in graph_result:
        yield "no_graph", {
            "primary_diagnosis": primary_diagnosis,
            "filename": filename,
            "reason": f"图谱搜索失败: {graph_result.get('error')}",
        }
        async for ev in _emit_no_graph_markdown(
            model=model,
            primary_diagnosis=primary_diagnosis,
            filename=filename,
            patient_info=patient_info,
            t0=t0,
        ):
            yield ev
        return

    matched_nodes = graph_result.get("matched_nodes") or []
    clarify_markdown = "".join(full_md_parts).strip() or (graph_result.get("clarify_markdown") or "").strip()
    decision_type = graph_result.get("decision_type") or ""

    yield "graph_done", {
        "decision_type": decision_type,
        "matched_node_count": len(matched_nodes),
        "clarify_markdown_chars": len(clarify_markdown),
        "first_chunk_seconds": round(first_chunk_time or 0, 2),
    }

    # 兜底:如果 LLM 一字未吐(常见于 missing_dimensions 为空、无需澄清),
    # 用真实抽到的 patient_info 渲染"已掌握信息", 不要再写死"未能抽出"。
    if not clarify_markdown:
        clarify_markdown = (
            _render_known_info_section(patient_info, primary_diagnosis)
            + "\n\n## 仍需澄清\n\n指南所需关键事实已齐备，无需补充。"
        )
        yield "markdown_chunk", {"text": clarify_markdown}

    # 存 Redis: 让主报告链路可复用同一组 matched_node_ids,保证一致性
    clarify_session_id = f"clarify_{_uuid.uuid4().hex[:16]}"
    try:
        from agent.common.session_store import save_session
        payload_for_redis = {
            "matched_node_ids": [n.get("node_id") for n in matched_nodes],
            "doc_id": doc_id,
            "filename": filename,
            "primary_diagnosis": primary_diagnosis,
            "patient_input": patient_input,
            "patient_info": patient_info,
        }
        # 借用 session_store 的 report_text 字段存 JSON(类型上 string 兼容)
        import json as _json
        await save_session(
            "plm", clarify_session_id,
            report_text=_json.dumps(payload_for_redis, ensure_ascii=False),
            history=[],
        )
        logger.info("[clarification] saved clarify_session_id=%s matched=%d", clarify_session_id, len(matched_nodes))
    except Exception as e:
        logger.warning("[clarification] redis save failed: %s", e)
        clarify_session_id = ""

    yield "complete", {
        "model": model,
        "full_markdown": clarify_markdown,
        "primary_diagnosis": primary_diagnosis,
        "patient_info": patient_info,  # ← bug 修复: 之前忘了透出, 主接口拿到的 confirmed_info 永远是空
        "doc_id": doc_id,
        "filename": filename,
        "has_graph": True,
        "decision_type": decision_type,
        "matched_nodes": matched_nodes,
        "clarify_markdown": clarify_markdown,
        "clarify_session_id": clarify_session_id,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }


async def _emit_no_graph_markdown(
    *,
    model: str,
    primary_diagnosis: str,
    filename: str,
    patient_info: dict,
    t0: float,
) -> AsyncIterator[tuple[str, dict]]:
    """无图谱场景:发送一段固定 Markdown,告诉用户"该指南暂无决策图谱"。

    严格不走 LLM 凭常识"列出还缺什么"——那会破坏"图谱缺什么才问什么"
    的语义边界。让前端 / 用户自行决定下一步动作(不加引导段落,保持
    与主路径"只输出两个章节"的产品口径一致)。

    Markdown 内容固定,但分段 yield 保持流式接口的一致性。
    """
    diag_label = primary_diagnosis if primary_diagnosis else "您所描述的病情"
    parts: list[str] = []
    parts.append("## 暂无对应的决策图谱\n\n")
    parts.append(f"我们目前对 **{diag_label}** 暂未构建结构化的临床决策图谱，")
    parts.append("无法基于指南精确告诉您还差哪些信息。\n")
    full = "".join(parts)

    # 切成 60 字一段流式发送(保持事件协议一致;不调 LLM)
    chunk_size = 60
    for i in range(0, len(full), chunk_size):
        yield "markdown_chunk", {"text": full[i:i + chunk_size]}

    # 即使无图谱也发放 clarify_session_id,让前端"必须先澄清再调主接口"的流程统一。
    # 主接口拿到该 session 会 fallback 到非图谱 RAG 路径。
    import uuid as _uuid
    clarify_session_id = f"clarify_{_uuid.uuid4().hex[:16]}"
    try:
        from agent.common.session_store import save_session
        import json as _json
        payload_for_redis = {
            "matched_node_ids": [],
            "doc_id": 0,
            "filename": filename,
            "primary_diagnosis": primary_diagnosis,
            "patient_input": "",
            "has_graph": False,
        }
        await save_session(
            "plm", clarify_session_id,
            report_text=_json.dumps(payload_for_redis, ensure_ascii=False),
            history=[],
        )
        logger.info("[clarification] saved no_graph clarify_session_id=%s", clarify_session_id)
    except Exception as e:
        logger.warning("[clarification] redis save (no_graph) failed: %s", e)
        clarify_session_id = ""

    yield "complete", {
        "model": model,
        "full_markdown": full,
        "primary_diagnosis": primary_diagnosis,
        "patient_info": patient_info,
        "doc_id": 0,
        "filename": filename,
        "has_graph": False,
        "decision_type": "no_graph",
        "matched_nodes": [],
        "missing_dimensions": [],
        "clarify_markdown": full,
        "clarify_session_id": clarify_session_id,
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
    }
