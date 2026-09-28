"""Vercel Python Function entry point for the FastAPI BFF."""

from pathlib import Path
import sys

# Vercel executes this file from api/. Add the repository root so the shared
# bff/, adapters/, competitors/, and kudu/ packages can be imported reliably.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bff.app import app  # noqa: E402

__all__ = ["app"]
