"""
competitors/hardees/ui/state.py
---------------------------------------------------------------------
Tiny shared session_state registries so `@st.cache_data`-wrapped
functions (which can only take hashable arguments - see each panel
module's own docstring) can look up the actual ChannelContext/product
dict behind a plain cache key. Centralized here so every panel reads and
writes the SAME two dicts - a bug in an earlier pass of this page had
comparison_panel.py fail with a KeyError because only the "active"
channel's ChannelContext ever got registered (by menu_panel.py, as a
side effect of rendering); branch_panel.py now registers BOTH Pickup and
Delivery contexts here as soon as they are resolved, regardless of which
one is currently "active" in the UI, so the comparison panel (which
always needs both) never misses one.
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st

from competitors.hardees.services.branch_service import ChannelContext

_CTX_KEY = "_hardees_ctx_lookup"
_PRODUCT_KEY = "_hardees_product_lookup"


def register_ctx(ctx: ChannelContext) -> None:
    st.session_state.setdefault(_CTX_KEY, {})[ctx.cache_key] = ctx


def get_ctx(cache_key: tuple) -> ChannelContext:
    return st.session_state.setdefault(_CTX_KEY, {})[cache_key]


def register_product(category_id: int, product_id, product: dict) -> None:
    """Keyed by (category_id, product_id) ONLY - deliberately NOT by
    channel/cache_key. The raw product dict comes from
    getProductsByCategory, which api-map.md confirms takes no
    channel/service field at all - the same product dict is valid to look
    up regardless of which channel's menu panel the user happened to
    select it from, so a product picked while Pickup was "active" is
    still found when the comparison panel needs it for a Delivery
    lookup too."""
    st.session_state.setdefault(_PRODUCT_KEY, {})[(category_id, product_id)] = product


def get_product(category_id: int, product_id) -> dict:
    return st.session_state.setdefault(_PRODUCT_KEY, {})[(category_id, product_id)]
