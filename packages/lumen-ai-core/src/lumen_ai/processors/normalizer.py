"""
EventNormalizerProcessor — normalizes spans into canonical LumenAI events
and exports them via an injected BaseLumenAIExporter.

Must run LAST in the processor chain, after TenantSpanProcessor and
CostComputingSpanProcessor have written to their side-dicts.
"""
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.trace import StatusCode

from lumen_ai._attributes import first_int, first_str
from lumen_ai.processors.cost import pop_span_cost_data
from lumen_ai.processors.tenant import pop_span_tenant, sanitize_tenant_id
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.event_types import EventType, LumenAIEvent, Severity
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    LumenAIAttributes,
    OpenInferenceAttributes,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Health counters — make otherwise-silent event drops observable.
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()
_metrics = {"events_exported": 0, "export_errors": 0, "events_dropped": 0}


def _incr(key: str) -> None:
    with _metrics_lock:
        _metrics[key] += 1


def get_metrics() -> dict:
    """Snapshot of counters: events_exported / export_errors / events_dropped."""
    with _metrics_lock:
        return dict(_metrics)


def reset_metrics() -> None:
    """Zero the counters (useful in tests and between reporting windows)."""
    with _metrics_lock:
        for key in _metrics:
            _metrics[key] = 0


def _is_error(span: ReadableSpan) -> bool:
    """Return True if span ended in an error state."""
    status = span.status
    if status is None:
        return False
    code = getattr(status, "status_code", None)
    # StatusCode.ERROR is an enum member (value 2); compare against the member,
    # tolerating int-like statuses. Then fall back to an explicit is_ok is False
    # so a truthy mock/shim attribute is never read as "ok".
    if code is StatusCode.ERROR or getattr(code, "value", code) == 2:
        return True
    return getattr(status, "is_ok", None) is False


def _span_to_event_type(span: ReadableSpan) -> str:
    """Infer canonical event type from span attributes and status."""
    attrs = span.attributes or {}
    span_kind = first_str(attrs, OpenInferenceAttributes.SPAN_KIND)
    op_name = first_str(attrs, GenAIAttributes.OPERATION_NAME)
    tool_name = first_str(attrs, GenAIAttributes.TOOL_NAME)
    error = _is_error(span)

    if span_kind == "TOOL" or tool_name:
        return EventType.TOOL_CALL_FAILED if error else EventType.TOOL_CALL_COMPLETED
    if span_kind == "EMBEDDING" or op_name == "embedding":
        return EventType.EMBEDDING_FAILED if error else EventType.EMBEDDING_COMPLETED
    if span_kind == "RETRIEVER":
        return EventType.RETRIEVAL_FAILED if error else EventType.RETRIEVAL_COMPLETED
    if span_kind == "RERANKER":
        return EventType.RERANK_FAILED if error else EventType.RERANK_COMPLETED
    if span_kind == "LLM" or op_name in ("chat", "completion"):
        return EventType.LLM_CALL_FAILED if error else EventType.LLM_CALL_COMPLETED
    if span_kind == "AGENT":
        return EventType.AGENT_FAILED if error else EventType.AGENT_COMPLETED
    if span_kind == "CHAIN":
        return EventType.TASK_FAILED if error else EventType.TASK_COMPLETED

    # Spans with no GenAI/OpenInference kind (HTTP handlers, custom work) are
    # reported as generic agent steps — but a failed one must still read as failed.
    return EventType.AGENT_FAILED if error else EventType.AGENT_COMPLETED


def _span_duration_ms(span: ReadableSpan) -> int:
    if span.start_time and span.end_time:
        return int((span.end_time - span.start_time) / 1_000_000)
    return 0


