"""
playwright_browsers.py
---------------------------------------------------------------------
Pins Playwright browser binaries to a stable repo-local directory so
collectors never re-download Chromium just because the agent/shell
redirected PLAYWRIGHT_BROWSERS_PATH into /tmp (Cursor sandbox cache).

Usage from each competitor's backend/run_service.py::_invoke_node:

    from playwright_browsers import node_env
    subprocess.run(..., env=node_env())
---------------------------------------------------------------------
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, MutableMapping, Optional

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_BROWSERS_DIR = REPO_ROOT / ".playwright-browsers"


def browsers_path() -> Path:
    """Stable install dir. PRICE_INTEL_PLAYWRIGHT_BROWSERS overrides if set."""
    override = os.environ.get("PRICE_INTEL_PLAYWRIGHT_BROWSERS")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_BROWSERS_DIR


def node_env(base: Optional[Mapping[str, str]] = None) -> MutableMapping[str, str]:
    """os.environ copy with PLAYWRIGHT_BROWSERS_PATH forced to the stable dir."""
    env: MutableMapping[str, str] = dict(base if base is not None else os.environ)
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path())
    return env
