"""
competitors/hardees/api
---------------------------------------------------------------------
Direct-HTTPS client for Hardee's Saudi's public guest-session API family
(saudi.hardees.me). See client.py's own docstring for why a real browser
is not required, and ../research/api-map/api-map.md "Direct API
feasibility" for the live evidence this is built from.

This package is intentionally Python (unlike competitors/kfc/collector/,
which is Node.js) because its only consumer is this competitor's own
Streamlit live-preview page (../dashboard/page.py) - a Python process
that needs to make on-demand HTTP calls in response to widget
interactions, not a scheduled batch collector. See ../README.md
"Streamlit live API preview" for how this fits into the overall
Hardee's architecture.
---------------------------------------------------------------------
"""
from __future__ import annotations

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError

__all__ = ["HardeesApiClient", "HardeesApiError"]
