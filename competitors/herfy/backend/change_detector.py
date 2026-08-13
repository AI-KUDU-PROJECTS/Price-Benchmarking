"""
backend/change_detector.py
---------------------------------------------------------------------
The Change Detection Engine. Compares the CURRENT run's snapshots against
the most recent PREVIOUS SUCCESSFUL run for the same branch+channel, and
emits change_events rows plus updates to the products/offers/categories
dimension tables (first_seen/last_seen/consecutive_missing_count/status).
Identical logic to competitors/kfc/backend/change_detector.py - this
engine operates purely on the generic schema and is fully brand-agnostic.

Critical rule (see README "Critical Rule to Prevent False Alerts"):
comparisons only ever happen between two runs with status == 'SUCCESS'.
run_change_detection() is a no-op (returns immediately, changes nothing)
if the current run is not SUCCESS - callers (backend/run_service.py) are
expected to only call this after a successful run, but the guard lives
here too so it can never be bypassed by a future caller mistake.
---------------------------------------------------------------------
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from competitors.herfy.backend import models

NOT_OBSERVED_THRESHOLD = 1
REMOVED_THRESHOLD = 3


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_run(conn: sqlite3.Connection, run_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM crawl_runs WHERE run_id = ?", (run_id,)).fetchone()


def get_previous_successful_run(conn: sqlite3.Connection, channel: str, branch_id: int, before_started_at: str, exclude_run_id: str) -> Optional[sqlite3.Row]:
    """Most recent OTHER run with status='SUCCESS' for the same channel+
    branch, started strictly before the current run - even if the
    immediately previous calendar day failed, since PARTIAL/FAILED runs
    are simply invisible to this query."""
    return conn.execute(
        """
        SELECT * FROM crawl_runs
        WHERE channel = ? AND branch_id = ? AND status = 'SUCCESS'
          AND run_id != ? AND started_at < ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (channel, branch_id, exclude_run_id, before_started_at),
    ).fetchone()


