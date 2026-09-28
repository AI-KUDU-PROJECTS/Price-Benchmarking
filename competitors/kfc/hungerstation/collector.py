"""Collect KFC prices from the open HungerStation Android screen.

The collector uses Android's accessibility hierarchy through ADB. Open the
KFC restaurant menu in the emulator before running this module. Every run is
stored as a historical snapshot in the KFC SQLite database.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from competitors.kfc.backend import config, database

CHANNEL = "HUNGERSTATION"
SOURCE = "hungerstation"
RESTAURANT = "KFC"


def _adb_candidates() -> Iterable[Path]:
    executable = shutil.which("adb")
    if executable:
        yield Path(executable)
    for home_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = __import__("os").environ.get(home_var)
        if value:
            yield Path(value) / "platform-tools" / ("adb.exe" if __import__("os").name == "nt" else "adb")
    yield from Path("/mnt/c/Users").glob("*/AppData/Local/Android/Sdk/platform-tools/adb.exe")


def find_adb(explicit: str | None = None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"ADB was not found at {candidate}")
    for candidate in _adb_candidates():
        if candidate.exists():
            return candidate
    raise FileNotFoundError("ADB was not found. Install Android SDK Platform Tools or pass --adb.")


def _run_adb(adb: Path, serial: str, *args: str) -> str:
    completed = subprocess.run(
        [str(adb), "-s", serial, *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def _swipe(adb: Path, serial: str, start_y: int, end_y: int) -> None:
    _run_adb(adb, serial, "shell", "input", "swipe", "540", str(start_y), "540", str(end_y), "500")
    time.sleep(0.7)


def _dump(adb: Path, serial: str) -> str:
    output = _run_adb(adb, serial, "exec-out", "uiautomator", "dump", "/dev/tty")
    end = output.rfind("</hierarchy>")
    if end < 0:
        raise RuntimeError("Android returned an incomplete UI hierarchy")
    return output[: end + len("</hierarchy>")]


def _labels_from_xml(xml: str) -> list[tuple[str, str]]:
    root = ET.fromstring(xml)
    labels: list[tuple[str, str]] = []
    for node in root.iter("node"):
        label = (node.attrib.get("content-desc") or "").strip()
        if label:
            labels.append((node.attrib.get("resource-id") or "", label))
    return labels


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value or uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:12]


def parse_accessibility_label(label: str, resource_id: str = "") -> dict[str, Any] | None:
    parts = [part.strip() for part in label.splitlines() if part.strip()]
    if not parts or (parts[0].casefold() == "kfc" and "Min. Order" in parts):
        return None
    try:
        currency_at = next(i for i, part in enumerate(parts) if part in {"§", "SAR", "ر.س"})
    except StopIteration:
        return None
    if currency_at < 1 or currency_at + 1 >= len(parts):
        return None
    try:
        current_price = float(parts[currency_at + 1].replace(",", ""))
    except ValueError:
        return None

    metadata = re.compile(r"^(?:\d+(?:\.\d+)?%|\d+\+? orders|Bestseller|Top Rated)$", re.I)
    pre_price = parts[:currency_at]
    name = next((part for part in pre_price if not metadata.match(part)), None)
    if not name:
        return None
    description_parts = [
        part for part in pre_price
        if part != name and not metadata.match(part) and part.casefold() != "description undefined"
    ]
    calorie_text = next((part for part in description_parts if re.fullmatch(r"[\d,]+\s*kcal", part, re.I)), None)
    calories = int(re.sub(r"\D", "", calorie_text)) if calorie_text else None
    description = " ".join(part for part in description_parts if part != calorie_text) or None

    original_price = None
    for index in range(currency_at + 2, len(parts) - 1):
        if parts[index] in {"§", "SAR", "ر.س"}:
            try:
                original_price = float(parts[index + 1].replace(",", ""))
            except ValueError:
                pass
            break
    discount_text = next((part for part in parts if re.fullmatch(r"\d+(?:\.\d+)?%", part)), None)
    discount = float(discount_text.rstrip("%")) if discount_text else None
    source_product_id = f"HUNGERSTATION|KFC|{_slug(name)}"
    return {
        "source_product_id": source_product_id,
        "name_en": name,
        "description_en": description,
        "category_name_en": "HungerStation Menu",
        "currency": "SAR",
        "regular_price": original_price if original_price is not None else current_price,
        "special_price": current_price if original_price is not None else None,
        "effective_price": current_price,
        "discount_percentage": discount,
        "calories": calories,
        "availability": 1,
        "image_url": None,
        "raw_label": label,
        "is_summary_card": resource_id.startswith("gridMenuCell-"),
    }


def _deduplicate(labels: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for resource_id, label in labels:
        item = parse_accessibility_label(label, resource_id)
        if item is None:
            continue
        key = item["name_en"].casefold()
        previous = by_name.get(key)
        if previous is None or (previous["is_summary_card"] and not item["is_summary_card"]):
            by_name[key] = item
    return sorted(by_name.values(), key=lambda item: item["name_en"].casefold())


def collect(adb: Path, serial: str, *, max_pages: int = 45) -> tuple[list[dict[str, Any]], list[str]]:
    for _ in range(8):
        _swipe(adb, serial, 650, 1950)
    pages: list[str] = []
    labels: list[tuple[str, str]] = []
    previous_signature = ""
    repeated = 0
    for _ in range(max_pages):
        xml = _dump(adb, serial)
        pages.append(xml)
        page_labels = _labels_from_xml(xml)
        labels.extend(page_labels)
        signature = "|".join(label for resource_id, label in page_labels if resource_id.startswith("gridMenuCell-") or "\n§\n" in label)
        repeated = repeated + 1 if signature and signature == previous_signature else 0
        if repeated >= 2:
            break
        previous_signature = signature
        _swipe(adb, serial, 1910, 610)
    return _deduplicate(labels), pages


def load_capture(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    labels: list[tuple[str, str]] = []
    for page in payload.get("pages", []):
        labels.extend(("", label) for label in page.get("descriptions", []))
    if not labels:
        for item in payload.get("items", []):
            label = item.get("raw_accessibility_label") or item.get("raw_label")
            if label:
                labels.append((item.get("source_id", ""), label))
    return _deduplicate(labels)


def save_snapshot(
    items: list[dict[str, Any]],
    *,
    db_path: Path = config.DB_PATH,
    captured_at: str | None = None,
    raw_capture_path: str | None = None,
) -> str:
    if not items:
        raise ValueError("No HungerStation menu products were found")
    captured_at = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = f"hungerstation-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO external_channel_runs (
                run_id, channel, source, restaurant_name, branch_name,
                started_at, finished_at, status, product_count, raw_capture_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'SUCCESS', ?, ?)
            """,
            (run_id, CHANNEL, SOURCE, RESTAURANT, "HungerStation", captured_at, captured_at, len(items), raw_capture_path),
        )
        for item in items:
            conn.execute(
                """
                INSERT INTO external_channel_products (
                    run_id, source_product_id, channel, source, restaurant_name,
                    name_en, description_en, category_name_en, currency,
                    regular_price, special_price, effective_price, discount_percentage,
                    calories, availability, image_url, captured_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, item["source_product_id"], CHANNEL, SOURCE, RESTAURANT,
                    item["name_en"], item.get("description_en"), item.get("category_name_en"),
                    item.get("currency", "SAR"), item.get("regular_price"), item.get("special_price"),
                    item.get("effective_price"), item.get("discount_percentage"), item.get("calories"),
                    item.get("availability", 1), item.get("image_url"), captured_at,
                    json.dumps(item, ensure_ascii=False),
                ),
            )
    return run_id


def collect_and_save(
    *,
    serial: str = "emulator-5554",
    adb_path: str | None = None,
    db_path: Path = config.DB_PATH,
) -> dict[str, Any]:
    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    items, pages = collect(find_adb(adb_path), serial)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_path = config.RAW_DATA_DIR / f"hungerstation_kfc_{stamp}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        json.dumps(
            {
                "collected_at": captured_at,
                "source": SOURCE,
                "restaurant": RESTAURANT,
                "items": items,
                "pages": pages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    run_id = save_snapshot(
        items,
        db_path=db_path,
        captured_at=captured_at,
        raw_capture_path=str(raw_path),
    )
    return {
        "run_id": run_id,
        "channel": SOURCE,
        "product_count": len(items),
        "database": str(db_path),
        "raw_capture": str(raw_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554", help="ADB device serial")
    parser.add_argument("--adb", help="Path to adb or adb.exe")
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="KFC SQLite database")
    parser.add_argument("--from-capture", type=Path, help="Import an existing raw capture JSON")
    args = parser.parse_args()

    captured_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_path: Path | None = None
    if args.from_capture:
        items = load_capture(args.from_capture)
        raw_path = args.from_capture
        run_id = save_snapshot(items, db_path=args.db, captured_at=captured_at, raw_capture_path=str(raw_path))
        result = {"run_id": run_id, "channel": SOURCE, "product_count": len(items), "database": str(args.db)}
    else:
        result = collect_and_save(serial=args.serial, adb_path=args.adb, db_path=args.db)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
