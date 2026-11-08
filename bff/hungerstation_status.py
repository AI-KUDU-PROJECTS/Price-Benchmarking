"""Read-only view of the latest HungerStation result for each restaurant."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from competitors.hungerstation import config, database

logger = logging.getLogger(__name__)


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def latest_collection_status(batch: dict | None, path: Path | None = None) -> dict | None:
    """Overlay newer completed individual runs without rewriting batch history."""
    if batch and batch["status"] == "running":
        return batch
    path = path if path is not None else config.DB_PATH
    if not path.exists():
        return batch
    try:
        with database.readonly_connection(path) as db:
            latest = {
                restaurant.id: db.execute(
                    "SELECT * FROM runs WHERE brand_id=? AND status IN ('SUCCESS','FAILED') "
                    "AND finished_at IS NOT NULL "
                    "ORDER BY julianday(started_at) DESC, julianday(finished_at) DESC, run_id DESC LIMIT 1",
                    (restaurant.id,),
                ).fetchone()
                for restaurant in config.RESTAURANTS
            }
    except sqlite3.Error:
        logger.warning("Could not read latest HungerStation collection results", exc_info=True)
        return batch

    # The KUDU integration has a different data source; preserve its batch row.
    brands = copy.deepcopy((batch or {}).get("brands", []))
    by_id = {row["id"]: row for row in brands}
    changed = False
    for restaurant in config.RESTAURANTS:
        saved = latest[restaurant.id]
        if saved is None:
            continue
        started = _timestamp(saved["started_at"])
        finished = _timestamp(saved["finished_at"])
        if started is None or finished is None:
            continue
        managed = by_id.get(restaurant.id)
        boundary = _timestamp(
            (managed or {}).get("completedAt") or (managed or {}).get("startedAt")
            or (batch or {}).get("startedAt")
        )
        # A newer startup failure may not have a database row. Never hide it
        # behind an old success, nor replace the batch's own collector result.
        if (boundary is not None and started <= boundary) or (
            batch and saved["batch_id"] == batch["runId"]
        ):
            continue
        status = saved["status"].lower()
        message = (
            f"Collected {saved['product_count']} products from HungerStation."
            if status == "success" else
            f"{saved['error_message'] or 'Collection failed.'} Previous complete data kept."
        )
        if managed is not None:
            message += " Updated by a newer collection."
        result = {
            "id": restaurant.id, "name": restaurant.name, "status": status,
            "startedAt": saved["started_at"], "completedAt": saved["finished_at"],
            "message": message, "sourceRunId": saved["run_id"],
        }
        if managed is None:
            brands.append(result)
        else:
            managed.clear()
            managed.update(result)
        changed = True
    if not changed:
        return batch

    statuses = {row["status"] for row in brands}
    status = "success" if statuses == {"success"} else "partial" if "success" in statuses else "failed"
    digest = hashlib.sha256(json.dumps(brands, sort_keys=True).encode()).hexdigest()[:16]
    starts = [row["startedAt"] for row in brands if _timestamp(row.get("startedAt"))]
    finishes = [row["completedAt"] for row in brands if _timestamp(row.get("completedAt"))]
    return {
        "runId": f"hungerstation-latest-{digest}", "status": status,
        "view": "latest_results", "batchRunId": (batch or {}).get("runId"),
        "startedAt": min(starts, key=_timestamp),
        "completedAt": max(finishes, key=_timestamp), "brands": brands,
    }
