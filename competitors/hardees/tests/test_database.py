"""
competitors/hardees/tests/test_database.py
Covers required test #14: Database migrations.
"""
from __future__ import annotations

from competitors.hardees.backend import database


def test_init_db_creates_all_expected_tables(db_path):
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "branches", "crawl_runs", "categories", "products", "product_snapshots",
        "product_options", "offers", "offer_snapshots", "change_events",
        "screenshots", "api_endpoints", "schema_migrations",
    }
    assert expected.issubset(tables)


def test_migrations_are_idempotent(db_path):
    """Running init_db() twice must not error or duplicate migration rows -
    this is what makes it safe to call at the top of every entrypoint
    (run_collector.py, scheduler.py, app.py) without a special first-run
    step."""
    database.init_db(db_path)
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    versions = [r[0] for r in rows]
    assert versions == sorted(set(versions))  # no duplicates
    assert versions == [v for v, _, _ in database.MIGRATIONS]


def test_crawl_runs_status_check_constraint_rejects_invalid_status(db_path):
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        import sqlite3
        with pytest_raises_sqlite_integrity_or_operational_error():
            conn.execute(
                "INSERT INTO crawl_runs (run_id, started_at, channel, branch_id, status) VALUES (?, ?, ?, ?, ?)",
                ("bad-run", "2026-08-01T00:00:00Z", "PICKUP", 24, "NOT_A_REAL_STATUS"),
            )


class pytest_raises_sqlite_integrity_or_operational_error:
    """Small local context manager (avoids importing pytest just for this
    one assertion) - sqlite3 raises IntegrityError for CHECK constraint
    violations."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import sqlite3
        assert exc_type is not None and issubclass(exc_type, sqlite3.IntegrityError), (
            f"expected sqlite3.IntegrityError, got {exc_type}"
        )
        return True


def test_upsert_branch_is_idempotent(db_path):
    database.init_db(db_path)
    with database.get_connection(db_path) as conn:
        database.upsert_branch(conn, 24, "Riyadh", "EUROMARCHE-H", 24.6866, 46.7240)
        database.upsert_branch(conn, 24, "Riyadh", "EUROMARCHE-H", 24.6866, 46.7240)
        rows = conn.execute("SELECT * FROM branches WHERE store_id = 24").fetchall()
    assert len(rows) == 1
    assert rows[0]["branch_name"] == "EUROMARCHE-H"
