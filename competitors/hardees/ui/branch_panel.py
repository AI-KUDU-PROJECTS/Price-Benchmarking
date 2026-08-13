"""
competitors/hardees/ui/branch_panel.py
---------------------------------------------------------------------
"Branch and service selection" - rendered in the SIDEBAR, mirroring
competitors/kfc/dashboard/page.py's `st.sidebar.header("Filters")`
pattern (KFC puts every filter/selection control in the sidebar and
keeps the main body for read-only tabbed output - see
../../research/api-map/api-map.md "Streamlit live API preview"). Options
are populated live from getStoreList, never hardcoded, and BOTH Pickup
and Delivery are always resolved (not just whichever one is "active"),
since the rest of the page (and the comparison tab) needs both at once -
see services/comparison_service.py's docstring for why neither channel
is ever assumed to equal the other.
---------------------------------------------------------------------
"""
from __future__ import annotations

import streamlit as st

from competitors.hardees.api.client import HardeesApiClient, HardeesApiError
from competitors.hardees.services import branch_service
from competitors.hardees.services.branch_service import ChannelContext
from competitors.hardees.services.sanitize import error_message
from competitors.hardees.ui import state as ui_state


@st.cache_data(show_spinner="Loading city/branch directory (getStoreList)...")
def _cached_store_list(_client: HardeesApiClient) -> list[dict]:
    return _client.get_store_list()


@st.cache_data(show_spinner=False)
def _cached_channel_context(
    _client: HardeesApiClient, service: str, city_id: int, city_name: str,
    store_id: int, store_name: str, menu_temp_id: int | None,
) -> ChannelContext:
    # Re-packaged as a plain dict->ChannelContext call so the cache key is
    # exactly the hashable scalars that determine the result - the actual
    # network call (getMenuConfig) happens inside resolve_channel_context.
    fake_city = {"cityId": city_id, "cityName": city_name}
    fake_store = {"storeId": store_id, "name_en": store_name, "menuTempId": menu_temp_id}
    return branch_service.resolve_channel_context(_client, service, fake_city, fake_store)


def clear_cache() -> None:
    _cached_store_list.clear()
    _cached_channel_context.clear()


def render(client: HardeesApiClient) -> tuple[ChannelContext | None, ChannelContext | None, str]:
    """Renders City + Pickup/Delivery store selectors in `st.sidebar` and
    returns (pickup_ctx, delivery_ctx, active_service). Both channels are
    always resolved so the page can mirror KFC's fixed Pickup/Delivery
    tabs. `active_service` defaults to PICKUP for callers that still expect
    a third return value."""
    st.sidebar.header("Branch & Service")

    try:
        stores_by_city = _cached_store_list(client)
    except HardeesApiError as e:
        st.sidebar.error(f"Could not load the branch directory: {error_message(e)}")
        return None, None, branch_service.PICKUP

    cities = branch_service.list_cities(stores_by_city)
    if not cities:
        st.sidebar.warning("getStoreList returned no cities.")
        return None, None, branch_service.PICKUP

    city_labels = [f"{c['cityName']} ({c['storeCount']} stores)" for c in cities]
    default_city_idx = next((i for i, c in enumerate(cities) if c["cityName"].strip().lower() == "riyadh"), 0)

    city_idx = st.sidebar.selectbox(
        "City", options=range(len(cities)), format_func=lambda i: city_labels[i],
        index=default_city_idx, key="hardees_city_idx",
    )
    selected_city = cities[city_idx]

    pickup_stores = branch_service.list_stores(stores_by_city, selected_city["cityId"], branch_service.PICKUP)
    delivery_stores = branch_service.list_stores(stores_by_city, selected_city["cityId"], branch_service.DELIVERY)
    st.sidebar.caption(
        f"{len(pickup_stores)} Pickup-capable / {len(delivery_stores)} Delivery-capable "
        f"stores in {selected_city['cityName']}"
    )

    pickup_ctx = delivery_ctx = None

    if pickup_stores:
        default_pickup = branch_service.pick_default_store(pickup_stores, branch_service.PICKUP)
        pickup_labels = [s.get("name_en") or f"Store {s.get('storeId')}" for s in pickup_stores]
        default_idx = pickup_stores.index(default_pickup) if default_pickup in pickup_stores else 0
        p_idx = st.sidebar.selectbox(
            "Pickup store", options=range(len(pickup_stores)),
            format_func=lambda i: pickup_labels[i], index=default_idx, key="hardees_pickup_store_idx",
        )
        store = pickup_stores[p_idx]
        try:
            pickup_ctx = _cached_channel_context(
                client, branch_service.PICKUP, selected_city["cityId"], selected_city["cityName"],
                store.get("storeId"), store.get("name_en") or "", store.get("menuTempId"),
            )
            ui_state.register_ctx(pickup_ctx)
        except HardeesApiError as e:
            st.sidebar.error(f"getMenuConfig(PICKUP) failed: {error_message(e)}")
    else:
        st.sidebar.info("No Pickup-capable store in this city.")

    if delivery_stores:
        default_delivery = branch_service.pick_default_store(delivery_stores, branch_service.DELIVERY)
        delivery_labels = [s.get("name_en") or f"Store {s.get('storeId')}" for s in delivery_stores]
        default_idx = delivery_stores.index(default_delivery) if default_delivery in delivery_stores else 0
        d_idx = st.sidebar.selectbox(
            "Delivery store", options=range(len(delivery_stores)),
            format_func=lambda i: delivery_labels[i], index=default_idx, key="hardees_delivery_store_idx",
        )
        store = delivery_stores[d_idx]
        try:
            delivery_ctx = _cached_channel_context(
                client, branch_service.DELIVERY, selected_city["cityId"], selected_city["cityName"],
                store.get("storeId"), store.get("name_en") or "", store.get("menuTempId"),
            )
            ui_state.register_ctx(delivery_ctx)
        except HardeesApiError as e:
            st.sidebar.error(f"getMenuConfig(DELIVERY) failed: {error_message(e)}")
    else:
        st.sidebar.info("No Delivery-capable store in this city.")

    return pickup_ctx, delivery_ctx, branch_service.PICKUP
