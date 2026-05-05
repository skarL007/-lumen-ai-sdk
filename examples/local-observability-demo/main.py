import json
import os
from contextlib import asynccontextmanager
from typing import Literal

import redis
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from lumen_ai import LumenAI, lumen_tenant
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
STREAM_PREFIX = "LumenAI:events"


class SimulateRequest(BaseModel):
    tenant_id: str = Field(default="acme", min_length=1)
    model: Literal["gpt-4o-mini", "claude-haiku-4-5", "google/gemini-2.5-flash"] = "gpt-4o-mini"
    input_tokens: int = Field(default=1200, ge=0)
    output_tokens: int = Field(default=300, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    fail: bool = False


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/simulate")
def simulate(request: SimulateRequest) -> dict[str, object]:
    tracer = trace.get_tracer("lumen-ai.local-demo")

    with lumen_tenant(request.tenant_id):
        with tracer.start_as_current_span("demo.synthetic_llm_call") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, request.model)
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, request.input_tokens)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, request.output_tokens)
            span.set_attribute(GenAIAttributes.USAGE_CACHE_READ, request.cache_read_tokens)

            if request.fail:
                span.set_status(Status(StatusCode.ERROR, "simulated failure"))

    return {
        "tenant_id": request.tenant_id,
        "model": request.model,
        "input_tokens": request.input_tokens,
        "output_tokens": request.output_tokens,
        "cache_read_tokens": request.cache_read_tokens,
        "redis_stream": f"{STREAM_PREFIX}:{request.tenant_id}",
    }


@app.get("/events/{tenant_id}")
def events(tenant_id: str, limit: int = 10) -> dict[str, object]:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        entries = client.xrevrange(f"{STREAM_PREFIX}:{tenant_id}", count=limit)
    finally:
        client.close()

    return {
        "tenant_id": tenant_id,
        "events": [json.loads(fields["data"]) for _, fields in entries],
    }
