import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _dependencies(package: str) -> list[str]:
    pyproject = ROOT / "packages" / package / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["dependencies"]


def _version(package: str) -> str:
    pyproject = ROOT / "packages" / package / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_core_declares_sqlalchemy_for_public_models_module():
    deps = _dependencies("lumen-ai-core")
    assert any(dep.startswith("sqlalchemy>=") for dep in deps)


def test_openlit_dependency_matches_bridge_requirement():
    deps = _dependencies("lumen-ai-openlit")
    assert any(dep.startswith("openlit>=1.0") for dep in deps)


def test_package_versions_match_runtime_versions():
    import sys

    sys.path.insert(0, str(ROOT / "packages" / "lumen-ai-core" / "src"))
    sys.path.insert(0, str(ROOT / "packages" / "lumen-ai-celery" / "src"))
    sys.path.insert(0, str(ROOT / "packages" / "lumen-ai-openlit" / "src"))

    import lumen_ai
    import lumen_ai_celery
    import lumen_ai_openlit

    assert _version("lumen-ai-core") == lumen_ai.__version__ == "0.2.0"
    assert _version("lumen-ai-celery") == lumen_ai_celery.__version__ == "0.2.0"
    assert _version("lumen-ai-openlit") == lumen_ai_openlit.__version__ == "0.2.0"
