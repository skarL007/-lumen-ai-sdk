"""
The README's reproducible demo must be exactly what the script prints.

Runs examples/multi-tenant-cost-report in a subprocess (fresh OTel globals,
as a user would) and compares stdout with the fenced block between the
``demo-output`` markers in README.md, so the documented output cannot drift.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "multi-tenant-cost-report" / "main.py"
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src"
OUTPUT = ".runtime/cost-report.jsonl"


def _run(tmp_path: Path) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(CORE_SRC), env.get("PYTHONPATH", "")) if p
    )
    result = subprocess.run(
        [sys.executable, str(EXAMPLE), "--output", OUTPUT],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _readme_block() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- demo-output:start -->\s*```text\n(.*?)```\s*<!-- demo-output:end -->",
        readme,
        re.S,
    )
    assert match, "demo-output markers not found in README.md"
    return match.group(1)


def test_readme_demo_output_matches_script(tmp_path):
    assert _run(tmp_path) == _readme_block()


def test_demo_events_are_metadata_only_and_isolated(tmp_path):
    _run(tmp_path)
    events = [
        json.loads(line)
        for line in (tmp_path / OUTPUT).read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 11
    crossing = [e for e in events if e["message"] == "support.async_followup"]
    assert [e["tenant_id"] for e in crossing] == ["acme-health"]
    assert {e["tenant_id"] for e in events} == {"acme-health", "globex-legal", "initech"}
    serialized = json.dumps(events).lower()
    for marker in ("prompt", "completion", "messages", "input.value", "output.value"):
        assert marker not in serialized
