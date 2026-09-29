"""
competitors/hardees/backend/config.py
---------------------------------------------------------------------
Central configuration for the Python half of the Hardee's system
(SQLite, change detection, Streamlit, Excel export, scheduler - see
competitors/hardees/README.md). Mirrors competitors/kfc/backend/
config.py's shape exactly - Hardee's Saudi runs on the same
Americana-operated platform as KFC (see research/api-map/api-map.md
"Shared platform note"), so the Python-side settings are namespaced the
same way BK_*/HERFY_* are: with an HRD_ prefix on the shared repo-root
.env file (see root README.md).

PROJECT_ROOT is this competitor's own package root (competitors/hardees)
- every data/export/collector-script path below is scoped inside it, per
the repo's "every competitor is isolated inside its own folder" rule.
REPO_ROOT is only used to locate the single shared .env file.
---------------------------------------------------------------------
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # competitors/hardees/
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
# EUROMARCHE-H / storeId 24 - confirmed live via getStoreList (cmsStatus=1,
# services.del=1, services.tak=1) AND both getNewStore (PICKUP) and
# validateLocation (DELIVERY) resolving back to storeId=24 for these exact
# coordinates - see research/api-map/api-map.md "Branch selection".
BRANCH_CITY = os.environ.get("HRD_CITY", "Riyadh")
BRANCH_NAME = os.environ.get("HRD_BRANCH_NAME", "EUROMARCHE-H")
BRANCH_STORE_ID = _int("HRD_STORE_ID", 24)
BRANCH_LATITUDE = _float("HRD_LATITUDE", 24.70452479)
BRANCH_LONGITUDE = _float("HRD_LONGITUDE", 46.66425169)
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Riyadh")

# --- Data locations (all scoped inside competitors/hardees/) ---------------
DB_PATH = PROJECT_ROOT / os.environ.get("HRD_DB_PATH", "data/database/hardees_monitor.db")
DEPLOYMENT_DB_PATH = REPO_ROOT / "bff" / "data" / "snapshots" / "hardees_monitor.db"
if os.environ.get("VERCEL") and DEPLOYMENT_DB_PATH.exists():
    DB_PATH = DEPLOYMENT_DB_PATH
RAW_DATA_DIR = PROJECT_ROOT / os.environ.get("HRD_RAW_DATA_DIR", "data/raw")
SCREENSHOTS_DIR = PROJECT_ROOT / os.environ.get("HRD_SCREENSHOTS_DIR", "data/screenshots")
EXPORTS_DIR = PROJECT_ROOT / os.environ.get("HRD_EXPORTS_DIR", "exports")
LOG_DIR = PROJECT_ROOT / os.environ.get("HRD_LOG_DIR", "data/logs")
LOCK_FILE = PROJECT_ROOT / "data" / ".collector.lock"

# --- Node collector entry points -------------------------------------------
NODE_BIN = os.environ.get("NODE_BIN", "node")
COLLECT_SCRIPT = PROJECT_ROOT / "collector" / "collect.js"
SCREENSHOT_SCRIPT = PROJECT_ROOT / "collector" / "screenshot-capture.js"
COLLECTOR_TIMEOUT_SECONDS = _int("COLLECTOR_TIMEOUT_SECONDS", 900)
SCREENSHOT_TIMEOUT_SECONDS = _int("SCREENSHOT_TIMEOUT_SECONDS", 600)
MAX_SCREENSHOTS_PER_RUN = _int("MAX_SCREENSHOTS_PER_RUN", 40)

# --- Scheduler ---------------------------------------------------------------
DAILY_RUN_TIME = os.environ.get("HRD_DAILY_RUN_TIME", "07:00")
ENABLE_SCHEDULER = _bool("HRD_ENABLE_SCHEDULER", True)
SCHEDULER_JITTER_SECONDS = _int("SCHEDULER_JITTER_SECONDS", 60)

# --- Change detection thresholds (per spec - not meant to be tuned in .env,
# but centralized here rather than as magic numbers scattered in code) -----
NOT_OBSERVED_THRESHOLD = 1   # first miss -> PRODUCT_NOT_OBSERVED / OFFER_NOT_OBSERVED
REMOVED_THRESHOLD = 3        # third consecutive miss -> PRODUCT_REMOVED / OFFER_ENDED

CHANNELS = ("PICKUP", "DELIVERY")


def ensure_directories() -> None:
    for d in (DB_PATH.parent, RAW_DATA_DIR, SCREENSHOTS_DIR, EXPORTS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
