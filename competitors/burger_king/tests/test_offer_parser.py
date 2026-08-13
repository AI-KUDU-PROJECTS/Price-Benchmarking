"""
tests/test_offer_parser.py
---------------------------------------------------------------------
Covers the confirmed offer-detection signal for this brand (see
backend/offer_parser.py module docstring): "KING DAILY DEALS" is Burger
King's own CMS-curated combo-bundle-deals category (confirmed live
2026-08-11), while the superficially similar "KING SAVERS" category is
deliberately excluded (it is the permanent budget/value menu, not
time-limited deals - see module docstring). Neither classification is
based on a product's own name/description text, per the "do not classify
or parse an offer using only its name" rule established for KFC - this
uses the site's own CMS category assignment instead.
---------------------------------------------------------------------
"""
from __future__ import annotations

from competitors.burger_king.backend import models, offer_parser


def test_is_offer_product_true_for_king_daily_deals_category():
    p = {"name": {"locale": "CHEESEBURGER LOVERS"}, "__categoryName": "KING DAILY DEALS", "__price": 39}
    assert offer_parser.is_offer_product(p) is True


def test_is_offer_product_false_for_king_savers_category():
    """KING SAVERS is BK's permanent budget menu (cheapest individual
    items, no discount signal) - explicitly rejected, see module
    docstring."""
    p = {"name": {"locale": "HAMBURGER"}, "__categoryName": "KING SAVERS", "__price": 5}
    assert offer_parser.is_offer_product(p) is False


def test_is_offer_product_false_for_regular_category():
    p = {"name": {"locale": "WHOPPER"}, "__categoryName": "FLAME-GRILLED BURGERS", "__price": 29}
    assert offer_parser.is_offer_product(p) is False


def test_is_offer_product_never_based_on_product_name_alone():
    """Spec: 'Do not classify or parse an offer using only its name.' A
    product whose own NAME sounds like a deal, but which lives in a
    regular (non-deals) category, must not be classified as an offer."""
    p = {"name": {"locale": "50% OFF SPECIAL DEAL BOX"}, "__categoryName": "KING SNACKS", "__price": 19}
    assert offer_parser.is_offer_product(p) is False


def test_is_offer_product_handles_missing_category_gracefully():
    assert offer_parser.is_offer_product({"name": {"locale": "X"}}) is False
    assert offer_parser.is_offer_product({}) is False


def test_is_offer_product_matches_case_and_whitespace_insensitively():
    """Compared via normalize_text() (see module docstring) so a trivial
    capitalization/whitespace difference in a future menu republish can
    never silently break this match."""
    p = {"name": {"locale": "X"}, "__categoryName": "  king   daily deals!! "}
    assert offer_parser.is_offer_product(p) is True


def test_offer_key_prefers_promo_id_over_product_key():
    key_with_promo = offer_parser.offer_key(11474, "PICKUP", "11474|PICKUP|id:abc", "9583")
    key_without_promo = offer_parser.offer_key(11474, "PICKUP", "11474|PICKUP|id:abc", None)
    assert key_with_promo == "11474|PICKUP|promo:9583"
    assert key_without_promo == "11474|PICKUP|offerprod:11474|PICKUP|id:abc"
    assert key_with_promo != key_without_promo


def test_build_offer_snapshot_never_fabricates_a_discount(pickup_result):
    product = next(p for p in pickup_result["products"] if p["_id"] == "b10d5e39-7a05-4207-b078-dd1ea35e0c08")  # Cheeseburger Lovers
    assert offer_parser.is_offer_product(product) is True
    snap = offer_parser.build_offer_snapshot(
        product, product_key="11474|PICKUP|id:b10d5e39-7a05-4207-b078-dd1ea35e0c08", channel="PICKUP",
        branch_id=11474, run_id="run-1", captured_at="2026-08-01T06:05:00Z", progressive_promo_ids=set(),
    )
    assert snap["offer_name"] == "CHEESEBURGER LOVERS"
    assert snap["offer_price"] == 39
    # KNOWN LIMITATION (see module docstring): no confirmed "before" price
    # exists anywhere in the collected data - never guessed.
    assert snap["original_price"] is None
    assert snap["saving_amount"] is None
    assert snap["discount_percentage"] is None
    assert snap["offer_type"] == models.OFFER_TYPE_BUNDLE
    assert snap["promo_id"] is None
    assert snap["offer_key"] == "11474|PICKUP|offerprod:11474|PICKUP|id:b10d5e39-7a05-4207-b078-dd1ea35e0c08"
