from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
import sqlite3

import pytest
from fastapi.testclient import TestClient

from adapters.kfc import KfcAdapter
from adapters.kfc.tests.seed import seed_kfc_db, _snapshot
from bff.app import app
from bff.read_cache import ReadCache, cached_read
from bff.registry import configure_adapters_for_test


def test_expiry_versions_and_mutation_are_isolated():
    now = [0.0]
    version = [1]
    calls = []
    cache = ReadCache(ttl=30, clock=lambda: now[0])

    def read():
        calls.append(True)
        return {"prices": [len(calls)]}

    first = cache.get("menu", lambda: version[0], read)
    first["prices"][0] = 999
    assert cache.get("menu", lambda: version[0], read) == {"prices": [1]}
    version[0] = 2
    assert cache.get("menu", lambda: version[0], read) == {"prices": [2]}
    now[0] = 30
    assert cache.get("menu", lambda: version[0], read) == {"prices": [3]}


def test_changed_during_load_and_failures_are_not_cached():
    version = [1]
    cache = ReadCache()
    calls = []

    def changed():
        calls.append(True)
        version[0] += 1
        return len(calls)

    assert cache.get("menu", lambda: version[0], changed) == 1
    assert cache.get("menu", lambda: version[0], changed) == 2
    assert cache.get("menu", lambda: version[0], lambda: 3) == 3
    version[0] += 1
    with pytest.raises(ValueError):
        cache.get("menu", lambda: version[0], lambda: (_ for _ in ()).throw(ValueError()))
    assert cache.get("menu", lambda: version[0], lambda: 4) == 4


def test_bounded_cache_evicts_least_recently_used_filters():
    cache = ReadCache(max_entries=2)
    for key in ("a", "b"):
        cache.get(key, lambda: 1, lambda k=key: k)
    assert cache.get("a", lambda: 1, lambda: "unexpected") == "a"
    cache.get("c", lambda: 1, lambda: "c")
    assert cache.get("b", lambda: 1, lambda: "reloaded") == "reloaded"


def test_concurrent_cold_requests_only_load_once():
    cache = ReadCache()
    barrier = Barrier(6)
    entered, release = Event(), Event()
    calls = []

    def load():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return [1]

    def request():
        barrier.wait(timeout=5)
        return cache.get("menu", lambda: 1, load)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(request) for _ in range(6)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert calls == [True]
    assert results == [[1]] * 6
    assert len({id(result) for result in results}) == 6


