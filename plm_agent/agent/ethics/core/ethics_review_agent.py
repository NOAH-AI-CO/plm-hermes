import importlib
import json
import logging
import traceback
import asyncio
import os
import re
import zipfile
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from utils.sql_client import get_connection_user, text
from agent.ethics.policy_service import (
    search_policy_context_by_angle,
)
from agent.ethics.prompt.util_prompt import (
    ethics_policy_angle_prompt,
    ethics_triage_routing_prompt,
    policy_query_extraction_prompt_template_by_angle,
    review_checklist_aggregation_prompt,
    review_checklist_evaluation_prompt_template_by_angle,
    auto_sheet_decision_prompt,
    review_report_markdown_prompt,
)
from llm.composite_models import EthicsReviewModels
from utils.azure.blob_client import upload_file
from utils.utils.attachment import AttachmentManager
from agent.ethics.ethics_report_export import (
    convert_md_to_pdf_ethics,
    md_to_word_ethics,
    strip_llm_reasoning_from_ethics_markdown,
)

logger = logging.getLogger(__name__)

_AUTO_SHEET_ALLOWED_CODES: set[str] = {"af28", "af29", "af30", "af31", "af32", "af33", "af34", "af35"}
_ALLOWED_ITEM_DECISIONS: set[str] = {"pass", "fail", "uncertain"}
_ALLOWED_RISK_LEVELS: set[str] = {"low", "medium", "high"}
_ALLOWED_OVERALL_DECISIONS: set[str] = {"approve", "revise", "reject"}
_RISK_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}

# 检索 query 拼接顺序：基座中国优先，其次国际，再专项（与执行顺序一致）
_ETHICS_ANGLE_DISPLAY_ORDER: tuple[str, ...] = (
    "china_regulatory",
    "intl_baseline",
    "gcp_trials",
    "genetics_samples",
    "cross_cutting",
)


@dataclass(frozen=True)
class EthicsAnglePipelineSpec:
    """单角度流水线配置：各角度在内存中仍为 query→检索→研判串行，彼此由 gather 并行。"""

    angle_id: str
    angle_name: str
    top_k: int = 5
    enabled: bool = True


ETHICS_ANGLE_PIPELINE_SPECS: tuple[EthicsAnglePipelineSpec, ...] = (
    EthicsAnglePipelineSpec("intl_baseline", "国际核心伦理基准文件"),
    EthicsAnglePipelineSpec("china_regulatory", "中国现行核心伦理审查法规"),
    EthicsAnglePipelineSpec("gcp_trials", "临床试验质量管理规范（GCP）体系"),
    EthicsAnglePipelineSpec("genetics_samples", "人类遗传资源与生物样本管理"),
    EthicsAnglePipelineSpec("cross_cutting", "综合医疗法规与新兴技术伦理"),
)

ETHICS_REVIEW_ANGLES: list[tuple[str, str]] = [(s.angle_id, s.angle_name) for s in ETHICS_ANGLE_PIPELINE_SPECS]


@dataclass
class EthicsReviewContext:
    review_id: str
    owner_id: str
    review_type: str
    title: str
    doc_ids: list[str]
    extra_instructions: str
    worksheet_sheet_code: str = ""
    review_checklist: list[dict[str, Any]] = field(default_factory=list)
    review_checklist_for_llm: list[dict[str, Any]] = field(default_factory=list)
    status: str = "process"
    processing_status: str = ""
    progress: int = 0
    retrieval_query: str = ""
    policy_context: list[dict[str, Any]] = field(default_factory=list)
    retrieval_query_by_angle: dict[str, str] = field(default_factory=dict)
    query_reason_by_angle: dict[str, str] = field(default_factory=dict)
    policy_context_by_angle: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    evaluation_by_angle: dict[str, dict[str, Any]] = field(default_factory=dict)
    evaluation_errors_by_angle: dict[str, str] = field(default_factory=dict)
    project_docs: list[dict[str, Any]] = field(default_factory=list)
    checklist_evaluation: list[dict[str, Any]] = field(default_factory=list)
    overall_decision: str = ""
    overall_risk_level: str = ""
    overall_decision_reason: str = ""
    extracted_project_title: str = ""
    report_markdown: str = ""
    report_url: str = ""
    url: str = ""
    generated_summary: str = ""
    error_message: str = ""
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    finished_at: str = ""
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    triage_result: dict[str, Any] = field(default_factory=dict)
    triage_branch_gcp: bool = False
    triage_branch_genetics: bool = False
    triage_branch_cross_cutting: bool = False

    def to_result_json(self, *, include_project_doc_content: bool = True) -> dict[str, Any]:
        if include_project_doc_content:
            project_docs_out: list[dict[str, Any]] = self.project_docs
        else:
            project_docs_out = [
                {"id": str(d.get("id") or ""), "name": str(d.get("name") or "")} for d in self.project_docs
            ]
        return {
            "phase": self.status,
            "processing_status": self.processing_status,
            "progress": self.progress,
            "review_type": self.review_type,
            "title": self.title,
            "doc_ids": self.doc_ids,
            "worksheet_sheet_code": self.worksheet_sheet_code,
            "review_checklist_count": len(self.review_checklist),
            "review_checklist": self.review_checklist,
            "review_checklist_for_llm_count": len(self.review_checklist_for_llm),
            "retrieval_query": self.retrieval_query,
            "policy_context_count": len(self.policy_context),
            "policy_context": self.policy_context,
            "retrieval_query_by_angle": self.retrieval_query_by_angle,
            "query_reason_by_angle": self.query_reason_by_angle,
            "policy_context_by_angle": self.policy_context_by_angle,
            "evaluation_by_angle": self.evaluation_by_angle,
            "evaluation_errors_by_angle": self.evaluation_errors_by_angle,
            "project_doc_count": len(self.project_docs),
            "project_docs": project_docs_out,
            "checklist_evaluation_count": len(self.checklist_evaluation),
            "checklist_evaluation": self.checklist_evaluation,
            "overall_decision": self.overall_decision,
            "overall_risk_level": self.overall_risk_level,
            "overall_decision_reason": self.overall_decision_reason,
            "extracted_project_title": self.extracted_project_title,
            "report_url": self.report_url,
            "url": self.report_url,
            "summary": self.generated_summary,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at or None,
            "steps": self.steps,
            "triage_result": self.triage_result,
            "triage_branch_gcp": self.triage_branch_gcp,
            "triage_branch_genetics": self.triage_branch_genetics,
            "triage_branch_cross_cutting": self.triage_branch_cross_cutting,
        }


