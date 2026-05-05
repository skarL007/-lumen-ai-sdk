import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DEMO_MAIN = ROOT / "examples" / "local-observability-demo" / "main.py"
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src"

sys.path.insert(0, str(CORE_SRC))


def _load_demo_module():
    spec = importlib.util.spec_from_file_location("lumen_local_observability_demo", DEMO_MAIN)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_demo_serves_dashboard_from_root():
    module = _load_demo_module()
    client = TestClient(module.app)

    response = client.get("/")

    assert response.status_code == 200
    assert "LumenAI Local Observability" in response.text
    assert 'id="tenant-input"' in response.text
    assert 'id="fail-input"' in response.text


def test_local_demo_serves_static_app_bundle():
    module = _load_demo_module()
    client = TestClient(module.app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "refreshEvents" in response.text
