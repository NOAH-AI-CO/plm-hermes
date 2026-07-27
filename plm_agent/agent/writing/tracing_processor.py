# -*- coding: utf-8 -*-
"""Local file tracing processor for the writing agent.

The ``openai-agents`` SDK emits tracing spans via
``agents.tracing.TracingProcessor``. The default processor uploads traces
to ``platform.openai.com`` — no value for Azure deployments and leaks
prompt / tool IO. This processor replaces the default with a local
implementation that writes span boundaries into ``logs/agent.log`` using
the project's standard ``logging`` pipeline.

The log filter (``logging_config.LogIDFilter``) already stamps the
current ``log_id_var`` value onto every record, so correlation IDs flow
through automatically — nothing to pass explicitly.

Usage (from ``WritingAgent.start``)::

    from agent.writing.tracing_processor import install_local_tracing_processor
    install_local_tracing_processor()  # idempotent, replaces the OpenAI uploader
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from agents.tracing import Span, Trace, TracingProcessor

logger = logging.getLogger("agent.writing.tracing")


# Trim deeply nested payloads (LLM generation spans carry full input/output
# message arrays that would otherwise bloat the log).
_STRING_PREVIEW_LIMIT = 500
_LIST_PREVIEW_LIMIT = 10


def _trim(value: Any, limit: int = _STRING_PREVIEW_LIMIT) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}...[+{len(value) - limit}]"
    if isinstance(value, (list, tuple)):
        trimmed = [_trim(v, limit) for v in value[:_LIST_PREVIEW_LIMIT]]
        if len(value) > _LIST_PREVIEW_LIMIT:
            trimmed.append(f"...[+{len(value) - _LIST_PREVIEW_LIMIT} more]")
        return trimmed
    if isinstance(value, dict):
        return {k: _trim(v, limit) for k, v in value.items()}
    return value


def _compute_duration_ms(started_at: Optional[str], ended_at: Optional[str]) -> Optional[int]:
    """``Span.started_at`` / ``ended_at`` are ISO-8601 strings in the SDK."""
    if not started_at or not ended_at:
        return None
    try:
        s = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        e = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return int((e - s).total_seconds() * 1000)
    except Exception:
        return None


class LocalFileTracingProcessor(TracingProcessor):
    """Write SDK trace / span boundaries into ``logs/agent.log``."""

    def on_trace_start(self, trace: Trace) -> None:
        logger.info("[trace start] id=%s name=%s", trace.trace_id, trace.name)

    def on_trace_end(self, trace: Trace) -> None:
        logger.info("[trace end] id=%s name=%s", trace.trace_id, trace.name)

    def on_span_start(self, span: "Span[Any]") -> None:
        # Noisy; keep at DEBUG so production stays quiet.
        logger.debug(
            "[span start] id=%s parent=%s type=%s",
            span.span_id,
            span.parent_id,
            type(span.span_data).__name__,
        )

    def on_span_end(self, span: "Span[Any]") -> None:
        data_type = type(span.span_data).__name__
        dur_ms = _compute_duration_ms(span.started_at, span.ended_at)
        try:
            exported = span.export() or {}
        except Exception:
            exported = {}
        payload = exported.get("span_data") if isinstance(exported, dict) else None
        if isinstance(payload, dict):
            payload = {k: _trim(v) for k, v in payload.items()}
        if span.error:
            logger.warning(
                "[span end ERR] id=%s type=%s dur=%sms error=%s data=%s",
                span.span_id,
                data_type,
                dur_ms,
                span.error,
                payload,
            )
        else:
            logger.info(
                "[span end] id=%s type=%s dur=%sms data=%s",
                span.span_id,
                data_type,
                dur_ms,
                payload,
            )

    def force_flush(self) -> None:
        for h in logging.getLogger().handlers:
            try:
                h.flush()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.force_flush()


_TRACING_INSTALLED = False


def install_local_tracing_processor() -> None:
    """Replace the SDK's default processors with ``LocalFileTracingProcessor``.

    Idempotent — safe to call on every ``WritingAgent.start`` invocation.
    Uses ``set_trace_processors`` (not ``add_trace_processor``) so the
    platform-OpenAI uploader is removed, not run alongside.
    """
    global _TRACING_INSTALLED
    if _TRACING_INSTALLED:
        return
    from agents.tracing import set_trace_processors

    set_trace_processors([LocalFileTracingProcessor()])
    _TRACING_INSTALLED = True


__all__ = ["LocalFileTracingProcessor", "install_local_tracing_processor"]
