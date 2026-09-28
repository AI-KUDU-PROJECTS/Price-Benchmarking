"""
backend/normalizer.py
---------------------------------------------------------------------
Turns one raw product object from getProductsByCategory (see api-map.md)
into the normalized dict backend/database.py's product_snapshots table
expects, plus the stable identity keys used for change detection.

Product identity (see README "Product Identity"):
  - Primary: the API's numeric product id.
  - Fallback (used only if the id is missing/blank): normalized name +
    normalized category.
  - canonical_product_key = f"{branch_id}|{channel}|{identity}" is what
    change_detector.py joins across runs - it is stable across a product's
    lifetime even if the branch or channel context around it changes.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Optional

CURRENCY_DEFAULT = "SAR"

# Per-channel key inside a product's `services` map (see api-map.md) - the
# closest real signal to "is this product actually available through THIS
# channel", since no explicit soldOut/available boolean exists on the
# product itself (confirmed absent live - see api-map.json calorieNote's
# sibling note on availability).
CHANNEL_SERVICE_KEY = {
    "PICKUP": "take_away",
    "DELIVERY": "delevery",  # sic - this is the API's own (mis-)spelling, not a typo here
}


def normalize_text(value: Optional[str]) -> str:
    """Lowercase, strip accents/diacritics, collapse whitespace, drop
    punctuation - used for both product-name and category-name matching so
    trivial formatting differences ("Zinger  Burger" vs "zinger burger!")
    never cause a false NEW_PRODUCT / PRODUCT_REMOVED pair."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9؀-ۿ]+", " ", text)
    return text.strip()


def parse_percentage(value: Any) -> Optional[float]:
    """disPercentage arrives as a string like '33% OFF' - extract the
    number defensively; returns None (never a guess) if no number is found."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_bool_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return False


def normalize_promo_id(raw: Any) -> Optional[str]:
    """A product's promoId sentinel for "no active promotion" is `-1`, not
    `0` or blank as might be assumed (live-confirmed 2026-08-05: 37 of 106
    sampled products all carried promoId=-1 with no specialPrice/discount,
    while every product with a genuine active discount carried a distinct
    positive integer). Category-level promoId uses `0` as its "no promo"
    sentinel instead (a different field on a different object) - this
    helper is for PRODUCT-level promoId only."""
    if raw in (None, "", 0, "0", -1, "-1"):
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return str(raw)
    return str(n) if n > 0 else None


def normalize_special_price(special_price_raw: Any, regular_price: Optional[float]) -> Optional[float]:
    """A product's specialPrice sentinel for "not a simple fixed-discount
    price" is `0`, not just absent (live-confirmed 2026-08-05: 28/106
    sampled products - all build-your-own "Combo"/"Box" bundle upsells with
    a real positive promoId but an EMPTY disPercentage - carried
    specialPrice=0 with a real, non-trivial originalPrice; a genuine $0
    price for a $19+ combo is not plausible). Also guards the case where
    specialPrice is present but not actually lower than originalPrice."""
    special_price = to_float(special_price_raw)
    if special_price is None or special_price <= 0:
        return None
    if regular_price is not None and special_price >= regular_price:
        return None
    return special_price


def first_present(product: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in product and product[key] not in (None, ""):
            return product[key]
    return None


def extract_image_url(product: dict[str, Any]) -> Optional[str]:
    assets = product.get("assets") or []
    if isinstance(assets, list) and assets:
        first = assets[0]
        if isinstance(first, dict):
            return first.get("src")
    return first_present(product, "mediaUrl", "imageUrl")


def _item_price_for_size(item: dict[str, Any]) -> Optional[float]:
    """Selling price for one nested size SKU from items[]. Uses the same
    specialPrice sentinel rules as the card-level product price."""
    regular = to_float(item.get("originalPrice"))
    special = normalize_special_price(item.get("specialPrice"), regular)
    return special if special is not None else regular


def _items_by_sel1(product: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index items[] by sel1Value (stringified) so each variants[].options[].id
    can be joined to its nested size SKU. Same Americana platform join as
    Hardee's: option.id === item.sel1Value carries that size's originalPrice."""
    index: dict[str, dict[str, Any]] = {}
    for item in product.get("items") or []:
        if not isinstance(item, dict):
            continue
        sel = item.get("sel1Value")
        if sel is None or sel == "":
            continue
        index[str(sel)] = item
    return index


