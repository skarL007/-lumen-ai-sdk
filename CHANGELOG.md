# Changelog

All notable changes to the LumenAI SDK will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Nothing yet.

---

## [0.1.6] - 2026-10-28

Uploaded with `twine` from a local build after `scripts/release_gate.py` passed, as `0.1.5` was.

### Added
- **budgets**: `BudgetExporter(store=...)` takes a `BudgetStore`. `MemoryBudgetStore` is the default and behaves as before. `RedisBudgetStore` shares one total per tenant and period between workers, keeps it across restarts, and alerts each threshold once across all of them (atomic `HINCRBYFLOAT` and `SET NX`, 40-day key TTL). A store error is logged and the event is still exported.
- **budgets**: `BudgetExporter.spent()` takes an optional `period`.

### Changed
- **docs**: the README shows a real-bill check: on 6 real OpenRouter `gpt-4o-mini` calls made from Axon Voice, LumenAI's cost equals OpenRouter's `usage.cost`, cache reads included.

---

## [0.1.5] - 2026-10-28

Uploaded with `twine` from a local build after `scripts/release_gate.py` passed, as `0.1.4` was. The fixes marked "real instrumentation" were found by running real instrumentation libraries against LumenAI (`tests/test_real_instrumentations.py`).

### Added
- **events**: `unpriced: bool` on every event. It is `true` when a span used tokens but got no price (a model missing from the table, a span with no model id, or a pricing provider that raised), so its `cost_usd` of `0.0` reads as unknown instead of free. A model priced at `$0`, such as a local Ollama model, stays `false`.
- **metrics**: `events_unpriced` in `lumen_ai.processors.normalizer.get_metrics()` counts those events.
- **cost**: the first unpriced span per model logs a WARNING naming the model (at most 256 models are tracked). It used to be a DEBUG line, so a new model looked free.
- **pricing**: current models at the list prices published on 2026-10-28, each provider's source page noted in the table:
  - Anthropic: Claude Fable 5.1 and 5, Opus 5.5, 5, 4.8, 4.7 and 4.5, Sonnet 5.5, 5 and 4.5, Haiku 5.5.
  - OpenAI: GPT-6 (astra, sol, luna), GPT-6.1 (sol, terra), GPT-5.6 (sol, terra, luna), GPT-5.5, 5.4, 5.2, 5.1 and 5 with their pro, mini and nano variants, and `gpt-5.3-codex`.
  - Google: Gemini 4 Argon, 3.8 and 3.6 Flash, 3.5 and 3.1 Flash-Lite, 3.1 Pro Preview, 3 Flash Preview, plus bare `gemini-2.5-*` keys, so ids from Google's SDK resolve without the `google/` prefix.
  - DeepSeek: `deepseek-flash`, `deepseek-v4-flash` and `deepseek-v4-pro`, at peak rates.
  - Mistral: Large 3 (`mistral-large-latest`), Large 4 (preview), Medium 3.5, Small 4.
  - Bare `text-embedding-3-small`.
- **pricing**: comments in the table say where a flat rate cannot follow the provider: Claude Haiku 5.5 over 100K prompt tokens, OpenAI over 272K, Gemini Pro over 200K, Gemini prices scheduled to change, and DeepSeek off-peak hours.
- **events**: `cache_write_tokens`.
- **budgets**: `BudgetExporter` wraps any exporter and alerts when a tenant crosses 80% and 100% of a USD limit per UTC month or day. An alert calls `on_alert(BudgetAlert)`, exports a `COST_THRESHOLD_EXCEEDED` event (`WARN` / `ERROR`) and logs a WARNING. Unpriced events are counted in the alert.
- **pricing**: `LiteLLMPricingProvider` keeps the built-in table first and fills the gaps from LiteLLM's community price list (about 4,000 models). It downloads the list over HTTPS in a background thread and refreshes it daily, so spans never wait. `path=` reads a local copy. `litellm_pricing_table()` converts the list to LumenAI's format.
- **scripts**: `check_prices.py` compares the built-in table with LiteLLM's list and exits 1 on a difference. Known differences where LiteLLM is the stale side are listed in the script. On 2026-10-28 the only one is Mistral Large 4.
- **tests**: `test_real_instrumentations.py` runs real OpenAI and Anthropic SDK calls under OpenInference, OpenLLMetry, OpenLIT and the OTel contrib instrumentation, against a mocked endpoint, and pins the cost of each.

