"""The saved KUDU production catalog must be usable through the real BFF."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adapters.kudu import KuduAdapter
from bff.app import app
from bff.registry import configure_adapters_for_test


@pytest.fixture()
def client() -> TestClient:
    configure_adapters_for_test({"kudu": KuduAdapter()})
    try:
        yield TestClient(app)
    finally:
        configure_adapters_for_test(None)


def test_kudu_is_first_and_has_both_channels(client: TestClient) -> None:
    brands = client.get("/api/v1/brands").json()["items"]
    assert brands[0]["id"] == "kudu"
    assert brands[0]["channels"] == ["delivery", "pickup"]
    overview = client.get("/api/v1/brands/kudu/overview")
    assert overview.status_code == 200
    body = overview.json()
    run_counts = {run["channel"]: run["itemCount"] for run in body["runs"]}
    assert set(run_counts) == {"delivery", "pickup"}
    assert body["productCount"] == sum(run_counts.values())
    assert body["promotionCount"] >= 0


def test_kudu_menu_has_source_prices_images_and_publication_flags(client: TestClient) -> None:
    delivery = client.get("/api/v1/brands/kudu/products?channel=delivery").json()
    pickup = client.get("/api/v1/brands/kudu/products?channel=pickup").json()
    assert delivery["meta"]["total"] == len(delivery["items"])
    assert pickup["meta"]["total"] == len(pickup["items"])
    assert delivery["meta"]["total"] > 0
    assert pickup["meta"]["total"] > 0
    assert all(p["regularPrice"] is not None and p["imageUrl"] for p in delivery["items"] + pickup["items"])
    assert any(p["isPublished"] is False for p in delivery["items"])
    combo = next(p for p in delivery["items"] if p["nameAr"] == "وجبة كودو دجاج")
    assert combo["regularPrice"] == 34
    assert combo["brandId"] == "kudu"
    assert combo["descriptionAr"]
    assert combo["calories"] is not None
    assert client.get(f"/api/v1/brands/kudu/products/{combo['id']}/history").json()["observations"][0]["regularPrice"] == 34
    pickup_combo = next(p for p in pickup["items"] if p["nameAr"] == "وجبة كودو دجاج")
    assert pickup_combo["regularPrice"] == 23
    assert pickup_combo["id"] != combo["id"]
    arabic_category = client.get("/api/v1/brands/kudu/products?channel=delivery&q=ساندويتشات").json()
    assert arabic_category["meta"]["total"] > 0


def test_kudu_offers_do_not_invent_discounts(client: TestClient) -> None:
    offers = client.get("/api/v1/brands/kudu/promotions?channel=delivery").json()["items"]
    assert offers
    assert all(offer["regularPrice"] is None and offer["discountPercent"] is None for offer in offers)
