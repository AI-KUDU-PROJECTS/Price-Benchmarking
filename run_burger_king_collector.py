#!/usr/bin/env python3
"""
run_burger_king_collector.py
---------------------------------------------------------------------
Root-level convenience wrapper so `python run_burger_king_collector.py`
works from the repository root (see root README.md "Multi-competitor
architecture"). All actual logic lives in
competitors/burger_king/run_collector.py - this file only imports and
executes it. Do not add Burger King business logic here.

Usage:
    python run_burger_king_collector.py
    python run_burger_king_collector.py --channel=PICKUP
    python run_burger_king_collector.py --channel=DELIVERY
    python run_burger_king_collector.py --no-screenshots
---------------------------------------------------------------------
"""
from __future__ import annotations

import sys

from competitors.burger_king.run_collector import main

if __name__ == "__main__":
    sys.exit(main())
