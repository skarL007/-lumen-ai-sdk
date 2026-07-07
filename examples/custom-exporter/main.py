"""
LumenAI - custom exporter example.

Shows how to write your own exporter to send events to any sink
(PostgreSQL, ClickHouse, Kafka, file, HTTP endpoint, etc.).
For built-in local JSONL output, prefer `JsonlExporter`.

Usage:
    pip install lumen-ai-core
    python main.py
"""
import json
from pathlib import Path

from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.providers import BaseLumenAIExporter
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind
from opentelemetry import trace


class JSONFileExporter(BaseLumenAIExporter):
    """
    Writes events to a JSONL file, one line per event.

    This is a minimal example. For production, consider:
    - Buffering writes (like AsyncRedisExporter does)
    - Rotating files by date or size
    - Async I/O
    """

    def __init__(self, path: str = "lumenai_events.jsonl"):
        self._path = Path(path)
        self._file = open(self._path, "a", encoding="utf-8")

    def export(self, tenant_id: str, event: dict) -> None:
        """
        Called by EventNormalizerProcessor for every span.
        Must never raise; exceptions break the OTel pipeline.
        """
        try:
            line = json.dumps(event, default=str)
            self._file.write(line + "\n")
            self._file.flush()
        except Exception:
            pass  # Silent failure; OTel pipeline must not break

    def shutdown(self) -> None:
        self._file.close()


# Usage
exporter = JSONFileExporter("./events.jsonl")

LumenAI.init(
    service_name="custom-exporter-demo",
    default_tenant="demo",
    exporter=exporter,  # Pass your exporter instead of redis_url
)

# ... your LLM calls here ...
# Every span will be written to events.jsonl
tracer = trace.get_tracer("custom-exporter-demo")
with lumen_tenant("client-acme"):
    with tracer.start_as_current_span("synthetic.llm") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
        span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 1200)
        span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 300)

print(f"Events will be written to: {exporter._path.resolve()}")
print("Wrote one synthetic LLM span. Check the file for the normalized event.")

LumenAI.shutdown()
