from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bff.app import app
from bff.contract import (
    Brand,
    BrandCapabilities,
    BrandOverview,
    Product,
    ProductHistory,
)
from bff.playground import configure_playground_db_path
from bff.registry import configure_adapters_for_test


class FakeAdapter:
    def __init__(self, brand_id: str, name: str, products: list[Product]) -> None:
        self.brand_id = brand_id
        self.name = name
        self.products = products

    def get_brand(self) -> Brand:
        return Brand(
            id=self.brand_id,
            name=self.name,
            health="healthy",
            data_freshness="fresh",
            capabilities=BrandCapabilities(
                has_discount=True,
                has_size_prices=False,
                has_images=False,
            ),
            channels=sorted({product.channel for product in self.products}),
        )

    def get_overview(self) -> BrandOverview:
        return BrandOverview(
            brand=self.get_brand(),
            runs=[],
            product_count=len(self.products),
            promotion_count=0,
            recent_changes=[],
            highlights=[],
        )

    def list_products(self, *, channel=None, category=None, query=None):
        return [
            product
            for product in self.products
            if (channel is None or product.channel == channel)
        ]

    def get_product(self, product_id: str) -> Product | None:
        return next((product for product in self.products if product.id == product_id), None)

    def get_product_history(self, product_id: str) -> ProductHistory | None:
        return None

    def list_promotions(self, **_kwargs):
        return []

    def get_promotion(self, _promotion_id: str):
        return None

    def list_changes(self, **_kwargs):
        return []

    def get_change(self, _change_id: str):
        return None


def product(
    product_id: str,
    brand_id: str,
    price: float | None,
    *,
    channel: str = "pickup",
    special_price: float | None = None,
) -> Product:
    return Product(
        id=product_id,
        brand_id=brand_id,
        source_id=product_id,
        name_en=f"{brand_id} {product_id}",
        category="Meals",
        image_url=f"/images/{brand_id}/{product_id}.jpg",
        channel=channel,
        regular_price=price,
        special_price=special_price,
        currency="SAR",
        status="active",
    )


@pytest.fixture()
def playground(tmp_path: Path):
    kudu = FakeAdapter("kudu", "KUDU", [product("kudu-1", "kudu", 25)])
    kfc = FakeAdapter(
        "kfc",
        "KFC",
        [
            product("kfc-offer", "kfc", 30, special_price=20),
            product("kfc-high", "kfc", 35),
            product("kfc-delivery", "kfc", 40, channel="delivery"),
            product("kfc-no-price", "kfc", None),
        ],
    )
    configure_playground_db_path(tmp_path / "playground.db")
    configure_adapters_for_test({"kudu": kudu, "kfc": kfc})
    try:
        yield TestClient(app), kudu, kfc
    finally:
        configure_adapters_for_test(None)
        configure_playground_db_path(None)


def payload(product_id: str = "kfc-offer") -> dict:
    return {
        "name": "Chicken benchmark",
        "channel": "pickup",
        "kuduProductId": "kudu-1",
        "competitorItems": [{"brandId": "kfc", "productId": product_id}],
    }


def test_playground_mapping_crud_and_duplicate_kudu_groups(playground) -> None:
    client, _kudu, _kfc = playground

    first = client.post("/api/v1/playground/mappings", json=payload())
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["kuduItem"]["imageUrl"] == "/images/kudu/kudu-1.jpg"
    assert first_body["competitorItems"][0]["imageUrl"] == "/images/kfc/kfc-offer.jpg"
    assert first_body["competitorItems"][0]["effectivePrice"] == 20
    assert first_body["competitorItems"][0]["differenceAmount"] == -5
    assert first_body["competitorItems"][0]["differencePercentage"] == -20
    assert first_body["competitorItems"][0]["pricePosition"] == "lower"

    second_payload = payload("kfc-high")
    second_payload["name"] = "Second group for the same KUDU item"
    second = client.post("/api/v1/playground/mappings", json=second_payload)
    assert second.status_code == 201
    assert second.json()["id"] != first_body["id"]

    listing = client.get("/api/v1/playground/mappings")
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 2

    update_payload = payload("kfc-high")
    update_payload["name"] = "Updated benchmark"
    updated = client.put(
        f"/api/v1/playground/mappings/{first_body['id']}",
        json=update_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated benchmark"
    assert updated.json()["competitorItems"][0]["pricePosition"] == "higher"

    detail = client.get(f"/api/v1/playground/mappings/{first_body['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Updated benchmark"

    deleted = client.delete(f"/api/v1/playground/mappings/{first_body['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/playground/mappings/{first_body['id']}").status_code == 404


def test_mapping_uses_latest_prices_and_keeps_missing_references(playground) -> None:
    client, _kudu, kfc = playground
    created = client.post("/api/v1/playground/mappings", json=payload()).json()
    mapping_id = created["id"]

    offer = kfc.get_product("kfc-offer")
    assert offer is not None
    offer.special_price = 15
    refreshed = client.get(f"/api/v1/playground/mappings/{mapping_id}").json()
    assert refreshed["competitorItems"][0]["effectivePrice"] == 15
    assert refreshed["competitorItems"][0]["differenceAmount"] == -10

    kfc.products = [item for item in kfc.products if item.id != "kfc-offer"]
    missing = client.get(f"/api/v1/playground/mappings/{mapping_id}").json()
    competitor = missing["competitorItems"][0]
    assert competitor["missing"] is True
    assert competitor["nameEn"] == "kfc kfc-offer"
    assert competitor["imageUrl"] is None
    assert competitor["effectivePrice"] is None
    assert competitor["differenceAmount"] is None
    assert competitor["pricePosition"] == "unavailable"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (
            {
                "name": "Invalid",
                "channel": "pickup",
                "kuduProductId": "kudu-1",
                "competitorItems": [{"brandId": "kudu", "productId": "kudu-1"}],
            },
            "competitorItems.0",
        ),
        (
            {
                "name": "Invalid",
                "channel": "pickup",
                "kuduProductId": "kudu-1",
                "competitorItems": [
                    {"brandId": "kfc", "productId": "kfc-high"},
                    {"brandId": "kfc", "productId": "kfc-high"},
                ],
            },
            "competitorItems.1",
        ),
        (
            payload("kfc-delivery"),
            "competitorItems.0",
        ),
        (
            payload("kfc-no-price"),
            "competitorItems.0",
        ),
    ],
)
def test_mapping_rejects_invalid_selections(playground, body: dict, field: str) -> None:
    client, _kudu, _kfc = playground
    response = client.post("/api/v1/playground/mappings", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == field


def test_mapping_requires_at_least_one_competitor(playground) -> None:
    client, _kudu, _kfc = playground
    body = payload()
    body["competitorItems"] = []
    response = client.post("/api/v1/playground/mappings", json=body)
    assert response.status_code == 422


def test_mapping_database_persists_between_connections(playground) -> None:
    client, _kudu, _kfc = playground
    created = client.post("/api/v1/playground/mappings", json=payload())
    assert created.status_code == 201

    first_read = client.get("/api/v1/playground/mappings").json()
    second_read = client.get("/api/v1/playground/mappings").json()
    assert first_read == second_read
    assert len(second_read["items"]) == 1

