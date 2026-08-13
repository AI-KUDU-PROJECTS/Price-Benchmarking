"""
tests/test_offer_parser.py
Covers offer_type classification (README "Offer Details") and the
combo-builder specialPrice=0 sentinel discovered during live verification.
"""
from __future__ import annotations

from competitors.kfc.backend import offer_parser


def test_is_offer_product_true_for_real_discount():
    p = {"originalPrice": 63, "specialPrice": 42, "promoId": 9583, "limited_offer": 0}
    assert offer_parser.is_offer_product(p) is True


def test_is_offer_product_false_for_combo_builder_sentinel():
    """specialPrice=0 with a real promoId but no actual discount signal is
    still an offer (promoId alone counts) - but the PRICE must never be
    read as "free"."""
    p = {"originalPrice": 19, "specialPrice": 0, "promoId": 9585, "limited_offer": 0}
    assert offer_parser.is_offer_product(p) is True  # has_promo makes it an offer
    snap = offer_parser.build_offer_snapshot(p, product_key="k", channel="DELIVERY", branch_id=251, run_id="r", captured_at="t", progressive_promo_ids=set())
    assert snap["offer_price"] == 19  # falls back to originalPrice, never 0


def test_is_offer_product_false_for_plain_bundle_without_discount():
    """A regular-priced Meal with build steps but no promo/discount/limited
    flag must NOT be classified as an offer - see the regression this
    guards against in offer_parser.py's module docstring."""
    p = {"originalPrice": 25, "specialPrice": 25, "promoId": -1, "limited_offer": 0, "bundleTypeId": "bundle", "steps": [{"title": "Choice of Side"}]}
    assert offer_parser.is_offer_product(p) is False


def test_classify_offer_type_meal_deal_for_multi_step_bundle():
    p = {
        "bundleTypeId": "bundle", "originalPrice": 63, "specialPrice": 42, "promoId": 9583,
        "steps": [
            {"title": "Choice of Sandwich", "isHidden": 0, "isDependent": 0},
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
    result = offer_parser.classify_components(steps, "Zinger Sandwich,Regular Fries,Pepsi Medium")
    assert "Regular Fries" in result["sides"]
    assert "Pepsi Medium" in result["drinks"]
    assert "Add On" in result["add_ons"]
    assert result["included_items"] == ["Zinger Sandwich", "Regular Fries", "Pepsi Medium"]


def test_offer_key_prefers_promo_id_over_product_key():
    key_with_promo = offer_parser.offer_key(251, "DELIVERY", "251|DELIVERY|id:1", "9583")
    key_without_promo = offer_parser.offer_key(251, "DELIVERY", "251|DELIVERY|id:1", None)
    assert key_with_promo == "251|DELIVERY|promo:9583"
    assert key_without_promo == "251|DELIVERY|offerprod:251|DELIVERY|id:1"
    assert key_with_promo != key_without_promo