def _product_rows(conn: sqlite3.Connection, run_id: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM product_snapshots WHERE run_id = ?", (run_id,)).fetchall()
    return {row["product_key"]: row for row in rows}


def _offer_rows(conn: sqlite3.Connection, run_id: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM offer_snapshots WHERE run_id = ?", (run_id,)).fetchall()
    return {row["offer_key"]: row for row in rows}


def _insert_event(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    compared_run_id: Optional[str],
    event_type: str,
    channel: str,
    branch_id: int,
    entity_type: str,
    entity_key: str,
    entity_name: Optional[str],
    field_name: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    absolute_change: Optional[float] = None,
    percentage_change: Optional[float] = None,
    evidence: Optional[dict] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO change_events (
            run_id, compared_run_id, event_type, channel, branch_id, entity_type,
            entity_key, entity_name, field_name, old_value, new_value,
            absolute_change, percentage_change, detected_at, evidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id, compared_run_id, event_type, channel, branch_id, entity_type,
            entity_key, entity_name, field_name,
            None if old_value is None else str(old_value),
            None if new_value is None else str(new_value),
            absolute_change, percentage_change, _now(),
            json.dumps(evidence, ensure_ascii=False, default=str) if evidence is not None else None,
        ),
    )


def _upsert_product_dimension(conn: sqlite3.Connection, snap: sqlite3.Row, run_id: str, captured_at: str) -> None:
    existing = conn.execute("SELECT * FROM products WHERE canonical_product_key = ?", (snap["product_key"],)).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO products (
                canonical_product_key, product_id, channel, branch_id, sku,
                product_name_en, product_name_ar, normalized_name, category_id,
                category_name_en, category_name_ar, product_type, bundle_type_id,
                image_url, product_url, first_seen_run_id, first_seen_at,
                last_seen_run_id, last_seen_at, consecutive_missing_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ACTIVE')
            """,
            (
                snap["product_key"], snap["product_id"], snap["channel"], snap["branch_id"], snap["sku"],
                snap["product_name_en"], snap["product_name_ar"], snap["normalized_name"], snap["category_id"],
                snap["category_name_en"], snap["category_name_ar"], snap["product_type"], snap["bundle_type_id"],
                snap["image_url"], snap["product_url"], run_id, captured_at, run_id, captured_at,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE products SET
                product_name_en = ?, product_name_ar = ?, normalized_name = ?, category_id = ?,
                category_name_en = ?, category_name_ar = ?, product_type = ?, bundle_type_id = ?,
                image_url = ?, last_seen_run_id = ?, last_seen_at = ?,
                consecutive_missing_count = 0, updated_at = ?
            WHERE canonical_product_key = ?
            """,
            (
                snap["product_name_en"], snap["product_name_ar"], snap["normalized_name"], snap["category_id"],
                snap["category_name_en"], snap["category_name_ar"], snap["product_type"], snap["bundle_type_id"],
                snap["image_url"], run_id, captured_at, _now(), snap["product_key"],
            ),
        )


def _upsert_offer_dimension(conn: sqlite3.Connection, snap: sqlite3.Row, run_id: str, captured_at: str) -> None:
    existing = conn.execute("SELECT * FROM offers WHERE offer_key = ?", (snap["offer_key"],)).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO offers (
                offer_key, promo_id, product_key, channel, branch_id, offer_name,
                offer_type, bundle_type, first_seen_run_id, first_seen_at,
                last_seen_run_id, last_seen_at, consecutive_missing_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'ACTIVE')
            """,
            (
                snap["offer_key"], snap["promo_id"], snap["product_key"], snap["channel"], snap["branch_id"],
                snap["offer_name"], snap["offer_type"], snap["bundle_type"], run_id, captured_at, run_id, captured_at,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE offers SET
                offer_name = ?, offer_type = ?, bundle_type = ?,
                last_seen_run_id = ?, last_seen_at = ?, consecutive_missing_count = 0, updated_at = ?
            WHERE offer_key = ?
            """,
            (snap["offer_name"], snap["offer_type"], snap["bundle_type"], run_id, captured_at, _now(), snap["offer_key"]),
        )


def _product_ever_seen_in_other_channel(conn: sqlite3.Connection, branch_id: int, channel: str, product_id: Optional[str]) -> bool:
    if not product_id:
        return False
    other_channel = "DELIVERY" if channel == "PICKUP" else "PICKUP"
    row = conn.execute(
        "SELECT 1 FROM products WHERE branch_id = ? AND channel = ? AND product_id = ? LIMIT 1",
        (branch_id, other_channel, product_id),
    ).fetchone()
    return row is not None


def _known_product_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> dict[str, sqlite3.Row]:
    """Every product identity ever tracked for this channel+branch,
    REGARDLESS of current status - the basis for "missing" detection must
    be this full dimension-table set, not just the immediately-previous
    run's snapshot, or a product missing for its 2nd/3rd+ consecutive run
    would never be re-evaluated once it drops out of both runs being
    directly compared."""
    rows = conn.execute("SELECT * FROM products WHERE channel = ? AND branch_id = ?", (channel, branch_id)).fetchall()
    return {row["canonical_product_key"]: row for row in rows}


def _diff_products(conn: sqlite3.Connection, run_id: str, compared_run_id: Optional[str], channel: str, branch_id: int, current: dict[str, sqlite3.Row], previous: dict[str, sqlite3.Row]) -> dict[str, int]:
    counts = {"new_product": 0, "new_in_channel": 0, "price_increase": 0, "price_decrease": 0, "not_observed": 0, "removed": 0, "returned": 0, "details_changed": 0, "category_changed": 0, "availability_changed": 0}
    current_keys = set(current)
    known = _known_product_rows(conn, channel, branch_id)

    for key in current_keys:
        snap = current[key]
        existing = known.get(key)
        _upsert_product_dimension(conn, snap, run_id, snap["captured_at"])

        if existing is None:
            if _product_ever_seen_in_other_channel(conn, branch_id, channel, snap["product_id"]):
                conn.execute("UPDATE products SET status = 'ACTIVE' WHERE canonical_product_key = ?", (key,))
                _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_NEW_IN_CHANNEL, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=snap["product_name_en"])
                counts["new_in_channel"] += 1
            else:
                _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_NEW_PRODUCT, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=snap["product_name_en"])
                counts["new_product"] += 1
            continue

        if existing["status"] in (models.ENTITY_STATUS_NOT_OBSERVED, models.ENTITY_STATUS_REMOVED):
            conn.execute("UPDATE products SET status = 'RETURNED' WHERE canonical_product_key = ?", (key,))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_PRODUCT_RETURNED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=snap["product_name_en"], evidence={"was_missing_for_runs": existing["consecutive_missing_count"]})
            counts["returned"] += 1
            continue  # no meaningful "previous snapshot" to field-diff against for the run it returns on

        conn.execute("UPDATE products SET status = 'ACTIVE' WHERE canonical_product_key = ?", (key,))
        prev = previous.get(key)
        if prev is None:
            continue  # was ACTIVE in the dimension table but has no snapshot in the immediately-previous run (shouldn't normally happen) - nothing to diff
        cur = snap

        for field, event_up, event_down in (("regular_price", models.EVENT_PRICE_INCREASE, models.EVENT_PRICE_DECREASE),):
            old_v, new_v = prev[field], cur[field]
            if old_v is not None and new_v is not None and float(old_v) != float(new_v):
                abs_change = round(float(new_v) - float(old_v), 2)
                pct_change = round((abs_change / float(old_v)) * 100, 2) if float(old_v) != 0 else None
                event_type = event_up if abs_change > 0 else event_down
                _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=event_type, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name=field, old_value=old_v, new_value=new_v, absolute_change=abs_change, percentage_change=pct_change)
                _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_REGULAR_PRICE_CHANGED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name=field, old_value=old_v, new_value=new_v, absolute_change=abs_change, percentage_change=pct_change)
                counts["price_increase" if abs_change > 0 else "price_decrease"] += 1

        old_special, new_special = prev["special_price"], cur["special_price"]
        if (old_special is None) != (new_special is None) or (old_special is not None and new_special is not None and float(old_special) != float(new_special)):
            abs_change = round(float(new_special or 0) - float(old_special or 0), 2)
            pct_change = round((abs_change / float(old_special)) * 100, 2) if old_special else None
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_SPECIAL_PRICE_CHANGED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name="special_price", old_value=old_special, new_value=new_special, absolute_change=abs_change, percentage_change=pct_change)

        if int(prev["availability"]) != int(cur["availability"]):
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_AVAILABILITY_CHANGED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name="availability", old_value=bool(prev["availability"]), new_value=bool(cur["availability"]))
            counts["availability_changed"] += 1

        if (prev["category_id"] or "") != (cur["category_id"] or ""):
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_CATEGORY_CHANGED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name="category_name_en", old_value=prev["category_name_en"], new_value=cur["category_name_en"])
            counts["category_changed"] += 1

        detail_fields = ("description_en", "option_groups", "variants")
        changed_details = [f for f in detail_fields if (prev[f] or "") != (cur[f] or "")]
        if changed_details:
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_DETAILS_CHANGED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=cur["product_name_en"], field_name=",".join(changed_details), evidence={"changed_fields": changed_details})
            counts["details_changed"] += 1

    for key, row in known.items():
        if key in current_keys or row["status"] == models.ENTITY_STATUS_REMOVED:
            continue  # present this run, or already fully removed (no further NOT_OBSERVED/REMOVED spam once removed)
        new_count = row["consecutive_missing_count"] + 1
        conn.execute("UPDATE products SET consecutive_missing_count = ?, updated_at = ? WHERE canonical_product_key = ?", (new_count, _now(), key))
        if new_count >= REMOVED_THRESHOLD:
            conn.execute("UPDATE products SET status = ? WHERE canonical_product_key = ?", (models.ENTITY_STATUS_REMOVED, key))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_PRODUCT_REMOVED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=row["product_name_en"], evidence={"consecutive_missing_count": new_count})
            counts["removed"] += 1
        else:
            conn.execute("UPDATE products SET status = ? WHERE canonical_product_key = ?", (models.ENTITY_STATUS_NOT_OBSERVED, key))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_PRODUCT_NOT_OBSERVED, channel=channel, branch_id=branch_id, entity_type="product", entity_key=key, entity_name=row["product_name_en"], evidence={"consecutive_missing_count": new_count})
            counts["not_observed"] += 1

    return counts


