#!/usr/bin/env python3
"""Run the independent HungerStation daily scheduler."""
from __future__ import annotations

import sys

from competitors.hungerstation.scheduler import main


if __name__ == "__main__":
    sys.exit(main())
