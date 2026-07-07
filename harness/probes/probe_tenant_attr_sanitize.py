"""Check whether tenant span attributes are sanitized before export."""

from __future__ import annotations

import json

from opentelemetry import trace

from lumen_ai import LumenAI
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.semconv import GenAIAttributes, LumenAIAttributes, OpenInferenceAttributes, SpanKind


class CaptureExporter(BaseLumenAIExporter):
    def __init__(self) -> None:
        self.events: list[dict] = []

    def export(self, tenant_id: str, event: dict) -> None:
        self.events.append({"tenant_id": tenant_id, "event": event})

    def shutdown(self) -> None:
        pass


def main() -> int:
    exporter = CaptureExporter()
    raw_tenant = "ac\nme\t"
    LumenAI.init(service_name="probe", exporter=exporter, default_tenant="default")
    tracer = trace.get_tracer("lumen-probe")
    with tracer.start_as_current_span("tenant-attr") as span:
        span.set_attribute(LumenAIAttributes.TENANT_ID, raw_tenant)
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
        span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 10)
        span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 2)
    LumenAI.shutdown()

    observed = exporter.events[-1]["tenant_id"] if exporter.events else ""
    status = "fail" if "\n" in observed or "\t" in observed else "pass"
    result = {
        "probe": "tenant_attr_sanitize",
        "status": status,
        "raw_tenant_repr": repr(raw_tenant),
        "observed_tenant_repr": repr(observed),
        "event_count": len(exporter.events),
        "finding": (
            "Tenant from span attribute reached exporter without public-helper sanitization"
            if status == "fail"
            else "Tenant span attribute was sanitized"
        ),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

