"""Run the local release gate used before publishing LumenAI packages."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def main() -> int:
    python = sys.executable

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
        venv_dir = tmp_dir / "venv"

        for package in PACKAGES:
            run([python, "-m", "build", str(package), "--wheel", "--outdir", str(dist_dir)])

        run([python, "-m", "venv", str(venv_dir)])
        clean_python = venv_python(venv_dir)
        run([str(clean_python), "-m", "pip", "install", "--upgrade", "pip"])

        wheels = sorted(str(path) for path in dist_dir.glob("*.whl"))
        if len(wheels) != len(PACKAGES):
            raise RuntimeError(f"Expected {len(PACKAGES)} wheels, found {len(wheels)}")

        run([str(clean_python), "-m", "pip", "install", *wheels])
        run([str(clean_python), "-m", "pip", "check"])
        run(
            [
                str(clean_python),
                "-c",
                (
                    "import lumen_ai; import lumen_ai.models; "
                    "from lumen_ai import LumenAI, JsonlExporter, lumen_tenant; "
                    "from lumen_ai_celery import CeleryInstrumentor; "
                    "from lumen_ai_openlit import OpenLITBridge; "
                    "print('Release gate import OK')"
                ),
            ]
        )

    print("\nRelease gate OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
