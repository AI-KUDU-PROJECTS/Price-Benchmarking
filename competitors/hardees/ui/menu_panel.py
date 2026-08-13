"""
competitors/hardees/ui/menu_panel.py
---------------------------------------------------------------------
"Menu preview" - categories (getMenu) and products across EVERY
category (getProductsByCategory, once per category). Tables use the
SAME normalized column vocabulary as KFC's own
`product_snapshots`/`offer_snapshots` tables
(competitors/kfc/backend/database.py) - product_id, sku,
product_name_en, category_id/category_name_en, regular_price,
special_price, effective_price, discount_percentage, promo_id,
limited_offer, product_type, bundle_type_id, availability, image_url
for products; promo_id, offer_name, original_price, offer_price,
discount_percentage, offer_type, bundle_type, image_url for offers - see
services/menu_service.py's summarize_product()/summarize_offer().

IMPORTANT: this shows the FULL catalog (every category) in one table,
not one category at a time - mirroring KFC's own `products_df(channel)`/
`offers_df(channel)`, which return every product/offer for that channel
from its database with no per-category selection required. "Category
contains" is a plain TEXT FILTER on the resulting table (exactly like
KFC's sidebar filter on `category_name_en`), not a gate that limits what
gets fetched.

This is still safe/low-volume: fetching every category is 12
`getProductsByCategory` calls (cached per category - see
`get_products_cached`, called once per session, not on every rerun),
NOT 12-194 per-PRODUCT `/api/product` detail calls - the task's "avoid
calling /api/product automatically" restriction is about that endpoint
specifically (see ../research/api-map/unresolved-items.md item #12) and
does not apply to the cheap, already-used-throughout-the-research-phase
category-listing endpoint.
---------------------------------------------------------------------
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import menu_service
from competitors.hardees.services.branch_service import ChannelContext
from competitors.hardees.services.sanitize import error_message
from competitors.hardees.ui import state as ui_state

# Identical column names/order as KFC's product_snapshots / offer_snapshots
# display (see menu_service.PRODUCT_DISPLAY_COLUMNS / OFFER_DISPLAY_COLUMNS).
PRODUCT_DISPLAY_COLS = list(menu_service.PRODUCT_DISPLAY_COLUMNS)
OFFER_DISPLAY_COLS = list(menu_service.OFFER_DISPLAY_COLUMNS)


@st.cache_data(show_spinner="Loading categories (getMenu)...")
def get_categories_cached(_client: HardeesApiClient, cache_key: tuple) -> list[dict]:
    return menu_service.get_categories(_client, ui_state.get_ctx(cache_key))


@st.cache_data(show_spinner="Loading products (getProductsByCategory)...")
def get_products_cached(_client: HardeesApiClient, cache_key: tuple, category_id: int) -> list[dict]:
    return menu_service.get_products(_client, ui_state.get_ctx(cache_key), category_id)


@st.cache_data(show_spinner="Loading the full catalog (getProductsByCategory x every category)...")
def get_full_catalog_cached(_client: HardeesApiClient, cache_key: tuple) -> list[dict]:
    """Every product across EVERY category for this channel - one
    `getProductsByCategory` call per category (reuses the same
    per-category cache entries `get_products_cached` uses, so drilling
    into one category elsewhere never re-fetches it). Each returned raw
    product dict carries its own `_category` key so callers can group/
    filter/display by category without a second lookup. A category that
    itself fails to load is skipped (logged via st.warning) rather than
    aborting the whole catalog - one bad category should never hide
    every other one."""
    categories = get_categories_cached(_client, cache_key)
    all_products: list[dict] = []
    failed = []
    for category in categories:
        try:
            products = get_products_cached(_client, cache_key, category.get("id"))
        except HardeesApiError:
            failed.append(category.get("name"))
            continue
        for p in products:
            p = dict(p)
            p["_category"] = category
            all_products.append(p)
    if failed:
        st.warning(f"Could not load: {', '.join(failed)} - showing every other category.")
    return all_products


def get_categories_for(client: HardeesApiClient, ctx: ChannelContext, *, sidebar: bool = False) -> list[dict]:
    """Registers `ctx` and returns its category list, showing any error
    in the sidebar or main body depending on `sidebar` - used wherever a
    plain category list is needed (the Comparison tab's own category
    picker, and dashboard/page.py's summary-card category count), unlike
    the Products/Offers tabs below which always show every category's
    products at once."""
    ui_state.register_ctx(ctx)
    target = st.sidebar if sidebar else st
    try:
        return get_categories_cached(client, ctx.cache_key)
    except HardeesApiError as e:
        target.error(f"getMenu failed: {error_message(e)}")
        return []


def render_products(
    client: HardeesApiClient, ctx: ChannelContext, filters: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Renders the FULL-catalog product table (every category) + a
    product-to-inspect selector for `ctx`, inside the caller's current
    tab (mirrors KFC's "Pickup/Delivery Products" tabs, which also show
    every category in one table). `filters` = {"category_contains": str,
    "product_name_contains": str, "offers_only": bool} - same semantics
    as KFC's sidebar filters. Returns (every raw product across every
    category, selected_product)."""
    filters = filters or {}
    ui_state.register_ctx(ctx)

    try:
        products = get_full_catalog_cached(client, ctx.cache_key)
    except HardeesApiError as e:
        st.error(f"getProductsByCategory failed: {error_message(e)}")
        return [], None

    if not products:
        st.info("No products returned for this branch.")
        return [], None

    df = pd.DataFrame([
        menu_service.summarize_product(p, p.get("_category"), channel=ctx.service)
        for p in products
    ])

    mask = pd.Series(True, index=df.index)
    category_contains = (filters.get("category_contains") or "").strip().lower()
    if category_contains:
        mask &= df["category_name_en"].fillna("").str.lower().str.contains(category_contains, na=False)
    name_or_desc = (filters.get("name_or_desc_contains") or filters.get("product_name_contains") or "").strip().lower()
    if name_or_desc:
        name_hit = df["product_name_en"].fillna("").str.lower().str.contains(name_or_desc, na=False)
        desc_hit = df["description_en"].fillna("").str.lower().str.contains(name_or_desc, na=False) if "description_en" in df.columns else False
        mask &= name_hit | desc_hit
    if filters.get("offers_only"):
        mask &= df["promo_id"].notna()
    filtered_df = df[mask]

    display_cols = [c for c in PRODUCT_DISPLAY_COLS if c in filtered_df.columns]
    st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)
    categories_shown = filtered_df["category_id"].nunique()
    st.caption(
        f"{len(filtered_df)}/{len(products)} products shown across {categories_shown} "
        f"categor{'y' if categories_shown == 1 else 'ies'}"
        + (" after sidebar filters" if any(filters.values()) else " (every category)") + ". "
        "Same column order as KFC: category → name → normalized → prices → currency → description → included → size → type → image → channel."
    )

    if filtered_df.empty:
        return products, None

    # A (category_id, product_id) pair, not product_id alone, identifies a row here -
    # the research phase found zero products shared across categories in practice,
    # but nothing here assumes that can never change.
    visible_pairs = set(zip(filtered_df["category_id"], filtered_df["product_id"]))
    selectable = [p for p in products if (p["_category"].get("id"), p.get("id")) in visible_pairs]
    labels = [f"{p.get('id')} — {p.get('name')}  [{p['_category'].get('name')}]" for p in selectable]
    idx = st.selectbox(
        "Select a product to inspect (Product details preview below)",
        options=range(len(selectable)), format_func=lambda i: labels[i],
        key=f"hardees_product_idx_{ctx.service}",
    )
    return products, selectable[idx]


