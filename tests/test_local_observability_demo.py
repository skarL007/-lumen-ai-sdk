import importlib.util
import json
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
    assert 'id="scenario-button"' in response.text
    assert 'id="reset-button"' in response.text
    assert 'id="stream-name"' in response.text


def test_local_demo_serves_static_app_bundle():
    module = _load_demo_module()
    client = TestClient(module.app)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "refreshEvents" in response.text
    assert "runScenario" in response.text
    assert "refreshStats" in response.text
    assert "resetTenant" in response.text
    assert "trace_id" in response.text


class FakeRedis:
    def __init__(self, fail_ping: bool = False):
        self.fail_ping = fail_ping
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.closed = False

    def ping(self):
        if self.fail_ping:
            raise RuntimeError("redis down")
        return True

    def xadd(self, key, fields, maxlen=None):
        entries = self.streams.setdefault(key, [])
        entries.append((f"{len(entries)}-0", fields))

    def xrevrange(self, key, count=None):
        entries = list(reversed(self.streams.get(key, [])))
        return entries if count is None else entries[:count]

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.streams:
                deleted += 1
                del self.streams[key]
        return deleted

    def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [key for key in self.streams if key.startswith(prefix)]

    def close(self):
        self.closed = True


def test_local_demo_health_reports_redis_status(monkeypatch):
    module = _load_demo_module()
    fake = FakeRedis()
    monkeypatch.setattr(module, "_redis_client", lambda: fake)
    client = TestClient(module.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "ok"}


def test_local_demo_health_reports_redis_unavailable(monkeypatch):
    module = _load_demo_module()
    fake = FakeRedis(fail_ping=True)
    monkeypatch.setattr(module, "_redis_client", lambda: fake)
    client = TestClient(module.app)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["redis"] == "unavailable"


def test_local_demo_scenario_stats_and_reset(monkeypatch):
    module = _load_demo_module()
    fake = FakeRedis()
    monkeypatch.setattr(module, "_redis_client", lambda: fake)

    def fake_emit(request):
        event = {
            "tenant_id": request.tenant_id,
            "model": request.model,
            "tokens_in": request.input_tokens,
            "tokens_out": request.output_tokens,
            "cache_read_tokens": request.cache_read_tokens,
            "cost_usd": 0.001,
            "duration_ms": request.latency_ms,
            "is_error": request.fail,
            "event_type": "LLM_CALL_FAILED" if request.fail else "LLM_CALL_COMPLETED",
            "severity": "ERROR" if request.fail else "INFO",
            "trace_id": "trace",
            "span_id": "span",
        }
        fake.xadd(
            f"{module.STREAM_PREFIX}:{request.tenant_id}",
            {"data": json.dumps(event)},
            maxlen=10000,
        )
        return event

    monkeypatch.setattr(module, "_emit_demo_span", fake_emit)
    client = TestClient(module.app)

    scenario = client.post("/scenario")
    stats = client.get("/stats/acme")
    reset = client.delete("/events/acme")
    empty = client.get("/stats/acme")

    assert scenario.status_code == 200
    assert scenario.json()["events_created"] >= 6
    assert stats.status_code == 200
    assert stats.json()["events"] >= 2
    assert stats.json()["cost_usd"] > 0
    assert stats.json()["errors"] >= 1
    assert reset.status_code == 200
    assert reset.json()["deleted_streams"] == 1
    assert empty.json()["events"] == 0