### Fixed
- **cost** (real instrumentation): Anthropic calls traced by OpenLLMetry (`opentelemetry-instrumentation-anthropic`), OpenInference or the Anthropic SDK's own spans were over-billed by about 56% when prompt caching was on. These emitters count cached tokens inside `input_tokens`; LumenAI assumed Anthropic never does and billed them twice. The rule is now per emitter (`CACHE_INCLUSIVE_SCOPES`), then per provider, and an input smaller than the cached tokens is never treated as including them.
- **cost** (real instrumentation): OpenInference spans (Arize Phoenix) lost their cached tokens, because `llm.token_count.prompt_details.cache_read` was not read. OpenAI calls were over-billed by about 26% on the tested workload.
- **cost** (real instrumentation): cache writes were free. `gen_ai.usage.cache_creation.input_tokens`, the Anthropic SDK's `gen_ai.usage.cache_write.input_tokens` and OpenInference's `prompt_details.cache_write` are now billed at the model's new `cache_write` rate, else at its input rate. The table has `cache_write` for every Claude model and for GPT-5.6 and GPT-6.
- **cost** (real instrumentation): a call recorded by two instrumentations, such as OpenInference wrapping the Anthropic SDK's own span, was billed twice. A span whose usage equals the sum of its children's is now stored with zero tokens and zero cost. The same applies to agent spans that carry their children's totals.
- **openlit** (real instrumentation): `OpenLITBridge` started OpenLIT with prompt capture, events and metrics on. Without an OTLP endpoint, OpenLIT printed prompt and completion text to stdout, which broke the metadata-only promise. It now passes `capture_message_content=False`, `disable_events=True` and `disable_metrics=True`. All three are constructor options.
- **pricing**: five list prices were wrong:
  - `claude-haiku-4-5` was priced as Claude 3 Haiku ($0.25 / $1.25). It is $1 / $5, with cache reads at $0.10.
  - `claude-opus-4-6` was priced at $15 / $75. It is $5 / $25, with cache reads at $0.50.
  - `gemini-2.5-flash` is $0.30 / $2.50, not $0.15 / $0.60.
  - `mistral-large` is now Large 3 at $0.50 / $1.50, not $2 / $6.
  - `mistral-small` is now Small 4 at $0.15 / $0.60, not $0.10 / $0.30.
  - Their `anthropic/`, `google/` and `mistral/` aliases change with them.
- **cost**: token counts are read before the price lookup, so spans with no usage skip the lookup.

### Removed
- **pricing**: `deepseek/deepseek-v3.2` and `deepseek/deepseek-r1`. DeepSeek no longer lists them: `deepseek-chat` and `deepseek-reasoner` were discontinued on 2026-07-24. Spans that still name them export `unpriced: true` instead of an unverified price.

### Changed
- **packaging**: the `lumen-ai-sdk` summary on PyPI no longer says "LumenAI Core".
- **docs**: the README no longer shows the CI badge. It reported "failing" while GitHub Actions is unavailable for this repository, not because of the code; `scripts/release_gate.py` still runs the same checks locally.

---

## [0.1.4] - 2026-10-28

First release under the names `lumen-ai-sdk`, `lumen-ai-sdk-celery` and `lumen-ai-sdk-openlit`. It also carries the June hardening pass below, which never reached PyPI under the old names.

### Added
- **examples**: the demo dashboard is live at https://lumen-ai-sdk-demo.vercel.app, deployed from `main` (`vercel.json`, `vercel_app.py`). It uses a new per-request store (`LUMEN_DEMO_STORE=memory`): each call runs the SDK and returns the events it exported, nothing is kept on the server, and visitors never share data.
- **sdk**: `LumenAI.init(genai_only=True)` exports only spans with GenAI, OpenInference, or LumenAI attributes, so framework spans (FastAPI 0.162 emits request, endpoint, and serialization spans) no longer become `$0` `AGENT_COMPLETED` events. Off by default; skipped spans are counted in the new `events_skipped` metric.
- **examples**: `local-observability-demo` redesigned as a dashboard over the real processor chain. It runs without Docker (JSONL by default, Redis Streams when `REDIS_URL` is set), replays the `multi-tenant-cost-report` workload to the same `$0.190000` total, checks tenant isolation, privacy, failed-call billing, and prompt caching from the exported events, and prices custom spans for any model in the table. New `/api/*` endpoints; the old `/health`, `/simulate`, and `/events/{tenant_id}` paths still work.
- **examples**: `local-observability-demo/record.py` records a run to `static/recorded-events.json`; without a backend, the page replays it, so it can be served from a static host.
- **examples**: `multi-tenant-cost-report`, a deterministic offline demo (three tenants, prompt caching, OpenInference spans, a failed call, a cross-tenant span) whose output is pinned in the README by `tests/test_cost_report_example.py`.
- **providers**: `BaseLumenAIExporter.force_flush()` (no-op default), reached by `TracerProvider.force_flush()` through the normalizer.
- **providers**: `AsyncRedisExporter(flush_interval=1.0)` writes partial buffers on a timer, plus a blocking `force_flush()`.
- **providers**: `RedisExporter(maxlen=...)`, matching `AsyncRedisExporter`.

