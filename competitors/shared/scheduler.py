"""Daily scheduler shared by every official-site competitor source."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from types import ModuleType

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


def _parse_run_time(value: str, fallback: str, logger: logging.Logger) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":")
        hour, minute = int(hour_text), int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError
        return hour, minute
    except (ValueError, AttributeError):
        logger.warning(
            "[SCHEDULER] Could not parse run time %r; falling back to %s",
            value,
            fallback,
        )
        hour_text, minute_text = fallback.split(":")
        return int(hour_text), int(minute_text)


def run_scheduler(
    *,
    brand_name: str,
    config: ModuleType,
    database: ModuleType,
    run_service: ModuleType,
    fallback_time: str,
    enable_setting: str,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
    )
    logger = logging.getLogger(f"scheduler.{brand_name.lower().replace(' ', '-')}")
    config.ensure_directories()
    database.init_db()

    if not config.ENABLE_SCHEDULER:
        logger.info("[SCHEDULER] %s=false; nothing to do.", enable_setting)
        return 0

    def scheduled_job() -> None:
        if config.SCHEDULER_JITTER_SECONDS > 0:
            jitter = random.uniform(0, config.SCHEDULER_JITTER_SECONDS)
            logger.info("[SCHEDULER] Waiting %.1fs before starting", jitter)
            time.sleep(jitter)

        logger.info("[SCHEDULER] Starting %s collection", brand_name)
        try:
            summary = run_service.run_collection(
                channel="BOTH",
                trigger="SCHEDULED",
                enable_screenshots=True,
            )
            logger.info(
                "[SCHEDULER] %s finished: %s",
                brand_name,
                summary["overall_status"],
            )
            for channel in summary["channels"]:
                logger.info(
                    "[SCHEDULER] %s: %s",
                    channel["channel"],
                    channel["status"],
                )
        except run_service.RunAlreadyInProgressError as error:
            logger.warning("[SCHEDULER] Another run is active: %s", error)
        except Exception:
            logger.exception("[SCHEDULER] Unexpected collection failure")

    hour, minute = _parse_run_time(config.DAILY_RUN_TIME, fallback_time, logger)
    timezone = pytz.timezone(config.TIMEZONE)
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        scheduled_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id="daily_collection",
        name=f"Daily {brand_name} price/offer collection",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    now = datetime.now(timezone)
    job = scheduler.get_job("daily_collection")
    next_run = job.trigger.get_next_fire_time(None, now)
    logger.info(
        "[SCHEDULER] Daily run: %02d:%02d %s. Next: %s",
        hour,
        minute,
        config.TIMEZONE,
        next_run,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("[SCHEDULER] Shutting down")
    return 0
