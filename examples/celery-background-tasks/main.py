"""
LumenAI + Celery - track AI costs in background tasks.

Prerequisites:
    pip install lumen-ai-core lumen-ai-celery redis celery

Start Redis:
    docker run -d -p 6379:6379 redis:7

Start worker:
    celery -A main worker -l info --pool=solo

Trigger task:
    python -c "from main import summarize; summarize.delay('client-acme', 'Long document text...')"
"""
from celery import Celery
from lumen_ai import LumenAI
from lumen_ai_celery import CeleryInstrumentor

# 1. Standard Celery app
app = Celery("tasks", broker="redis://localhost:6379/0")

# 2. Initialize LumenAI with Celery instrumentor
LumenAI.init(
    service_name="celery-ai-worker",
    default_tenant="system",
    redis_url="redis://localhost:6379/0",
    instrumentors=[CeleryInstrumentor()],
)


@app.task(name="tasks.summarize")
def summarize(tenant_id: str, text: str) -> dict:
    """
    Background task that (here) simulates an LLM call.

    The CeleryInstrumentor already opens a CHAIN span for the task. We open a
    child LLM span carrying the model and token usage so the cost processor
    computes USD. ``lumen_tenant`` sets the tenant for this execution and ALWAYS
    resets it on exit — using a bare ``set_tenant_id`` would leak the tenant into
    the next task that runs on the same (reused) worker thread.
    """
    from lumen_ai import lumen_tenant
    from lumen_ai.schema.semconv import (
        GenAIAttributes,
        OpenInferenceAttributes,
        SpanKind,
    )
    from opentelemetry import trace

    tracer = trace.get_tracer("celery-ai-worker")
    with lumen_tenant(tenant_id):
        with tracer.start_as_current_span("summarize.llm") as span:
            span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
            span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, "claude-haiku-4-5")
            # Replace with real usage from your LLM client response:
            tokens_in = len(text.split())
            tokens_out = max(1, tokens_in // 4)
            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, tokens_in)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, tokens_out)
            result = f"Summary of {len(text)} chars for {tenant_id}"

    return {
        "tenant": tenant_id,
        "summary": result,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
