"""
tests/test_change_detector.py
---------------------------------------------------------------------
Covers required tests #3-12 - the same engine and rules as
competitors/kfc/tests/test_change_detector.py:
  3. Pickup and Delivery never mix.
  4. New product detection.
  5. Price increase detection.
  6. Price decrease detection.
  7. New offer detection.
  8. Offer Not Observed.
  9. Offer Ended after three successful runs.
  10. Product Removed after three successful runs.
  11. Preventing Missing events from Partial runs.
  12. Product Returned.

Offer-side tests (#7-9) use the fixtures' "KING DAILY DEALS" products
(Cheeseburger Lovers / King Wrap Box) - see backend/offer_parser.py for
why that specific category is this brand's confirmed offer signal, and
why SPECIAL_PRICE_CHANGED/OFFER discount fields still never fire/populate
(no "before" price exists for this brand - see
test_special_price_change_never_fires_for_this_brand below).

Every test ingests fixture-derived channel results through
backend.run_service._ingest_channel() (the real ingestion code path, not a
reimplementation) against a temporary SQLite database - no network access.
---------------------------------------------------------------------
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from competitors.burger_king.backend import change_detector, models, run_service


def ingest(conn, tmp_path: Path, batch_id: str, channel: str, result: dict) -> dict:
    out_dir = tmp_path / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{channel}.json", "w", encoding="utf-8") as f:
        json.dump(result, f)
    return run_service._ingest_channel(conn, batch_id, channel, out_dir)


def bump_run(result: dict, started: str) -> dict:
    out = copy.deepcopy(result)
    out["startedAt"] = f"{started}T06:00:00.000Z"
    out["finishedAt"] = f"{started}T06:05:00.000Z"
    return out


# --- #3 Pickup and Delivery never mix --------------------------------------

def test_pickup_and_delivery_never_mix(conn, tmp_path, pickup_result, delivery_result):
    ingest(conn, tmp_path, "batch1", "PICKUP", bump_run(pickup_result, "2026-08-01"))
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    pickup_products = conn.execute("SELECT * FROM product_snapshots WHERE channel='PICKUP'").fetchall()
    delivery_products = conn.execute("SELECT * FROM product_snapshots WHERE channel='DELIVERY'").fetchall()
    assert len(pickup_products) > 0
    assert len(delivery_products) > 0

    pickup_keys = {r["product_key"] for r in pickup_products}
    delivery_keys = {r["product_key"] for r in delivery_products}
    # Canonical keys embed the channel, so a product common to both channels
    # never collides into a single row/key - see backend/normalizer.py.
    assert pickup_keys.isdisjoint(delivery_keys)

    assert all(r["channel"] == "PICKUP" for r in pickup_products)
    assert all(r["channel"] == "DELIVERY" for r in delivery_products)

    both = conn.execute("SELECT DISTINCT channel FROM product_snapshots").fetchall()
    assert {r["channel"] for r in both} == {"PICKUP", "DELIVERY"}


# --- #4 New product detection ------------------------------------------------

def test_new_product_detection(conn, tmp_path, delivery_result):
    result = ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    assert result["status"] == "SUCCESS"
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (result["run_id"],)).fetchall()
    new_product_events = [e for e in events if e["event_type"] == models.EVENT_NEW_PRODUCT]
    # First-ever successful run -> every product is NEW_PRODUCT.
    assert len(new_product_events) == len(delivery_result["products"])


# --- #5 / #6 Price increase / decrease detection -----------------------------

def test_price_increase_and_decrease_detection(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"][0]["__price"] = run2["products"][0]["__price"] + 5  # increase
    run2["products"][1]["__price"] = run2["products"][1]["__price"] - 2  # decrease
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (result2["run_id"],)).fetchall()
    increases = [e for e in events if e["event_type"] == models.EVENT_PRICE_INCREASE]
    decreases = [e for e in events if e["event_type"] == models.EVENT_PRICE_DECREASE]
    assert len(increases) == 1
    assert len(decreases) == 1
    inc = increases[0]
    assert float(inc["absolute_change"]) == 5.0
    assert inc["old_value"] is not None and inc["new_value"] is not None
    assert float(inc["new_value"]) - float(inc["old_value"]) == 5.0
    # REGULAR_PRICE_CHANGED must also fire alongside PRICE_INCREASE/DECREASE (spec).
    regular_changed = [e for e in events if e["event_type"] == models.EVENT_REGULAR_PRICE_CHANGED]
    assert len(regular_changed) == 2


def test_price_change_of_one_sar_is_never_dropped(conn, tmp_path, delivery_result):
    """Spec: 'Any genuine price difference must appear, even if the change
    is only one SAR.'"""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"][0]["__price"] = run2["products"][0]["__price"] + 1
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_PRICE_INCREASE)).fetchall()
    assert len(events) == 1
    assert float(events[0]["absolute_change"]) == 1.0


