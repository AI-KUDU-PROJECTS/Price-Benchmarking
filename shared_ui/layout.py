"""
shared_ui/layout.py
---------------------------------------------------------------------
Generic page-layout helpers: a page header and simple vertical spacing.
No competitor names, business logic, or data queries - see
shared_ui/__init__.py for the rules this module follows.
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st


def page_header(title: str, subtitle: str | None = None, caption: str | None = None) -> None:
    """Renders a simple, consistent page title block. `subtitle` is shown as
    regular text under the title; `caption` (smaller/muted) under that."""
    st.title(title)
    if subtitle:
        st.write(subtitle)
    if caption:
        st.caption(caption)


def spacer(lines: int = 1) -> None:
    """Adds `lines` blank lines of vertical spacing - a plain, generic
    alternative to sprinkling raw st.write('') calls everywhere."""
    for _ in range(max(0, lines)):
        st.write("")
