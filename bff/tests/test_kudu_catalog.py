"""Multi-menu KUDU products retain stable identity and safe snapshot writes."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from adapters.kudu import KuduAdapter
from kudu import catalog, refresh


def _raw() -> dict:
    services = {}
    for channel, sandwich_id, combo_id, sandwich_price, combo_price in (
        ("delivery", 104380, 104383, 25, 31),
        ("pickup", 104379, 104382, 19, 20),
    ):
        sandwich = {
            "itemId": sandwich_id, "nameEnglish": "Chopino Sandwich", "nameArabic": "ساندويتش تشوبينو",
            "price": sandwich_price, "itemImageUrl": "https://images.example/sandwich.jpg",
            "descriptionEnglish": "Regular sandwich description", "status": "active",
            "isCustomizedPrice": False,
        }
        combo = {
            "itemId": combo_id, "nameEnglish": "Chopino Combo", "nameArabic": "كومبو تشوبينو",
            "price": combo_price, "itemImageUrl": "https://images.example/combo.jpg",
            "descriptionEnglish": "Regular combo description", "status": "active",
            "isCustomizedPrice": True, "drinkItemPrice": 3, "friesItemPrice": 2,
        }
        offer_sandwich = {**sandwich, "itemImageUrl": "https://images.example/offer-sandwich.jpg"}
        offer_combo = {**combo, "descriptionEnglish": "Offer combo description"}
        if channel == "delivery":
            offer_combo.update(isCustomizedPrice=False, drinkItemPrice=None)
        services[channel] = [
            {"menu": {"menuId": 20, "titleEnglish": "Sandwiches", "titleArabic": "ساندويتشات"}, "items": [sandwich]},
            {"menu": {"menuId": 19, "titleEnglish": "Combos", "titleArabic": "الوجبات"}, "items": [combo]},
            {"menu": {"menuId": 44, "titleEnglish": "Special Offers", "titleArabic": "العروض الخاصة"},
             "items": [offer_sandwich, offer_combo]},
        ]
    return {"templateId": 1, "retrievedAtUtc": "2026-10-31T05:44:59+00:00", "services": services}


def _adapter(path: Path) -> KuduAdapter:
    return KuduAdapter(catalog_path=path, hungerstation_path=path.parent / "absent-hungerstation.json")


@pytest.mark.parametrize("reverse", [False, True])
def test_multi_menu_products_keep_ids_counts_images_and_promotions(tmp_path, reverse) -> None:
    raw = _raw()
    if reverse:
        for categories in raw["services"].values():
            categories.reverse()
            for category in categories:
                category["items"].reverse()
                category["menu"]["displayOrder"] = -category["menu"]["menuId"]
    original = copy.deepcopy(raw)
    path = catalog.save_catalog(raw, tmp_path / "catalog.json")
    assert raw == original
    saved = json.loads(path.read_text())
    for categories in saved["services"].values():
        assert sum(len(category["items"]) for category in categories) == 2
        for category in categories:
            for item in category["items"]:
                assert len(item["categoryVariants"]) == 2
    adapter = _adapter(path)
    products = adapter.list_products()
    assert len(products) == len({p.id for p in products}) == 4
    assert {p.id: p.regular_price for p in products} == {
        "delivery-104380": 25, "delivery-104383": 31,
        "pickup-104379": 19, "pickup-104382": 25,
    }
    sandwich = adapter.get_product("delivery-104380")
    assert sandwich.source_id == "104380"
    assert sandwich.category == "Sandwiches"
    assert sandwich.image_url == "https://images.example/sandwich.jpg"
    combo = adapter.get_product("delivery-104383")
    assert combo.description_en == "Regular combo description"
    history = adapter.get_product_history(sandwich.id)
    assert history.product.id == sandwich.id
    assert history.observations[0].regular_price == 25
    overview = adapter.get_overview()
    assert overview.product_count == 4
    assert [run.item_count for run in overview.runs] == [2, 2]
    assert overview.promotion_count == 4
    offers = adapter.list_promotions(category="Special Offers")
    assert {offer.product_id for offer in offers} == {p.id for p in products}
    assert all(offer.regular_price is None and offer.discount_percent is None for offer in offers)
    assert adapter.get_promotion(sandwich.id).image_url == sandwich.image_url
    assert len(adapter.list_products(category="Special Offers")) == 4
    assert len(adapter.list_products(query="العروض الخاصة", channel="delivery")) == 2
    assert len(adapter.list_products(category="Sandwiches")) == 2


def test_source_variants_are_preserved_without_mixing_fields() -> None:
    raw = _raw()
    raw["services"]["delivery"][0]["items"][0]["itemImageUrl"] = None
    saved = catalog.normalize_catalog(raw)
    items = {item["itemId"]: item for c in saved["services"]["delivery"] for item in c["items"]}
    assert items[104380]["itemImageUrl"] is None  # no arbitrary fallback to an offer image
    assert items[104380]["categoryVariants"][1]["item"]["itemImageUrl"].endswith("offer-sandwich.jpg")
    combo = items[104383]
    assert combo["isCustomizedPrice"] is True and combo["drinkItemPrice"] == 3
    assert combo["categoryVariants"][1]["item"]["isCustomizedPrice"] is False
    assert combo["categoryVariants"][1]["item"]["drinkItemPrice"] is None


@pytest.mark.parametrize("channel, changes", [
    ("delivery", {"price": 32}),
    ("pickup", {"price": 21}),
    ("pickup", {"drinkItemPrice": 4}),
    ("pickup", {"drinkItemPrice": 2, "friesItemPrice": 3}),  # same total still conflicts
    ("pickup", {"isCustomizedPrice": False}),
    ("pickup", {"friesItemPrice": None}),
    ("pickup", {"isCustomizedPrice": "true"}),
    ("pickup", {"drinkItemPrice": "invalid"}),
    ("delivery", {"price": None}),
    ("delivery", {"price": "NaN"}),
    ("delivery", {"price": float("inf")}),
])
def test_ambiguous_pricing_keeps_previous_snapshot(tmp_path, channel, changes) -> None:
    path = catalog.save_catalog(_raw(), tmp_path / "catalog.json")
    previous = path.read_bytes()
    raw = _raw()
    raw["services"][channel][2]["items"][1].update(changes)
    with pytest.raises(catalog.CatalogValidationError, match=f"KUDU {channel} item"):
        catalog.save_catalog(raw, path)
    assert path.read_bytes() == previous
    assert not path.with_name("catalog.json.tmp").exists()


def test_equivalent_numeric_prices_and_optional_zero_sides_are_compatible() -> None:
    raw = _raw()
    raw["services"]["pickup"][1]["items"][0]["friesItemPrice"] = None
    raw["services"]["pickup"][2]["items"][1].update(price="20.00", drinkItemPrice="3.00", friesItemPrice=0)
    assert catalog.normalize_catalog(raw)


def test_multiple_regular_categories_use_stable_menu_id_tiebreak() -> None:
    raw = _raw()
    extra = copy.deepcopy(raw["services"]["delivery"][0])
    extra["menu"].update(menuId=21, titleEnglish="Featured")
    extra["items"][0]["itemImageUrl"] = "https://images.example/featured.jpg"
    raw["services"]["delivery"].insert(0, extra)
    saved = catalog.normalize_catalog(raw)
    containing = [c for c in saved["services"]["delivery"] if any(i["itemId"] == 104380 for i in c["items"])]
    assert len(containing) == 1 and containing[0]["menuId"] == 20


def test_offer_only_product_is_retained_and_arabic_offer_title_is_recognized(tmp_path) -> None:
    raw = _raw()
    for categories in raw["services"].values():
        categories[0]["items"].clear()
        categories[2]["menu"]["titleEnglish"] = None
    adapter = _adapter(catalog.save_catalog(raw, tmp_path / "catalog.json"))
    assert len(adapter.list_products()) == 4
    assert len(adapter.list_promotions()) == 4


def test_repeated_record_within_one_menu_requires_identical_retained_fields() -> None:
    raw = _raw()
    items = raw["services"]["delivery"][0]["items"]
    items.append(copy.deepcopy(items[0]))
    assert catalog.normalize_catalog(raw)
    items[1]["itemImageUrl"] = "https://images.example/ambiguous.jpg"
    with pytest.raises(catalog.CatalogValidationError, match="conflicting records within menu 20"):
        catalog.normalize_catalog(raw)


@pytest.mark.parametrize("invalid_pickup", [[], [{"menu": {"menuId": 1}, "items": []}], [None]])
def test_incomplete_second_channel_does_not_replace_snapshot(tmp_path, invalid_pickup) -> None:
    path = catalog.save_catalog(_raw(), tmp_path / "catalog.json")
    previous = path.read_bytes()
    raw = _raw()
    raw["services"]["pickup"] = invalid_pickup
    with pytest.raises(catalog.CatalogValidationError):
        catalog.save_catalog(raw, path)
    assert path.read_bytes() == previous


def test_failed_atomic_replace_keeps_previous_snapshot(tmp_path, monkeypatch) -> None:
    path = catalog.save_catalog(_raw(), tmp_path / "catalog.json")
    previous = path.read_bytes()

    def fail_replace(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(catalog.os, "replace", fail_replace)
    with pytest.raises(OSError):
        catalog.save_catalog(_raw(), path)
    assert path.read_bytes() == previous
    assert not path.with_name("catalog.json.tmp").exists()


def _configure_main(monkeypatch, path):
    monkeypatch.setattr(refresh, "load_dotenv", lambda: None)
    monkeypatch.setenv("KUDU_API_USERNAME", "test-user")
    monkeypatch.setenv("KUDU_API_PASSWORD", "test-secret")
    monkeypatch.setattr(refresh, "save_catalog", lambda raw: catalog.save_catalog(raw, path))


def test_refresh_reports_unique_counts(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "catalog.json"
    _configure_main(monkeypatch, path)
    monkeypatch.setattr(refresh, "fetch_catalog", lambda *_: _raw())
    assert refresh.main() == 0
    assert "delivery=2 pickup=2" in capsys.readouterr().out
    assert len(_adapter(path).list_products()) == 4


def test_refresh_reports_conflict_without_replacing_snapshot(tmp_path, monkeypatch, capsys) -> None:
    path = catalog.save_catalog(_raw(), tmp_path / "catalog.json")
    previous = path.read_bytes()
    _configure_main(monkeypatch, path)
    raw = _raw()
    raw["services"]["pickup"][2]["items"][1]["drinkItemPrice"] = 4
    monkeypatch.setattr(refresh, "fetch_catalog", lambda *_: raw)
    assert refresh.main() == 1
    output = capsys.readouterr().out
    assert "KUDU_ERROR code=INVALID_CATALOG" in output
    assert "pickup item 104382 in menus 19, 44" in output
    assert "conflicting price or pickup default drink/fries settings" in output
    assert "Previous complete data kept" in output
    assert "test-secret" not in output
    assert path.read_bytes() == previous


@pytest.mark.parametrize("failure, code", [("network", "NETWORK_ERROR"), ("auth", "AUTH_FAILED"),
                                         ("json", "INVALID_RESPONSE"), ("schema", "INVALID_CATALOG")])
def test_fetch_failure_after_first_channel_keeps_previous_data(tmp_path, monkeypatch, capsys, failure, code) -> None:
    path = catalog.save_catalog(_raw(), tmp_path / "catalog.json")
    previous = path.read_bytes()
    _configure_main(monkeypatch, path)
    requests = []
    original_client = httpx.Client

    def respond(request):
        requests.append(request)
        if request.url.params["servicesType"] == "pickup":
            if failure == "network":
                raise httpx.ConnectError("sensitive transport details", request=request)
            if failure == "auth":
                return httpx.Response(401, text="test-secret")
            if failure == "json":
                return httpx.Response(200, text="invalid JSON test-secret")
            return httpx.Response(200, json={"statusCode": 200, "data": "test-secret"})
        if request.url.path.endswith("menuList"):
            data = [entry["menu"] for entry in _raw()["services"]["delivery"]]
        else:
            data = next(entry["items"] for entry in _raw()["services"]["delivery"]
                        if str(entry["menu"]["menuId"]) == request.url.params["menuId"])
        return httpx.Response(200, json={"statusCode": 200, "data": data})

    monkeypatch.setattr(refresh.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(refresh.time, "sleep", lambda _: None)
    assert refresh.main() == 1
    output = capsys.readouterr().out
    assert f"KUDU_ERROR code={code}" in output
    assert "Previous complete data kept" in output
    assert "test-secret" not in output and "sensitive transport details" not in output
    assert any(r.url.path.endswith("itemList") for r in requests)
    assert path.read_bytes() == previous
