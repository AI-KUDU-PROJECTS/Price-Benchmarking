"""
competitors/hardees/ui/batch_panel.py
---------------------------------------------------------------------
"Per-product request volume" batch-preview tool (task Phase 3). Lets the
user fetch /api/product for a SMALL, EXPLICITLY CHOSEN set of products
from the currently-loaded category, with a visible delay between calls,
a progress bar, and a success/failure count - never an automatic bulk
crawl. See ../research/api-map/unresolved-items.md item #12 for the
full request-volume/rate-pacing research this tool's defaults come from:
110 unique products across the 12 categories sampled, zero duplicates
across categories, 53 of them bundle_group wrappers each needing one
call PER size/flavor variant for full coverage (137 variant calls total),
and Pickup/Delivery detail responses confirmed byte-for-byte identical
(see comparison_service.py) - so this tool, like the rest of the page,
only ever calls the ACTIVE channel once per product, never both.
---------------------------------------------------------------------
"""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import menu_service
from competitors.hardees.services.branch_service import ChannelContext
from competitors.hardees.services.sanitize import error_message

DEFAULT_BATCH_SIZE = 5
MAX_BATCH_SIZE = 20  # hard UI safety limit - see unresolved-items.md item #12
DEFAULT_DELAY_SECONDS = 0.6


def render(client: HardeesApiClient, ctx: ChannelContext | None, products: list[dict]) -> None:
    """`products` is the FULL catalog (every category) for `ctx`, as
    returned by menu_panel.render_products() - each product dict carries
    its own `_category` key, so this tool resolves each product's
    categoryId individually rather than assuming one shared category."""
    st.subheader("Batch product-detail preview")

    if not ctx or not products:
        st.info("Select a branch above first.")
        return

    st.caption(
        f"{len(products)} products across the full catalog. This tool calls "
        f"POST /api/product sequentially for a small, explicitly chosen subset - it never "
        f"runs automatically and never covers the whole catalog by default. See "
        "research/api-map/unresolved-items.md item #12 for the full request-volume analysis "
        "this tool's defaults are based on."
    )

    max_available = min(len(products), MAX_BATCH_SIZE)
    col1, col2 = st.columns(2)
    with col1:
        batch_size = st.slider(
            "Number of products to fetch", min_value=1, max_value=max_available,
            value=min(DEFAULT_BATCH_SIZE, max_available), key="hardees_batch_size",
        )
    with col2:
        delay = st.slider(
            "Delay between calls (seconds)", min_value=0.0, max_value=3.0,
            value=DEFAULT_DELAY_SECONDS, step=0.1, key="hardees_batch_delay",
            help="No rate limit was ever observed live during this project's research, but a "
                 "small delay is kept as a considerate default - see unresolved-items.md item #12.",
        )

    if max_available < len(products):
        st.caption(f"⚠️ Category has {len(products)} products - capped to the first {MAX_BATCH_SIZE} for this tool's hard safety limit.")

    subset = products[:max_available][:batch_size]
    st.caption("Will fetch: " + ", ".join(f"{p.get('id')} ({p.get('name')}, {p['_category'].get('name')})" for p in subset))

    run = st.button(f"▶️ Run batch fetch ({batch_size} product{'s' if batch_size != 1 else ''})", key="hardees_run_batch")
    if not run:
        st.caption("Nothing fetched yet - click the button above to start. No calls happen just from moving the sliders.")
        return

    progress = st.progress(0.0, text="Starting...")
    results = []
    success_count = 0
    failure_count = 0
    start = time.monotonic()

    for i, product in enumerate(subset):
        progress.progress(i / len(subset), text=f"Fetching {i + 1}/{len(subset)}: {product.get('name')}...")
        row = {"id": product.get("id"), "name": product.get("name"), "category": product["_category"].get("name")}
        try:
            detail = menu_service.get_product_detail(client, ctx, product["_category"].get("id"), product)
            if detail.empty:
                row["result"] = "empty data:{} (see api-map.md 'Product detail endpoint')"
                failure_count += 1
            else:
                mods = menu_service.summarize_modifiers(detail.raw)
                row["result"] = f"OK - {len(mods)} modifier/variant options"
                success_count += 1
        except HardeesApiError as e:
            row["result"] = f"ERROR: {error_message(e)}"
            failure_count += 1
        results.append(row)
        if i < len(subset) - 1 and delay > 0:
            time.sleep(delay)

    progress.progress(1.0, text="Done.")
    elapsed = time.monotonic() - start

    c1, c2, c3 = st.columns(3)
    c1.metric("Succeeded", success_count)
    c2.metric("Failed / empty", failure_count)
    c3.metric("Elapsed", f"{elapsed:.1f}s")

    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
    st.caption(
        f"{len(subset)} sequential calls, {delay:.1f}s delay between each. "
        f"This client has made {client.request_count} live network calls in total this browser tab's session."
    )
