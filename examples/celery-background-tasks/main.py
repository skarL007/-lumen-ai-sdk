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
    Background task that calls an LLM.
    LumenAI tracks cost automatically via Celery signal hooks.
    The CeleryInstrumentor propagates tenant context across task boundaries.
    """
    from lumen_ai.processors.tenant import set_tenant_id

    # Set tenant for this task execution
    set_tenant_id(tenant_id)

    # Your LLM call here (e.g., OpenAI, Anthropic, etc.)
    # The instrumentation captures tokens, model, and computes cost
    result = f"Summary of {len(text)} chars for {tenant_id}"

    return {"tenant": tenant_id, "summary": result}