def _span_timestamp(span: ReadableSpan) -> str:
    """ISO-8601 UTC time the span ended — not the time it was exported.

    Exporters can batch or retry, so wall-clock time at export would skew cost
    timelines; the span's own end_time (ns since epoch) is the event time.
    """
    if span.end_time:
        return datetime.fromtimestamp(span.end_time / 1_000_000_000, tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


class EventNormalizerProcessor(SpanProcessor):
    """
    Converts OTel spans into canonical LumenAI events and exports them.

    Args:
        exporter: Optional BaseLumenAIExporter. If None, events are only logged.
    """

    def __init__(self, exporter: Optional[BaseLumenAIExporter] = None, runtime=None) -> None:
        self._exporter = exporter
        self._runtime = runtime

    def on_start(self, span, parent_context=None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = span.attributes or {}
            # Consume (pop) the upstream side-map entries so they are freed once
            # this span's event is built — bounds memory and avoids id-reuse stale reads.
            cost_data = pop_span_cost_data(span)
            tenant_id = (
                pop_span_tenant(span)
                or sanitize_tenant_id(first_str(attrs, LumenAIAttributes.TENANT_ID))
                or "default"
            )
            error = _is_error(span)
            model = cost_data.get("model") or first_str(
                attrs,
                GenAIAttributes.REQUEST_MODEL,
                GenAIAttributes.RESPONSE_MODEL,
                OpenInferenceAttributes.MODEL_NAME,
            )
            tokens_in = cost_data.get("input_tokens")
            if tokens_in is None:
                tokens_in = first_int(
                    attrs,
                    GenAIAttributes.USAGE_INPUT_TOKENS,
                    OpenInferenceAttributes.TOKEN_COUNT_PROMPT,
                )
            tokens_out = cost_data.get("output_tokens")
            if tokens_out is None:
                tokens_out = first_int(
                    attrs,
                    GenAIAttributes.USAGE_OUTPUT_TOKENS,
                    OpenInferenceAttributes.TOKEN_COUNT_COMPLETION,
                )
            cache_read_tokens = cost_data.get("cache_read_tokens")
            if cache_read_tokens is None:
                cache_read_tokens = first_int(attrs, GenAIAttributes.USAGE_CACHE_READ)

            event: LumenAIEvent = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                # LumenAI keys first, then the OTel GenAI equivalents.
                "session_id": first_str(
                    attrs, LumenAIAttributes.SESSION_ID, GenAIAttributes.CONVERSATION_ID
                ),
                "agent_id": first_str(attrs, LumenAIAttributes.AGENT_ID, GenAIAttributes.AGENT_ID),
                "trace_id": format(span.context.trace_id, "032x") if span.context else "",
                "span_id": format(span.context.span_id, "016x") if span.context else "",
                "timestamp": _span_timestamp(span),
                "event_type": _span_to_event_type(span),
                "severity": Severity.ERROR if error else Severity.INFO,
                "message": span.name or "",
                "duration_ms": _span_duration_ms(span),
                "is_error": error,
                # Cost data — zero if CostProcessor did not run or found no pricing
                "cost_usd": cost_data.get("cost_usd", 0.0),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cache_read_tokens": cache_read_tokens,
                # Model / tool metadata
                "model": model,
                "tool_name": first_str(attrs, GenAIAttributes.TOOL_NAME),
                "span_kind": first_str(attrs, OpenInferenceAttributes.SPAN_KIND),
            }

            exporter = self._runtime.exporter if self._runtime is not None else self._exporter
            if exporter:
                try:
                    exporter.export(tenant_id, event)
                    _incr("events_exported")
                except Exception:
                    _incr("export_errors")
                    logger.warning("Exporter raised on event export", exc_info=True)

            logger.debug(
                "LumenAI event: type=%s span='%s' tenant=%s cost=$%.6f error=%s",
                event["event_type"], span.name, tenant_id, event["cost_usd"], error,
            )

        except Exception:
            _incr("events_dropped")
            logger.warning("EventNormalizerProcessor.on_end failed silently", exc_info=True)

    def shutdown(self) -> None:
        if self._runtime is not None:
            self._runtime.shutdown_exporter()
        elif self._exporter:
            try:
                self._exporter.shutdown()
            except Exception:
                logger.debug("Exporter shutdown raised", exc_info=True)

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        """Flush buffered events in the exporter (e.g. AsyncRedisExporter)."""
        exporter = self._runtime.exporter if self._runtime is not None else self._exporter
        flush = getattr(exporter, "force_flush", None)
        if flush is None:  # duck-typed exporter without a flush hook
            return True
        try:
            return bool(flush(timeout_millis))
        except Exception:
            logger.warning("Exporter force_flush raised", exc_info=True)
            return False
