import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _dependencies(package: str) -> list[str]:
    pyproject = ROOT / "packages" / package / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["dependencies"]


def test_core_declares_sqlalchemy_for_public_models_module():
    deps = _dependencies("lumen-ai-core")
    assert any(dep.startswith("sqlalchemy>=") for dep in deps)


def test_openlit_dependency_matches_bridge_requirement():
    deps = _dependencies("lumen-ai-openlit")
    assert any(dep.startswith("openlit>=1.0") for dep in deps)
