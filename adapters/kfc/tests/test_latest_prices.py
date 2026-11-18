import sqlite3

import pytest

from adapters.kfc import KfcAdapter
from adapters.kfc.tests.seed import seed_kfc_db, _run, _snapshot


@pytest.fixture()
def adapter(tmp_path):
    path = tmp_path / "kfc.db"
    seed_kfc_db(path)
    return KfcAdapter(db_path=path)


def snapshot(db, run, price, captured="2026-09-07T06:00:00Z"):
    _snapshot(db, run_id=run, key="143|PICKUP|id:100", product_id="100", channel="PICKUP",
              captured=captured, name="Spicy Bites", category="Chicken", regular=price,
              special=None, sizes="[]")


def test_previous_price_skips_missing_runs_and_failed_or_partial_observations(adapter):
    with sqlite3.connect(adapter.db_path) as db:
        _run(db, "middle-empty", "PICKUP", "2026-09-04T06:00:00Z", "SUCCESS", 0)
        for status in ("FAILED", "PARTIAL"):
            _run(db, status, "PICKUP", "2026-09-07T06:00:00Z", status, 1)
            snapshot(db, status, 999)
        # Imported later, but chronologically older than the previous reading.
        _run(db, "backfill", "PICKUP", "2026-08-01T06:00:00Z", "SUCCESS", 1)
        snapshot(db, "backfill", 100, captured="2026-08-01T06:00:00Z")
    product, = adapter.list_products(channel="pickup")
    assert product.regular_price == 19
    assert product.previous_regular_price == 21
    delivery, = adapter.list_products(channel="delivery")
    assert delivery.regular_price is None
    assert delivery.previous_regular_price is None


@pytest.mark.parametrize("previous", [None, 0, 12.5])
def test_previous_price_preserves_null_and_zero(adapter, previous):
    with sqlite3.connect(adapter.db_path) as db:
        db.execute("UPDATE product_snapshots SET regular_price=?, special_price=? WHERE run_id='run-old-p'",
                   (previous, previous))
    product, = adapter.list_products(channel="pickup")
    assert product.previous_regular_price == previous
    assert product.previous_special_price == previous


def test_equal_run_times_use_a_stable_observation_order(adapter):
    with sqlite3.connect(adapter.db_path) as db:
        _run(db, "same-time", "PICKUP", "2026-09-08T06:00:00Z", "SUCCESS", 1)
        snapshot(db, "same-time", 25)
    product, = adapter.list_products(channel="pickup")
    assert product.regular_price == 25
    assert product.previous_regular_price == 19
    assert len(adapter.get_product_history(product.id).observations) == 3
