"""Cross-channel comparisons must not invent prices or split rows across pages."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bff.app import app
from bff.contract import Product, ProductSize
from bff.menu import menu_rows, menu_section
import bff.routes as routes


def product(channel, name, *, source=None, brand="kfc", **fields):
    source = source or f"143|{channel.upper()}|id:{name}"
    return Product(id=f"{channel}-{source}", source_id=source, brand_id=brand,
                   channel=channel, name_en=name, status="active", **fields)


def test_three_channel_prices_are_grouped_without_changing_source_products():
    pickup = product("pickup", "Chicken Burger", regular_price=20)
    delivery = product("delivery", "Chicken Burger", regular_price=24)
    hs = product("hungerstation", "CHICKEN BURGER®", source="hs-12", regular_price=27, special_price=25)
    row, = menu_rows([hs, delivery, pickup])
    assert row.channels == {"pickup": pickup, "delivery": delivery, "hungerstation": hs}
    assert row.channels["hungerstation"].special_price == 25
    assert row.channels["delivery"].regular_price == 24
    assert row.product is pickup


def test_shared_official_ids_match_channel_names_without_matching_foreign_aggregator_ids():
    pickup = product("pickup", "Original Burger", source="143|PICKUP|id:12")
    delivery = product("delivery", "Renamed Burger", source="143|DELIVERY|id:12")
    hs = product("hungerstation", "Different Burger", source="143|PICKUP|id:12")
    rows = menu_rows([pickup, delivery, hs])
    assert sorted(len(row.channels) for row in rows) == [1, 2]


def test_kudu_shared_ids_and_arabic_names_work_across_channels():
    ps = [product("pickup", "KUDU Chicken", source="101", brand="kudu", name_ar="ساندوتش كودو دجاج"),
          product("delivery", "KUDU Chicken", source="102", brand="kudu", name_ar="ساندوتش كودو دجاج"),
          product("hungerstation", "Kudu Chicken Sandwich", source="101", brand="kudu")]
    row, = menu_rows(ps)
    assert len(row.channels) == 3


def test_unique_arabic_name_matches_even_if_english_names_differ():
    row, = menu_rows([
        product("pickup", "Chicken Combo", name_ar="وجبة دجاج"),
        product("hungerstation", "Chicken Meal", source="hs-other", name_ar="وَجْبَة دَجاج"),
    ])
    assert len(row.channels) == 2


def test_ambiguous_names_different_sizes_and_meals_remain_separate():
    ps = [product("pickup", "Burger", source="143|PICKUP|id:1"),
          product("pickup", "Burger", source="143|PICKUP|id:2"),
          product("hungerstation", "Burger", source="hs-1"),
          product("hungerstation", "Burger Meal", source="hs-2"),
          product("hungerstation", "Burger Meal Large", source="hs-3")]
    rows = menu_rows(ps)
    assert len(rows) == 5
    assert sum(len(row.channels) for row in rows) == len(ps)
    assert all(len(row.channels) == 1 for row in rows)


def test_missing_channels_prices_and_sizes_stay_independent():
    pickup = product("pickup", "Burger Meal", regular_price=0,
                     sizes=[ProductSize(label="Large", price=25)])
    delivery = product("delivery", "Burger Meal", regular_price=None,
                       sizes=[ProductSize(label="Large", price=30)])
    row, = menu_rows([pickup, delivery])
    assert "hungerstation" not in row.channels
    assert row.channels["pickup"].regular_price == 0
    assert row.channels["delivery"].regular_price is None
    assert row.channels["delivery"].sizes[0].price == 30


@pytest.mark.parametrize("first,second", [
    ("Small Pepsi", "Large Pepsi"),
    ("6 Nuggets", "12 Nuggets"),
    ("Chicken Burger", "Chicken Burger Meal"),
])
def test_shared_translation_cannot_merge_different_variants(first, second):
    rows = menu_rows([product("pickup", first, name_ar="منتج"),
                      product("hungerstation", second, name_ar="منتج")])
    assert len(rows) == 2


@pytest.mark.parametrize("name,category,section", [
    ("Chicken Burger with Cheese Sauce", "Offers", 0),
    ("Chicken Meal with Juice", "Offers", 0),
    ("Chicken Meal with Chocolate Sundae", "Offers", 0),
    ("وجبة دجاج", "وجبات", 0),
    ("Cheese Sauce", "HungerStation Menu", 3),
    ("صوص الثوم", "إضافات", 3),
    ("Orange Juice", "HungerStation Menu", 4),
    ("عصير البرتقال", "قائمة هنقرستيشن", 4),
    ("7 Up", "HungerStation Menu", 4),
    ("Chocolate Milkshake", "Milk Shake & Desserts", 4),
    ("Hot Chocolate", "HungerStation Menu", 4),
    ("Caramel Macchiato", "HungerStation Menu", 4),
    ("Honey Mustard", "HungerStation Menu", 3),
    ("Mc Flurry Oreo", "HungerStation Menu", 2),
    ("Chocolate Cake", "Desserts & Beverages", 2),
    ("Large Fries", "HungerStation Menu", 1),
])
def test_menu_sections_with_real_category_patterns(name, category, section):
    assert menu_section(product("hungerstation", name, category=category)) == section


def menu_client(monkeypatch, products):
    def listing(*, channel=None, category=None, query=None):
        return [p for p in products
                if (not channel or p.channel == channel)
                and (not category or p.category == category)
                and (not query or query.casefold() in " ".join([
                    p.name_en or "", p.name_ar or "", p.category or ""]).casefold())]
    adapter = SimpleNamespace(list_products=listing, get_brand=lambda: SimpleNamespace(data_freshness="fresh"))
    monkeypatch.setattr(routes, "_require_adapter", lambda _: adapter)
    return TestClient(app)


@pytest.mark.parametrize("brand", ["kudu", "kfc", "hardees", "burger-king", "herfy", "mcdonalds", "albaik"])
def test_whole_menu_is_grouped_and_sorted_before_pagination(monkeypatch, brand):
    ps = [product(c, name, source=f"1|{c.upper()}|{name}", brand=brand,
                  category="HungerStation Menu", regular_price=price)
          for c, price in [("pickup", 20), ("delivery", 22), ("hungerstation", 25)]
          for name in ["Apple Juice", "BBQ Sauce", "Chicken Meal"]]
    client = menu_client(monkeypatch, ps)
    url = f"/api/v1/brands/{brand}/menu?page_size=1"
    pages = [client.get(f"{url}&page={page}").json() for page in [1, 2, 3]]
    assert [page["items"][0]["product"]["nameEn"] for page in pages] == ["Chicken Meal", "BBQ Sauce", "Apple Juice"]
    assert all(page["meta"]["total"] == 3 for page in pages)
    assert set(pages[0]["items"][0]["channels"]) == {"pickup", "delivery", "hungerstation"}
    for channel in ["pickup", "delivery", "hungerstation"]:
        body = client.get(f"{url}&channel={channel}").json()
        assert body["items"][0]["product"]["nameEn"] == "Chicken Meal"
        assert body["meta"]["total"] == 3
        assert set(body["items"][0]["channels"]) == {channel}


def test_search_matches_any_channel_and_preserves_all_prices(monkeypatch):
    ps = [product("pickup", "Original Burger", source="143|PICKUP|id:12", regular_price=20),
          product("delivery", "Renamed Burger", source="143|DELIVERY|id:12", regular_price=22)]
    client = menu_client(monkeypatch, ps)
    body = client.get("/api/v1/brands/kfc/menu?q=Renamed").json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["channels"]["pickup"]["regularPrice"] == 20
    assert body["items"][0]["channels"]["delivery"]["regularPrice"] == 22
    assert client.get("/api/v1/brands/kfc/menu?q=absent").json()["items"] == []


def test_product_endpoint_sorts_single_channel_before_pagination(monkeypatch):
    client = menu_client(monkeypatch, [product("pickup", "Apple Juice"), product("pickup", "Chicken Meal")])
    body = client.get("/api/v1/brands/kfc/products?channel=pickup&page_size=1").json()
    assert body["items"][0]["nameEn"] == "Chicken Meal"
    assert body["meta"]["total"] == 2
