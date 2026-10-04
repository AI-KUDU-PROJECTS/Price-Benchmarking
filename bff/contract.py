"""Shared frontend-facing contract.

Brand-agnostic types used by the BFF and every restaurant adapter.
JSON is serialized in camelCase. Nullable numbers mean unknown — never zero.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

TIMEZONE_NAME = "Asia/Riyadh"
RIYADH = ZoneInfo(TIMEZONE_NAME)
STALE_AFTER = timedelta(hours=30)

Health = Literal["healthy", "partial", "stale", "error", "disconnected"]
Freshness = Literal["fresh", "stale", "unavailable"]
Channel = Literal["pickup", "delivery", "hungerstation"]
ProductStatus = Literal["active", "not_observed", "removed", "returned"]
PromotionStatus = Literal["active", "not_observed", "ended", "returned"]
RunStatus = Literal["running", "success", "partial", "failed"]
PricePosition = Literal["higher", "lower", "equal", "unavailable"]

EventType = Literal[
    "price_increased",
    "price_decreased",
    "product_added",
    "product_removed",
    "product_not_observed",
    "product_returned",
    "offer_started",
    "offer_ended",
    "offer_not_observed",
    "offer_returned",
    "offer_changed",
    "availability_changed",
    "new_in_channel",
    "regular_price_changed",
    "special_price_changed",
    "details_changed",
    "category_changed",
]

HIGHLIGHT_RANK: dict[str, int] = {
    "offer_started": 1,
    "price_decreased": 2,
    "offer_ended": 3,
    "product_added": 4,
    "price_increased": 5,
    "product_returned": 6,
    "offer_returned": 6,
    "availability_changed": 7,
}

SOURCE_EVENT_TO_CONTRACT: dict[str, EventType] = {
    "NEW_PRODUCT": "product_added",
    "NEW_IN_CHANNEL": "new_in_channel",
    "NEW_OFFER": "offer_started",
    "OFFER_CHANGED": "offer_changed",
    "OFFER_NOT_OBSERVED": "offer_not_observed",
    "OFFER_ENDED": "offer_ended",
    "PRICE_INCREASE": "price_increased",
    "PRICE_DECREASE": "price_decreased",
    "REGULAR_PRICE_CHANGED": "regular_price_changed",
    "SPECIAL_PRICE_CHANGED": "special_price_changed",
    "PRODUCT_NOT_OBSERVED": "product_not_observed",
    "PRODUCT_REMOVED": "product_removed",
    "PRODUCT_RETURNED": "product_returned",
    "OFFER_RETURNED": "offer_returned",
    "AVAILABILITY_CHANGED": "availability_changed",
    "DETAILS_CHANGED": "details_changed",
    "CATEGORY_CHANGED": "category_changed",
}

PRODUCT_STATUS_TO_CONTRACT: dict[str, ProductStatus] = {
    "ACTIVE": "active",
    "NOT_OBSERVED": "not_observed",
    "REMOVED": "removed",
    "RETURNED": "returned",
}

PROMOTION_STATUS_TO_CONTRACT: dict[str, PromotionStatus] = {
    "ACTIVE": "active",
    "NOT_OBSERVED": "not_observed",
    "ENDED": "ended",
    "RETURNED": "returned",
}

RUN_STATUS_TO_CONTRACT: dict[str, RunStatus] = {
    "RUNNING": "running",
    "SUCCESS": "success",
    "PARTIAL": "partial",
    "FAILED": "failed",
}

KNOWN_BRANDS: tuple[tuple[str, str], ...] = (
    ("kudu", "KUDU"),
    ("kfc", "KFC"),
    ("hardees", "Hardee's"),
    ("burger-king", "Burger King"),
    ("herfy", "Herfy"),
    ("mcdonalds", "McDonald's"),
    ("albaik", "AlBaik"),
)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class BrandCapabilities(ContractModel):
    has_discount: bool
    has_size_prices: bool
    has_images: bool


class Brand(ContractModel):
    id: str
    name: str
    health: Health
    last_successful_run_at: str | None = None
    data_freshness: Freshness
    capabilities: BrandCapabilities
    channels: list[Channel]
    location_label: str | None = None


class ProductSize(ContractModel):
    label: str
    price: float | None = None
    currency: str | None = None


class Product(ContractModel):
    id: str
    brand_id: str
    source_id: str
    name_ar: str | None = None
    name_en: str | None = None
    category: str | None = None
    category_ar: str | None = None
    image_url: str | None = None
    channel: Channel
    location: str | None = None
    regular_price: float | None = None
    special_price: float | None = None
    previous_regular_price: float | None = None
    previous_special_price: float | None = None
    currency: str | None = None
    sizes: list[ProductSize] = Field(default_factory=list)
    availability: bool | None = None
    is_published: bool | None = None
    is_hidden: bool | None = None
    description_ar: str | None = None
    description_en: str | None = None
    calories: int | None = None
    status: ProductStatus
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    observed_at: str | None = None
    source_run_id: str | None = None


class Promotion(ContractModel):
    id: str
    brand_id: str
    product_id: str | None = None
    title: str | None = None
    image_url: str | None = None
    status: PromotionStatus
    is_new: bool = False
    regular_price: float | None = None
    promotional_price: float | None = None
    discount_percent: float | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    channel: Channel
    source: str | None = None
    category: str | None = None


class ChangeEvent(ContractModel):
    id: str
    brand_id: str
    product_id: str | None = None
    promotion_id: str | None = None
    type: EventType
    title: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    percentage_change: float | None = None
    detected_at: str
    channel: Channel
    location: str | None = None
    source_run_id: str | None = None
    category: str | None = None


class CollectionRun(ContractModel):
    id: str
    brand_id: str
    status: RunStatus
    started_at: str | None = None
    completed_at: str | None = None
    channel: Channel
    location: str | None = None
    item_count: int | None = None
    warning_count: int | None = None
    error_summary: str | None = None


class Observation(ContractModel):
    observed_at: str | None = None
    source_run_id: str | None = None
    channel: Channel
    regular_price: float | None = None
    special_price: float | None = None
    availability: bool | None = None
    image_url: str | None = None
    sizes: list[ProductSize] = Field(default_factory=list)


class ProductHistory(ContractModel):
    product: Product
    observations: list[Observation] = Field(default_factory=list)


class Highlight(ContractModel):
    id: str
    rank: int
    type: EventType
    title: str
    summary: str | None = None
    brand_id: str
    href: str
    detected_at: str
    channel: Channel
    change_id: str
    product_id: str | None = None
    promotion_id: str | None = None


class ListMeta(ContractModel):
    page: int
    page_size: int
    total: int
    freshness: Freshness
    source_run_ids: list[str] = Field(default_factory=list)
    generated_at: str
    timezone: str = TIMEZONE_NAME


class BrandStatusRow(ContractModel):
    brand: Brand
    product_count: int | None = None
    promotion_count: int | None = None
    change_count: int | None = None


class MarketCounts(ContractModel):
    price_decreases: int = 0
    price_increases: int = 0
    new_products: int = 0
    new_offers: int = 0
    ended_offers: int = 0


class MarketOverview(ContractModel):
    last_updated_at: str | None = None
    freshness: Freshness
    connected_brand_ids: list[str]
    counts: MarketCounts
    highlights: list[Highlight]
    brands: list[BrandStatusRow]


class BrandOverview(ContractModel):
    brand: Brand
    runs: list[CollectionRun]
    product_count: int
    promotion_count: int
    recent_changes: list[ChangeEvent]
    highlights: list[Highlight]

class MappingSelectionInput(ContractModel):
    brand_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)


class PriceMappingWrite(ContractModel):
    name: str = Field(min_length=1, max_length=120)
    channel: Channel
    kudu_product_id: str = Field(min_length=1)
    competitor_items: list[MappingSelectionInput] = Field(min_length=1)


class MappingProduct(ContractModel):
    brand_id: str
    brand_name: str
    product_id: str
    name_ar: str | None = None
    name_en: str | None = None
    category: str | None = None
    image_url: str | None = None
    effective_price: float | None = None
    currency: str | None = None
    missing: bool = False


class MappingCompetitor(MappingProduct):
    difference_amount: float | None = None
    difference_percentage: float | None = None
    price_position: PricePosition = "unavailable"


class PriceMapping(ContractModel):
    id: str
    name: str
    channel: Channel
    kudu_item: MappingProduct
    competitor_items: list[MappingCompetitor] = Field(default_factory=list)
    created_at: str
    updated_at: str


class PriceMappingList(ContractModel):
    items: list[PriceMapping] = Field(default_factory=list)



def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def to_riyadh_iso(value: str | datetime | None) -> str | None:
    """Convert a stored UTC timestamp to Asia/Riyadh ISO-8601 with offset."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        dt = parse_utc(value)
        if dt is None:
            return None
    local = dt.astimezone(RIYADH)
    return local.replace(microsecond=0).isoformat()


