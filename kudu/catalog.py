"""Small, validated on-disk snapshot of the KUDU production menu."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
CHANNELS = ("delivery", "pickup")


def normalize_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the fields used by the app; reject incomplete API collections."""
    if raw.get("templateId") != 1 or not raw.get("retrievedAtUtc"):
        raise ValueError("KUDU snapshot needs templateId=1 and retrievedAtUtc")
    source_services = raw.get("services")
    if not isinstance(source_services, dict):
        raise ValueError("KUDU snapshot has no services")

    services: dict[str, list[dict[str, Any]]] = {}
    for channel in CHANNELS:
        source_categories = source_services.get(channel)
        if not isinstance(source_categories, list) or not source_categories:
            raise ValueError(f"KUDU {channel} menu is missing")
        categories: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        for entry in source_categories:
            menu = entry.get("menu")
            items = entry.get("items")
            if not isinstance(menu, dict) or not isinstance(items, list):
                raise ValueError(f"KUDU {channel} category is incomplete")
            if menu.get("menuId") is None:
                raise ValueError(f"KUDU {channel} category has no menuId")
            products = []
            for item in items:
                if not isinstance(item, dict) or item.get("itemId") is None:
                    raise ValueError(f"KUDU {channel} item has no itemId")
                item_id = str(item["itemId"])
                if item_id in seen_items:
                    raise ValueError(f"KUDU {channel} contains duplicate itemId {item_id}")
                seen_items.add(item_id)
                if not item.get("nameArabic") and not item.get("nameEnglish"):
                    raise ValueError(f"KUDU {channel} item {item_id} has no name")
                products.append({
                    key: item.get(key) for key in (
                        "itemId", "nameArabic", "nameEnglish", "price", "itemImageUrl",
                        "descriptionArabic", "descriptionEnglish", "calories", "isAvailable",
                        "isPublish", "isHidden", "status", "updatedAt",
                    )
                })
            categories.append({
                "menuId": menu["menuId"],
                "titleArabic": menu.get("titleArabic"),
                "titleEnglish": menu.get("titleEnglish"),
                "displayOrder": menu.get("displayOrder"),
                "items": products,
            })
        services[channel] = categories

    return {
        "retrievedAtUtc": raw["retrievedAtUtc"],
        "templateId": 1,
        "services": services,
    }


def save_catalog(raw: dict[str, Any], path: Path = CATALOG_PATH) -> Path:
    """Write only after both channels and every item list validated."""
    catalog = normalize_catalog(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
