#!/usr/bin/env python3
"""
run_kfc_collector.py
---------------------------------------------------------------------
Root-level convenience wrapper so `python run_kfc_collector.py` keeps
working from the repository root after KFC was moved into
competitors/kfc/ (see root README.md "Multi-competitor architecture").
All actual logic lives in competitors/kfc/run_collector.py - this file
only imports and executes it. Do not add KFC business logic here.

Usage (identical to before the move):
    python run_kfc_collector.py
    python run_kfc_collector.py --channel=PICKUP
    python run_kfc_collector.py --channel=DELIVERY
    python run_kfc_collector.py --no-screenshots
---------------------------------------------------------------------
"""
from __future__ import annotations

import sys

from competitors.kfc.run_collector import main

if __name__ == "__main__":
    sys.exit(main())
