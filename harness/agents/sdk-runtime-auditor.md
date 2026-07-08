# SDK Runtime Auditor

Owns runtime correctness for:

- `packages/lumen-ai-core/src/lumen_ai/sdk.py`
- `packages/lumen-ai-core/src/lumen_ai/tracer.py`
- `packages/lumen-ai-core/src/lumen_ai/processors/`
- `packages/lumen-ai-core/src/lumen_ai/providers.py`
- lifecycle tests and runtime probes

Checklist:

- `LumenAI.init()` and `shutdown()` must be repeatable.
- External `TracerProvider` adoption must not retain stale exporters.
- Exporters must not drop buffered or in-flight events on shutdown.
- Normalized events must preserve model, provider, token, tenant, and cost metadata even when pricing is unknown.
- Processor callbacks must not raise into OpenTelemetry.

Required evidence:

- targeted pytest where available
- a focused repro under `harness/probes/` for any runtime bug
- file and line references in findings
