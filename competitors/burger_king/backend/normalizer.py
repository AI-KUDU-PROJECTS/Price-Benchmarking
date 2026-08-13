"""
backend/normalizer.py
---------------------------------------------------------------------
Turns one raw product object from the Node collector's GetMenuSections
walk (see research/api-map/api-map.md) into the normalized dict
backend/database.py's product_snapshots table expects, plus the stable
identity keys used for change detection.

Product identity (see README "Product Identity"):
  - Primary: the Sanity document's own _id (stable across runs - it is a
    real CMS document id, not a generated one).
  - Fallback (used only if _id is missing/blank): normalized name +
    normalized category.
  - canonical_product_key = f"{branch_id}|{channel}|{identity}" is what
    change_detector.py joins across runs.

KNOWN LIMITATION (see api-map.md "Known limitation: live prices" and the
root of this file's docstring): Burger King's GetMenuSections API carries
NO price field of any kind and no discount/promoId/limited-offer
signal - regular_price here comes entirely from
collector/price-scraper.js's DOM-text extraction (a single current price
per product), and special_price is always None because no second
("was X, now Y") price signal exists anywhere in the collected data.
This is a deliberate, documented gap - see offer_parser.py.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Optional

CURRENCY_DEFAULT = "SAR"


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


def extract_portable_text(value: Any) -> Optional[str]:
    """Best-effort plain-text extraction from a Sanity "portable text"
    rich-text field (a list of {_type:'block', children:[{text}]} blocks) -
    used for Picker-type products' `description.localeRaw`. Returns None
    (never a guess) if the shape doesn't match what's expected."""
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for block in value:
            if isinstance(block, dict):
                for child in block.get("children") or []:
                    if isinstance(child, dict) and child.get("text"):
                        parts.append(str(child["text"]))
        return " ".join(parts).strip() or None
    return None


def extract_description(product: dict[str, Any]) -> Optional[str]:
    desc = product.get("description")
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return extract_portable_text(desc.get("localeRaw")) or desc.get("locale")
    return None


def extract_description_ar(product: dict[str, Any]) -> Optional[str]:
    desc = product.get("description")
    if isinstance(desc, dict):
        return extract_portable_text(desc.get("_locFbRaw")) or desc.get("_locFb")
    return None


def extract_image_url(product: dict[str, Any]) -> Optional[str]:
    image = product.get("image")
    if isinstance(image, dict):
        asset = image.get("asset")
        if isinstance(asset, dict) and asset.get("url"):
            return asset["url"]
    return None


def extract_option_groups(node: Any, depth: int = 0, seen: Optional[set] = None) -> list[dict[str, Any]]:
    """Recursively collects modifier/option-group-shaped nodes (anything
    with its own `name.locale`) from a product's `options` tree. Best
    effort - see api-map.md, the exact GraphQL union shape of every
    variant (ItemOption/Picker/Combo component step, etc.) was not fully
    modeled in this session, so this walks generically rather than
    assuming one specific shape."""
    if seen is None:
        seen = set()
    groups: list[dict[str, Any]] = []
    if depth > 10 or not isinstance(node, (dict, list)):
        return groups
    if isinstance(node, list):
        for item in node:
            groups.extend(extract_option_groups(item, depth + 1, seen))
        return groups
    node_id = node.get("_id")
    if node_id and node_id in seen:
        return groups
    if node_id:
        seen.add(node_id)
    name = node.get("name")
    if isinstance(name, dict) and name.get("locale") and node.get("_type") in ("section", "item", "combo", "picker"):
        pass  # top-level product/category names are handled by the caller, not collected as an "option group" here
    # A modifier/step-like node in this schema doesn't carry a plain
    # `name.locale` the way sections/items do - it carries a
    # modifierMultiplier/pluConfigs tree (see api-map.md). Collect a
    # lightweight record whenever one is found.
    if "modifierMultiplier" in node or "pluConfigs" in node:
        groups.append({
            "id": node_id,
            "hasPlu": bool(node.get("pluConfigs")),
        })
    for value in node.values():
        if isinstance(value, (dict, list)):
            groups.extend(extract_option_groups(value, depth + 1, seen))
    return groups


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
    source_endpoint: str = "GetMenuSections",
) -> dict[str, Any]:
    """Returns a dict with exactly the columns backend/database.py's
    product_snapshots table expects, plus a few extra keys the ingestion
    code reads before insert but does not store verbatim."""
    product_id = product.get("_id")
    category_id = product.get("__categoryId")
    category_name_en = product.get("__categoryName")
    name_obj = product.get("name") or {}
    name_en = name_obj.get("locale") if isinstance(name_obj, dict) else None
    name_ar = name_obj.get("_locFb") if isinstance(name_obj, dict) else None

    # See module docstring / api-map.md "Known limitation: live prices" -
    # regular_price is the collector's scraped current price; there is no
    # second ("special") price signal anywhere in the collected data.
    regular_price = to_float(product.get("__price"))
    special_price = None
    effective_price = regular_price
    discount_amount = None
    discount_percentage = None

    option_groups = extract_option_groups(product.get("options"))
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
        "sku": None,  # no SKU/PLU is exposed at the catalog level, only per-vendor modifier PLU codes - see api-map.md
        "product_name_en": name_en,
        "product_name_ar": name_ar,
        "normalized_name": normalize_text(name_en),
        "category_id": str(category_id) if category_id is not None else None,
        "category_name_en": category_name_en,
        "category_name_ar": product.get("__categoryNameAr"),
        "description_en": extract_description(product),
        "description_ar": extract_description_ar(product),
        "currency": CURRENCY_DEFAULT,
        "regular_price": regular_price,
        "special_price": special_price,
        "effective_price": effective_price,
        "discount_amount": discount_amount,
        "discount_percentage": discount_percentage,
        "promo_id": None,  # no promo id signal exists in this brand's collected data - see api-map.md
        "limited_offer": 0,
        "product_type": product.get("_type"),
        "bundle_type_id": "combo" if product.get("_type") == "combo" else None,
        "availability": 1,  # appearing in GetMenuSections is the only availability signal available - see api-map.md
        "image_url": extract_image_url(product),
        "product_url": None,  # SPA, no confirmed per-product deep link - see api-map.md
        "calories": None,  # not present anywhere in the collected data this session
        "variants": json.dumps([], ensure_ascii=False),
        "sizes": json.dumps([{"title": product.get("itemSize")}] if product.get("itemSize") else [], ensure_ascii=False),
        "option_groups": json.dumps(option_groups, ensure_ascii=False),
        "included_items": json.dumps([], ensure_ascii=False),
        "sides": json.dumps([], ensure_ascii=False),
        "drinks": json.dumps([], ensure_ascii=False),
        "sauces": json.dumps([], ensure_ascii=False),
        "add_ons": json.dumps([], ensure_ascii=False),
        "raw_api_json": json.dumps(raw_copy, ensure_ascii=False),
        "source_endpoint": source_endpoint,
    }
