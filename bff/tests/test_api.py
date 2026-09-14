from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.kfc import KfcAdapter
from adapters.kfc.tests.seed import seed_kfc_db
from bff.app import app
from bff.registry import configure_adapters_for_test, configure_kfc_adapter


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "kfc_monitor.db"
    seed_kfc_db(db_path)
    adapter = KfcAdapter(db_path=db_path)
    configure_kfc_adapter(adapter)
    configure_adapters_for_test({"kfc": adapter})
    yield TestClient(app)
    configure_adapters_for_test(None)
    configure_kfc_adapter(None)


def test_market_overview_marks_disconnected_brands(client: TestClient) -> None:
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["connectedBrandIds"] == ["kfc"]
    by_id = {row["brand"]["id"]: row for row in body["brands"]}
    assert by_id["kfc"]["brand"]["health"] != "disconnected"
    assert by_id["hardees"]["brand"]["health"] == "disconnected"
    assert by_id["burger-king"]["brand"]["health"] == "disconnected"
    assert by_id["herfy"]["brand"]["health"] == "disconnected"
    assert by_id["hardees"]["productCount"] is None
    types = [h["type"] for h in body["highlights"]]
    assert "product_not_observed" not in types
    assert "offer_not_observed" not in types


def test_disconnected_brand_is_not_empty_healthy(client: TestClient) -> None:
    response = client.get("/api/v1/brands/hardees/overview")
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "brand_not_connected"


def test_kfc_pages_through_bff_only(client: TestClient) -> None:
    overview = client.get("/api/v1/brands/kfc/overview")
    assert overview.status_code == 200
    products = client.get("/api/v1/brands/kfc/products?channel=pickup")
    assert products.status_code == 200
    items = products.json()["items"]
    assert items
    assert all(p["channel"] == "pickup" for p in items)
    product_id = items[0]["id"]
    history = client.get(f"/api/v1/brands/kfc/products/{product_id}/history")
    assert history.status_code == 200
    assert history.json()["observations"]
    promotions = client.get("/api/v1/brands/kfc/promotions")
    assert promotions.status_code == 200
    changes = client.get("/api/v1/brands/kfc/changes")
    assert changes.status_code == 200
    event_types = {row["type"] for row in changes.json()["items"]}
    assert "product_not_observed" in event_types
    assert "product_removed" in event_types
    change_id = changes.json()["items"][0]["id"]
    detail = client.get(f"/api/v1/changes/{change_id}")
    assert detail.status_code == 200


def test_market_feeds_use_connected_adapters(client: TestClient) -> None:
    changes = client.get("/api/v1/market/changes")
    promotions = client.get("/api/v1/market/promotions")
    assert changes.status_code == 200
    assert promotions.status_code == 200
    assert all(item["brandId"] == "kfc" for item in changes.json()["items"])
    assert all(item["brandId"] == "kfc" for item in promotions.json()["items"])


def test_contract_uses_camel_case_and_riyadh(client: TestClient) -> None:
    brand = client.get("/api/v1/brands").json()["items"][0]
    assert "lastSuccessfulRunAt" in brand
    assert "dataFreshness" in brand
    assert brand["id"] == "kfc"
    if brand["lastSuccessfulRunAt"]:
        assert "+03:00" in brand["lastSuccessfulRunAt"]
