"""
backend/database.py
---------------------------------------------------------------------
SQLite connection management + a small, explicit migration system.
No ORM - the schema is simple enough (and the spec explicitly calls this
"a local experimental project") that plain sqlite3 + parameterized SQL
keeps the whole data layer inspectable in one file.

Tables (see README "Database" for the full rationale):
  branches, crawl_runs, categories, products, product_snapshots,
  product_options, offers, offer_snapshots, change_events, screenshots,
  api_endpoints, schema_migrations
---------------------------------------------------------------------
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from competitors.kfc.backend import config

# Each migration is (version, description, list-of-SQL-statements). Applied
# in order, tracked in schema_migrations, and never re-applied. To evolve
# the schema, APPEND a new migration - never edit an already-shipped one.
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "initial schema",
        [
            """
            CREATE TABLE IF NOT EXISTS branches (
                store_id INTEGER PRIMARY KEY,
                city TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                is_fixed_branch INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED')),
                category_count INTEGER NOT NULL DEFAULT 0,
                product_count INTEGER NOT NULL DEFAULT 0,
                offer_count INTEGER NOT NULL DEFAULT 0,
                expected_category_count INTEGER NOT NULL DEFAULT 0,
                completion_percentage REAL NOT NULL DEFAULT 0,
                error_message TEXT,
                api_config_id TEXT,
                cluster_id TEXT,
                branch_currently_closed INTEGER NOT NULL DEFAULT 0,
                trigger_source TEXT NOT NULL DEFAULT 'MANUAL' CHECK (trigger_source IN ('MANUAL','SCHEDULED')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_crawl_runs_channel_status ON crawl_runs(channel, status, started_at)",
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id TEXT NOT NULL,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                name_en TEXT,
                name_ar TEXT,
                first_seen_run_id TEXT,
                first_seen_at TEXT,
                last_seen_run_id TEXT,
                last_seen_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE (category_id, channel, branch_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_product_key TEXT NOT NULL UNIQUE,
                product_id TEXT,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                sku TEXT,
                product_name_en TEXT,
                product_name_ar TEXT,
                normalized_name TEXT,
                category_id TEXT,
                category_name_en TEXT,
                category_name_ar TEXT,
                product_type TEXT,
                bundle_type_id TEXT,
                image_url TEXT,
                product_url TEXT,
                first_seen_run_id TEXT,
                first_seen_at TEXT,
                last_seen_run_id TEXT,
                last_seen_at TEXT,
                consecutive_missing_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','NOT_OBSERVED','REMOVED','RETURNED')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_products_channel_status ON products(channel, status)",
            "CREATE INDEX IF NOT EXISTS idx_products_product_id ON products(product_id)",
            """
            CREATE TABLE IF NOT EXISTS product_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                product_id TEXT,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                sku TEXT,
                product_name_en TEXT,
                product_name_ar TEXT,
                normalized_name TEXT,
                category_id TEXT,
                category_name_en TEXT,
                category_name_ar TEXT,
                description_en TEXT,
                description_ar TEXT,
                currency TEXT,
                regular_price REAL,
                special_price REAL,
                effective_price REAL,
                discount_amount REAL,
                discount_percentage REAL,
                promo_id TEXT,
                limited_offer INTEGER NOT NULL DEFAULT 0,
                product_type TEXT,
                bundle_type_id TEXT,
                availability INTEGER NOT NULL DEFAULT 1,
                image_url TEXT,
                product_url TEXT,
                calories TEXT,
                variants TEXT,
                sizes TEXT,
                option_groups TEXT,
                included_items TEXT,
                sides TEXT,
                drinks TEXT,
                sauces TEXT,
                add_ons TEXT,
                raw_api_json TEXT,
                source_endpoint TEXT,
                UNIQUE (run_id, product_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_product_snapshots_key ON product_snapshots(product_key, captured_at)",
            "CREATE INDEX IF NOT EXISTS idx_product_snapshots_run ON product_snapshots(run_id)",
            """
            CREATE TABLE IF NOT EXISTS product_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                product_key TEXT NOT NULL,
                option_group_id TEXT,
                option_group_title TEXT,
                option_group_subtitle TEXT,
                option_type TEXT,
                min_selections INTEGER,
                max_selections INTEGER,
                is_addon INTEGER NOT NULL DEFAULT 0,
                is_modifier INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_product_options_product ON product_options(product_key, run_id)",
            """
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offer_key TEXT NOT NULL UNIQUE,
                promo_id TEXT,
                product_key TEXT,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                offer_name TEXT,
                offer_type TEXT NOT NULL DEFAULT 'Unknown',
                bundle_type TEXT,
                first_seen_run_id TEXT,
                first_seen_at TEXT,
                last_seen_run_id TEXT,
                last_seen_at TEXT,
                consecutive_missing_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','NOT_OBSERVED','ENDED','RETURNED')),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_offers_channel_status ON offers(channel, status)",
            """
            CREATE TABLE IF NOT EXISTS offer_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                offer_key TEXT NOT NULL,
                promo_id TEXT,
                product_key TEXT,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                offer_name TEXT,
                main_item TEXT,
                included_items TEXT,
                number_of_pieces INTEGER,
                sides TEXT,
                drinks TEXT,
                sauces TEXT,
                sizes TEXT,
                add_ons TEXT,
                original_price REAL,
                offer_price REAL,
                saving_amount REAL,
                discount_percentage REAL,
                offer_description TEXT,
                offer_type TEXT,
                bundle_type TEXT,
                image_url TEXT,
                screenshot_path TEXT,
                source_endpoint TEXT,
                raw_json TEXT,
                UNIQUE (run_id, offer_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_offer_snapshots_key ON offer_snapshots(offer_key, captured_at)",
            """
            CREATE TABLE IF NOT EXISTS change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                compared_run_id TEXT,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                branch_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL CHECK (entity_type IN ('product','offer','category')),
                entity_key TEXT NOT NULL,
                entity_name TEXT,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                absolute_change REAL,
                percentage_change REAL,
                detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                evidence TEXT
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_change_events_run ON change_events(run_id, event_type)",
            "CREATE INDEX IF NOT EXISTS idx_change_events_entity ON change_events(entity_key, entity_type)",
            """
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                channel TEXT NOT NULL CHECK (channel IN ('PICKUP','DELIVERY')),
                entity_type TEXT NOT NULL CHECK (entity_type IN ('product','offer')),
                entity_key TEXT NOT NULL,
                event_type TEXT NOT NULL,
                screenshot_path TEXT,
                image_url TEXT,
                success INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                captured_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_screenshots_entity ON screenshots(entity_key, entity_type)",
            """
            CREATE TABLE IF NOT EXISTS api_endpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint_name TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                last_verified_at TEXT,
                last_run_id TEXT,
                last_status TEXT,
                notes TEXT,
                UNIQUE (endpoint_name)
            )
            """,
        ],
    ),
]


# Explicit column lists (excluding the autoincrement `id`) - used by
# run_service.py to filter a normalized dict down to exactly what the table
# accepts before building an INSERT, so an extra key produced by
# normalizer.py/offer_parser.py (e.g. denormalized context fields useful for
# logging but not stored per-row) can never raise "no column named ...".
PRODUCT_SNAPSHOT_COLUMNS = (
    "run_id", "product_key", "product_id", "channel", "branch_id", "captured_at",
    "sku", "product_name_en", "product_name_ar", "normalized_name", "category_id",
    "category_name_en", "category_name_ar", "description_en", "description_ar",
    "currency", "regular_price", "special_price", "effective_price", "discount_amount",
    "discount_percentage", "promo_id", "limited_offer", "product_type", "bundle_type_id",
    "availability", "image_url", "product_url", "calories", "variants", "sizes",
    "option_groups", "included_items", "sides", "drinks", "sauces", "add_ons",
    "raw_api_json", "source_endpoint",
)

OFFER_SNAPSHOT_COLUMNS = (
    "run_id", "offer_key", "promo_id", "product_key", "channel", "branch_id", "captured_at",
    "offer_name", "main_item", "included_items", "number_of_pieces", "sides", "drinks",
    "sauces", "sizes", "add_ons", "original_price", "offer_price", "saving_amount",
    "discount_percentage", "offer_description", "offer_type", "bundle_type", "image_url",
    "screenshot_path", "source_endpoint", "raw_json",
)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | None = None) -> None:
    """Creates the schema_migrations table (if needed) and applies every
    pending migration in order, inside its own transaction each."""
    path = db_path or config.DB_PATH
    conn = _connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
            """
        )
        conn.commit()
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, description, statements in MIGRATIONS:
            if version in applied:
                continue
            with conn:
                for stmt in statements:
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                    (version, description),
                )
    finally:
        conn.close()


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Context-managed connection. Ensures migrations have run and commits
    on clean exit / rolls back on exception."""
    path = db_path or config.DB_PATH
    init_db(path)
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_branch(conn: sqlite3.Connection, store_id: int, city: str, branch_name: str, latitude: float, longitude: float) -> None:
    conn.execute(
        """
        INSERT INTO branches (store_id, city, branch_name, latitude, longitude, is_fixed_branch, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        ON CONFLICT(store_id) DO UPDATE SET
            city=excluded.city, branch_name=excluded.branch_name,
            latitude=excluded.latitude, longitude=excluded.longitude,
            updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
        """,
        (store_id, city, branch_name, latitude, longitude),
    )
