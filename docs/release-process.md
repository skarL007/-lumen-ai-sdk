# Release Process

LumenAI publishes three packages: `lumen-ai-core`, `lumen-ai-celery`, and `lumen-ai-openlit`.

## Checklist

1. Update package versions and runtime `__version__` values together.
2. Move relevant `CHANGELOG.md` entries from `Unreleased` into the release section.
3. Run `python scripts/release_gate.py`.
4. Confirm the GitHub Actions CI matrix is green for Python 3.11 and 3.12.
5. Create a GitHub release for the tag. The publish workflow builds wheel and sdist artifacts, runs `twine check`, and uploads only the package selected by the workflow matrix.

The root `pyproject.toml` is workspace/tooling metadata only. Do not publish it as a meta-package.
