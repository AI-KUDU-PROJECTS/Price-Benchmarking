"""
shared_ui/navigation.py
---------------------------------------------------------------------
A generic navigation-list renderer for the root app.py landing page. Takes
a plain list of {"label", "page", "status"} dicts from the caller - it
does not know or hardcode any competitor's name, page path, or status.
See shared_ui/__init__.py for the rules this module follows.
---------------------------------------------------------------------
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from shared_ui.components import status_badge


def render_nav_list(items: list[dict[str, Any]]) -> None:
    """Renders one row per item: a Streamlit page link plus a status badge.

    Each item must have:
      - "label":  display name, e.g. "KFC"
      - "page":   path to the page script, e.g. "pages/1_KFC.py"
      - "status": any status string (e.g. "implemented", "scaffold")

    An optional "note" string is shown as a caption under the row.
    """
    for item in items:
        col_link, col_status = st.columns([3, 2])
        with col_link:
            st.page_link(item["page"], label=item["label"])
        with col_status:
            st.markdown(status_badge(item["status"]))
        if item.get("note"):
            st.caption(item["note"])
