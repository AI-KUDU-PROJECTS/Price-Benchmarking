"""
tests/test_normalizer.py
Covers required tests #1 (Product ID matching) and #2 (fallback matching by
normalized name and category), plus the promoId/specialPrice sentinel
handling discovered during live verification (see api-map.md).
"""
from __future__ import annotations

from competitors.kfc.backend import normalizer


def test_canonical_key_uses_product_id_when_present():
    key1 = normalizer.canonical_product_key(251, "PICKUP", 18182, "Double Up Deal", "Exclusive")
    key2 = normalizer.canonical_product_key(251, "PICKUP", 18182, "Renamed Double Up Deal", "Different Category")
    # Same product id -> same identity, EVEN IF the name/category text changed
    # around it (spec: "The primary product identity is: Product ID").
    assert key1 == key2
    assert key1 == "251|PICKUP|id:18182"


def test_canonical_key_falls_back_to_normalized_name_and_category_when_id_missing():
    key1 = normalizer.canonical_product_key(251, "PICKUP", None, "Zinger Burger", "Burgers")
    key2 = normalizer.canonical_product_key(251, "PICKUP", "", "  ZINGER   burger! ", "burgers")
    # No id on either side -> falls back to normalized name+category, and
    # trivial formatting differences (case/punctuation/whitespace) must not
    # produce a different key.
    assert key1 == key2


def test_canonical_key_fallback_differs_by_category():
    key1 = normalizer.canonical_product_key(251, "PICKUP", None, "Fries", "Sides")
    key2 = normalizer.canonical_product_key(251, "PICKUP", None, "Fries", "Kids Meal")
    assert key1 != key2


def test_canonical_key_differs_by_channel_and_branch():
    pickup_key = normalizer.canonical_product_key(251, "PICKUP", 18182, "X", "Y")
    delivery_key = normalizer.canonical_product_key(251, "DELIVERY", 18182, "X", "Y")
    other_branch_key = normalizer.canonical_product_key(999, "PICKUP", 18182, "X", "Y")
    assert pickup_key != delivery_key
    assert pickup_key != other_branch_key


def test_normalize_text_strips_accents_case_and_punctuation():
    assert normalizer.normalize_text("Café Latte!!") == normalizer.normalize_text("cafe latte")


def test_normalize_promo_id_sentinel_minus_one_is_no_promo():
    # Live-confirmed 2026-08-05: -1 is the "no active promotion" sentinel,
    # not 0 or blank - see api-map.md.
    assert normalizer.normalize_promo_id(-1) is None
    assert normalizer.normalize_promo_id("-1") is None
    assert normalizer.normalize_promo_id(0) is None
    assert normalizer.normalize_promo_id(None) is None
    assert normalizer.normalize_promo_id("") is None
    assert normalizer.normalize_promo_id(9583) == "9583"


def test_normalize_special_price_sentinel_zero_is_no_special_price():
    # Live-confirmed: 0 is a "not a simple discount price" sentinel on
    # combo-builder products, not a genuinely free item.
    assert normalizer.normalize_special_price(0, 19.0) is None
    assert normalizer.normalize_special_price(None, 19.0) is None
    assert normalizer.normalize_special_price(19.0, 19.0) is None  # equal to regular price -> not a discount
    assert normalizer.normalize_special_price(25.0, 19.0) is None  # above regular price -> not a discount
    assert normalizer.normalize_special_price(15.0, 19.0) == 15.0


def test_normalize_product_end_to_end_real_shape(delivery_result):
    product = delivery_result["products"][0]  # "Double Up Deal" - see tests/fixtures
    snap = normalizer.normalize_product(
        product, channel="DELIVERY", branch_id=251, branch_name="SITEEN", city="Riyadh",
        cluster_id="1_5", config_id="KFC_SA_27", run_id="run-1", captured_at="2026-08-01T06:05:00Z",
    )
    assert snap["product_id"] == str(product["id"])
    assert snap["product_key"] == f"251|DELIVERY|id:{product['id']}"
    assert snap["regular_price"] == product["originalPrice"]
    assert snap["special_price"] == product["specialPrice"]
    assert snap["effective_price"] == product["specialPrice"]
    assert snap["promo_id"] == str(product["promoId"])
    assert snap["channel"] == "DELIVERY"
    assert snap["calories"] is None  # never guessed - see api-map.md
    assert snap["product_name_ar"] is None  # Arabic not available from this endpoint - see api-map.md


def test_extract_sizes_joins_items_sel1value_prices(pickup_result):
    product = next(p for p in pickup_result["products"] if p.get("name") == "5 Pcs Spicy Bitez Combo")
    sizes = normalizer.extract_sizes(product)
    assert [(s["title"], s.get("price")) for s in sizes] == [
        ("Medium", 19.0),
        ("Large", 22.0),
    ]