def _known_offer_rows(conn: sqlite3.Connection, channel: str, branch_id: int) -> dict[str, sqlite3.Row]:
    """See _known_product_rows - same reasoning, same bug class, same fix."""
    rows = conn.execute("SELECT * FROM offers WHERE channel = ? AND branch_id = ?", (channel, branch_id)).fetchall()
    return {row["offer_key"]: row for row in rows}


def _diff_offers(conn: sqlite3.Connection, run_id: str, compared_run_id: Optional[str], channel: str, branch_id: int, current: dict[str, sqlite3.Row], previous: dict[str, sqlite3.Row]) -> dict[str, int]:
    counts = {"new_offer": 0, "changed": 0, "not_observed": 0, "ended": 0, "returned": 0}
    current_keys = set(current)
    known = _known_offer_rows(conn, channel, branch_id)

    for key in current_keys:
        snap = current[key]
        existing = known.get(key)
        _upsert_offer_dimension(conn, snap, run_id, snap["captured_at"])

        if existing is None:
            conn.execute("UPDATE offers SET status = 'ACTIVE' WHERE offer_key = ?", (key,))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_NEW_OFFER, channel=channel, branch_id=branch_id, entity_type="offer", entity_key=key, entity_name=snap["offer_name"])
            counts["new_offer"] += 1
            continue

        if existing["status"] in (models.ENTITY_STATUS_NOT_OBSERVED, models.ENTITY_STATUS_ENDED):
            conn.execute("UPDATE offers SET status = 'RETURNED' WHERE offer_key = ?", (key,))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_OFFER_RETURNED, channel=channel, branch_id=branch_id, entity_type="offer", entity_key=key, entity_name=snap["offer_name"], evidence={"was_missing_for_runs": existing["consecutive_missing_count"]})
            counts["returned"] += 1
            continue

        conn.execute("UPDATE offers SET status = 'ACTIVE' WHERE offer_key = ?", (key,))
        prev = previous.get(key)
        if prev is None:
            continue
        cur = snap
        changed_fields = []
        for field in ("included_items", "number_of_pieces", "sizes", "drinks", "sides", "sauces", "original_price", "offer_price", "discount_percentage", "offer_description"):
            if (prev[field] if prev[field] is not None else "") != (cur[field] if cur[field] is not None else ""):
                changed_fields.append(field)
        if changed_fields:
            _insert_event(
                conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_OFFER_CHANGED,
                channel=channel, branch_id=branch_id, entity_type="offer", entity_key=key, entity_name=cur["offer_name"],
                field_name=",".join(changed_fields),
                old_value={f: prev[f] for f in changed_fields}, new_value={f: cur[f] for f in changed_fields},
                evidence={"changed_fields": changed_fields},
            )
            counts["changed"] += 1

    for key, row in known.items():
        if key in current_keys or row["status"] == models.ENTITY_STATUS_ENDED:
            continue
        new_count = row["consecutive_missing_count"] + 1
        conn.execute("UPDATE offers SET consecutive_missing_count = ?, updated_at = ? WHERE offer_key = ?", (new_count, _now(), key))
        if new_count >= REMOVED_THRESHOLD:
            conn.execute("UPDATE offers SET status = ? WHERE offer_key = ?", (models.ENTITY_STATUS_ENDED, key))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_OFFER_ENDED, channel=channel, branch_id=branch_id, entity_type="offer", entity_key=key, entity_name=row["offer_name"], evidence={"consecutive_missing_count": new_count})
            counts["ended"] += 1
        else:
            conn.execute("UPDATE offers SET status = ? WHERE offer_key = ?", (models.ENTITY_STATUS_NOT_OBSERVED, key))
            _insert_event(conn, run_id=run_id, compared_run_id=compared_run_id, event_type=models.EVENT_OFFER_NOT_OBSERVED, channel=channel, branch_id=branch_id, entity_type="offer", entity_key=key, entity_name=row["offer_name"], evidence={"consecutive_missing_count": new_count})
            counts["not_observed"] += 1

    return counts


