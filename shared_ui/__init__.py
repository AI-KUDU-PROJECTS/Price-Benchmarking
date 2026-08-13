"""
shared_ui
---------------------------------------------------------------------
Generic, competitor-agnostic Streamlit UI helpers shared by the root
`app.py` and, optionally, individual competitor dashboards. See root
README.md "Multi-competitor architecture".

Rules for this package (enforced by convention, not by code):
  - No product normalization, API clients, pricing calculations, change
    detection, or database queries - that is all competitor-specific
    business logic and belongs under competitors/<name>/.
  - No competitor name, endpoint, or config value hardcoded into any
    function body. Every function here takes its data (titles, labels,
    statuses, page paths) as plain arguments from the caller.
  - Only visual/structural helpers: page headers, status badges, empty
    states, navigation rendering, spacing/layout, and shared display
    column/tab order for price dashboards (price_columns.py).
---------------------------------------------------------------------
"""
from __future__ import annotations

from shared_ui.components import empty_state, status_badge
from shared_ui.layout import page_header, spacer
from shared_ui.navigation import render_nav_list
from shared_ui.price_columns import (
    CHANNEL_COMPARE_COLUMNS,
    DASHBOARD_TAB_NAMES,
    OFFER_PRICE_COLUMNS,
    PRODUCT_PRICE_COLUMNS,
    format_sizes,
    order_columns,
)

__all__ = [
    "empty_state",
    "status_badge",
    "page_header",
    "spacer",
    "render_nav_list",
    "CHANNEL_COMPARE_COLUMNS",
    "DASHBOARD_TAB_NAMES",
    "OFFER_PRICE_COLUMNS",
    "PRODUCT_PRICE_COLUMNS",
    "format_sizes",
    "order_columns",
]
