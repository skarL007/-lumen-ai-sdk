import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples" / "local-observability-demo"
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src"

sys.path.insert(0, str(CORE_SRC))

# The README scenario, per tenant (USD).
EXPECTED = {"globex-legal": 0.174, "initech": 0.0144, "acme-health": 0.0016}
CONTENT_KEYS = ("prompt", "completion", "input.value", "output.value", "messages")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _costs(events: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for event in events:
        totals[event["tenant_id"]] += event["cost_usd"]
    return {tenant: round(cost, 6) for tenant, cost in totals.items()}


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("LUMEN_DEMO_EVENTS", str(tmp_path / "events.jsonl"))
    return _load("lumen_local_observability_demo", DEMO_DIR / "main.py")


def test_dashboard_is_served_from_root(demo):
    response = TestClient(demo.app).get("/")

    assert response.status_code == 200
    assert "LumenAI" in response.text
    assert 'id="run-scenario"' in response.text
    assert 'src="static/app.js"' in response.text


def test_static_bundle_talks_to_the_api(demo):
    response = TestClient(demo.app).get("/static/app.js")

    assert response.status_code == 200
    assert "api/scenario" in response.text
    assert "recorded-events.json" in response.text


def test_health_reports_the_jsonl_exporter_without_redis(demo):
    with TestClient(demo.app) as client:
        body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["exporter"] == "jsonl"


def test_scenario_reproduces_the_readme_totals(demo):
    with TestClient(demo.app) as client:
        assert client.post("/api/scenario").json()["events"] == 11
        events = client.get("/api/events").json()["events"]

    assert _costs(events) == EXPECTED
    assert round(sum(EXPECTED.values()), 6) == 0.19
    crossing = next(event for event in events if event["message"] == "support.async_followup")
    assert crossing["tenant_id"] == "acme-health"
    assert not [key for event in events for key in CONTENT_KEYS if key in event]


def test_scenario_twice_does_not_double_count(demo):
    with TestClient(demo.app) as client:
        client.post("/api/scenario")
        client.post("/api/scenario")
        events = client.get("/api/events").json()["events"]

    assert len(events) == 11
    assert _costs(events) == EXPECTED


def test_simulate_then_reset(demo):
    with TestClient(demo.app) as client:
        response = client.post(
            "/api/simulate",
            json={"tenant_id": "t-1", "model": "claude-sonnet-4-6", "input_tokens": 40_000,
                  "output_tokens": 2_000, "cache_read_tokens": 30_000},
        )
        assert response.status_code == 200
        legacy = client.get("/events/t-1").json()["events"]
        assert len(legacy) == 1
        assert legacy[0]["cost_usd"] == pytest.approx(0.159)
        assert legacy[0]["cache_read_tokens"] == 30_000

        client.post("/api/reset")
        assert client.get("/api/events").json()["events"] == []


def test_simulate_rejects_models_outside_the_pricing_table(demo):
    with TestClient(demo.app) as client:
        response = client.post("/api/simulate", json={"model": "made-up-model"})

    assert response.status_code == 422


def test_models_skip_anthropic_aliases(demo):
    with TestClient(demo.app) as client:
        ids = [model["id"] for model in client.get("/api/models").json()["models"]]

    assert "claude-sonnet-4-6" in ids
    assert not [model for model in ids if model.startswith("anthropic/")]


@pytest.fixture
def per_request_demo(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("LUMEN_DEMO_STORE", "memory")
    return _load("lumen_demo_per_request", DEMO_DIR / "main.py")


def test_per_request_scenario_returns_its_events_and_keeps_none(per_request_demo):
    with TestClient(per_request_demo.app) as client:
        health = client.get("/api/health").json()
        body = client.post("/api/scenario").json()
        stored = client.get("/api/events").json()["events"]

    assert health["exporter"] == "memory"
    assert health["per_request"] is True
    assert body["events"] == len(body["produced"]) == 11
    assert _costs(body["produced"]) == EXPECTED
    assert not [key for event in body["produced"] for key in CONTENT_KEYS if key in event]
    assert stored == []


def test_per_request_simulate_returns_only_its_own_event(per_request_demo):
    span = {"tenant_id": "t-1", "model": "claude-sonnet-4-6", "input_tokens": 40_000,
            "output_tokens": 2_000, "cache_read_tokens": 30_000}
    with TestClient(per_request_demo.app) as client:
        client.post("/api/scenario")
        first = client.post("/api/simulate", json=span).json()["produced"]
        second = client.post("/api/simulate", json={**span, "tenant_id": "t-2"}).json()["produced"]

    assert [event["tenant_id"] for event in first] == ["t-1"]
    assert first[0]["cost_usd"] == pytest.approx(0.159)
    assert [event["tenant_id"] for event in second] == ["t-2"]


def test_vercel_entry_serves_the_per_request_store(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "main", raising=False)
    had_store = "LUMEN_DEMO_STORE" in os.environ
    monkeypatch.delenv("LUMEN_DEMO_STORE", raising=False)
    try:
        entry = _load("lumen_demo_vercel_entry", DEMO_DIR / "vercel_app.py")
        with TestClient(entry.app) as client:
            assert client.get("/api/health").json()["exporter"] == "memory"
            assert client.get("/").status_code == 200
            assert client.get("/static/app.js").status_code == 200
    finally:
        sys.modules.pop("main", None)
        if not had_store:
            os.environ.pop("LUMEN_DEMO_STORE", None)


def test_recording_matches_a_fresh_run():
    recorder = _load("lumen_demo_recorder", DEMO_DIR / "record.py")
    recorded = json.loads((DEMO_DIR / "static" / "recorded-events.json").read_text(encoding="utf-8"))
    fresh = recorder.record()

    assert _costs(recorded["events"]) == _costs(fresh["events"]) == EXPECTED
    assert [e["message"] for e in recorded["events"]] == [e["message"] for e in fresh["events"]]
