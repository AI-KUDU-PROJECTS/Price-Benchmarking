#!/usr/bin/env python3
"""
pages/2_Hardees.py
---------------------------------------------------------------------
Hardee's Streamlit page. Calls competitors.hardees.dashboard.page.render()
— the real, SQLite-backed dashboard (see competitors/hardees/README.md).
Does not import KFC or any other competitor's code.
---------------------------------------------------------------------
"""
from competitors.hardees.dashboard.page import render

render()
