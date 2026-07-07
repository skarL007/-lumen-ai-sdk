# LumenAI SDK

Real-time FinOps and multi-tenant observability for Generative AI workloads.

![LumenAI local observability dashboard](docs/assets/lumen-dashboard.png)

LumenAI is a Python OpenTelemetry extension that enriches GenAI spans with tenant attribution, token cost, normalized event metadata, and Redis Streams or JSONL delivery. It is designed for teams that need to understand which tenant, model, agent, or background job is driving AI cost without storing prompts or responses.

[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange?style=flat-square)](https://github.com/skarL007/-lumen-ai-sdk)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://www.python.org/)
[![CI](https://github.com/skarL007/-lumen-ai-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/skarL007/-lumen-ai-sdk/actions/workflows/ci.yml)

## What Works Today

- `lumen-ai-core`: OTel processor chain for tenant tagging, cost calculation, event normalization, Redis export, JSONL export, async Redis export, and typed public API.
- `lumen-ai-celery`: Celery signal instrumentor for task lifecycle spans without modifying task code.
- `lumen-ai-openlit`: OpenLIT bridge that passes the LumenAI tracer provider into OpenLIT auto-instrumentation.
- Redis integration tests, clean wheel/sdist build checks, package import checks, mypy on core, and blocking dependency audit in CI.
- Local demo with no paid API key: [examples/local-observability-demo](examples/local-observability-demo).

This project is still alpha. The core contracts are usable, but the API can still evolve before v1.0.

## Why This Matters In Production

1. Tenant cost attribution: SaaS teams can answer which customer caused a cost spike instead of seeing one shared LLM bill.
2. Spike detection: normalized metadata makes it possible to alert on model, latency, token, and error anomalies without parsing app logs.
3. Privacy-preserving audit trail: LumenAI exports metadata only. It does not export prompt text, completion text, tool arguments, or raw request bodies.

## Quick Start

PyPI may still lag the audited source version. Until `0.1.4` is published,
install from the repository or from a local checkout:

```bash
pip install "git+https://github.com/skarL007/-lumen-ai-sdk.git#subdirectory=packages/lumen-ai-core"
# or, inside this repository:
pip install -e packages/lumen-ai-core
```

Initialize once at application startup:

```python
from lumen_ai import LumenAI, lumen_tenant
from opentelemetry import trace
from lumen_ai.schema.semconv import GenAIAttributes, OpenInferenceAttributes, SpanKind

LumenAI.init(
    service_name="my-ai-app",
    redis_url="redis://localhost:6379/0",
    default_tenant="anonymous",
)

tracer = trace.get_tracer("my-ai-app")

with lumen_tenant("client-acme"):
    with tracer.start_as_current_span("llm.chat") as span:
        span.set_attribute(OpenInferenceAttributes.SPAN_KIND, SpanKind.LLM)
        span.set_attribute(GenAIAttributes.OPERATION_NAME, "chat")
        span.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
        span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, 1200)
        span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, 300)

LumenAI.shutdown()
```

The event is written to:

```text
LumenAI:events:client-acme
```

For local smoke tests or examples without Redis, use the JSONL exporter:

```python
from lumen_ai import JsonlExporter, LumenAI

LumenAI.init(
    service_name="my-ai-app",
    exporter=JsonlExporter("lumen-events.jsonl"),
    default_tenant="anonymous",
)
```

The smallest runnable example is [examples/jsonl-smoke](examples/jsonl-smoke).

## Local Demo

Run a real SDK demo without OpenAI, Anthropic, or other paid credentials:

```bash
cd examples/local-observability-demo
docker compose up --build
```

Open `http://localhost:8000` for the dashboard, or use the API directly:

```bash
curl -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"acme","model":"gpt-4o-mini","input_tokens":1200,"output_tokens":300}'

curl http://localhost:8000/events/acme
```

The old static visual simulation is kept as [lumen-simulation.html](lumen-simulation.html). It is a portfolio visual, not proof of SDK behavior.

## Public API

```python
from lumen_ai import (
    AsyncRedisExporter,
    JsonlExporter,
    LumenAI,
    LumenAIEvent,
    RedisExporter,
    clear_tenant_id,
    get_tenant_id,
    lumen_tenant,
    reset_tenant_id,
    set_tenant_id,
)
```

`LumenAIEvent` is a typed metadata-only event contract. Exporters receive `tenant_id` plus this normalized event object.

## Packages

| Package | Purpose |
|---|---|
| `lumen-ai-core` | Core OTel processors, pricing, exporters, typed event contract |
| `lumen-ai-celery` | Celery task lifecycle instrumentation |
| `lumen-ai-openlit` | OpenLIT bridge for provider auto-instrumentation |

## Development

```bash
pip install -e packages/lumen-ai-core
pip install -e packages/lumen-ai-celery
pip install -e packages/lumen-ai-openlit
pip install pytest pytest-cov fastapi httpx ruff mypy build twine pip-audit celery

python scripts/release_gate.py
```

The release gate runs tests, ruff, mypy, wheel/sdist builds, `twine check`,
clean wheel and sdist installs, `pip check`, and public import verification. To run individual gates:

```bash
python -m pytest tests -q
python -m ruff check packages/lumen-ai-core/src packages/lumen-ai-celery/src packages/lumen-ai-openlit/src --select E,F,W,I --ignore E501
python -m mypy packages/lumen-ai-core/src/lumen_ai --ignore-missing-imports --no-error-summary
python -m build packages/lumen-ai-core
python -m build packages/lumen-ai-celery
python -m build packages/lumen-ai-openlit
python -m twine check packages/*/dist/*
```

Performance benchmarks are opt-in because they depend on local machine load:

```bash
LUMEN_RUN_BENCHMARKS=1 python -m pytest tests/test_benchmark.py -v
```

The GitHub Actions `Benchmarks` workflow runs the same benchmark suite on demand and weekly, separate from the correctness CI.

## Roadmap

- v0.1.4: runtime lifecycle fixes, tenant sanitization, release hardening, and updated examples.
- v0.1.3: JSONL exporter, live dashboard screenshot, and benchmark workflow.
- v0.1.2: package hardening, typed event contract, honest docs, local no-key demo, clean install CI.
- v0.2: richer exporter examples, typed pricing provider contract, benchmark docs, OpenLIT compatibility matrix.
- v0.3: production dashboard example backed by Redis or ClickHouse.
- v1.0: stable public API, migration guide, security review, and production readiness checklist.

## Security Model

LumenAI reads OpenTelemetry metadata such as model names, token counts, trace IDs, span IDs, tenant IDs, duration, and status. It does not export prompts, completions, tool arguments, or raw request/response bodies. See [SECURITY.md](SECURITY.md).

## Storage Schema Note

The SQLAlchemy models include tenant-scoped composite constraints for new schemas
so sessions, agents, events, artifacts, and approvals cannot be related across
tenants by foreign key. This release does not add Alembic migrations; existing
databases should be migrated explicitly or recreated in a controlled maintenance
window before relying on the new constraints.
