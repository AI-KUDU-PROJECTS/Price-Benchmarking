"""
tests/test_offer_parser.py
---------------------------------------------------------------------
Covers Herfy's THREE independent, real offer signals (see
backend/offer_parser.py module docstring): a genuine price discount
(price < original-price), the "Offers" CMS category, and the real
has-timed-event flag. None of these are based on a product's own
name/description text, per the "do not classify or parse an offer using
only its name" rule established for KFC.
---------------------------------------------------------------------
"""
from __future__ import annotations

from competitors.herfy.backend import models, offer_parser


def test_is_offer_product_true_for_offers_category(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2971976)  # Double Offer
    assert offer_parser.is_offer_product(product) is True


def test_is_offer_product_false_for_regular_category(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2996553)  # Beef Tortilla Meal
    assert offer_parser.is_offer_product(product) is False


def test_is_offer_product_true_for_a_real_discount():
    p = {"price": 15, "original-price": 20, "__categoryName": "Side Orders"}
    assert offer_parser.is_offer_product(p) is True


def test_is_offer_product_true_for_has_timed_event_flag():
    p = {"price": 10, "original-price": 10, "has-timed-event": True, "__categoryName": "Side Orders"}
    assert offer_parser.is_offer_product(p) is True


def test_is_offer_product_never_based_on_product_name_alone():
    """Spec: 'Do not classify or parse an offer using only its name.' A
    product whose own NAME sounds like a deal, but which has no real
    discount, no timed-event flag, and lives in a regular category, must
    not be classified as an offer."""
    p = {"name": {"en-us": "50% OFF SPECIAL DEAL BOX"}, "price": 19, "original-price": 19, "__categoryName": "Side Orders"}
    assert offer_parser.is_offer_product(p) is False


def test_is_offer_product_handles_missing_fields_gracefully():
    assert offer_parser.is_offer_product({}) is False


def test_is_offer_product_matches_category_case_and_whitespace_insensitively():
    p = {"price": 10, "original-price": 10, "__categoryName": "  offers  "}
    assert offer_parser.is_offer_product(p) is True


def test_offer_key_prefers_promo_id_over_product_key():
    key_with_promo = offer_parser.offer_key(29696, "PICKUP", "29696|PICKUP|id:1", "9583")
    key_without_promo = offer_parser.offer_key(29696, "PICKUP", "29696|PICKUP|id:1", None)
    assert key_with_promo == "29696|PICKUP|promo:9583"
    assert key_without_promo == "29696|PICKUP|offerprod:29696|PICKUP|id:1"
    assert key_with_promo != key_without_promo


def test_build_offer_snapshot_never_fabricates_a_discount_for_category_only_offer(pickup_result):
    product = next(p for p in pickup_result["products"] if p["id"] == 2971976)  # Double Offer - no real discount
    snap = offer_parser.build_offer_snapshot(
        product, product_key="29696|PICKUP|id:2971976", channel="PICKUP", branch_id=29696,
        run_id="run-1", captured_at="2026-08-01T06:05:00Z", progressive_promo_ids=set(),
    )
    assert snap["offer_name"] == "Double Offer"
    assert snap["offer_price"] == 17
    # KNOWN LIMITATION (see module docstring): no active discount exists
    # for this product (price == original-price) - never fabricated.
    assert snap["original_price"] is None
    assert snap["saving_amount"] is None
    assert snap["discount_percentage"] is None
    assert snap["offer_type"] == models.OFFER_TYPE_BUNDLE


def test_build_offer_snapshot_populates_a_real_discount_when_one_exists():
    p = {
        "name": {"en-us": "Discounted Combo"}, "price": 15, "original-price": 20,
        "description": {"en-us": "A real discount"}, "is-combo": False, "image-uri": None,
        "__categoryName": "Side Orders", "__optionGroups": [],
    }
    snap = offer_parser.build_offer_snapshot(
        p, product_key="29696|PICKUP|id:999", channel="PICKUP", branch_id=29696,
        run_id="run-1", captured_at="t", progressive_promo_ids=set(),
    )
    assert snap["offer_price"] == 15
    assert snap["original_price"] == 20
    assert snap["saving_amount"] == 5
    assert snap["discount_percentage"] == 25.0
    assert snap["offer_type"] == models.OFFER_TYPE_DISCOUNT
