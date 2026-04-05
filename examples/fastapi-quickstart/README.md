# LumenAI Quickstart

Minimal FastAPI app with real-time cost tracking per tenant.

## Run

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up
```

## Test

```bash
# Send a chat request with tenant header
curl -X POST http://localhost:8000/chat \
  -H "X-Tenant-ID: acme-corp" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!"}'

# View events in Redis
docker exec -it fastapi-quickstart-redis-1 \
  redis-cli XRANGE "LumenAI:events:acme-corp" - +
```

## After PyPI is live

Replace the git install in `Dockerfile` with:

```dockerfile
RUN pip install fastapi uvicorn anthropic lumen-ai-core
```
