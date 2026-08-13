"""
competitors/hardees/ui/comparison_panel.py
---------------------------------------------------------------------
"Comparison view" section - Pickup vs Delivery, for either a whole
category (base prices/offers/availability) or one specific product
(base price + every modifier-option price). Triggered only by an
explicit button - see services/comparison_service.py for the actual
diff logic (this module only renders its result).
---------------------------------------------------------------------
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import comparison_service as cmp
from competitors.hardees.services.branch_service import ChannelContext
from competitors.hardees.services.sanitize import error_message
from competitors.hardees.ui import menu_panel
from competitors.hardees.ui import state as ui_state

_VERDICT_ICON = {
    cmp.IDENTICAL: "✅ identical",
    cmp.DIFFERENT: "⚠️ different",
    cmp.UNAVAILABLE_PICKUP: "🚫 unavailable in Pickup",
    cmp.UNAVAILABLE_DELIVERY: "🚫 unavailable in Delivery",
    cmp.NOT_COMPARABLE: "❔ comparison not possible",
}


@st.cache_data(show_spinner="Comparing Pickup vs Delivery for this category...")
def _cached_category_comparison(_client: HardeesApiClient, pickup_key: tuple, delivery_key: tuple, category_id: int):
    pickup_ctx = ui_state.get_ctx(pickup_key)
    delivery_ctx = ui_state.get_ctx(delivery_key)
    return cmp.compare_category(_client, pickup_ctx, delivery_ctx, category_id)


@st.cache_data(show_spinner="Comparing Pickup vs Delivery for this product...")
def _cached_product_comparison(_client: HardeesApiClient, pickup_key: tuple, delivery_key: tuple, category_id: int, product_id):
    pickup_ctx = ui_state.get_ctx(pickup_key)
    delivery_ctx = ui_state.get_ctx(delivery_key)
    product = ui_state.get_product(category_id, product_id)
    return cmp.compare_product_detail(_client, pickup_ctx, delivery_ctx, category_id, product)


def render(
    client: HardeesApiClient, pickup_ctx: ChannelContext | None, delivery_ctx: ChannelContext | None,
    active_ctx: ChannelContext | None, product: dict | None,
) -> None:
    """`product` (optional) is whatever's currently selected in the
    active channel's Products tab - used as the default for "Compare
    this product" mode, carrying its own `_category` (see
    menu_panel.render_products). "Compare this category" mode picks its
    own category independently via a dropdown below, since the
    Products/Offers tabs no longer share one single selected category
    (they show the full catalog - see menu_panel.py)."""
    st.subheader("Pickup vs Delivery comparison")

    if not pickup_ctx or not delivery_ctx:
        st.info("Select a city with at least one Pickup-capable AND one Delivery-capable store above to enable comparison.")
        return

    st.caption(
        f"Comparing **Pickup** (storeId={pickup_ctx.store_id}, {pickup_ctx.store_name}) vs "
        f"**Delivery** (storeId={delivery_ctx.store_id}, {delivery_ctx.store_name}). "
        "Each channel's data is fetched independently - see services/comparison_service.py."
    )

    # A plain radio, not st.tabs() - Streamlit's tabs widget does not
    # remember which tab was active across a rerun triggered by a widget
    # in a DIFFERENT tab (e.g. the "Run comparison" button below), so the
    # view would visibly snap back to the first tab right after showing a
    # result. A radio's selection IS preserved across reruns via its key,
    # so the result stays visible under the tab the user actually clicked.
    mode = st.radio(
        "Comparison scope", options=["Compare this category", "Compare this product"],
        horizontal=True, key="hardees_comparison_mode",
    )

    if mode == "Compare this category":
        categories = menu_panel.get_categories_for(client, active_ctx) if active_ctx else []
        if not categories:
            st.info("No categories available.")
            return
        labels = [c.get("name") for c in categories]
        idx = st.selectbox("Category to compare", options=range(len(categories)), format_func=lambda i: labels[i], key="hardees_comparison_category_idx")
        category_id = categories[idx].get("id")

        if st.button("🔍 Run category comparison", key="run_category_comparison"):
            try:
                result = _cached_category_comparison(client, pickup_ctx.cache_key, delivery_ctx.cache_key, category_id)
            except HardeesApiError as e:
                st.error(error_message(e))
            else:
                st.session_state["_hardees_last_category_cmp"] = result
        if "_hardees_last_category_cmp" in st.session_state:
            _render_category_result(st.session_state["_hardees_last_category_cmp"])
    else:
        if product is None:
            st.info("Select a product in the active channel's Products tab first.")
        else:
            category_id = product["_category"].get("id")
            if st.button("🔍 Run product comparison", key="run_product_comparison"):
                try:
                    fields = _cached_product_comparison(client, pickup_ctx.cache_key, delivery_ctx.cache_key, category_id, product.get("id"))
                except HardeesApiError as e:
                    st.error(error_message(e))
                else:
                    st.session_state["_hardees_last_product_cmp"] = (product.get("name"), fields)
            if "_hardees_last_product_cmp" in st.session_state:
                name, fields = st.session_state["_hardees_last_product_cmp"]
                _render_field_table(fields, title=f"'{name}' — Pickup vs Delivery")


def _render_category_result(result: cmp.CategoryComparisonResult) -> None:
    c1, c2 = st.columns(2)
    c1.metric("menuConfigId match", _VERDICT_ICON[result.menu_config_comparison.verdict])
    c2.metric("clusterId match", _VERDICT_ICON[result.cluster_comparison.verdict])

    if result.pickup_error:
        st.error(f"Pickup fetch error: {result.pickup_error}")
    if result.delivery_error:
        st.error(f"Delivery fetch error: {result.delivery_error}")

    counts = result.summary_counts
    st.markdown(
        f"**{len(result.products)} products compared** — "
        f"{counts[cmp.IDENTICAL]} identical, {counts[cmp.DIFFERENT]} different, "
        f"{counts[cmp.UNAVAILABLE_PICKUP] + counts[cmp.UNAVAILABLE_DELIVERY]} unavailable in one channel, "
        f"{counts[cmp.NOT_COMPARABLE]} not comparable."
    )

    rows = []
    for p in result.products:
        row = {"product_id": p.product_id, "name": p.name, "overall": _VERDICT_ICON[p.overall_verdict]}
        for f in p.fields:
            row[f.field] = f"{f.pickup_value!r} / {f.delivery_value!r}" if f.verdict != cmp.IDENTICAL else f"{f.pickup_value!r}"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_field_table(fields, title: str) -> None:
    st.markdown(f"**{title}**")
    rows = [{
        "field": f.field, "pickup": f.pickup_value, "delivery": f.delivery_value,
        "verdict": _VERDICT_ICON.get(f.verdict, f.verdict),
    } for f in fields]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    diffs = [f for f in fields if f.verdict == cmp.DIFFERENT]
    if diffs:
        st.warning(f"{len(diffs)} field(s) differ between Pickup and Delivery for this product.")
    else:
        st.success("No differences detected between Pickup and Delivery for this product.")
