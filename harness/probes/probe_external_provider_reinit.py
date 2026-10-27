"""Reproduce stale exporter behavior when adopting an external TracerProvider."""

from __future__ import annotations

import json

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from lumen_ai import LumenAI
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind


class CaptureExporter(BaseLumenAIExporter):
    def __init__(self, name: str) -> None:
        self.name = name
        self.events: list[dict] = []
        self.after_closed: list[dict] = []
        self.closed = False

    def export(self, tenant_id: str, event: dict) -> None:
        item = {"tenant_id": tenant_id, "event": event}
        if self.closed:
            self.after_closed.append(item)
        else:
            self.events.append(item)

    def shutdown(self) -> None:
        self.closed = True


def emit(name: str) -> None:
    tracer = trace.get_tracer("lumen-probe")
    with tracer.start_as_current_span(name) as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
        span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 100)
        span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 20)


def main() -> int:
    provider = TracerProvider()
    trace.set_tracer_provider(provider)

    first = CaptureExporter("first")
    second = CaptureExporter("second")

    LumenAI.init(service_name="probe", exporter=first, default_tenant="probe")
    emit("first-span")
    LumenAI.shutdown()

    LumenAI.init(service_name="probe", exporter=second, default_tenant="probe")
    emit("second-span")
    LumenAI.shutdown()

    result = {
        "probe": "external_provider_reinit",
        "status": "fail" if len(second.events) == 0 else "pass",
        "first_events_before_close": len(first.events),
        "first_events_after_close": len(first.after_closed),
        "second_events": len(second.events),
        "finding": (
            "Second init did not attach the new exporter to the adopted provider"
            if len(second.events) == 0
            else "Second init exported to the new exporter"
        ),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
