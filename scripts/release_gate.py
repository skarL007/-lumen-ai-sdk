"""Run the local release gate used before publishing LumenAI packages."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECTS = (
    ROOT / "pyproject.toml",
    ROOT / "packages" / "lumen-ai-core" / "pyproject.toml",
    ROOT / "packages" / "lumen-ai-celery" / "pyproject.toml",
    ROOT / "packages" / "lumen-ai-openlit" / "pyproject.toml",
)
PACKAGES = (
    ROOT / "packages" / "lumen-ai-core",
    ROOT / "packages" / "lumen-ai-celery",
    ROOT / "packages" / "lumen-ai-openlit",
)
CORE_SRC = ROOT / "packages" / "lumen-ai-core" / "src" / "lumen_ai"


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def project_version(path: Path) -> str:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]


def validate_versions() -> str:
    versions = {path.relative_to(ROOT).as_posix(): project_version(path) for path in PYPROJECTS}
    distinct = set(versions.values())
    if len(distinct) != 1:
        raise RuntimeError(f"Version drift across pyprojects: {versions}")

    version = distinct.pop()
    ref = os.environ.get("GITHUB_REF", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    release_tag = os.environ.get("RELEASE_TAG", "")
    tag = release_tag or (ref_name if ref_type == "tag" else "")
    if not tag and ref.startswith("refs/tags/"):
        tag = ref.removeprefix("refs/tags/")
    if tag and tag != f"v{version}":
        raise RuntimeError(f"Tag {tag!r} does not match package version v{version}")
    return version


def verify_clean_install(clean_python: Path, label: str) -> None:
    run([str(clean_python), "-m", "pip", "check"])
    run(
        [
            str(clean_python),
            "-c",
            (
                "import lumen_ai; import lumen_ai.models; "
                "from lumen_ai import LumenAI, JsonlExporter, lumen_tenant, reset_tenant_id; "
                "from lumen_ai_celery import CeleryInstrumentor; "
                "from lumen_ai_openlit import OpenLITBridge; "
                f"print('{label} import OK')"
            ),
        ]
    )


def main() -> int:
    python = sys.executable
    version = validate_versions()
    print(f"Release gate for LumenAI {version}", flush=True)

    run([python, "-m", "pytest", "tests", "-q"])
    run(
        [
            python,
            "-m",
            "ruff",
            "check",
            "packages/lumen-ai-core/src",
            "packages/lumen-ai-celery/src",
            "packages/lumen-ai-openlit/src",
            "--select",
            "E,F,W,I",
            "--ignore",
            "E501",
        ]
    )
    run(
        [
            python,
            "-m",
            "mypy",
            str(CORE_SRC),
            "--ignore-missing-imports",
            "--no-error-summary",
        ]
    )

    with tempfile.TemporaryDirectory(prefix="lumen-release-gate-") as tmp:
        tmp_dir = Path(tmp)
        dist_dir = tmp_dir / "dist"
        wheel_venv_dir = tmp_dir / "wheel-venv"
        sdist_venv_dir = tmp_dir / "sdist-venv"

        for package in PACKAGES:
            run([python, "-m", "build", str(package), "--outdir", str(dist_dir)])

        run([python, "-m", "twine", "check", *[str(path) for path in sorted(dist_dir.iterdir())]])

        wheels = sorted(str(path) for path in dist_dir.glob("*.whl"))
        sdists = sorted(str(path) for path in dist_dir.glob("*.tar.gz"))
        if len(wheels) != len(PACKAGES):
            raise RuntimeError(f"Expected {len(PACKAGES)} wheels, found {len(wheels)}")
        if len(sdists) != len(PACKAGES):
            raise RuntimeError(f"Expected {len(PACKAGES)} sdists, found {len(sdists)}")

        run([python, "-m", "venv", str(wheel_venv_dir)])
        wheel_python = venv_python(wheel_venv_dir)
        run([str(wheel_python), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(wheel_python), "-m", "pip", "install", *wheels])
        verify_clean_install(wheel_python, "Release gate wheel")

        run([python, "-m", "venv", str(sdist_venv_dir)])
        sdist_python = venv_python(sdist_venv_dir)
        run([str(sdist_python), "-m", "pip", "install", "--upgrade", "pip"])
        run([str(sdist_python), "-m", "pip", "install", *sdists])
        verify_clean_install(sdist_python, "Release gate sdist")

    print("\nRelease gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
