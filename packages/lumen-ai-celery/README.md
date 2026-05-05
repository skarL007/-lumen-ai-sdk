# lumen-ai-celery

Celery integration for LumenAI.

## Includes

- `CeleryInstrumentor`
- Signal-based instrumentation for `task_prerun`, `task_postrun`, and `task_failure`
- Tenant extraction from task keyword arguments when `tenant_id` is provided
- Task result metadata extraction for `tokens_in`, `tokens_out`, and `cost_usd`

## Install

```bash
pip install lumen-ai-celery
```

## Usage

```python
from lumen_ai import LumenAI
from lumen_ai_celery import CeleryInstrumentor

LumenAI.init(
    service_name="worker",
    redis_url="redis://localhost:6379/0",
    instrumentors=[CeleryInstrumentor()],
)
```

The integration observes task lifecycle spans without changing existing task bodies.
