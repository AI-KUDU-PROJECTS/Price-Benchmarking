"""Configuration for the shared HungerStation collector."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_ROOT.parent.parent
load_dotenv(REPO_ROOT / ".env")
DB_PATH = Path(os.environ.get("HUNGERSTATION_DB_PATH", PROJECT_ROOT / "data" / "hungerstation.db"))
RAW_DIR = Path(os.environ.get("HUNGERSTATION_RAW_DIR", PROJECT_ROOT / "data" / "raw"))
IMAGE_DIR = Path(os.environ.get("HUNGERSTATION_IMAGE_DIR", PROJECT_ROOT / "data" / "images"))
ADB_SERIAL = os.environ.get("HUNGERSTATION_ADB_SERIAL", "emulator-5554")
LATITUDE = float(os.environ.get("HUNGERSTATION_LATITUDE", "24.7136"))
LONGITUDE = float(os.environ.get("HUNGERSTATION_LONGITUDE", "46.6753"))
UPLOAD_URL = os.environ.get("HUNGERSTATION_UPLOAD_URL", "").strip()
UPLOAD_TOKEN = os.environ.get("HUNGERSTATION_UPLOAD_TOKEN", "").strip()
DAILY_RUN_TIME = os.environ.get("HUNGERSTATION_DAILY_RUN_TIME", "23:00")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Riyadh")
ENABLE_SCHEDULER = os.environ.get("HUNGERSTATION_ENABLE_SCHEDULER", "true").strip().lower() in {"1", "true", "yes", "on"}
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
ANTHROPIC_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "medium").strip().lower()
AI_NAVIGATION_ENABLED = (
    os.environ.get("HUNGERSTATION_AI_NAVIGATION", "false").strip().lower()
    in {"1", "true", "yes", "on"}
    and bool(ANTHROPIC_API_KEY)
)
AI_MAX_ACTIONS = max(1, int(os.environ.get("HUNGERSTATION_AI_MAX_ACTIONS", "6")))
ADB_COMMAND_TIMEOUT = max(5.0, float(os.environ.get("HUNGERSTATION_ADB_TIMEOUT", "30")))


@dataclass(frozen=True)
class Restaurant:
    id: str
    name: str
    search_term: str
    aliases: tuple[str, ...]
    minimum_products: int = 10


RESTAURANTS: tuple[Restaurant, ...] = (
    Restaurant("kfc", "KFC", "kfc", ("kfc", "كنتاكي")),
    Restaurant("hardees", "Hardee's", "hardees", ("hardees", "hardee's", "هارديز")),
    Restaurant("burger-king", "Burger King", "burger king", ("burger king", "برجر كنج", "برجر كينج")),
    Restaurant("herfy", "Herfy", "herfy", ("herfy", "هرفي")),
    Restaurant("mcdonalds", "McDonald's", "mcdonalds", ("mcdonalds", "mcdonald's", "ماكدونالدز")),
    Restaurant("albaik", "AlBaik", "albaik", ("albaik", "al baik", "البيك")),
)

RESTAURANT_BY_ID = {restaurant.id: restaurant for restaurant in RESTAURANTS}
