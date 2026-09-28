#!/usr/bin/env python3
"""Run the shared HungerStation collector from the repository root."""
from __future__ import annotations

import sys

from competitors.hungerstation.collector import main


if __name__ == "__main__":
    sys.exit(main())
