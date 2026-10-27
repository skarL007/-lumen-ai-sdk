# LumenAI local demo dashboard

A dashboard on top of the real LumenAI processor chain. Press **Run the 3-tenant scenario** and it
replays the README workload (`examples/multi-tenant-cost-report`) through LumenAI. The total is the
same `$0.190000` the README prints. The page then shows:

- the cost per tenant and each tenant's share of the total;
- what the events prove: tenant isolation, privacy, failed calls still billed, prompt-cache reads;
- every exported event, with its raw JSON one click away;
- a form to send your own span: any tenant, any model in the price table, any token counts.

The app starts LumenAI with `genai_only=True`, so FastAPI's own request spans stay out of the cost
stream.

![LumenAI demo dashboard after the 3-tenant scenario](../../docs/assets/lumen-dashboard.png)

## Run it (no Docker, no API key)

From the repository root:

```bash
pip install -e packages/lumen-ai-core fastapi uvicorn
uvicorn main:app --app-dir examples/local-observability-demo
```

Open <http://localhost:8000>. Events are written by `JsonlExporter` to
`examples/local-observability-demo/.runtime/events.jsonl`, and the dashboard reads them back from
that file. Set `LUMEN_DEMO_EVENTS` to use another path.

## Run it with Redis Streams

```bash
cd examples/local-observability-demo
docker compose up --build
```

With `REDIS_URL` set (the compose file sets it), LumenAI stores events in tenant-scoped streams
(`LumenAI:events:{tenant_id}`), and the dashboard reads them back with `XREVRANGE`.

## API

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/health` | Exporter in use (`jsonl` or `redis`) and where events are stored |
| `GET` | `/api/models` | Models in the built-in pricing table, with USD per million tokens |
| `GET` | `/api/events?tenant=&limit=` | Exported events, oldest first |
| `POST` | `/api/scenario` | Clears the store and replays the 3-tenant scenario |
| `POST` | `/api/simulate` | Sends one synthetic LLM span |
| `POST` | `/api/reset` | Clears the store |

```bash
curl -X POST http://localhost:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{"tenant_id":"acme","model":"claude-sonnet-4-6","input_tokens":40000,"output_tokens":2000,"cache_read_tokens":30000}'

curl "http://localhost:8000/api/events?tenant=acme"
```

The event comes back with `tenant_id`, `model`, `tokens_in`, `tokens_out`, `cache_read_tokens` and
`cost_usd` (`0.159` here). It has no prompt or response text.

## Static mode

When the page is served without the backend, it replays `static/recorded-events.json`, a real run
of the scenario recorded by the SDK. To host it on a static site, publish `static/index.html` as
`index.html` next to the `static/` folder. To regenerate the recording after changing the pricing or
the scenario, run:

```bash
python examples/local-observability-demo/record.py
```

`tests/test_local_observability_demo.py` fails if the recording drifts from a fresh run.
