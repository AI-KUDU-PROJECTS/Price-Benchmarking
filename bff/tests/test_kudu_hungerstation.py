"""KUDU's HungerStation menu: collection, image reuse, and the BFF channel."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import kudu.hungerstation as kudu_hs
from adapters.kudu import KuduAdapter
from kudu.hungerstation import CollectionError, ImageIndex, normalize_menu

MAIN_ITEMS = [
    {"itemId": 102295, "nameEnglish": "Muraba'a Combo", "nameArabic": "كومبو المربع", "itemImageUrl": "img/muraba.jpg"},
    {"itemId": 1, "nameEnglish": "Orange Juice", "nameArabic": "عصير برتقال", "itemImageUrl": "img/orange.jpg"},
    {"itemId": 2, "nameEnglish": "Latte", "nameArabic": "لاتيه", "itemImageUrl": "img/latte.jpg"},
    {"itemId": 3, "nameEnglish": "Kudu Spicy Chicken Combo", "nameArabic": "وجبة دجاج", "itemImageUrl": "img/spicy.jpg"},
    {"itemId": 4, "nameEnglish": "Club Sandwich", "nameArabic": "كلوب", "itemImageUrl": "img/club.jpg"},
    {"itemId": 5, "nameEnglish": "Large KUDU Nachos Platter", "nameArabic": "ناتشوز", "itemImageUrl": "img/nachos.jpg"},
]


def _item(item_id: int, name: str, price: float, *, arabic: str = "", original: float = 0) -> dict:
    return {
        "id": item_id, "nameEnglish": name, "nameArabic": arabic, "price": price,
        "originalPrice": original, "descriptionEnglish": "", "descriptionArabic": "", "modgroups": [],
    }


def _raw_menu(*categories: tuple[str, list[dict]]) -> list[dict]:
    return [{"id": 1, "submenus": [
        {"id": index, "titleEnglish": title, "titleArabic": title, "items": items}
        for index, (title, items) in enumerate(categories)
    ]}]


def test_images_match_by_id_name_similar_and_leading_name_only() -> None:
    index = ImageIndex(MAIN_ITEMS)
    assert index.match(_item(102295, "Different name", 39)) == ("img/muraba.jpg", "id")
    assert index.match(_item(9, "", 12, arabic="عصير برتقال")) == ("img/orange.jpg", "name")
    assert index.match(_item(9, "Spicy Chicken Combo", 39)) == ("img/spicy.jpg", "similar-name")
    assert index.match(_item(9, "Orange Juice Large", 12)) == ("img/orange.jpg", "leading-name")
    assert index.match(_item(9, "Combo Club Sandwich Multigrain Toast", 37)) == ("img/club.jpg", "leading-name")
    # "platter" contains "latte": a substring match would show the wrong image.
    assert index.match(_item(9, "Burger box +Large Nachos Platter", 60)) == (None, None)
    assert index.match(_item(9, "Pancake", 18)) == (None, None)


def test_normalize_keeps_prices_and_skips_empty_categories() -> None:
    raw = _raw_menu(("Drinks", [_item(1, "Orange Juice Large", 12), _item(7, "Spicy Karak", 6.5)]), ("M41", []))
    snapshot = normalize_menu(raw, ImageIndex(MAIN_ITEMS), "2026-10-12T09:00:00+00:00")
    assert [category["titleEnglish"] for category in snapshot["categories"]] == ["Drinks"]
    juice, karak = snapshot["categories"][0]["items"]
    assert (juice["price"], juice["imageUrl"], juice["imageMatch"]) == (12, "img/orange.jpg", "id")
    assert (karak["price"], karak["imageUrl"]) == (6.5, None)


@pytest.mark.parametrize(
    "raw, reason",
    [
        ({"error": "nope"}, "expected a list"),
        (_raw_menu(("Drinks", [_item(1, "A", 5), _item(1, "B", 6)])), "duplicate item id"),
        (_raw_menu(("Drinks", [_item(1, "A", None)])), "no valid price"),  # type: ignore[arg-type]
        (_raw_menu(("Empty", [])), "no items"),
    ],
)
def test_normalize_rejects_incomplete_menus(raw: object, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        normalize_menu(raw, ImageIndex([]), "2026-10-12T09:00:00+00:00")


def test_main_reports_success_and_failure_without_replacing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot_path = tmp_path / "hungerstation.json"
    monkeypatch.setattr(kudu_hs, "SNAPSHOT_PATH", snapshot_path)
    monkeypatch.setattr(kudu_hs, "load_main_items", lambda: MAIN_ITEMS)
    monkeypatch.setattr(kudu_hs, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("KUDU_AGGREGATOR_TOKEN", "test-token")
    monkeypatch.setattr(kudu_hs, "fetch_menu", lambda url, token: _raw_menu(("Drinks", [_item(1, "Orange Juice", 12)])))

    assert kudu_hs.main() == 0
    assert "HUNGERSTATION_RESULT brand=kudu status=SUCCESS products=1" in capsys.readouterr().out
    saved = json.loads(snapshot_path.read_text(encoding="utf-8"))

    def unreachable(url: str, token: str) -> None:
        raise CollectionError("NETWORK_UNREACHABLE", "Cannot reach the KUDU integration server.")

    monkeypatch.setattr(kudu_hs, "fetch_menu", unreachable)
    assert kudu_hs.main() == 1
    output = capsys.readouterr().out
    assert "HUNGERSTATION_ERROR brand=kudu code=NETWORK_UNREACHABLE" in output
    assert "test-token" not in output
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == saved


def test_missing_token_is_reported(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(kudu_hs, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("KUDU_AGGREGATOR_TOKEN", "")
    assert kudu_hs.main() == 1
    assert "code=TOKEN_MISSING" in capsys.readouterr().out


def test_fetch_maps_auth_and_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kudu_hs.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(kudu_hs.httpx, "get", lambda *args, **kwargs: httpx.Response(401, request=httpx.Request("GET", "x")))
    with pytest.raises(CollectionError) as error:
        kudu_hs.fetch_menu("https://example.test", "token")
    assert error.value.code == "AUTH_FAILED"

    def timeout(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(kudu_hs.httpx, "get", timeout)
    with pytest.raises(CollectionError) as error:
        kudu_hs.fetch_menu("https://example.test", "token")
    assert error.value.code == "NETWORK_UNREACHABLE"


def test_adapter_exposes_hungerstation_channel(tmp_path: Path) -> None:
    snapshot = normalize_menu(
        _raw_menu(
            ("Drinks", [_item(1, "Orange Juice Large", 12)]),
            ("Promotions", [_item(8, "Family Box", 99, original=120)]),
        ),
        ImageIndex(MAIN_ITEMS),
        "2026-10-12T09:00:00+00:00",
    )
    path = tmp_path / "hungerstation.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    adapter = KuduAdapter(catalog_path=tmp_path / "missing.json", hungerstation_path=path)

    assert "hungerstation" in adapter.get_brand().channels
    products = adapter.list_products(channel="hungerstation")
    juice = next(product for product in products if product.source_id == "1")
    assert (juice.id, juice.regular_price, juice.special_price, juice.image_url) == (
        "hungerstation-1", 12, None, "img/orange.jpg",
    )
    box = adapter.get_product("hungerstation-8")
    assert box is not None and (box.regular_price, box.special_price) == (120, 99)

    promotions = adapter.list_promotions(channel="hungerstation")
    assert [(p.title, p.promotional_price, p.regular_price, p.discount_percent) for p in promotions] == [
        ("Family Box", 99, 120, 17.5),
    ]
    runs = adapter.get_overview().runs
    assert [(run.channel, run.item_count) for run in runs] == [("hungerstation", 2)]


def test_adapter_without_snapshot_keeps_two_channels(tmp_path: Path) -> None:
    adapter = KuduAdapter(catalog_path=tmp_path / "missing.json", hungerstation_path=tmp_path / "none.json")
    assert adapter.get_brand().channels == ["delivery", "pickup"]
    assert adapter.list_products(channel="hungerstation") == []
