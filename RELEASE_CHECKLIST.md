# LumenAI Release Checklist

Use this checklist before tagging or publishing a release. The current one is `0.1.6`.

## Current Status

- PyPI: `lumen-ai-sdk`, `lumen-ai-sdk-celery` and `lumen-ai-sdk-openlit` at `0.1.5`, until `v0.1.6` is published.
- Remote GitHub Actions: unavailable for this repository, so `0.1.4`, `0.1.5` and `0.1.6` are uploaded with `twine` from a local build (see "Local upload" below).

## Manual Gate

Run the full local gate from a clean checkout:

```powershell
python scripts/release_gate.py
python scripts/check_prices.py
.\harness\scripts\run-audit.ps1 -Full
```

`release_gate.py` must exit 0: tests, ruff, mypy, wheel and sdist builds, `twine check`, clean installs from both, and `pip check`. `check_prices.py` must report no price difference from LiteLLM's list other than the acknowledged ones.

The audit dashboard should show:

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

- `scripts/release_gate.py` does not pass on the commit being tagged.
- The release tag does not match package versions exactly, for example `v0.1.6` for version `0.1.6` in all four `pyproject.toml` files and the three `__version__` strings.
- `CHANGELOG.md` has no dated section for the version.

## Publish Sequence

1. Merge the release PR into `main`.
2. Create and push the tag:

   ```powershell
   git tag v0.1.6
   git push origin v0.1.6
   ```

3. Publish through the Trusted Publishing workflow (`.github/workflows/publish.yml`, one environment per package: `pypi`, `pypi-celery`, `pypi-openlit`), or through "Local upload" while Actions is unavailable.
4. Confirm PyPI shows the version for:

- `lumen-ai-sdk`
- `lumen-ai-sdk-celery`
- `lumen-ai-sdk-openlit`

5. Install the three packages from PyPI in a clean virtual environment and run `pip check`.
6. Create the GitHub release for the tag with the six distribution files attached.
7. Rerun the dependency audit against the PyPI-installed artifacts.

## Local upload

Only while GitHub Actions is unavailable:

```powershell
python -m build packages/lumen-ai-core --outdir dist-0.1.6
python -m build packages/lumen-ai-celery --outdir dist-0.1.6
python -m build packages/lumen-ai-openlit --outdir dist-0.1.6
python -m twine check dist-0.1.6/*
python -m twine upload -u __token__ dist-0.1.6/*
```

The maintainer pastes a PyPI API token at the prompt. Delete the token at <https://pypi.org/manage/account/> once the upload is confirmed.

## Known Follow-ups

- Add Alembic migrations for tenant-scoped constraints before applying them to existing databases.
- Run live provider validation for OpenLIT/LangChain with real credentials.
- Add historical dashboard comparison by commit.
