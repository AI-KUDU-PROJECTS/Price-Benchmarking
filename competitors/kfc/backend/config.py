"""
competitors/kfc/backend/config.py
---------------------------------------------------------------------
Central configuration for the Python half of the KFC system (SQLite,
change detection, React/BFF, Excel export, scheduler - see
competitors/kfc/README.md). Every other competitors/kfc/backend/* module,
plus competitors/kfc/run_collector.py and competitors/kfc/scheduler.py,
import settings from here rather than
reading os.environ directly, mirroring collector/config.js's role on the
Node side.

PROJECT_ROOT is this competitor's own package root (competitors/kfc) -
every data/export/collector-script path below is scoped inside it, per
the repo's "every competitor is isolated inside its own folder" rule (see
root README.md). REPO_ROOT is only used to locate the single shared
.env file at the repository root (KFC_* variables are already namespaced,
so sharing one .env file across competitors is safe for now; each
competitor may move to its own .env under its own config/ folder later
without other competitors needing to change).
---------------------------------------------------------------------
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # competitors/kfc/
REPO_ROOT = PROJECT_ROOT.parent.parent  # repository root
load_dotenv(REPO_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- Fixed branch (must match collector/config.js's BRANCH block) ---------
# EUROMARCHE/143 - switched from RABWAH/223 when that branch was closed for
# Pickup (getNewStore returned storeId=0). EUROMARCHE was among the 2026-08-06
# candidates confirmed for both Pickup and Delivery. See api-map.md.
BRANCH_CITY = os.environ.get("KFC_CITY", "Riyadh")
BRANCH_NAME = os.environ.get("KFC_BRANCH_NAME", "EUROMARCHE")
BRANCH_STORE_ID = _int("KFC_STORE_ID", 143)
BRANCH_LATITUDE = _float("KFC_LATITUDE", 24.70453454)
BRANCH_LONGITUDE = _float("KFC_LONGITUDE", 46.66464865)
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Riyadh")

# --- Data locations (all scoped inside competitors/kfc/ - see PROJECT_ROOT
# note above; the database lives under data/database/ specifically, as
# required by the multi-competitor layout, e.g.
# competitors/kfc/data/database/kfc_monitor.db) --------------------------
DB_PATH = PROJECT_ROOT / os.environ.get("DB_PATH", "data/database/kfc_monitor.db")
RAW_DATA_DIR = PROJECT_ROOT / os.environ.get("RAW_DATA_DIR", "data/raw")
SCREENSHOTS_DIR = PROJECT_ROOT / os.environ.get("SCREENSHOTS_DIR", "data/screenshots")
EXPORTS_DIR = PROJECT_ROOT / os.environ.get("EXPORTS_DIR", "exports")
LOG_DIR = PROJECT_ROOT / os.environ.get("LOG_DIR", "data/logs")
LOCK_FILE = PROJECT_ROOT / "data" / ".collector.lock"

# --- Node collector entry points -------------------------------------------
NODE_BIN = os.environ.get("NODE_BIN", "node")
COLLECT_SCRIPT = PROJECT_ROOT / "collector" / "collect.js"
SCREENSHOT_SCRIPT = PROJECT_ROOT / "collector" / "screenshot-capture.js"
COLLECTOR_TIMEOUT_SECONDS = _int("COLLECTOR_TIMEOUT_SECONDS", 900)
SCREENSHOT_TIMEOUT_SECONDS = _int("SCREENSHOT_TIMEOUT_SECONDS", 600)
MAX_SCREENSHOTS_PER_RUN = _int("MAX_SCREENSHOTS_PER_RUN", 40)

# --- Scheduler ---------------------------------------------------------------
DAILY_RUN_TIME = os.environ.get("DAILY_RUN_TIME", "06:00")
ENABLE_SCHEDULER = _bool("ENABLE_SCHEDULER", True)
SCHEDULER_JITTER_SECONDS = _int("SCHEDULER_JITTER_SECONDS", 60)

# --- Change detection thresholds (per spec - not meant to be tuned in .env,
# but centralized here rather than as magic numbers scattered in code) -----
NOT_OBSERVED_THRESHOLD = 1   # first miss -> PRODUCT_NOT_OBSERVED / OFFER_NOT_OBSERVED
REMOVED_THRESHOLD = 3        # third consecutive miss -> PRODUCT_REMOVED / OFFER_ENDED

CHANNELS = ("PICKUP", "DELIVERY")


def ensure_directories() -> None:
    for d in (DB_PATH.parent, RAW_DATA_DIR, SCREENSHOTS_DIR, EXPORTS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
