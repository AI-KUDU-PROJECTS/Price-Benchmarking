"""Small, validated on-disk snapshot of the KUDU production menu."""
from __future__ import annotations

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"
CHANNELS = ("delivery", "pickup")
ITEM_FIELDS = (
    "itemId", "nameArabic", "nameEnglish", "price", "itemImageUrl",
    "isCustomizedPrice", "drinkItemPrice", "friesItemPrice",
    "descriptionArabic", "descriptionEnglish", "calories", "isAvailable",
    "isPublish", "isHidden", "status", "updatedAt",
)
MENU_FIELDS = ("menuId", "titleArabic", "titleEnglish", "displayOrder")


class CatalogValidationError(ValueError):
    """A controlled, user-facing reason for retaining the previous snapshot."""


def is_special_offers(menu: dict[str, Any]) -> bool:
    return (
        str(menu.get("titleEnglish") or "").strip().casefold() == "special offers"
        or str(menu.get("titleArabic") or "").strip() == "العروض الخاصة"
    )


def _menu_order(menu: dict[str, Any]) -> tuple[bool, str]:
    # Stable across API ordering/display-order changes. Prefer a regular menu,
    # then the lexicographically smallest menu ID when several qualify.
    return is_special_offers(menu), str(menu["menuId"])


def _resolve_occurrences(channel: str, item_id: str, occurrences: list[dict]) -> dict:
    """Select one whole record, retaining category variants without double counts."""
    occurrences.sort(key=lambda occurrence: _menu_order(occurrence["menu"]))
    chosen = occurrences[0]
    if len(occurrences) == 1:
        return chosen

    context = (
        f"KUDU {channel} item {item_id} in menus "
        + ", ".join(str(entry["menu"]["menuId"]) for entry in occurrences)
    )

    def money(item: dict, field: str, *, optional: bool = False) -> Decimal:
        value = item.get(field)
        if value is None and optional:
            return Decimal(0)
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise CatalogValidationError(f"{context}: cannot compare invalid {field}.") from None
        if not amount.is_finite() or amount < 0:
            raise CatalogValidationError(f"{context}: cannot compare invalid {field}.")
        return amount

    def pricing(item: dict) -> tuple:
        signature = (money(item, "price"),)
        # Delivery price already includes the meal; pickup adds default sides.
        # Compare components, not just totals: swapped drink/fries prices are
        # still ambiguous. Missing/None sides mean zero, as in the adapter.
        if channel == "pickup":
            customized = item.get("isCustomizedPrice")
            if customized is not None and not isinstance(customized, bool):
                raise CatalogValidationError(f"{context}: invalid isCustomizedPrice.")
            signature += (customized is True,)
            if customized is True:
                signature += (money(item, "drinkItemPrice", optional=True),
                              money(item, "friesItemPrice", optional=True))
        return signature

    expected = pricing(chosen["item"])
    for entry in occurrences[1:]:
        if pricing(entry["item"]) != expected:
            fields = "price or pickup default drink/fries settings" if channel == "pickup" else "price"
            raise CatalogValidationError(f"{context}: conflicting {fields}; no safe product price can be selected.")

    # Preserve each source image, description and pricing configuration for
    # audit and category membership. Never blend fields from different menus.
    return {"menu": chosen["menu"], "item": {**chosen["item"], "categoryVariants": occurrences}}


def normalize_catalog(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the fields used by the app; reject incomplete API collections."""
    if raw.get("templateId") != 1 or not raw.get("retrievedAtUtc"):
        raise CatalogValidationError("KUDU snapshot needs templateId=1 and retrievedAtUtc")
    source_services = raw.get("services")
    if not isinstance(source_services, dict):
        raise CatalogValidationError("KUDU snapshot has no services")

    services: dict[str, list[dict[str, Any]]] = {}
    for channel in CHANNELS:
        source_categories = source_services.get(channel)
        if not isinstance(source_categories, list) or not source_categories:
            raise CatalogValidationError(f"KUDU {channel} menu is missing")
        categories: list[dict[str, Any]] = []
        by_menu: dict[str, dict] = {}
        by_item: dict[str, list[dict]] = {}
        for entry in source_categories:
            if not isinstance(entry, dict):
                raise CatalogValidationError(f"KUDU {channel} category is incomplete")
            menu = entry.get("menu")
            items = entry.get("items")
            if not isinstance(menu, dict) or not isinstance(items, list):
                raise CatalogValidationError(f"KUDU {channel} category is incomplete")
            if menu.get("menuId") is None:
                raise CatalogValidationError(f"KUDU {channel} category has no menuId")
            menu_id = str(menu["menuId"])
            if menu_id in by_menu:
                raise CatalogValidationError(f"KUDU {channel} contains duplicate menuId {menu_id}")
            metadata = {key: menu.get(key) for key in MENU_FIELDS}
            category = {**metadata, "items": []}
            categories.append(category)
            by_menu[menu_id] = category
            within_menu: dict[str, dict] = {}
            for item in items:
                if not isinstance(item, dict) or item.get("itemId") is None:
                    raise CatalogValidationError(f"KUDU {channel} item has no itemId")
                item_id = str(item["itemId"])
                if not item.get("nameArabic") and not item.get("nameEnglish"):
                    raise CatalogValidationError(f"KUDU {channel} item {item_id} has no name")
                product = {key: item.get(key) for key in ITEM_FIELDS}
                if item_id in within_menu:
                    if product != within_menu[item_id]:
                        raise CatalogValidationError(
                            f"KUDU {channel} item {item_id}: conflicting records within menu {menu_id}."
                        )
                    continue
                within_menu[item_id] = product
                by_item.setdefault(item_id, []).append({"menu": metadata, "item": product})
        if not by_item:
            raise CatalogValidationError(f"KUDU {channel} has no products")
        for item_id, occurrences in by_item.items():
            selected = _resolve_occurrences(channel, item_id, occurrences)
            by_menu[str(selected["menu"]["menuId"])]["items"].append(selected["item"])
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
