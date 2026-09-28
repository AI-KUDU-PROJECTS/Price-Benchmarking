"""Brand adapter overlay for the shared HungerStation mobile data store."""
from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from adapters.base import BrandAdapter
from bff.contract import (
    Brand,
    BrandCapabilities,
    BrandOverview,
    ChangeEvent,
    Channel,
    CollectionRun,
    Observation,
    Product,
    ProductHistory,
    Promotion,
    as_money,
    freshness_from_timestamp,
    select_highlights,
    to_riyadh_iso,
)
from competitors.hungerstation import config, database


def _public_id(source_id: str) -> str:
    return source_id.replace("|", "--")


def _source_id(public_id: str) -> str:
    return public_id.replace("--", "|")


def _normalize(value: str | None) -> str:
    return "".join(character.casefold() for character in (value or "") if character.isalnum())


def _image_map(base: BrandAdapter | None) -> dict[str, str]:
    if base is None:
        return {}
    images: dict[str, str] = {}
    for channel in ("pickup", "delivery"):
        try:
            products = base.list_products(channel=channel)  # type: ignore[arg-type]
        except (FileNotFoundError, sqlite3.Error):
            continue
        for product in products:
            if product.image_url:
                images.setdefault(_normalize(product.name_en or product.name_ar), product.image_url)
    return images


def _match_image(name: str | None, images: dict[str, str]) -> str | None:
    key = _normalize(name)
    if not key:
        return None
    exact = images.get(key)
    if exact:
        return exact
    best_key = max(
        images,
        key=lambda candidate: SequenceMatcher(None, key, candidate).ratio(),
        default=None,
    )
    if best_key is None:
        return None
    score = SequenceMatcher(None, key, best_key).ratio()
    return images[best_key] if score >= 0.86 else None


