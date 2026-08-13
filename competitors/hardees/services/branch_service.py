"""
competitors/hardees/services/branch_service.py
---------------------------------------------------------------------
City/store/channel resolution built on api/client.py. Everything here
reads from ONE getStoreList() call (cached by the caller - see
../ui/branch_panel.py) - city and store dropdown options are derived
from that live response, never hardcoded, per the task's "Do not
hard-code the whole UI to only these stores" instruction. The known-good
branches from ../research/api-map/ (Riyadh storeId=24/5796, Jeddah
storeId=97/7) are used only as DEFAULT selections when present in the
live list - see `pick_default_store()`.
---------------------------------------------------------------------
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from competitors.hardees.api.client import HardeesApiClient

PICKUP = "PICKUP"
DELIVERY = "DELIVERY"
SERVICES = (PICKUP, DELIVERY)

# service -> store 'services' flag that must be 1 for that store to
# support the channel (see api-map.json 'getStoreList': store.services =
# {carHop,del,din,driveThru,tak}). 'tak' = take-away/self-pickup.
_SERVICE_FLAG = {PICKUP: "tak", DELIVERY: "del"}

# Known-good branches from the live research phase (api-map.md "Pickup
# flow"/"Delivery flow" and the Jeddah re-test) - used only as a DEFAULT
# pre-selection when present in the live getStoreList response, never as
# a hardcoded substitute for it.
KNOWN_DEFAULT_STORE_IDS: dict[str, tuple[int, ...]] = {
    PICKUP: (24, 97),      # Riyadh EUROMARCHE-H, Jeddah TAHLIA-H
    DELIVERY: (5796, 7),   # Riyadh Sulimanya-H, Jeddah ANDALOS-WH
}


@dataclass(frozen=True)
class ChannelContext:
    """Everything downstream menu/product calls need for one channel. Two
    ChannelContext instances (one PICKUP, one DELIVERY) are always kept as
    separate objects, even on the same store list snapshot - see
    ../research/api-map/api-map.md 'Channel separation mechanism': prices
    happened to be identical in every branch tested, but this app never
    assumes that going in - it fetches and labels each channel's own
    result independently (see comparison_service.py)."""

    service: str          # "PICKUP" | "DELIVERY"
    city_id: int
    city_name: str
    store_id: int
    store_name: str
    menu_temp_id: int | None
    cluster_id: str
    menu_config_id: str

    @property
    def cache_key(self) -> tuple:
        """A hashable key identifying this exact channel+branch+cluster
        combination - used as part of the cache key for menu/product
        service calls (see menu_service.py) so switching store or service
        never silently reuses another branch's cached data."""
        return (self.service, self.store_id, self.cluster_id, self.menu_config_id)


def list_cities(stores_by_city: list[dict]) -> list[dict]:
    """`stores_by_city` is the raw list from HardeesApiClient.get_store_list().
    Returns [{cityId, cityName, storeCount}], sorted by name, for the
    City selectbox."""
    out = []
    for city in stores_by_city:
        stores = city.get("store") or []
        out.append({
            "cityId": city.get("cityId"),
            "cityName": city.get("name_en") or city.get("cityName") or f"City {city.get('cityId')}",
            "storeCount": len(stores),
        })
    out.sort(key=lambda c: (c["cityName"] or ""))
    return out


def list_stores(stores_by_city: list[dict], city_id: int, service: str | None = None) -> list[dict]:
    """Stores for one city, optionally filtered to those whose 'services'
    flags support `service`. Each returned dict is the raw store object
    from getStoreList (storeId, name_en, active, cmsStatus, services,
    location, menuTempId, promiseTime, ...) - the Store selectbox reads
    directly from this, so any field getStoreList adds in the future shows
    up automatically without a code change."""
    city = next((c for c in stores_by_city if c.get("cityId") == city_id), None)
    if not city:
        return []
    stores = city.get("store") or []
    if service:
        flag = _SERVICE_FLAG.get(service)
        if flag:
            stores = [s for s in stores if (s.get("services") or {}).get(flag) == 1]
    return sorted(stores, key=lambda s: (s.get("name_en") or ""))


def pick_default_store(stores: list[dict], service: str) -> dict | None:
    """Prefers a known-good store id (see KNOWN_DEFAULT_STORE_IDS) if it is
    present in `stores`; otherwise falls back to the first active,
    CMS-published store in the list. Returns None if `stores` is empty."""
    if not stores:
        return None
    known_ids = KNOWN_DEFAULT_STORE_IDS.get(service, ())
    for known_id in known_ids:
        for store in stores:
            if store.get("storeId") == known_id:
                return store
    for store in stores:
        if store.get("active") == 1 and store.get("cmsStatus") == 1:
            return store
    return stores[0]


def resolve_channel_context(
    client: HardeesApiClient, service: str, city: dict, store: dict,
) -> ChannelContext:
    """Calls getMenuConfig(orderType=service, storeId=store['storeId'])
    and packages the result with the store's own city/name/menuTempId
    into a ChannelContext. This is the one place `storeId` is passed into
    getMenuConfig - matching api-map.md 'Branch selection' (an explicit
    City/Store pair is a documented, valid way to resolve a branch,
    alongside the geolocation-based getNewStore/validateLocation flows
    used during the research phase, which need real coordinates this
    preview UI does not collect from the user)."""
    menu_config = client.get_menu_config(order_type=service, store_id=store.get("storeId"))
    return ChannelContext(
        service=service,
        city_id=city.get("cityId"),
        city_name=city.get("cityName") or "",
        store_id=store.get("storeId"),
        store_name=store.get("name_en") or "",
        menu_temp_id=store.get("menuTempId"),
        cluster_id=menu_config.get("clusterId", ""),
        menu_config_id=menu_config.get("menuConfigId", ""),
    )
