"""Adapter registry for the independently collected restaurant modules."""
from __future__ import annotations

from adapters.base import BrandAdapter
from adapters.burger_king import BurgerKingAdapter
from adapters.hardees import HardeesAdapter
from adapters.herfy import HerfyAdapter
from adapters.kfc import KfcAdapter
from bff.contract import KNOWN_BRANDS, Brand, disconnected_brand

_kfc: KfcAdapter | None = None
_hardees: HardeesAdapter | None = None
_burger_king: BurgerKingAdapter | None = None
_herfy: HerfyAdapter | None = None
_test_adapters: dict[str, BrandAdapter] | None = None


def configure_kfc_adapter(adapter: KfcAdapter | None) -> None:
    """Test hook so the BFF can use a temporary KFC database."""
    global _kfc
    _kfc = adapter


def kfc_adapter() -> KfcAdapter:
    global _kfc
    if _kfc is None:
        _kfc = KfcAdapter()
    return _kfc


def hardees_adapter() -> HardeesAdapter:
    global _hardees
    if _hardees is None:
        _hardees = HardeesAdapter()
    return _hardees


def burger_king_adapter() -> BurgerKingAdapter:
    global _burger_king
    if _burger_king is None:
        _burger_king = BurgerKingAdapter()
    return _burger_king


def herfy_adapter() -> HerfyAdapter:
    global _herfy
    if _herfy is None:
        _herfy = HerfyAdapter()
    return _herfy


def configure_adapters_for_test(adapters: dict[str, BrandAdapter] | None) -> None:
    """Override the production registry for isolated BFF tests only."""
    global _test_adapters
    _test_adapters = adapters


def connected_adapters() -> dict[str, BrandAdapter]:
    if _test_adapters is not None:
        return _test_adapters
    return {
        "kfc": kfc_adapter(),
        "hardees": hardees_adapter(),
        "burger-king": burger_king_adapter(),
        "herfy": herfy_adapter(),
    }


def get_adapter(brand_id: str) -> BrandAdapter | None:
    return connected_adapters().get(brand_id)


def all_brands() -> list[Brand]:
    connected = connected_adapters()
    brands: list[Brand] = []
    for brand_id, name in KNOWN_BRANDS:
        adapter = connected.get(brand_id)
        if adapter is None:
            brands.append(disconnected_brand(brand_id, name))
        else:
            brands.append(adapter.get_brand())
    return brands
