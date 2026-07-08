"""
LumenAI Quickstart - FastAPI + Anthropic with real-time cost tracking.

Run:
    docker compose up
    curl -X POST http://localhost:8000/chat \
      -H "X-Tenant-ID: acme-corp" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "Hello!"}'
"""
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from lumen_ai import LumenAI, reset_tenant_id, set_tenant_id
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind
from opentelemetry import trace


@asynccontextmanager
async def lifespan(app: FastAPI):
    LumenAI.init(
        service_name="quickstart",
        redis_url="redis://redis:6379/0",
    )
    yield
    LumenAI.shutdown()


app = FastAPI(title="LumenAI Quickstart", lifespan=lifespan)


@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    tenant_id = request.headers.get("X-Tenant-ID", "anonymous")
    token = set_tenant_id(tenant_id)
    try:
        return await call_next(request)
    finally:
        reset_tenant_id(token)


@app.post("/chat")
async def chat(body: dict):
    # Wrap the model call in a span so LumenAI's processors attribute the cost to
    # the tenant set by the middleware. Without a span there is nothing to observe.
    tracer = trace.get_tracer("lumen-ai.quickstart")
    client = anthropic.Anthropic()
    with tracer.start_as_current_span("anthropic.messages.create") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
        span.set_attribute(GenAIAttributes.PROVIDER_NAME, "anthropic")
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "claude-haiku-4-5")
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            messages=[{"role": "user", "content": body["prompt"]}],
        )
        usage = getattr(msg, "usage", None)
        if usage is not None:
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, getattr(usage, "input_tokens", 0))
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, getattr(usage, "output_tokens", 0))
        return {"reply": msg.content[0].text}
