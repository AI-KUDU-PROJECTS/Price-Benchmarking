"""Independent daily scheduler for all configured HungerStation restaurants."""
from __future__ import annotations

import logging
import subprocess
import sys

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from competitors.hungerstation import config

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("hungerstation-scheduler")


def scheduled_job() -> None:
    result = subprocess.run(
        [sys.executable, "manage.py", "collect", "hungerstation", "--all"],
        cwd=config.REPO_ROOT,
        check=False,
    )
    if result.returncode:
        logger.error("HungerStation collection completed with one or more failed restaurants")
    else:
        logger.info("HungerStation collection completed successfully")


def main() -> int:
    if not config.ENABLE_SCHEDULER:
        logger.info("HUNGERSTATION_ENABLE_SCHEDULER=false; exiting")
        return 0
    hour, minute = (int(part) for part in config.DAILY_RUN_TIME.split(":", maxsplit=1))
    timezone = pytz.timezone(config.TIMEZONE)
    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        scheduled_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id="daily_hungerstation_collection",
        name="Daily HungerStation restaurant collection",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    logger.info("HungerStation collection scheduled daily at %s %s", config.DAILY_RUN_TIME, config.TIMEZONE)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("HungerStation scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
