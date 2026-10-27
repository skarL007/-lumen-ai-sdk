"""
LumenAI local demo dashboard: FastAPI in front of the real processor chain.

No Docker, Redis or API key is needed. Events go to a JSON Lines file by
default; set ``REDIS_URL`` to store them in Redis Streams instead (the
docker-compose file does that).

    pip install -e packages/lumen-ai-core fastapi uvicorn
    uvicorn main:app --app-dir examples/local-observability-demo

Open http://localhost:8000 and press "Run the 3-tenant scenario". It replays
the workload from ``examples/multi-tenant-cost-report`` through LumenAI, so the
dashboard shows the same $0.190000 total as the README.
"""

from __future__ import annotations

import importlib.util
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from lumen_ai import JsonlExporter, LumenAI, lumen_tenant
from lumen_ai.schema.semconv import (
    PRICING_TABLE,
    GenAIAttributes,
    OpenInferenceAttributes,
    SpanKind,
)
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
SCENARIO_FILE = BASE_DIR.parent / "multi-tenant-cost-report" / "main.py"
STREAM_PREFIX = "LumenAI:events"
SERVICE_NAME = "lumen-local-demo"


class JsonlStore:
    """Events in an append-only JSON Lines file, read back for the dashboard."""

    mode = "jsonl"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def init_kwargs(self) -> dict[str, Any]:
        return {"exporter": JsonlExporter(self.path)}

    def events(self, tenant: Optional[str], limit: int) -> list[dict[str, Any]]:
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a line still being written
        if tenant:
            rows = [row for row in rows if row.get("tenant_id") == tenant]
        return rows[-limit:]

    def reset(self) -> None:
        # The exporter keeps its append handle; appends land at the new end.
        self.path.write_text("", encoding="utf-8")

    def describe(self) -> str:
        return self.path.as_posix()


class RedisStore:
    """Events in tenant-scoped Redis Streams: ``LumenAI:events:{tenant_id}``."""

    mode = "redis"

    def __init__(self, url: str) -> None:
        import redis

        self.url = url
        self.client = redis.Redis.from_url(url, decode_responses=True)

    def init_kwargs(self) -> dict[str, Any]:
        return {"redis_url": self.url}

    def _keys(self, tenant: Optional[str]) -> list[str]:
        if tenant:
            return [f"{STREAM_PREFIX}:{tenant}"]
        return list(self.client.scan_iter(f"{STREAM_PREFIX}:*"))

    def events(self, tenant: Optional[str], limit: int) -> list[dict[str, Any]]:
        rows = []
        for key in self._keys(tenant):
            for _, fields in self.client.xrevrange(key, count=limit):
                rows.append(json.loads(fields["data"]))
        rows.sort(key=lambda row: row.get("timestamp", ""))
        return rows[-limit:]

    def reset(self) -> None:
        keys = self._keys(None)
        if keys:
            self.client.delete(*keys)

    def describe(self) -> str:
        return f"{STREAM_PREFIX}:{{tenant_id}}"


def _make_store() -> JsonlStore | RedisStore:
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        return RedisStore(redis_url)
    default = BASE_DIR / ".runtime" / "events.jsonl"
    return JsonlStore(Path(os.getenv("LUMEN_DEMO_EVENTS", default)))


def _load_scenario() -> ModuleType:
    """Import the README demo's workload so both demos stay one source of truth."""
    spec = importlib.util.spec_from_file_location("lumen_cost_report_scenario", SCENARIO_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Scenario not found: {SCENARIO_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


store = _make_store()
scenario = _load_scenario()
_write_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # genai_only: FastAPI emits its own request spans; keep them out of the cost stream.
    LumenAI.init(
        service_name=SERVICE_NAME, default_tenant="anonymous", genai_only=True, **store.init_kwargs()
    )
    yield
    LumenAI.shutdown()


app = FastAPI(title="LumenAI Local Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SimulateRequest(BaseModel):
    tenant_id: str = Field(default="acme", min_length=1, max_length=64)
    model: str = "gpt-4o-mini"
    input_tokens: int = Field(default=1200, ge=0, le=10_000_000)
    output_tokens: int = Field(default=300, ge=0, le=10_000_000)
    cache_read_tokens: int = Field(default=0, ge=0, le=10_000_000)
    fail: bool = False

    @field_validator("model")
    @classmethod
    def known_model(cls, value: str) -> str:
        if value not in PRICING_TABLE:
            raise ValueError("model must be one of /api/models")
        return value


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "exporter": store.mode, "store": store.describe()}


@app.get("/api/models")
def models() -> dict[str, list[dict[str, Any]]]:
    return {
        "models": [
            {"id": name, "usd_per_million": prices}
            for name, prices in sorted(PRICING_TABLE.items())
            if not name.startswith("anthropic/")  # aliases of the bare claude-* names
        ]
    }


@app.get("/api/events")
def events(
    tenant: Optional[str] = None, limit: int = Query(default=500, ge=1, le=5000)
) -> dict[str, Any]:
    return {"exporter": store.mode, "events": store.events(tenant, limit)}


@app.post("/api/scenario")
def run_scenario() -> dict[str, Any]:
    """Clear the store, then replay the README workload so totals reproduce."""
    with _write_lock:
        store.reset()
        scenario.run_workload(trace.get_tracer(SERVICE_NAME))
    return {"exporter": store.mode, "events": len(store.events(None, 5000))}


@app.post("/api/simulate")
def simulate(request: SimulateRequest) -> dict[str, Any]:
    tracer = trace.get_tracer(SERVICE_NAME)
    with _write_lock, lumen_tenant(request.tenant_id):
        with tracer.start_as_current_span("demo.custom_llm_call") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, request.model)
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, request.input_tokens)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, request.output_tokens)
            span.set_attribute(GenAIAttributes.USAGE_CACHE_READ, request.cache_read_tokens)
            if request.fail:
                span.set_status(Status(StatusCode.ERROR, "simulated failure"))
    return {"accepted": True, **request.model_dump()}


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    with _write_lock:
        store.reset()
    return {"exporter": store.mode, "events": 0}


# The paths below predate the dashboard redesign and stay for the curl examples.
@app.get("/health", include_in_schema=False)
def legacy_health() -> dict[str, str]:
    return health()


@app.post("/simulate", include_in_schema=False)
def legacy_simulate(request: SimulateRequest) -> dict[str, Any]:
    return simulate(request)


@app.get("/events/{tenant_id}", include_in_schema=False)
def legacy_events(tenant_id: str, limit: int = Query(default=10, ge=1, le=5000)) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "events": store.events(tenant_id, limit)[::-1]}
