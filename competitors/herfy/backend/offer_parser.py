"""
backend/offer_parser.py
---------------------------------------------------------------------
Herfy has TWO independent, real (non-guessed) offer signals - richer than
either KFC's or Burger King's single signal:

1. **A genuine price discount** (see normalizer.py's module docstring):
   the menu-ref response carries `price` and `original-price` per item.
   Every one of the 144 items sampled live (2026-08-11) had `price ==
   original-price` (no active discount anywhere on the menu at
   verification time), but the field structure is real and unambiguous -
   the moment `price < original-price` for any item, this is treated as a
   real offer with a real, confirmed discount amount (never a guess).
2. **The "Offers" CMS category** (عروض حصرية / "Exclusive Offers",
   categoryId 169347 at verification time, 10 combo items) - Herfy's own
   dedicated combo-bundle-deals section, matched by category NAME (robust
   to a future categoryId change), same category-based-signal pattern
   already established for Burger King's "KING DAILY DEALS". Per the "do
   not classify or parse an offer using only its name" rule, this is
   never inferred from a PRODUCT's own name/description text - only from
   the CMS category the site itself assigned it to.
3. A real, structural "has-timed-event" boolean flag also exists on every
   item (always False at verification time) - a genuine limited-time-offer
   signal, not a guess, included for completeness/forward-compatibility.

Unlike Burger King, `build_offer_snapshot()` here DOES populate
`original_price`/`saving_amount`/`discount_percentage` whenever signal #1
(a genuine price discount) is present - it only leaves them `NULL` for
offers detected purely via signal #2 (category membership) or #3 (the
timed-event flag) with no confirmed discount amount, exactly matching
Burger King's "never fabricate a discount that isn't in the data" rule
for those cases.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
from typing import Any, Optional

from competitors.herfy.backend import models, normalizer

# The one Herfy CMS category treated as a deal/offer section - see module
# docstring. Compared via normalizer.normalize_text() so trivial
# capitalization/whitespace differences in a future menu republish can
# never silently break this match.
DEAL_CATEGORY_NAME = "Offers"
_DEAL_CATEGORY_NORMALIZED = normalizer.normalize_text(DEAL_CATEGORY_NAME)


def _has_real_discount(product: dict[str, Any]) -> bool:
    price = normalizer.to_float(product.get("price"))
    original_price = normalizer.to_float(product.get("original-price"))
    return price is not None and original_price is not None and price < original_price


def is_offer_product(product: dict[str, Any]) -> bool:
    """True for a genuine price discount, membership in the "Offers"
    category, or the real has-timed-event flag - see module docstring.
    Never based on the product's own name/description text alone."""
    if _has_real_discount(product):
        return True
    if product.get("has-timed-event"):
        return True
    category_name = product.get("__categoryName")
    return normalizer.normalize_text(category_name) == _DEAL_CATEGORY_NORMALIZED


def offer_key(branch_id: int, channel: str, product_key: str, promo_id: Optional[str]) -> str:
    """Mirrors every other competitor's offer_parser.py's offer_key() -
    prefers a real promo id (never populated for this brand - no promo/
    coupon id field exists at the catalog level, see api-map.md) and
    otherwise falls back to the product's own canonical key."""
    if promo_id:
        return f"{branch_id}|{channel}|promo:{promo_id}"
    return f"{branch_id}|{channel}|offerprod:{product_key}"


def build_offer_snapshot(
    product: dict[str, Any],
    *,
    product_key: str,
    channel: str,
    branch_id: int,
    run_id: str,
    captured_at: str,
    progressive_promo_ids: set[str],
    source_endpoint: str = "menu-ref",
) -> dict[str, Any]:
    """Returns a dict with exactly the columns backend/database.py's
    offer_snapshots table expects. Only called when is_offer_product() is
    True - see module docstring for when original_price/saving_amount/
    discount_percentage are populated vs. left None."""
    name_obj = product.get("name") or {}
    name_en = name_obj.get("en-us") if isinstance(name_obj, dict) else None
    price = normalizer.to_float(product.get("price"))
    original_price = normalizer.to_float(product.get("original-price"))

    has_discount = _has_real_discount(product)
    offer_price = price
    saving_amount = round(original_price - price, 2) if (has_discount and original_price is not None and price is not None) else None
    discount_percentage = round((saving_amount / original_price) * 100, 2) if (saving_amount and original_price) else None

    desc_obj = product.get("description") or {}
    offer_description = desc_obj.get("en-us") if isinstance(desc_obj, dict) else None
    raw_copy = {k: v for k, v in product.items() if not k.startswith("__")}

    return {
        "run_id": run_id,
        "offer_key": offer_key(branch_id, channel, product_key, None),
        "promo_id": None,
        "product_key": product_key,
        "channel": channel,
        "branch_id": branch_id,
        "captured_at": captured_at,
        "offer_name": name_en,
        "main_item": name_en,
        # No reliable per-included-item breakdown exists for this brand's
        # combo shape (the "combo" field lists component options, not a
        # simple flat ingredient list) - left empty rather than guessed.
        "included_items": json.dumps([], ensure_ascii=False),
        "number_of_pieces": None,
        "sides": json.dumps([], ensure_ascii=False),
        "drinks": json.dumps([], ensure_ascii=False),
        "sauces": json.dumps([], ensure_ascii=False),
        "sizes": json.dumps(normalizer.extract_sizes(product.get("__optionGroups") or []), ensure_ascii=False),
        "add_ons": json.dumps([], ensure_ascii=False),
        "original_price": original_price if has_discount else None,  # never fabricated - see module docstring
        "offer_price": offer_price,
        "saving_amount": saving_amount,
        "discount_percentage": discount_percentage,
        "offer_description": offer_description,
        "offer_type": models.OFFER_TYPE_BUNDLE if product.get("is-combo") else models.OFFER_TYPE_DISCOUNT if has_discount else models.OFFER_TYPE_UNKNOWN,
        "bundle_type": "combo" if product.get("is-combo") else None,
        "image_url": product.get("image-uri"),
        "screenshot_path": None,
        "source_endpoint": source_endpoint,
        "raw_json": json.dumps(raw_copy, ensure_ascii=False),
    }
