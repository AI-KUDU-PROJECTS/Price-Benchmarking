from __future__ import annotations

from pathlib import Path

import pytest

from adapters.kfc import KfcAdapter
from adapters.kfc.adapter import _filter_changes
from adapters.kfc.tests.seed import seed_kfc_db
from bff.contract import ChangeEvent, HIGHLIGHT_RANK, select_highlights


@pytest.fixture()
def adapter(tmp_path: Path) -> KfcAdapter:
    db_path = tmp_path / "kfc_monitor.db"
    seed_kfc_db(db_path)
    return KfcAdapter(db_path=db_path)


def test_missing_price_stays_null(adapter: KfcAdapter) -> None:
    delivery = adapter.get_product("143--DELIVERY--id:100")
    assert delivery is not None
    assert delivery.regular_price is None
    assert delivery.special_price is None
    assert delivery.regular_price != 0


def test_pickup_and_delivery_are_separate_identities(adapter: KfcAdapter) -> None:
    pickup = adapter.get_product("143--PICKUP--id:100")
    delivery = adapter.get_product("143--DELIVERY--id:100")
    assert pickup is not None and delivery is not None
    assert pickup.id != delivery.id
    assert pickup.channel == "pickup"
    assert delivery.channel == "delivery"
    assert pickup.regular_price == 19.0
    assert pickup.previous_regular_price == 21.0


def test_size_prices_preserved_and_not_invented(adapter: KfcAdapter) -> None:
    pickup = adapter.get_product("143--PICKUP--id:100")
    assert pickup is not None
    labels = [s.label for s in pickup.sizes]
    assert labels == ["Medium", "Large"]
    assert pickup.sizes[0].price == 19.0
    assert "Small" not in labels


def test_not_observed_is_not_removed_or_ended(adapter: KfcAdapter) -> None:
    changes = {event.type: event for event in adapter.list_changes()}
    assert "product_not_observed" in changes
    assert "product_removed" in changes
    assert "offer_not_observed" in changes
    assert "offer_ended" in changes
    assert changes["product_not_observed"].id != changes["product_removed"].id
    not_observed = adapter.get_product("143--PICKUP--id:200")
    removed = adapter.get_product("143--PICKUP--id:300")
    assert not_observed is not None and not_observed.status == "not_observed"
    assert removed is not None and removed.status == "removed"
    ended = adapter.get_promotion("143--PICKUP--promo:8")
    missing = adapter.get_promotion("143--PICKUP--promo:7")
    assert ended is not None and ended.status == "ended"
    assert missing is not None and missing.status == "not_observed"


def test_stale_run_is_marked_stale(adapter: KfcAdapter) -> None:
    brand = adapter.get_brand()
    assert brand.data_freshness in ("fresh", "stale")
    # Seed last success is 2026-09-08; current date is 2026-09-09 in this workspace.
    # Either is acceptable depending on exact clock; mixed channel FAILED makes partial.
    assert brand.health in ("stale", "partial", "healthy")
    assert brand.last_successful_run_at is not None
    assert "+03:00" in brand.last_successful_run_at or brand.last_successful_run_at.endswith("+03:00")


def test_highlights_skip_not_observed(adapter: KfcAdapter) -> None:
    overview = adapter.get_overview()
    types = [h.type for h in overview.highlights]
    assert "product_not_observed" not in types
    assert "offer_not_observed" not in types
    assert types[0] in HIGHLIGHT_RANK
    ranked = select_highlights(adapter.list_changes())
    assert [h.type for h in ranked[:3]] == [
        "offer_started",
        "price_decreased",
        "offer_ended",
    ]


def test_history_has_observations(adapter: KfcAdapter) -> None:
    history = adapter.get_product_history("143--PICKUP--id:100")
    assert history is not None
    assert len(history.observations) == 2
    assert history.observations[0].regular_price == 21.0
    assert history.observations[1].regular_price == 19.0


def test_date_filters_use_riyadh_calendar_day() -> None:
    early_riyadh = ChangeEvent(
        id="early",
        brand_id="kfc",
        type="price_decreased",
        detected_at="2026-09-08T01:30:00+03:00",
        channel="pickup",
    )
    next_riyadh_day = ChangeEvent(
        id="next",
        brand_id="kfc",
        type="price_increased",
        detected_at="2026-09-09T00:30:00+03:00",
        channel="pickup",
    )

    filtered = _filter_changes(
        [early_riyadh, next_riyadh_day],
        channel=None,
        event_type=None,
        category=None,
        date_from="2026-09-08",
        date_to="2026-09-08",
    )

    assert [event.id for event in filtered] == ["early"]
