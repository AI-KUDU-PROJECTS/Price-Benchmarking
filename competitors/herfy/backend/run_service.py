"""
backend/run_service.py
---------------------------------------------------------------------
Orchestrates one full collection run: acquires the run lock, invokes the
Node collector (collector/collect.js) as a subprocess, validates and
ingests its output into SQLite, runs change detection for every SUCCESS
channel, triggers screenshot capture for NEW_PRODUCT/NEW_OFFER events, and
returns a summary dict. Identical orchestration to competitors/kfc's and
competitors/burger_king's run_service.py except for the import path and
the product_options extraction (Herfy's menu-ref response already
resolves modifier-group references into clean {id, name, nameAr, min,
max, modifiers} records in the Node collector - see channel-collector.js's
resolveOptionGroups() - so no generic tree-walk is needed here, unlike
Burger King's).

This is the ONE function both run_collector.py (CLI), scheduler.py (the
daily job), and dashboard/page.py's "Run Now" button all call - so there
is exactly one code path that can ever start a collection run, which is
also where the concurrency lock lives.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import os
import subprocess
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from competitors.herfy.backend import change_detector, config, database, models, normalizer, offer_parser, schema_validator

LOCK_STALE_SECONDS = 30 * 60  # a lock older than this is assumed to be from a crashed process, not a live run


class RunAlreadyInProgressError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_batch_id() -> str:
    return "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


@contextmanager
def run_lock() -> Iterator[None]:
    """Filesystem-based run lock. Atomic create via O_CREAT|O_EXCL so two
    processes racing to acquire it can never both succeed. A lock older
    than LOCK_STALE_SECONDS is treated as abandoned (crashed process) and
    reclaimed automatically - it is never left to block the system
    forever."""
    config.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if config.LOCK_FILE.exists():
        age = time.time() - config.LOCK_FILE.stat().st_mtime
        if age < LOCK_STALE_SECONDS:
            raise RunAlreadyInProgressError(
                f"A collection run is already in progress (lock created {int(age)}s ago: {config.LOCK_FILE})."
            )
        try:
            config.LOCK_FILE.unlink()
        except FileNotFoundError:
            pass

    try:
        fd = os.open(str(config.LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RunAlreadyInProgressError(f"A collection run is already in progress: {config.LOCK_FILE}")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"pid": os.getpid(), "started_at": _now_iso()}))
    try:
        yield
    finally:
        try:
            config.LOCK_FILE.unlink()
        except FileNotFoundError:
            pass


def is_run_active() -> bool:
    if not config.LOCK_FILE.exists():
        return False
    age = time.time() - config.LOCK_FILE.stat().st_mtime
    return age < LOCK_STALE_SECONDS


def _invoke_node(script: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    cmd = [config.NODE_BIN, str(script), *args]
    return subprocess.run(
        cmd,
        cwd=str(config.PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ingest_channel(conn: sqlite3.Connection, batch_id: str, channel: str, out_dir: Path) -> dict[str, Any]:
    """Reads <out_dir>/<CHANNEL>.json, validates it, writes the crawl_runs
    row + product_snapshots/offer_snapshots/product_options, and returns a
    summary dict. Never raises for a normal collection failure - a missing
    or malformed file becomes a FAILED run row, not a crash."""
    run_id = f"{batch_id}-{channel}"
    channel_file = out_dir / f"{channel}.json"
    started_at = _now_iso()

    if not channel_file.exists():
        conn.execute(
            """
            INSERT INTO crawl_runs (run_id, started_at, finished_at, channel, branch_id, status, error_message, trigger_source)
            VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?)
            """,
            (run_id, started_at, _now_iso(), channel, config.BRANCH_STORE_ID, f"Collector output file not found: {channel_file}", "MANUAL"),
        )
        return {"run_id": run_id, "channel": channel, "status": "FAILED", "error": "output file missing"}

    with open(channel_file, encoding="utf-8") as f:
        data = json.load(f)

    usable, problems = schema_validator.is_usable(data)
    if not usable:
        conn.execute(
            """
            INSERT INTO crawl_runs (run_id, started_at, finished_at, channel, branch_id, status, error_message, trigger_source)
            VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?)
            """,
            (run_id, started_at, _now_iso(), channel, config.BRANCH_STORE_ID, "Schema validation failed: " + "; ".join(problems), "MANUAL"),
        )
        return {"run_id": run_id, "channel": channel, "status": "FAILED", "error": problems}

    result = models.ChannelResult.from_json(data)
    branch_id = result.branch_id or config.BRANCH_STORE_ID
    finished_at = result.finished_at or _now_iso()

    progressive_promo_ids: set[str] = set()
    for promo in result.promotions:
        pid = promo.get("promoId") if isinstance(promo, dict) else None
        if pid is not None:
            progressive_promo_ids.add(str(pid))

    conn.execute(
        """
        INSERT INTO crawl_runs (
            run_id, started_at, finished_at, channel, branch_id, status,
            category_count, product_count, offer_count, expected_category_count,
            completion_percentage, error_message, api_config_id, cluster_id,
            branch_currently_closed, trigger_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, result.started_at or started_at, finished_at, channel, branch_id, result.status,
            result.category_count, result.product_count, result.expected_category_count,
            result.completion_percentage, result.error_message, result.api_config_id, result.cluster_id,
            1 if result.branch_currently_closed else 0, "MANUAL",
        ),
    )

    offer_count = 0
    for product in result.products:
        snap = normalizer.normalize_product(
            product, channel=channel, branch_id=branch_id, branch_name=result.branch_name, city=result.city,
            cluster_id=result.cluster_id, config_id=result.api_config_id, run_id=run_id, captured_at=finished_at,
        )
        cols = database.PRODUCT_SNAPSHOT_COLUMNS
        conn.execute(
            f"INSERT OR REPLACE INTO product_snapshots ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(snap[c] for c in cols),
        )
        # Already resolved into clean {id, name, nameAr, min, max,
        # modifiers} records by the Node collector (channel-collector.js's
        # resolveOptionGroups()) - no generic tree-walk needed here.
        for group in product.get("__optionGroups") or []:
            group_name = (group.get("name") or "").strip().lower()
            is_addon = 1 if "extra" in group_name else 0
            conn.execute(
                """
                INSERT INTO product_options (
                    run_id, product_key, option_group_id, option_group_title, option_group_subtitle,
                    option_type, min_selections, max_selections, is_addon, is_modifier, is_hidden, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, snap["product_key"], str(group.get("id")), group.get("name"), group.get("nameAr"),
                    "modifier", group.get("min"), group.get("max"), is_addon, 1, 0,
                    json.dumps(group, ensure_ascii=False),
                ),
            )
        if offer_parser.is_offer_product(product):
            offer_snap = offer_parser.build_offer_snapshot(
                product, product_key=snap["product_key"], channel=channel, branch_id=branch_id,
                run_id=run_id, captured_at=finished_at, progressive_promo_ids=progressive_promo_ids,
            )
            cols = database.OFFER_SNAPSHOT_COLUMNS
            conn.execute(
                f"INSERT OR REPLACE INTO offer_snapshots ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                tuple(offer_snap[c] for c in cols),
            )
            offer_count += 1

    conn.execute("UPDATE crawl_runs SET offer_count = ? WHERE run_id = ?", (offer_count, run_id))
    database.upsert_branch(conn, branch_id, result.city or config.BRANCH_CITY, result.branch_name or config.BRANCH_NAME, config.BRANCH_LATITUDE, config.BRANCH_LONGITUDE)

    change_summary: dict[str, Any] = {"skipped": "not a SUCCESS run"}
    if result.status == models.RUN_STATUS_SUCCESS:
        change_summary = change_detector.run_change_detection(conn, run_id)

    return {
        "run_id": run_id, "channel": channel, "status": result.status,
        "product_count": result.product_count, "offer_count": offer_count,
        "change_summary": change_summary,
    }


def _record_endpoint_health(conn: sqlite3.Connection, batch_id: str, out_dir: Path) -> None:
    """Best-effort population of the api_endpoints reference table from the
    raw per-call dumps collect.js wrote - purely informational for the
    Streamlit "Run Logs"/"Sources" views."""
    for channel_dir in out_dir.glob("raw/*"):
        if not channel_dir.is_dir():
            continue
        for raw_file in channel_dir.glob("*.json"):
            try:
                with open(raw_file, encoding="utf-8") as f:
                    entry = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            endpoint = str(entry.get("endpoint", raw_file.stem))
            endpoint_name = endpoint.split("-")[0].split("_")[0] if endpoint else raw_file.stem
            ok = bool(entry.get("ok")) and bool((entry.get("schema") or {}).get("valid", True))
            conn.execute(
                """
                INSERT INTO api_endpoints (endpoint_name, method, path, last_verified_at, last_run_id, last_status)
                VALUES (?, 'POST', ?, ?, ?, ?)
                ON CONFLICT(endpoint_name) DO UPDATE SET
                    last_verified_at = excluded.last_verified_at,
                    last_run_id = excluded.last_run_id,
                    last_status = excluded.last_status
                """,
                (endpoint_name, endpoint_name, _now_iso(), batch_id, "OK" if ok else "SCHEMA_ERROR"),
            )


def _collect_screenshot_jobs(conn: sqlite3.Connection, batch_id: str, channel_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for cr in channel_results:
        run_id = cr["run_id"]
        rows = conn.execute(
            "SELECT * FROM change_events WHERE run_id = ? AND event_type IN (?, ?)",
            (run_id, models.EVENT_NEW_PRODUCT, models.EVENT_NEW_OFFER),
        ).fetchall()
        for row in rows:
            if row["entity_type"] == "product":
                prod = conn.execute("SELECT * FROM product_snapshots WHERE run_id = ? AND product_key = ?", (run_id, row["entity_key"])).fetchone()
                if prod is None:
                    continue
                jobs.append({
                    "product_id": prod["product_id"] or row["entity_key"],
                    "product_name": prod["product_name_en"] or row["entity_name"] or "",
                    "product_name_ar": prod["product_name_ar"],  # Arabic fallback for screenshot-capture.js - this brand's UI is Arabic-first
                    "category_name": prod["category_name_en"],
                    "channel": cr["channel"],
                    "event_type": row["event_type"],
                    "date": today,
                    "entity_type": "product",
                    "entity_key": row["entity_key"],
                    "run_id": run_id,
                })
            else:
                offer = conn.execute("SELECT * FROM offer_snapshots WHERE run_id = ? AND offer_key = ?", (run_id, row["entity_key"])).fetchone()
                if offer is None:
                    continue
                jobs.append({
                    "product_id": offer["offer_key"],
                    "product_name": offer["main_item"] or row["entity_name"] or "",
                    "product_name_ar": None,
                    "category_name": None,
                    "channel": cr["channel"],
                    "event_type": row["event_type"],
                    "date": today,
                    "entity_type": "offer",
                    "entity_key": row["entity_key"],
                    "run_id": run_id,
                })
    return jobs[: config.MAX_SCREENSHOTS_PER_RUN]


def _run_screenshot_capture(conn: sqlite3.Connection, jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        return
    jobs_path = config.RAW_DATA_DIR / "_screenshot_jobs.json"
    results_path = config.RAW_DATA_DIR / "_screenshot_results.json"
    with open(jobs_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f)
    try:
        _invoke_node(
            config.SCREENSHOT_SCRIPT,
            [f"--jobs={jobs_path}", f"--out={results_path}"],
            timeout=config.SCREENSHOT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return
    if not results_path.exists():
        return
    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)
    for job, result in zip(jobs, results):
        conn.execute(
            """
            INSERT INTO screenshots (run_id, channel, entity_type, entity_key, event_type, screenshot_path, image_url, success, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["run_id"], job["channel"], job["entity_type"], job["entity_key"], job["event_type"],
                result.get("screenshot_path"), None, 1 if result.get("success") else 0, result.get("error"),
            ),
        )
        if result.get("success") and job["entity_type"] == "offer":
            conn.execute(
                "UPDATE offer_snapshots SET screenshot_path = ? WHERE offer_key = ?",
                (result.get("screenshot_path"), job["entity_key"]),
            )


