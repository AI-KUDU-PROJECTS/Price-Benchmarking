"""Seed a temporary KFC SQLite database for adapter/BFF tests."""
from __future__ import annotations

import json
from pathlib import Path

from competitors.kfc.backend import database, models

BRANCH_ID = 143


def seed_kfc_db(db_path: Path) -> None:
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        database.upsert_branch(conn, BRANCH_ID, "Riyadh", "EUROMARCHE", 24.70, 46.66)
        _run(conn, "run-old-p", "PICKUP", "2026-09-01T06:00:00Z", "SUCCESS", 2)
        _run(conn, "run-old-d", "DELIVERY", "2026-09-01T06:05:00Z", "SUCCESS", 2)
        _run(conn, "run-new-p", "PICKUP", "2026-09-08T06:00:00Z", "SUCCESS", 2)
        _run(conn, "run-new-d", "DELIVERY", "2026-09-08T06:05:00Z", "SUCCESS", 2)
        _run(conn, "run-fail-p", "PICKUP", "2026-09-08T07:00:00Z", "FAILED", 0, error="schema")
        _external_run(conn, "run-hungerstation-old", "2026-09-01T06:10:00Z", 1)
        _external_product(
            conn,
            run_id="run-hungerstation-old",
            source_id="HUNGERSTATION|KFC|spicy-bites",
            captured="2026-09-01T06:10:00Z",
            name="Spicy Bites",
            regular=40.0,
            special=20.0,
        )
        _external_run(conn, "run-hungerstation", "2026-09-08T06:10:00Z", 1)
        _external_product(
            conn,
            run_id="run-hungerstation",
            source_id="HUNGERSTATION|KFC|spicy-bites",
            captured="2026-09-08T06:10:00Z",
            name="Spicy Bites",
            regular=40.0,
            special=18.0,
        )

        sizes = json.dumps(
            [
                {"title": "Medium", "price": 19.0},
                {"title": "Large", "price": 22.0},
            ],
            ensure_ascii=False,
        )

        _product(
            conn,
            key="143|PICKUP|id:100",
            product_id="100",
            channel="PICKUP",
            name="Spicy Bites",
            category="Chicken",
            status=models.ENTITY_STATUS_ACTIVE,
            first="2026-09-01T06:00:00Z",
            last="2026-09-08T06:00:00Z",
        )
        _product(
            conn,
            key="143|DELIVERY|id:100",
            product_id="100",
            channel="DELIVERY",
            name="Spicy Bites",
            category="Chicken",
            status=models.ENTITY_STATUS_ACTIVE,
            first="2026-09-01T06:05:00Z",
            last="2026-09-08T06:05:00Z",
        )
        _product(
            conn,
            key="143|PICKUP|id:200",
            product_id="200",
            channel="PICKUP",
            name="Mystery Item",
            category="Other",
            status=models.ENTITY_STATUS_NOT_OBSERVED,
            first="2026-09-01T06:00:00Z",
            last="2026-09-01T06:00:00Z",
        )
        _product(
            conn,
            key="143|PICKUP|id:300",
            product_id="300",
            channel="PICKUP",
            name="Retired Bucket",
            category="Chicken",
            status=models.ENTITY_STATUS_REMOVED,
            first="2026-08-01T06:00:00Z",
            last="2026-08-20T06:00:00Z",
        )

        _snapshot(
            conn,
            run_id="run-old-p",
            key="143|PICKUP|id:100",
            product_id="100",
            channel="PICKUP",
            captured="2026-09-01T06:00:00Z",
            name="Spicy Bites",
            category="Chicken",
            regular=21.0,
            special=None,
            sizes=sizes,
        )
        _snapshot(
            conn,
            run_id="run-new-p",
            key="143|PICKUP|id:100",
            product_id="100",
            channel="PICKUP",
            captured="2026-09-08T06:00:00Z",
            name="Spicy Bites",
            category="Chicken",
            regular=19.0,
            special=None,
            sizes=sizes,
            image="https://images.example.test/chicken-combo.jpg",
        )
        _snapshot(
            conn,
            run_id="run-new-d",
            key="143|DELIVERY|id:100",
            product_id="100",
            channel="DELIVERY",
            captured="2026-09-08T06:05:00Z",
            name="Spicy Bites",
            category="Chicken",
            regular=None,
            special=None,
            sizes="[]",
        )
        _snapshot(
            conn,
            run_id="run-old-p",
            key="143|PICKUP|id:200",
            product_id="200",
            channel="PICKUP",
            captured="2026-09-01T06:00:00Z",
            name="Mystery Item",
            category="Other",
            regular=10.0,
            special=None,
            sizes="[]",
        )
        _snapshot(
            conn,
            run_id="run-old-p",
            key="143|PICKUP|id:300",
            product_id="300",
            channel="PICKUP",
            captured="2026-08-20T06:00:00Z",
            name="Retired Bucket",
            category="Chicken",
            regular=30.0,
            special=None,
            sizes="[]",
        )

        _offer(
            conn,
            key="143|PICKUP|promo:9",
            promo_id="9",
            product_key="143|PICKUP|id:100",
            channel="PICKUP",
            name="Bites Deal",
            status=models.ENTITY_STATUS_ACTIVE,
            first="2026-09-08T06:00:00Z",
            last="2026-09-08T06:00:00Z",
            first_run="run-new-p",
        )
        _offer(
            conn,
            key="143|PICKUP|promo:8",
            promo_id="8",
            product_key="143|PICKUP|id:300",
            channel="PICKUP",
            name="Old Deal",
            status=models.ENTITY_STATUS_ENDED,
            first="2026-08-01T06:00:00Z",
            last="2026-08-20T06:00:00Z",
            first_run="run-old-p",
        )
        _offer(
            conn,
            key="143|PICKUP|promo:7",
            promo_id="7",
            product_key="143|PICKUP|id:200",
            channel="PICKUP",
            name="Maybe Deal",
            status=models.ENTITY_STATUS_NOT_OBSERVED,
            first="2026-09-01T06:00:00Z",
            last="2026-09-01T06:00:00Z",
            first_run="run-old-p",
        )

        _offer_snap(
            conn,
            run_id="run-new-p",
            key="143|PICKUP|promo:9",
            promo_id="9",
            product_key="143|PICKUP|id:100",
            channel="PICKUP",
            captured="2026-09-08T06:00:00Z",
            name="Bites Deal",
            original=21.0,
            offer=16.0,
            discount=24.0,
        )
        _offer_snap(
            conn,
            run_id="run-old-p",
            key="143|PICKUP|promo:8",
            promo_id="8",
            product_key="143|PICKUP|id:300",
            channel="PICKUP",
            captured="2026-08-20T06:00:00Z",
            name="Old Deal",
            original=30.0,
            offer=25.0,
            discount=None,
        )

        _event(conn, 1, "run-new-p", models.EVENT_PRICE_DECREASE, "product", "143|PICKUP|id:100", "Spicy Bites", "21.0", "19.0", -9.5, "2026-09-08T06:01:00Z")
        _event(conn, 2, "run-new-p", models.EVENT_NEW_OFFER, "offer", "143|PICKUP|promo:9", "Bites Deal", None, None, None, "2026-09-08T06:01:01Z")
        _event(conn, 3, "run-new-p", models.EVENT_PRODUCT_NOT_OBSERVED, "product", "143|PICKUP|id:200", "Mystery Item", None, None, None, "2026-09-08T06:01:02Z")
        _event(conn, 4, "run-new-p", models.EVENT_PRODUCT_REMOVED, "product", "143|PICKUP|id:300", "Retired Bucket", None, None, None, "2026-09-08T06:01:03Z")
        _event(conn, 5, "run-new-p", models.EVENT_OFFER_ENDED, "offer", "143|PICKUP|promo:8", "Old Deal", None, None, None, "2026-09-08T06:01:04Z")
        _event(conn, 6, "run-new-p", models.EVENT_OFFER_NOT_OBSERVED, "offer", "143|PICKUP|promo:7", "Maybe Deal", None, None, None, "2026-09-08T06:01:05Z")


