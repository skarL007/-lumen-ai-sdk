# lumen-ai-openlit

OpenLIT bridge for LumenAI.

## Includes

- `OpenLITBridge`
- Defensive `openlit.init()` argument detection for OpenLIT API compatibility
- Optional forwarding of `tracer_provider`, `collect_gpu_stats`, `disable_batch`, and `pricing_json`

## Install

```bash
pip install lumen-ai-openlit
```

## Usage

```python
from lumen_ai import LumenAI
from lumen_ai_openlit import OpenLITBridge

LumenAI.init(
    service_name="ai-app",
    redis_url="redis://localhost:6379/0",
    instrumentors=[OpenLITBridge()],
)
```

OpenLIT creates provider spans; LumenAI enriches and exports the normalized metadata events.
