#!/usr/bin/env python3
"""Run the KFC daily scheduler."""
from competitors.kfc.backend import config, database, run_service
from competitors.shared.scheduler import run_scheduler


def main() -> int:
    return run_scheduler(
        brand_name="KFC",
        config=config,
        database=database,
        run_service=run_service,
        fallback_time="06:00",
        enable_setting="ENABLE_SCHEDULER",
    )


if __name__ == "__main__":
    raise SystemExit(main())
