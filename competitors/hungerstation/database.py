"""SQLite storage for HungerStation runs and historical menu snapshots."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from competitors.hungerstation import config

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        batch_id TEXT,
        brand_id TEXT NOT NULL,
        restaurant_name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','FAILED')),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        product_count INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        raw_capture_path TEXT,
        upload_status TEXT,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hs_runs_brand_status ON runs(brand_id, status, started_at)",
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        brand_id TEXT NOT NULL,
        source_product_id TEXT NOT NULL,
        name_en TEXT NOT NULL,
        description_en TEXT,
        category_name_en TEXT,
        currency TEXT,
        regular_price REAL,
        special_price REAL,
        effective_price REAL,
        discount_percentage REAL,
        calories INTEGER,
        availability INTEGER,
        image_url TEXT,
        captured_at TEXT NOT NULL,
        raw_json TEXT,
        UNIQUE (run_id, source_product_id),
        FOREIGN KEY (run_id) REFERENCES runs(run_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hs_products_brand_run ON products(brand_id, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_hs_products_history ON products(brand_id, source_product_id, captured_at)",
)


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db(path: Path = config.DB_PATH) -> None:
    with _connect(path) as connection:
        for statement in SCHEMA:
            connection.execute(statement)


@contextmanager
def connection(path: Path = config.DB_PATH) -> Iterator[sqlite3.Connection]:
    init_db(path)
    db = _connect(path)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def save_success(
    *,
    run_id: str,
    batch_id: str | None,
    brand_id: str,
    restaurant_name: str,
    started_at: str,
    finished_at: str,
    items: list[dict[str, Any]],
    raw_capture_path: str | None,
    path: Path = config.DB_PATH,
) -> None:
    unique_items: dict[str, dict[str, Any]] = {}
    for item in items:
        source_id = item["source_product_id"]
        previous = unique_items.get(source_id)
        if previous is None or (
            previous.get("is_summary_card") and not item.get("is_summary_card")
        ):
            unique_items[source_id] = item
    items = list(unique_items.values())
    with connection(path) as db:
        db.execute(
            """
            INSERT INTO runs (
                run_id, batch_id, brand_id, restaurant_name, status,
                started_at, finished_at, product_count, raw_capture_path
            ) VALUES (?, ?, ?, ?, 'SUCCESS', ?, ?, ?, ?)
            """,
            (run_id, batch_id, brand_id, restaurant_name, started_at, finished_at, len(items), raw_capture_path),
        )
        for item in items:
            db.execute(
                """
                INSERT INTO products (
                    run_id, brand_id, source_product_id, name_en, description_en,
                    category_name_en, currency, regular_price, special_price,
                    effective_price, discount_percentage, calories, availability,
                    image_url, captured_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, brand_id, item["source_product_id"], item["name_en"],
                    item.get("description_en"), item.get("category_name_en"),
                    item.get("currency", "SAR"), item.get("regular_price"),
                    item.get("special_price"), item.get("effective_price"),
                    item.get("discount_percentage"), item.get("calories"),
                    item.get("availability", 1), item.get("image_url"),
                    finished_at, json.dumps(item, ensure_ascii=False),
                ),
            )


def save_failure(
    *,
    run_id: str,
    batch_id: str | None,
    brand_id: str,
    restaurant_name: str,
    started_at: str,
    finished_at: str,
    error: str,
    path: Path = config.DB_PATH,
) -> None:
    with connection(path) as db:
        db.execute(
            """
            INSERT INTO runs (
                run_id, batch_id, brand_id, restaurant_name, status,
                started_at, finished_at, product_count, error_message
            ) VALUES (?, ?, ?, ?, 'FAILED', ?, ?, 0, ?)
            """,
            (run_id, batch_id, brand_id, restaurant_name, started_at, finished_at, error[:1000]),
        )


def latest_run(db: sqlite3.Connection, brand_id: str, *, success_only: bool = False) -> sqlite3.Row | None:
    status_sql = "AND status = 'SUCCESS'" if success_only else ""
    return db.execute(
        f"SELECT * FROM runs WHERE brand_id = ? {status_sql} ORDER BY started_at DESC LIMIT 1",
        (brand_id,),
    ).fetchone()


def latest_products(db: sqlite3.Connection, brand_id: str) -> list[sqlite3.Row]:
    return db.execute(
        """
        WITH latest AS (
            SELECT run_id FROM runs
            WHERE brand_id = ? AND status = 'SUCCESS'
            ORDER BY started_at DESC LIMIT 1
        ),
        history AS (
            SELECT
                p.*,
                r.started_at AS run_started,
                LAG(p.regular_price) OVER (
                    PARTITION BY p.source_product_id ORDER BY r.started_at
                ) AS previous_regular_price,
                LAG(p.special_price) OVER (
                    PARTITION BY p.source_product_id ORDER BY r.started_at
                ) AS previous_special_price,
                LAG(p.effective_price) OVER (
                    PARTITION BY p.source_product_id ORDER BY r.started_at
                ) AS previous_effective_price,
                LAG(p.availability) OVER (
                    PARTITION BY p.source_product_id ORDER BY r.started_at
                ) AS previous_availability,
                LAG(p.run_id) OVER (
                    PARTITION BY p.source_product_id ORDER BY r.started_at
                ) AS previous_run_id,
                MIN(p.captured_at) OVER (
                    PARTITION BY p.source_product_id
                ) AS first_seen_at,
                MAX(p.captured_at) OVER (
                    PARTITION BY p.source_product_id
                ) AS last_seen_at
            FROM products p
            JOIN runs r ON r.run_id = p.run_id
            WHERE p.brand_id = ? AND r.status = 'SUCCESS'
        )
        SELECT history.* FROM history JOIN latest ON latest.run_id = history.run_id
        ORDER BY history.category_name_en, history.name_en
        """,
        (brand_id, brand_id),
    ).fetchall()


def observations(db: sqlite3.Connection, brand_id: str, source_product_id: str) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT p.*, r.started_at AS run_started
        FROM products p JOIN runs r ON r.run_id = p.run_id
        WHERE p.brand_id = ? AND p.source_product_id = ? AND r.status = 'SUCCESS'
        ORDER BY r.started_at ASC
        """,
        (brand_id, source_product_id),
    ).fetchall()


def historical_products(db: sqlite3.Connection, brand_id: str) -> list[sqlite3.Row]:
    return db.execute(
        """
        WITH history AS (
            SELECT
                p.*,
                r.started_at,
                LAG(p.run_id) OVER (PARTITION BY p.source_product_id ORDER BY r.started_at) AS previous_run_id,
                LAG(p.effective_price) OVER (PARTITION BY p.source_product_id ORDER BY r.started_at) AS previous_effective_price,
                LAG(p.special_price) OVER (PARTITION BY p.source_product_id ORDER BY r.started_at) AS previous_special_price,
                LAG(p.availability) OVER (PARTITION BY p.source_product_id ORDER BY r.started_at) AS previous_availability
            FROM products p JOIN runs r ON r.run_id = p.run_id
            WHERE p.brand_id = ? AND r.status = 'SUCCESS'
        )
        SELECT * FROM history WHERE previous_run_id IS NOT NULL ORDER BY started_at DESC
        """,
        (brand_id,),
    ).fetchall()