def test_special_price_change_never_fires_for_this_brand(conn, tmp_path, delivery_result):
    """KNOWN LIMITATION (see backend/normalizer.py): special_price is always
    None for Burger King - SPECIAL_PRICE_CHANGED must never fire, since
    None == None on both sides of every comparison."""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(delivery_result, "2026-08-02"))
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_SPECIAL_PRICE_CHANGED)).fetchall()
    assert len(events) == 0


# --- #7 New offer detection --------------------------------------------------

def test_new_offer_detection_for_king_daily_deals_product(conn, tmp_path, delivery_result):
    result = ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result["run_id"], models.EVENT_NEW_OFFER)).fetchall()
    # Fixture has 2 KING DAILY DEALS products (Cheeseburger Lovers, King Wrap Box).
    assert len(events) == 2
    names = {e["entity_name"] for e in events}
    assert names == {"CHEESEBURGER LOVERS", "KING WRAP BOX"}


def test_offer_price_change_is_tracked_via_offer_price_field(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    target = next(p for p in run2["products"] if p["_id"] == "b10d5e39-7a05-4207-b078-dd1ea35e0c08")  # Cheeseburger Lovers
    target["__price"] = target["__price"] + 5
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_OFFER_CHANGED)).fetchall()
    assert len(events) == 1
    assert "offer_price" in events[0]["field_name"]


# --- #8 Offer Not Observed ----------------------------------------------------

def test_offer_not_observed_on_first_absence(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"] = [p for p in run2["products"] if p["name"]["locale"] != "CHEESEBURGER LOVERS"]
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_OFFER_NOT_OBSERVED)).fetchall()
    assert len(events) == 1
    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'CHEESEBURGER LOVERS'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_NOT_OBSERVED
    assert offer_row["consecutive_missing_count"] == 1


# --- #9 Offer Ended after three successful runs ------------------------------

def test_offer_ended_after_three_consecutive_successful_runs(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    without_offer = copy.deepcopy(delivery_result)
    without_offer["products"] = [p for p in without_offer["products"] if p["name"]["locale"] != "CHEESEBURGER LOVERS"]

    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_offer, "2026-08-02"))
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(without_offer, "2026-08-03"))
    r4 = ingest(conn, tmp_path, "batch4", "DELIVERY", bump_run(without_offer, "2026-08-04"))

    def events_of(run_id, event_type):
        return conn.execute("SELECT * FROM change_events WHERE run_id=? AND event_type=?", (run_id, event_type)).fetchall()

    assert len(events_of(r2["run_id"], models.EVENT_OFFER_NOT_OBSERVED)) == 1
    assert len(events_of(r3["run_id"], models.EVENT_OFFER_NOT_OBSERVED)) == 1  # spec: "Missing in two consecutive... Remain PRODUCT_NOT_OBSERVED"
    assert len(events_of(r4["run_id"], models.EVENT_OFFER_ENDED)) == 1  # third consecutive miss -> ENDED

    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'CHEESEBURGER LOVERS'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_ENDED
    assert offer_row["consecutive_missing_count"] == 3


def test_offer_ended_only_fires_once_not_every_subsequent_run(conn, tmp_path, delivery_result):
    without_offer = copy.deepcopy(delivery_result)
    without_offer["products"] = [p for p in without_offer["products"] if p["name"]["locale"] != "CHEESEBURGER LOVERS"]
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    for i, d in enumerate(["2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"], start=2):
        ingest(conn, tmp_path, f"batch{i}", "DELIVERY", bump_run(without_offer, d))
    ended_events = conn.execute("SELECT * FROM change_events WHERE event_type = ?", (models.EVENT_OFFER_ENDED,)).fetchall()
    assert len(ended_events) == 1  # not re-emitted on every run after it's already ENDED


def test_offer_returned_cancels_the_ended_progression(conn, tmp_path, delivery_result):
    """Spec: 'If the offer returns before three successful runs, cancel the
    ended-offer progression and record that it returned.'"""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    without_offer = copy.deepcopy(delivery_result)
    without_offer["products"] = [p for p in without_offer["products"] if p["name"]["locale"] != "CHEESEBURGER LOVERS"]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_offer, "2026-08-02"))  # miss 1
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # returns before miss 3

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (r3["run_id"], models.EVENT_OFFER_RETURNED)).fetchall()
    assert len(events) == 1
    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'CHEESEBURGER LOVERS'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_RETURNED
    ended_events = conn.execute("SELECT * FROM change_events WHERE event_type = ?", (models.EVENT_OFFER_ENDED,)).fetchall()
    assert len(ended_events) == 0  # never reached ENDED


