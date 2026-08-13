"""
competitors/hardees/services/menu_service.py
---------------------------------------------------------------------
Category/product/product-detail retrieval built on api/client.py, plus
the normalization rules documented in
../research/api-map/field-map.json - e.g. the specialPrice<=0 and
promoId=-1 sentinels, and the bundle_group wrapper -> selectedItem
nested-id rule for /api/product (api-map.md "Product detail endpoint").
None of this re-derives those rules from scratch; each one links back to
the exact doc section it came from.
---------------------------------------------------------------------
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from shared_ui import OFFER_PRICE_COLUMNS, PRODUCT_PRICE_COLUMNS

from competitors.hardees.api.client import HardeesApiClient
from competitors.hardees.services.branch_service import ChannelContext

# Shared with KFC via shared_ui.price_columns — description + payable price
# first, menu names last.
PRODUCT_DISPLAY_COLUMNS = PRODUCT_PRICE_COLUMNS
OFFER_DISPLAY_COLUMNS = OFFER_PRICE_COLUMNS


def get_categories(client: HardeesApiClient, ctx: ChannelContext) -> list[dict]:
    """Category list for this channel's cluster - see api-map.json
    'getMenu'. Returns the raw categories[] array (id, name, productCount,
    services, ...)."""
    if not ctx.menu_temp_id:
        raise ValueError(f"Store {ctx.store_id} has no menuTempId - cannot call getMenu")
    menu = client.get_menu(
        menu_config_id=ctx.menu_config_id, cluster_id=ctx.cluster_id,
        menu_temp_id=ctx.menu_temp_id, service=ctx.service,
    )
    return menu.get("categories") or []


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(obj: dict, *keys: str) -> Any:
    for key in keys:
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
    return None


def _parse_percentage(value: Any) -> float | None:
    """Mirrors KFC normalizer.parse_percentage - disPercentage may be a
    bare number or a string like '33% OFF'."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def _normalize_promo_id(raw: Any) -> str | None:
    """promoId=-1 means no active offer (field-map.json) - same sentinel
    KFC uses; stored/displayed as None so both dashboards look identical."""
    if raw in (None, "", 0, "0", -1, "-1"):
        return None
    return str(raw)


def _normalize_special_price(special_raw: Any, regular: float | None) -> float | None:
    """specialPrice<=0 (or >= regular) is a sentinel, not a real price -
    same rule as KFC normalizer.normalize_special_price / field-map.json."""
    special = _to_float(special_raw)
    if special is None or special <= 0:
        return None
    if regular is not None and special >= regular:
        return None
    return special


def _description_en(product: dict) -> str | None:
    """Top-level description/longDesc/shortDesc, falling back to the
    selected nested item for bundle_group wrappers (field-map.json)."""
    top = _first_present(product, "description", "longDesc", "shortDesc")
    if top:
        return top
    selected_sku = product.get("selectedItem")
    for item in product.get("items") or []:
        if selected_sku is None or item.get("sku") == selected_sku:
            nested = _first_present(item, "description", "longDesc", "shortDesc")
            if nested:
                return nested
    return None


def _normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    return re.sub(r"\s+", " ", name).strip().lower()


def _sizes_label(product: dict) -> str | None:
    for variant in product.get("variants") or []:
        if str(variant.get("title") or "").strip().upper() == "SIZE":
            titles = [o.get("title") for o in (variant.get("options") or []) if o.get("title")]
            return ", ".join(titles) if titles else None
    return None


def _included_items_label(product: dict) -> str | None:
    names = [i.get("name") for i in (product.get("items") or []) if i.get("name")]
    return ", ".join(names) if names else None


def effective_price(product: dict) -> float | None:
    """specialPrice if (0 < specialPrice < originalPrice) else
    originalPrice - the sentinel rule from field-map.json
    'effective_price' (specialPrice<=0 does NOT mean free - see
    api-map.md 'Known sentinel values and quirks')."""
    regular = _to_float(product.get("originalPrice"))
    special = _normalize_special_price(product.get("specialPrice"), regular)
    return special if special is not None else regular


def has_active_offer(product: dict) -> bool:
    """promoId == -1 means 'no active offer' - field-map.json 'promo_id'."""
    return _normalize_promo_id(product.get("promoId")) is not None


def get_products(client: HardeesApiClient, ctx: ChannelContext, category_id: int) -> list[dict]:
    """Every product in one category - see api-map.json
    'getProductsByCategory'. Deliberately does not pass ctx.service - the
    live-verified payload for this endpoint carries no channel field at
    all (see api-map.md 'Channel separation mechanism')."""
    data = client.get_products_by_category(
        cluster_id=ctx.cluster_id, category_id=category_id, config_id=ctx.menu_config_id,
    )
    return data.get("products") or []


