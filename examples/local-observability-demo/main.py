import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover - exercised through _redis_client
    redis = None

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.schema.semconv import (
    GenAIAttributes,
    LumenAIAttributes,
    OpenInferenceAttributes,
    SpanKind,
)
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_PREFIX = "LumenAI:events"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class SimulateRequest(BaseModel):
    tenant_id: str = Field(default="acme", min_length=1)
    model: Literal["gpt-4o-mini", "claude-haiku-4-5", "google/gemini-2.5-flash"] = "gpt-4o-mini"
    input_tokens: int = Field(default=1200, ge=0)
    output_tokens: int = Field(default=300, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=18, ge=0, le=500)
    fail: bool = False


SCENARIO_REQUESTS = (
    SimulateRequest(tenant_id="acme", model="gpt-4o-mini", input_tokens=1200, output_tokens=300, latency_ms=18),
    SimulateRequest(tenant_id="acme", model="claude-haiku-4-5", input_tokens=850, output_tokens=220, cache_read_tokens=400, latency_ms=27),
    SimulateRequest(tenant_id="acme", model="google/gemini-2.5-flash", input_tokens=2100, output_tokens=640, latency_ms=42, fail=True),
    SimulateRequest(tenant_id="globex", model="gpt-4o-mini", input_tokens=520, output_tokens=160, latency_ms=12),
    SimulateRequest(tenant_id="globex", model="google/gemini-2.5-flash", input_tokens=1800, output_tokens=420, cache_read_tokens=250, latency_ms=34),
    SimulateRequest(tenant_id="umbrella", model="claude-haiku-4-5", input_tokens=3300, output_tokens=760, latency_ms=58),
    SimulateRequest(tenant_id="umbrella", model="gpt-4o-mini", input_tokens=720, output_tokens=180, cache_read_tokens=120, latency_ms=22),
)


def _redis_client():
    if redis is None:
        raise RuntimeError("redis package is not installed")
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def _stream_key(tenant_id: str) -> str:
    return f"{STREAM_PREFIX}:{tenant_id}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    LumenAI.init(
        service_name="lumen-local-demo",
        redis_url=REDIS_URL,
        default_tenant="anonymous",
    )
    yield
    LumenAI.shutdown()


app = FastAPI(title="LumenAI Local Observability Demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health(response: Response) -> dict[str, str]:
    client = _redis_client()
    try:
        client.ping()
    except Exception as exc:
        response.status_code = 503
        return {"status": "degraded", "redis": "unavailable", "error": str(exc)}
    finally:
        client.close()

    return {"status": "ok", "redis": "ok"}


def _emit_demo_span(request: SimulateRequest) -> dict[str, object]:
    tracer = trace.get_tracer("lumen-ai.local-demo")

    with lumen_tenant(request.tenant_id):
        with tracer.start_as_current_span("demo.synthetic_llm_call") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, request.model)
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, request.input_tokens)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, request.output_tokens)
            span.set_attribute(GenAIAttributes.USAGE_CACHE_READ, request.cache_read_tokens)
            span.set_attribute(LumenAIAttributes.AGENT_ID, "demo-support-agent")
            span.set_attribute(LumenAIAttributes.SESSION_ID, "demo-local-session")

            if request.fail:
                span.set_status(Status(StatusCode.ERROR, "simulated failure"))

            if request.latency_ms:
                time.sleep(request.latency_ms / 1000)

    return {
        "tenant_id": request.tenant_id,
        "model": request.model,
        "input_tokens": request.input_tokens,
        "output_tokens": request.output_tokens,
        "cache_read_tokens": request.cache_read_tokens,
        "latency_ms": request.latency_ms,
        "failed": request.fail,
        "redis_stream": _stream_key(request.tenant_id),
    }


@app.post("/simulate")
def simulate(request: SimulateRequest) -> dict[str, object]:
    return _emit_demo_span(request)


@app.post("/scenario")
def scenario() -> dict[str, object]:
    events = [_emit_demo_span(request) for request in SCENARIO_REQUESTS]
    tenants = sorted({event["tenant_id"] for event in events})
    return {"events_created": len(events), "tenants": tenants, "events": events}


def _parse_entries(entries) -> list[dict[str, object]]:
    parsed = []
    for _, fields in entries:
        data = fields.get("data")
        if not data:
            continue
        try:
            parsed.append(json.loads(data))
        except json.JSONDecodeError:
            continue
    return parsed


def _events_for_tenant(tenant_id: str, limit: int | None = None) -> list[dict[str, object]]:
    client = _redis_client()
    try:
        entries = client.xrevrange(_stream_key(tenant_id), count=limit)
    finally:
        client.close()
    return _parse_entries(entries)


@app.get("/events/{tenant_id}")
def events(tenant_id: str, limit: int = 10) -> dict[str, object]:
    event_items = _events_for_tenant(tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "stream": _stream_key(tenant_id),
        "events": event_items,
    }


@app.get("/stats/{tenant_id}")
def stats(tenant_id: str) -> dict[str, object]:
    event_items = _events_for_tenant(tenant_id)
    total_cost = sum(float(event.get("cost_usd") or 0) for event in event_items)
    tokens = sum(int(event.get("tokens_in") or 0) + int(event.get("tokens_out") or 0) for event in event_items)
    cache_read_tokens = sum(int(event.get("cache_read_tokens") or 0) for event in event_items)
    errors = sum(1 for event in event_items if event.get("is_error"))

    return {
        "tenant_id": tenant_id,
        "stream": _stream_key(tenant_id),
        "events": len(event_items),
        "cost_usd": round(total_cost, 8),
        "tokens": tokens,
        "cache_read_tokens": cache_read_tokens,
        "errors": errors,
    }


@app.delete("/events/{tenant_id}")
def reset_tenant(tenant_id: str) -> dict[str, object]:
    client = _redis_client()
    try:
        deleted = client.delete(_stream_key(tenant_id))
    finally:
        client.close()
    return {"tenant_id": tenant_id, "deleted_streams": int(deleted)}


@app.delete("/events")
def reset_all() -> dict[str, object]:
    client = _redis_client()
    try:
        keys = list(client.keys(f"{STREAM_PREFIX}:*"))
        deleted = client.delete(*keys) if keys else 0
    finally:
        client.close()
    return {"deleted_streams": int(deleted)}
