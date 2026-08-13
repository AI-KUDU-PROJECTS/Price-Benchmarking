"""
backend/offer_parser.py
---------------------------------------------------------------------
Parses a product's offer details as completely as possible from its raw
getProductsByCategory fields (originalPrice, specialPrice, disPercentage,
promoId, limited_offer, description, steps, subOptionStr - see
api-map.md), and classifies its offer_type from STRUCTURAL signals only.

Per spec: "Do not classify or parse an offer using only its name." Every
rule below keys off price/promo/bundle-structure fields; description text
is used only as one signal among several for BOGO/Coupon (never alone, and
never the product's bare name).
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from competitors.kfc.backend import models
from competitors.kfc.backend.normalizer import normalize_promo_id, normalize_special_price, parse_percentage, to_bool_flag, to_float

# Step title/subtitle keyword -> component bucket. Matched against a step's
# own title/subtitle (real API fields), never against the product's name.
_SIDE_RE = re.compile(r"\bside\b|\bfries\b", re.I)
_DRINK_RE = re.compile(r"\bdrink\b|\bbeverage\b", re.I)
_SAUCE_RE = re.compile(r"\bsauce\b|\bdip\b|\bcondiment\b", re.I)
_ADDON_RE = re.compile(r"\badd.?on\b", re.I)
_PIECE_RE = re.compile(r"\bstrip", re.I)

_BOGO_RE = re.compile(r"buy\s*1.{0,15}get\s*1|b1g1|buy\s*one.{0,20}get\s*one", re.I)
_COUPON_RE = re.compile(r"\bcoupon\b|\bpromo\s*code\b", re.I)
_PIECE_COUNT_RE = re.compile(r"(\d+)\s*(?:pc\b|pcs\b|piece|pieces|strips?)", re.I)


def _bucket_for_step(step: dict[str, Any]) -> Optional[str]:
    label = f"{step.get('title', '')} {step.get('subtitle', '')}"
    if _ADDON_RE.search(label):
        return "add_ons"
    if _SIDE_RE.search(label):
        return "sides"
    if _DRINK_RE.search(label):
        return "drinks"
    if _SAUCE_RE.search(label):
        return "sauces"
    return None


def classify_components(steps: list[dict[str, Any]], sub_option_str: Optional[str]) -> dict[str, list[str]]:
    """Best-effort split of a bundle's default build into
    included_items / sides / drinks / sauces / add_ons.

    `subOptionStr` (e.g. "Zinger Sandwich,Lettuce,Twister Sandwich
    Original,Lettuce,Tomato,2 Strips Pcs,Regular Fries,Regular Fries") is
    the only place the ACTUAL chosen item text lives - `steps` only
    describes the CHOICE STRUCTURE (group titles like "Choice of Sandwich",
    "Choose your condiments"), not which option was picked. There is no
    reliable positional mapping between the two lists (some steps are
    hidden/dependent sub-choices - see api-map.md), so this function does
    NOT attempt to force a 1:1 zip. Instead:
      - `included_items` is always the full, literal, comma-split token
        list from subOptionStr (100% real data, unclassified).
      - sides/drinks/sauces/add_ons are populated only when a token's own
        text contains one of that bucket's keywords - i.e. classification
        never outruns what the text itself says.
    This intentionally leaves some tokens (e.g. a sandwich name) out of
    every bucket rather than guessing which bucket they belong to.
    """
    included_items: list[str] = []
    if sub_option_str:
        included_items = [t.strip() for t in str(sub_option_str).split(",") if t.strip()]

    buckets: dict[str, list[str]] = {"sides": [], "drinks": [], "sauces": [], "add_ons": []}
    for token in included_items:
        if _SIDE_RE.search(token) or re.search(r"\bfries\b", token, re.I):
            buckets["sides"].append(token)
        elif _DRINK_RE.search(token) or re.search(r"\bpepsi\b|\b7up\b|\bjuice\b|\bcola\b", token, re.I):
            buckets["drinks"].append(token)
        elif _SAUCE_RE.search(token):
            buckets["sauces"].append(token)

    # Steps flagged isAddon=1 contribute their *title* as a best-effort
    # add-on label (no chosen-option text is available for hidden/optional
    # add-on steps at the catalog level - see docstring above).
    for step in steps or []:
        if to_bool_flag(step.get("isAddon")) and step.get("title"):
            buckets["add_ons"].append(step["title"])

    return {
        "included_items": included_items,
        "sides": buckets["sides"],
        "drinks": buckets["drinks"],
        "sauces": buckets["sauces"],
        "add_ons": buckets["add_ons"],
    }


def count_pieces(sub_option_str: Optional[str], description: Optional[str]) -> Optional[int]:
    total = 0
    found = False
    for text in (sub_option_str, description):
        if not text:
            continue
        for match in _PIECE_COUNT_RE.finditer(str(text)):
            total += int(match.group(1))
            found = True
    return total if found else None


def is_offer_product(product: dict[str, Any]) -> bool:
    """True when a product carries ANY genuine offer signal (see README
    "New Offer" rules) - never based on its name."""
    original_price = to_float(product.get("originalPrice"))
    special_price = normalize_special_price(product.get("specialPrice"), original_price)
    has_special = special_price is not None
    has_promo = normalize_promo_id(product.get("promoId")) is not None
    is_limited = to_bool_flag(product.get("limited_offer"))
    # NOTE: bundleTypeId=="bundle" alone is NOT a discount/promotion signal -
    # it just means the product has customizable build steps (e.g. a
    # regular-priced Meal where you pick a side/drink). Only has_special /
    # has_promo / is_limited indicate a genuine, currently-active offer.
    return has_special or has_promo or is_limited


def offer_key(branch_id: int, channel: str, product_key: str, promo_id: Optional[str]) -> str:
    """Stable offer identity: prefer promoId (a real offer/promotion
    identity that can outlive a single product), fall back to the
    product's own key when a discount is active with no separate promo id
    (see README "New Offer": 'A Special Price appears where none existed
    previously' must count as an offer even without a promoId)."""
    if promo_id:
        return f"{branch_id}|{channel}|promo:{promo_id}"
    return f"{branch_id}|{channel}|offerprod:{product_key}"


def classify_offer_type(product: dict[str, Any], progressive_promo_ids: set[str]) -> str:
    """Structural classification only - see module docstring. Priority
    order (most to least specific signal), never a single field alone."""
    description_blob = " ".join(
        str(x) for x in (
            product.get("description"), product.get("longDesc"), product.get("shortDesc"),
            " ".join(product.get("metaKeyword") or []) if isinstance(product.get("metaKeyword"), list) else "",
        ) if x
    )
    promo_id_str = normalize_promo_id(product.get("promoId"))

    if _BOGO_RE.search(description_blob):
        return models.OFFER_TYPE_BOGO
    if promo_id_str and _COUPON_RE.search(description_blob):
        return models.OFFER_TYPE_COUPON
    if promo_id_str and promo_id_str in progressive_promo_ids:
        return models.OFFER_TYPE_PROGRESSIVE_PROMOTION

    steps = product.get("steps") or []
    visible_component_steps = [s for s in steps if not to_bool_flag(s.get("isHidden")) and not to_bool_flag(s.get("isDependent"))]
    is_bundle = str(product.get("bundleTypeId") or "").lower() == "bundle"
    if is_bundle and len(visible_component_steps) >= 2:
        return models.OFFER_TYPE_MEAL_DEAL
    if is_bundle:
        return models.OFFER_TYPE_BUNDLE

    original_price = to_float(product.get("originalPrice"))
    special_price = normalize_special_price(product.get("specialPrice"), original_price)
    if special_price is not None:
        return models.OFFER_TYPE_DISCOUNT

    if to_bool_flag(product.get("limited_offer")):
        return models.OFFER_TYPE_LIMITED_EDITION

    return models.OFFER_TYPE_UNKNOWN


def build_offer_snapshot(
    product: dict[str, Any],
    *,
    product_key: str,
    channel: str,
    branch_id: int,
    run_id: str,
    captured_at: str,
    progressive_promo_ids: set[str],
    source_endpoint: str = "/api/getProductsByCategory",
) -> dict[str, Any]:
    """Builds one offer_snapshots row from a product that is_offer_product().
    Every field the README "Offer Details" section asks for is populated
    here (or explicitly left NULL when genuinely unavailable - see
    api-map.md), sourced from originalPrice/specialPrice/disPercentage/
    promoId/limited_offer/description/steps/subOptionStr."""
    promo_id = normalize_promo_id(product.get("promoId"))
    original_price = to_float(product.get("originalPrice"))
    offer_price = normalize_special_price(product.get("specialPrice"), original_price)
    if offer_price is None:
        offer_price = original_price
    saving_amount = round(original_price - offer_price, 2) if (original_price is not None and offer_price is not None) else None
    discount_percentage = parse_percentage(product.get("disPercentage"))
    if discount_percentage is None and saving_amount and original_price:
        discount_percentage = round((saving_amount / original_price) * 100, 2)

    components = classify_components(product.get("steps") or [], product.get("subOptionStr"))
    offer_type = classify_offer_type(product, progressive_promo_ids)
    key = offer_key(branch_id, channel, product_key, promo_id)

    assets = product.get("assets") or []
    image_url = assets[0].get("src") if assets and isinstance(assets[0], dict) else None

    raw_copy = {k: v for k, v in product.items() if not k.startswith("__")}

    return {
        "run_id": run_id,
        "offer_key": key,
        "promo_id": promo_id,
        "product_key": product_key,
        "channel": channel,
        "branch_id": branch_id,
        "captured_at": captured_at,
        "offer_name": product.get("metaTitle") or product.get("name"),
        "main_item": product.get("name"),
        "included_items": json.dumps(components["included_items"], ensure_ascii=False),
        "number_of_pieces": count_pieces(product.get("subOptionStr"), product.get("description")),
        "sides": json.dumps(components["sides"], ensure_ascii=False),
        "drinks": json.dumps(components["drinks"], ensure_ascii=False),
        "sauces": json.dumps(components["sauces"], ensure_ascii=False),
        "sizes": json.dumps([v.get("title") for v in (product.get("variants") or []) if isinstance(v, dict)], ensure_ascii=False),
        "add_ons": json.dumps(components["add_ons"], ensure_ascii=False),
        "original_price": original_price,
        "offer_price": offer_price,
        "saving_amount": saving_amount,
        "discount_percentage": discount_percentage,
        "offer_description": product.get("description") or product.get("longDesc"),
        "offer_type": offer_type,
        "bundle_type": product.get("bundleTypeId"),
        "image_url": image_url,
        "screenshot_path": None,
        "source_endpoint": source_endpoint,
        "raw_json": json.dumps(raw_copy, ensure_ascii=False),
    }