class EthicsReviewAgent:
    """伦理审查 Agent；主流程形态对齐 IIT `_use_tool`：线性 try + 反复写上下文。"""

    attachment_manager: AttachmentManager = AttachmentManager()

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self._custom_es_client: Any | None = self._build_custom_es_client(payload)
        raw_review_checklist = payload.get("review_checklist") if isinstance(payload.get("review_checklist"), list) else []
        self.ctx = EthicsReviewContext(
            review_id=str(payload.get("review_id") or "").strip(),
            owner_id=str(payload.get("owner_id") or "").strip(),
            review_type=str(payload.get("review_type") or "").strip() or "initial",
            title=str(payload.get("title") or "").strip(),
            doc_ids=[str(x) for x in (payload.get("doc_ids") or []) if str(x).strip()],
            extra_instructions=str(payload.get("extra_instructions") or "").strip(),
            worksheet_sheet_code=str(payload.get("worksheet_sheet_code") or "").strip().lower(),
            review_checklist=raw_review_checklist,
            review_checklist_for_llm=self._build_llm_review_checklist(raw_review_checklist),
        )
        self._ethics_run_step_key: str = ""

    async def _write_ethics_context(self, task_status: str, error_message: str = "") -> None:
        """对齐 IIT `write_iit_context`：落库当前快照（不含 project_docs 正文）。"""
        await self._update_review_status(
            task_status, self.ctx.to_result_json(include_project_doc_content=False), error_message
        )

    async def run(self) -> None:
        if not self.ctx.review_id or not self.ctx.owner_id:
            logger.warning("EthicsReviewAgent skipped: missing review_id/owner_id")
            return
        if self.ctx.worksheet_sheet_code not in _AUTO_SHEET_ALLOWED_CODES:
            raise ValueError("invalid worksheet_sheet_code: expected af28~af35")
        if not isinstance(self.ctx.review_checklist, list) or not self.ctx.review_checklist:
            raise ValueError("review_checklist must be provided as non-empty list")

        self._ethics_run_step_key = ""
        try:
            self.ctx.processing_status = "任务已受理，等待执行"
            await self._write_ethics_context("process")

            await self.ethics_collect_project_documents()
            await self.ethics_triage_and_routing()
            await self.ethics_core_baseline_review()
            await self.ethics_dynamic_specialized_review()
            await self.ethics_aggregate_multi_angle_results()
            await self.ethics_generate_markdown_report()
            await self.ethics_export_report_artifacts()

            self.ctx.processing_status = "completed"
            self.ctx.progress = 100
            self.ctx.status = "complete"
            self.ctx.finished_at = datetime.utcnow().isoformat() + "Z"
            await self._write_ethics_context("complete")
        except Exception as e:
            if self._ethics_run_step_key:
                self._mark_step_failed(self._ethics_run_step_key, str(e))
            self.ctx.status = "failed"
            self.ctx.processing_status = "failed"
            self.ctx.error_message = str(e)
            self.ctx.finished_at = datetime.utcnow().isoformat() + "Z"
            logger.error("EthicsReviewAgent failed: %s", traceback.format_exc())
            await self._write_ethics_context("failed", str(e))

    async def ethics_collect_project_documents(self) -> None:
        """按 doc_ids 拉附件并解析正文写入 ctx.project_docs（对齐 IIT：开始/结束语 + 写库）。"""
        step = "collect_project_docs"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "收集审查材料（附件正文）开始"
        self.ctx.progress = 15
        await self._write_ethics_context("process")

        self._ensure_project_docs_loaded()

        self.ctx.processing_status = "收集审查材料（附件正文）结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    def _ensure_project_docs_loaded(self) -> None:
        if self.ctx.project_docs:
            return
        if not self.ctx.doc_ids:
            self.ctx.project_docs = []
            return
        attachment_records = self.attachment_manager.fetch_attachments(self.ctx.doc_ids, True)
        docs: list[dict[str, Any]] = []
        for record in attachment_records:
            content_obj = record.get("content")
            raw_content = content_obj.get("content") if isinstance(content_obj, dict) else ""
            if isinstance(raw_content, (dict, list)):
                preview = json.dumps(raw_content, ensure_ascii=False)
            else:
                preview = str(raw_content or "")
            docs.append(
                {
                    "id": str(record.get("id") or ""),
                    "name": str(record.get("name") or ""),
                    "raw_content": preview,
                }
            )
        self.ctx.project_docs = docs

    async def ethics_triage_and_routing(self) -> None:
        """第一阶段：智能分诊与路由（提取特征 + 专项分支 0~3 触发开关）。"""
        step = "triage_routing"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "第一阶段：智能分诊与路由定调开始"
        self.ctx.progress = 28
        await self._write_ethics_context("process")

        if not self.ctx.review_checklist:
            raise ValueError("triage_routing failed: review_checklist is empty")

        raw_triage = await self._run_triage_routing_llm()
        normalized = self._normalize_triage_payload(raw_triage)
        self.ctx.triage_result = normalized
        self.ctx.triage_branch_gcp = bool(normalized.get("trigger_branch_gcp"))
        self.ctx.triage_branch_genetics = bool(normalized.get("trigger_branch_genetics"))
        self.ctx.triage_branch_cross_cutting = bool(normalized.get("trigger_branch_cross_cutting"))

        self.ctx.processing_status = "第一阶段：智能分诊与路由定调结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def ethics_core_baseline_review(self) -> None:
        """第二阶段：核心基座审查——先中国法规（主干），再国际准则（补漏；冲突在聚合阶段按属地优先裁决）。"""
        step = "core_baseline_review"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "第二阶段：核心基座审查（中国法规 → 国际准则）开始"
        self.ctx.progress = 48
        await self._write_ethics_context("process")

        if not self.ctx.review_checklist:
            raise ValueError("core_baseline_review failed: review_checklist is empty")

        self._reset_pipeline_angle_state()

        china_spec = ETHICS_ANGLE_PIPELINE_SPECS[1]
        china_result = await self._china_regulatory_ethics_review()
        self._accumulate_angle_results([china_spec], [china_result])

        intl_spec = ETHICS_ANGLE_PIPELINE_SPECS[0]
        intl_result = await self._intl_baseline_ethics_review()
        self._accumulate_angle_results([intl_spec], [intl_result])

        if "china_regulatory" not in self.ctx.evaluation_by_angle:
            raise ValueError("core_baseline_review failed: china_regulatory evaluation missing")
        if "intl_baseline" not in self.ctx.evaluation_by_angle:
            raise ValueError("core_baseline_review failed: intl_baseline evaluation missing")

        self.ctx.processing_status = "第二阶段：核心基座审查（中国法规 → 国际准则）结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def ethics_dynamic_specialized_review(self) -> None:
        """第三阶段：动态专项审查——按分诊标签并行 0~3 路（GCP / 遗传资源与样本 / 新兴技术与综合医疗）。"""
        step = "dynamic_specialized_review"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "第三阶段：动态专项审查开始"
        self.ctx.progress = 62
        await self._write_ethics_context("process")

        specs: list[EthicsAnglePipelineSpec] = []
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        if self.ctx.triage_branch_gcp:
            specs.append(ETHICS_ANGLE_PIPELINE_SPECS[2])
            tasks.append(asyncio.create_task(self._gcp_trials_ethics_review()))
        if self.ctx.triage_branch_genetics:
            specs.append(ETHICS_ANGLE_PIPELINE_SPECS[3])
            tasks.append(asyncio.create_task(self._genetics_samples_ethics_review()))
        if self.ctx.triage_branch_cross_cutting:
            specs.append(ETHICS_ANGLE_PIPELINE_SPECS[4])
            tasks.append(asyncio.create_task(self._cross_cutting_ethics_review()))

        if not tasks:
            self.ctx.processing_status = "第三阶段：动态专项审查结束（未触发任何专项分支，已跳过）"
            await self._write_ethics_context("process")
            self._mark_step_succeeded(step)
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._accumulate_angle_results(specs, results)

        self.ctx.processing_status = "第三阶段：动态专项审查结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def ethics_aggregate_multi_angle_results(self) -> None:
        """第四阶段：结论融合——冲突裁决、去重与证据链（LLM）；输出唯一 checklist_evaluation。"""
        step = "aggregate_angle_evaluation"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "第四阶段：结论融合与清单聚合开始"
        self.ctx.progress = 75
        await self._write_ethics_context("process")

        if not self.ctx.evaluation_by_angle:
            raise ValueError("aggregate_angle_evaluation failed: evaluation_by_angle is empty")
        llm_payload = await self._aggregate_review_checklist_with_llm()
        normalized_payload = self._normalize_checklist_evaluation_payload(llm_payload)
        if not normalized_payload.get("dimension_results"):
            raise ValueError("aggregate_angle_evaluation failed: llm output is empty or invalid")

        self.ctx.checklist_evaluation = normalized_payload.get("dimension_results", [])
        self.ctx.overall_decision = str(normalized_payload.get("overall_decision") or "revise")
        self.ctx.overall_risk_level = str(normalized_payload.get("overall_risk_level") or "medium")
        self.ctx.overall_decision_reason = str(normalized_payload.get("overall_reason") or "")
        self.ctx.extracted_project_title = str(normalized_payload.get("extracted_project_title") or "").strip()

        self.ctx.processing_status = "第四阶段：结论融合与清单聚合结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def ethics_generate_markdown_report(self) -> None:
        """第五阶段：生成《科学与伦理审查意见书》Markdown（REVIEW_REPORT_MARKDOWN_PROMPT）。"""
        step = "generate_markdown_report"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "生成 Markdown 伦理审查意见书开始"
        self.ctx.progress = 90
        await self._write_ethics_context("process")

        markdown = await self._generate_report_markdown_with_llm()
        if not markdown:
            raise ValueError("generate_markdown_report failed: llm returned empty markdown")
        self.ctx.report_markdown = markdown
        policy_titles = [str(x.get("title") or "") for x in self.ctx.policy_context if x.get("title")]
        project_doc_names = [str(x.get("name") or "") for x in self.ctx.project_docs if x.get("name")]
        checklist_dimension_names = [
            str(x.get("name") or "")
            for x in self.ctx.review_checklist
            if isinstance(x, dict) and str(x.get("name") or "").strip()
        ]
        self.ctx.generated_summary = (
            "伦理审查主流程已完成；以下为便于接口展示的字段摘要（正文见 report_markdown / 导出文件）。\n"
            f"- Query: {self.ctx.retrieval_query}\n"
            f"- Project docs: {', '.join(project_doc_names) if project_doc_names else 'N/A'}\n"
            f"- Worksheet: {self.ctx.worksheet_sheet_code or 'N/A'}\n"
            f"- Checklist dimensions: {len(self.ctx.review_checklist)}\n"
            f"- Checklist names: {', '.join(checklist_dimension_names[:8]) if checklist_dimension_names else 'N/A'}\n"
            f"- Overall decision: {self.ctx.overall_decision or 'N/A'}\n"
            f"- Overall risk level: {self.ctx.overall_risk_level or 'N/A'}\n"
            f"- Policy hits: {len(self.ctx.policy_context)}\n"
            f"- Policy titles: {', '.join(policy_titles) if policy_titles else 'N/A'}"
        )

        self.ctx.processing_status = "生成 Markdown 伦理审查意见书结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def ethics_export_report_artifacts(self) -> None:
        """Markdown → Word/PDF → zip → 上传 blob，写入 report_url。"""
        step = "persist_report_artifact"
        self._ethics_run_step_key = step
        self._mark_step_started(step)
        self.ctx.processing_status = "导出审查报告（Word/PDF/zip）并上传开始"
        self.ctx.progress = 95
        await self._write_ethics_context("process")

        report_markdown = strip_llm_reasoning_from_ethics_markdown((self.ctx.report_markdown or "").strip())
        if not report_markdown:
            raise ValueError("persist_report_artifact failed: report_markdown is empty")
        self.ctx.report_markdown = report_markdown

        ts = int(time.time())
        output_dir = f"outputs/ethics_review_{self.ctx.review_id}_{ts}"
        os.makedirs(output_dir, exist_ok=True)
        safe_title = (
            (self.ctx.extracted_project_title or self.ctx.title or "ethics_review").strip().replace("/", "_").replace("\\", "_")[:40]
        )
        file_stem = os.path.join(output_dir, f"伦理审查-{safe_title}-{ts}")
        md_path = f"{file_stem}.md"
        docx_path = f"{file_stem}.docx"
        pdf_path = f"{file_stem}.pdf"
        zip_path = f"{file_stem}.zip"
        format_type = "chinese"

        with open(md_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(report_markdown)

        def _convert_and_zip_sync() -> None:
            md_to_word_ethics(
                input_file_path=md_path,
                output_file_path=docx_path,
                format_type=format_type,
            )
            convert_md_to_pdf_ethics(md_path=md_path, pdf_path=pdf_path)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(docx_path, arcname=os.path.basename(docx_path))
                zf.write(pdf_path, arcname=os.path.basename(pdf_path))

        try:
            await asyncio.to_thread(_convert_and_zip_sync)
        except Exception as exc:
            raise RuntimeError(f"persist_report_artifact failed: md/docx/pdf or zip: {exc}") from exc

        object_key = f"{file_stem}.zip"
        upload_success = False
        upload_error = ""
        for attempt in range(3):
            try:
                if upload_file(bucket="", object_key=object_key, file_path=zip_path):
                    upload_success = True
                    break
            except Exception as upload_exception:
                upload_error = str(upload_exception)
            await asyncio.sleep(1 + attempt)

        if not upload_success:
            raise RuntimeError(f"persist_report_artifact failed: upload zip failed: {upload_error or 'unknown error'}")

        encoded_key = urllib.parse.quote(object_key)
        report_url = f"https://noahdata.blob.core.windows.net/nudata/{encoded_key}"
        self.ctx.report_url = report_url
        self.ctx.url = report_url

        for path in (md_path, docx_path, pdf_path, zip_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as cleanup_error:
                logger.warning("failed to cleanup report artifact file %s: %s", path, cleanup_error)

        self.ctx.processing_status = "导出审查报告（Word/PDF/zip）并上传结束"
        await self._write_ethics_context("process")
        self._mark_step_succeeded(step)

    async def infer_sheet_code_only(self) -> dict[str, Any]:
        """
        兼容接口: /ethics/review/infer-sheet-code
        不参与主审查流程，仅用于返回推断 sheet_code。
        """
        provided_code = str(self.ctx.worksheet_sheet_code or "").strip().lower()
        if provided_code in _AUTO_SHEET_ALLOWED_CODES:
            return {
                "sheet_code": provided_code,
                "reason": "sheet_code provided by caller",
                "decision_path": ["explicit_sheet_code"],
                "confidence": "high",
                "doc_count": len(self.ctx.project_docs),
            }

        self._ensure_project_docs_loaded()
        inferred = await self._infer_sheet_code_with_llm_for_api()
        inferred_code = str(inferred.get("sheet_code") or "").strip().lower()
        if inferred_code not in _AUTO_SHEET_ALLOWED_CODES:
            inferred_code = self._fallback_infer_sheet_code_by_keywords()
            inferred["reason"] = f"llm invalid output, fallback by heuristics => {inferred_code}"
            inferred["decision_path"] = ["fallback_heuristic"]
            inferred["confidence"] = "low"

        return {
            "sheet_code": inferred_code,
            "reason": str(inferred.get("reason") or ""),
            "decision_path": inferred.get("decision_path") if isinstance(inferred.get("decision_path"), list) else [],
            "confidence": str(inferred.get("confidence") or "low"),
            "doc_count": len(self.ctx.project_docs),
        }

    def _reset_pipeline_angle_state(self) -> None:
        self.ctx.retrieval_query_by_angle = {}
        self.ctx.query_reason_by_angle = {}
        self.ctx.policy_context_by_angle = {}
        self.ctx.evaluation_by_angle = {}
        self.ctx.evaluation_errors_by_angle = {}
        self.ctx.policy_context = []
        self.ctx.retrieval_query = ""

    def _rebuild_retrieval_query_display(self) -> None:
        parts: list[str] = []
        query_by_angle = self.ctx.retrieval_query_by_angle
        for angle_id in _ETHICS_ANGLE_DISPLAY_ORDER:
            query_text = str(query_by_angle.get(angle_id) or "").strip()
            if query_text:
                parts.append(f"{angle_id}:{query_text}")
        self.ctx.retrieval_query = " | ".join(parts)

    def _accumulate_angle_results(
        self,
        enabled_specs: list[EthicsAnglePipelineSpec],
        results: list[Any],
    ) -> None:
        seen_doc_ids: set[str] = set()
        for row in self.ctx.policy_context:
            doc_id = str(row.get("doc_id") or "").strip()
            unique_key = doc_id or f"nodoc::{row.get('title')}::{row.get('retrieval_source')}"
            seen_doc_ids.add(unique_key)

        for idx, result in enumerate(results):
            spec = enabled_specs[idx]
            angle_id = spec.angle_id
            if isinstance(result, Exception):
                self.ctx.evaluation_errors_by_angle[angle_id] = str(result)
                continue
            self.ctx.retrieval_query_by_angle[angle_id] = str(result.get("policy_query") or "").strip()
            self.ctx.query_reason_by_angle[angle_id] = str(result.get("reason") or "").strip()
            angle_policy_context = result.get("policy_context")
            policy_list = angle_policy_context if isinstance(angle_policy_context, list) else []
            self.ctx.policy_context_by_angle[angle_id] = policy_list
            angle_evaluation = result.get("evaluation")
            if isinstance(angle_evaluation, dict):
                self.ctx.evaluation_by_angle[angle_id] = angle_evaluation
            for row in policy_list:
                doc_id = str(row.get("doc_id") or "").strip()
                unique_key = doc_id or f"nodoc::{row.get('title')}::{row.get('retrieval_source')}"
                if unique_key in seen_doc_ids:
                    continue
                seen_doc_ids.add(unique_key)
                self.ctx.policy_context.append(dict(row))

        self._rebuild_retrieval_query_display()

        if not self.ctx.evaluation_by_angle:
            raise ValueError(
                "policy_review failed: no angle evaluation succeeded: "
                f"{self.ctx.evaluation_errors_by_angle}"
            )

    async def _run_triage_routing_llm(self) -> dict[str, Any]:
        checklist_blob = json.dumps(self.ctx.review_checklist_for_llm, ensure_ascii=False)
        docs_blob = json.dumps(self.ctx.project_docs, ensure_ascii=False)
        sys_prompt = ethics_triage_routing_prompt.replace("{review_checklist}", checklist_blob).replace(
            "{project_docs}", docs_blob
        )
        try:
            llm = EthicsReviewModels()
            stream = llm.stream_call(sys_prompt=sys_prompt, temperature=0)
            raw = ""
            async for chunk in stream:
                if chunk:
                    raw += str(chunk)
            parsed = self._extract_json_object(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.warning("ethics triage routing llm failed: %s", traceback.format_exc())
            return {}

    def _normalize_triage_payload(self, raw: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, dict) or not raw:
            return self._fallback_triage_from_docs()
        features_obj = raw.get("features")
        features: dict[str, Any] = features_obj if isinstance(features_obj, dict) else {}
        triggers_present = (
            "trigger_branch_gcp" in raw or "trigger_branch_genetics" in raw or "trigger_branch_cross_cutting" in raw
        )
        if not triggers_present:
            return self._fallback_triage_from_docs()
        return {
            "feature_summary": str(raw.get("feature_summary") or "").strip(),
            "features": features,
            "routing_rationale": str(raw.get("routing_rationale") or "").strip(),
            "trigger_branch_gcp": bool(raw.get("trigger_branch_gcp")),
            "trigger_branch_genetics": bool(raw.get("trigger_branch_genetics")),
            "trigger_branch_cross_cutting": bool(raw.get("trigger_branch_cross_cutting")),
        }

    def _fallback_triage_from_docs(self) -> dict[str, Any]:
        text_blocks: list[str] = [self.ctx.title, self.ctx.extra_instructions, self.ctx.review_type]
        for doc in self.ctx.project_docs:
            text_blocks.append(str(doc.get("name") or ""))
            text_blocks.append(str(doc.get("raw_content") or ""))
        text_joined = " ".join(text_blocks)
        lower = text_joined.lower()
        trigger_gcp = bool(
            re.search(
                r"干预|随机|对照|iit|研究者发起|临床试验|gcp|新药|器械|用药|给药|细胞治疗|免疫治疗|特医|申办方",
                text_joined,
            )
        )
        trigger_genetics = bool(
            re.search(r"遗传|基因|生物样本|组织|切片|血样|出境|人类遗传资源|二次利用|样本库|销毁", text_joined)
        )
        trigger_cross = bool(
            re.search(
                r"人工智能|机器学习|深度学习|医疗大模型|真实世界|电子病历|\brwd\b|\brwe\b|脑机|算法|数据挖掘",
                lower,
            )
        )
        return {
            "feature_summary": "未获得有效模型分诊输出，已按材料关键词触发专项路由",
            "features": {},
            "routing_rationale": "keyword_fallback_after_invalid_or_empty_llm_triage",
            "trigger_branch_gcp": trigger_gcp,
            "trigger_branch_genetics": trigger_genetics,
            "trigger_branch_cross_cutting": trigger_cross,
        }

    async def _intl_baseline_ethics_review(self) -> dict[str, Any]:
        s = ETHICS_ANGLE_PIPELINE_SPECS[0]
        query_info = await self._extract_policy_query_with_llm_by_angle(angle_id=s.angle_id, angle_name=s.angle_name)
        policy_query = str(query_info.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"{s.angle_id}: empty policy_query from llm")
        reason = str(query_info.get("reason") or "").strip()
        policy_context = await asyncio.to_thread(
            search_policy_context_by_angle,
            angle_id=s.angle_id,
            owner_id=self.ctx.owner_id,
            query_text=policy_query,
            top_k=s.top_k,
            es_client=self._custom_es_client,
        )
        llm_payload = await self._evaluate_review_checklist_with_llm_by_angle(
            angle_id=s.angle_id,
            angle_name=s.angle_name,
            policy_context=policy_context,
        )
        return {
            "policy_query": policy_query,
            "reason": reason,
            "policy_context": policy_context,
            "evaluation": llm_payload,
        }

    async def _china_regulatory_ethics_review(self) -> dict[str, Any]:
        s = ETHICS_ANGLE_PIPELINE_SPECS[1]
        query_info = await self._extract_policy_query_with_llm_by_angle(angle_id=s.angle_id, angle_name=s.angle_name)
        policy_query = str(query_info.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"{s.angle_id}: empty policy_query from llm")
        reason = str(query_info.get("reason") or "").strip()
        policy_context = await asyncio.to_thread(
            search_policy_context_by_angle,
            angle_id=s.angle_id,
            owner_id=self.ctx.owner_id,
            query_text=policy_query,
            top_k=s.top_k,
            es_client=self._custom_es_client,
        )
        llm_payload = await self._evaluate_review_checklist_with_llm_by_angle(
            angle_id=s.angle_id,
            angle_name=s.angle_name,
            policy_context=policy_context,
        )
        return {
            "policy_query": policy_query,
            "reason": reason,
            "policy_context": policy_context,
            "evaluation": llm_payload,
        }

    async def _gcp_trials_ethics_review(self) -> dict[str, Any]:
        s = ETHICS_ANGLE_PIPELINE_SPECS[2]
        query_info = await self._extract_policy_query_with_llm_by_angle(angle_id=s.angle_id, angle_name=s.angle_name)
        policy_query = str(query_info.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"{s.angle_id}: empty policy_query from llm")
        reason = str(query_info.get("reason") or "").strip()
        policy_context = await asyncio.to_thread(
            search_policy_context_by_angle,
            angle_id=s.angle_id,
            owner_id=self.ctx.owner_id,
            query_text=policy_query,
            top_k=s.top_k,
            es_client=self._custom_es_client,
        )
        llm_payload = await self._evaluate_review_checklist_with_llm_by_angle(
            angle_id=s.angle_id,
            angle_name=s.angle_name,
            policy_context=policy_context,
        )
        return {
            "policy_query": policy_query,
            "reason": reason,
            "policy_context": policy_context,
            "evaluation": llm_payload,
        }

    async def _genetics_samples_ethics_review(self) -> dict[str, Any]:
        s = ETHICS_ANGLE_PIPELINE_SPECS[3]
        query_info = await self._extract_policy_query_with_llm_by_angle(angle_id=s.angle_id, angle_name=s.angle_name)
        policy_query = str(query_info.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"{s.angle_id}: empty policy_query from llm")
        reason = str(query_info.get("reason") or "").strip()
        policy_context = await asyncio.to_thread(
            search_policy_context_by_angle,
            angle_id=s.angle_id,
            owner_id=self.ctx.owner_id,
            query_text=policy_query,
            top_k=s.top_k,
            es_client=self._custom_es_client,
        )
        llm_payload = await self._evaluate_review_checklist_with_llm_by_angle(
            angle_id=s.angle_id,
            angle_name=s.angle_name,
            policy_context=policy_context,
        )
        return {
            "policy_query": policy_query,
            "reason": reason,
            "policy_context": policy_context,
            "evaluation": llm_payload,
        }

    async def _cross_cutting_ethics_review(self) -> dict[str, Any]:
        s = ETHICS_ANGLE_PIPELINE_SPECS[4]
        query_info = await self._extract_policy_query_with_llm_by_angle(angle_id=s.angle_id, angle_name=s.angle_name)
        policy_query = str(query_info.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"{s.angle_id}: empty policy_query from llm")
        reason = str(query_info.get("reason") or "").strip()
        policy_context = await asyncio.to_thread(
            search_policy_context_by_angle,
            angle_id=s.angle_id,
            owner_id=self.ctx.owner_id,
            query_text=policy_query,
            top_k=s.top_k,
            es_client=self._custom_es_client,
        )
        llm_payload = await self._evaluate_review_checklist_with_llm_by_angle(
            angle_id=s.angle_id,
            angle_name=s.angle_name,
            policy_context=policy_context,
        )
        return {
            "policy_query": policy_query,
            "reason": reason,
            "policy_context": policy_context,
            "evaluation": llm_payload,
        }

    async def _extract_policy_query_with_llm_by_angle(self, *, angle_id: str, angle_name: str) -> dict[str, str]:
        query_schema: dict[str, Any] = {
            "type": "OBJECT",
            "properties": {
                "policy_query": {
                    "type": "STRING",
                    "description": "基于审查要点与审查方案内容提取的政策库检索 query",
                },
                "reason": {
                    "type": "STRING",
                    "description": "简述为何选择该 policy_query（项目事实与审查要点映射）",
                },
            },
            "required": ["policy_query", "reason"],
        }
        angle_prompt_config = ethics_policy_angle_prompt.get(angle_id)
        if not angle_prompt_config:
            raise ValueError(f"unknown angle prompt config: {angle_id}")
        sys_prompt = (
            policy_query_extraction_prompt_template_by_angle.replace("__ANGLE_NAME__", angle_name)
            .replace("__POLICY_LIST__", angle_prompt_config.get("policy_list", ""))
            .replace("{review_checklist}", json.dumps(self.ctx.review_checklist_for_llm, ensure_ascii=False))
            .replace("{project_docs}", json.dumps(self.ctx.project_docs, ensure_ascii=False))
        )
        if self.ctx.triage_result:
            sys_prompt += (
                "\n\n<triage_routing_context>\n以下 JSON 为第一阶段智能分诊结论，请据此收窄或强化本角度的检索 query（勿编造材料中不存在的事实）。\n"
                f"{json.dumps(self.ctx.triage_result, ensure_ascii=False)}\n"
                "</triage_routing_context>\n"
            )

        llm = EthicsReviewModels()
        raw_result = await llm(
            sys_prompt=sys_prompt,
            response_schema=query_schema,
            response_mime_type="application/json",
            thinking_budget="low",
            temperature=0,
        )
        if isinstance(raw_result, dict):
            parsed = raw_result
        else:
            parsed = self._extract_json_object(str(raw_result))
        if not isinstance(parsed, dict):
            raise ValueError(f"prepare_query failed: llm returned invalid json for angle={angle_id}")
        policy_query = str(parsed.get("policy_query") or "").strip()
        if not policy_query:
            raise ValueError(f"prepare_query failed: policy_query is empty for angle={angle_id}")
        return {"policy_query": policy_query, "reason": str(parsed.get("reason") or "").strip()}

    @staticmethod
    def _build_llm_review_checklist(review_checklist: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        for dimension in review_checklist:
            if not isinstance(dimension, dict):
                continue
            compact_items: list[dict[str, str]] = []
            raw_items = dimension.get("items")
            raw_items = raw_items if isinstance(raw_items, list) else []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                compact_items.append(
                    {
                        "item_key": str(item.get("item_key") or "").strip(),
                        "text": str(item.get("text") or "").strip(),
                    }
                )
            compact.append(
                {
                    "name": str(dimension.get("name") or "").strip(),
                    "description": str(dimension.get("description") or "").strip(),
                    "items": compact_items,
                }
            )
        return compact

    @staticmethod
    def _build_custom_es_client(payload: dict[str, Any]) -> Any | None:
        es_url = str(payload.get("es_url") or "").strip()
        es_username = str(payload.get("es_username") or "").strip()
        es_password = str(payload.get("es_password") or "").strip()
        if not es_url and not es_username and not es_password:
            return None
        if not es_url:
            raise ValueError("es_url is required when using custom es connection")
        if bool(es_username) != bool(es_password):
            raise ValueError("es_username and es_password must be provided together")
        elasticsearch_module = importlib.import_module("elasticsearch")
        basic_auth = (es_username, es_password) if es_username else None
        client = elasticsearch_module.Elasticsearch(
            hosts=es_url,
            basic_auth=basic_auth,
            max_retries=3,
            retry_on_timeout=True,
            request_timeout=30,
        )
        if not client.ping():
            raise ValueError("custom es connection failed: ping returned false")
        return client

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any]:
        text = (raw or "").strip().replace("```json", "").replace("```", "").strip()
        if not text:
            return {}
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def _infer_sheet_code_with_llm_for_api(self) -> dict[str, Any]:
        doc_lines: list[str] = []
        for idx, doc in enumerate(self.ctx.project_docs, start=1):
            name = str(doc.get("name") or "")
            raw_content = str(doc.get("raw_content") or "")
            doc_lines.append(f"[{idx}] name={name}\nraw_content={raw_content}")
        docs_text = "\n\n".join(doc_lines) if doc_lines else "NO_DOC_CONTENT"
        try:
            llm = EthicsReviewModels()
            stream = llm.stream_call(
                sys_prompt=auto_sheet_decision_prompt.replace("docx_text", docs_text),
                temperature=0,
            )
            raw = ""
            async for chunk in stream:
                if chunk:
                    raw += str(chunk)
            parsed = self._extract_json_object(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            logger.warning("infer sheet code with llm failed: %s", traceback.format_exc())
            return {}

    def _fallback_infer_sheet_code_by_keywords(self) -> str:
        text_blocks: list[str] = [self.ctx.title, self.ctx.extra_instructions, self.ctx.review_type]
        for doc in self.ctx.project_docs:
            text_blocks.append(str(doc.get("name") or ""))
            text_blocks.append(str(doc.get("raw_content") or ""))
        text = " ".join(text_blocks).lower()
        if re.search(r"免除审查|exempt review|exemption review", text):
            return "af28"
        if re.search(r"免除知情同意|免签|waiver of consent|waiver", text):
            return "af34"
        if re.search(r"隐瞒|欺骗|延迟告知|deception|conceal|withhold", text):
            return "af35"
        if re.search(r"泛知情同意|broad consent|未来不特定用途", text):
            return "af33"
        if re.search(r"二次利用|既往样本|既往数据|secondary use|identifiable sample", text):
            return "af32"
        if re.search(r"随机|干预|侵入|治疗|给药|intervention|random", text):
            return "af30"
        if re.search(r"观察性|问卷|访谈|随访|observational|survey|interview", text):
            return "af31"
        if re.search(r"研究方案|研究计划书|protocol", text):
            return "af29"
        return "af29"

    async def _generate_report_markdown_with_llm(self) -> str:
        report_dimensions = self.ctx.checklist_evaluation
        report_checklist = self.ctx.review_checklist_for_llm
        compact_payload = {
            "extracted_project_title": self.ctx.extracted_project_title,
            "overall_decision": self.ctx.overall_decision,
            "overall_risk_level": self.ctx.overall_risk_level,
            "overall_decision_reason": self.ctx.overall_decision_reason,
            "review_checklist": report_checklist,
            "checklist_evaluation": report_dimensions,
            "evaluation_by_angle_summary": self.ctx.evaluation_by_angle,
        }
        user_prompt = (
            "请将以下结构化审查结果整理为最终 Markdown 报告：\n"
            f"{json.dumps(compact_payload, ensure_ascii=False)}"
        )
        try:
            llm = EthicsReviewModels()
            stream = llm.stream_call(
                sys_prompt=review_report_markdown_prompt,
                user_prompt=user_prompt,
                temperature=0,
            )
            raw = ""
            async for chunk in stream:
                if chunk:
                    raw += str(chunk)
            text = (raw or "").strip().replace("```markdown", "").replace("```", "").strip()
            return strip_llm_reasoning_from_ethics_markdown(text)
        except Exception:
            logger.warning("generate markdown report with llm failed: %s", traceback.format_exc())
            return ""

    async def _evaluate_review_checklist_with_llm_by_angle(
        self,
        *,
        angle_id: str,
        angle_name: str,
        policy_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        angle_prompt_config = ethics_policy_angle_prompt.get(angle_id)
        if not angle_prompt_config:
            raise ValueError(f"unknown angle prompt config: {angle_id}")
        sys_prompt = (
            review_checklist_evaluation_prompt_template_by_angle.replace("__ANGLE_NAME__", angle_name)
            .replace("{project_docs}", json.dumps(self.ctx.project_docs, ensure_ascii=False))
            .replace("{policy_context}", json.dumps(policy_context, ensure_ascii=False))
            .replace("{review_checklist}", json.dumps(self.ctx.review_checklist_for_llm, ensure_ascii=False))
        )
        try:
            llm = EthicsReviewModels()
            stream = llm.stream_call(
                sys_prompt=sys_prompt,
                temperature=0,
            )
            raw = ""
            async for chunk in stream:
                if chunk:
                    raw += str(chunk)
            parsed = self._extract_json_object(raw)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("review_checklist_evaluation failed: llm returned non-json or empty json")
            return parsed
        except Exception as error:
            logger.error("review checklist evaluation with llm failed: %s", traceback.format_exc())
            raise RuntimeError(f"review_checklist_evaluation failed: llm call error angle={angle_id}") from error

    async def _aggregate_review_checklist_with_llm(self) -> dict[str, Any]:
        sys_prompt = (
            review_checklist_aggregation_prompt.replace(
                "{review_checklist}", json.dumps(self.ctx.review_checklist_for_llm, ensure_ascii=False)
            )
            .replace("{angle_results}", json.dumps(self.ctx.evaluation_by_angle, ensure_ascii=False))
            .replace("{triage_context}", json.dumps(self.ctx.triage_result, ensure_ascii=False))
        )
        try:
            llm = EthicsReviewModels()
            stream = llm.stream_call(
                sys_prompt=sys_prompt,
                temperature=0,
            )
            raw = ""
            async for chunk in stream:
                if chunk:
                    raw += str(chunk)
            parsed = self._extract_json_object(raw)
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("aggregate_angle_evaluation failed: llm returned non-json or empty json")
            return parsed
        except Exception as error:
            logger.error("aggregate angle evaluation with llm failed: %s", traceback.format_exc())
            raise RuntimeError("aggregate_angle_evaluation failed: llm call error") from error

    def _normalize_checklist_evaluation_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_dimensions = payload.get("dimension_results")
        source_dimensions = source_dimensions if isinstance(source_dimensions, list) else []
        source_dimension_by_id: dict[str, dict[str, Any]] = {}
        for dimension in source_dimensions:
            if not isinstance(dimension, dict):
                continue
            dimension_id = str(dimension.get("dimension_id") or "").strip()
            if dimension_id:
                source_dimension_by_id[dimension_id] = dimension

        normalized_dimensions: list[dict[str, Any]] = []
        all_item_decisions: list[str] = []
        all_item_risks: list[str] = []
        for idx, dimension in enumerate(self.ctx.review_checklist):
            if not isinstance(dimension, dict):
                continue
            dimension_id = str(dimension.get("dimension_id") or "").strip()
            source_dimension = source_dimension_by_id.get(dimension_id, {})
            if not source_dimension and idx < len(source_dimensions) and isinstance(source_dimensions[idx], dict):
                source_dimension = source_dimensions[idx]
            source_items = source_dimension.get("item_results")
            source_items = source_items if isinstance(source_items, list) else []
            source_item_by_id: dict[str, dict[str, Any]] = {}
            source_item_by_key: dict[str, dict[str, Any]] = {}
            for item in source_items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("item_id") or "").strip()
                if item_id:
                    source_item_by_id[item_id] = item
                item_key = str(item.get("item_key") or "").strip()
                if item_key:
                    source_item_by_key[item_key] = item

            normalized_items: list[dict[str, Any]] = []
            dimension_items = dimension.get("items")
            dimension_items = dimension_items if isinstance(dimension_items, list) else []
            for item_idx, item in enumerate(dimension_items):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                item_key = str(item.get("item_key") or "").strip()
                item_text = str(item.get("text") or "").strip()
                source_item: dict[str, Any] = {}
                if item_id:
                    source_item = source_item_by_id.get(item_id, {})
                if not source_item and item_key:
                    source_item = source_item_by_key.get(item_key, {})
                if not source_item and item_text:
                    for source_item_candidate in source_items:
                        if not isinstance(source_item_candidate, dict):
                            continue
                        if str(source_item_candidate.get("text") or "").strip() == item_text:
                            source_item = source_item_candidate
                            break
                if not source_item and item_idx < len(source_items) and isinstance(source_items[item_idx], dict):
                    source_item = source_items[item_idx]
                item_decision = self._normalize_item_decision(source_item.get("decision"))
                item_risk_level = self._normalize_risk_level(source_item.get("risk_level"))
                item_reason = str(source_item.get("reason") or "").strip()
                raw_evidence = source_item.get("evidence")
                evidence = [str(x).strip() for x in raw_evidence if str(x).strip()] if isinstance(raw_evidence, list) else []
                if not evidence:
                    evidence = ["证据不足，需人工复核"]
                normalized_items.append(
                    {
                        "text": str(item.get("text") or ""),
                        "decision": item_decision,
                        "risk_level": item_risk_level,
                        "reason": item_reason or "未提供明确理由，需人工复核",
                        "evidence": evidence,
                    }
                )
                all_item_decisions.append(item_decision)
                all_item_risks.append(item_risk_level)

            dimension_decision = self._derive_dimension_decision(normalized_items)
            dimension_risk_level = self._derive_max_risk_level(all_levels=[x.get("risk_level") for x in normalized_items])
            normalized_dimensions.append(
                {
                    "name": str(dimension.get("name") or ""),
                    "decision": dimension_decision,
                    "risk_level": dimension_risk_level,
                    "reason": str(source_dimension.get("reason") or "").strip() or "基于条目判定自动汇总",
                    "item_results": normalized_items,
                }
            )

        overall_decision = self._derive_overall_decision(item_decisions=all_item_decisions, item_risk_levels=all_item_risks)
        overall_risk_level = self._derive_max_risk_level(all_levels=all_item_risks)
        overall_reason = str(payload.get("overall_reason") or "").strip() or self._build_default_overall_reason(
            overall_decision=overall_decision,
            overall_risk_level=overall_risk_level,
            item_decisions=all_item_decisions,
        )
        raw_title = str(payload.get("extracted_project_title") or "").strip()
        if len(raw_title) > 200:
            raw_title = raw_title[:200] + "…"
        return {
            "overall_decision": overall_decision,
            "overall_risk_level": overall_risk_level,
            "overall_reason": overall_reason,
            "extracted_project_title": raw_title,
            "dimension_results": normalized_dimensions,
        }

    def _fallback_review_checklist_evaluation(self, reason: str) -> dict[str, Any]:
        normalized_dimensions: list[dict[str, Any]] = []
        for dimension in self.ctx.review_checklist:
            if not isinstance(dimension, dict):
                continue
            raw_items = dimension.get("items")
            raw_items = raw_items if isinstance(raw_items, list) else []
            item_results: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                item_results.append(
                    {
                        "text": str(item.get("text") or ""),
                        "decision": "uncertain",
                        "risk_level": "medium",
                        "reason": "自动审查结果不可用，需人工复核",
                        "evidence": ["未获得可靠自动证据"],
                    }
                )
            normalized_dimensions.append(
                {
                    "name": str(dimension.get("name") or ""),
                    "decision": "uncertain",
                    "risk_level": "medium",
                    "reason": "该维度需人工复核",
                    "item_results": item_results,
                }
            )
        return {
            "overall_decision": "revise",
            "overall_risk_level": "medium",
            "overall_reason": f"自动审查降级为人工复核: {reason}",
            "extracted_project_title": "",
            "dimension_results": normalized_dimensions,
        }

    @staticmethod
    def _normalize_item_decision(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _ALLOWED_ITEM_DECISIONS:
            return normalized
        return "uncertain"

    @staticmethod
    def _normalize_risk_level(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _ALLOWED_RISK_LEVELS:
            return normalized
        return "medium"

    @staticmethod
    def _normalize_overall_decision(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _ALLOWED_OVERALL_DECISIONS:
            return normalized
        return "revise"

    def _derive_dimension_decision(self, item_results: list[dict[str, Any]]) -> str:
        decisions = [self._normalize_item_decision(x.get("decision")) for x in item_results if isinstance(x, dict)]
        if not decisions:
            return "uncertain"
        if "fail" in decisions:
            return "fail"
        if "uncertain" in decisions:
            return "uncertain"
        return "pass"

    def _derive_max_risk_level(self, all_levels: list[Any]) -> str:
        normalized_levels = [self._normalize_risk_level(x) for x in all_levels]
        if not normalized_levels:
            return "medium"
        return max(normalized_levels, key=lambda level: _RISK_RANK.get(level, 2))

    def _derive_overall_decision(self, *, item_decisions: list[str], item_risk_levels: list[str]) -> str:
        normalized_decisions = [self._normalize_item_decision(x) for x in item_decisions]
        normalized_risks = [self._normalize_risk_level(x) for x in item_risk_levels]
        if any(decision == "fail" and risk == "high" for decision, risk in zip(normalized_decisions, normalized_risks)):
            return "reject"
        if "fail" in normalized_decisions or "uncertain" in normalized_decisions:
            return "revise"
        return "approve"

    def _build_default_overall_reason(self, *, overall_decision: str, overall_risk_level: str, item_decisions: list[str]) -> str:
        fail_count = sum(1 for x in item_decisions if self._normalize_item_decision(x) == "fail")
        uncertain_count = sum(1 for x in item_decisions if self._normalize_item_decision(x) == "uncertain")
        return (
            f"overall_decision={self._normalize_overall_decision(overall_decision)}, "
            f"overall_risk_level={self._normalize_risk_level(overall_risk_level)}, "
            f"fail_items={fail_count}, uncertain_items={uncertain_count}"
        )

    def _mark_step_started(self, step_name: str) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        step = self.ctx.steps.get(step_name) or {}
        step["status"] = "running"
        step["started_at"] = step.get("started_at") or now
        step["updated_at"] = now
        self.ctx.steps[step_name] = step

    def _mark_step_succeeded(self, step_name: str) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        step = self.ctx.steps.get(step_name) or {}
        step["status"] = "succeeded"
        step["updated_at"] = now
        step["finished_at"] = now
        step["error_message"] = ""
        self.ctx.steps[step_name] = step

    def _mark_step_failed(self, step_name: str, error_message: str) -> None:
        now = datetime.utcnow().isoformat() + "Z"
        step = self.ctx.steps.get(step_name) or {}
        step["status"] = "failed"
        step["updated_at"] = now
        step["finished_at"] = now
        step["error_message"] = error_message or ""
        self.ctx.steps[step_name] = step

    async def _update_review_status(self, status_value: str, result_json: dict[str, Any], error_message: str) -> None:
        sql = text(
            """
            UPDATE "Workflow_ethicsreviewtask"
            SET status = :status,
                result_json = CAST(:result_json AS jsonb),
                error_message = :error_message,
                time_updated = NOW(),
                time_finished = CASE WHEN :status IN ('complete', 'failed', 'error') THEN NOW() ELSE time_finished END
            WHERE id = CAST(:review_id AS uuid)
            """
        )
        params = {
            "review_id": self.ctx.review_id,
            "status": status_value,
            "result_json": json.dumps(result_json, ensure_ascii=False),
            "error_message": error_message or "",
        }

        def _write() -> None:
            with get_connection_user() as conn:
                conn.execute(sql, params)
                conn.commit()

        try:
            await asyncio.to_thread(_write)
        except (OSError, IOError) as io_error:
            logger.warning("Ethics review status write failed, retrying: %s", str(io_error))
            await asyncio.sleep(0.5)
            await asyncio.to_thread(_write)
