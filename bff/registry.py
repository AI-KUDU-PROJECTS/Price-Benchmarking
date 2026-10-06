"""Build the BFF's brand adapters from one declarative registry."""
from __future__ import annotations

from collections.abc import Callable

from adapters.base import BrandAdapter
from adapters.burger_king import BurgerKingAdapter
from adapters.hardees import HardeesAdapter
from adapters.herfy import HerfyAdapter
from adapters.hungerstation import HungerstationOverlayAdapter
from adapters.kfc import KfcAdapter
from adapters.kudu import KuduAdapter
from bff.contract import KNOWN_BRANDS, Brand, disconnected_brand

AdapterFactory = Callable[[], BrandAdapter]

# Official-site adapters. McDonald's and AlBaik currently have only the
# HungerStation source, so they intentionally have no factory here.
_BASE_FACTORIES: dict[str, AdapterFactory] = {
    "kudu": KuduAdapter,
    "kfc": KfcAdapter,
    "hardees": HardeesAdapter,
    "burger-king": BurgerKingAdapter,
    "herfy": HerfyAdapter,
}
_BRAND_NAMES = dict(KNOWN_BRANDS)

_base_adapters: dict[str, BrandAdapter] = {}
_test_adapters: dict[str, BrandAdapter] | None = None


def _base_adapter(brand_id: str) -> BrandAdapter | None:
    factory = _BASE_FACTORIES.get(brand_id)
    if factory is None:
        return None
    if brand_id not in _base_adapters:
        _base_adapters[brand_id] = factory()
    return _base_adapters[brand_id]


def configure_kfc_adapter(adapter: KfcAdapter | None) -> None:
    """Backward-compatible test hook for a temporary KFC database."""
    if adapter is None:
        _base_adapters.pop("kfc", None)
    else:
        _base_adapters["kfc"] = adapter


def configure_adapters_for_test(adapters: dict[str, BrandAdapter] | None) -> None:
    """Override the production registry for isolated BFF tests only."""
    global _test_adapters
    _test_adapters = adapters


def connected_adapters() -> dict[str, BrandAdapter]:
    if _test_adapters is not None:
        return _test_adapters

    kudu = _base_adapter("kudu")
    assert kudu is not None
    adapters: dict[str, BrandAdapter] = {"kudu": kudu}

    for brand_id, brand_name in KNOWN_BRANDS:
        if brand_id == "kudu":
            continue
        adapters[brand_id] = HungerstationOverlayAdapter(
            brand_id=brand_id,
            brand_name=brand_name,
            base=_base_adapter(brand_id),
        )
    return adapters


def get_adapter(brand_id: str) -> BrandAdapter | None:
    return connected_adapters().get(brand_id)


def all_brands() -> list[Brand]:
    connected = connected_adapters()
    return [
        connected[brand_id].get_brand()
        if brand_id in connected
        else disconnected_brand(brand_id, _BRAND_NAMES[brand_id])
        for brand_id, _ in KNOWN_BRANDS
    ]