def _run(conn, run_id, channel, started, status, products, error=None):
    conn.execute(
        """
        INSERT INTO crawl_runs (
            run_id, started_at, finished_at, channel, branch_id, status,
            product_count, offer_count, error_message, trigger_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 'MANUAL')
        """,
        (run_id, started, started, channel, BRANCH_ID, status, products, error),
    )


def _external_run(conn, run_id, started, products):
    conn.execute(
        """
        INSERT INTO external_channel_runs (
            run_id, channel, source, restaurant_name, branch_name,
            started_at, finished_at, status, product_count
        ) VALUES (?, 'HUNGERSTATION', 'hungerstation', 'KFC', 'HungerStation', ?, ?, 'SUCCESS', ?)
        """,
        (run_id, started, started, products),
    )


def _external_product(conn, *, run_id, source_id, captured, name, regular, special):
    conn.execute(
        """
        INSERT INTO external_channel_products (
            run_id, source_product_id, channel, source, restaurant_name,
            name_en, category_name_en, currency, regular_price, special_price,
            effective_price, discount_percentage, availability, captured_at
        ) VALUES (?, ?, 'HUNGERSTATION', 'hungerstation', 'KFC', ?,
                  'HungerStation Menu', 'SAR', ?, ?, ?, 55, 1, ?)
        """,
        (run_id, source_id, name, regular, special, special or regular, captured),
    )


