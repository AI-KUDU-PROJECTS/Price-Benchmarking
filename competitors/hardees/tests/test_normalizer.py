"""
competitors/hardees/tests/test_normalizer.py
Covers required tests #1 (Product ID matching) and #2 (fallback matching by
normalized name and category), plus the promoId/specialPrice sentinel
handling - confirmed identical on Hardee's platform to KFC's (see
research/api-map/api-map.md "Shared platform note").
"""
from __future__ import annotations

import json

from competitors.hardees.backend import normalizer


def test_canonical_key_uses_product_id_when_present():
    key1 = normalizer.canonical_product_key(24, "PICKUP", 61001, "Sunday Duo", "Deal of the Day")
    key2 = normalizer.canonical_product_key(24, "PICKUP", 61001, "Renamed Sunday Duo", "Different Category")
    # Same product id -> same identity, EVEN IF the name/category text changed
    # around it (spec: "The primary product identity is: Product ID").
    assert key1 == key2
    assert key1 == "24|PICKUP|id:61001"


def test_canonical_key_falls_back_to_normalized_name_and_category_when_id_missing():
    key1 = normalizer.canonical_product_key(24, "PICKUP", None, "Thick Burger", "Burgers")
    key2 = normalizer.canonical_product_key(24, "PICKUP", "", "  THICK   burger! ", "burgers")
    # No id on either side -> falls back to normalized name+category, and
    # trivial formatting differences (case/punctuation/whitespace) must not
    # produce a different key.
    assert key1 == key2


def test_canonical_key_fallback_differs_by_category():
    key1 = normalizer.canonical_product_key(24, "PICKUP", None, "Fries", "Sides")
    key2 = normalizer.canonical_product_key(24, "PICKUP", None, "Fries", "Kids Meal")
    assert key1 != key2


def test_canonical_key_differs_by_channel_and_branch():
    pickup_key = normalizer.canonical_product_key(24, "PICKUP", 61001, "X", "Y")
    delivery_key = normalizer.canonical_product_key(24, "DELIVERY", 61001, "X", "Y")
    other_branch_key = normalizer.canonical_product_key(999, "PICKUP", 61001, "X", "Y")
    assert pickup_key != delivery_key
    assert pickup_key != other_branch_key


def test_normalize_text_strips_accents_case_and_punctuation():
    assert normalizer.normalize_text("Café Latte!!") == normalizer.normalize_text("cafe latte")


def test_normalize_promo_id_sentinel_minus_one_is_no_promo():
    # -1 is the "no active promotion" sentinel on this shared Americana
    # platform (confirmed for KFC, structurally identical for Hardee's -
    # see api-map.md), not 0 or blank.
    assert normalizer.normalize_promo_id(-1) is None
    assert normalizer.normalize_promo_id("-1") is None
    assert normalizer.normalize_promo_id(0) is None
    assert normalizer.normalize_promo_id(None) is None
    assert normalizer.normalize_promo_id("") is None
    assert normalizer.normalize_promo_id(6739) == "6739"


def test_normalize_special_price_sentinel_zero_is_no_special_price():
    # 0 is a "not a simple discount price" sentinel on combo-builder
    # products, not a genuinely free item.
    assert normalizer.normalize_special_price(0, 19.0) is None
    assert normalizer.normalize_special_price(None, 19.0) is None
    assert normalizer.normalize_special_price(19.0, 19.0) is None  # equal to regular price -> not a discount
    assert normalizer.normalize_special_price(25.0, 19.0) is None  # above regular price -> not a discount
    assert normalizer.normalize_special_price(15.0, 19.0) == 15.0


def test_normalize_product_end_to_end_real_shape(delivery_result):
    product = delivery_result["products"][0]  # "Sunday Duo" - see tests/fixtures
    snap = normalizer.normalize_product(
        product, channel="DELIVERY", branch_id=24, branch_name="EUROMARCHE-H", city="Riyadh",
        cluster_id="1_8", config_id="HRD_SA_24", run_id="run-1", captured_at="2026-08-11T06:05:00Z",
    )
    assert snap["product_id"] == str(product["id"])
    assert snap["product_key"] == f"24|DELIVERY|id:{product['id']}"
    assert snap["regular_price"] == product["originalPrice"]
    assert snap["special_price"] == product["specialPrice"]
    assert snap["effective_price"] == product["specialPrice"]
    assert snap["promo_id"] == str(product["promoId"])
    assert snap["channel"] == "DELIVERY"
    assert snap["calories"] is None  # never guessed - see api-map.md
    assert snap["product_name_ar"] is None  # Arabic not available from this endpoint - see api-map.md


def test_extract_sizes_joins_items_sel1value_prices(delivery_result):
    """Per-size prices come from items[] joined on sel1Value === option.id
    (Americana platform) - not from inventing prices or calling /api/product
    for every size when the catalog already carries them."""
    product = next(p for p in delivery_result["products"] if p["name"] == "Low Mein Thickburger Combo")
    sizes = normalizer.extract_sizes(product)
    assert [(s["title"], s.get("price"), s.get("nestedItemId")) for s in sizes] == [
        ("Medium", 32.0, 71011),
        ("Large", 37.0, 71012),
    ]
    snap = normalizer.normalize_product(
        product, channel="DELIVERY", branch_id=24, branch_name="EUROMARCHE-H", city="Riyadh",
        cluster_id="1_8", config_id="HRD_SA_24", run_id="run-1", captured_at="2026-08-11T06:05:00Z",
    )
    stored = json.loads(snap["sizes"])
    assert stored[0]["price"] == 32.0 and stored[1]["price"] == 37.0


def test_extract_sizes_omits_price_when_items_missing():
    product = {
        "variants": [{"title": "Size", "options": [{"id": 1, "title": "Regular", "isSelected": 1}]}],
        "items": [],
    }
    sizes = normalizer.extract_sizes(product)
    assert sizes == [{"id": 1, "title": "Regular", "isSelected": True, "variantTitle": "Size"}]
    assert "price" not in sizes[0]
