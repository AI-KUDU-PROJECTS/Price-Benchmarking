from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from adapters.hungerstation import HungerstationOverlayAdapter, _match_image
from competitors.hungerstation import database
from competitors.hungerstation.collector import (
    _find_first_restaurant_card,
    _find_location_recovery,
    _find_location_setup_action,
    _find_search_suggestion,
    _is_restaurant_menu,
    deduplicate,
    load_capture,
    parse_accessibility_label,
    product_image_candidates,
    save_product_images,
)
from competitors.hungerstation.config import RESTAURANT_BY_ID


def _item(price: float, special: float | None = None) -> dict:
    return {
        "source_product_id": "HUNGERSTATION|mcdonalds|big-mac",
        "name_en": "Big Mac",
        "description_en": "Beef burger",
        "category_name_en": "HungerStation Menu",
        "currency": "SAR",
        "regular_price": price,
        "special_price": special,
        "effective_price": special if special is not None else price,
        "discount_percentage": None,
        "availability": 1,
        "image_url": "/hungerstation-images/mcdonalds/big-mac.jpg",
    }


def _save(path: Path, run_id: str, captured_at: str, item: dict) -> None:
    database.save_success(
        run_id=run_id,
        batch_id="batch",
        brand_id="mcdonalds",
        restaurant_name="McDonald's",
        started_at=captured_at,
        finished_at=captured_at,
        items=[item],
        raw_capture_path=None,
        path=path,
    )


def test_accessibility_label_preserves_offer_price() -> None:
    item = parse_accessibility_label("45%\n130+ orders\nBig Mac\n§\n18\n§\n32.73", "mcdonalds")
    assert item is not None
    assert item["name_en"] == "Big Mac"
    assert item["regular_price"] == 32.73
    assert item["special_price"] == 18.0
    assert item["source_product_id"] == "HUNGERSTATION|mcdonalds|big-mac"


def test_deduplicate_uses_source_id_after_slug_normalization() -> None:
    products = deduplicate(
        [("", "7 Up\n§\n9"), ("", "7-Up\n§\n9")],
        "herfy",
    )
    assert len(products) == 1


def test_database_defensively_deduplicates_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "hungerstation.db"
    item = _item(30.0)
    database.save_success(
        run_id="duplicate-safe",
        batch_id="batch",
        brand_id="mcdonalds",
        restaurant_name="McDonald's",
        started_at="2026-09-01T20:00:00Z",
        finished_at="2026-09-01T20:01:00Z",
        items=[item, dict(item)],
        raw_capture_path=None,
        path=path,
    )
    with database.connection(path) as db:
        assert db.execute("SELECT product_count FROM runs").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1


def test_product_image_is_cropped_and_gets_public_url(tmp_path: Path) -> None:
    xml = """
    <hierarchy>
      <node content-desc="Big Mac&#10;§&#10;18" bounds="[0,100][1080,800]">
        <node class="android.widget.ImageView" bounds="[650,200][1030,580]" />
        <node class="android.widget.ImageView" bounds="[930,500][1010,580]" />
      </node>
    </hierarchy>
    """
    candidates = product_image_candidates(xml, "mcdonalds")
    assert candidates[0][2] == (650, 200, 1030, 580)

    screenshot = Image.new("RGB", (1080, 2400), color=(180, 20, 30))
    buffer = io.BytesIO()
    screenshot.save(buffer, format="PNG")
    urls = save_product_images(
        buffer.getvalue(),
        candidates,
        "mcdonalds",
        {},
        image_dir=tmp_path,
    )

    assert urls["HUNGERSTATION|mcdonalds|big-mac"] == (
        "/hungerstation-images/mcdonalds/big-mac.jpg"
    )
    saved = Image.open(tmp_path / "mcdonalds" / "big-mac.jpg")
    assert saved.size == (380, 380)


def test_search_suggestion_is_used_when_enter_only_opens_autocomplete() -> None:
    xml = """
    <hierarchy>
      <node clickable="true" bounds="[0,180][1080,360]">
        <node text="burger king in Restaurants" bounds="[100,200][900,330]" />
      </node>
    </hierarchy>
    """
    assert _find_search_suggestion(xml, RESTAURANT_BY_ID["burger-king"]) == (540, 270)


def test_first_full_restaurant_card_handles_missing_accessible_title() -> None:
    xml = """
    <hierarchy>
      <node clickable="true" bounds="[0,442][1080,1249]">
        <node resource-id="app:id/description" text="Fast Food, Burgers" />
        <node resource-id="app:id/product_name" text="Whopper" />
        <node resource-id="app:id/rate_value" text="4.4" />
      </node>
    </hierarchy>
    """
    assert _find_first_restaurant_card(
        xml,
        RESTAURANT_BY_ID["burger-king"],
    ) == (540, 522, "Burger King")


def test_out_of_range_location_recovery_button_is_found() -> None:
    xml = """
    <hierarchy>
      <node resource-id="app:id/empty_state_primary_button"
            text="Select a New Location"
            bounds="[63,1256][1017,1382]" />
    </hierarchy>
    """
    assert _find_location_recovery(xml) == (540, 1319)


