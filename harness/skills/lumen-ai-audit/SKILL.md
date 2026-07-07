# LumenAI Audit Skill

Use this skill when auditing, fixing, or preparing release work for `skarL007/-lumen-ai-sdk`.

## First Steps

1. Read `CODEX.md`.
2. Read `harness/context/project-context.md`.
3. Run `git status --short --branch`.
4. Prefer `.venv\Scripts\python.exe`; if missing, run `.\harness\scripts\run-audit.ps1` to create it.

## Validation

Fast gate:

```powershell
.\harness\scripts\run-audit.ps1
```

Full gate:

```powershell
.\harness\scripts\run-audit.ps1 -Full
```

The full gate includes `scripts\release_gate.py`.

## Review Focus

- Runtime: stale exporters, OpenTelemetry provider adoption, shutdown determinism, event metadata preservation.
- Cost: model resolution, cache token semantics, unknown model behavior, pricing source failures.
- Tenant: start-pinned tenant, attribute sanitization, stream key safety, ORM cross-tenant integrity.
- Release: publish restrictions, mutable GitHub Actions refs, Python matrix, wheel/sdist parity.
- Docs: examples that claim automatic tracking, private API imports, PyPI/source version drift.

## Output

Always update or regenerate:

- `harness/reports/audit-data.json`
- `harness/dashboard/index.html`

Summaries should separate:

- validated passing gates
- reproduced bugs
- static risk findings
- skipped or environment-limited checks

