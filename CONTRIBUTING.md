# Contributing to LumenAI SDK

Welcome, and thank you for considering a contribution. LumenAI is the first open-source project by [skarL007](https://github.com/skarL007) — every pull request, issue, and pricing update makes a real difference.

This guide will help you get oriented quickly and contribute effectively, whether you are fixing a typo or implementing a new exporter.

---

## Quick Orientation

The repository is a Python monorepo with three packages and a shared test suite:

```
-lumen-ai-sdk/
├── packages/
│   ├── lumen-ai-core/       ← Core SDK (always start here)
│   ├── lumen-ai-celery/     ← Optional Celery integration
│   └── lumen-ai-openlit/    ← Optional OpenLIT bridge
└── tests/
    ├── test_smoke.py        ← 13 smoke tests (imports, processors, pricing)
    └── test_processors.py   ← 9 unit tests (ContextVar, cost math, pricing table)
```

**Start with `lumen-ai-core`.** Everything else builds on it. The most important files are:

| File | What it does |
|---|---|
| `packages/lumen-ai-core/src/lumen_ai/sdk.py` | `LumenAI` class — the public entry point |
| `packages/lumen-ai-core/src/lumen_ai/processors/tenant.py` | `TenantSpanProcessor` + ContextVar API |
| `packages/lumen-ai-core/src/lumen_ai/processors/cost.py` | `CostComputingSpanProcessor` |
| `packages/lumen-ai-core/src/lumen_ai/processors/normalizer.py` | `EventNormalizerProcessor` |
| `packages/lumen-ai-core/src/lumen_ai/providers.py` | `BasePricingProvider`, `BaseLumenAIExporter`, `RedisExporter` |
| `packages/lumen-ai-core/src/lumen_ai/schema/semconv.py` | `PRICING_TABLE` + OTel attribute constants |

---

## Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/skarL007/-lumen-ai-sdk.git
cd -lumen-ai-sdk

# 2. Install the core package in editable mode
pip install -e packages/lumen-ai-core

# 3. Install optional packages if working on them
pip install -e packages/lumen-ai-celery
pip install -e packages/lumen-ai-openlit

# 4. Install test dependencies
pip install pytest

# 5. Run all tests to verify your setup
pytest tests/ -v
```

All 22 tests should pass. If any fail on a clean clone, please [open an issue](https://github.com/skarL007/-lumen-ai-sdk/issues).

---

## Architecture for Contributors

Understanding the three-processor pipeline is essential before making any change to the core SDK.

### The Pipeline

```
OTel span created
       │
       ▼
TenantSpanProcessor.on_start()
  → reads ContextVar lumenai_tenant_id
  → calls span.set_attribute("LumenAI.tenant_id", tenant)
       │
       │  (span runs... LLM call executes...)
       │
       ▼
TenantSpanProcessor.on_end()
  → writes to side-dict: {trace_id:span_id → tenant_id}
       │
       ▼
CostComputingSpanProcessor.on_end()
  → reads gen_ai.usage.input_tokens, output_tokens, cache_read.input_tokens
  → looks up model in BasePricingProvider
  → computes cost_usd = (in * input_rate + out * output_rate + cache * cache_rate) / 1_000_000
  → writes to side-dict: {trace_id:span_id → {cost_usd, tokens, model}}
       │
       ▼
EventNormalizerProcessor.on_end()
  → reads tenant from TenantProcessor's side-dict
  → reads cost from CostProcessor's side-dict
  → assembles canonical LumenAIEvent dict
  → calls exporter.export(tenant_id, event)
```

### Why This Order Matters

The processors are registered in order: `Tenant → Cost → Normalizer`. This order is enforced in `tracer.py` and must not change.

- **Tenant must run first** because `on_start()` stamps the span attribute before the LLM call begins. Child spans inherit the tenant attribute from their parent span this way. If Tenant ran after Cost, child spans could lose their tenant attribution.

- **Cost must run before Normalizer** because `EventNormalizerProcessor` reads from `CostComputingSpanProcessor`'s side-dict. If Cost has not yet processed the span, `get_span_cost_data()` returns `{}` and the event shows `cost_usd: 0.0`.

- **Normalizer runs last** because it is the only processor that writes to an external system (the exporter). Running it last ensures the event is fully enriched before it leaves the process.

### Side-Dicts

Both `TenantSpanProcessor` and `CostComputingSpanProcessor` use an `OrderedDict` keyed by `"{trace_id:032x}:{span_id:016x}"` as a side channel. This is a deliberate design choice:

- **Non-destructive**: Multiple processors can read the same span's data without consuming it.
- **GC-safe**: The dict has a bounded size (`_MAX_ENTRIES = 50_000`) with LRU eviction. Long-running processes never accumulate unbounded memory.
- **Thread-safe**: All writes use a `threading.Lock`.

If you are adding a new processor that needs data from an upstream processor, follow this same side-dict pattern.

---

## 5 Ways to Contribute

Ordered from easiest to most involved.

---

### 1. Update the Pricing Table (Easiest — ~2 minutes)

The pricing table lives in one file, one dict. Open it, add a line, open a PR.

**File:** `packages/lumen-ai-core/src/lumen_ai/schema/semconv.py`

```python
# Find this dict and add your model:
PRICING_TABLE: dict[str, dict[str, float]] = {
    # ... existing entries ...

    # Add new model here — prices are USD per 1 million tokens
    "provider/new-model-name": {"input": 0.50, "output": 2.00, "cache_read": 0.05},
}
```

**Where to find current prices:**
- Anthropic: https://www.anthropic.com/pricing
- OpenAI: https://openai.com/api/pricing/
- Google: https://ai.google.dev/pricing
- DeepSeek: https://platform.deepseek.com/docs/pricing
- Local models (Ollama): always `{"input": 0.0, "output": 0.0, "cache_read": 0.0}`

**PR title format:** `feat(pricing): add <provider>/<model-name>`

---

### 2. Report Bugs / Open Issues

If something is broken or confusing, please open an issue. Good bug reports include:

- Python version (`python --version`)
- Package version (`pip show lumen-ai-core`)
- Minimal reproduction script
- What you expected vs. what happened
- Full traceback if applicable

[Open a bug report](https://github.com/skarL007/-lumen-ai-sdk/issues/new)

---

### 3. Write a New Exporter

Exporters let LumenAI send events to any data store. Implement `BaseLumenAIExporter` and pass an instance to `LumenAI.init(exporter=...)`.

**Template:**

```python
# packages/lumen-ai-core/src/lumen_ai/providers.py
# (or your own separate package)

import logging
from lumen_ai.providers import BaseLumenAIExporter

logger = logging.getLogger(__name__)


class MyCustomExporter(BaseLumenAIExporter):
    """
    Exports LumenAI events to <your target>.

    Args:
        connection_string: Connection details for your data store.
    """

    def __init__(self, connection_string: str) -> None:
        self._conn_str = connection_string
        self._client = None
        self._connect()

    def _connect(self) -> None:
        """Establish connection. Called once at construction."""
        try:
            # self._client = YourClient(self._conn_str)
            pass
        except Exception as exc:
            logger.error("MyCustomExporter: connection failed: %s", exc)

    def export(self, tenant_id: str, event: dict) -> None:
        """
        Send one normalized LumenAI event to the target.

        This method is called synchronously from on_end() — keep it fast.
        For high-throughput scenarios, buffer writes and flush in a background thread.

        Args:
            tenant_id: The tenant that owns this event.
            event:     Canonical LumenAI event dict. See Event Schema in README.
        """
        if self._client is None:
            return  # Silently drop if not connected — never raise here

        try:
            # self._client.write(table="lumenai_events", data=event)
            pass
        except Exception as exc:
            # Always catch exceptions — a broken exporter must never crash the app
            logger.debug("MyCustomExporter.export failed: %s", exc)

    def shutdown(self) -> None:
        """
        Flush any buffered data and close the connection gracefully.
        Called by LumenAI.shutdown().
        """
        try:
            if self._client:
                # self._client.close()
                pass
        except Exception as exc:
            logger.debug("MyCustomExporter.shutdown failed: %s", exc)
```

**Key rules for exporters:**
- `export()` must **never raise** — exceptions crash the OTel span pipeline for the calling thread.
- `export()` is called **synchronously** from `on_end()`. Keep it fast (< 1ms) or use a buffer + background flush.
- Always implement `shutdown()` — it is called on `LumenAI.shutdown()` to drain buffers.
- The `event` dict structure is documented in the [Event Schema](README.md#event-schema) section of the README.

---

### 4. Write a New PricingProvider

If you need dynamic pricing (from an API, database, or secrets manager), implement `BasePricingProvider`.

**Template:**

```python
from typing import Optional, Dict
from lumen_ai.providers import BasePricingProvider
import logging

logger = logging.getLogger(__name__)


class MyPricingProvider(BasePricingProvider):
    """
    Provides model pricing from <your source>.

    Args:
        source: Where to fetch prices (API URL, DB DSN, config path, etc.)
    """

    def __init__(self, source: str) -> None:
        self._source = source
        self._cache: Dict[str, Dict[str, float]] = {}

    def get_pricing(self, model: str) -> Optional[Dict[str, float]]:
        """
        Return pricing for a model, or None if unknown.

        Args:
            model: Model identifier as it appears in OTel spans
                   (e.g. "claude-sonnet-4-6", "openai/gpt-4o").

        Returns:
            Dict with keys "input", "output", "cache_read" (all USD per 1M tokens),
            or None if the model is not recognized.
        """
        # Check cache first
        if model in self._cache:
            return self._cache[model]

        # Attempt to load from source
        try:
            pricing = self._fetch_from_source(model)
            if pricing:
                self._cache[model] = pricing
            return pricing
        except Exception as exc:
            logger.warning("MyPricingProvider: fetch failed for model '%s': %s", model, exc)
            return None

    def _fetch_from_source(self, model: str) -> Optional[Dict[str, float]]:
        """Implement your actual data retrieval here."""
        # Example: database query, HTTP call, config file read, etc.
        raise NotImplementedError
```

**Key rules for pricing providers:**
- `get_pricing()` must **never raise** — exceptions in the pricing provider cause the span to skip cost computation silently (not crash).
- Return `None` for unknown models, not a dict with zero values. Zero values are reserved for genuinely free models (local Ollama).
- Cache aggressively — `get_pricing()` is called on every span end. A database round-trip per span is not acceptable.
- The return dict must have exactly these keys: `"input"`, `"output"`, `"cache_read"` — all floats, USD per 1 million tokens.

---

### 5. Add Integrations

New integrations (LangChain, LlamaIndex, Haystack, etc.) follow the `BaseInstrumentor` pattern used by `CeleryInstrumentor` and `OpenLITBridge`.

**Pattern:**

```python
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
import logging

logger = logging.getLogger(__name__)


class MyFrameworkInstrumentor(BaseInstrumentor):
    """
    Auto-instruments <framework> to emit OTel spans compatible with LumenAI.

    Usage:
        LumenAI.init(instrumentors=[MyFrameworkInstrumentor()])
    """

    def __init__(self):
        self._connected = False

    def instrumentation_dependencies(self) -> list[str]:
        """Return pip dependencies needed by this instrumentor."""
        return ["my-framework >= 1.0"]

    def _instrument(self, tracer_provider=None, **kwargs):
        """Called by LumenAI.init(). Hook into the framework here."""
        if self._connected:
            return
        # Install hooks, monkey-patches, or signal connections here.
        # Use the tracer_provider argument so spans flow through LumenAI processors.
        self._connected = True
        logger.info("MyFrameworkInstrumentor: activated")

    def _uninstrument(self, **kwargs):
        """Called by LumenAI.shutdown(). Remove all hooks here."""
        if not self._connected:
            return
        # Remove hooks, disconnect signals, etc.
        self._connected = False
        logger.info("MyFrameworkInstrumentor: deactivated")
```

Integration packages should be added as `packages/lumen-ai-<framework>/` following the same `pyproject.toml` structure as `lumen-ai-celery`.

---

## Commit Message Conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | When to use |
|---|---|
| `feat` | New feature or capability (e.g. `feat(pricing): add google/gemini-2.0-flash`) |
| `fix` | Bug fix (e.g. `fix(cost): handle None model attribute without crashing`) |
| `docs` | Documentation only (e.g. `docs: add ClickHouse exporter example to README`) |
| `test` | Adding or fixing tests (e.g. `test: add smoke test for CommunityPricingProvider`) |
| `chore` | Maintenance, dependency bumps, config (e.g. `chore: bump opentelemetry-sdk to 1.31`) |
| `refactor` | Code restructuring without behavior change |
| `perf` | Performance improvement |

**Examples:**

```
feat(pricing): add mistral/mistral-large-2411 to PRICING_TABLE
fix(tenant): reset ContextVar token even when call_next raises
docs(contributing): add template for new PricingProvider
test(smoke): add test for partial model name matching with provider prefix
chore: update opentelemetry-sdk dependency to >=1.31.0
```

---

## PR Checklist

Before opening a pull request, verify the following:

- [ ] All 22 tests pass: `pytest tests/ -v`
- [ ] New code follows the patterns in the file it modifies (side-dicts, exception handling, logging style)
- [ ] `export()` and `get_pricing()` implementations never raise exceptions to the caller
- [ ] No hardcoded model names — use `PRICING_TABLE` keys or the `semconv.py` constants
- [ ] No secrets, API keys, or `.env` files committed
- [ ] Commit messages follow the Conventional Commits format above
- [ ] PR description explains *why* the change is needed, not just *what* it does
- [ ] If adding a new model to `PRICING_TABLE`: include a link to the official pricing page in the PR description
- [ ] If adding a new exporter: include a minimal usage example in the PR description

---

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test by name
pytest tests/ -v -k "test_tenant_processor_isolation"

# Run with output (useful when debugging)
pytest tests/ -v -s

# Check test coverage (requires pytest-cov)
pip install pytest-cov
pytest tests/ --cov=lumen_ai --cov-report=term-missing
```

The test suite uses `unittest.mock.MagicMock` to create minimal OTel span objects — no real OTel collector, Redis instance, or LLM provider is needed to run the tests. All 22 tests run in under 1 second.

---

## Code Style

- **PEP 8** for formatting. Line length: 100 characters.
- **Descriptive names** over comments. `_store_cost_data()` is better than `# store it`.
- **No magic numbers** — constants belong in `semconv.py` or at the module top with a name.
- **Type hints everywhere** — return types, parameter types, class attributes.
- **No bare `except:`** — always catch a specific exception or `Exception` with a logged message.
- **Silent failure in processors** — processors must never crash the calling thread. Catch `Exception`, log at `WARNING` level, return.

```python
# Good — silent failure with context
def on_end(self, span: ReadableSpan) -> None:
    try:
        ...
    except Exception:
        logger.warning("CostComputingSpanProcessor.on_end failed silently", exc_info=True)

# Bad — crashes the OTel pipeline
def on_end(self, span: ReadableSpan) -> None:
    pricing = self._pricing.get_pricing(model)  # Can raise!
    cost = pricing["input"] * tokens            # KeyError if missing key!
```

---

## Community

Questions, ideas, or feedback that do not fit a GitHub issue?

- Discord: [skar1v9](https://discord.com/users/skar1v9)
- Instagram: [@skar1v9](https://instagram.com/skar1v9)
- Sponsor: [github.com/sponsors/skarL007](https://github.com/sponsors/skarL007)

If LumenAI has been useful to you or your team, consider starring the repo or sponsoring further development. This is a solo project, and your support is what makes continued work possible.

---

Thank you for contributing.
