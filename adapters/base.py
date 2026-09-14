"""Brand adapter protocol. BFF depends on this, never on restaurant SQL."""
from __future__ import annotations

from typing import Protocol

from bff.contract import (
    Brand,
    BrandOverview,
    ChangeEvent,
    Channel,
    Product,
    ProductHistory,
    Promotion,
)


class BrandAdapter(Protocol):
    brand_id: str

    def get_brand(self) -> Brand: ...

    def get_overview(self) -> BrandOverview: ...

    def list_products(
        self,
        *,
        channel: Channel | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Product]: ...

    def get_product(self, product_id: str) -> Product | None: ...

    def get_product_history(self, product_id: str) -> ProductHistory | None: ...

    def list_promotions(
        self,
        *,
        channel: Channel | None = None,
        status: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Promotion]: ...

    def get_promotion(self, promotion_id: str) -> Promotion | None: ...

    def list_changes(
        self,
        *,
        channel: Channel | None = None,
        event_type: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[ChangeEvent]: ...

    def get_change(self, change_id: str) -> ChangeEvent | None: ...