def run_collection(channel: str = "BOTH", trigger: str = "MANUAL", enable_screenshots: bool = True) -> dict[str, Any]:
    """The single entry point for starting a collection run. `channel` is
    one of PICKUP / DELIVERY / BOTH. Raises RunAlreadyInProgressError if
    another run is active - callers (CLI/scheduler/Streamlit) should catch
    this and surface it, never retry-loop around it."""
    config.ensure_directories()
    channel = channel.upper()
    if channel not in ("PICKUP", "DELIVERY", "BOTH"):
        raise ValueError(f"Unknown channel: {channel}")

    with run_lock():
        batch_id = new_batch_id()
        out_dir = config.RAW_DATA_DIR / batch_id
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            proc = _invoke_node(
                config.COLLECT_SCRIPT,
                [f"--run-id={batch_id}", f"--channel={channel}", f"--out-dir={out_dir}"],
                timeout=config.COLLECTOR_TIMEOUT_SECONDS,
            )
            node_ok = proc.returncode == 0
            node_log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired as e:
            node_ok = False
            node_log = f"Node collector timed out after {config.COLLECTOR_TIMEOUT_SECONDS}s: {e}"

        with open(out_dir / "node_log.txt", "w", encoding="utf-8") as f:
            f.write(node_log)

        channels_to_ingest = ["PICKUP", "DELIVERY"] if channel == "BOTH" else [channel]

        with database.get_connection() as conn:
            channel_results = []
            if not node_ok and not (out_dir / "summary.json").exists():
                # The Node process crashed before writing anything at all -
                # record a FAILED run row per requested channel so this is
                # visible in Run Logs rather than silently vanishing.
                for c in channels_to_ingest:
                    run_id = f"{batch_id}-{c}"
                    conn.execute(
                        "INSERT INTO crawl_runs (run_id, started_at, finished_at, channel, branch_id, status, error_message, trigger_source) VALUES (?, ?, ?, ?, ?, 'FAILED', ?, ?)",
                        (run_id, _now_iso(), _now_iso(), c, config.BRANCH_STORE_ID, f"Node collector process failed: {node_log[-2000:]}", trigger),
                    )
                    channel_results.append({"run_id": run_id, "channel": c, "status": "FAILED", "error": "node process failed"})
            else:
                for c in channels_to_ingest:
                    channel_results.append(_ingest_channel(conn, batch_id, c, out_dir))

            _record_endpoint_health(conn, batch_id, out_dir)

            screenshot_jobs = []
            if enable_screenshots:
                screenshot_jobs = _collect_screenshot_jobs(conn, batch_id, channel_results)

        if screenshot_jobs:
            with database.get_connection() as conn:
                _run_screenshot_capture(conn, screenshot_jobs)

        statuses = [cr["status"] for cr in channel_results]
        if all(s == "SUCCESS" for s in statuses):
            overall = "SUCCESS"
        elif any(s in ("SUCCESS", "PARTIAL") for s in statuses):
            overall = "PARTIAL"
        else:
            overall = "FAILED"

        return {
            "batch_id": batch_id,
            "channel": channel,
            "overall_status": overall,
            "channels": channel_results,
            "screenshots_captured": len(screenshot_jobs),
        }