def now_riyadh() -> datetime:
    return datetime.now(tz=RIYADH)


def now_riyadh_iso() -> str:
    return now_riyadh().replace(microsecond=0).isoformat()


def as_money(value: Any) -> float | None:
    """Preserve unknown as None. Never coerce missing to 0."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def freshness_from_timestamp(last_success: str | None, now: datetime | None = None) -> Freshness:
    dt = parse_utc(last_success) if last_success and "T" in str(last_success) else None
    if last_success and dt is None:
        dt = parse_utc(last_success)
    if dt is None:
        return "unavailable"
    current = now or datetime.now(tz=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = current - dt
    return "fresh" if age <= STALE_AFTER else "stale"


def disconnected_brand(brand_id: str, name: str) -> Brand:
    return Brand(
        id=brand_id,
        name=name,
        health="disconnected",
        last_successful_run_at=None,
        data_freshness="unavailable",
        capabilities=BrandCapabilities(
            has_discount=False,
            has_size_prices=False,
            has_images=False,
        ),
        channels=[],
        location_label=None,
    )


def highlight_href(event: ChangeEvent) -> str:
    if event.promotion_id:
        return f"/competitors/{event.brand_id}/promotions/{event.promotion_id}"
    if event.product_id:
        return f"/competitors/{event.brand_id}/products/{event.product_id}"
    return f"/changes/{event.id}"


def select_highlights(events: list[ChangeEvent], limit: int = 12) -> list[Highlight]:
    """Rank supported facts. not_observed is never promoted."""
    ranked: list[tuple[int, ChangeEvent]] = []
    for event in events:
        rank = HIGHLIGHT_RANK.get(event.type)
        if rank is None:
            continue
        ranked.append((rank, event))
    ranked.sort(key=lambda item: (item[0], item[1].detected_at), reverse=True)
    ranked.sort(key=lambda item: item[0])
    ordered = [event for _, event in ranked]
    highlights: list[Highlight] = []
    for event in ordered[:limit]:
        rank = HIGHLIGHT_RANK[event.type]
        title = event.title or event.type.replace("_", " ")
        highlights.append(
            Highlight(
                id=f"hl-{event.id}",
                rank=rank,
                type=event.type,
                title=title,
                summary=_highlight_summary(event),
                brand_id=event.brand_id,
                href=highlight_href(event),
                detected_at=event.detected_at,
                channel=event.channel,
                change_id=event.id,
                product_id=event.product_id,
                promotion_id=event.promotion_id,
            )
        )
    return highlights


def _highlight_summary(event: ChangeEvent) -> str | None:
    parts = [event.channel]
    if event.before_value or event.after_value:
        parts.append(f"{event.before_value or '—'} → {event.after_value or '—'}")
    if event.percentage_change is not None:
        parts.append(f"{event.percentage_change:g}%")
    return " · ".join(parts) if parts else None


def dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, exclude_none=False)
