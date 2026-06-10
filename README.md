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
- Redis integration tests, clean wheel and sdist checks, package import checks, mypy on core, and non-blocking dependency audit in CI.
- Local demo with no paid API key: [examples/local-observability-demo](examples/local-observability-demo).

This project is still alpha. The core contracts are usable, but the API can still evolve before v1.0.

## Why This Matters In Production

1. Tenant cost attribution: SaaS teams can answer which customer caused a cost spike instead of seeing one shared LLM bill.
2. Spike detection: normalized metadata makes it possible to alert on model, latency, token, and error anomalies without parsing app logs.
3. Privacy-preserving audit trail: LumenAI exports metadata only. It does not export prompt text, completion text, tool arguments, or raw request bodies.

## Quick Start

Install the core package:

```bash
pip install lumen-ai-core
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

Open `http://localhost:8000` for the dashboard. The Compose file starts Redis, waits for it to become healthy, and runs the FastAPI app on port `8000`.

Use the API directly:

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/scenario

curl -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"acme","model":"gpt-4o-mini","input_tokens":1200,"output_tokens":300,"cache_read_tokens":0,"latency_ms":18}'

curl http://localhost:8000/events/acme
curl http://localhost:8000/stats/acme
curl -X DELETE http://localhost:8000/events/acme
```

If port `8000` is already in use, change the left side of `8000:8000` in `examples/local-observability-demo/docker-compose.yml`. Stop and remove the demo with `docker compose down`.

The old static visual simulation is kept as [lumen-simulation.html](lumen-simulation.html). It is a portfolio visual, not proof of SDK behavior.

## Public API

```python
from lumen_ai import (
    AsyncRedisExporter,
    BaseLumenAIExporter,
    BasePricingProvider,
    DefaultPricingProvider,
    JsonlExporter,
    LumenAI,
    LumenAIEvent,
    RedisExporter,
    clear_tenant_id,
    get_tenant_id,
    lumen_tenant,
    set_tenant_id,
)
```

`LumenAIEvent` is a typed metadata-only event contract. Exporters receive `tenant_id` plus this normalized event object.

## Event Schema

`LumenAIEvent` contains metadata only:

| Field | Meaning |
|---|---|
| `tenant_id`, `session_id`, `agent_id` | Business and workflow identifiers supplied through context or span attributes |
| `trace_id`, `span_id`, `timestamp`, `duration_ms` | OpenTelemetry timing and trace metadata |
| `event_type`, `severity`, `message`, `is_error` | Normalized event classification |
| `cost_usd`, `tokens_in`, `tokens_out`, `cache_read_tokens` | Cost and token metrics from GenAI/OpenInference attributes or explicit LumenAI metadata |
| `model`, `tool_name`, `span_kind` | Model/tool/span labels used for filtering and dashboards |

Prompt text, completion text, tool arguments, raw request bodies, and raw response bodies are not exported.

## Packages

| Package | Purpose |
|---|---|
| `lumen-ai-core` | Core OTel processors, pricing, exporters, typed event contract |
| `lumen-ai-celery` | Celery task lifecycle instrumentation |
| `lumen-ai-openlit` | OpenLIT bridge for provider auto-instrumentation |

## Development

```bash
pip install -r requirements-dev.txt
pip install -e packages/lumen-ai-core
pip install -e packages/lumen-ai-celery
pip install -e packages/lumen-ai-openlit

python scripts/release_gate.py
```

The release gate runs tests, ruff, mypy, wheel and sdist builds, `twine check`, clean wheel install, `pip check`, and public import verification. To run individual gates:

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

- v0.2.0: SDK contract fixes, richer real local demo, Python 3.11/3.12 CI, sdist/wheel release checks.
- v0.1.3: JSONL exporter, live dashboard screenshot, and benchmark workflow.
- v0.1.2: package hardening, typed event contract, honest docs, local no-key demo, clean install CI.
- v0.3: production dashboard example backed by Redis or ClickHouse.
- v1.0: stable public API, migration guide, security review, and production readiness checklist.

## Security Model

LumenAI reads OpenTelemetry metadata such as model names, token counts, trace IDs, span IDs, tenant IDs, duration, and status. It does not export prompts, completions, tool arguments, or raw request/response bodies. See [SECURITY.md](SECURITY.md).
