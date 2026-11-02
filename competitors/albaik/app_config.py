"""Settings for the official ALBAIK Android app collector."""
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parents[1] / ".env")
PACKAGE = "com.albaik.customer"
ACTIVITY = f"{PACKAGE}/com.albaikapp.MainActivity"
ADB_SERIAL = os.getenv("ALBAIK_ADB_SERIAL", os.getenv("HUNGERSTATION_ADB_SERIAL", "emulator-5554"))
EMULATOR_SERVICE = os.getenv("ALBAIK_EMULATOR_SERVICE", os.getenv("HUNGERSTATION_EMULATOR_SERVICE", "android-emulator.service"))
DB_PATH = Path(os.getenv("ALBAIK_DB_PATH", ROOT / "data/database/albaik_monitor.db"))
RAW_DIR = Path(os.getenv("ALBAIK_RAW_DIR", ROOT / "data/raw"))
IMAGE_DIR = Path(os.getenv("ALBAIK_IMAGE_DIR", ROOT / "data/images"))
# Local stable branch key; actual selected branch is verified against app evidence.
BRANCH_ID = 1
BRANCH_NAME = "Orubah"
BRANCH_ALIASES = ("arubah", "orubah", "oruba", "urubah", "العروبة")
# Near ALBAIK-ORUBAH, verified against albaik.com/branches.
LATITUDE = float(os.getenv("ALBAIK_LATITUDE", "24.70265"))
LONGITUDE = float(os.getenv("ALBAIK_LONGITUDE", "46.65075"))
# Explicit user-requested exception: this detail page stalls in Delivery.
# Keep the independently verified pickup product.
EXCLUDED_PRODUCTS = {"DELIVERY": frozenset({"BAIKEEZ Burger with Lahaleebo Sauce"})}
# User approved skipping other delivery details that fail to open twice,
# provided every skipped name is reported with the collection result.
SKIP_UNREADABLE_CHANNELS = frozenset({"DELIVERY"})