def test_location_setup_opens_header_and_confirms_map() -> None:
    home = """
    <hierarchy>
      <node resource-id="app:id/change_location_header_v2"
            text="Select your location" bounds="[0,105][1038,225]" />
    </hierarchy>
    """
    map_screen = """
    <hierarchy>
      <node resource-id="app:id/confirm_drop_off_button"
            clickable="true" bounds="[42,2158][1038,2284]" />
    </hierarchy>
    """
    assert _find_location_setup_action(home) == (519, 165)
    assert _find_location_setup_action(map_screen) == (540, 2221)

    uncovered_map = """
    <hierarchy>
      <node resource-id="app:id/detect_my_location" clickable="true"
            bounds="[907,1658][1017,1768]" />
      <node resource-id="app:id/confirm_drop_off_button" clickable="false"
            enabled="false" bounds="[42,2158][1038,2284]" />
    </hierarchy>
    """
    assert _find_location_setup_action(uncovered_map) == (962, 1713)


def test_menu_validation_requires_brand_name_in_header() -> None:
    wrong_brand = """
    <hierarchy>
      <node class="android.widget.ScrollView" bounds="[0,0][1080,2300]">
        <node content-desc="Burger King" bounds="[0,0][1080,210]" />
        <node content-desc="Herfy Sauce&#10;§&#10;5" bounds="[0,900][1080,1300]" />
        <node content-desc="Min. Order" bounds="[0,2200][1080,2300]" />
      </node>
    </hierarchy>
    """
    assert not _is_restaurant_menu(wrong_brand, RESTAURANT_BY_ID["herfy"])


def test_deduplicate_uses_database_source_id() -> None:
    items = deduplicate(
        [
            ("", "A+B\n§\n10"),
            ("", "A B\n§\n10"),
        ],
        "herfy",
    )
    assert len(items) == 1


def test_load_capture_keeps_images_and_removes_source_collisions(tmp_path: Path) -> None:
    capture = tmp_path / "capture.json"
    capture.write_text(
        '{"items": ['
        '{"source_product_id": "HUNGERSTATION|herfy|meal", '
        '"name_en": "Meal", "image_url": "/hungerstation-images/herfy/meal.jpg"},'
        '{"source_product_id": "HUNGERSTATION|herfy|meal", '
        '"name_en": "Meal.", "image_url": "/hungerstation-images/herfy/meal.jpg"}'
        '] }',
        encoding="utf-8",
    )
    items = load_capture(capture, "herfy")
    assert len(items) == 1
    assert items[0]["image_url"] == "/hungerstation-images/herfy/meal.jpg"


def test_image_fallback_accepts_only_close_official_name() -> None:
    images = {
        "doublegrilledchicken": "grilled.jpg",
        "vanillaicecream": "ice-cream.jpg",
    }
    assert _match_image("Double Grilled Chicken Meal", images) == "grilled.jpg"
    assert _match_image("Completely Different Product", images) is None


def test_overlay_exposes_menu_promotions_history_and_changes(tmp_path: Path) -> None:
    path = tmp_path / "hungerstation.db"
    _save(path, "old", "2026-09-01T20:00:00Z", _item(30.0))
    _save(path, "new", "2026-09-02T20:00:00Z", _item(30.0, 18.0))
    adapter = HungerstationOverlayAdapter(
        brand_id="mcdonalds",
        brand_name="McDonald's",
        base=None,
        db_path=path,
    )

    assert adapter.get_brand().channels == ["hungerstation"]
    products = adapter.list_products(channel="hungerstation")
    assert len(products) == 1
    assert products[0].special_price == 18.0
    assert products[0].previous_regular_price == 30.0
    assert products[0].image_url == "/hungerstation-images/mcdonalds/big-mac.jpg"

    promotions = adapter.list_promotions(channel="hungerstation")
    assert len(promotions) == 1
    assert promotions[0].promotional_price == 18.0
    assert promotions[0].image_url == "/hungerstation-images/mcdonalds/big-mac.jpg"

    history = adapter.get_product_history(products[0].id)
    assert history is not None
    assert len(history.observations) == 2

    changes = adapter.list_changes(channel="hungerstation")
    assert {change.type for change in changes} == {"price_decreased", "offer_started"}


def test_failed_run_keeps_last_successful_menu(tmp_path: Path) -> None:
    path = tmp_path / "hungerstation.db"
    _save(path, "good", "2026-09-01T20:00:00Z", _item(30.0))
    database.save_failure(
        run_id="failed",
        batch_id="batch",
        brand_id="mcdonalds",
        restaurant_name="McDonald's",
        started_at="2026-09-02T20:00:00Z",
        finished_at="2026-09-02T20:01:00Z",
        error="restaurant not found",
        path=path,
    )
    adapter = HungerstationOverlayAdapter(
        brand_id="mcdonalds",
        brand_name="McDonald's",
        base=None,
        db_path=path,
    )
    assert len(adapter.list_products(channel="hungerstation")) == 1
    assert adapter.get_overview().runs[0].status == "failed"