def _product(conn, *, key, product_id, channel, name, category, status, first, last):
    conn.execute(
        """
        INSERT INTO products (
            canonical_product_key, product_id, channel, branch_id,
            product_name_en, category_name_en, first_seen_at, last_seen_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (key, product_id, channel, BRANCH_ID, name, category, first, last, status),
    )


def _snapshot(conn, *, run_id, key, product_id, channel, captured, name, category, regular, special, sizes, image=None):
    conn.execute(
        """
        INSERT INTO product_snapshots (
            run_id, product_key, product_id, channel, branch_id, captured_at,
            product_name_en, category_name_en, currency, regular_price, special_price,
            effective_price, availability, sizes, image_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SAR', ?, ?, ?, 1, ?, ?)
        """,
        (run_id, key, product_id, channel, BRANCH_ID, captured, name, category, regular, special, special or regular, sizes, image),
    )


def _offer(conn, *, key, promo_id, product_key, channel, name, status, first, last, first_run):
    conn.execute(
        """
        INSERT INTO offers (
            offer_key, promo_id, product_key, channel, branch_id, offer_name,
            offer_type, first_seen_run_id, first_seen_at, last_seen_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'Discount', ?, ?, ?, ?)
        """,
        (key, promo_id, product_key, channel, BRANCH_ID, name, first_run, first, last, status),
    )


def _offer_snap(conn, *, run_id, key, promo_id, product_key, channel, captured, name, original, offer, discount):
    conn.execute(
        """
        INSERT INTO offer_snapshots (
            run_id, offer_key, promo_id, product_key, channel, branch_id, captured_at,
            offer_name, original_price, offer_price, discount_percentage, offer_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Discount')
        """,
        (run_id, key, promo_id, product_key, channel, BRANCH_ID, captured, name, original, offer, discount),
    )


def _event(conn, event_id, run_id, event_type, entity_type, entity_key, name, old, new, pct, detected):
    conn.execute(
        """
        INSERT INTO change_events (
            id, run_id, event_type, channel, branch_id, entity_type, entity_key,
            entity_name, old_value, new_value, percentage_change, detected_at
        ) VALUES (?, ?, ?, 'PICKUP', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event_id, run_id, event_type, BRANCH_ID, entity_type, entity_key, name, old, new, pct, detected),
    )