class HungerstationOverlayAdapter:
    """Merge HungerStation snapshots with an optional official-site adapter."""

    def __init__(
        self,
        *,
        brand_id: str,
        brand_name: str,
        base: BrandAdapter | None,
        db_path: Path = config.DB_PATH,
    ) -> None:
        self.brand_id = brand_id
        self.brand_name = brand_name
        self.base = base
        self.db_path = Path(db_path)

    def _base_brand(self) -> Brand | None:
        if self.base is None:
            return None
        return self.base.get_brand()

    def get_brand(self) -> Brand:
        base = self._base_brand()
        with database.readonly_connection(self.db_path) as db:
            latest = database.latest_run(db, self.brand_id)
            success = database.latest_run(db, self.brand_id, success_only=True)
        hs_time = to_riyadh_iso(success["finished_at"]) if success else None
        base_time = base.last_successful_run_at if base else None
        last_success = max((value for value in (base_time, hs_time) if value), default=None)
        freshness = freshness_from_timestamp(last_success)
        if base is None:
            health = "error" if success is None else "stale" if freshness == "stale" else "healthy"
        elif latest is not None and latest["status"] == "FAILED" and base.health == "healthy":
            health = "partial"
        else:
            health = base.health
        channels = [channel for channel in (base.channels if base else []) if channel != "hungerstation"]
        channels.append("hungerstation")
        return Brand(
            id=self.brand_id,
            name=self.brand_name,
            health=health,  # type: ignore[arg-type]
            last_successful_run_at=last_success,
            data_freshness=freshness,
            capabilities=BrandCapabilities(
                has_discount=True,
                has_size_prices=base.capabilities.has_size_prices if base else False,
                has_images=True,
            ),
            channels=channels,
            location_label=base.location_label if base else "HungerStation – Riyadh",
        )

    def get_overview(self) -> BrandOverview:
        products = self.list_products()
        promotions = self.list_promotions()
        changes = self.list_changes()
        runs: list[CollectionRun] = []
        if self.base is not None:
            try:
                runs.extend(run for run in self.base.get_overview().runs if run.channel != "hungerstation")
            except (FileNotFoundError, sqlite3.Error):
                pass
        runs.extend(self._runs())
        runs.sort(key=lambda run: run.started_at or "", reverse=True)
        recent = changes[:200]
        return BrandOverview(
            brand=self.get_brand(),
            runs=runs[:12],
            product_count=len(products),
            promotion_count=sum(1 for promotion in promotions if promotion.status == "active"),
            recent_changes=recent,
            highlights=select_highlights(recent),
        )

    def _runs(self) -> list[CollectionRun]:
        with database.readonly_connection(self.db_path) as db:
            rows = db.execute(
                "SELECT * FROM runs WHERE brand_id = ? ORDER BY started_at DESC LIMIT 20",
                (self.brand_id,),
            ).fetchall()
        return [
            CollectionRun(
                id=row["run_id"],
                brand_id=self.brand_id,
                status="success" if row["status"] == "SUCCESS" else "failed",
                started_at=to_riyadh_iso(row["started_at"]),
                completed_at=to_riyadh_iso(row["finished_at"]),
                channel="hungerstation",
                location="HungerStation – Riyadh",
                item_count=row["product_count"],
                error_summary=row["error_message"],
            )
            for row in rows
        ]

    def _hungerstation_products(self) -> list[Product]:
        with database.readonly_connection(self.db_path) as db:
            rows = database.latest_products(db, self.brand_id)
        images = _image_map(self.base)
        return [self._product(row, _match_image(row["name_en"], images)) for row in rows]

    def _product(self, row: sqlite3.Row | dict[str, Any], fallback_image: str | None = None) -> Product:
        data = dict(row)
        source_id = data["source_product_id"]
        return Product(
            id=_public_id(source_id),
            brand_id=self.brand_id,
            source_id=source_id,
            name_en=data.get("name_en"),
            category=data.get("category_name_en"),
            image_url=data.get("image_url") or fallback_image,
            channel="hungerstation",
            location="HungerStation – Riyadh",
            regular_price=as_money(data.get("regular_price")),
            special_price=as_money(data.get("special_price")),
            previous_regular_price=as_money(data.get("previous_regular_price")),
            previous_special_price=as_money(data.get("previous_special_price")),
            currency=data.get("currency") or "SAR",
            sizes=[],
            availability=bool(data["availability"]) if data.get("availability") is not None else None,
            description_en=data.get("description_en"),
            calories=data.get("calories"),
            status="active",
            first_seen_at=to_riyadh_iso(data.get("first_seen_at") or data.get("captured_at")),
            last_seen_at=to_riyadh_iso(data.get("last_seen_at") or data.get("captured_at")),
            observed_at=to_riyadh_iso(data.get("captured_at")),
            source_run_id=data.get("run_id"),
        )

    def list_products(
        self,
        *,
        channel: Channel | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Product]:
        products: list[Product] = []
        if channel != "hungerstation" and self.base is not None:
            try:
                products.extend(
                    product for product in self.base.list_products(channel=channel, category=category, query=query)
                    if product.channel != "hungerstation"
                )
            except (FileNotFoundError, sqlite3.Error):
                pass
        if channel in (None, "hungerstation"):
            products.extend(self._hungerstation_products())
        category_key = (category or "").casefold()
        query_key = (query or "").casefold()
        return [
            product for product in products
            if (not category_key or (product.category or "").casefold() == category_key)
            and (
                not query_key
                or query_key in (product.name_en or "").casefold()
                or query_key in (product.name_ar or "").casefold()
                or query_key in (product.category or "").casefold()
            )
        ]

    def get_product(self, product_id: str) -> Product | None:
        if product_id.startswith("HUNGERSTATION--"):
            return next((product for product in self._hungerstation_products() if product.id == product_id), None)
        return self.base.get_product(product_id) if self.base else None

    def get_product_history(self, product_id: str) -> ProductHistory | None:
        if not product_id.startswith("HUNGERSTATION--"):
            return self.base.get_product_history(product_id) if self.base else None
        product = self.get_product(product_id)
        if product is None:
            return None
        source_id = _source_id(product_id)
        with database.readonly_connection(self.db_path) as db:
            rows = database.observations(db, self.brand_id, source_id)
        images = _image_map(self.base)
        fallback = _match_image(product.name_en, images)
        observations = [
            Observation(
                observed_at=to_riyadh_iso(row["captured_at"]),
                source_run_id=row["run_id"],
                channel="hungerstation",
                regular_price=as_money(row["regular_price"]),
                special_price=as_money(row["special_price"]),
                availability=bool(row["availability"]) if row["availability"] is not None else None,
                image_url=row["image_url"] or fallback,
                sizes=[],
            )
            for row in rows
        ]
        return ProductHistory(product=product, observations=observations)

    def _hungerstation_promotions(self) -> list[Promotion]:
        promotions: list[Promotion] = []
        for product in self._hungerstation_products():
            if product.special_price is None:
                continue
            discount = None
            if product.regular_price:
                discount = round((product.regular_price - product.special_price) / product.regular_price * 100, 2)
            promotions.append(
                Promotion(
                    id=_public_id(product.source_id.replace("HUNGERSTATION|", "HUNGERSTATION|PROMO|", 1)),
                    brand_id=self.brand_id,
                    product_id=product.id,
                    title=product.name_en,
                    image_url=product.image_url,
                    status="active",
                    is_new=product.previous_special_price is None,
                    regular_price=product.regular_price,
                    promotional_price=product.special_price,
                    discount_percent=discount,
                    first_seen_at=product.first_seen_at,
                    last_seen_at=product.last_seen_at,
                    channel="hungerstation",
                    source="HungerStation",
                    category=product.category,
                )
            )
        return promotions

    def list_promotions(
        self,
        *,
        channel: Channel | None = None,
        status: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Promotion]:
        promotions: list[Promotion] = []
        if channel != "hungerstation" and self.base is not None:
            try:
                promotions.extend(
                    promotion for promotion in self.base.list_promotions(
                        channel=channel, status=status, category=category, query=query
                    ) if promotion.channel != "hungerstation"
                )
            except (FileNotFoundError, sqlite3.Error):
                pass
        if channel in (None, "hungerstation"):
            promotions.extend(self._hungerstation_promotions())
        return [
            promotion for promotion in promotions
            if (
                not status
                or status == promotion.status
                or (status == "new" and promotion.is_new)
            )
            and (not category or (promotion.category or "").casefold() == category.casefold())
            and (not query or query.casefold() in (promotion.title or "").casefold())
        ]

    def get_promotion(self, promotion_id: str) -> Promotion | None:
        if promotion_id.startswith("HUNGERSTATION--PROMO--"):
            return next((promotion for promotion in self._hungerstation_promotions() if promotion.id == promotion_id), None)
        return self.base.get_promotion(promotion_id) if self.base else None

    def _hungerstation_changes(self) -> list[ChangeEvent]:
        with database.readonly_connection(self.db_path) as db:
            rows = database.historical_products(db, self.brand_id)
        events: list[ChangeEvent] = []
        for row in rows:
            source_id = row["source_product_id"]
            product_id = _public_id(source_id)
            common = {
                "brand_id": self.brand_id,
                "product_id": product_id,
                "title": row["name_en"],
                "detected_at": to_riyadh_iso(row["captured_at"]),
                "channel": "hungerstation",
                "location": "HungerStation – Riyadh",
                "source_run_id": row["run_id"],
                "category": row["category_name_en"],
            }
            before = as_money(row["previous_effective_price"])
            after = as_money(row["effective_price"])
            key = _normalize(row["name_en"])
            if before is not None and after is not None and before != after:
                events.append(
                    ChangeEvent(
                        id=f"hs-price-{row['run_id']}-{key}",
                        type="price_increased" if after > before else "price_decreased",
                        before_value=str(before),
                        after_value=str(after),
                        percentage_change=round((after - before) / before * 100, 2) if before else None,
                        **common,
                    )
                )
            previous_special = as_money(row["previous_special_price"])
            current_special = as_money(row["special_price"])
            promotion_id = _public_id(source_id.replace("HUNGERSTATION|", "HUNGERSTATION|PROMO|", 1))
            if previous_special is None and current_special is not None:
                events.append(
                    ChangeEvent(
                        id=f"hs-offer-start-{row['run_id']}-{key}",
                        promotion_id=promotion_id,
                        type="offer_started",
                        after_value=str(current_special),
                        **common,
                    )
                )
            elif previous_special is not None and current_special is None:
                events.append(
                    ChangeEvent(
                        id=f"hs-offer-end-{row['run_id']}-{key}",
                        promotion_id=promotion_id,
                        type="offer_ended",
                        before_value=str(previous_special),
                        **common,
                    )
                )
            if row["previous_availability"] is not None and row["previous_availability"] != row["availability"]:
                events.append(
                    ChangeEvent(
                        id=f"hs-availability-{row['run_id']}-{key}",
                        type="availability_changed",
                        before_value=str(bool(row["previous_availability"])),
                        after_value=str(bool(row["availability"])),
                        **common,
                    )
                )
        events.sort(key=lambda event: event.detected_at, reverse=True)
        return events

    def list_changes(
        self,
        *,
        channel: Channel | None = None,
        event_type: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        if channel != "hungerstation" and self.base is not None:
            try:
                events.extend(
                    event for event in self.base.list_changes(
                        channel=channel,
                        event_type=event_type,
                        category=category,
                        date_from=date_from,
                        date_to=date_to,
                    ) if event.channel != "hungerstation"
                )
            except (FileNotFoundError, sqlite3.Error):
                pass
        if channel in (None, "hungerstation"):
            events.extend(self._hungerstation_changes())
        events = [
            event for event in events
            if (not event_type or event.type == event_type)
            and (not category or (event.category or "").casefold() == category.casefold())
            and (not date_from or event.detected_at[:10] >= date_from)
            and (not date_to or event.detected_at[:10] <= date_to)
        ]
        events.sort(key=lambda event: event.detected_at, reverse=True)
        return events

    def get_change(self, change_id: str) -> ChangeEvent | None:
        if change_id.startswith("hs-"):
            return next((event for event in self._hungerstation_changes() if event.id == change_id), None)
        return self.base.get_change(change_id) if self.base else None
