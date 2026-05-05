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
from lumen_ai import LumenAI
from lumen_ai.processors.tenant import _current_tenant, set_tenant_id


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
        _current_tenant.reset(token)


@app.post("/chat")
async def chat(body: dict):
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        messages=[{"role": "user", "content": body["prompt"]}],
    )
    return {"reply": msg.content[0].text}
