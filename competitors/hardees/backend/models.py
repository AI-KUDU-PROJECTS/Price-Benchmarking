"""
competitors/hardees/backend/models.py
---------------------------------------------------------------------
Shared constants and light dataclasses used across backend/*. Keeping the
event-type / status vocabularies in exactly one place means
change_detector.py, excel_exporter.py, and app.py can never drift apart on
spelling.
---------------------------------------------------------------------
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# --- Run status ------------------------------------------------------------
RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_SUCCESS = "SUCCESS"
RUN_STATUS_PARTIAL = "PARTIAL"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUSES = (RUN_STATUS_RUNNING, RUN_STATUS_SUCCESS, RUN_STATUS_PARTIAL, RUN_STATUS_FAILED)

# --- Entity status (products / offers dimension tables) --------------------
ENTITY_STATUS_ACTIVE = "ACTIVE"
ENTITY_STATUS_NOT_OBSERVED = "NOT_OBSERVED"
ENTITY_STATUS_REMOVED = "REMOVED"       # products
ENTITY_STATUS_ENDED = "ENDED"           # offers
ENTITY_STATUS_RETURNED = "RETURNED"

# --- Change event types (see README "Change Detection Engine") -------------
EVENT_NEW_PRODUCT = "NEW_PRODUCT"
EVENT_NEW_IN_CHANNEL = "NEW_IN_CHANNEL"
EVENT_NEW_OFFER = "NEW_OFFER"
EVENT_OFFER_CHANGED = "OFFER_CHANGED"
EVENT_OFFER_NOT_OBSERVED = "OFFER_NOT_OBSERVED"
EVENT_OFFER_ENDED = "OFFER_ENDED"
EVENT_PRICE_INCREASE = "PRICE_INCREASE"
EVENT_PRICE_DECREASE = "PRICE_DECREASE"
EVENT_REGULAR_PRICE_CHANGED = "REGULAR_PRICE_CHANGED"
EVENT_SPECIAL_PRICE_CHANGED = "SPECIAL_PRICE_CHANGED"
EVENT_PRODUCT_NOT_OBSERVED = "PRODUCT_NOT_OBSERVED"
EVENT_PRODUCT_REMOVED = "PRODUCT_REMOVED"
EVENT_PRODUCT_RETURNED = "PRODUCT_RETURNED"
EVENT_OFFER_RETURNED = "OFFER_RETURNED"
EVENT_AVAILABILITY_CHANGED = "AVAILABILITY_CHANGED"
EVENT_DETAILS_CHANGED = "DETAILS_CHANGED"
EVENT_CATEGORY_CHANGED = "CATEGORY_CHANGED"

ALL_EVENT_TYPES = (
    EVENT_NEW_PRODUCT, EVENT_NEW_IN_CHANNEL, EVENT_NEW_OFFER, EVENT_OFFER_CHANGED,
    EVENT_OFFER_NOT_OBSERVED, EVENT_OFFER_ENDED, EVENT_PRICE_INCREASE, EVENT_PRICE_DECREASE,
    EVENT_REGULAR_PRICE_CHANGED, EVENT_SPECIAL_PRICE_CHANGED, EVENT_PRODUCT_NOT_OBSERVED,
    EVENT_PRODUCT_REMOVED, EVENT_PRODUCT_RETURNED, EVENT_OFFER_RETURNED,
    EVENT_AVAILABILITY_CHANGED, EVENT_DETAILS_CHANGED, EVENT_CATEGORY_CHANGED,
)

# Event types that should trigger a screenshot capture job (spec: "Capture
# screenshots only for NEW_PRODUCT / NEW_OFFER").
SCREENSHOT_TRIGGER_EVENTS = (EVENT_NEW_PRODUCT, EVENT_NEW_OFFER)

# Colors for the Daily Changes tab (spec: "Use simple colors").
EVENT_COLOR_GREEN = "green"     # New / Price Decrease
EVENT_COLOR_RED = "red"         # Price Increase / Removed
EVENT_COLOR_ORANGE = "orange"   # Not Observed / Potential End
EVENT_COLOR_BLUE = "blue"       # Details Changed
EVENT_COLOR_GRAY = "gray"       # No change / neutral

EVENT_COLOR_MAP = {
    EVENT_NEW_PRODUCT: EVENT_COLOR_GREEN,
    EVENT_NEW_IN_CHANNEL: EVENT_COLOR_GREEN,
    EVENT_NEW_OFFER: EVENT_COLOR_GREEN,
    EVENT_PRICE_DECREASE: EVENT_COLOR_GREEN,
    EVENT_PRODUCT_RETURNED: EVENT_COLOR_GREEN,
    EVENT_OFFER_RETURNED: EVENT_COLOR_GREEN,
    EVENT_PRICE_INCREASE: EVENT_COLOR_RED,
    EVENT_PRODUCT_REMOVED: EVENT_COLOR_RED,
    EVENT_OFFER_ENDED: EVENT_COLOR_RED,
    EVENT_PRODUCT_NOT_OBSERVED: EVENT_COLOR_ORANGE,
    EVENT_OFFER_NOT_OBSERVED: EVENT_COLOR_ORANGE,
    EVENT_DETAILS_CHANGED: EVENT_COLOR_BLUE,
    EVENT_OFFER_CHANGED: EVENT_COLOR_BLUE,
    EVENT_CATEGORY_CHANGED: EVENT_COLOR_BLUE,
    EVENT_AVAILABILITY_CHANGED: EVENT_COLOR_BLUE,
    EVENT_REGULAR_PRICE_CHANGED: EVENT_COLOR_BLUE,
    EVENT_SPECIAL_PRICE_CHANGED: EVENT_COLOR_BLUE,
}

# --- Offer types (see README "Offer Details") -------------------------------
OFFER_TYPE_DISCOUNT = "Discount"
OFFER_TYPE_BUNDLE = "Bundle"
OFFER_TYPE_MEAL_DEAL = "Meal Deal"
OFFER_TYPE_BOGO = "Buy One Get One"
OFFER_TYPE_LIMITED_EDITION = "Limited Edition"
OFFER_TYPE_COUPON = "Coupon"
OFFER_TYPE_PROGRESSIVE_PROMOTION = "Progressive Promotion"
OFFER_TYPE_UNKNOWN = "Unknown"

ALL_OFFER_TYPES = (
    OFFER_TYPE_DISCOUNT, OFFER_TYPE_BUNDLE, OFFER_TYPE_MEAL_DEAL, OFFER_TYPE_BOGO,
    OFFER_TYPE_LIMITED_EDITION, OFFER_TYPE_COUPON, OFFER_TYPE_PROGRESSIVE_PROMOTION,
    OFFER_TYPE_UNKNOWN,
)

# Human-facing label for a product/offer not observed for 3 successful runs
# (spec: 'Do not use the word "Discontinued" as a confirmed fact').
NOT_OBSERVED_DISPLAY_LABEL = "Removed / Not observed for 3 successful runs"


@dataclass
class ChannelResult:
    """Mirrors the JSON one Node channel-collector run writes to disk."""

    channel: str
    status: str
    branch_id: int
    branch_name: str
    city: str
    started_at: str
    finished_at: str
    api_config_id: Optional[str]
    cluster_id: Optional[str]
    expected_category_count: int
    category_count: int
    completion_percentage: float
    product_count: int
    products: list[dict[str, Any]] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    category_results: list[dict[str, Any]] = field(default_factory=list)
    promotions: list[dict[str, Any]] = field(default_factory=list)
    branch_currently_closed: bool = False
    error_message: Optional[str] = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ChannelResult":
        return cls(
            channel=data["channel"],
            status=data["status"],
            branch_id=data.get("branchId"),
            branch_name=data.get("branchName"),
            city=data.get("city"),
            started_at=data.get("startedAt"),
            finished_at=data.get("finishedAt"),
            api_config_id=data.get("apiConfigId"),
            cluster_id=data.get("clusterId"),
            expected_category_count=data.get("expectedCategoryCount", 0),
            category_count=data.get("categoryCount", 0),
            completion_percentage=data.get("completionPercentage", 0),
            product_count=data.get("productCount", 0),
            products=data.get("products") or [],
            categories=data.get("categories") or [],
            category_results=data.get("categoryResults") or [],
            promotions=data.get("promotions") or [],
            branch_currently_closed=bool(data.get("branchCurrentlyClosed")),
            error_message=data.get("errorMessage"),
        )
