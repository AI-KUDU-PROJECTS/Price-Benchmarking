#!/usr/bin/env python3
"""Run the Hardee's daily scheduler."""
from competitors.hardees.backend import config, database, run_service
from competitors.shared.scheduler import run_scheduler


def main() -> int:
    return run_scheduler(
        brand_name="Hardee's",
        config=config,
        database=database,
        run_service=run_service,
        fallback_time="07:00",
        enable_setting="HRD_ENABLE_SCHEDULER",
    )


if __name__ == "__main__":
    raise SystemExit(main())
