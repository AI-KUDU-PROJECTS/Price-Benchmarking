"""The saved KUDU production catalog must be usable through the real BFF."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.kudu import KuduAdapter
from bff.app import app
from bff.registry import configure_adapters_for_test
from kudu.catalog import CHANNELS, normalize_catalog


@pytest.mark.parametrize(
    "fields, expected_pickup",
    [
        ({"price": 23, "drinkItemPrice": 3, "friesItemPrice": 2, "isCustomizedPrice": True}, 28),
        ({"price": 23, "drinkItemPrice": 3, "friesItemPrice": 2, "isCustomizedPrice": False}, 23),
        ({"price": 23, "isCustomizedPrice": True}, 23),
        ({"price": 23, "drinkItemPrice": None, "friesItemPrice": None, "isCustomizedPrice": True}, 23),
        ({"price": "23", "drinkItemPrice": "3", "friesItemPrice": "2", "isCustomizedPrice": True}, 28),
        ({"price": 23, "drinkItemPrice": "invalid", "friesItemPrice": {}, "isCustomizedPrice": True}, 23),
        ({"drinkItemPrice": 3, "friesItemPrice": 2, "isCustomizedPrice": True}, None),
        ({"price": None, "drinkItemPrice": 3, "friesItemPrice": 2, "isCustomizedPrice": True}, None),
        ({"price": "invalid", "isCustomizedPrice": True}, None),
        ({"price": 23, "drinkItemPrice": 3, "friesItemPrice": 2}, 23),
    ],
)
def test_default_meal_prices_from_independent_snapshot(tmp_path: Path, fields: dict, expected_pickup: float | None) -> None:
    raw = {
        "templateId": 1,
        "retrievedAtUtc": "2026-10-21T00:00:00+00:00",
        "services": {
            channel: [{"menu": {"menuId": 1}, "items": [{"itemId": 1, "nameEnglish": "Test item", **fields}]}]
            for channel in CHANNELS
        },
    }
    snapshot = normalize_catalog(raw)
    for channel in CHANNELS:
        item = snapshot["services"][channel][0]["items"][0]
        for key in ("price", "isCustomizedPrice", "drinkItemPrice", "friesItemPrice"):
            assert item[key] == fields.get(key)

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(snapshot), encoding="utf-8")
    hungerstation_path = tmp_path / "hungerstation.json"
    hungerstation_path.write_text(json.dumps({
        "retrievedAtUtc": raw["retrievedAtUtc"],
        "categories": [{"items": [{
            "id": 1, "price": 23, "isCustomizedPrice": True,
            "drinkItemPrice": 3, "friesItemPrice": 2,
        }]}],
    }), encoding="utf-8")
    adapter = KuduAdapter(catalog_path=catalog_path, hungerstation_path=hungerstation_path)
    expected_delivery = 23 if fields.get("price") in (23, "23") else None
    for _ in range(2):
        assert adapter.get_product("pickup-1").regular_price == expected_pickup
        assert adapter.get_product("delivery-1").regular_price == expected_delivery
        assert adapter.get_product("hungerstation-1").regular_price == 23
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == snapshot


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
    # A HungerStation channel is added once kudu-hungerstation has collected.
    assert brands[0]["channels"][:2] == ["delivery", "pickup"]
    overview = client.get("/api/v1/brands/kudu/overview")
    assert overview.status_code == 200
    body = overview.json()
    run_counts = {run["channel"]: run["itemCount"] for run in body["runs"]}
    assert {"delivery", "pickup"} <= set(run_counts)
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
    assert pickup_combo["regularPrice"] == 28
    assert pickup_combo["id"] != combo["id"]
    pickup_quattro = next(p for p in pickup["items"] if p["nameAr"] == "وجبة كواترو دجاج")
    assert pickup_quattro["regularPrice"] == 28
    pickup_sandwich = next(p for p in pickup["items"] if p["nameAr"] == "ساندوتش كودو دجاج")
    assert pickup_sandwich["regularPrice"] == 23
    arabic_category = client.get("/api/v1/brands/kudu/products?channel=delivery&q=ساندويتشات").json()
    assert arabic_category["meta"]["total"] > 0


def test_kudu_offers_do_not_invent_discounts(client: TestClient) -> None:
    offers = client.get("/api/v1/brands/kudu/promotions?channel=delivery").json()["items"]
    assert offers
    assert all(offer["regularPrice"] is None and offer["discountPercent"] is None for offer in offers)
