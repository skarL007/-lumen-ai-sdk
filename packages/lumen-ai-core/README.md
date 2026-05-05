# lumen-ai-core

Core package for the LumenAI SDK.

## Includes

- `LumenAI.init()` and `LumenAI.shutdown()`
- Tenant context helpers: `set_tenant_id`, `get_tenant_id`, `clear_tenant_id`, `lumen_tenant`
- OTel processors for tenant tagging, cost computation, and event normalization
- `RedisExporter` and `AsyncRedisExporter`
- `LumenAIEvent` typed event contract
- SQLAlchemy ORM models for downstream storage integrations

## Install

```bash
pip install lumen-ai-core
```

## Minimal Example

```python
from lumen_ai import LumenAI, lumen_tenant

LumenAI.init(redis_url="redis://localhost:6379/0")

with lumen_tenant("client-acme"):
    # Create OTel GenAI spans here.
    pass

LumenAI.shutdown()
```

See the repository README for the full demo and development gates.
