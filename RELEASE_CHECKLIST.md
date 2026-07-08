# LumenAI 0.1.4 Release Checklist

Use this checklist before tagging or publishing `0.1.4`.

## Current Status

- Local validation: green.
- Audit dashboard: score `90`.
- Remote GitHub Actions: blocked until account billing allows runners to start.
- PyPI: latest public package remains `0.1.3` until `v0.1.4` is published.

## Manual Gate

Run the full local gate from a clean checkout:

```powershell
.\harness\scripts\run-audit.ps1 -Full
```

The generated dashboard should show:

- `overall_score`: `90` or higher.
- `pytest`: pass.
- `ruff`: pass.
- `mypy`: pass.
- `pip-check`: pass.
- `pip-audit`: pass.
- `release-gate`: pass.
- Runtime probes: all pass.

Then visually review:

- `harness\dashboard\index.html`
- `harness\reports\audit-data.json`
- `harness\reports\dashboard-screenshot.png`

## Release Blockers

Do not publish while any of these are true:

- GitHub Actions cannot start because account billing is locked.
- The full local harness does not pass.
- PyPI `0.1.4` artifacts have not been checked through the hardened publish workflow.
- The release tag does not match package versions exactly: `v0.1.4`.

## Publish Sequence

After billing is available and PR checks can run:

1. Rerun the PR checks:

   ```powershell
   gh run rerun 28906569194 --failed
   ```

2. Confirm PR checks pass for Python `3.11` and `3.12`.
3. Mark the PR ready for review:

   ```powershell
   gh pr ready 12
   ```

4. Merge into `LumenAI`.
5. Create and push the tag:

   ```powershell
   git tag v0.1.4
   git push origin v0.1.4
   ```

6. Publish through the hardened Trusted Publishing workflow.
7. Confirm PyPI shows `0.1.4` for:

- `lumen-ai-core`
- `lumen-ai-celery`
- `lumen-ai-openlit`

8. Rerun dependency audit against PyPI-installed `0.1.4` artifacts.

## Known Follow-ups

- Add Alembic migrations for tenant-scoped constraints before applying them to existing databases.
- Run live provider validation for OpenLIT/LangChain with real credentials.
- Add historical dashboard comparison by commit.
