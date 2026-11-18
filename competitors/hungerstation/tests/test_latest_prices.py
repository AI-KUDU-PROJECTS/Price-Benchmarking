from competitors.hungerstation import database


def save(path, run, date, price, *, source="meal", brand="kfc", special=None):
    database.save_success(
        run_id=run, batch_id=None, brand_id=brand, restaurant_name=brand,
        started_at=date, finished_at=date, raw_capture_path=None, path=path,
        items=[{"source_product_id": source, "name_en": source, "regular_price": price,
                "special_price": special, "effective_price": special if special is not None else price,
                "availability": 1}],
    )


def test_previous_prices_and_seen_dates_ignore_failed_runs_and_other_brands(tmp_path):
    path = tmp_path / "hs.db"
    save(path, "old", "2026-09-01T10:00:00Z", 20)
    save(path, "missing", "2026-09-02T10:00:00Z", 8, source="other")
    save(path, "failed", "2026-09-03T10:00:00Z", 999)
    save(path, "foreign", "2026-09-03T12:00:00Z", 888, brand="herfy")
    save(path, "current", "2026-09-04T10:00:00Z", 25, special=0)
    # Insert a backfill last to verify ordering by run time, not insertion time.
    save(path, "backfill", "2026-08-01T10:00:00Z", 15)
    with database.connection(path) as db:
        db.execute("UPDATE runs SET status='FAILED' WHERE run_id='failed'")
    with database.readonly_connection(path) as db:
        row, = database.latest_products(db, "kfc")
        assert row["regular_price"] == 25
        assert row["special_price"] == row["effective_price"] == 0
        assert row["previous_regular_price"] == 20
        assert row["previous_special_price"] is None
        assert row["previous_run_id"] == "old"
        assert row["first_seen_at"] == "2026-08-01T10:00:00Z"
        assert row["last_seen_at"] == "2026-09-04T10:00:00Z"
        assert len(database.observations(db, "kfc", "meal")) == 3


def test_new_product_and_null_previous_prices(tmp_path):
    path = tmp_path / "hs.db"
    save(path, "first", "2026-09-01T10:00:00Z", None)
    with database.readonly_connection(path) as db:
        row, = database.latest_products(db, "kfc")
        assert row["previous_run_id"] is None
        assert row["previous_regular_price"] is None
    save(path, "second", "2026-09-02T10:00:00Z", 0)
    with database.readonly_connection(path) as db:
        row, = database.latest_products(db, "kfc")
        assert row["previous_run_id"] == "first"
        assert row["previous_regular_price"] is None
        assert row["regular_price"] == 0


def test_equal_times_have_a_deterministic_previous_observation(tmp_path):
    path = tmp_path / "hs.db"
    save(path, "first", "2026-09-01T10:00:00Z", 20)
    save(path, "second", "2026-09-01T10:00:00Z", 22)
    with database.readonly_connection(path) as db:
        row, = database.latest_products(db, "kfc")
        assert row["run_id"] == "second"
        assert row["previous_run_id"] == "first"
        assert row["previous_regular_price"] == 20
