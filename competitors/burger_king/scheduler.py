#!/usr/bin/env python3
"""Run the Burger King daily scheduler."""
from competitors.burger_king.backend import config, database, run_service
from competitors.shared.scheduler import run_scheduler


def main() -> int:
    return run_scheduler(
        brand_name="Burger King",
        config=config,
        database=database,
        run_service=run_service,
        fallback_time="06:30",
        enable_setting="BK_ENABLE_SCHEDULER",
    )


if __name__ == "__main__":
    raise SystemExit(main())
