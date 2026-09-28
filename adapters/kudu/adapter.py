"""Expose KUDU's own production menu snapshot through the shared BFF contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bff.contract import (
    Brand, BrandCapabilities, BrandOverview, ChangeEvent, Channel, CollectionRun,
    Observation, Product, ProductHistory, Promotion, as_money,
    freshness_from_timestamp, to_riyadh_iso,
)
from kudu.catalog import CATALOG_PATH, CHANNELS


class KuduAdapter:
    brand_id = "kudu"

    def __init__(self, catalog_path: Path = CATALOG_PATH) -> None:
        self.catalog_path = Path(catalog_path)

    def _catalog(self) -> dict[str, Any] | None:
        if not self.catalog_path.exists():
            return None
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))

    def get_brand(self) -> Brand:
        catalog = self._catalog()
        timestamp = catalog.get("retrievedAtUtc") if catalog else None
        freshness = freshness_from_timestamp(timestamp)
        return Brand(
            id=self.brand_id,
            name="KUDU",
            health="healthy" if freshness == "fresh" else "stale" if freshness == "stale" else "error",
            last_successful_run_at=to_riyadh_iso(timestamp),
            data_freshness=freshness,
            capabilities=BrandCapabilities(has_discount=False, has_size_prices=False, has_images=True),
            channels=["delivery", "pickup"],
            location_label="KUDU production menu · template 1",
        )

    def _products(self) -> list[Product]:
        catalog = self._catalog()
        if not catalog:
            return []
        observed = to_riyadh_iso(catalog["retrievedAtUtc"])
        products: list[Product] = []
        for channel in CHANNELS:
            categories = sorted(catalog["services"][channel], key=lambda c: c.get("displayOrder") or 0)
            for category in categories:
                for item in category["items"]:
                    item_id = str(item["itemId"])
                    products.append(Product(
                        id=f"{channel}-{item_id}",
                        brand_id=self.brand_id,
                        source_id=item_id,
                        name_ar=item.get("nameArabic") or None,
                        name_en=item.get("nameEnglish") or None,
                        category=category.get("titleEnglish") or category.get("titleArabic"),
                        category_ar=category.get("titleArabic") or None,
                        image_url=item.get("itemImageUrl") or None,
                        channel=channel,
                        location=None,
                        regular_price=as_money(item.get("price")),
                        special_price=None,
                        currency="SAR",
                        availability=item.get("isAvailable"),
                        is_published=item.get("isPublish"),
                        is_hidden=item.get("isHidden"),
                        description_ar=item.get("descriptionArabic") or None,
                        description_en=item.get("descriptionEnglish") or None,
                        calories=item.get("calories"),
                        status="active" if item.get("status") == "active" else "removed",
                        first_seen_at=observed,
                        last_seen_at=observed,
                        observed_at=observed,
                        source_run_id=f"kudu-{channel}-{catalog['retrievedAtUtc']}",
                    ))
        return products

    def get_overview(self) -> BrandOverview:
        brand = self.get_brand()
        catalog = self._catalog()
        products = self._products()
        observed = brand.last_successful_run_at
        runs = [
            CollectionRun(
                id=f"kudu-{channel}-{catalog['retrievedAtUtc']}",
                brand_id=self.brand_id,
                status="success",
                started_at=observed,
                completed_at=observed,
                channel=channel,
                location=None,
                item_count=sum(len(category["items"]) for category in catalog["services"][channel]),
            )
            for channel in CHANNELS
        ] if catalog else []
        return BrandOverview(
            brand=brand,
            runs=runs,
            product_count=len(products),
            promotion_count=len(self.list_promotions()),
            recent_changes=[],
            highlights=[],
        )

    def list_products(
        self, *, channel: Channel | None = None, category: str | None = None,
        query: str | None = None,
    ) -> list[Product]:
        products = self._products()
        if channel:
            products = [p for p in products if p.channel == channel]
        if category:
            products = [p for p in products if (p.category or "").casefold() == category.casefold()]
        if query:
            term = query.casefold().strip()
            products = [p for p in products if term in " ".join((p.name_ar or "", p.name_en or "", p.category or "", p.category_ar or "")).casefold()]
        return products

    def get_product(self, product_id: str) -> Product | None:
        return next((p for p in self._products() if p.id == product_id), None)

    def get_product_history(self, product_id: str) -> ProductHistory | None:
        product = self.get_product(product_id)
        if product is None:
            return None
        return ProductHistory(
            product=product,
            observations=[Observation(
                observed_at=product.observed_at,
                source_run_id=product.source_run_id,
                channel=product.channel,
                regular_price=product.regular_price,
                availability=product.availability,
                image_url=product.image_url,
            )],
        )

    def list_promotions(
        self, *, channel: Channel | None = None, status: str | None = None,
        category: str | None = None, query: str | None = None,
    ) -> list[Promotion]:
        # The API has a Special Offers category, but no original price or
        # discount. Expose its items as offers without inventing savings.
        offers = [
            Promotion(
                id=product.id,
                brand_id=self.brand_id,
                product_id=product.id,
                title=product.name_en or product.name_ar,
                image_url=product.image_url,
                status="active",
                promotional_price=product.regular_price,
                channel=product.channel,
                source="KUDU Special Offers menu",
                category=product.category,
                first_seen_at=product.first_seen_at,
                last_seen_at=product.last_seen_at,
            )
            for product in self._products()
            if product.category == "Special Offers"
        ]
        if channel:
            offers = [p for p in offers if p.channel == channel]
        if status:
            offers = [p for p in offers if p.status == status]
        if category:
            offers = [p for p in offers if (p.category or "").casefold() == category.casefold()]
        if query:
            term = query.casefold().strip()
            offers = [p for p in offers if term in (p.title or "").casefold()]
        return offers

    def get_promotion(self, promotion_id: str) -> Promotion | None:
        return next((p for p in self.list_promotions() if p.id == promotion_id), None)

    def list_changes(
        self, *, channel: Channel | None = None, event_type: str | None = None,
        category: str | None = None, date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[ChangeEvent]:
        # A single collected snapshot cannot prove a change over time.
        return []

    def get_change(self, change_id: str) -> ChangeEvent | None:
        return None
