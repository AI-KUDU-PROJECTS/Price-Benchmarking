"""
shared_ui/price_columns.py
---------------------------------------------------------------------
Shared column order for competitor price dashboards (KFC, Hardee's, …).
Scan order: category → name → normalized name → prices → currency →
description → included items → size → product type → image → channel.
Pure display helpers; no competitor-specific logic.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Optional

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

# Product table — analyst scan order requested by Kudu pricing workflow.
PRODUCT_PRICE_COLUMNS = (
    "category_name_en",
    "product_name_en",
    "normalized_name",
    "effective_price",
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


def order_columns(df: pd.DataFrame, preferred: Iterable[str]) -> pd.DataFrame:
    """Reorder `df` columns: preferred order first (only those present),
    then any remaining columns in their existing order."""
    if df is None or df.empty:
        return df
    preferred_list = [c for c in preferred if c in df.columns]
    rest = [c for c in df.columns if c not in preferred_list]
    return df[preferred_list + rest]
