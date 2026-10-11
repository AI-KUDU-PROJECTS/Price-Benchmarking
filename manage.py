#!/usr/bin/env python3
"""Manage the local app, collectors, and schedulers from one entry point."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from collections.abc import Sequence


COLLECTOR_MODULES = {
    "kfc": "competitors.kfc.run_collector",
    "hardees": "competitors.hardees.run_collector",
    "burger-king": "competitors.burger_king.run_collector",
    "herfy": "competitors.herfy.run_collector",
    "hungerstation": "competitors.hungerstation.collector",
}

SCHEDULER_MODULES = {
    "kfc": "competitors.kfc.scheduler",
    "hardees": "competitors.hardees.scheduler",
    "burger-king": "competitors.burger_king.scheduler",
    "herfy": "competitors.herfy.scheduler",
    "hungerstation": "competitors.hungerstation.scheduler",
}


def _call_main(module_name: str, forwarded: Sequence[str] = ()) -> int:
    """Import an implementation only when selected and preserve its CLI."""
    module = importlib.import_module(module_name)
    previous_argv = sys.argv
    sys.argv = [module_name, *forwarded]
    try:
        result = module.main()
    finally:
        sys.argv = previous_argv
    return int(result or 0)


def _run_api(host: str, port: int, reload: bool) -> int:
    import uvicorn

    uvicorn.run("bff.app:app", host=host, port=port, reload=reload)
    return 0


def _run_all_collectors() -> int:
    from bff.pull_all import PullManager, TARGETS

    manager = PullManager(targets=TARGETS)
    _, started = manager.start()
    if not started:
        print("A collection batch is already running.", file=sys.stderr)
        return 2

    while True:
        result = manager.latest()
        if result and result["status"] != "running":
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "success" else 1
        time.sleep(0.2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the KUDU Price Benchmark app and data operations."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("dev", help="start the React app and FastAPI BFF")

    api = commands.add_parser("api", help="start only the FastAPI BFF")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument(
        "--no-reload",
        action="store_true",
        help="disable automatic reload (reload is enabled by default)",
    )

    collect = commands.add_parser(
        "collect",
        help="run a collector",
        description=(
            "Run one collector. Options after SOURCE are passed to that source; "
            "official sources accept --channel and --no-screenshots, while "
            "HungerStation accepts --brand, --all, --serial, --adb, --db, "
            "--batch-id, and --from-capture."
        ),
    )
    collect.add_argument("source", choices=["all", *COLLECTOR_MODULES])
    collect.add_argument("options", nargs=argparse.REMAINDER, metavar="OPTION")

    schedule = commands.add_parser("schedule", help="run a daily scheduler")
    schedule.add_argument("source", choices=sorted(SCHEDULER_MODULES))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "dev":
        return _call_main("bff.dev")
    if args.command == "api":
        return _run_api(args.host, args.port, not args.no_reload)
    if args.command == "schedule":
        return _call_main(SCHEDULER_MODULES[args.source])
    if args.command == "collect" and args.source == "all":
        if args.options:
            parser.error("collect all does not accept source-specific options")
        return _run_all_collectors()
    if args.command == "collect":
        forwarded = list(args.options)
        if args.source == "hungerstation" and not ({"--all", "--brand"} & set(forwarded)):
            forwarded.insert(0, "--all")
        return _call_main(COLLECTOR_MODULES[args.source], forwarded)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
