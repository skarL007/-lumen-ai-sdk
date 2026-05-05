# Changelog

All notable changes to the LumenAI SDK will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