# --- #10 Product Removed after three successful runs ------------------------

def test_product_removed_after_three_consecutive_successful_runs(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    target_name = delivery_result["products"][-1]["name"]["locale"]

    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["locale"] != target_name]

    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_product, "2026-08-02"))
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(without_product, "2026-08-03"))
    r4 = ingest(conn, tmp_path, "batch4", "DELIVERY", bump_run(without_product, "2026-08-04"))

    def events_of(run_id, event_type):
        return conn.execute("SELECT * FROM change_events WHERE run_id=? AND event_type=?", (run_id, event_type)).fetchall()

    assert len(events_of(r2["run_id"], models.EVENT_PRODUCT_NOT_OBSERVED)) == 1
    assert len(events_of(r3["run_id"], models.EVENT_PRODUCT_NOT_OBSERVED)) == 1
    assert len(events_of(r4["run_id"], models.EVENT_PRODUCT_REMOVED)) == 1

    row = conn.execute("SELECT * FROM products WHERE product_name_en = ?", (target_name,)).fetchone()
    assert row["status"] == models.ENTITY_STATUS_REMOVED
    assert row["consecutive_missing_count"] == 3


# --- #11 Preventing Missing events from Partial runs -------------------------

def test_partial_run_never_generates_not_observed_or_removed_events(conn, tmp_path, delivery_result, partial_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    # partial_result is missing the KING SAVERS category's product because
    # that category failed to load - overall status PARTIAL - change
    # detection must skip it entirely, not treat the missing product as
    # newly-absent.
    assert partial_result["status"] == "PARTIAL"
    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(partial_result, "2026-08-02"))
    assert r2["status"] == "PARTIAL"
    assert r2["change_summary"] == {"skipped": "not a SUCCESS run"}

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (r2["run_id"],)).fetchall()
    assert len(events) == 0

    rows = conn.execute("SELECT * FROM products WHERE channel='DELIVERY'").fetchall()
    assert all(r["consecutive_missing_count"] == 0 for r in rows)

    # A SUBSEQUENT successful run must compare against batch1 (the last
    # SUCCESS run), not against the skipped PARTIAL run.
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))
    assert r3["change_summary"]["previous_run_id"] == "batch1-DELIVERY"
    events3 = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (r3["run_id"],)).fetchall()
    assert not any(e["event_type"] in (models.EVENT_PRODUCT_NOT_OBSERVED, models.EVENT_PRODUCT_REMOVED, models.EVENT_NEW_PRODUCT) for e in events3)


def test_failed_run_never_generates_change_events(conn, tmp_path, delivery_result, failed_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    failed_result = copy.deepcopy(failed_result)
    failed_result["channel"] = "DELIVERY"
    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(failed_result, "2026-08-02"))
    assert r2["status"] == "FAILED"
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (r2["run_id"],)).fetchall()
    assert len(events) == 0


# --- #12 Product Returned -----------------------------------------------------

def test_product_returned_after_absence(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    target_name = delivery_result["products"][-1]["name"]["locale"]
    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["locale"] != target_name]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_product, "2026-08-02"))
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # product is back

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (r3["run_id"], models.EVENT_PRODUCT_RETURNED)).fetchall()
    assert len(events) == 1
    row = conn.execute("SELECT * FROM products WHERE product_name_en = ?", (target_name,)).fetchone()
    assert row["status"] == models.ENTITY_STATUS_RETURNED
    assert row["consecutive_missing_count"] == 0  # reset on return


def test_product_returned_cancels_the_removed_progression(conn, tmp_path, delivery_result):
    """Spec: 'If the offer returns before three successful runs, cancel the
    ended-offer progression and record that it returned.' - same rule for
    products."""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    target_name = delivery_result["products"][-1]["name"]["locale"]
    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["locale"] != target_name]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_product, "2026-08-02"))  # miss 1
    ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # returns before miss 3

    row = conn.execute("SELECT * FROM products WHERE product_name_en = ?", (target_name,)).fetchone()
    assert row["status"] == models.ENTITY_STATUS_RETURNED
    removed_events = conn.execute("SELECT * FROM change_events WHERE event_type = ?", (models.EVENT_PRODUCT_REMOVED,)).fetchall()
    assert len(removed_events) == 0  # never reached REMOVED
