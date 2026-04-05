"""
EventNormalizerProcessor — normalizes spans into canonical LumenAI events
and exports them via an injected BaseLumenAIExporter.

Must run LAST in the processor chain, after TenantSpanProcessor and
CostComputingSpanProcessor have written to their side-dicts.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from lumen_ai.processors.cost import get_span_cost_data
from lumen_ai.processors.tenant import get_span_tenant
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    LumenAIAttributes,
    OpenInferenceAttributes,
)
from lumen_ai.schema.event_types import EventType, Severity
from lumen_ai.providers import BaseLumenAIExporter

logger = logging.getLogger(__name__)


def _is_error(span: ReadableSpan) -> bool:
    """Return True if span ended in an error state."""
    status = span.status
    if status is None:
        return False
    # OTel StatusCode.ERROR = 2
    return getattr(status, "status_code", None) == 2 or (
        hasattr(status, "is_ok") and not status.is_ok
    )


def _span_to_event_type(span: ReadableSpan) -> str:
    """Infer canonical event type from span attributes and status."""
    attrs = span.attributes or {}
    span_kind = attrs.get(OpenInferenceAttributes.SPAN_KIND, "")
    op_name = attrs.get(GenAIAttributes.OPERATION_NAME, "")
    tool_name = attrs.get(GenAIAttributes.TOOL_NAME, "")
    error = _is_error(span)

    if span_kind == "TOOL" or tool_name:
        return EventType.TOOL_CALL_FAILED if error else EventType.TOOL_CALL_COMPLETED
    if span_kind == "LLM" or op_name in ("chat", "completion", "embedding"):
        return EventType.LLM_CALL_FAILED if error else EventType.LLM_CALL_COMPLETED
    if span_kind == "AGENT":
        return EventType.AGENT_FAILED if error else EventType.AGENT_COMPLETED
    if span_kind == "CHAIN":
        return EventType.TASK_FAILED if error else EventType.TASK_COMPLETED

    return EventType.AGENT_COMPLETED


def _span_duration_ms(span: ReadableSpan) -> int:
    if span.start_time and span.end_time:
        return int((span.end_time - span.start_time) / 1_000_000)
    return 0


class EventNormalizerProcessor(SpanProcessor):
    """
    Converts OTel spans into canonical LumenAI events and exports them.

    Args:
        exporter: Optional BaseLumenAIExporter. If None, events are only logged.
    """

    def __init__(self, exporter: Optional[BaseLumenAIExporter] = None) -> None:
        self._exporter = exporter

    def on_start(self, span, parent_context=None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = span.attributes or {}
            cost_data = get_span_cost_data(span)
            tenant_id = (
                get_span_tenant(span)
                or attrs.get(LumenAIAttributes.TENANT_ID, "")
                or "default"
            )
            error = _is_error(span)

            event = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "session_id": attrs.get(LumenAIAttributes.SESSION_ID, ""),
                "agent_id": attrs.get(LumenAIAttributes.AGENT_ID, ""),
                "trace_id": format(span.context.trace_id, "032x") if span.context else "",
                "span_id": format(span.context.span_id, "016x") if span.context else "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": _span_to_event_type(span),
                "severity": Severity.ERROR if error else Severity.INFO,
                "message": span.name or "",
                "duration_ms": _span_duration_ms(span),
                "is_error": error,
                # Cost data — zero if CostProcessor did not run or found no pricing
                "cost_usd": cost_data.get("cost_usd", 0.0),
                "tokens_in": cost_data.get("input_tokens", 0),
                "tokens_out": cost_data.get("output_tokens", 0),
                "cache_read_tokens": cost_data.get("cache_read_tokens", 0),
                # Model / tool metadata
                "model": cost_data.get("model") or attrs.get(GenAIAttributes.REQUEST_MODEL, ""),
                "tool_name": attrs.get(GenAIAttributes.TOOL_NAME, ""),
                "span_kind": attrs.get(OpenInferenceAttributes.SPAN_KIND, ""),
            }

            if self._exporter:
                try:
                    self._exporter.export(tenant_id, event)
                except Exception:
                    logger.warning("Exporter raised on event export", exc_info=True)

            logger.debug(
                "LumenAI event: type=%s span='%s' tenant=%s cost=$%.6f error=%s",
                event["event_type"], span.name, tenant_id, event["cost_usd"], error,
            )

        except Exception:
            logger.warning("EventNormalizerProcessor.on_end failed silently", exc_info=True)

    def shutdown(self) -> None:
        if self._exporter:
            try:
                self._exporter.shutdown()
            except Exception:
                logger.debug("Exporter shutdown raised", exc_info=True)

    def force_flush(self, timeout_millis: Optional[int] = None) -> bool:
        return True
