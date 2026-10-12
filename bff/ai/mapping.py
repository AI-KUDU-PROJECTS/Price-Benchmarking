"""AI mapping: for one KUDU item, suggest the closest item at each competitor.

The model sees the KUDU item, every competitor item in the same channel
(names, categories, descriptions - never prices), and the matching rules
agreed with Marketing. It returns one suggestion per competitor; the server
keeps only suggestions that point to a real product. Saving is a normal
Playground mapping, done by the user after review.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from bff.ai import store
from bff.contract import KNOWN_BRANDS, Channel, Product, dump
from bff.registry import connected_adapters

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULT_MODEL = "claude-opus-5-5"
DESCRIPTION_LIMIT = 300
CHANNEL_LABELS = {"pickup": "Pickup", "delivery": "Delivery", "hungerstation": "HungerStation"}
# Agreed with Marketing: HungerStation meals compare at Medium, the
# brands' own pickup/delivery menus at Regular.
DEFAULT_SIZE = {"hungerstation": "medium", "pickup": "regular", "delivery": "regular"}

# USD per million tokens: input, output, cache read. Cache writes cost 1.25x
# input. Used for the spend estimate shown in the app, not an invoice.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}

RULES = """\
You match menu items for KUDU, a Saudi fast-food brand, against its
competitors so the Marketing team can compare prices. The system message
below lists every competitor item sold in one sales channel. The user
message gives one KUDU item. For each competitor brand in the list, choose
the single closest item to the KUDU item, or none.

Matching rules, agreed with KUDU Marketing:
1. Requirements. An item that fails any of these is not a match:
   - Same kind of item. A meal (a main with a side and a drink) matches
     only a meal. A sandwich, burger, or wrap sold alone matches only one
     sold alone. A kids meal matches only a kids meal, a sharing or family
     box only a sharing box, and chicken pieces, nuggets, or strips only the
     same. Sides, drinks, desserts, and sauces match only their own kind.
   - Same main protein: chicken, beef, fish, shrimp, egg, or vegetarian.
   - Same audience (kids or regular) and same daypart (breakfast or all-day).
   - Not a temporary promo bundle: a deal that combines different products
     or several units for one price ("5 FOR 38", "Burger box + 12 Chicken
     Bites", "Double Up Deal"). Never suggest one. If the KUDU item is such
     a bundle, return none for every brand.
2. Among items that meet the requirements, prefer the same format (burger
   in a bun, wrap or tortilla, toast or sliced bread, pieces), the same
   cooking (crispy or fried versus grilled), and the same counts (patties or
   fillets per sandwich, number of sandwiches, number of pieces).
3. Size. When a competitor lists the same item in several sizes as separate
   items, choose the size named in the request's "default_size". Otherwise
   choose the closest size.
4. A spicy item and a regular item are equivalent only when the competitor
   has no version with the same heat. If you match them, list it in
   differences.
5. Do not choose based on toppings or add-ons such as cheese, lettuce, or
   sauces. List notable ones in differences.
6. Use the item names, categories, and descriptions. When a description is
   short, you may use well-known facts about a brand's standard items (for
   example, KFC's Zinger is a crispy chicken fillet burger and its Twister
   is a wrap). Prices are not provided; do not consider them.

For every competitor brand in the list, return one entry:
- ref: the chosen item's "ref", copied exactly as listed, or "" when none.
- alternative_ref: a second item that is almost as close, or "".
- confidence:
  - high: all requirements are met, and format, cooking, and counts match.
  - medium: all requirements are met, with one notable difference (count,
    size, heat, tier) or an uncertain fact.
  - none: no item meets the requirements; ref and alternative_ref are "".
- reason: one short English sentence on why this is the closest item, or
  why there is none.
- differences: a short English list of how the item differs from the KUDU
  item, or "" when it does not differ.
