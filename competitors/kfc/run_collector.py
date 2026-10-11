#!/usr/bin/env python3
"""Run one KFC collection."""
from competitors.kfc.backend import config, database, run_service
from competitors.shared.runner import run_collection_cli


def main() -> int:
    return run_collection_cli(
        brand_name="KFC",
        config=config,
        database=database,
        run_service=run_service,
    )


if __name__ == "__main__":
    raise SystemExit(main())
