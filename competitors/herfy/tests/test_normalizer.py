"""
tests/test_normalizer.py
---------------------------------------------------------------------
Covers required tests #1 (Product ID matching) and #2 (fallback matching
by normalized name and category), the real per-size price extraction
(extract_sizes), and the price/original-price discount logic - which is
real field-structure-based logic (see normalizer.py's module docstring),
confirmed dormant (no active discount existed anywhere on the menu at
verification time) but tested here to prove it actually fires the moment
price < original-price for any product.
---------------------------------------------------------------------
"""
from __future__ import annotations

from competitors.herfy.backend import normalizer


def test_canonical_key_uses_product_id_when_present():
    key1 = normalizer.canonical_product_key(29696, "PICKUP", 2996553, "Beef Tortilla Meal", "The Tortilla Masters")
    key2 = normalizer.canonical_product_key(29696, "PICKUP", 2996553, "Renamed Beef Tortilla Meal", "Different Category")
    # Same product id -> same identity, EVEN IF the name/category text
    # changed around it (spec: "The primary product identity is: Product ID").
    assert key1 == key2
    assert key1 == "29696|PICKUP|id:2996553"


def test_canonical_key_falls_back_to_normalized_name_and_category_when_id_missing():
    key1 = normalizer.canonical_product_key(29696, "PICKUP", None, "Chicken Tortilla", "The Tortilla Masters")
    key2 = normalizer.canonical_product_key(29696, "PICKUP", "", "  CHICKEN   tortilla! ", "the tortilla masters")
    # No id on either side -> falls back to normalized name+category, and
    # trivial formatting differences (case/punctuation/whitespace) must not
    # produce a different key.
    assert key1 == key2


def test_canonical_key_fallback_differs_by_category():
    key1 = normalizer.canonical_product_key(29696, "PICKUP", None, "Fries", "Side Orders")
    key2 = normalizer.canonical_product_key(29696, "PICKUP", None, "Fries", "Offers")
    assert key1 != key2


def test_canonical_key_differs_by_channel_and_branch():
    pickup_key = normalizer.canonical_product_key(29696, "PICKUP", 123, "X", "Y")
    delivery_key = normalizer.canonical_product_key(29696, "DELIVERY", 123, "X", "Y")
    other_branch_key = normalizer.canonical_product_key(999, "PICKUP", 123, "X", "Y")
    assert pickup_key != delivery_key
    assert pickup_key != other_branch_key


def test_normalize_text_strips_accents_case_and_punctuation():
    assert normalizer.normalize_text("Café Latte!!") == normalizer.normalize_text("cafe latte")


def test_to_float_handles_missing_and_invalid_values():
    assert normalizer.to_float(None) is None
    assert normalizer.to_float("") is None
    assert normalizer.to_float("not a number") is None
    assert normalizer.to_float(29) == 29.0
    assert normalizer.to_float("15.5") == 15.5


def test_extract_sizes_finds_the_real_sizes_option_group(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2996553)  # Beef Tortilla Meal
    sizes = normalizer.extract_sizes(product["__optionGroups"])
    assert sizes == [
        {"title": "Regular", "price": 29},
        {"title": "Medium", "price": 32},
        {"title": "Large", "price": 34},
    ]


def test_extract_sizes_returns_empty_when_no_sizes_group_exists(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2784707)  # Jalapeno Bites - no option groups at all
    assert normalizer.extract_sizes(product["__optionGroups"]) == []


def test_normalize_product_end_to_end_real_shape(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2996553)  # Beef Tortilla Meal
    snap = normalizer.normalize_product(
        product, channel="PICKUP", branch_id=29696, branch_name="RUH - Al Mogarazat - Eirad Plaza Mall 1073", city="Riyadh",
        cluster_id="6285", config_id="12303", run_id="run-1", captured_at="2026-08-01T06:05:00Z",
    )
    assert snap["product_id"] == "2996553"
    assert snap["product_key"] == "29696|PICKUP|id:2996553"
    assert snap["product_name_en"] == "Beef Tortilla Meal"
    assert snap["product_name_ar"] == "وجبة تورتيلا اللحم"
    assert snap["sku"] == "beef-tortilla-meal"
    assert snap["regular_price"] == 29.0
    assert snap["effective_price"] == 29.0
    # No active discount on this product (price == original-price) -
    # never guessed - see module docstring.
    assert snap["special_price"] is None
    assert snap["discount_amount"] is None
    assert snap["calories"] == "860"
    assert snap["description_en"] and "Tortilla Masters" in snap["description_en"]
    assert '"title": "Regular"' in snap["sizes"]
    assert snap["channel"] == "PICKUP"


def test_normalize_product_reports_a_real_discount_when_price_is_below_original():
    """Proves the price/original-price discount logic (see module
    docstring) actually fires - not just documentation - the moment a
    real discount exists, without any code change."""
    product = {
        "id": 999999, "name": {"en-us": "Test Discounted Item", "ar-sa": "عنصر مخفض"},
        "price": 15, "original-price": 20, "list-price": 0,
        "__categoryId": 1, "__categoryName": "Side Orders", "__optionGroups": [],
    }
    snap = normalizer.normalize_product(
        product, channel="PICKUP", branch_id=29696, branch_name="X", city="Riyadh",
        cluster_id=None, config_id=None, run_id="run-1", captured_at="2026-08-01T06:05:00Z",
    )
    assert snap["regular_price"] == 20.0
    assert snap["special_price"] == 15.0
    assert snap["effective_price"] == 15.0
    assert snap["discount_amount"] == 5.0
    assert snap["discount_percentage"] == 25.0


def test_normalize_product_limited_offer_flag_reflects_has_timed_event():
    product = {
        "id": 1, "name": {"en-us": "X"}, "price": 10, "original-price": 10,
        "has-timed-event": True, "__categoryId": 1, "__categoryName": "Y", "__optionGroups": [],
    }
    snap = normalizer.normalize_product(
        product, channel="PICKUP", branch_id=29696, branch_name="X", city="Riyadh",
        cluster_id=None, config_id=None, run_id="run-1", captured_at="t",
    )
    assert snap["limited_offer"] == 1
