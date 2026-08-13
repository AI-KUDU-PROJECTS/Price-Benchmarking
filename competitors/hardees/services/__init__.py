"""
competitors/hardees/services
---------------------------------------------------------------------
Business-logic layer between ../api/client.py (raw HTTP) and ../ui/*
(Streamlit rendering). Nothing in ../ui/ should call HardeesApiClient
directly - it should go through one of these service functions, so the
"which nested id to send", "which fields mean what", and "how to compare
two channels" rules (all documented in
../research/api-map/api-map.md and field-map.json) live in exactly one
place each.
---------------------------------------------------------------------
"""
