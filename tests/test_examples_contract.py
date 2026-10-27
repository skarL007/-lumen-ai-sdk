import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src"
EXAMPLES = [
    ROOT / "examples" / "fastapi-quickstart" / "main.py",
    ROOT / "examples" / "celery-background-tasks" / "main.py",
    ROOT / "examples" / "custom-exporter" / "main.py",
    ROOT / "examples" / "langchain-cost-tracking" / "main.py",
]


def test_examples_compile():
    for example in EXAMPLES:
        py_compile.compile(str(example), doraise=True)


def test_examples_use_public_api_contracts():
    fastapi = (ROOT / "examples" / "fastapi-quickstart" / "main.py").read_text(
        encoding="utf-8"
    )
    celery = (ROOT / "examples" / "celery-background-tasks" / "main.py").read_text(
        encoding="utf-8"
    )
    langchain = (ROOT / "examples" / "langchain-cost-tracking" / "main.py").read_text(
        encoding="utf-8"
    )

    assert "_current_tenant" not in fastapi
    assert "reset_tenant_id(token)" in fastapi
    assert "summarize.delay(tenant_id='client-acme', text='Long document text...')" in celery
    assert "OpenLITBridge" in langchain
    assert "instrumentors=[OpenLITBridge()]" in langchain


def test_custom_exporter_example_emits_synthetic_span(tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in (str(CORE_SRC), env.get("PYTHONPATH", "")) if path
    )

    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "custom-exporter" / "main.py")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1
    event = json.loads(events[0])
    assert event["tenant_id"] == "client-acme"
    assert event["model"] == "gpt-4o-mini"
    assert event["tokens_in"] == 1200
    assert event["tokens_out"] == 300
