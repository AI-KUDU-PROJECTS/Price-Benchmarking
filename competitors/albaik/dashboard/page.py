#!/usr/bin/env python3
"""
competitors/albaik/dashboard/page.py
---------------------------------------------------------------------
Placeholder Albaik dashboard page. Albaik has no collector, database, or
change-detection logic yet (see ../README.md) - this module only renders
a status placeholder so pages/6_Albaik.py has something real to import,
matching the same `render()` pattern KFC uses
(competitors/kfc/dashboard/page.py). It shows no product data (there is
none to show) and imports nothing from any other competitor.
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st

from shared_ui import empty_state, page_header


def render() -> None:
    st.set_page_config(page_title="Albaik Price Intelligence", layout="wide")
    page_header("Albaik Price Intelligence")
    empty_state(
        "Status: Collector not implemented yet.",
        "Folder structure is ready for future development.",
    )
