"""
competitors/hardees/services/comparison_service.py
---------------------------------------------------------------------
Pickup-vs-Delivery comparison logic. Per the task's explicit instruction
("Do not assume the channels are identical; compare the actual returned
data") and ../research/api-map/api-map.md's own "Channel separation
mechanism" section, this module NEVER short-circuits on the assumption
that both channels return the same thing - it always fetches each
channel's own data independently (via two separate ChannelContext
values - see branch_service.py) and diffs the actual results field by
field. The research phase found them identical on every branch tested so
far; this code does not encode that as a shortcut, so it would correctly
surface a real difference if one appears on a future branch/day.
---------------------------------------------------------------------
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import menu_service
from competitors.hardees.services.branch_service import ChannelContext

# Labels used consistently across the UI - see product_panel.py/comparison_panel.py.
IDENTICAL = "identical"
DIFFERENT = "different"
UNAVAILABLE_PICKUP = "unavailable in Pickup"
UNAVAILABLE_DELIVERY = "unavailable in Delivery"
NOT_COMPARABLE = "comparison not possible"


@dataclass
class FieldComparison:
    field: str
    pickup_value: Any
    delivery_value: Any
    verdict: str


@dataclass
class ProductComparison:
    product_id: Any
    name: str
    fields: list[FieldComparison] = field(default_factory=list)

    @property
    def overall_verdict(self) -> str:
        verdicts = {f.verdict for f in self.fields}
        if not verdicts:
            return NOT_COMPARABLE
        if verdicts == {IDENTICAL}:
            return IDENTICAL
        if UNAVAILABLE_PICKUP in verdicts or UNAVAILABLE_DELIVERY in verdicts:
            return UNAVAILABLE_PICKUP if UNAVAILABLE_PICKUP in verdicts else UNAVAILABLE_DELIVERY
        return DIFFERENT


@dataclass
class CategoryComparisonResult:
    category_id: int
    pickup_ctx: ChannelContext
    delivery_ctx: ChannelContext
    menu_config_comparison: FieldComparison
    cluster_comparison: FieldComparison
    products: list[ProductComparison] = field(default_factory=list)
    pickup_error: str | None = None
    delivery_error: str | None = None

    @property
    def summary_counts(self) -> dict[str, int]:
        counts = {IDENTICAL: 0, DIFFERENT: 0, UNAVAILABLE_PICKUP: 0, UNAVAILABLE_DELIVERY: 0, NOT_COMPARABLE: 0}
        for p in self.products:
            counts[p.overall_verdict] = counts.get(p.overall_verdict, 0) + 1
        return counts


_PRODUCT_COMPARE_FIELDS = ("originalPrice", "specialPrice", "promoId", "limited_offer")


def _compare_value(pickup_val: Any, delivery_val: Any) -> str:
    if pickup_val is None and delivery_val is None:
        return NOT_COMPARABLE
    if pickup_val is None:
        return UNAVAILABLE_PICKUP
    if delivery_val is None:
        return UNAVAILABLE_DELIVERY
    return IDENTICAL if pickup_val == delivery_val else DIFFERENT


def compare_category(
    client: HardeesApiClient, pickup_ctx: ChannelContext, delivery_ctx: ChannelContext, category_id: int,
) -> CategoryComparisonResult:
    """Fetches getProductsByCategory independently under EACH channel
    context and diffs every product found in either. A product missing
    from one channel's response is labeled unavailable-in-that-channel,
    not silently skipped."""
    menu_cmp = FieldComparison(
        "menuConfigId", pickup_ctx.menu_config_id, delivery_ctx.menu_config_id,
        _compare_value(pickup_ctx.menu_config_id, delivery_ctx.menu_config_id),
    )
    cluster_cmp = FieldComparison(
        "clusterId", pickup_ctx.cluster_id, delivery_ctx.cluster_id,
        _compare_value(pickup_ctx.cluster_id, delivery_ctx.cluster_id),
    )

    result = CategoryComparisonResult(
        category_id=category_id, pickup_ctx=pickup_ctx, delivery_ctx=delivery_ctx,
        menu_config_comparison=menu_cmp, cluster_comparison=cluster_cmp,
    )

    pickup_products: list[dict] = []
    delivery_products: list[dict] = []
    try:
        pickup_products = menu_service.get_products(client, pickup_ctx, category_id)
    except HardeesApiError as e:
        result.pickup_error = str(e)
    try:
        delivery_products = menu_service.get_products(client, delivery_ctx, category_id)
    except HardeesApiError as e:
        result.delivery_error = str(e)

    by_id_pickup = {p.get("id"): p for p in pickup_products}
    by_id_delivery = {p.get("id"): p for p in delivery_products}
    all_ids = list(dict.fromkeys(list(by_id_pickup.keys()) + list(by_id_delivery.keys())))

    for pid in all_ids:
        p_prod = by_id_pickup.get(pid)
        d_prod = by_id_delivery.get(pid)
        name = (p_prod or d_prod or {}).get("name") or f"product {pid}"
        pc = ProductComparison(product_id=pid, name=name)
        for f in _PRODUCT_COMPARE_FIELDS:
            pv = p_prod.get(f) if p_prod else None
            dv = d_prod.get(f) if d_prod else None
            pc.fields.append(FieldComparison(f, pv, dv, _compare_value(pv, dv)))
        # availability flags come from the SAME shared 'services' object per product
        # (api-map.md: this is a per-product flag, not a per-channel-response
        # difference) - compare take_away vs delevery flags as an extra signal.
        p_services = (p_prod or {}).get("services") or {}
        d_services = (d_prod or {}).get("services") or {}
        pc.fields.append(FieldComparison(
            "availability_flags", p_services, d_services, _compare_value(str(p_services), str(d_services)),
        ))
        result.products.append(pc)

    return result


def compare_product_detail(
    client: HardeesApiClient, pickup_ctx: ChannelContext, delivery_ctx: ChannelContext, category_id: int, product: dict,
) -> list[FieldComparison]:
    """Calls POST /api/product independently for Pickup and Delivery
    (same product, same category, explicit service field each time - see
    api/client.py's get_product()) and diffs the base price plus every
    modifier-option price found in either response's steps[].options[].
    This is the modifier-price-level comparison the task explicitly asks
    for, not just a base-price diff."""
    comparisons: list[FieldComparison] = []
    pickup_detail = delivery_detail = None
    pickup_err = delivery_err = None
    try:
        pickup_detail = menu_service.get_product_detail(client, pickup_ctx, category_id, product)
    except HardeesApiError as e:
        pickup_err = str(e)
    try:
        delivery_detail = menu_service.get_product_detail(client, delivery_ctx, category_id, product)
    except HardeesApiError as e:
        delivery_err = str(e)

    if pickup_err or delivery_err:
        comparisons.append(FieldComparison("fetch_error", pickup_err, delivery_err, NOT_COMPARABLE))
        return comparisons

    p_raw = pickup_detail.raw if pickup_detail and not pickup_detail.empty else {}
    d_raw = delivery_detail.raw if delivery_detail and not delivery_detail.empty else {}

    for f in ("originalPrice", "specialPrice", "promoId", "currency"):
        pv, dv = p_raw.get(f), d_raw.get(f)
        comparisons.append(FieldComparison(f, pv, dv, _compare_value(pv, dv)))

    p_options = {(s.get("title"), o.get("title")): o.get("price") for s in (p_raw.get("steps") or []) for o in (s.get("options") or [])}
    d_options = {(s.get("title"), o.get("title")): o.get("price") for s in (d_raw.get("steps") or []) for o in (s.get("options") or [])}
    all_keys = list(dict.fromkeys(list(p_options.keys()) + list(d_options.keys())))
    for key in all_keys:
        pv, dv = p_options.get(key), d_options.get(key)
        label = f"{key[0]} / {key[1]}"
        comparisons.append(FieldComparison(label, pv, dv, _compare_value(pv, dv)))

    return comparisons
