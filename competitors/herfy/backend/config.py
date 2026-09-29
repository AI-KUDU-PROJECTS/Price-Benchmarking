"""
competitors/herfy/backend/config.py
---------------------------------------------------------------------
Central configuration for the Python half of the Herfy system (SQLite,
change detection, Streamlit, Excel export, scheduler - see
competitors/herfy/README.md). Mirrors competitors/kfc's and
competitors/burger_king's backend/config.py shape exactly - every other
backend/* module, plus run_collector.py/scheduler.py/dashboard/page.py,
import settings from here rather than reading os.environ directly.

PROJECT_ROOT is this competitor's own package root (competitors/herfy) -
every data/export/collector-script path below is scoped inside it, per
the repo's "every competitor is isolated inside its own folder" rule (see
root README.md). REPO_ROOT only locates the shared .env file at the
repository root (HERFY_* variables are namespaced, so sharing one .env
file across competitors is safe).
---------------------------------------------------------------------
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # competitors/herfy/
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
# RUH - Al Mogarazat - Eirad Plaza Mall 1073 / locationId 29696 - confirmed
# live via GET /locations/29696 to have status="active", is-open=true,
# is-open-pickup=true, is-open-deliver=true, pickup-enabled=1,
# delivery-enabled=1. See research/api-map/api-map.md "Branch selection".
BRANCH_CITY = os.environ.get("HERFY_CITY", "Riyadh")
BRANCH_NAME = os.environ.get("HERFY_BRANCH_NAME", "RUH - Al Mogarazat - Eirad Plaza Mall 1073")
BRANCH_STORE_ID = _int("HERFY_LOCATION_ID", 29696)
BRANCH_LATITUDE = _float("HERFY_LATITUDE", 24.76017)
BRANCH_LONGITUDE = _float("HERFY_LONGITUDE", 46.717525)
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Riyadh")

# --- Data locations (all scoped inside competitors/herfy/) -----------------
DB_PATH = PROJECT_ROOT / os.environ.get("HERFY_DB_PATH", "data/database/herfy_monitor.db")
DEPLOYMENT_DB_PATH = REPO_ROOT / "bff" / "data" / "snapshots" / "herfy_monitor.db"
if os.environ.get("VERCEL") and DEPLOYMENT_DB_PATH.exists():
    DB_PATH = DEPLOYMENT_DB_PATH
RAW_DATA_DIR = PROJECT_ROOT / os.environ.get("HERFY_RAW_DATA_DIR", "data/raw")
SCREENSHOTS_DIR = PROJECT_ROOT / os.environ.get("HERFY_SCREENSHOTS_DIR", "data/screenshots")
EXPORTS_DIR = PROJECT_ROOT / os.environ.get("HERFY_EXPORTS_DIR", "exports")
LOG_DIR = PROJECT_ROOT / os.environ.get("HERFY_LOG_DIR", "data/logs")
LOCK_FILE = PROJECT_ROOT / "data" / ".collector.lock"

# --- Node collector entry points -------------------------------------------
NODE_BIN = os.environ.get("NODE_BIN", "node")
COLLECT_SCRIPT = PROJECT_ROOT / "collector" / "collect.js"
SCREENSHOT_SCRIPT = PROJECT_ROOT / "collector" / "screenshot-capture.js"
COLLECTOR_TIMEOUT_SECONDS = _int("COLLECTOR_TIMEOUT_SECONDS", 900)
SCREENSHOT_TIMEOUT_SECONDS = _int("SCREENSHOT_TIMEOUT_SECONDS", 600)
MAX_SCREENSHOTS_PER_RUN = _int("MAX_SCREENSHOTS_PER_RUN", 40)

# --- Scheduler ---------------------------------------------------------------
DAILY_RUN_TIME = os.environ.get("HERFY_DAILY_RUN_TIME", os.environ.get("DAILY_RUN_TIME", "06:45"))
ENABLE_SCHEDULER = _bool("HERFY_ENABLE_SCHEDULER", _bool("ENABLE_SCHEDULER", True))
SCHEDULER_JITTER_SECONDS = _int("SCHEDULER_JITTER_SECONDS", 60)

# --- Change detection thresholds (centralized, not meant to be tuned in .env) ---
NOT_OBSERVED_THRESHOLD = 1  # first miss -> PRODUCT_NOT_OBSERVED / OFFER_NOT_OBSERVED
REMOVED_THRESHOLD = 3       # third consecutive miss -> PRODUCT_REMOVED / OFFER_ENDED

CHANNELS = ("PICKUP", "DELIVERY")


def ensure_directories() -> None:
    for d in (DB_PATH.parent, RAW_DATA_DIR, SCREENSHOTS_DIR, EXPORTS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
