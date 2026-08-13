"""
tests/test_normalizer.py
---------------------------------------------------------------------
Covers required tests #1 (Product ID matching) and #2 (fallback matching
by normalized name and category), plus the option-tree extraction and
known-limitation behaviors specific to Burger King's GetMenuSections shape
(see backend/normalizer.py module docstring: no promoId/specialPrice
signal exists anywhere in this brand's collected data).
---------------------------------------------------------------------
"""
from __future__ import annotations

from competitors.burger_king.backend import normalizer


def test_canonical_key_uses_product_id_when_present():
    key1 = normalizer.canonical_product_key(11474, "PICKUP", "b10d5e39-7a05-4207-b078-dd1ea35e0c08", "Cheeseburger Lovers", "King Daily Deals")
    key2 = normalizer.canonical_product_key(11474, "PICKUP", "b10d5e39-7a05-4207-b078-dd1ea35e0c08", "Renamed Cheeseburger Lovers", "Different Category")
    # Same product id -> same identity, EVEN IF the name/category text
    # changed around it (spec: "The primary product identity is: Product ID").
    assert key1 == key2
    assert key1 == "11474|PICKUP|id:b10d5e39-7a05-4207-b078-dd1ea35e0c08"


def test_canonical_key_falls_back_to_normalized_name_and_category_when_id_missing():
    key1 = normalizer.canonical_product_key(11474, "PICKUP", None, "Whopper", "Flame-Grilled Burgers")
    key2 = normalizer.canonical_product_key(11474, "PICKUP", "", "  WHOPPER!!  ", "flame-grilled burgers")
    # No id on either side -> falls back to normalized name+category, and
    # trivial formatting differences (case/punctuation/whitespace) must not
    # produce a different key.
    assert key1 == key2


def test_canonical_key_fallback_differs_by_category():
    key1 = normalizer.canonical_product_key(11474, "PICKUP", None, "Fries", "Sides")
    key2 = normalizer.canonical_product_key(11474, "PICKUP", None, "Fries", "King Savers")
    assert key1 != key2


def test_canonical_key_differs_by_channel_and_branch():
    pickup_key = normalizer.canonical_product_key(11474, "PICKUP", "abc", "X", "Y")
    delivery_key = normalizer.canonical_product_key(11474, "DELIVERY", "abc", "X", "Y")
    other_branch_key = normalizer.canonical_product_key(999, "PICKUP", "abc", "X", "Y")
    assert pickup_key != delivery_key
    assert pickup_key != other_branch_key


def test_normalize_text_strips_accents_case_and_punctuation():
    assert normalizer.normalize_text("Café Latte!!") == normalizer.normalize_text("cafe latte")


def test_to_float_handles_missing_and_invalid_values():
    assert normalizer.to_float(None) is None
    assert normalizer.to_float("") is None
    assert normalizer.to_float("not a number") is None
    assert normalizer.to_float(34.99) == 34.99
    assert normalizer.to_float("13") == 13.0


def test_extract_portable_text_from_sanity_blocks():
    blocks = [{"_type": "block", "children": [{"text": "A flame-grilled"}, {"text": "patty."}]}]
    assert normalizer.extract_portable_text(blocks) == "A flame-grilled patty."
    assert normalizer.extract_portable_text(None) is None
    assert normalizer.extract_portable_text([]) is None


def test_extract_option_groups_finds_modifier_multiplier_nodes(pickup_result):
    product = next(p for p in pickup_result["products"] if p["_id"] == "48210cdd-14f3-42ea-900a-85c3923f0f2e")
    groups = normalizer.extract_option_groups(product.get("options"))
    # Best-effort walk (see module docstring) - must find both modifier
    # nodes in this real captured shape, never crash on the vendorConfigs
    # nesting, and never loop forever on the >10 depth guard.
    assert len(groups) == 2
    assert all("hasPlu" in g for g in groups)


def test_extract_option_groups_returns_empty_for_none_or_picker_only_options(pickup_result):
    item = next(p for p in pickup_result["products"] if p["_id"] == "96d6bee7-a93a-41db-b870-2b1bf497016e")
    assert normalizer.extract_option_groups(item.get("options")) == []
    picker = next(p for p in pickup_result["products"] if p["_id"] == "b9bd3a45-b4eb-45c5-a1d0-65267b9dcc32")
    # A Picker's options are Item/Combo references, not modifier nodes -
    # nothing modifierMultiplier/pluConfigs-shaped to find here.
    assert normalizer.extract_option_groups(picker.get("options")) == []


def test_normalize_product_end_to_end_real_shape(pickup_result):
    product = next(p for p in pickup_result["products"] if p["_id"] == "b9bd3a45-b4eb-45c5-a1d0-65267b9dcc32")  # Cheese Storm Burger
    snap = normalizer.normalize_product(
        product, channel="PICKUP", branch_id=11474, branch_name="Dabab Street", city="Riyadh",
        cluster_id=None, config_id="9670fe1e-0342-41b7-9f92-a8fb1907120f", run_id="run-1", captured_at="2026-08-01T06:05:00Z",
    )
    assert snap["product_id"] == product["_id"]
    assert snap["product_key"] == f"11474|PICKUP|id:{product['_id']}"
    assert snap["product_name_en"] == "CHEESE STORM BURGER"
    assert snap["regular_price"] == product["__price"]
    assert snap["effective_price"] == product["__price"]
    # KNOWN LIMITATION (see module docstring): no second price signal exists
    # anywhere in this brand's data - special_price/promo_id/discount are
    # always None, never guessed from name/description text.
    assert snap["special_price"] is None
    assert snap["promo_id"] is None
    assert snap["discount_amount"] is None
    assert snap["calories"] is None  # never present in the collected data this session
    assert snap["description_en"] and "flame-grilled" in snap["description_en"].lower()
    assert snap["description_ar"]
    assert snap["channel"] == "PICKUP"
