"""
competitors/hardees/ui/product_panel.py
---------------------------------------------------------------------
"Product details preview" section - calls POST /api/product (and,
separately, POST /api/product-bundle-step) for exactly ONE product, and
ONLY when the user explicitly clicks "Load product details" below - see
the task's "Only call product details when I explicitly select or
request them" / "Avoid calling /api/product for every product
automatically". Selecting a different product in ../menu_panel.py's
dropdown does NOT by itself trigger this call.
---------------------------------------------------------------------
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import menu_service
from competitors.hardees.services.branch_service import ChannelContext
from competitors.hardees.services.sanitize import error_message, sanitize
from competitors.hardees.ui import state as ui_state


@st.cache_data(show_spinner="Loading product detail (POST /api/product)...")
def _cached_detail(_client: HardeesApiClient, cache_key: tuple, category_id: int, product_id):
    ctx = ui_state.get_ctx(cache_key)
    product = ui_state.get_product(category_id, product_id)
    return menu_service.get_product_detail(_client, ctx, category_id, product)


@st.cache_data(show_spinner="Loading bundle steps (POST /api/product-bundle-step)...")
def _cached_bundle_steps(_client: HardeesApiClient, cache_key: tuple, category_id: int, product_id):
    ctx = ui_state.get_ctx(cache_key)
    product = ui_state.get_product(category_id, product_id)
    return menu_service.get_bundle_steps(_client, ctx, category_id, product)


def render(client: HardeesApiClient, ctx: ChannelContext, category_id: int, product: dict) -> None:
    st.subheader("Product details preview")
    product_id = product.get("id")
    st.markdown(f"Selected: **{product.get('name')}** (id={product_id}, categoryId={category_id}, service={ctx.service})")

    ui_state.register_product(category_id, product_id, product)

    col1, col2 = st.columns(2)
    load_detail = col1.button("📄 Load product details (/api/product)", key=f"load_detail_{ctx.service}_{product_id}")
    load_bundle_step = col2.button("🧩 Also call /api/product-bundle-step", key=f"load_bundlestep_{ctx.service}_{product_id}")

    if not load_detail and not load_bundle_step:
        st.caption("Nothing fetched yet - click a button above to call the live API for this one product.")
        return

    if load_detail:
        try:
            detail = _cached_detail(client, ctx.cache_key, category_id, product_id)
        except HardeesApiError as e:
            st.error(f"/api/product failed: {error_message(e)}")
        else:
            _render_detail(detail, product)

    if load_bundle_step:
        try:
            steps = _cached_bundle_steps(client, ctx.cache_key, category_id, product_id)
        except HardeesApiError as e:
            st.error(f"/api/product-bundle-step failed: {error_message(e)}")
        else:
            _render_bundle_step_comparison(steps)


def _render_detail(detail, original_product: dict) -> None:
    if detail.empty:
        st.warning(
            f"/api/product returned HTTP 200 with an EMPTY data:{{}} for id={detail.requested_id}. "
            "This is the documented failure mode for sending a bundle_group wrapper's own "
            "top-level id instead of its selectedItem - see api-map.md 'Product detail endpoint'."
        )
        return

    raw = detail.raw
    if detail.is_wrapper:
        st.info(
            f"'{original_product.get('name')}' is a bundle_group wrapper (id={detail.wrapper_id}) - "
            f"resolved to its selectedItem nested id={detail.requested_id} automatically "
            "(services/menu_service.py's resolve_detail_lookup_id())."
        )

    # Same field vocabulary as KFC product_snapshots so the detail view
    # is easy to scan against the Products table above.
    summary = menu_service.summarize_product(
        {**original_product, **{k: v for k, v in raw.items() if v not in (None, "", [], {})}},
        original_product.get("_category"),
        channel=detail.service,
    )
    # Prefer detail-endpoint description when present (category listing
    # sometimes omits it on wrappers).
    detail_desc = raw.get("description") or raw.get("longDesc") or raw.get("shortDesc")
    if detail_desc:
        summary["description_en"] = detail_desc
    if raw.get("currency"):
        summary["currency"] = raw.get("currency")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("regular_price", summary.get("regular_price"))
    m2.metric("special_price", summary.get("special_price") if summary.get("special_price") is not None else "—")
    m3.metric("effective_price", summary.get("effective_price"))
    m4.metric("promo_id", summary.get("promo_id") or "—")

    st.markdown("**description_en**")
    st.write(summary.get("description_en") or "—")

    with st.expander("Normalized fields (KFC column names)"):
        st.json({k: summary.get(k) for k in menu_service.PRODUCT_DISPLAY_COLUMNS})

    rows = menu_service.summarize_modifiers(raw)
    if rows:
        st.markdown("**Variants / modifier options (readable view):**")
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("No variants or step options in this response.")

    with st.expander("Raw JSON (sanitized)"):
        st.json(sanitize(raw))


def _render_bundle_step_comparison(steps: list[dict]) -> None:
    st.markdown("**`/api/product-bundle-step` response:**")
    if not steps:
        st.caption("Empty response.")
        return
    summary = [{"step": s.get("title"), "type": s.get("type"), "option_count": len(s.get("options") or [])} for s in steps]
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)
    st.caption(
        "Per api-map.md: this endpoint returns the SAME steps[] content as /api/product's "
        "own `steps` field, as a bare array - compare the step titles/option counts above "
        "against the 'Load product details' table to see this for yourself."
    )
    with st.expander("Raw JSON (sanitized)"):
        st.json(sanitize(steps))