def render_offers(client: HardeesApiClient, ctx: ChannelContext, filters: dict | None = None) -> None:
    """Renders the FULL-catalog offers table (every category, every
    product with `promoId != -1`) + "View full offer details" selectbox
    - mirrors KFC's "Pickup/Delivery Offers" tabs exactly (dataframe,
    then a selectbox to drill into one offer's full JSON + image).
    `filters` = {"category_contains": str} - same "Category contains"
    sidebar filter the Products tab uses."""
    filters = filters or {}
    ui_state.register_ctx(ctx)

    try:
        products = get_full_catalog_cached(client, ctx.cache_key)
    except HardeesApiError as e:
        st.error(f"getProductsByCategory failed: {error_message(e)}")
        return

    offers = [p for p in products if menu_service.has_active_offer(p)]
    category_contains = (filters.get("category_contains") or "").strip().lower()
    if category_contains:
        offers = [p for p in offers if category_contains in (p["_category"].get("name") or "").lower()]
    name_or_desc = (filters.get("name_or_desc_contains") or filters.get("product_name_contains") or "").strip().lower()
    if name_or_desc:
        filtered = []
        for p in offers:
            name = (p.get("name") or "").lower()
            desc = (p.get("description") or p.get("longDesc") or p.get("shortDesc") or "").lower()
            if name_or_desc in name or name_or_desc in desc:
                filtered.append(p)
        offers = filtered

    if not offers:
        st.info(f"No active offers for {ctx.service}" + (f' matching "{filters.get("category_contains")}"' if category_contains else "") + ".")
        return

    df = pd.DataFrame([
        menu_service.summarize_offer(p, p.get("_category"), channel=ctx.service)
        for p in offers
    ])
    display_cols = [c for c in OFFER_DISPLAY_COLS if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
    st.caption(
        f"{len(offers)}/{len(products)} products have an active offer. "
        "Same column order as KFC: category → name → normalized → prices → currency → description → included → size → type → image → channel."
    )

    labels = ["(select an offer)"] + df["offer_name"].fillna("(unnamed)").tolist()
    choice = st.selectbox("View full offer details", options=labels, key=f"hardees_offer_detail_{ctx.service}")
    if choice != "(select an offer)":
        row = df[df["offer_name"] == choice].iloc[0]
        st.json(row.to_dict())
        image = row.get("image_url")
        if image:
            st.image(str(image), caption=choice, width=200)
