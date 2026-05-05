import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MAIN = ROOT / "examples" / "jsonl-smoke" / "main.py"
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src"


def test_jsonl_smoke_example_writes_metadata_event(tmp_path):
    output = tmp_path / "events.jsonl"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(CORE_SRC), env.get("PYTHONPATH", "")) if path
    )

    result = subprocess.run(
        [sys.executable, str(EXAMPLE_MAIN), "--output", str(output)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Wrote 1 event" in result.stdout

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["tenant_id"] == "portfolio-acme"
    assert event["model"] == "gpt-4o-mini"
    assert event["tokens_in"] == 1200
    assert event["tokens_out"] == 300
    assert event["cost_usd"] > 0

    serialized = json.dumps(event).lower()
    assert "prompt" not in serialized
    assert "completion" not in serialized
    assert "tool_args" not in serialized
    assert "raw_request" not in serialized
