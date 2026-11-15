from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from bff.app import app
from bff.contract import Brand, BrandCapabilities, Product, Promotion, now_riyadh
from bff.registry import configure_adapters_for_test

KEY = "test-key-for-restaurant-export"
HEADERS = {"Authorization": f"Bearer {KEY}"}


class MenuAdapter:
    def __init__(self):
        fresh = now_riyadh().isoformat()
        stale = (now_riyadh() - timedelta(days=3)).isoformat()
        self.brand = Brand(
            id="kfc", name="KFC", health="healthy", data_freshness="fresh",
            capabilities=BrandCapabilities(has_discount=True, has_size_prices=False, has_images=True),
            channels=["pickup", "delivery", "hungerstation"],
        )
        self.products = [Product(
            id=f"pickup-{i}", brand_id="kfc", source_id=str(i), name_en=f"Meal {i}",
            channel="pickup", regular_price=25, special_price=0 if i == 0 else None,
            currency="SAR", status="active", observed_at=fresh, source_run_id="pickup-success",
            image_url="/hungerstation-images/kfc/meal.jpg" if i == 0 else None,
        ) for i in range(501)]
        self.products.append(Product(
            id="hs-0", brand_id="kfc", source_id="0", name_en="Meal 0", channel="hungerstation",
            regular_price=30, status="active", observed_at=stale, source_run_id="hs-old-success",
            image_url="https://cdn.example.com/meal.jpg",
        ))
        self.promotions = [Promotion(
            id="offer", brand_id="kfc", product_id="pickup-0", status="active", channel="pickup",
            image_url="/albaik-app-images/meal.jpg", promotional_price=0,
        )]

    def get_brand(self):
        return self.brand

    def list_products(self):
        return self.products

    def list_promotions(self, **kwargs):
        return self.promotions


@pytest.fixture()
def sharing(monkeypatch):
    monkeypatch.setenv("SHARED_API_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.setenv("SHARED_API_BASE_URL", "https://prices.example.com")
    adapter = MenuAdapter()
    configure_adapters_for_test({"kfc": adapter})
    try:
        # Avoid the lifespan context: tests must not start the production scheduler.
        yield TestClient(app), adapter
    finally:
        configure_adapters_for_test(None)


@pytest.mark.parametrize("headers", [
    {}, {"X-API-Key": KEY}, {"Authorization": "Bearer wrong"},
    {"Authorization": "Bearer"}, {"Authorization": f"Basic {KEY}"},
])
def test_authentication_is_required_before_reading_data(sharing, headers):
    client, adapter = sharing
    adapter.get_brand = lambda: pytest.fail("Unauthenticated request accessed source data")
    response = client.get("/api/v1/restaurants/kfc", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert KEY not in response.text


def test_bearer_scheme_is_case_insensitive(sharing):
    client, _ = sharing
    assert client.get("/api/v1/restaurants/kfc", headers={"Authorization": f"bearer {KEY}"}).status_code == 200


@pytest.mark.parametrize("configured", ["", "invalid-hash"])
def test_missing_or_invalid_configuration_disables_endpoint(sharing, monkeypatch, configured):
    client, _ = sharing
    monkeypatch.setenv("SHARED_API_KEY_SHA256", configured)
    assert client.get("/api/v1/restaurants/kfc", headers=HEADERS).status_code == 503


def test_export_keeps_all_channels_and_products_with_independent_freshness(sharing):
    client, adapter = sharing
    response = client.get("/api/v1/restaurants/kfc", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["restaurant"]["id"] == "kfc"
    assert set(body["channels"]) == {"pickup", "delivery", "hungerstation"}
    pickup, delivery, hs = (body["channels"][c] for c in ["pickup", "delivery", "hungerstation"])
    assert pickup["productCount"] == len(pickup["products"]) == 501
    assert pickup["dataFreshness"] == "fresh"
    assert pickup["sourceRunIds"] == ["pickup-success"]
    item = next(p for p in pickup["products"] if p["id"] == "pickup-0")
    assert item["imageUrl"] == "https://prices.example.com/hungerstation-images/kfc/meal.jpg"
    assert item["effectivePrice"] == 0
    assert any(p["effectivePrice"] == 25 and p["imageUrl"] is None for p in pickup["products"])
    assert pickup["promotions"][0]["imageUrl"] == "https://prices.example.com/albaik-app-images/meal.jpg"
    assert delivery["products"] == delivery["promotions"] == []
    assert delivery["productCount"] == 0
    assert delivery["observedAt"] is None
    assert delivery["dataFreshness"] == "unavailable"
    assert hs["dataFreshness"] == "stale"
    assert hs["sourceRunIds"] == ["hs-old-success"]
    assert hs["products"][0]["imageUrl"] == "https://cdn.example.com/meal.jpg"
    assert hs["products"][0]["effectivePrice"] == 30
    assert hs["promotions"] == []
    assert hs["observedAt"] != pickup["observedAt"]
    assert "+03:00" in body["generatedAt"]
    assert adapter.products[0].image_url.startswith("/")  # Cached source objects were not mutated.


def test_aggregator_only_restaurant_and_request_origin(sharing, monkeypatch):
    client, adapter = sharing
    monkeypatch.delenv("SHARED_API_BASE_URL")
    adapter.brand = adapter.brand.model_copy(update={"id": "mcdonalds", "channels": ["hungerstation"]})
    adapter.products = [adapter.products[-1].model_copy(update={
        "brand_id": "mcdonalds", "image_url": "/hungerstation-images/mcdonalds/meal.jpg",
    })]
    adapter.promotions = []
    configure_adapters_for_test({"mcdonalds": adapter})
    body = client.get("/api/v1/restaurants/mcdonalds", headers=HEADERS).json()
    assert list(body["channels"]) == ["hungerstation"]
    assert body["channels"]["hungerstation"]["products"][0]["imageUrl"] == (
        "http://testserver/hungerstation-images/mcdonalds/meal.jpg"
    )


def test_unknown_and_unavailable_restaurants(sharing):
    client, adapter = sharing
    assert client.get("/api/v1/restaurants/unknown", headers=HEADERS).status_code == 404
    assert client.get("/api/v1/restaurants/herfy", headers=HEADERS).status_code == 503

    def fail():
        raise FileNotFoundError("private database path")

    adapter.list_products = fail
    response = client.get("/api/v1/restaurants/kfc", headers=HEADERS)
    assert response.status_code == 503
    assert "private database path" not in response.text


def test_openapi_describes_bearer_auth_and_response(sharing):
    client, _ = sharing
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/restaurants/{brand_id}"]["get"]
    assert operation["security"] == [{"RestaurantBearerToken": []}]
    scheme = schema["components"]["securitySchemes"]["RestaurantBearerToken"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/RestaurantData")
