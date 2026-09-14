"""
shared_ui/price_columns.py
---------------------------------------------------------------------
Shared column order for competitor price dashboards (KFC, Hardee's, …).
Scan order: category → name → normalized name → prices → size prices →
currency → description → included items → size summary → product type →
image → channel.
Pure display helpers; no competitor-specific logic.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

# Tab bar shared by every competitor price page (same labels, same order).
DASHBOARD_TAB_NAMES = (
    "Overview",
    "Pickup Prices",
    "Delivery Prices",
    "Pickup Offers",
    "Delivery Offers",
    "Pickup vs Delivery",
    "Changes",
    "History / Logs",
)

# Canonical size columns shown next to the product's base price.
SIZE_PRICE_COLUMNS = (
    "Small",
    "Regular",
    "Medium",
    "Large",
)

_SIZE_TITLE_TO_COLUMN = {
    "small": "Small",
    "regular": "Regular",
    "medium": "Medium",
    "large": "Large",
    # Burger King meal-size / piece-count labels (when left uncanonicalized)
    "sandwich only": "Small",
    "go regular": "Regular",
    "go value": "Regular",
    "go medium": "Medium",
    "go large": "Large",
    "6 pieces": "Small",
    "9 pieces": "Regular",
    "12 pieces": "Large",
}

# Product table — analyst scan order requested by Kudu pricing workflow.
PRODUCT_PRICE_COLUMNS = (
    "category_name_en",
    "product_name_en",
    "normalized_name",
    "effective_price",
    "Small",
    "Regular",
    "Medium",
    "Large",
    "regular_price",
    "special_price",
    "discount_amount",
    "discount_percentage",
    "currency",
    "description_en",
    "included_items",
    "sizes",
    "number_of_pieces",
    "product_type",
    "image_url",
    "channel",
    "promo_id",
    "limited_offer",
    "bundle_type_id",
    "availability",
    "sku",
    "product_id",
    "product_name_ar",
    "description_ar",
    "category_id",
    "category_name_ar",
    "calories",
)

# Offer table — same scan order as products.
OFFER_PRICE_COLUMNS = (
    "category_name_en",
    "offer_name",
    "offer_price",
    "original_price",
    "saving_amount",
    "discount_percentage",
    "currency",
    "offer_description",
    "included_items",
    "Small",
    "Regular",
    "Medium",
    "Large",
    "sizes",
    "number_of_pieces",
    "bundle_type",
    "image_url",
    "channel",
    "main_item",
    "offer_type",
    "promo_id",
    "category_id",
)

# Pickup vs Delivery comparison columns (after merge).
CHANNEL_COMPARE_COLUMNS = (
    "category_name_en",
    "product_name_en",
    "normalized_name",
    "effective_price_pickup",
    "effective_price_delivery",
    "price_diff",
    "regular_price_pickup",
    "regular_price_delivery",
    "currency",
    "description_en",
    "included_items",
    "sizes",
    "product_type",
    "image_url",
    "promo_id_pickup",
    "promo_id_delivery",
    "product_id",
)


def format_sizes(sizes_json: Optional[Any]) -> str:
    """Turns a product/offer's `sizes` column (JSON text encoding a list of
    `{"title": ..., "price": ...}` - or, for a competitor with no confirmed
    per-size price, just `{"title": ...}` - dicts; see each competitor's
    normalizer.py) into a compact, human-readable string for display, e.g.
    "Regular: 29 | Medium: 32 | Large: 34" instead of the raw JSON text a
    dataframe cell would otherwise show verbatim. Generic across every
    competitor's `sizes` shape - never guesses a size/price that isn't in
    the data; returns "" for empty/missing/malformed input."""
    if not sizes_json:
        return ""
    try:
        sizes = json.loads(sizes_json) if isinstance(sizes_json, str) else sizes_json
    except (TypeError, ValueError):
        return str(sizes_json)
    if not isinstance(sizes, list) or not sizes:
        return ""
    parts = []
    for s in sizes:
        if not isinstance(s, dict):
            continue
        title = s.get("title")
        if not title:
            continue
        price = s.get("price")
        parts.append(f"{title}: {price}" if price is not None else str(title))
    return " | ".join(parts)


def size_price_map(sizes_json: Optional[Any]) -> dict[str, Optional[float]]:
    """Extracts Small/Regular/Medium/Large prices from a sizes JSON cell.
    Missing sizes stay None - never invents a price."""
    out: dict[str, Optional[float]] = {col: None for col in SIZE_PRICE_COLUMNS}
    if not sizes_json:
        return out
    try:
        sizes = json.loads(sizes_json) if isinstance(sizes_json, str) else sizes_json
    except (TypeError, ValueError):
        return out
    if not isinstance(sizes, list):
        return out
    for entry in sizes:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title")
        if not title:
            continue
        col = _SIZE_TITLE_TO_COLUMN.get(str(title).strip().lower())
        if not col:
            continue
        price = entry.get("price")
        if price is None or price == "":
            continue
        try:
            out[col] = float(price)
        except (TypeError, ValueError):
            continue
    return out


def expand_size_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adds Small/Regular/Medium/Large columns from the `sizes` JSON column,
    then replaces `sizes` with the human-readable summary string. No-op on
    empty frames or when `sizes` is absent."""
    if df is None or df.empty or "sizes" not in df.columns:
        return df
    maps = df["sizes"].apply(size_price_map)
    for col in SIZE_PRICE_COLUMNS:
        df[col] = maps.apply(lambda m, c=col: m.get(c))
    df["sizes"] = df["sizes"].apply(format_sizes)
    return df


def format_run_timestamp(value: Optional[str], tz_name: str = "Asia/Riyadh") -> str:
    """Formats a stored UTC ISO timestamp (…Z) for display in the dashboard
    timezone. Returns 'Never' for empty input."""
    if not value:
        return "Never"
    text = str(value).strip()
    if not text:
        return "Never"
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(ZoneInfo(tz_name))
        return local.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text[:16].replace("T", " ")


def localize_timestamp_columns(
    df: pd.DataFrame,
    columns: Sequence[str],
    tz_name: str = "Asia/Riyadh",
) -> pd.DataFrame:
    """Localizes known UTC timestamp columns in a dataframe for display."""
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].apply(lambda v, tz=tz_name: format_run_timestamp(v, tz) if pd.notna(v) and v != "" else v)
    return out


def order_columns(df: pd.DataFrame, preferred: Iterable[str]) -> pd.DataFrame:
    """Reorder `df` columns: preferred order first (only those present),
    then any remaining columns in their existing order."""
    if df is None or df.empty:
        return df
    preferred_list = [c for c in preferred if c in df.columns]
    rest = [c for c in df.columns if c not in preferred_list]
    return df[preferred_list + rest]
