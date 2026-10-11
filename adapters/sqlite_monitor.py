"""Generic read-only adapter for the shared competitor SQLite schema."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bff.contract import (
    Brand,
    BrandCapabilities,
    BrandOverview,
    ChangeEvent,
    Channel,
    CollectionRun,
    Observation,
    PRODUCT_STATUS_TO_CONTRACT,
    PROMOTION_STATUS_TO_CONTRACT,
    Product,
    ProductHistory,
    ProductSize,
    Promotion,
    RIYADH,
    RUN_STATUS_TO_CONTRACT,
    SOURCE_EVENT_TO_CONTRACT,
    as_money,
    freshness_from_timestamp,
    now_riyadh,
    parse_utc,
    select_highlights,
    to_riyadh_iso,
)
class SQLiteMonitorAdapter:
    def __init__(
        self,
        *,
        brand_id: str,
        brand_name: str,
        db_path: Path,
        branch_id: int,
        location_label: str,
    ) -> None:
        self.brand_id = brand_id
        self.brand_name = brand_name
        self.db_path = Path(db_path)
        self.branch_id = int(branch_id)
        self.location_label = location_label

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(f"{self.brand_name} database not found: {self.db_path}")
        conn = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    def get_brand(self) -> Brand:
        if not self.db_path.exists():
            return Brand(
                id=self.brand_id,
                name=self.brand_name,
                health="error",
                last_successful_run_at=None,
                data_freshness="unavailable",
                capabilities=self._capabilities(),
                channels=["pickup", "delivery", "hungerstation"],
                location_label=self.location_label,
            )
        with self._connect() as conn:
            return self._brand_from_conn(conn)

    def get_overview(self) -> BrandOverview:
        with self._connect() as conn:
            brand = self._brand_from_conn(conn)
            runs = self._runs(conn, limit=8)
            products = self._latest_products(conn)
            promotions = self._latest_promotions(conn)
            changes = self._changes(conn)
            window = _recent_window(changes)
            return BrandOverview(
                brand=brand,
                runs=runs,
                product_count=len(products),
                promotion_count=sum(1 for p in promotions if p.status == "active"),
                recent_changes=window[:20],
                highlights=select_highlights(window),
            )

    def list_products(
        self,
        *,
        channel: Channel | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Product]:
        with self._connect() as conn:
            products = self._latest_products(conn, channel=channel)
        return _filter_products(products, category=category, query=query)

    def get_product(self, product_id: str) -> Product | None:
        with self._connect() as conn:
            products = self._latest_products(conn)
            match = next((p for p in products if p.id == product_id), None)
            if match:
                return match
            return self._product_from_dimension(conn, product_id)

    def get_product_history(self, product_id: str) -> ProductHistory | None:
        with self._connect() as conn:
            product = self.get_product(product_id)
            if product is None:
                row = self._dimension_product_row(conn, product_id)
                if row is None:
                    return None
                product = self._product_from_dimension(conn, product_id)
                if product is None:
                    return None
            observations = self._observations(conn, product.source_id)
            return ProductHistory(product=product, observations=observations)

    def list_promotions(
        self,
        *,
        channel: Channel | None = None,
        status: str | None = None,
        category: str | None = None,
        query: str | None = None,
    ) -> list[Promotion]:
        with self._connect() as conn:
            promotions = self._latest_promotions(conn, channel=channel)
        return _filter_promotions(promotions, status=status, category=category, query=query)

    def get_promotion(self, promotion_id: str) -> Promotion | None:
        with self._connect() as conn:
            promotions = self._latest_promotions(conn)
            match = next((p for p in promotions if p.id == promotion_id), None)
            if match:
                return match
            return self._promotion_from_dimension(conn, promotion_id)

    def list_changes(
        self,
        *,
        channel: Channel | None = None,
        event_type: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[ChangeEvent]:
        with self._connect() as conn:
            events = self._changes(conn)
        return _filter_changes(
            events,
            channel=channel,
            event_type=event_type,
            category=category,
            date_from=date_from,
            date_to=date_to,
        )

    def get_change(self, change_id: str) -> ChangeEvent | None:
        with self._connect() as conn:
            for event in self._changes(conn):
                if event.id == str(change_id):
                    return event
        return None

    def _capabilities(self) -> BrandCapabilities:
        return BrandCapabilities(has_discount=True, has_size_prices=True, has_images=True)

    def _brand_from_conn(self, conn: sqlite3.Connection) -> Brand:
        latest = self._latest_runs_by_channel(conn)
        successes = self._latest_success_by_channel(conn)
        success_times = [parse_utc(r["started_at"]) for r in successes.values() if r]
        success_times = [t for t in success_times if t is not None]
        last_success = max(success_times) if success_times else None
        last_success_iso = to_riyadh_iso(last_success) if last_success else None
        freshness = freshness_from_timestamp(
            last_success.isoformat() if last_success else None
        )
        health = _health(latest, successes, freshness)
        return Brand(
            id=self.brand_id,
            name=self.brand_name,
            health=health,
            last_successful_run_at=last_success_iso,
            data_freshness=freshness,
            capabilities=self._capabilities(),
            channels=["pickup", "delivery", "hungerstation"],
            location_label=self.location_label,
        )

    def _latest_runs_by_channel(self, conn: sqlite3.Connection) -> dict[str, sqlite3.Row | None]:
        out: dict[str, sqlite3.Row | None] = {"PICKUP": None, "DELIVERY": None}
        for channel in out:
            row = conn.execute(
                """
                SELECT * FROM crawl_runs
                WHERE channel = ? AND branch_id = ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (channel, self.branch_id),
            ).fetchone()
            out[channel] = row
        if _table_exists(conn, "external_channel_runs"):
            out["HUNGERSTATION"] = conn.execute(
                """
                SELECT * FROM external_channel_runs
                WHERE channel = 'HUNGERSTATION'
                ORDER BY started_at DESC LIMIT 1
                """
            ).fetchone()
        return out

    def _latest_success_by_channel(self, conn: sqlite3.Connection) -> dict[str, sqlite3.Row | None]:
        out: dict[str, sqlite3.Row | None] = {"PICKUP": None, "DELIVERY": None}
        for channel in out:
            row = conn.execute(
                """
                SELECT * FROM crawl_runs
                WHERE channel = ? AND branch_id = ? AND status = 'SUCCESS'
                ORDER BY started_at DESC LIMIT 1
                """,
                (channel, self.branch_id),
            ).fetchone()
            out[channel] = row
        if _table_exists(conn, "external_channel_runs"):
            out["HUNGERSTATION"] = conn.execute(
                """
                SELECT * FROM external_channel_runs
                WHERE channel = 'HUNGERSTATION' AND status = 'SUCCESS'
                ORDER BY started_at DESC LIMIT 1
                """
            ).fetchone()
        return out

    def _runs(self, conn: sqlite3.Connection, limit: int = 8) -> list[CollectionRun]:
        rows = conn.execute(
            """
            SELECT * FROM crawl_runs
            WHERE branch_id = ?
            ORDER BY started_at DESC LIMIT ?
            """,
            (self.branch_id, limit),
        ).fetchall()
        all_rows = list(rows)
        if _table_exists(conn, "external_channel_runs"):
            all_rows.extend(
                conn.execute(
                    """
                    SELECT * FROM external_channel_runs
                    WHERE channel = 'HUNGERSTATION'
                    ORDER BY started_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            )
        all_rows.sort(key=lambda row: row["started_at"] or "", reverse=True)
        return [self._run_from_row(r) for r in all_rows[:limit]]

    def _run_from_row(self, row: sqlite3.Row) -> CollectionRun:
        warnings = 0
        if "branch_currently_closed" in row.keys() and row["branch_currently_closed"]:
            warnings += 1
        return CollectionRun(
            id=row["run_id"],
            brand_id=self.brand_id,
            status=RUN_STATUS_TO_CONTRACT.get(row["status"], "failed"),
            started_at=to_riyadh_iso(row["started_at"]),
            completed_at=to_riyadh_iso(row["finished_at"]),
            channel=_to_channel(row["channel"]),
            location=(row["branch_name"] if "branch_name" in row.keys() else None) or self.location_label,
            item_count=row["product_count"] if row["product_count"] is not None else None,
            warning_count=warnings or None,
            error_summary=row["error_message"],
        )

    def _latest_products(
        self,
        conn: sqlite3.Connection,
        channel: Channel | None = None,
    ) -> list[Product]:
        source_channel = _from_channel(channel)
        products: list[Product] = []
        params: list[Any] = [self.branch_id, self.branch_id]
        channel_sql = ""
        if source_channel and source_channel != "HUNGERSTATION":
            channel_sql = "AND ranked.channel = ?"
            params.append(source_channel)
        if source_channel != "HUNGERSTATION":
            rows = conn.execute(
                f"""
            WITH latest AS (
                SELECT channel, run_id FROM (
                    SELECT channel, run_id,
                           ROW_NUMBER() OVER (
                             PARTITION BY channel ORDER BY started_at DESC
                           ) AS rn
                    FROM crawl_runs
                    WHERE branch_id = ? AND status = 'SUCCESS'
                ) ranked_runs
                WHERE rn = 1
            ),
            ranked AS (
                SELECT
                    ps.*,
                    cr.started_at AS run_started,
                    LAG(ps.regular_price) OVER (
                        PARTITION BY ps.product_key ORDER BY cr.started_at
                    ) AS prev_regular,
                    LAG(ps.special_price) OVER (
                        PARTITION BY ps.product_key ORDER BY cr.started_at
                    ) AS prev_special
                FROM product_snapshots ps
                JOIN crawl_runs cr
                  ON cr.run_id = ps.run_id AND cr.status = 'SUCCESS'
                WHERE ps.branch_id = ?
            )
            SELECT
                ranked.*,
                p.status AS entity_status,
                p.first_seen_at,
                p.last_seen_at,
                p.canonical_product_key
            FROM ranked
            JOIN latest ON latest.run_id = ranked.run_id
            JOIN products p ON p.canonical_product_key = ranked.product_key
            WHERE 1 = 1 {channel_sql}
            ORDER BY ranked.category_name_en, ranked.product_name_en
            """,
                params,
            ).fetchall()
            products.extend(self._product_from_row(r) for r in rows)
        if source_channel in (None, "HUNGERSTATION"):
            products.extend(self._latest_external_products(conn))
        return products

    def _latest_external_products(self, conn: sqlite3.Connection) -> list[Product]:
        if not _table_exists(conn, "external_channel_products"):
            return []
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT run_id
                FROM external_channel_runs
                WHERE channel = 'HUNGERSTATION' AND status = 'SUCCESS'
                ORDER BY started_at DESC LIMIT 1
            ),
            ranked AS (
                SELECT
                    ep.*,
                    er.started_at AS run_started,
                    er.branch_name,
                    LAG(ep.regular_price) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS prev_regular,
                    LAG(ep.special_price) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS prev_special,
                    MIN(ep.captured_at) OVER (
                        PARTITION BY ep.source_product_id
                    ) AS first_seen_at,
                    MAX(ep.captured_at) OVER (
                        PARTITION BY ep.source_product_id
                    ) AS last_seen_at
                FROM external_channel_products ep
                JOIN external_channel_runs er ON er.run_id = ep.run_id
                WHERE er.channel = 'HUNGERSTATION' AND er.status = 'SUCCESS'
            )
            SELECT ranked.*
            FROM ranked JOIN latest ON latest.run_id = ranked.run_id
            ORDER BY ranked.category_name_en, ranked.name_en
            """
        ).fetchall()
        image_by_name = self._image_by_product_name(conn)
        return [
            self._external_product_from_row(
                row,
                fallback_image_url=image_by_name.get(_normalize_product_name(row["name_en"])),
            )
            for row in rows
        ]

    def _image_by_product_name(self, conn: sqlite3.Connection) -> dict[str, str]:
        rows = conn.execute(
            """
            SELECT ps.product_name_en, ps.image_url
            FROM product_snapshots ps
            JOIN crawl_runs cr ON cr.run_id = ps.run_id
            WHERE cr.status = 'SUCCESS'
              AND ps.image_url IS NOT NULL
              AND TRIM(ps.image_url) != ''
              AND ps.product_name_en IS NOT NULL
            ORDER BY cr.started_at DESC
            """
        ).fetchall()
        images: dict[str, str] = {}
        for row in rows:
            key = _normalize_product_name(row["product_name_en"])
            if key:
                images.setdefault(key, row["image_url"])
        return images

    def _external_product_from_row(
        self,
        row: sqlite3.Row | dict[str, Any],
        *,
        fallback_image_url: str | None = None,
    ) -> Product:
        data = dict(row)
        source_id = data["source_product_id"]
        return Product(
            id=_public_id(source_id),
            brand_id=self.brand_id,
            source_id=source_id,
            name_en=_blank_to_none(data.get("name_en")),
            category=_blank_to_none(data.get("category_name_en")),
            image_url=_blank_to_none(data.get("image_url")) or _blank_to_none(fallback_image_url),
            channel="hungerstation",
            location=_blank_to_none(data.get("branch_name")) or "HungerStation",
            regular_price=as_money(data.get("regular_price")),
            special_price=as_money(data.get("special_price")),
            previous_regular_price=as_money(data.get("prev_regular")),
            previous_special_price=as_money(data.get("prev_special")),
            currency=_blank_to_none(data.get("currency")),
            sizes=[],
            availability=_availability(data.get("availability")),
            description_en=_blank_to_none(data.get("description_en")),
            calories=data.get("calories"),
            status="active",
            first_seen_at=to_riyadh_iso(data.get("first_seen_at") or data.get("captured_at")),
            last_seen_at=to_riyadh_iso(data.get("last_seen_at") or data.get("captured_at")),
            observed_at=to_riyadh_iso(data.get("captured_at")),
            source_run_id=data.get("run_id"),
        )

    def _product_from_row(self, row: sqlite3.Row) -> Product:
        source_id = row["product_key"]
        channel = _to_channel(row["channel"])
        currency = row["currency"] or None
        return Product(
            id=_public_id(source_id),
            brand_id=self.brand_id,
            source_id=source_id,
            name_ar=_blank_to_none(row["product_name_ar"]),
            name_en=_blank_to_none(row["product_name_en"]),
            category=_blank_to_none(row["category_name_en"]),
            image_url=_blank_to_none(row["image_url"]),
            channel=channel,
            location=self.location_label,
            regular_price=as_money(row["regular_price"]),
            special_price=as_money(row["special_price"]),
            previous_regular_price=as_money(row["prev_regular"]) if "prev_regular" in row.keys() else None,
            previous_special_price=as_money(row["prev_special"]) if "prev_special" in row.keys() else None,
            currency=currency,
            sizes=parse_sizes(row["sizes"] if "sizes" in row.keys() else None, currency),
            availability=_availability(row["availability"] if "availability" in row.keys() else None),
            status=PRODUCT_STATUS_TO_CONTRACT.get(
                row["entity_status"] if "entity_status" in row.keys() else "ACTIVE",
                "active",
            ),
            first_seen_at=to_riyadh_iso(row["first_seen_at"] if "first_seen_at" in row.keys() else None),
            last_seen_at=to_riyadh_iso(row["last_seen_at"] if "last_seen_at" in row.keys() else None),
            observed_at=to_riyadh_iso(row["captured_at"] if "captured_at" in row.keys() else None),
            source_run_id=row["run_id"] if "run_id" in row.keys() else None,
        )

    def _dimension_product_row(self, conn: sqlite3.Connection, product_id: str) -> sqlite3.Row | None:
        key = _source_key(product_id)
        return conn.execute(
            """
            SELECT canonical_product_key, product_id, channel, product_name_en, product_name_ar,
                   category_name_en, image_url, status AS entity_status,
                   first_seen_at, last_seen_at, last_seen_run_id
            FROM products
            WHERE branch_id = ? AND (canonical_product_key = ? OR canonical_product_key = ?)
            """,
            (self.branch_id, key, product_id),
        ).fetchone()

    def _product_from_dimension(self, conn: sqlite3.Connection, product_id: str) -> Product | None:
        row = self._dimension_product_row(conn, product_id)
        if row is None:
            return None
        snap = conn.execute(
            """
            SELECT ps.*
            FROM product_snapshots ps
            JOIN crawl_runs cr ON cr.run_id = ps.run_id AND cr.status = 'SUCCESS'
            WHERE ps.product_key = ?
            ORDER BY cr.started_at DESC
            LIMIT 1
            """,
            (row["canonical_product_key"],),
        ).fetchone()
        if snap is not None:
            merged = dict(snap)
            merged.update(
                {
                    "entity_status": row["entity_status"],
                    "first_seen_at": row["first_seen_at"],
                    "last_seen_at": row["last_seen_at"],
                    "canonical_product_key": row["canonical_product_key"],
                    "product_key": row["canonical_product_key"],
                }
            )
            return self._product_from_row(merged)
        return Product(
            id=_public_id(row["canonical_product_key"]),
            brand_id=self.brand_id,
            source_id=row["canonical_product_key"],
            name_ar=_blank_to_none(row["product_name_ar"]),
            name_en=_blank_to_none(row["product_name_en"]),
            category=_blank_to_none(row["category_name_en"]),
            image_url=_blank_to_none(row["image_url"]),
            channel=_to_channel(row["channel"]),
            location=self.location_label,
            regular_price=None,
            special_price=None,
            previous_regular_price=None,
            previous_special_price=None,
            currency=None,
            sizes=[],
            availability=None,
            status=PRODUCT_STATUS_TO_CONTRACT.get(row["entity_status"], "active"),
            first_seen_at=to_riyadh_iso(row["first_seen_at"]),
            last_seen_at=to_riyadh_iso(row["last_seen_at"]),
            observed_at=None,
            source_run_id=row["last_seen_run_id"],
        )

    def _observations(self, conn: sqlite3.Connection, source_id: str) -> list[Observation]:
        if source_id.startswith("HUNGERSTATION|") and _table_exists(conn, "external_channel_products"):
            rows = conn.execute(
                """
                SELECT ep.*
                FROM external_channel_products ep
                JOIN external_channel_runs er ON er.run_id = ep.run_id
                WHERE ep.source_product_id = ? AND er.status = 'SUCCESS'
                ORDER BY er.started_at ASC
                """,
                (source_id,),
            ).fetchall()
            image_by_name = self._image_by_product_name(conn)
            return [
                Observation(
                    observed_at=to_riyadh_iso(row["captured_at"]),
                    source_run_id=row["run_id"],
                    channel="hungerstation",
                    regular_price=as_money(row["regular_price"]),
                    special_price=as_money(row["special_price"]),
                    availability=_availability(row["availability"]),
                    image_url=_blank_to_none(row["image_url"]) or image_by_name.get(_normalize_product_name(row["name_en"])),
                    sizes=[],
                )
                for row in rows
            ]
        rows = conn.execute(
            """
            SELECT ps.*, cr.started_at AS run_started
            FROM product_snapshots ps
            JOIN crawl_runs cr ON cr.run_id = ps.run_id
            WHERE ps.product_key = ? AND cr.status = 'SUCCESS'
            ORDER BY cr.started_at ASC
            """,
            (source_id,),
        ).fetchall()
        observations: list[Observation] = []
        for row in rows:
            currency = row["currency"] or None
            observations.append(
                Observation(
                    observed_at=to_riyadh_iso(row["captured_at"] or row["run_started"]),
                    source_run_id=row["run_id"],
                    channel=_to_channel(row["channel"]),
                    regular_price=as_money(row["regular_price"]),
                    special_price=as_money(row["special_price"]),
                    availability=_availability(row["availability"]),
                    image_url=_blank_to_none(row["image_url"]),
                    sizes=parse_sizes(row["sizes"], currency),
                )
            )
        return observations

    def _latest_promotions(
        self,
        conn: sqlite3.Connection,
        channel: Channel | None = None,
    ) -> list[Promotion]:
        latest_ids = {
            r["run_id"]
            for r in self._latest_success_by_channel(conn).values()
            if r is not None
        }
        source_channel = _from_channel(channel)
        if source_channel == "HUNGERSTATION":
            return self._latest_external_promotions(conn)
        params: list[Any] = [self.branch_id]
        channel_sql = ""
        if source_channel:
            channel_sql = "AND os.channel = ?"
            params.append(source_channel)
        rows = conn.execute(
            f"""
            SELECT os.*, o.status AS entity_status, o.first_seen_at, o.last_seen_at,
                   o.first_seen_run_id, o.offer_key
            FROM offer_snapshots os
            JOIN offers o ON o.offer_key = os.offer_key
            WHERE os.branch_id = ? {channel_sql}
              AND os.run_id IN (
                  SELECT cr.run_id FROM crawl_runs cr
                  WHERE cr.channel = os.channel AND cr.branch_id = os.branch_id
                    AND cr.status = 'SUCCESS'
                  ORDER BY cr.started_at DESC LIMIT 1
              )
            ORDER BY os.offer_name
            """,
            params,
        ).fetchall()
        # SQLite LIMIT in correlated subquery is supported. Also include
        # ended/not_observed dimension rows that have no latest-run snapshot
        # so the UI can still open their detail pages.
        seen = {row["offer_key"] for row in rows}
        extras = conn.execute(
            f"""
            SELECT o.offer_key, o.promo_id, o.product_key, o.channel, o.offer_name,
                   o.offer_type, o.status AS entity_status, o.first_seen_at, o.last_seen_at,
                   o.first_seen_run_id, o.last_seen_run_id
            FROM offers o
            WHERE o.branch_id = ?
              AND o.status IN ('ENDED', 'NOT_OBSERVED', 'RETURNED')
            """,
            (self.branch_id,),
        ).fetchall()
        promotions = [self._promotion_from_row(r, latest_ids) for r in rows]
        for extra in extras:
            if extra["offer_key"] in seen:
                continue
            if source_channel and extra["channel"] != source_channel:
                continue
            snap = conn.execute(
                """
                SELECT * FROM offer_snapshots
                WHERE offer_key = ?
                ORDER BY captured_at DESC LIMIT 1
                """,
                (extra["offer_key"],),
            ).fetchone()
            payload = dict(extra)
            if snap is not None:
                payload.update(dict(snap))
            payload["entity_status"] = extra["entity_status"]
            payload["first_seen_at"] = extra["first_seen_at"]
            payload["last_seen_at"] = extra["last_seen_at"]
            payload["first_seen_run_id"] = extra["first_seen_run_id"]
            promotions.append(self._promotion_from_row(payload, latest_ids))
        if source_channel is None:
            promotions.extend(self._latest_external_promotions(conn))
        return promotions

    def _latest_external_promotions(self, conn: sqlite3.Connection) -> list[Promotion]:
        promotions: list[Promotion] = []
        for product in self._latest_external_products(conn):
            if product.special_price is None:
                continue
            discount = None
            if product.regular_price and product.regular_price > 0:
                discount = round(
                    (product.regular_price - product.special_price) / product.regular_price * 100,
                    2,
                )
            promotion_key = _external_promotion_key(product.source_id)
            promotions.append(
                Promotion(
                    id=_public_id(promotion_key),
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

    def _promotion_from_row(self, row: sqlite3.Row | dict[str, Any], latest_ids: set[str]) -> Promotion:
        data = dict(row)
        source_id = data.get("offer_key") or data["offer_key"]
        product_key = data.get("product_key")
        first_seen_run = data.get("first_seen_run_id")
        discount = as_money(data.get("discount_percentage"))
        return Promotion(
            id=_public_id(source_id),
            brand_id=self.brand_id,
            product_id=_public_id(product_key) if product_key else None,
            title=_blank_to_none(data.get("offer_name")),
            image_url=_blank_to_none(data.get("image_url")),
            status=PROMOTION_STATUS_TO_CONTRACT.get(data.get("entity_status") or "ACTIVE", "active"),
            is_new=bool(first_seen_run and first_seen_run in latest_ids),
            regular_price=as_money(data.get("original_price")),
            promotional_price=as_money(data.get("offer_price")),
            discount_percent=discount,
            first_seen_at=to_riyadh_iso(data.get("first_seen_at")),
            last_seen_at=to_riyadh_iso(data.get("last_seen_at")),
            channel=_to_channel(data.get("channel") or "PICKUP"),
            source=data.get("source_endpoint") or data.get("offer_type"),
            category=_blank_to_none(data.get("offer_type")),
        )

    def _promotion_from_dimension(self, conn: sqlite3.Connection, promotion_id: str) -> Promotion | None:
        key = _source_key(promotion_id)
        row = conn.execute(
            """
            SELECT * FROM offers
            WHERE branch_id = ? AND (offer_key = ? OR offer_key = ?)
            """,
            (self.branch_id, key, promotion_id),
        ).fetchone()
        if row is None:
            return None
        latest_ids = {
            r["run_id"]
            for r in self._latest_success_by_channel(conn).values()
            if r is not None
        }
        snap = conn.execute(
            "SELECT * FROM offer_snapshots WHERE offer_key = ? ORDER BY captured_at DESC LIMIT 1",
            (row["offer_key"],),
        ).fetchone()
        payload = dict(row)
        if snap is not None:
            payload.update(dict(snap))
        payload["entity_status"] = row["status"]
        payload["offer_key"] = row["offer_key"]
        return self._promotion_from_row(payload, latest_ids)

    def _changes(self, conn: sqlite3.Connection) -> list[ChangeEvent]:
        rows = conn.execute(
            """
            SELECT ce.*, o.product_key AS offer_product_key
            FROM change_events ce
            LEFT JOIN offers o ON o.offer_key = ce.entity_key AND ce.entity_type = 'offer'
            WHERE ce.branch_id = ?
            ORDER BY ce.detected_at DESC
            LIMIT 5000
            """,
            (self.branch_id,),
        ).fetchall()
        events: list[ChangeEvent] = []
        for row in rows:
            mapped = SOURCE_EVENT_TO_CONTRACT.get(row["event_type"])
            if mapped is None:
                continue
            entity_type = row["entity_type"]
            entity_key = row["entity_key"]
            product_id = _public_id(entity_key) if entity_type == "product" else None
            promotion_id = _public_id(entity_key) if entity_type == "offer" else None
            if entity_type == "offer" and row["offer_product_key"]:
                product_id = _public_id(row["offer_product_key"])
            events.append(
                ChangeEvent(
                    id=str(row["id"]),
                    brand_id=self.brand_id,
                    product_id=product_id,
                    promotion_id=promotion_id,
                    type=mapped,
                    title=_blank_to_none(row["entity_name"]),
                    before_value=_blank_to_none(row["old_value"]),
                    after_value=_blank_to_none(row["new_value"]),
                    percentage_change=as_money(row["percentage_change"]),
                    detected_at=to_riyadh_iso(row["detected_at"]) or now_riyadh().isoformat(),
                    channel=_to_channel(row["channel"]),
                    location=self.location_label,
                    source_run_id=row["run_id"],
                    category=_blank_to_none(row["field_name"]),
                )
            )
        events.extend(self._external_changes(conn))
        events.sort(key=lambda event: event.detected_at, reverse=True)
        return events

    def _external_changes(self, conn: sqlite3.Connection) -> list[ChangeEvent]:
        if not _table_exists(conn, "external_channel_products"):
            return []
        rows = conn.execute(
            """
            WITH history AS (
                SELECT
                    ep.*,
                    er.started_at,
                    er.branch_name,
                    LAG(ep.run_id) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS previous_run_id,
                    LAG(ep.effective_price) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS previous_effective_price,
                    LAG(ep.special_price) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS previous_special_price,
                    LAG(ep.availability) OVER (
                        PARTITION BY ep.source_product_id ORDER BY er.started_at
                    ) AS previous_availability
                FROM external_channel_products ep
                JOIN external_channel_runs er ON er.run_id = ep.run_id
                WHERE er.channel = 'HUNGERSTATION' AND er.status = 'SUCCESS'
            )
            SELECT * FROM history
            WHERE previous_run_id IS NOT NULL
            ORDER BY started_at DESC
            """
        ).fetchall()
        events: list[ChangeEvent] = []
        for row in rows:
            source_id = row["source_product_id"]
            product_id = _public_id(source_id)
            common = {
                "brand_id": self.brand_id,
                "product_id": product_id,
                "title": _blank_to_none(row["name_en"]),
                "detected_at": to_riyadh_iso(row["captured_at"]) or now_riyadh().isoformat(),
                "channel": "hungerstation",
                "location": row["branch_name"] or "HungerStation",
                "source_run_id": row["run_id"],
                "category": _blank_to_none(row["category_name_en"]),
            }
            before = as_money(row["previous_effective_price"])
            after = as_money(row["effective_price"])
            if before is not None and after is not None and before != after:
                percentage = round((after - before) / before * 100, 2) if before else None
                events.append(
                    ChangeEvent(
                        id=f"hs-price-{row['run_id']}-{_normalize_product_name(row['name_en'])}",
                        type="price_increased" if after > before else "price_decreased",
                        before_value=str(before),
                        after_value=str(after),
                        percentage_change=percentage,
                        **common,
                    )
                )
            previous_special = as_money(row["previous_special_price"])
            current_special = as_money(row["special_price"])
            if previous_special is None and current_special is not None:
                events.append(
                    ChangeEvent(
                        id=f"hs-offer-start-{row['run_id']}-{_normalize_product_name(row['name_en'])}",
                        promotion_id=_public_id(_external_promotion_key(source_id)),
                        type="offer_started",
                        before_value=None,
                        after_value=str(current_special),
                        **common,
                    )
                )
            elif previous_special is not None and current_special is None:
                events.append(
                    ChangeEvent(
                        id=f"hs-offer-end-{row['run_id']}-{_normalize_product_name(row['name_en'])}",
                        promotion_id=_public_id(_external_promotion_key(source_id)),
                        type="offer_ended",
                        before_value=str(previous_special),
                        after_value=None,
                        **common,
                    )
                )
            previous_availability = row["previous_availability"]
            if previous_availability is not None and previous_availability != row["availability"]:
                events.append(
                    ChangeEvent(
                        id=f"hs-availability-{row['run_id']}-{_normalize_product_name(row['name_en'])}",
                        type="availability_changed",
                        before_value=str(bool(previous_availability)),
                        after_value=str(bool(row["availability"])),
                        **common,
                    )
                )
        return events


def parse_sizes(raw: Any, currency: str | None) -> list[ProductSize]:
    """Parse size JSON. Missing prices stay None; never invent a size."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    sizes: list[ProductSize] = []
    for entry in data:
        if isinstance(entry, str):
            label = entry.strip()
            if label:
                sizes.append(ProductSize(label=label, price=None, currency=currency))
            continue
        if not isinstance(entry, dict):
            continue
        label = entry.get("title") or entry.get("label") or entry.get("name")
        if not label:
            continue
        sizes.append(
            ProductSize(
                label=str(label),
                price=as_money(entry.get("price")),
                currency=currency,
            )
        )
    return sizes


def _to_channel(value: str) -> Channel:
    normalized = str(value).upper()
    if normalized == "HUNGERSTATION":
        return "hungerstation"
    return "delivery" if normalized == "DELIVERY" else "pickup"


def _from_channel(value: Channel | str | None) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).lower()
    if normalized == "hungerstation":
        return "HUNGERSTATION"
    return "DELIVERY" if normalized == "delivery" else "PICKUP"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone() is not None


def _public_id(source_key: str | None) -> str:
    if not source_key:
        return ""
    return source_key.replace("|", "--")


def _source_key(public_id: str) -> str:
    return public_id.replace("--", "|")


def _external_promotion_key(source_id: str) -> str:
    """Insert a PROMO segment without assuming a specific brand token."""
    source, separator, remainder = source_id.partition("|")
    brand, brand_separator, product = remainder.partition("|")
    if separator and brand_separator:
        return f"{source}|{brand}|PROMO|{product}"
    return f"{source_id}|PROMO"


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_product_name(value: Any) -> str:
    if value is None:
        return ""
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def _availability(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(int(value)) if value in (0, 1, "0", "1", True, False) else bool(value)


def _health(
    latest: dict[str, sqlite3.Row | None],
    successes: dict[str, sqlite3.Row | None],
    freshness: str,
) -> str:
    statuses = [r["status"] for r in latest.values() if r is not None]
    if not any(successes.values()):
        return "error"
    if any(s == "PARTIAL" for s in statuses) or (
        "SUCCESS" in statuses and "FAILED" in statuses
    ):
        return "partial"
    if freshness == "stale":
        return "stale"
    if any(s == "FAILED" for s in statuses):
        return "error"
    return "healthy"


def _filter_products(
    products: list[Product],
    *,
    category: str | None,
    query: str | None,
) -> list[Product]:
    out = products
    if category:
        needle = category.lower()
        out = [p for p in out if (p.category or "").lower() == needle]
    if query:
        q = query.lower()
        out = [
            p
            for p in out
            if q in (p.name_en or "").lower()
            or q in (p.name_ar or "").lower()
            or q in (p.category or "").lower()
        ]
    return out


def _filter_promotions(
    promotions: list[Promotion],
    *,
    status: str | None,
    category: str | None,
    query: str | None,
) -> list[Promotion]:
    out = promotions
    if status:
        if status == "new":
            out = [p for p in out if p.is_new]
        else:
            out = [p for p in out if p.status == status]
    if category:
        needle = category.lower()
        out = [p for p in out if (p.category or "").lower() == needle]
    if query:
        q = query.lower()
        out = [p for p in out if q in (p.title or "").lower()]
    return out


def _filter_changes(
    events: list[ChangeEvent],
    *,
    channel: Channel | None,
    event_type: str | None,
    category: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[ChangeEvent]:
    out = events
    if channel:
        out = [e for e in out if e.channel == channel]
    if event_type:
        wanted = {part.strip() for part in event_type.split(",") if part.strip()}
        out = [e for e in out if e.type in wanted]
    if category:
        needle = category.lower()
        out = [e for e in out if (e.category or "").lower() == needle]
    start = _parse_riyadh_boundary(date_from, end_of_day=False)
    end = _parse_riyadh_boundary(date_to, end_of_day=True)
    if start or end:
        filtered: list[ChangeEvent] = []
        for event in out:
            detected = parse_utc(event.detected_at)
            if detected is None:
                continue
            if start and detected < start:
                continue
            if end and detected > end:
                continue
            filtered.append(event)
        out = filtered
    return out


def _parse_riyadh_boundary(value: str | None, *, end_of_day: bool) -> datetime | None:
    """Interpret date-only filters as a calendar date in Riyadh, not UTC."""
    if not value:
        return None
    text = value.strip()
    if len(text) == 10:
        try:
            local = datetime.fromisoformat(
                f"{text}T23:59:59.999999" if end_of_day else f"{text}T00:00:00"
            ).replace(tzinfo=RIYADH)
            return local.astimezone(timezone.utc)
        except ValueError:
            return None
    return parse_utc(text)


def _recent_window(events: list[ChangeEvent], days: int = 7) -> list[ChangeEvent]:
    cutoff = now_riyadh().astimezone(timezone.utc) - timedelta(days=days)
    recent = []
    for event in events:
        detected = parse_utc(event.detected_at)
        if detected and detected >= cutoff:
            recent.append(event)
    return recent or events[:50]