### Fixed
- **cost**: OpenInference-only spans (`llm.token_count.*`) are now priced; they were exported with `cost_usd=0.0` even for known models.
- **normalizer**: event `timestamp` is the span's end time instead of the export wall-clock.
- **normalizer**: an errored span with no GenAI/OpenInference kind is `AGENT_FAILED`, not `AGENT_COMPLETED`.
- **normalizer**: `session_id` / `agent_id` fall back to `gen_ai.conversation.id` / `gen_ai.agent.id`.
- **providers**: `JsonlExporter.export()` after `shutdown()` is ignored instead of raising on the closed file.
- **sdk**: reinitializing against an externally attached `TracerProvider` now updates exporter, pricing provider, and default tenant through shared runtime state instead of keeping stale sinks.
- **normalizer**: OpenInference-only spans now preserve `llm.model_name`, prompt tokens, and completion tokens even when pricing is unknown and `cost_usd` stays zero.
- **providers**: `AsyncRedisExporter.shutdown()` now waits for in-flight auto-flush futures before closing Redis and its background loop.
- **tenant**: span attributes, Celery kwargs, tenant context, and exporter stream keys now share the same tenant sanitization path; `reset_tenant_id(token)` is public.

### Changed (packaging)
- PyPI distribution names are now `lumen-ai-sdk`, `lumen-ai-sdk-celery` and `lumen-ai-sdk-openlit`, matching the repository. Import names do not change. `lumen-ai-core`, `lumen-ai-celery` and `lumen-ai-openlit` stay at `0.1.3` and get no new releases.

### Removed
- `lumen-simulation.html` and `lumen-ai-demo/`, standalone mock dashboards that did not run the SDK; the demo dashboard replaces them.

### Changed
- README: new "See it in a dashboard" and "Only GenAI spans" sections, and a new dashboard screenshot.
- Lint (CI and `scripts/release_gate.py`) now covers `examples/` and `tests/`; the prompt-cache cost test asserts the exact expected value.
- README rewritten around a reproducible demo, with architecture, span-lifecycle, tenant-attribution, cost, and async-export diagrams and a design-decisions table.
- Span attribute coercion lives in one module (`lumen_ai._attributes`) instead of three diverging copies.
- Hardened CI and publishing with Python 3.11/3.12 matrices, pinned GitHub Actions, blocking dependency audit, release-gate enforcement, `twine check`, and wheel/sdist clean-install validation.
- Updated FastAPI, Celery, LangChain, and custom exporter examples to match the public API and active instrumentation path.
- Added a local audit harness with probes, MCP/context/skills/agent prompts, generated report data, and a visual dashboard.

### Hardening pass (prepared in June 2026)

Correctness, concurrency, and security hardening pass. Two notable behavior changes:
cached tokens are no longer double-billed for OpenAI/Azure (reported cost drops for
those spans), and OTLP transport now defaults to TLS for non-loopback endpoints.

#### Fixed
- **cost**: model ids resolve by longest boundary match instead of the first substring, so dated/versioned ids no longer mis-resolve to a pricier base tier (e.g. `gpt-4o-mini-2024-07-18` was billed as `gpt-4o`, 16–20×).
- **cost**: cached tokens are no longer double-billed for emitters that fold them into `input_tokens` (OpenAI/Azure); cache-only spans (input==output==0, cache_read>0) are now counted.
- **providers**: `AsyncRedisExporter` no longer self-deadlocks on auto-flush and no longer drops writes across event loops; it runs on a dedicated background loop and shuts down deterministically.
- **tenant**: `TenantSpanProcessor.on_end` keeps the tenant pinned at span start, fixing a cross-tenant cost/metadata leak when a span ended in another tenant's context; the normalizer now consumes the side-map entries.
- **sdk**: `init()` adopts an already-installed `TracerProvider`, and a fresh `init()` after `shutdown()` installs a live provider (telemetry no longer silently dies after the first restart).
- **celery**: spans are closed on `task_revoked` / `worker_shutting_down`; a null `task_id` no longer creates a leaked entry.
- **normalizer**: error detection compares the `StatusCode` enum (the prior `== 2` check was dead); embedding/retrieval/rerank span kinds get their own event types instead of `AGENT_COMPLETED`.
- **examples**: the FastAPI quickstart and Celery demo now open spans with model + token usage (previously emitted zero events / always $0).

#### Added
- Provider-aware cache accounting (`semconv.provider_includes_cache_in_input`).
- Normalizer health counters `get_metrics()` / `reset_metrics()` (events_exported / export_errors / events_dropped).
- RAG event types: `EMBEDDING_*`, `RETRIEVAL_*`, `RERANK_*`.
- `__version__` on `lumen-ai-celery` and `lumen-ai-openlit`, plus `py.typed` markers for both.
- A version-consistency test that fails CI if any version declaration drifts.
- `scripts/release_gate.py`; `examples/jsonl-smoke`.

#### Changed
- ORM event model renamed `LumenAIEvent` → `LumenAIEventRow` to avoid clashing with the public `LumenAIEvent` TypedDict.
- `RedisExporter` documented as synchronous/low-throughput (use `AsyncRedisExporter` for non-blocking paths).
- `linear-sync` CI guarded to the canonical repo so fork PRs no longer fail it.
- Replaced example API-key placeholders with non-secret placeholders; updated contributor docs and issue templates.

#### Security
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
