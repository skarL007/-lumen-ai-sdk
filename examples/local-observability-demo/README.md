# LumenAI Local Observability Demo

This is the primary LumenAI demo. It proves the SDK path without any paid LLM API key by starting FastAPI and Redis, creating synthetic OpenTelemetry GenAI spans, letting LumenAI compute cost and tenant metadata, and storing normalized events in Redis Streams.

## Run

```bash
cd examples/local-observability-demo
docker compose up --build
```

Open `http://localhost:8000` for the dashboard. In another terminal, exercise the same flow through the API:

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

Expected result: the `/events/acme` response includes normalized LumenAI events with `tenant_id`, `model`, `tokens_in`, `tokens_out`, `cache_read_tokens`, `cost_usd`, `trace_id`, `span_id`, `duration_ms`, and no prompt or response text.

If port `8000` is busy, change the left side of `8000:8000` in `docker-compose.yml`. Stop and remove containers with:

```bash
docker compose down
```

## Why this demo exists

- No external AI provider account is required.
- The generated events go through the real `LumenAI.init()` processor chain.
- The Redis stream name is tenant-scoped: `LumenAI:events:{tenant_id}`.
- The deterministic scenario creates multiple tenants, cache reads, and one simulated failure so the dashboard shows the useful paths immediately.
