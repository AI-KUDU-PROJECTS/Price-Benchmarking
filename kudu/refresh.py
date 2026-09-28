"""Refresh KUDU's local baseline from the production read-only APIs.

Set KUDU_API_USERNAME and KUDU_API_PASSWORD in the environment or .env,
then run ``python -m kudu.refresh``. Credentials never enter the snapshot.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from kudu.catalog import CHANNELS, save_catalog

BASE_URL = "https://api-prod.kudu.com.sa/userStore/api/v1/external"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _data(response: httpx.Response, endpoint: str) -> list[dict[str, Any]]:
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("statusCode") != 200 or not isinstance(body.get("data"), list):
        raise ValueError(f"KUDU {endpoint} returned an unexpected body")
    return body["data"]



def _get(client: httpx.Client, endpoint: str, params: dict[str, Any]) -> httpx.Response:
    """Retry transient GET failures; never retry an auth or schema error."""
    for attempt in range(3):
        try:
            response = client.get(f"{BASE_URL}/{endpoint}", params=params)
        except httpx.TransportError:
            if attempt == 2:
                raise
        else:
            if response.status_code not in RETRYABLE_STATUS or attempt == 2:
                return response
        time.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("KUDU API retry loop did not finish")


def fetch_catalog(username: str, password: str) -> dict[str, Any]:
    services: dict[str, list[dict[str, Any]]] = {}
    with httpx.Client(auth=httpx.BasicAuth(username, password), headers={"accept": "application/json"}, timeout=30) as client:
        for channel in CHANNELS:
            menus = _data(
                _get(client, "menuList", {"templateId": 1, "servicesType": channel}),
                "menuList",
            )
            if not menus:
                raise ValueError(f"KUDU {channel} menu is empty")
            categories = []
            for menu in menus:
                items = _data(
                    _get(client, "itemList", {"templateId": 1, "menuId": menu["menuId"], "servicesType": channel}),
                    "itemList",
                )
                categories.append({"menu": menu, "items": items})
            services[channel] = categories
    return {
        "retrievedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "templateId": 1,
        "services": services,
    }


def main() -> None:
    load_dotenv()
    username = os.getenv("KUDU_API_USERNAME")
    password = os.getenv("KUDU_API_PASSWORD")
    if not username or not password:
        raise SystemExit("Set KUDU_API_USERNAME and KUDU_API_PASSWORD before refreshing KUDU data.")
    raw = fetch_catalog(username, password)
    path = save_catalog(raw)
    counts = {channel: sum(len(category["items"]) for category in raw["services"][channel]) for channel in CHANNELS}
    print(f"KUDU catalog updated: {path} | delivery={counts['delivery']} pickup={counts['pickup']}")


if __name__ == "__main__":
    main()
