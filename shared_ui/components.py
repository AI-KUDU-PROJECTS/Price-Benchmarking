"""
shared_ui/components.py
---------------------------------------------------------------------
Small, generic, reusable visual components: a status badge and an
empty-state placeholder. Both are pure presentation - they take whatever
text/status the caller passes in and render it; neither one knows what a
"competitor" is. See shared_ui/__init__.py for the rules this module
follows.
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st

# Generic status vocabulary -> (emoji, color). Callers pass one of these
# keys (or any other string, which falls back to the "unknown" style) -
# nothing competitor-specific is encoded here.
_STATUS_STYLES: dict[str, tuple[str, str]] = {
    "implemented": ("🟢", "green"),
    "active": ("🟢", "green"),
    "success": ("🟢", "green"),
    "scaffold": ("⚪", "gray"),
    "not_implemented": ("⚪", "gray"),
    "pending": ("🟡", "orange"),
    "partial": ("🟡", "orange"),
    "error": ("🔴", "red"),
    "failed": ("🔴", "red"),
}


def status_badge(status: str, label: str | None = None) -> str:
    """Returns a small Markdown-formatted status badge string, e.g.
    ':green[🟢 Implemented]'. Callers render it with st.markdown(...) so it
    can be composed inline with other text. `label` overrides the display
    text; otherwise the raw `status` string is title-cased."""
    key = (status or "").strip().lower()
    emoji, color = _STATUS_STYLES.get(key, ("⚫", "gray"))
    text = label if label is not None else status.replace("_", " ").title()
    return f":{color}[{emoji} {text}]"


def empty_state(title: str, message: str = "", icon: str = "🧩") -> None:
    """A centered, generic placeholder box for a page/section that has no
    data or implementation yet. Purely visual - callers decide the actual
    wording."""
    st.info(f"{icon} **{title}**" + (f"\n\n{message}" if message else ""))
