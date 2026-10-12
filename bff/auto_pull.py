"""Run the Market Overview collections on a daily schedule inside the API.

Set AUTO_PULL_TIMES (Riyadh time, comma-separated, e.g. "11:00") to enable.
Each scheduled run uses the same pull managers as the Market Overview
buttons, so progress and results appear in the app exactly like a manual
pull. Websites run first and HungerStation starts only after they finish;
the two never run at the same time.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from bff.contract import RIYADH, TIMEZONE_NAME, to_riyadh_iso
from bff.pull_all import PullManager, hungerstation_pull_manager, pull_manager

logger = logging.getLogger("bff.auto_pull")

ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = 15.0

_scheduler: BackgroundScheduler | None = None
_times: list[str] = []
_include_hungerstation = False


def parse_times(value: str | None) -> list[str]:
    """Return sorted, de-duplicated HH:MM values; invalid entries are skipped."""
    times: set[str] = set()
    for part in (value or "").split(","):
        text = part.strip()
        if not text:
            continue
        try:
            hour_text, minute_text = text.split(":")
            hour, minute = int(hour_text), int(minute_text)
        except ValueError:
            logger.warning("[AUTO-PULL] Ignoring invalid time %r (expected HH:MM)", text)
            continue
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            logger.warning("[AUTO-PULL] Ignoring out-of-range time %r", text)
            continue
        times.add(f"{hour:02d}:{minute:02d}")
    return sorted(times)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _wait_until_idle(manager: PullManager, poll_seconds: float) -> None:
    while (manager.latest() or {}).get("status") == "running":
        time.sleep(poll_seconds)


def run_scheduled_pull(include_hungerstation: bool, poll_seconds: float = POLL_SECONDS) -> None:
    """Websites first, then HungerStation. A manual pull that is already
    running is waited for instead of being started twice."""
    _wait_until_idle(hungerstation_pull_manager, poll_seconds)
    pull_manager.start(trigger="scheduled")
    _wait_until_idle(pull_manager, poll_seconds)
    if include_hungerstation:
        hungerstation_pull_manager.start(trigger="scheduled")
        _wait_until_idle(hungerstation_pull_manager, poll_seconds)


def start_from_env() -> BackgroundScheduler | None:
    """Start the scheduler when AUTO_PULL_TIMES is set; otherwise do nothing."""
    global _scheduler, _times, _include_hungerstation
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    times = parse_times(os.environ.get("AUTO_PULL_TIMES"))
    include_hungerstation = _env_flag("AUTO_PULL_HUNGERSTATION", True)
    if not times:
        logger.info("[AUTO-PULL] AUTO_PULL_TIMES is not set; automatic collection is off.")
        return None

    scheduler = BackgroundScheduler(timezone=RIYADH)
    for value in times:
        hour, minute = value.split(":")
        scheduler.add_job(
            run_scheduled_pull,
            trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=RIYADH),
            args=[include_hungerstation],
            id=f"auto-pull-{value}",
            name=f"Automatic market collection at {value}",
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
    scheduler.start()
    _scheduler, _times, _include_hungerstation = scheduler, times, include_hungerstation
    logger.info(
        "[AUTO-PULL] Daily at %s %s, HungerStation=%s",
        ", ".join(times), TIMEZONE_NAME, include_hungerstation,
    )
    return scheduler


def stop() -> None:
    global _scheduler, _times
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    _scheduler, _times = None, []


def schedule_status() -> dict[str, Any]:
    next_run = None
    if _scheduler is not None:
        upcoming = [job.next_run_time for job in _scheduler.get_jobs() if job.next_run_time]
        if upcoming:
            next_run = to_riyadh_iso(min(upcoming))
    return {
        "enabled": _scheduler is not None,
        "times": list(_times),
        "includeHungerstation": _include_hungerstation,
        "nextRunAt": next_run,
        "timezone": TIMEZONE_NAME,
    }
