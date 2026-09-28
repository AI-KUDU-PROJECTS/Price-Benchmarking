"""KUDU baseline view for the repository's legacy Streamlit entry point."""
from __future__ import annotations

import streamlit as st

from adapters.kudu import KuduAdapter


def render() -> None:
    st.set_page_config(page_title="KUDU menu baseline", layout="wide")
    adapter = KuduAdapter()
    brand = adapter.get_brand()
    st.title("KUDU menu baseline")
    st.caption("Production menu · template 1 · delivery and pickup")
    if brand.data_freshness == "unavailable":
        st.error("No KUDU catalog snapshot is available. Run python -m kudu.refresh.")
        return
    if brand.data_freshness == "stale":
        st.warning(f"Saved KUDU data is stale. Last collection: {brand.last_successful_run_at}.")
    else:
        st.caption(f"Last collection: {brand.last_successful_run_at}")

    channel = st.radio("Service", ("delivery", "pickup"), horizontal=True)
    search = st.text_input("Search item name or category")
    products = adapter.list_products(channel=channel, query=search)
    st.write(f"{len(products)} items")
    st.dataframe(
        [
            {
                "Image": product.image_url,
                "Name": product.name_en,
                "Arabic name": product.name_ar,
                "Category": product.category,
                "Price (SAR)": product.regular_price,
                "Published": product.is_published,
                "Calories": product.calories,
            }
            for product in products
        ],
        column_config={"Image": st.column_config.ImageColumn("Image")},
        hide_index=True,
        use_container_width=True,
    )
    st.caption("The production API supplies price numbers but no currency field; SAR is the project market setting. Unpublished items remain visible and marked.")
