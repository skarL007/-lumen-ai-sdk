# Multi-Tenant Cost Report

A deterministic, offline demo of the full LumenAI pipeline. It sends a fixed
workload of synthetic OpenTelemetry spans for three tenants through the real
processor chain, writes normalized events to JSON Lines, and rebuilds a
per-tenant cost report from that file.

No Redis, Docker, OpenAI, Anthropic, or other API key is required.

## Run

From the repository root:

```bash
pip install -e packages/lumen-ai-core
python examples/multi-tenant-cost-report/main.py
```

Use `--output path/to/events.jsonl` to write the events somewhere else. The
file is truncated on every run so totals are reproducible.

The expected output is in the root [README](../../README.md#reproducible-demo-60-seconds-no-keys);
`tests/test_cost_report_example.py` fails if the two ever differ.

## What the workload covers

| Tenant | Spans | Exercises |
|---|---|---|
| `acme-health` | 3 chat turns, 1 embedding, 1 tool call, 1 follow-up | OTel GenAI attributes, event types, a span that ends in another tenant's context |
| `globex-legal` | 1 review with 30k cached tokens, 1 failed retry | Anthropic cache-read pricing, cost of failed calls |
| `initech` | 1 agent span with an OpenInference-only LLM call and a local model | Phoenix-style token counts, free local models, nested spans |
