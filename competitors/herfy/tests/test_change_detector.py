"""
tests/test_change_detector.py
---------------------------------------------------------------------
Covers required tests #3-12 - the same engine and rules as every other
competitor's test_change_detector.py:
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

Offer-side tests (#7-9) use the fixtures' "Offers"-category product
("Double Offer") - see backend/offer_parser.py for why that category is
this brand's confirmed offer signal (alongside a real price discount and
the has-timed-event flag, neither of which the fixtures currently trigger).

Every test ingests fixture-derived channel results through
backend.run_service._ingest_channel() (the real ingestion code path, not a
reimplementation) against a temporary SQLite database - no network access.
---------------------------------------------------------------------
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from competitors.herfy.backend import models, run_service


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
    assert len(new_product_events) == len(delivery_result["products"])


# --- #5 / #6 Price increase / decrease detection -----------------------------

def test_price_increase_and_decrease_detection(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"][0]["price"] = run2["products"][0]["price"] + 5  # increase
    run2["products"][0]["original-price"] = run2["products"][0]["price"]
    run2["products"][1]["price"] = run2["products"][1]["price"] - 2  # decrease
    run2["products"][1]["original-price"] = run2["products"][1]["price"]
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (result2["run_id"],)).fetchall()
    increases = [e for e in events if e["event_type"] == models.EVENT_PRICE_INCREASE]
    decreases = [e for e in events if e["event_type"] == models.EVENT_PRICE_DECREASE]
    assert len(increases) == 1
    assert len(decreases) == 1
    inc = increases[0]
    assert float(inc["absolute_change"]) == 5.0
    regular_changed = [e for e in events if e["event_type"] == models.EVENT_REGULAR_PRICE_CHANGED]
    assert len(regular_changed) == 2


def test_price_change_of_one_sar_is_never_dropped(conn, tmp_path, delivery_result):
    """Spec: 'Any genuine price difference must appear, even if the change
    is only one SAR.'"""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"][0]["price"] = run2["products"][0]["price"] + 1
    run2["products"][0]["original-price"] = run2["products"][0]["price"]
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_PRICE_INCREASE)).fetchall()
    assert len(events) == 1
    assert float(events[0]["absolute_change"]) == 1.0


def test_special_price_change_fires_when_a_real_discount_appears(conn, tmp_path, delivery_result):
    """Unlike Burger King, Herfy's special_price CAN populate - see
    normalizer.py's price/original-price discount logic - and
    SPECIAL_PRICE_CHANGED must fire the moment one appears."""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    target = run2["products"][0]
    target["original-price"] = target["price"]
    target["price"] = target["price"] - 3  # a genuine discount appears
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_SPECIAL_PRICE_CHANGED)).fetchall()
    assert len(events) == 1


# --- #7 New offer detection --------------------------------------------------

def test_new_offer_detection_for_offers_category_product(conn, tmp_path, delivery_result):
    result = ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result["run_id"], models.EVENT_NEW_OFFER)).fetchall()
    # Fixture has 2 "Offers"-category products (Double Offer, Offer you'll love).
    assert len(events) == 2
    names = {e["entity_name"] for e in events}
    assert names == {"Double Offer", "Offer you'll love"}


def test_offer_price_change_is_tracked_via_offer_price_field(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    target = next(p for p in run2["products"] if p["id"] == 2971976)  # Double Offer
    target["price"] = target["price"] + 2
    target["original-price"] = target["price"]
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)
    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_OFFER_CHANGED)).fetchall()
    assert len(events) == 1
    assert "offer_price" in events[0]["field_name"]


# --- #8 Offer Not Observed ----------------------------------------------------

def test_offer_not_observed_on_first_absence(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    run2 = bump_run(delivery_result, "2026-08-02")
    run2["products"] = [p for p in run2["products"] if p["name"]["en-us"] != "Double Offer"]
    result2 = ingest(conn, tmp_path, "batch2", "DELIVERY", run2)

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (result2["run_id"], models.EVENT_OFFER_NOT_OBSERVED)).fetchall()
    assert len(events) == 1
    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'Double Offer'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_NOT_OBSERVED
    assert offer_row["consecutive_missing_count"] == 1


# --- #9 Offer Ended after three successful runs ------------------------------

