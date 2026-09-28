#!/usr/bin/env python3
"""
app.py
---------------------------------------------------------------------
Root Streamlit entry point for the multi-competitor Price Intelligence
app. Run with:

    streamlit run app.py

This file is intentionally thin: a title, basic navigation information,
and links to each competitor's own page under pages/. It owns the list of
competitors (name/page/status) as plain data - shared_ui/ itself never
hardcodes a competitor name (see shared_ui/__init__.py). It renders no
product data, prices, or change events itself; every competitor's actual
dashboard lives in its own competitors/<name>/dashboard/page.py, reached
only through its own page in pages/ - see README.md "Multi-competitor
architecture".
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st

from shared_ui import page_header, render_nav_list, spacer

st.set_page_config(page_title="KUDU Price Intelligence", layout="wide")

# The only place in the repo where the full competitor list is assembled.
# Each competitor's own page (pages/<n>_<Name>.py) is the only thing that
# ever imports that competitor's dashboard code - this list only points at
# page paths and a status string, nothing business-specific.
COMPETITORS = [
    {"label": "KFC", "page": "pages/1_KFC.py", "status": "implemented",
     "note": "Collector, database, change detection, dashboard, and Excel exports are live."},
    {"label": "Hardee's", "page": "pages/2_Hardees.py", "status": "scaffold",
     "note": "Folder structure ready; no collector implemented yet."},
    {"label": "McDonald's", "page": "pages/3_McDonalds.py", "status": "scaffold",
     "note": "Folder structure ready; no collector implemented yet."},
    {"label": "Burger King", "page": "pages/4_Burger_King.py", "status": "scaffold",
     "note": "Folder structure ready; no collector implemented yet."},
    {"label": "Herfy", "page": "pages/5_Herfy.py", "status": "scaffold",
     "note": "Folder structure ready; no collector implemented yet."},
    {"label": "Albaik", "page": "pages/6_Albaik.py", "status": "scaffold",
     "note": "Folder structure ready; no collector implemented yet."},
]

page_header(
    "KUDU Price Intelligence",
    subtitle="KUDU production menu is the baseline for competitor price monitoring.",
    caption="Each competitor below has its own page, its own database, and its own data directory. "
            "None of them import from each other - see README.md.",
)

spacer(1)
st.subheader("KUDU baseline")
st.page_link("pages/0_Kudu.py", label="Open KUDU menu and prices")
st.caption("Production template 1 · delivery and pickup · item names, prices, and images")

spacer(1)
st.subheader("Competitors")
render_nav_list(COMPETITORS)

spacer(1)
st.divider()
st.markdown(
    "Open the KUDU baseline first, then compare it with the competitor pages. "
    "See "
    "`competitors/kfc/README.md` for its full architecture, and the root "
    "`README.md` for how new competitors get added to this repo."
)
