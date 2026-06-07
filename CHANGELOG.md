# Changelog

All notable changes to the LumenAI SDK will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.4] - 2026-06-07

Correctness, concurrency, and security hardening pass. Two notable behavior changes:
cached tokens are no longer double-billed for OpenAI/Azure (reported cost drops for
those spans), and OTLP transport now defaults to TLS for non-loopback endpoints.

### Fixed
- **cost**: model ids resolve by longest boundary match instead of the first substring, so dated/versioned ids no longer mis-resolve to a pricier base tier (e.g. `gpt-4o-mini-2024-07-18` was billed as `gpt-4o`, 16–20×).
- **cost**: cached tokens are no longer double-billed for emitters that fold them into `input_tokens` (OpenAI/Azure); cache-only spans (input==output==0, cache_read>0) are now counted.
- **providers**: `AsyncRedisExporter` no longer self-deadlocks on auto-flush and no longer drops writes across event loops; it runs on a dedicated background loop and shuts down deterministically.
- **tenant**: `TenantSpanProcessor.on_end` keeps the tenant pinned at span start, fixing a cross-tenant cost/metadata leak when a span ended in another tenant's context; the normalizer now consumes the side-map entries.
- **sdk**: `init()` adopts an already-installed `TracerProvider`, and a fresh `init()` after `shutdown()` installs a live provider (telemetry no longer silently dies after the first restart).
- **celery**: spans are closed on `task_revoked` / `worker_shutting_down`; a null `task_id` no longer creates a leaked entry.
- **normalizer**: error detection compares the `StatusCode` enum (the prior `== 2` check was dead); embedding/retrieval/rerank span kinds get their own event types instead of `AGENT_COMPLETED`.
- **examples**: the FastAPI quickstart and Celery demo now open spans with model + token usage (previously emitted zero events / always $0).

### Added
- Provider-aware cache accounting (`semconv.provider_includes_cache_in_input`).
- Normalizer health counters `get_metrics()` / `reset_metrics()` (events_exported / export_errors / events_dropped).
- RAG event types: `EMBEDDING_*`, `RETRIEVAL_*`, `RERANK_*`.
- `__version__` on `lumen-ai-celery` and `lumen-ai-openlit`, plus `py.typed` markers for both.
- A version-consistency test that fails CI if any version declaration drifts.
- `scripts/release_gate.py`; `examples/jsonl-smoke`.

### Changed
- ORM event model renamed `LumenAIEvent` → `LumenAIEventRow` to avoid clashing with the public `LumenAIEvent` TypedDict.
- `RedisExporter` documented as synchronous/low-throughput (use `AsyncRedisExporter` for non-blocking paths).
- `linear-sync` CI guarded to the canonical repo so fork PRs no longer fail it.
- Replaced example API-key placeholders with non-secret placeholders; updated contributor docs and issue templates.

### Security
- `CommunityPricingProvider` fetch hardened: https-only by default, 1 MiB cap, JSON-object validation, and failure back-off — prevents SSRF / local-file read / pricing poisoning of the billing table.
- OTLP transport defaults to TLS for non-loopback endpoints (`otlp_insecure=None` auto-selects), so telemetry isn't sent in cleartext to a remote collector by default.
- `tenant_id` is sanitized (control chars stripped, length capped) before it reaches Redis stream keys or logs.

---

## [0.1.3] - 2026-05-05

### Added
- `JsonlExporter` for local demos and smoke tests without Redis.
- Top-level `JsonlExporter` export from `lumen_ai`.
- Real dashboard screenshot in the root README.

### Changed
- Documented JSONL export as a no-service sink.

---

## [0.1.2] - 2026-05-05

### Fixed
- Added missing `sqlalchemy>=2.0.0` dependency for the public `lumen_ai.models` module.
- Made the core mypy gate actionable by fixing OTel attribute casts instead of masking errors.
- Aligned `lumen-ai-openlit` package dependency with the bridge requirement: `openlit>=1.0`.
- Updated publish workflow so manual package selection respects `core`, `celery`, `openlit`, or `all`.

### Added
- Top-level exports for tenant helpers, Redis exporters, and `LumenAIEvent`.
- `LumenAIEvent` typed event contract.
- Privacy regression test proving prompt, completion, tool arguments, and raw bodies are not exported.
- OpenLIT mock test and Celery signal-handler unit test.
- Clean wheel install CI job and non-blocking `pip-audit` job.
- Local no-key observability demo under `examples/local-observability-demo`.
- Opt-in benchmark execution via `LUMEN_RUN_BENCHMARKS=1`.

### Changed
- Replaced duplicated package READMEs with package-specific docs.
- Rewrote the root README to separate working alpha behavior, local demo, public API, and roadmap.
- Renamed the old static visual demo to `lumen-simulation.html` to avoid presenting it as a real SDK integration demo.

---

## [0.1.1] — 2026-04-05

### Fixed
- **lumen-ai-celery**: corrected import paths (`LumenAI` → `lumen_ai`) — package was non-functional since v0.1.0
- **lumen-ai-openlit**: corrected import paths (`LumenAI` → `lumen_ai`) — package was non-functional since v0.1.0
- **models.py**: removed coupling to Brain project (`app.infra.db` fallback import)
- **RedisExporter**: elevated export failure log from `DEBUG` to `WARNING`

### Added
- `AsyncRedisExporter` — non-blocking buffered exporter with batch flush for async frameworks
- Expanded pricing table: OpenAI (GPT-4o, 4.1, o3-mini), Anthropic aliases, Mistral, Meta Llama 4, Gemini Flash (~30 models)
- Input validation on `LumenAI.init()` — rejects empty tenant, invalid redis_url, conflicting redis_url+exporter
- `py.typed` marker (PEP 561) for mypy/pyright support
- `otlp_insecure` parameter to `LumenAI.init()` — allows TLS for OTLP in production
- Performance benchmarks (`test_benchmark.py`) — 10K spans, 4 scenarios
- Integration tests with real Redis (`test_integration.py`) — roundtrip, tenant isolation, full pipeline
- Redis service container in CI for integration tests
- `CHANGELOG.md`

### Changed
- CI now runs ~32 tests (smoke + processors + benchmarks + integration)
- Updated CONTRIBUTING.md, SECURITY.md, and README.md to reflect current project state

---

## [0.1.0] — 2026-03-30

### Added
- Initial PyPI release of all three packages:
  - `lumen-ai-core` — TenantSpanProcessor, CostComputingSpanProcessor, EventNormalizerProcessor, RedisExporter
  - `lumen-ai-celery` — CeleryInstrumentor (signal hooks)
  - `lumen-ai-openlit` — OpenLITBridge (60+ LLM provider auto-instrumentation)
- 22 tests (13 smoke + 9 processor unit tests)
- Trusted Publishing to PyPI via GitHub Actions OIDC
- Interactive demo (`lumen-demo.html`)
- FastAPI quickstart example with Docker Compose
- SECURITY.md with privacy model and vulnerability reporting
- CONTRIBUTING.md with architecture guide and templates
