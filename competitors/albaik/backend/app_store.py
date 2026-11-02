"""Atomic official-app snapshots using the existing price/history schema."""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path

from competitors.albaik import app_config as config
from competitors.shared.backend import database, change_detector


def latest_collection_status(active_run: dict | None, path: Path | None = None,
                             raw_dir: Path | None = None) -> dict | None:
    """Show actual latest channel results, including collections run from the CLI."""
    if active_run and active_run["status"] == "running":
        return active_run
    path = path or config.DB_PATH
    if not path.exists():
        return active_run
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = {channel: db.execute("SELECT * FROM crawl_runs WHERE channel=? AND branch_id=? ORDER BY started_at DESC LIMIT 1",
                                   (channel,config.BRANCH_ID)).fetchone() for channel in ("PICKUP","DELIVERY")}
    if not any(row is not None for row in rows.values()):
        return active_run
    brands=[]
    for channel,row in rows.items():
        managed = next((entry for entry in (active_run or {}).get("brands",[])
                        if entry["id"]==f"albaik-{channel.lower()}"),None)
        # A startup failure may happen before the collector can write a DB run.
        # Never replace that newer failure with an older successful snapshot.
        if managed and managed["status"]=="failed" and managed.get("startedAt") and (
                row is None or datetime.fromisoformat(managed["startedAt"].replace("Z","+00:00")) >
                datetime.fromisoformat(row["started_at"].replace("Z","+00:00"))):
            brands.append(dict(managed))
            continue
        status = "pending" if row is None else row["status"].lower()
        message = "No app collection yet." if row is None else row["error_message"]
        if row is not None and status=="success":
            message=f"Collected {row['product_count']} products."
            capture=(raw_dir or config.RAW_DIR)/row["run_id"]/"capture.json"
            try:
                captured=json.loads(capture.read_text(encoding="utf-8"))
                images=captured["images_new"]
                message=f"Collected {row['product_count']} products; {int(images)} new images saved."
                if captured.get("excluded_products"):
                    message += " Excluded as requested: " + ", ".join(captured["excluded_products"]) + "."
                if captured.get("unreadable_products"):
                    message += " Could not open after two attempts (skipped): " + ", ".join(captured["unreadable_products"]) + "."
            except (OSError,ValueError,KeyError,TypeError):
                pass
        brands.append(dict(id=f"albaik-{channel.lower()}",name=f"AlBaik · {channel.title()}",status=status,
                           startedAt=row["started_at"] if row else None,completedAt=row["finished_at"] if row else None,
                           message=message))
    statuses={row["status"] for row in brands}
    status="running" if "running" in statuses else "success" if statuses=={"success"} else "partial" if "success" in statuses else "failed"
    return dict(runId="/".join(f"{row['id']}:{row['startedAt']}:{row['status']}" for row in brands),status=status,trigger="manual",
                startedAt=min(row["startedAt"] for row in brands if row["startedAt"]),
                completedAt=max((row["completedAt"] for row in brands if row["completedAt"]),default=None),
                brands=brands)


def save_failure(run_id: str, channel: str, started_at: str, finished_at: str,
                 message: str, path: Path = config.DB_PATH) -> None:
    with database.get_connection(path) as db:
        db.execute("""INSERT INTO crawl_runs
            (run_id,channel,branch_id,started_at,finished_at,status,error_message)
            VALUES (?,?,?,?,?,'FAILED',?)""",
            (run_id, channel, config.BRANCH_ID, started_at, finished_at, message[:1000]))


def save_success(payload: dict, path: Path = config.DB_PATH) -> None:
    """Reject incomplete/unverified results before replacing a channel's menu."""
    items = payload["items"]
    if payload.get("complete") is not True or len(items) < 10:
        raise ValueError("The app did not confirm a complete menu with at least 10 products.")
    if payload["channel"] not in {"PICKUP", "DELIVERY"}:
        raise ValueError("Unknown collection channel.")
    seen = set()
    for item in items:
        price = item.get("price")
        if not item.get("id") or item["id"] in seen or not item.get("name"):
            raise ValueError("Missing or duplicate product identity.")
        seen.add(item["id"])
        if isinstance(price, bool) or not isinstance(price, (float, int)) or not math.isfinite(price) or price < 0:
            raise ValueError("A product has no valid observed price.")
        if not item.get("image_url"):
            raise ValueError("A product image is missing; previous complete data kept.")
    for base in {item.get("base_name") for item in items if "Spicy" in item.get("customizations",{})}:
        variants={item["name"] for item in items if item.get("base_name")==base}
        if len(variants)<2:
            raise ValueError(f"The Spicy option for {base} was not fully captured.")

    channel, run_id = payload["channel"], payload["run_id"]
    stamp = payload["finished_at"]
    categories = {item["category"] for item in items}
    with database.get_connection(path) as db:
        previous = db.execute("SELECT product_count FROM crawl_runs WHERE channel=? AND branch_id=? AND status='SUCCESS' ORDER BY started_at DESC LIMIT 1",
                              (channel, config.BRANCH_ID)).fetchone()
        if previous and len(items) < previous["product_count"] * 0.8:
            raise ValueError(f"Menu dropped from {previous['product_count']} to {len(items)} products; review the capture before accepting it.")
        database.upsert_branch(db, config.BRANCH_ID, "Riyadh", "Arubah pickup / delivery nearby, Olaya, Riyadh", config.LATITUDE, config.LONGITUDE)
        db.execute("""INSERT INTO crawl_runs (run_id,channel,branch_id,started_at,finished_at,status,
            category_count,product_count,expected_category_count,completion_percentage)
            VALUES (?,?,?,?,?,'SUCCESS',?,?,?,100)""",
            (run_id,channel,config.BRANCH_ID,payload["started_at"],stamp,len(categories),len(items),len(categories)))
        for item in items:
            snap = dict.fromkeys(database.PRODUCT_SNAPSHOT_COLUMNS)
            snap.update(run_id=run_id,product_key=f"{channel}|{config.BRANCH_ID}|{item['id']}",
                        product_id=item["id"],channel=channel,branch_id=config.BRANCH_ID,captured_at=stamp,
                        product_name_en=item["name"],normalized_name=item["name"].casefold(),
                        category_id=item["category"],category_name_en=item["category"],
                        description_en=item.get("description"),currency="SAR",regular_price=item["price"],
                        effective_price=item["price"],limited_offer=0,availability=1,
                        image_url=item["image_url"],calories=str(item["calories"]) if item.get("calories") is not None else None,
                        raw_api_json=json.dumps(item,ensure_ascii=False),source_endpoint="ALBAIK Android app")
            columns = database.PRODUCT_SNAPSHOT_COLUMNS
            db.execute(f"INSERT INTO product_snapshots ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [snap[column] for column in columns])
        change_detector.run_change_detection(db, run_id)
