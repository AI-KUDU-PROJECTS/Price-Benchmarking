#!/usr/bin/env python3
"""
competitors/hardees/scheduler.py
---------------------------------------------------------------------
Independent local daily scheduler (spec: "Do not make the scheduler
depend on an active Streamlit browser session"). Runs as its own
long-lived process, entirely separate from `streamlit run app.py` - the
Streamlit "Run Now" button and this scheduler both call the exact same
backend.run_service.run_collection(), so a run started here shows up in
the dashboard exactly like a manual one.

Usage:
    python scheduler.py

Configuration (.env):
    DAILY_RUN_TIME=06:00          # HH:MM, in TIMEZONE
    TIMEZONE=Asia/Riyadh
    ENABLE_SCHEDULER=true         # if false, this process logs why and exits immediately
    SCHEDULER_JITTER_SECONDS=60   # random +/- jitter so many local installs don't all fire in the same second
---------------------------------------------------------------------
"""
from __future__ import annotations

import logging
import random
import sys
import time as time_module
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from competitors.hardees.backend import config, database, run_service

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("scheduler")


def _parse_run_time(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.strip().split(":")
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        logger.warning(f"[SCHEDULER] Could not parse DAILY_RUN_TIME={value!r} - falling back to 06:00")
        return 6, 0


def scheduled_job() -> None:
    if config.SCHEDULER_JITTER_SECONDS > 0:
        jitter = random.uniform(0, config.SCHEDULER_JITTER_SECONDS)
        logger.info(f"[SCHEDULER] Waiting {jitter:.1f}s jitter before starting the scheduled run")
        time_module.sleep(jitter)

    logger.info("[SCHEDULER] Starting scheduled collection run (channel=BOTH)")
    try:
        summary = run_service.run_collection(channel="BOTH", trigger="SCHEDULED", enable_screenshots=True)
        logger.info(f"[SCHEDULER] Scheduled run finished: overall_status={summary['overall_status']}")
        for ch in summary["channels"]:
            logger.info(f"[SCHEDULER]   {ch['channel']}: {ch['status']}")
    except run_service.RunAlreadyInProgressError as e:
        logger.warning(f"[SCHEDULER] Skipped scheduled run - another run is already active: {e}")
    except Exception as e:  # noqa: BLE001 - a scheduler job must never crash the whole process
        logger.error(f"[SCHEDULER] Scheduled run raised an unexpected error: {e}", exc_info=True)


def main() -> int:
    config.ensure_directories()
    database.init_db()

    if not config.ENABLE_SCHEDULER:
        logger.info("[SCHEDULER] ENABLE_SCHEDULER=false in .env - nothing to do. Exiting.")
        return 0

    hour, minute = _parse_run_time(config.DAILY_RUN_TIME)
    tz = pytz.timezone(config.TIMEZONE)
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(
        scheduled_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_collection",
        name="Daily Hardee's price/offer collection",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    now = datetime.now(tz)
    next_run = scheduler.get_job("daily_collection").trigger.get_next_fire_time(None, now)
    logger.info(f"[SCHEDULER] Daily run scheduled for {hour:02d}:{minute:02d} {config.TIMEZONE}. Next fire: {next_run}")
    logger.info("[SCHEDULER] Running independently of Streamlit - leave this process running (e.g. under systemd/pm2/screen) for daily collection to happen automatically.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[SCHEDULER] Shutting down.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
