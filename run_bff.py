#!/usr/bin/env python3
"""Run the marketing BFF (does not start Streamlit or collectors)."""
from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("bff.app:app", host="127.0.0.1", port=8000, reload=True)
