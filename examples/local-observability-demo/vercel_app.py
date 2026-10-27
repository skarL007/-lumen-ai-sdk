"""
Vercel entry point for the hosted demo (see ``vercel.json`` at the repo root).

Serverless functions share no disk between calls, so the demo runs with the
per-request store: each request runs the real SDK and returns the events it
exported, and the browser keeps them. The SDK is imported from this checkout,
not from PyPI, so the hosted demo always matches the code next to it.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1] / "packages" / "lumen-ai-core" / "src"), str(HERE)]
os.environ.setdefault("LUMEN_DEMO_STORE", "memory")

from main import app  # noqa: E402

__all__ = ["app"]
