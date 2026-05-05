import json
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "lumen-ai-core", "src"),
)


def test_jsonl_exporter_writes_one_event_per_line(tmp_path):
    from lumen_ai.providers import JsonlExporter

    path = tmp_path / "events.jsonl"
    exporter = JsonlExporter(path)

    exporter.export(
        "acme",
        {
            "id": "event-1",
            "tenant_id": "acme",
            "event_type": "LLM_CALL_COMPLETED",
            "cost_usd": 0.123,
        },
    )
    exporter.export(
        "globex",
        {
            "id": "event-2",
            "tenant_id": "globex",
            "event_type": "LLM_CALL_FAILED",
            "is_error": True,
        },
    )
    exporter.shutdown()

    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["tenant_id"] == "acme"
    assert json.loads(lines[1])["tenant_id"] == "globex"


def test_jsonl_exporter_is_available_from_top_level():
    from lumen_ai import JsonlExporter

    assert JsonlExporter is not None
