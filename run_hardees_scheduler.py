#!/usr/bin/env python3
"""
run_hardees_scheduler.py
---------------------------------------------------------------------
Root-level convenience wrapper so `python run_hardees_scheduler.py`
works from the repository root (see root README.md "Multi-competitor
architecture"). All actual logic lives in competitors/hardees/
scheduler.py - this file only imports and executes it. Do not add
Hardee's business logic here.

Usage:
    python run_hardees_scheduler.py
---------------------------------------------------------------------
"""
from __future__ import annotations

import sys

from competitors.hardees.scheduler import main

if __name__ == "__main__":
    sys.exit(main())