def image_url(product: dict) -> str | None:
    assets = product.get("assets") or []
    return assets[0].get("src") if assets and isinstance(assets[0], dict) else None


def _availability_flag(product: dict, service: str | None = None) -> int:
    """0/1 like KFC product_snapshots.availability. Uses the product's
    services object (note API misspelling 'delevery' - field-map.json)."""
    services = product.get("services") or {}
    if service == "PICKUP":
        return 1 if services.get("take_away") or services.get("tak") else 0
    if service == "DELIVERY":
        return 1 if services.get("delevery") or services.get("del") else 0
    if services.get("take_away") or services.get("tak") or services.get("delevery") or services.get("del"):
        return 1
    return 0


def summarize_product(
    product: dict, category: dict | None = None, *, channel: str | None = None,
) -> dict[str, Any]:
    """Flat row matching KFC's product_snapshots column vocabulary
    (competitors/kfc/backend/database.py + normalizer.py) so both
    dashboards show the same field names. Missing Hardee's fields
    (e.g. *_ar) are None rather than omitted or guessed."""
    name_en = product.get("name") or "(no name)"
    regular = _to_float(product.get("originalPrice"))
    special = _normalize_special_price(product.get("specialPrice"), regular)
    eff = special if special is not None else regular
    discount_amount = round(regular - special, 2) if (regular is not None and special is not None) else None
    discount_pct = _parse_percentage(product.get("disPercentage"))
    if discount_pct is None and discount_amount is not None and regular:
        discount_pct = round((discount_amount / regular) * 100, 2)
    promo_id = _normalize_promo_id(product.get("promoId"))

    return {
        "product_id": product.get("id"),
        "sku": str(product.get("sku")) if product.get("sku") not in (None, "") else None,
        "product_name_en": name_en,
        "product_name_ar": _first_present(product, "name_ar", "nameAr"),
        "normalized_name": _normalize_name(name_en),
        "category_id": category.get("id") if category else None,
        "category_name_en": category.get("name") if category else None,
        "category_name_ar": category.get("name_ar") if category else None,
        "description_en": _description_en(product),
        "description_ar": _first_present(product, "description_ar"),
        "currency": product.get("currency") or "SAR",
        "regular_price": regular,
        "special_price": special,
        "effective_price": eff,
        "discount_amount": discount_amount,
        "discount_percentage": discount_pct,
        "promo_id": promo_id,
        "has_offer": promo_id is not None,
        "limited_offer": 1 if product.get("limited_offer") else 0,
        "product_type": str(product.get("typeId")) if product.get("typeId") not in (None, "") else None,
        "bundle_type_id": product.get("bundleTypeId"),
        "availability": _availability_flag(product, channel),
        "image_url": image_url(product),
        "calories": _first_present(product, "calories", "kcal", "energy"),
        "sizes": _sizes_label(product),
        "number_of_pieces": None,
        "included_items": _included_items_label(product),
        "channel": channel,
        "is_bundle_wrapper": product.get("typeId") == "bundle_group" or product.get("bundleTypeId") == "bundle_group",
    }


def summarize_offer(
    product: dict, category: dict | None = None, *, channel: str | None = None,
) -> dict[str, Any]:
    """Flat row matching KFC's offer_snapshots vocabulary. An 'offer' is
    any product with an active promoId (field-map.json offer.offer_id)."""
    name = product.get("name") or "(no name)"
    regular = _to_float(product.get("originalPrice"))
    offer_price = _normalize_special_price(product.get("specialPrice"), regular)
    if offer_price is None:
        offer_price = regular
    saving = round(regular - offer_price, 2) if (regular is not None and offer_price is not None) else None
    discount_pct = _parse_percentage(product.get("disPercentage"))
    if discount_pct is None and saving and regular:
        discount_pct = round((saving / regular) * 100, 2)

    nested_main = None
    items = product.get("items") or []
    if items:
        nested_main = items[0].get("name")

    return {
        "promo_id": _normalize_promo_id(product.get("promoId")),
        "offer_name": name,
        "offer_description": _description_en(product),
        "main_item": nested_main or name,
        "included_items": _included_items_label(product),
        "number_of_pieces": None,
        "sizes": _sizes_label(product),
        "original_price": regular,
        "offer_price": offer_price,
        "saving_amount": saving,
        "discount_percentage": discount_pct,
        "offer_type": "Limited/day-scoped" if product.get("limited_offer") else "Standard",
        "bundle_type": product.get("bundleTypeId"),
        "currency": product.get("currency") or "SAR",
        "image_url": image_url(product),
        "category_id": category.get("id") if category else None,
        "category_name_en": category.get("name") if category else None,
        "channel": channel,
    }