"""


class AiError(Exception):
    """An AI request failed in a way the user should see."""


@dataclass(frozen=True)
class Candidate:
    ref: str
    brand_id: str
    brand_name: str
    product: Product


def model_name() -> str:
    return (os.environ.get("AI_MODEL") or "").strip() or DEFAULT_MODEL


def effort() -> str:
    return (os.environ.get("AI_EFFORT") or "").strip() or "medium"


def is_configured() -> bool:
    return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())


def estimate_cost(model: str, usage: dict[str, int]) -> float | None:
    prices = PRICES.get(model)
    if prices is None:
        return None
    input_price, output_price, cache_read_price = prices
    return round((
        usage["input_tokens"] * input_price
        + usage["cache_write_tokens"] * input_price * 1.25
        + usage["cache_read_tokens"] * cache_read_price
        + usage["output_tokens"] * output_price
    ) / 1_000_000, 6)


def _client():
    import anthropic

    return anthropic.Anthropic()


def _fallback_kwargs(model: str) -> dict[str, Any]:
    # Server-side fallback re-runs a declined request on Anthropic's
    # recommended model. Haiku has no server-side fallback.
    if model.startswith(("claude-opus", "claude-sonnet-5-5", "claude-fable")):
        return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    return {}


def _describe(product: Product) -> dict[str, Any]:
    """What the model sees about an item. Deliberately no prices."""
    description = product.description_en or product.description_ar or ""
    fields = {
        "name_en": product.name_en,
        "name_ar": product.name_ar,
        "category": product.category,
        "description": description[:DESCRIPTION_LIMIT],
        "calories": product.calories,
    }
    return {key: value for key, value in fields.items() if value}


def competitor_candidates(channel: Channel) -> list[Candidate]:
    """Every priced competitor item in the channel, in a stable order so the
    menu text (and its prompt cache) only changes when the data does."""
    names = dict(KNOWN_BRANDS)
    candidates: list[Candidate] = []
    for brand_id, adapter in connected_adapters().items():
        if brand_id == "kudu":
            continue
        products = [
            product for product in adapter.list_products(channel=channel)
            if product.availability is not False
            and (product.special_price if product.special_price is not None else product.regular_price) is not None
        ]
        products.sort(key=lambda product: (product.name_en or product.name_ar or "", product.id))
        candidates.extend(
            Candidate(f"{brand_id}:{index}", brand_id, names.get(brand_id, brand_id), product)
            for index, product in enumerate(products, start=1)
        )
    return candidates


def menu_text(channel: Channel, candidates: list[Candidate]) -> str:
    brands: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        entry = brands.setdefault(
            candidate.brand_id,
            {"brand_id": candidate.brand_id, "brand": candidate.brand_name, "items": []},
        )
        entry["items"].append({"ref": candidate.ref, **_describe(candidate.product)})
    return (
        f"Competitor items sold on {CHANNEL_LABELS[channel]}:\n"
        + json.dumps(list(brands.values()), ensure_ascii=False)
    )


def _schema(brand_ids: list[str]) -> dict[str, Any]:
    match = {
        "type": "object",
        "properties": {
            "brand_id": {"type": "string", "enum": brand_ids},
            "ref": {"type": "string"},
            "alternative_ref": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "none"]},
            "reason": {"type": "string"},
            "differences": {"type": "string"},
        },
        "required": ["brand_id", "ref", "alternative_ref", "confidence", "reason", "differences"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"matches": {"type": "array", "items": match}},
        "required": ["matches"],
        "additionalProperties": False,
    }


def suggest(kudu_product: Product, channel: Channel, *, client: Any = None) -> dict[str, Any]:
    started = time.monotonic()
    candidates = competitor_candidates(channel)
    if not candidates:
        raise AiError(f"No competitor items with prices on {CHANNEL_LABELS[channel]}.")
    by_ref = {candidate.ref: candidate for candidate in candidates}
    brand_ids = list(dict.fromkeys(candidate.brand_id for candidate in candidates))
    if client is None:
        if not is_configured():
            raise AiError("ANTHROPIC_API_KEY is not set on the server.")
        client = _client()

    model = model_name()
    request = {
        "channel": CHANNEL_LABELS[channel],
        "default_size": DEFAULT_SIZE[channel],
        "kudu_item": _describe(kudu_product),
    }
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        system=[
            {"type": "text", "text": RULES},
            # The menu is the large, repeated part: cache it so the next
            # item in the same channel reads it at a tenth of the price.
            {"type": "text", "text": menu_text(channel, candidates), "cache_control": {"type": "ephemeral"}},
        ],
        output_config={"effort": effort(), "format": {"type": "json_schema", "schema": _schema(brand_ids)}},
        messages=[{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
        **_fallback_kwargs(model),
    )
    raw = response.usage
    usage = {
        "input_tokens": raw.input_tokens or 0,
        "output_tokens": raw.output_tokens or 0,
        "cache_read_tokens": getattr(raw, "cache_read_input_tokens", 0) or 0,
        "cache_write_tokens": getattr(raw, "cache_creation_input_tokens", 0) or 0,
    }
    cost = estimate_cost(model, usage)
    store.record_usage("mapping", model, usage, cost)
    if response.stop_reason == "refusal":
        raise AiError("The AI declined this request.")
    if response.stop_reason == "max_tokens":
        raise AiError("The AI response was cut off. Try again.")
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        raw_matches = json.loads(text)["matches"]
    except (ValueError, KeyError, TypeError):
        raise AiError("The AI returned an unreadable response.") from None

    def pick(ref: str, brand_id: str) -> Candidate | None:
        candidate = by_ref.get(ref)
        return candidate if candidate is not None and candidate.brand_id == brand_id else None

    matches: dict[str, dict[str, Any]] = {}
    for raw_match in raw_matches:
        brand_id = raw_match.get("brand_id")
        if brand_id not in brand_ids or brand_id in matches:
            continue
        chosen = pick(raw_match.get("ref", ""), brand_id)
        alternative = pick(raw_match.get("alternative_ref", ""), brand_id)
        confidence = raw_match.get("confidence", "none") if chosen else "none"
        reason = raw_match.get("reason", "")
        if raw_match.get("ref") and chosen is None:
            reason = "The AI pointed to an item that is not on this menu, so it was dropped."
        matches[brand_id] = {
            "brandId": brand_id,
            "brandName": dict(KNOWN_BRANDS).get(brand_id, brand_id),
            "product": dump(chosen.product) if chosen else None,
            "alternative": dump(alternative.product) if alternative and alternative is not chosen else None,
            "confidence": confidence,
            "reason": reason,
            "differences": raw_match.get("differences", "") if chosen else "",
        }
    for brand_id in brand_ids:
        matches.setdefault(brand_id, {
            "brandId": brand_id,
            "brandName": dict(KNOWN_BRANDS).get(brand_id, brand_id),
            "product": None,
            "alternative": None,
            "confidence": "none",
            "reason": "The AI returned no suggestion for this brand.",
            "differences": "",
        })
    return {
        "kuduProduct": dump(kudu_product),
        "channel": channel,
        "matches": [matches[brand_id] for brand_id in brand_ids],
        "model": model,
        "costUsd": round(cost or 0.0, 4),
        "seconds": round(time.monotonic() - started, 1),
    }