def run_change_detection(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    """Main entry point. Returns a summary dict of event counts. No-op
    (returns {"skipped": reason}) unless the given run is a SUCCESS run -
    see module docstring."""
    run = get_run(conn, run_id)
    if run is None:
        return {"skipped": f"run {run_id} not found"}
    if run["status"] != models.RUN_STATUS_SUCCESS:
        return {"skipped": f"run {run_id} has status {run['status']} - change detection only runs for SUCCESS runs"}

    channel = run["channel"]
    branch_id = run["branch_id"]
    previous_run = get_previous_successful_run(conn, channel, branch_id, run["started_at"], run_id)

    current_products = _product_rows(conn, run_id)
    current_offers = _offer_rows(conn, run_id)
    previous_products = _product_rows(conn, previous_run["run_id"]) if previous_run else {}
    previous_offers = _offer_rows(conn, previous_run["run_id"]) if previous_run else {}

    with conn:
        product_counts = _diff_products(conn, run_id, previous_run["run_id"] if previous_run else None, channel, branch_id, current_products, previous_products)
        offer_counts = _diff_offers(conn, run_id, previous_run["run_id"] if previous_run else None, channel, branch_id, current_offers, previous_offers)

        # Category dimension upsert (first_seen/last_seen tracking, informational).
        for cat_id, cat_name in {(r["category_id"], r["category_name_en"]) for r in current_products.values() if r["category_id"]}:
            existing = conn.execute("SELECT 1 FROM categories WHERE category_id = ? AND channel = ? AND branch_id = ?", (cat_id, channel, branch_id)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE categories SET name_en = ?, last_seen_run_id = ?, last_seen_at = ?, updated_at = ? WHERE category_id = ? AND channel = ? AND branch_id = ?",
                    (cat_name, run_id, run["finished_at"] or run["started_at"], _now(), cat_id, channel, branch_id),
                )
            else:
                conn.execute(
                    "INSERT INTO categories (category_id, channel, branch_id, name_en, first_seen_run_id, first_seen_at, last_seen_run_id, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (cat_id, channel, branch_id, cat_name, run_id, run["finished_at"] or run["started_at"], run_id, run["finished_at"] or run["started_at"]),
                )

    return {
        "previous_run_id": previous_run["run_id"] if previous_run else None,
        "products": product_counts,
        "offers": offer_counts,
    }