def extract_sizes(product: dict[str, Any]) -> list[dict[str, Any]]:
    """variants[].options[] identifies size WITH CONFIDENCE (see api-map.md).
    When items[] is present, join each option.id to items[].sel1Value and
    attach that nested SKU's selling price so dashboards/Excel can show
    Regular/Medium/Large prices - not only the selected size's card price.
    Returns [] (never a guess) when the product has no size variant. Price
    stays omitted (not invented) when no matching items[] row exists."""
    items_index = _items_by_sel1(product)
    sizes: list[dict[str, Any]] = []
    for variant in product.get("variants") or []:
        if not isinstance(variant, dict):
            continue
        for option in variant.get("options") or []:
            if not isinstance(option, dict) or not option.get("title"):
                continue
            entry: dict[str, Any] = {
                "id": option.get("id"),
                "title": option.get("title"),
                "isSelected": bool(option.get("isSelected")),
                "variantTitle": variant.get("title"),
            }
            item = items_index.get(str(option.get("id"))) if option.get("id") is not None else None
            if item is not None:
                price = _item_price_for_size(item)
                if price is not None:
                    entry["price"] = price
                nested_id = item.get("id")
                if nested_id is not None:
                    entry["nestedItemId"] = nested_id
            sizes.append(entry)
    return sizes


def compute_availability(product: dict[str, Any], channel: str) -> bool:
    services = product.get("services")
    if isinstance(services, dict):
        key = CHANNEL_SERVICE_KEY.get(channel)
        if key and key in services:
            return to_bool_flag(services[key])
    # No per-channel signal on this product - it was returned by this
    # channel's getProductsByCategory call at all, so default to available.
    return True


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
    source_endpoint: str = "/api/getProductsByCategory",
) -> dict[str, Any]:
    """Returns a dict with exactly the columns backend/database.py's
    product_snapshots table expects, plus a few extra keys
    (canonical_product_key, category_id, is_offer) that database.py's
    ingestion code reads before insert but does not store verbatim."""
    from competitors.kfc.backend.offer_parser import classify_components  # local import: avoids a circular import at module load time

    product_id = product.get("id")
    category_id = product.get("__categoryId")
    category_name_en = product.get("__categoryName")
    name_en = first_present(product, "name", "metaTitle")
    description_en = first_present(product, "description", "longDesc", "shortDesc")

    regular_price = to_float(first_present(product, "originalPrice", "price", "basePrice"))
    special_price = normalize_special_price(product.get("specialPrice"), regular_price)

    effective_price = special_price if special_price is not None else regular_price
    discount_amount = round(regular_price - special_price, 2) if (regular_price is not None and special_price is not None) else None
    discount_percentage = parse_percentage(product.get("disPercentage"))
    if discount_percentage is None and discount_amount is not None and regular_price:
        discount_percentage = round((discount_amount / regular_price) * 100, 2)

    promo_id = normalize_promo_id(product.get("promoId"))

    components = classify_components(product.get("steps") or [], product.get("subOptionStr"))

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
        "sku": str(product.get("sku")) if product.get("sku") not in (None, "") else None,
        "product_name_en": name_en,
        "product_name_ar": first_present(product, "name_ar", "nameAr"),
        "normalized_name": normalize_text(name_en),
        "category_id": str(category_id) if category_id is not None else None,
        "category_name_en": category_name_en,
        "category_name_ar": first_present(product, "category_name_ar"),
        "description_en": description_en,
        "description_ar": first_present(product, "description_ar"),
        "currency": product.get("currency") or CURRENCY_DEFAULT,
        "regular_price": regular_price,
        "special_price": special_price,
        "effective_price": effective_price,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "promo_id": promo_id,
        "limited_offer": 1 if to_bool_flag(product.get("limited_offer")) else 0,
        "product_type": str(product.get("typeId")) if product.get("typeId") not in (None, "") else None,
        "bundle_type_id": product.get("bundleTypeId"),
        "availability": 1 if compute_availability(product, channel) else 0,
        "image_url": extract_image_url(product),
        "product_url": None,  # see api-map.md - no confirmed per-product deep link exists; left NULL rather than guessed
        "calories": first_present(product, "calories", "kcal", "energy"),
        "variants": json.dumps(product.get("variants") or [], ensure_ascii=False),
        "sizes": json.dumps(extract_sizes(product), ensure_ascii=False),
        "option_groups": json.dumps(product.get("steps") or [], ensure_ascii=False),
        "included_items": json.dumps(components["included_items"], ensure_ascii=False),
        "sides": json.dumps(components["sides"], ensure_ascii=False),
        "drinks": json.dumps(components["drinks"], ensure_ascii=False),
        "sauces": json.dumps(components["sauces"], ensure_ascii=False),
        "add_ons": json.dumps(components["add_ons"], ensure_ascii=False),
        "raw_api_json": json.dumps(raw_copy, ensure_ascii=False),
        "source_endpoint": source_endpoint,
    }
