"""Read-only restaurant exports for API consumers, protected by a separate key."""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bff.contract import (
    KNOWN_BRANDS, Brand, Channel, ContractModel, Freshness, Product, Promotion,
    freshness_from_timestamp, now_riyadh_iso, parse_utc,
)
from bff.menu import menu_sort_key
from bff.registry import get_adapter

bearer_auth = HTTPBearer(auto_error=False, scheme_name="RestaurantBearerToken")


def require_bearer_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth)) -> None:
    expected = os.environ.get("SHARED_API_KEY_SHA256", "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise HTTPException(status_code=503, detail="Restaurant sharing is not configured.")
    key = credentials.credentials if credentials else ""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if not key or not hmac.compare_digest(digest, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.",
                            headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(tags=["Restaurant sharing"], dependencies=[Depends(require_bearer_token)])


class SharedProduct(Product):
    effective_price: float | None = None


class RestaurantChannel(ContractModel):
    data_freshness: Freshness
    observed_at: str | None = None
    source_run_ids: list[str]
    product_count: int
    products: list[SharedProduct]
    promotions: list[Promotion]


class RestaurantData(ContractModel):
    restaurant: Brand
    channels: dict[Channel, RestaurantChannel]
    generated_at: str


def _image_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("//"):
        value = f"{urlsplit(base_url).scheme}:{value}"
    if value.startswith("/"):
        return f"{base_url.rstrip('/')}{value}"
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


@router.get("/restaurants/{brand_id}", response_model=RestaurantData)
def restaurant_data(brand_id: str, request: Request, response: Response) -> RestaurantData:
    """All supported channels and their latest saved products and active offers.

    No pagination and no new collection. observedAt is the channel's data time;
    generatedAt is the response time. Empty channels have unavailable freshness.
    Image URLs are absolute; missing images remain null. This is a current-menu
    export, not a historical export. Authenticate with Authorization: Bearer <token>.
    """
    response.headers["Cache-Control"] = "private, no-store"
    if brand_id not in dict(KNOWN_BRANDS):
        raise HTTPException(status_code=404, detail="Unknown restaurant.")
    adapter = get_adapter(brand_id)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Restaurant data is unavailable.")
    try:
        brand = adapter.get_brand()
        products = adapter.list_products()
        promotions = adapter.list_promotions(status="active")
    except (OSError, sqlite3.Error, ValueError):
        raise HTTPException(status_code=503, detail="Restaurant data is unavailable.") from None

    base_url = os.environ.get("SHARED_API_BASE_URL", "").strip() or str(request.base_url)
    channels: dict[Channel, RestaurantChannel] = {}
    for channel in dict.fromkeys(brand.channels):
        items = sorted((item for item in products if item.channel == channel), key=menu_sort_key)
        observations = [item.observed_at for item in items if parse_utc(item.observed_at)]
        observed_at = max(observations, key=parse_utc, default=None)
        channels[channel] = RestaurantChannel(
            data_freshness=freshness_from_timestamp(observed_at),
            observed_at=observed_at,
            source_run_ids=sorted({item.source_run_id for item in items if item.source_run_id}),
            product_count=len(items),
            products=[SharedProduct(**{
                **item.model_dump(),
                "image_url": _image_url(item.image_url, base_url),
                "effective_price": item.special_price if item.special_price is not None else item.regular_price,
            }) for item in items],
            promotions=[item.model_copy(update={"image_url": _image_url(item.image_url, base_url)})
                        for item in promotions if item.channel == channel and item.status == "active"],
        )
    return RestaurantData(restaurant=brand, channels=channels, generated_at=now_riyadh_iso())
