"""
LumenAI — custom exporter example.

Shows how to write your own exporter to send events to any sink
(PostgreSQL, ClickHouse, Kafka, file, HTTP endpoint, etc.).

Usage:
    pip install lumen-ai-core
    python main.py
"""
import json
from pathlib import Path
from lumen_ai import LumenAI
from lumen_ai.providers import BaseLumenAIExporter


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
        Must never raise — exceptions break the OTel pipeline.
        """
        try:
            line = json.dumps(event, default=str)
            self._file.write(line + "\n")
            self._file.flush()
        except Exception:
            pass  # Silent failure — OTel pipeline must not break

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

print(f"Events will be written to: {exporter._path.resolve()}")
print("Make some LLM calls, then check the file.")

LumenAI.shutdown()
