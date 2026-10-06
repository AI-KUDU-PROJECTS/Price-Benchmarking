#!/usr/bin/env python3
"""Run the Herfy daily scheduler."""
from competitors.herfy.backend import config, database, run_service
from competitors.shared.scheduler import run_scheduler


def main() -> int:
    return run_scheduler(
        brand_name="Herfy",
        config=config,
        database=database,
        run_service=run_service,
        fallback_time="06:45",
        enable_setting="HERFY_ENABLE_SCHEDULER",
    )


if __name__ == "__main__":
    raise SystemExit(main())
