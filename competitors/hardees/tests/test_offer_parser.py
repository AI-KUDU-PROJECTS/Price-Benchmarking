"""
competitors/hardees/tests/test_offer_parser.py
Covers offer_type classification (README "Offer Details") and the
combo-builder specialPrice=0 sentinel - structural-signal classification
copied verbatim from KFC's confirmed-identical logic (see
research/api-map/api-map.md "Shared platform note").
"""
from __future__ import annotations

from competitors.hardees.backend import offer_parser


def test_is_offer_product_true_for_real_discount():
    p = {"originalPrice": 24, "specialPrice": 19, "promoId": 6739, "limited_offer": 0}
    assert offer_parser.is_offer_product(p) is True


def test_is_offer_product_false_for_combo_builder_sentinel():
    """specialPrice=0 with a real promoId but no actual discount signal is
    still an offer (promoId alone counts) - but the PRICE must never be
    read as "free"."""
    p = {"originalPrice": 32, "specialPrice": 0, "promoId": 5501, "limited_offer": 0}
    assert offer_parser.is_offer_product(p) is True  # has_promo makes it an offer
    snap = offer_parser.build_offer_snapshot(p, product_key="k", channel="DELIVERY", branch_id=24, run_id="r", captured_at="t", progressive_promo_ids=set())
    assert snap["offer_price"] == 32  # falls back to originalPrice, never 0


def test_is_offer_product_false_for_plain_bundle_without_discount():
    """A regular-priced combo with build steps but no promo/discount/limited
    flag must NOT be classified as an offer - see the regression this
    guards against in offer_parser.py's module docstring."""
    p = {"originalPrice": 32, "specialPrice": 32, "promoId": -1, "limited_offer": 0, "bundleTypeId": "bundle", "steps": [{"title": "Choice of Side"}]}
    assert offer_parser.is_offer_product(p) is False


def test_classify_offer_type_meal_deal_for_multi_step_bundle():
    p = {
        "bundleTypeId": "bundle", "originalPrice": 24, "specialPrice": 19, "promoId": 6739,
        "steps": [
            {"title": "Choice of Burger", "isHidden": 0, "isDependent": 0},
            {"title": "Choice of Side", "isHidden": 0, "isDependent": 0},
            {"title": "Choice of Drink", "isHidden": 0, "isDependent": 0},
        ],
    }
    assert offer_parser.classify_offer_type(p, set()) == "Meal Deal"


def test_classify_offer_type_discount_for_simple_price_cut():
    p = {"originalPrice": 20, "specialPrice": 15, "promoId": 111, "steps": []}
    assert offer_parser.classify_offer_type(p, set()) == "Discount"


def test_classify_offer_type_bogo_from_description_signal():
    p = {"originalPrice": 20, "specialPrice": 20, "promoId": 111, "description": "Buy 1 Get 1 Free on Tuesdays", "steps": []}
    assert offer_parser.classify_offer_type(p, set()) == "Buy One Get One"


def test_classify_offer_type_never_uses_name_alone():
    """Spec: 'Do not classify or parse an offer using only its name.' A
    product whose NAME suggests BOGO but whose description/structure gives
    no such signal must not be classified as BOGO."""
    p = {"name": "Buy 1 Get 1 Special Box", "description": "", "originalPrice": 20, "specialPrice": 15, "promoId": 111, "steps": []}
    assert offer_parser.classify_offer_type(p, set()) == "Discount"


def test_classify_components_splits_by_keyword_never_by_position():
    steps = [{"title": "Add On", "isAddon": 1}]
    result = offer_parser.classify_components(steps, "Chargrilled Burger,Regular Fries,Pepsi Medium")
    assert "Regular Fries" in result["sides"]
    assert "Pepsi Medium" in result["drinks"]
    assert "Add On" in result["add_ons"]
    assert result["included_items"] == ["Chargrilled Burger", "Regular Fries", "Pepsi Medium"]


def test_offer_key_prefers_promo_id_over_product_key():
    key_with_promo = offer_parser.offer_key(24, "DELIVERY", "24|DELIVERY|id:1", "6739")
    key_without_promo = offer_parser.offer_key(24, "DELIVERY", "24|DELIVERY|id:1", None)
    assert key_with_promo == "24|DELIVERY|promo:6739"
    assert key_without_promo == "24|DELIVERY|offerprod:24|DELIVERY|id:1"
    assert key_with_promo != key_without_promo
