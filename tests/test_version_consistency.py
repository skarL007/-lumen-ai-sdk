"""
The version string lived in 4 pyproject.toml files plus lumen_ai.__version__ with
nothing keeping them in sync, and the celery/openlit packages exposed no
__version__ at all. This test fails CI the moment any declaration drifts.
"""
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]

PYPROJECTS = [
    "pyproject.toml",
    "packages/lumen-ai-core/pyproject.toml",
    "packages/lumen-ai-celery/pyproject.toml",
    "packages/lumen-ai-openlit/pyproject.toml",
]

INITS = [
    "packages/lumen-ai-core/src/lumen_ai/__init__.py",
    "packages/lumen-ai-celery/src/lumen_ai_celery/__init__.py",
    "packages/lumen-ai-openlit/src/lumen_ai_openlit/__init__.py",
]


def _pyproject_version(rel: str):
    data = tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))
    return data["project"]["version"]


def _init_version(rel: str):
    txt = (ROOT / rel).read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', txt)
    return m.group(1) if m else None


def test_all_version_declarations_agree():
    seen = {}
    for rel in PYPROJECTS:
        seen[rel] = _pyproject_version(rel)
    for rel in INITS:
        seen[rel] = _init_version(rel)
    distinct = set(seen.values())
    assert len(distinct) == 1, f"version drift across declarations: {seen}"