def resolve_detail_lookup_id(product: dict) -> int | None:
    """THE rule from api-map.md 'Product detail endpoint', CORRECTED
    2026-08-06 (Streamlit-integration session) after a live smoke test
    caught a documentation error: a bundle_group wrapper's `selectedItem`
    field is the currently-selected nested item's **sku**, NOT its **id**
    (they happened to differ enough in earlier spot checks that this went
    unnoticed until this session compared them directly - live-confirmed
    on wrapper id=77772960 'Roast Beef Box': `selectedItem=945`, while
    `items[].sku=945` belongs to the item whose own `id=12187` - sending
    `945` itself to /api/product returns an empty data:{}, sending `12187`
    returns the full response). The correct rule: find the entry in the
    wrapper's own `items[]` array whose `sku` equals `selectedItem`, and
    use THAT entry's `id`. Falls back to the wrapper's own id if no
    items[] entry matches (should not happen on a well-formed response,
    but must never crash the UI - see unresolved-items.md for this
    correction's write-up)."""
    is_wrapper = product.get("typeId") == "bundle_group" or product.get("bundleTypeId") == "bundle_group"
    if not is_wrapper:
        return product.get("id")
    selected_sku = product.get("selectedItem")
    for item in product.get("items") or []:
        if item.get("sku") == selected_sku:
            return item.get("id")
    # No items[] entry matched selectedItem (e.g. items[] was empty in this
    # response) - fall back to the wrapper's own id rather than raising;
    # the caller (get_product_detail) already handles an empty-data result
    # gracefully via ProductDetailResult.empty.
    return product.get("id")


@dataclass
class ProductDetailResult:
    requested_id: int | None
    wrapper_id: int | None
    is_wrapper: bool
    category_id: int
    service: str
    raw: dict
    empty: bool  # True if the API returned HTTP 200 with an empty data:{} - see api-map.md's documented failure mode


def get_product_detail(
    client: HardeesApiClient, ctx: ChannelContext, category_id: int, product: dict,
) -> ProductDetailResult:
    """Calls POST /api/product for one product, resolving the
    bundle_group nested-item-id rule automatically (see
    resolve_detail_lookup_id above). Raises HardeesApiError on a real API
    error (network failure, WAF block, validation error) - callers
    (../ui/product_panel.py) show that message rather than crashing;
    an HTTP-200-but-empty response is NOT raised as an error (it is a
    documented, valid outcome - see ProductDetailResult.empty) so the UI
    can show a clear "no data returned" message instead of a generic
    exception."""
    lookup_id = resolve_detail_lookup_id(product)
    is_wrapper = product.get("typeId") == "bundle_group" or product.get("bundleTypeId") == "bundle_group"
    raw = client.get_product(
        product_id=lookup_id, cluster_id=ctx.cluster_id, category_id=category_id,
        service=ctx.service, menu_config_id=ctx.menu_config_id,
    )
    return ProductDetailResult(
        requested_id=lookup_id,
        wrapper_id=product.get("id") if is_wrapper else None,
        is_wrapper=is_wrapper,
        category_id=category_id,
        service=ctx.service,
        raw=raw,
        empty=not raw,
    )


def get_bundle_steps(
    client: HardeesApiClient, ctx: ChannelContext, category_id: int, product: dict,
) -> list[dict]:
    """POST /api/product-bundle-step for the same product - see
    api-map.json 'getProductBundleStep'. Exposed separately from
    get_product_detail() so the UI can show BOTH responses side by side
    and let the user see for themselves that they carry the same steps[]
    content (per api-map.md's finding) rather than asserting it."""
    lookup_id = resolve_detail_lookup_id(product)
    return client.get_product_bundle_step(
        product_id=lookup_id, cluster_id=ctx.cluster_id, category_id=category_id,
        service=ctx.service, menu_config_id=ctx.menu_config_id,
    )


def summarize_modifiers(detail_raw: dict) -> list[dict[str, Any]]:
    """Flattens a /api/product response's steps[]/variants[] into a
    single, readable table: one row per option, with its parent step
    title and type. Used by ../ui/product_panel.py's 'readable normalized
    view'. Never raises on a missing/unexpected shape - falls back to an
    empty list."""
    rows: list[dict[str, Any]] = []
    for variant in detail_raw.get("variants") or []:
        group_title = variant.get("title") or variant.get("subtitle") or "Variant"
        for option in variant.get("options") or []:
            rows.append({
                "group": group_title,
                "group_type": "variant",
                "option": option.get("title"),
                "price": None,  # variant options (SIZE/FLAVOR) carry no per-option price in samples observed
                "selected": bool(option.get("isSelected")),
            })
    for step in detail_raw.get("steps") or []:
        group_title = step.get("title") or "Step"
        for option in step.get("options") or []:
            rows.append({
                "group": group_title,
                "group_type": step.get("type") or "step",
                "option": option.get("title"),
                "price": option.get("price"),
                "selected": bool(option.get("defaultSelected")),
            })
    return rows
