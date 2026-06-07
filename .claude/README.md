# LumenAI dev agents & workflows

Project-scoped Claude Code agents and a saved multi-agent workflow for working on the
LumenAI SDK. They encode the institutional knowledge from the codebase audit — the exact
traps that have caused (and could re-cause) silent billing errors, deadlocks, and
cross-tenant leaks — so contributions get checked against them automatically.

## Agents (`.claude/agents/`)

Invoke with the Task/Agent tool, e.g. *"Use the cost-accuracy-reviewer on my pricing change."*

| Agent | Use it when you touch… | Role |
|---|---|---|
| **cost-accuracy-reviewer** | pricing, USD/token math, `PRICING_TABLE`, `cost.py`, `semconv.py` | Specialist — adversarial review of cost correctness (longest-match resolution, cache double-billing, KeyError-safe math, single source of truth). |
| **otel-concurrency-reviewer** | span processors, exporters, `tracer.py`/`sdk.py`, threads/asyncio/locks, celery instrumentor | Specialist — deadlocks, loop-bound clients, set-once TracerProvider lifecycle, blocking I/O on `on_end`, span leaks. |
| **tenant-isolation-auditor** | tenant resolution, ContextVar, stream keys, `tenant_id` columns | Specialist — cross-tenant leakage vs the `SECURITY.md` guarantee. |
| **pricing-table-updater** | adding/updating a model price | Helper — does the project's most common contribution correctly (format, sourcing, verification). |
| **release-gate-runner** | before a PR / release | Helper — runs the CI-equivalent gate (`scripts/release_gate.py`) and explains failures. |
| **docs-sync-checker** | README/CONTRIBUTING/docstrings/examples | Specialist — finds docs/examples that contradict the code. |

Design follows the agent-designer Role-Spec framework (identity, responsibilities, what-to-check,
constraints) and each prompt cites the real files and traps in this repo. Reviewers are read-only
(`Read, Grep, Glob, Bash`); the pricing updater also has `Edit`.

## Workflow (`.claude/workflows/`)

**`lumen-improvement-hunt`** — fans out specialist finder lenses across the codebase,
adversarially verifies every finding (each claim handed to a skeptic that tries to refute it),
then deduplicates and ranks the survivors into an actionable report.

```
Workflow({ name: "lumen-improvement-hunt" })                                   # all 10 lenses
Workflow({ name: "lumen-improvement-hunt", args: ["cost-money","security"] })  # a subset
```

Lens keys: `concurrency-async`, `cost-money`, `multitenant-isolation`, `otel-integration`,
`resource-robustness`, `api-typing-contracts`, `security`, `packaging-release`,
`tests-coverage`, `docs-examples`.

Returns `{ raw_count, confirmed_count, summary, themes, ranked[], confirmed_detail[] }`.
Re-run it after large changes to catch regressions in the same risk areas.
