# JSONL Smoke Example

This is the smallest no-service LumenAI example. It creates one synthetic
OpenTelemetry GenAI span, runs it through the real SDK processors, and writes a
normalized metadata-only event to a JSONL file.

## Run

```bash
pip install -e ../../packages/lumen-ai-core
python main.py --output .runtime/events.jsonl
```

Expected output:

```text
Wrote 1 event to ...
tenant=portfolio-acme model=gpt-4o-mini cost_usd=...
```

No Redis, Docker, OpenAI, Anthropic, or paid API key is required.
