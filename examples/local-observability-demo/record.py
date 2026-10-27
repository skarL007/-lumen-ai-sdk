"""
Record a real run of the 3-tenant scenario for the static dashboard.

The dashboard falls back to ``static/recorded-events.json`` when it is served
without the FastAPI backend (for example from a static host). This script
regenerates that file from the SDK itself, so the recording never drifts from
what LumenAI actually exports:

    python examples/local-observability-demo/record.py
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCENARIO_FILE = BASE_DIR.parent / "multi-tenant-cost-report" / "main.py"
OUTPUT = BASE_DIR / "static" / "recorded-events.json"


def record() -> dict:
    spec = importlib.util.spec_from_file_location("lumen_cost_report_scenario", SCENARIO_FILE)
    assert spec is not None and spec.loader is not None
    scenario = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scenario)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        with scenario.lumen_session(path) as tracer:
            scenario.run_workload(tracer)
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    return {
        "recorded_with": f"lumen-ai-sdk {version('lumen-ai-sdk')}",
        "scenario": "examples/multi-tenant-cost-report",
        "events": events,
    }


def main() -> int:
    payload = record()
    OUTPUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"{len(payload['events'])} events -> {OUTPUT.relative_to(BASE_DIR.parents[1]).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
