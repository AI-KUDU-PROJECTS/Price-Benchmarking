"""
backend/normalizer.py
---------------------------------------------------------------------
Turns one raw product object from the Node collector's menu-ref CDN JSON
walk (see research/api-map/api-map.md) into the normalized dict
backend/database.py's product_snapshots table expects, plus the stable
identity keys used for change detection.

Product identity (see README "Product Identity"):
  - Primary: the Solo platform's own numeric item `id` (stable across
    runs - a real catalog id, not a generated one).
  - Fallback (used only if `id` is missing/blank): normalized name +
    normalized category.
  - canonical_product_key = f"{branch_id}|{channel}|{identity}" is what
    change_detector.py joins across runs.

Unlike Burger King (no price field anywhere) and closer to KFC's
originalPrice/specialPrice pair, Herfy's menu-ref response carries THREE
price-shaped fields per item: `price`, `list-price`, `original-price`.
Live-confirmed across the full 144-item menu (2026-08-11): `list-price`
was `0` and `price == original-price` on every single item, with zero
exceptions - i.e. there is currently no ACTIVE discount anywhere on the
menu, but the field structure clearly supports one (`original-price` read
as the regular/reference price, `price` as the current/possibly-discounted
selling price) - see normalize_product()'s regular_price/special_price
logic below, which is real field-structure-based logic, not a guess, and
will start reporting a genuine discount automatically the moment Herfy
ever puts one live, with no code change needed. `list-price`'s exact
purpose was not confirmed (always 0 at verification time) - kept in
raw_api_json for forensic reference, never used to compute anything.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Optional

CURRENCY_DEFAULT = "SAR"  # confirmed live: concept.currency-code == "SAR" for every product

_SIZE_NAMES = {"regular", "medium", "large"}


def normalize_text(value: Optional[str]) -> str:
    """Lowercase, strip accents/diacritics, collapse whitespace, drop
    punctuation - used for both product-name and category-name matching so
    trivial formatting differences never cause a false NEW_PRODUCT /
    PRODUCT_REMOVED pair."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9؀-ۿ]+", " ", text)
    return text.strip()


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_sizes(option_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Finds an option group explicitly named "Sizes" (a real, CMS-labeled
    group - see api-map.md, confirmed live on e.g. "Beef Tortilla Meal":
    Regular=29, Medium=32, Large=34 SAR) and returns its modifiers as
    {title, price} pairs. Returns [] if no such group exists on this
    product - never guessed from the product's own name/description."""
    for group in option_groups or []:
        if normalize_text(group.get("name")) == "sizes":
            return [
                {"title": m.get("name"), "price": m.get("price")}
                for m in group.get("modifiers") or []
                if m.get("name")
            ]
    return []


def canonical_product_identity(product_id: Any, product_name: Optional[str], category_name: Optional[str]) -> str:
    pid = str(product_id).strip() if product_id not in (None, "") else ""
    if pid:
        return f"id:{pid}"
    return f"name:{normalize_text(product_name)}|cat:{normalize_text(category_name)}"


def canonical_product_key(branch_id: int, channel: str, product_id: Any, product_name: Optional[str], category_name: Optional[str]) -> str:
    identity = canonical_product_identity(product_id, product_name, category_name)
    return f"{branch_id}|{channel}|{identity}"


def normalize_product(
    product: dict[str, Any],
    *,
    channel: str,
    branch_id: int,
    branch_name: str,
    city: str,
    cluster_id: Optional[str],
    config_id: Optional[str],
    run_id: str,
    captured_at: str,
    source_endpoint: str = "menu-ref",
) -> dict[str, Any]:
    """Returns a dict with exactly the columns backend/database.py's
    product_snapshots table expects, plus a few extra keys the ingestion
    code reads before insert but does not store verbatim."""
    product_id = product.get("id")
    category_id = product.get("__categoryId")
    category_name_en = product.get("__categoryName")
    name_obj = product.get("name") or {}
    name_en = name_obj.get("en-us") if isinstance(name_obj, dict) else None
    name_ar = name_obj.get("ar-sa") if isinstance(name_obj, dict) else None
    desc_obj = product.get("description") or {}
    description_en = desc_obj.get("en-us") if isinstance(desc_obj, dict) else None
    description_ar = desc_obj.get("ar-sa") if isinstance(desc_obj, dict) else None

    # See module docstring - real field-structure-based discount logic,
    # not a guess: `original-price` is the regular/reference price,
    # `price` is the current selling price. Every item observed live has
    # price == original-price (no active discount), but this correctly
    # reports one the moment either field ever diverges.
    price = to_float(product.get("price"))
    original_price = to_float(product.get("original-price"))
    regular_price = original_price if original_price is not None else price
    special_price = price if (price is not None and regular_price is not None and price < regular_price) else None
    effective_price = special_price if special_price is not None else regular_price
    discount_amount = round(regular_price - special_price, 2) if (special_price is not None and regular_price is not None) else None
    discount_percentage = round((discount_amount / regular_price) * 100, 2) if (discount_amount and regular_price) else None

    option_groups = product.get("__optionGroups") or []
    sizes = extract_sizes(option_groups)
    canonical_key = canonical_product_key(branch_id, channel, product_id, name_en, category_name_en)

    raw_copy = {k: v for k, v in product.items() if not k.startswith("__")}

    return {
        "run_id": run_id,
        "product_key": canonical_key,
        "product_id": str(product_id) if product_id is not None else None,
        "channel": channel,
        "branch_id": branch_id,
        "branch_name": branch_name,
        "city": city,
        "cluster_id": cluster_id,
        "config_id": config_id,
        "captured_at": captured_at,
        "sku": product.get("code"),  # a real slug-style SKU, e.g. "beef-tortilla-meal" - see api-map.md
        "product_name_en": name_en,
        "product_name_ar": name_ar,
        "normalized_name": normalize_text(name_en),
        "category_id": str(category_id) if category_id is not None else None,
        "category_name_en": category_name_en,
        "category_name_ar": product.get("__categoryNameAr"),
        "description_en": description_en,
        "description_ar": description_ar,
        "currency": CURRENCY_DEFAULT,
        "regular_price": regular_price,
        "special_price": special_price,
        "effective_price": effective_price,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "promo_id": None,  # no promo/coupon id signal exists at the catalog level - see api-map.md
        "limited_offer": 1 if product.get("has-timed-event") else 0,  # a real structural flag (always False at verification time), not guessed
        "product_type": "combo" if product.get("is-combo") else "item",
        "bundle_type_id": "combo" if product.get("is-combo") else None,
        "availability": 1 if product.get("enabled") else 0,
        "image_url": product.get("image-uri"),
        "product_url": None,  # SPA, no confirmed stable per-product deep link - see api-map.md
        "calories": product.get("calories") or (str(product["calorie-count"]) if product.get("calorie-count") else None),
        "variants": json.dumps([], ensure_ascii=False),
        "sizes": json.dumps(sizes, ensure_ascii=False),
        "option_groups": json.dumps(option_groups, ensure_ascii=False),
        "included_items": json.dumps([], ensure_ascii=False),
        "sides": json.dumps([], ensure_ascii=False),
        "drinks": json.dumps([], ensure_ascii=False),
        "sauces": json.dumps([], ensure_ascii=False),
        "add_ons": json.dumps([], ensure_ascii=False),
        "raw_api_json": json.dumps(raw_copy, ensure_ascii=False),
        "source_endpoint": source_endpoint,
    }