def test_offer_ended_after_three_consecutive_successful_runs(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))

    without_offer = copy.deepcopy(delivery_result)
    without_offer["products"] = [p for p in without_offer["products"] if p["name"]["en-us"] != "Double Offer"]

    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_offer, "2026-08-02"))
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(without_offer, "2026-08-03"))
    r4 = ingest(conn, tmp_path, "batch4", "DELIVERY", bump_run(without_offer, "2026-08-04"))

    def events_of(run_id, event_type):
        return conn.execute("SELECT * FROM change_events WHERE run_id=? AND event_type=?", (run_id, event_type)).fetchall()

    assert len(events_of(r2["run_id"], models.EVENT_OFFER_NOT_OBSERVED)) == 1
    assert len(events_of(r3["run_id"], models.EVENT_OFFER_NOT_OBSERVED)) == 1
    assert len(events_of(r4["run_id"], models.EVENT_OFFER_ENDED)) == 1

    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'Double Offer'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_ENDED
    assert offer_row["consecutive_missing_count"] == 3


def test_offer_returned_cancels_the_ended_progression(conn, tmp_path, delivery_result):
    """Spec: 'If the offer returns before three successful runs, cancel the
    ended-offer progression and record that it returned.'"""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    without_offer = copy.deepcopy(delivery_result)
    without_offer["products"] = [p for p in without_offer["products"] if p["name"]["en-us"] != "Double Offer"]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_offer, "2026-08-02"))  # miss 1
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # returns before miss 3

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (r3["run_id"], models.EVENT_OFFER_RETURNED)).fetchall()
    assert len(events) == 1
    offer_row = conn.execute("SELECT * FROM offers WHERE offer_name = 'Double Offer'").fetchone()
    assert offer_row["status"] == models.ENTITY_STATUS_RETURNED
    ended_events = conn.execute("SELECT * FROM change_events WHERE event_type = ?", (models.EVENT_OFFER_ENDED,)).fetchall()
    assert len(ended_events) == 0


# --- #10 Product Removed after three successful runs ------------------------

def test_product_removed_after_three_consecutive_successful_runs(conn, tmp_path, delivery_result):
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    target_name = delivery_result["products"][-1]["name"]["en-us"]

    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["en-us"] != target_name]

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

    # partial_result is missing the "Side Orders" category's product
    # because that category failed to load - overall status PARTIAL -
    # change detection must skip it entirely, not treat the missing
    # product as newly-absent.
    assert partial_result["status"] == "PARTIAL"
    r2 = ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(partial_result, "2026-08-02"))
    assert r2["status"] == "PARTIAL"
    assert r2["change_summary"] == {"skipped": "not a SUCCESS run"}

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ?", (r2["run_id"],)).fetchall()
    assert len(events) == 0

    rows = conn.execute("SELECT * FROM products WHERE channel='DELIVERY'").fetchall()
    assert all(r["consecutive_missing_count"] == 0 for r in rows)

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
    target_name = delivery_result["products"][-1]["name"]["en-us"]
    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["en-us"] != target_name]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_product, "2026-08-02"))
    r3 = ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # product is back

    events = conn.execute("SELECT * FROM change_events WHERE run_id = ? AND event_type = ?", (r3["run_id"], models.EVENT_PRODUCT_RETURNED)).fetchall()
    assert len(events) == 1
    row = conn.execute("SELECT * FROM products WHERE product_name_en = ?", (target_name,)).fetchone()
    assert row["status"] == models.ENTITY_STATUS_RETURNED
    assert row["consecutive_missing_count"] == 0


def test_product_returned_cancels_the_removed_progression(conn, tmp_path, delivery_result):
    """Spec: 'If the offer returns before three successful runs, cancel the
    ended-offer progression and record that it returned.' - same rule for
    products."""
    ingest(conn, tmp_path, "batch1", "DELIVERY", bump_run(delivery_result, "2026-08-01"))
    target_name = delivery_result["products"][-1]["name"]["en-us"]
    without_product = copy.deepcopy(delivery_result)
    without_product["products"] = [p for p in without_product["products"] if p["name"]["en-us"] != target_name]

    ingest(conn, tmp_path, "batch2", "DELIVERY", bump_run(without_product, "2026-08-02"))  # miss 1
    ingest(conn, tmp_path, "batch3", "DELIVERY", bump_run(delivery_result, "2026-08-03"))  # returns before miss 3

    row = conn.execute("SELECT * FROM products WHERE product_name_en = ?", (target_name,)).fetchone()
    assert row["status"] == models.ENTITY_STATUS_RETURNED
    removed_events = conn.execute("SELECT * FROM change_events WHERE event_type = ?", (models.EVENT_PRODUCT_REMOVED,)).fetchall()
    assert len(removed_events) == 0
