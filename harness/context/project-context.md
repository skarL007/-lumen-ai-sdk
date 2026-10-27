# Project Context

Repository: `skarL007/-lumen-ai-sdk`

Repo root: current checkout.

Canonical branch: `LumenAI`

Primary packages:

- `packages/lumen-ai-core`: OpenTelemetry processors, pricing, exporters, typed event schema.
- `packages/lumen-ai-celery`: Celery lifecycle instrumentation.
- `packages/lumen-ai-openlit`: OpenLIT bridge for auto-instrumentation.

Primary gates:

- `.\.venv\Scripts\python.exe -m pytest tests -q`
- `.\.venv\Scripts\python.exe -m ruff check packages/lumen-ai-core/src packages/lumen-ai-celery/src packages/lumen-ai-openlit/src --select E,F,W,I --ignore E501`
- `.\.venv\Scripts\python.exe -m mypy packages/lumen-ai-core/src/lumen_ai --ignore-missing-imports --no-error-summary`
- `.\.venv\Scripts\python.exe scripts\release_gate.py`

Audit priorities:

1. Runtime correctness: no lost events, no stale exporters, no incorrect cost or token metadata.
2. Tenant isolation: no cross-tenant attribution, no raw unsanitized tenant in stream keys.
3. Release safety: publish must run the same quality bar as local release gate.
4. Supply chain: pinned actions, reproducible dependencies, blocking dependency audit.
5. Docs and examples: quickstarts must run the code being audited and avoid private APIs.
6. Adoption: local no-key demo, provider examples, Celery, and OpenLIT/LangChain paths need clear proof.

Known environment caveat:

- `python.exe` in PATH may be the Windows Store alias. Use `.venv\Scripts\python.exe` or the Python 3.12 executable under `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.
