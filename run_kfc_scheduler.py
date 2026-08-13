#!/usr/bin/env python3
"""
run_kfc_scheduler.py
---------------------------------------------------------------------
Root-level convenience wrapper so `python run_kfc_scheduler.py` keeps
working from the repository root after KFC was moved into
competitors/kfc/ (see root README.md "Multi-competitor architecture").
All actual logic lives in competitors/kfc/scheduler.py - this file only
imports and executes it. Do not add KFC business logic here.

Usage (identical to before the move):
    python run_kfc_scheduler.py
---------------------------------------------------------------------
"""
from __future__ import annotations

import sys

from competitors.kfc.scheduler import main

if __name__ == "__main__":
    sys.exit(main())