def test_wal_commit_invalidates_without_main_database_change(tmp_path):
    path = tmp_path / "data.db"
    adapter = SimpleNamespace(db_path=path, brand_id="test")
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE prices (value REAL)")
        writer.execute("INSERT INTO prices VALUES (20)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = path.stat().st_mtime_ns

        def read():
            return writer.execute("SELECT value FROM prices").fetchone()[0]

        assert cached_read(adapter, ("menu",), read) == 20
        writer.execute("UPDATE prices SET value=22")
        writer.commit()
        assert path.stat().st_mtime_ns == before
        assert cached_read(adapter, ("menu",), read) == 22
    writer.close()


def test_json_and_overlay_base_changes_invalidate(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text("20")
    base = SimpleNamespace(catalog_path=catalog, brand_id="test")
    overlay = SimpleNamespace(db_path=tmp_path / "hs.db", base=base, brand_id="test")
    read = lambda: catalog.read_text()
    assert cached_read(overlay, ("menu",), read) == "20"
    replacement = tmp_path / "new.json"
    replacement.write_text("22")
    replacement.replace(catalog)
    assert cached_read(overlay, ("menu",), read) == "22"


@pytest.fixture()
def menu_client(tmp_path):
    path = tmp_path / "kfc.db"
    seed_kfc_db(path)
    adapter = KfcAdapter(db_path=path)
    configure_adapters_for_test({"kfc": adapter})
    try:
        yield TestClient(app), path, adapter
    finally:
        configure_adapters_for_test(None)


def test_menu_cache_preserves_filters_pages_and_refreshes_on_write(menu_client, monkeypatch):
    client, path, adapter = menu_client
    with sqlite3.connect(path) as db:
        _snapshot(db, run_id="run-new-p", key="143|PICKUP|id:200", product_id="200",
                  channel="PICKUP", captured="2026-09-08T06:00:00Z", name="Mystery Item",
                  category="Other", regular=10, special=None, sizes="[]")
    original = adapter.list_products
    calls = []

    def counted(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(adapter, "list_products", counted)
    url = "/api/v1/brands/kfc/menu"
    first = client.get(url, params={"page_size": 1}).json()
    count = len(calls)
    second = client.get(url, params={"page_size": 1, "page": 2}).json()
    assert len(calls) == count
    assert first["items"][0]["id"] != second["items"][0]["id"]
    pickup = client.get(url, params={"channel": "pickup"}).json()
    assert all(list(row["channels"]) == ["pickup"] for row in pickup["items"])
    assert client.get(url, params={"q": "not a product"}).json()["items"] == []
    assert client.get(url).json()["items"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE product_snapshots SET regular_price=23 WHERE run_id='run-new-p'")
    refreshed = client.get(url, params={"channel": "pickup"}).json()
    assert refreshed["items"][0]["channels"]["pickup"]["regularPrice"] == 23


def test_overview_cache_is_shared_and_invalidates(menu_client, monkeypatch):
    client, path, adapter = menu_client
    original = adapter.get_overview
    calls = []

    def counted():
        calls.append(True)
        return original()

    monkeypatch.setattr(adapter, "get_overview", counted)
    client.get("/api/v1/brands/kfc/overview").raise_for_status()
    client.get("/api/v1/market/overview").raise_for_status()
    assert len(calls) == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE product_snapshots SET regular_price=24 WHERE run_id='run-new-p'")
    client.get("/api/v1/market/overview").raise_for_status()
    assert len(calls) == 2


def test_warm_cache_still_requires_authentication(menu_client, monkeypatch):
    # Authentication is optional in older deployments of this repository.
    auth = pytest.importorskip("bff.auth")
    client, _, _ = menu_client
    previous = app.dependency_overrides.get(auth.require_user)
    app.dependency_overrides[auth.require_user] = lambda: {"user": {"id": "test"}}
    try:
        assert client.get("/api/v1/brands/kfc/menu").status_code == 200
        app.dependency_overrides.pop(auth.require_user, None)
        monkeypatch.setattr(auth, "settings", lambda: SimpleNamespace())
        monkeypatch.setattr(auth, "current_session", lambda *_: None)
        assert client.get("/api/v1/brands/kfc/menu").status_code == 401
        assert client.get("/api/v1/data-version").status_code == 401
    finally:
        if previous is None:
            app.dependency_overrides.pop(auth.require_user, None)
        else:
            app.dependency_overrides[auth.require_user] = previous


def test_browser_version_changes_with_database_wal_and_json(tmp_path):
    from bff.read_cache import data_version
    path = tmp_path / "prices.db"
    catalog = tmp_path / "catalog.json"
    catalog.write_text("20")
    adapter = SimpleNamespace(db_path=path, base=SimpleNamespace(catalog_path=catalog))
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE prices (value REAL)")
        writer.execute("INSERT INTO prices VALUES (20)")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        first = data_version({"test": adapter})
        assert first == data_version({"test": adapter})
        before = path.stat().st_mtime_ns
        writer.execute("UPDATE prices SET value=25")
        writer.commit()
        assert path.stat().st_mtime_ns == before
        second = data_version({"test": adapter})
        assert second != first
        replacement = tmp_path / "replacement.json"
        replacement.write_text("25")
        replacement.replace(catalog)
        assert data_version({"test": adapter}) != second
    writer.close()
    assert data_version({"custom": object()}) is None


def test_version_endpoint_and_response_headers_follow_new_prices(menu_client):
    client, path, _ = menu_client
    first = client.get("/api/v1/data-version")
    assert first.status_code == 200
    version = first.json()["version"]
    assert first.headers["cache-control"] == "no-store"
    menu = client.get("/api/v1/brands/kfc/menu")
    assert menu.headers["x-data-version"] == version
    with sqlite3.connect(path) as db:
        db.execute("UPDATE product_snapshots SET regular_price=25 WHERE run_id='run-new-p'")
    new_version = client.get("/api/v1/data-version").json()["version"]
    assert new_version != version
    assert client.get("/api/v1/brands/kfc/menu").headers["x-data-version"] == new_version


def test_commit_during_read_is_retried_instead_of_tagging_old_data(menu_client, monkeypatch):
    client, path, adapter = menu_client
    original = adapter.list_products
    changed = False

    def read_then_commit(**kwargs):
        nonlocal changed
        result = original(**kwargs)
        if not changed:
            changed = True
            with sqlite3.connect(path) as db:
                db.execute("UPDATE product_snapshots SET regular_price=27 WHERE run_id='run-new-p'")
        return result

    monkeypatch.setattr(adapter, "list_products", read_then_commit)
    url = "/api/v1/brands/kfc/menu?channel=pickup"
    first = client.get(url)
    assert first.status_code == 409
    assert "x-data-version" not in first.headers
    second = client.get(url)
    assert second.status_code == 200
    assert second.json()["items"][0]["channels"]["pickup"]["regularPrice"] == 27


@pytest.mark.parametrize("kind", ["changes", "promotions"])
def test_changes_and_promotions_share_cache_and_refresh_on_commit(menu_client, monkeypatch, kind):
    client, path, adapter = menu_client
    original = getattr(adapter, f"list_{kind}")
    calls = []

    def counted(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(adapter, f"list_{kind}", counted)
    for url in (f"/api/v1/brands/kfc/{kind}", f"/api/v1/market/{kind}"):
        assert client.get(url).status_code == 200
    assert len(calls) == 1
    assert client.get(f"/api/v1/market/{kind}?channel=pickup").status_code == 200
    assert len(calls) == 2
    with sqlite3.connect(path) as db:
        db.execute("UPDATE product_snapshots SET regular_price=28 WHERE run_id='run-new-p'")
    assert client.get(f"/api/v1/market/{kind}").status_code == 200
    assert len(calls) == 3
