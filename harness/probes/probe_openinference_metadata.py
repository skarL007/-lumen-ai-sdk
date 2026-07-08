"""Check whether OpenInference-only spans preserve model and token metadata."""

from __future__ import annotations

import json

from opentelemetry import trace

from lumen_ai import LumenAI
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.semconv import OpenInferenceAttributes, SpanKind


class CaptureExporter(BaseLumenAIExporter):
    def __init__(self) -> None:
        self.events: list[dict] = []

    def export(self, tenant_id: str, event: dict) -> None:
        self.events.append(event)

    def shutdown(self) -> None:
        pass


def main() -> int:
    exporter = CaptureExporter()
    LumenAI.init(service_name="probe", exporter=exporter, default_tenant="probe")
    tracer = trace.get_tracer("lumen-probe")
    with tracer.start_as_current_span("openinference-only") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(OpenInferenceAttributes.MODEL_NAME, "gpt-4o-mini")
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_PROMPT, 1200)
        span.set_attribute(OpenInferenceAttributes.TOKEN_COUNT_COMPLETION, 300)
    LumenAI.shutdown()

    event = exporter.events[-1] if exporter.events else {}
    status = "fail" if not event.get("model") or event.get("tokens_in") == 0 else "pass"
    result = {
        "probe": "openinference_metadata",
        "status": status,
        "event_count": len(exporter.events),
        "observed_model": event.get("model", ""),
        "observed_tokens_in": event.get("tokens_in", 0),
        "observed_tokens_out": event.get("tokens_out", 0),
        "finding": (
            "OpenInference-only model/token attributes were not preserved"
            if status == "fail"
            else "OpenInference-only metadata was preserved"
        ),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
