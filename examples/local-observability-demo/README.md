# LumenAI Local Observability Demo

This demo proves the SDK path without any paid LLM API key. It starts FastAPI and Redis, creates synthetic OpenTelemetry GenAI spans, lets LumenAI compute cost and tenant metadata, and stores normalized events in Redis Streams.

## Run

```bash
cd examples/local-observability-demo
docker compose up --build
```

Open `http://localhost:8000` for the dashboard. In another terminal, the same flow can be exercised through the API:

```bash
curl -X POST http://localhost:8000/simulate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"acme","model":"gpt-4o-mini","input_tokens":1200,"output_tokens":300}'

curl http://localhost:8000/events/acme
```

Expected result: the `/events/acme` response includes a normalized LumenAI event with `tenant_id`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `duration_ms`, and no prompt or response text.

## Why this demo exists

- No external AI provider account is required.
- The generated events go through the real `LumenAI.init()` processor chain.
- The Redis stream name is tenant-scoped: `LumenAI:events:{tenant_id}`.
