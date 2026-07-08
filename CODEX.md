# LumenAI SDK Codex Context

This clone is prepared for audit work under `harness/`.

Fast paths:

- Run the audit harness: `.\harness\scripts\run-audit.ps1`
- Run the full release-grade harness: `.\harness\scripts\run-audit.ps1 -Full`
- Open the dashboard: `harness\dashboard\index.html`
- Read the project context: `harness\context\project-context.md`
- Use project agent roles from `harness\agents\`
- Use the local skill from `harness\skills\lumen-ai-audit\SKILL.md`
- Configure MCP from `harness\mcp\lumen-audit.mcp.json`

Current environment note:

- On this machine, the PATH `python.exe` can resolve to the Microsoft Store alias.
- Prefer `.venv\Scripts\python.exe`; otherwise use the Python 3.12 executable under `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.
- The repo base branch is `LumenAI`.

## Checkpoint - 2026-07-08

Current branch:

- `codex/lumen-audit-fixes`
- Synced with `origin/codex/lumen-audit-fixes`
- PR: https://github.com/skarL007/-lumen-ai-sdk/pull/12
- PR state: draft
- Latest commit: `ad202de chore: refresh audit dashboard after readme`

What was completed:

- Runtime lifecycle hardening for `LumenAI.init()` / `LumenAI.shutdown()`.
- Mutable runtime state for adopted external `TracerProvider` instances.
- Idempotent exporter shutdown and singleton reset behavior.
- OpenInference-only metadata preservation for model and token counts.
- `AsyncRedisExporter` shutdown hardening, including in-flight auto-flush tracking and race regression test.
- Shared tenant sanitization across context helpers, span attrs, Celery kwargs, and Redis stream keys.
- Public `reset_tenant_id(token)` API exported from `lumen_ai`.
- Tenant-scoped SQLAlchemy constraints for new schemas.
- Hardened CI and publish workflows with Python 3.11/3.12 matrix, pinned action SHAs, release gate before publish, `twine check`, clean wheel/sdist installs, and blocking dependency audit intent.
- README fully rewritten as an open-source project landing page.
- Examples updated for FastAPI, Celery, OpenLIT/LangChain, JSONL smoke, custom exporter, and local demo.
- Local audit harness added under `harness/`: context, agents, skill, MCP config, probes, report JSON, dashboard, and screenshot.
- PR body updated with readiness assessment and current validation evidence.

Latest local validation:

- `.\.venv\Scripts\python.exe -m pytest tests -q` -> `104 passed, 4 skipped, 1 warning`
- `.\.venv\Scripts\python.exe -m ruff check packages/lumen-ai-core/src packages/lumen-ai-celery/src packages/lumen-ai-openlit/src --select E,F,W,I --ignore E501` -> pass
- `.\.venv\Scripts\python.exe -m mypy packages/lumen-ai-core/src/lumen_ai --ignore-missing-imports --no-error-summary` -> pass
- `.\.venv\Scripts\python.exe scripts\release_gate.py` -> pass
- `.\harness\scripts\run-audit.ps1 -Full` -> pass, dashboard score `90`
- Playwright dashboard check -> pass, `0` console errors, all 3 probes pass, all gates pass
- PyPI latest checks -> `lumen-ai-core`, `lumen-ai-celery`, and `lumen-ai-openlit` still latest `0.1.3`; source is `0.1.4`

Known blockers / residual risks:

- GitHub Actions remote CI does not start because the account is locked due to billing. Latest checked run `28910752127` on commit `ad202de` returned: `The job was not started because your account is locked due to a billing issue.`
- Keep PR #12 as draft until billing is restored and remote CI can run.
- Do not publish `0.1.4` until remote CI is green.
- Tenant-scoped SQLAlchemy constraints protect new schemas only; existing databases need an explicit Alembic or manual migration before relying on them.
- `pip-audit` covers dependencies, but unpublished local package names themselves cannot be audited from PyPI until `0.1.4` is published.

Recommended next steps:

1. Restore GitHub Actions billing for the account.
2. Re-run CI on PR #12 and inspect real job logs.
3. If CI is green, mark PR #12 ready for review.
4. Merge when review is acceptable.
5. Create and push tag `v0.1.4`.
6. Let the hardened Trusted Publishing workflow publish the three packages.
7. After publish, rerun PyPI install checks and `pip-audit` against PyPI-installed artifacts.
8. Plan a storage migration cycle for existing SQLAlchemy deployments.
