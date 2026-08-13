"""
backend/offer_parser.py
---------------------------------------------------------------------
KNOWN LIMITATION (see research/api-map/api-map.md "Known limitation: live
prices" and normalizer.py's module docstring): Burger King's
GetMenuSections response carries NO price-discount signal of any kind -
every `discountPlu` observed across the full menu during development was
`null`, no promoId field exists, and there is no "was X, now Y" second
price anywhere in the collected data. A flat-priced combo/bundle with no
such signal is therefore NOT counted as an offer here, per the same rule
already established for KFC (see
competitors/kfc/tests/test_offer_parser.py::
test_is_offer_product_false_for_plain_bundle_without_discount) - a bundle
by itself is not a discount.

CATEGORY-BASED CLASSIFICATION (confirmed live 2026-08-11, domain
knowledge, see research/api-map/api-map.md "Deal category"): unlike a
product's own free-text name/description (which this project never
trusts to classify an offer - "do not classify or parse an offer using
only its name"), Burger King's GetMenuSections response groups products
into site-curated CMS categories, and one specific category -
"KING DAILY DEALS" (categoryId c0e92480-0bc4-4821-9760-28d18dd8fc89 at
verification time) - is the brand's own dedicated combo-bundle-deals
section, distinct from its 9 regular food categories. This is a
structural signal set by Burger King's own CMS editors, not a guess by
this collector, so `is_offer_product()` uses the category NAME (robust to
a future categoryId change) as its one and only classification signal for
this brand.

"KING SAVERS" was considered and explicitly REJECTED as an offer category:
live inspection of its 7 products (HAMBURGER=5 SAR, CHEESEBURGER=6 SAR,
etc.) showed it is Burger King's permanent budget/value menu - the
individually cheapest core menu items, not time-limited or bundled deals,
and with the exact same "one flat price, no discount signal" shape as
every other regular category. Treating a store's cheapest staple items as
"special offers" would misrepresent them.

Because there is still no confirmed original/"before" price for a KING
DAILY DEALS combo, `build_offer_snapshot()` below sets `original_price`,
`saving_amount`, and `discount_percentage` to None rather than inventing
one - `offer_price` (the combo's one real, scraped price) is the only
price field populated. This offer's presence/absence/price IS still fully
change-tracked (NEW_OFFER, OFFER_NOT_OBSERVED, OFFER_ENDED,
OFFER_RETURNED, price changes) by the same change_detector.py engine
KFC uses, unchanged.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
from typing import Any, Optional

from competitors.burger_king.backend import models, normalizer

# The one Burger King CMS category treated as a deal/offer section - see
# module docstring. Compared via normalizer.normalize_text() so trivial
# capitalization/whitespace differences in a future menu republish can
# never silently break this match.
DEAL_CATEGORY_NAME = "KING DAILY DEALS"
_DEAL_CATEGORY_NORMALIZED = normalizer.normalize_text(DEAL_CATEGORY_NAME)


def is_offer_product(product: dict[str, Any]) -> bool:
    """True only for products in the "KING DAILY DEALS" category - see
    module docstring for why this is a structural (CMS-category) signal,
    not a guess from the product's own name/description text, and why the
    superficially similar "KING SAVERS" category is deliberately excluded."""
    category_name = product.get("__categoryName")
    return normalizer.normalize_text(category_name) == _DEAL_CATEGORY_NORMALIZED


def offer_key(branch_id: int, channel: str, product_key: str, promo_id: Optional[str]) -> str:
    """Mirrors competitors/kfc/backend/offer_parser.py's offer_key() -
    prefers a real promo id (never populated for this brand - see module
    docstring) and otherwise falls back to the product's own canonical
    key, since Burger King has no separate promo/offer id anywhere."""
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
    source_endpoint: str = "GetMenuSections",
) -> dict[str, Any]:
    """Returns a dict with exactly the columns backend/database.py's
    offer_snapshots table expects. Only called when is_offer_product()
    is True (KING DAILY DEALS products) - see module docstring for why
    original_price/saving_amount/discount_percentage are always None."""
    name_obj = product.get("name") or {}
    name_en = name_obj.get("locale") if isinstance(name_obj, dict) else None
    offer_price = normalizer.to_float(product.get("__price"))
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
        # combo shape (unlike KFC's subOptionStr) - see normalizer.py
        # module docstring on the generic option-tree walk. Left empty
        # rather than guessed.
        "included_items": json.dumps([], ensure_ascii=False),
        "number_of_pieces": None,
        "sides": json.dumps([], ensure_ascii=False),
        "drinks": json.dumps([], ensure_ascii=False),
        "sauces": json.dumps([], ensure_ascii=False),
        "sizes": json.dumps([], ensure_ascii=False),
        "add_ons": json.dumps([], ensure_ascii=False),
        "original_price": None,  # no confirmed "before" price exists anywhere in the collected data - see module docstring
        "offer_price": offer_price,
        "saving_amount": None,
        "discount_percentage": None,
        "offer_description": normalizer.extract_description(product),
        "offer_type": models.OFFER_TYPE_BUNDLE,
        "bundle_type": product.get("_type"),
        "image_url": normalizer.extract_image_url(product),
        "screenshot_path": None,
        "source_endpoint": source_endpoint,
        "raw_json": json.dumps(raw_copy, ensure_ascii=False),
    }
