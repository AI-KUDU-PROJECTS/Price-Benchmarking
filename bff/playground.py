"""Local persistence and live-price hydration for Playground mappings."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from fastapi import HTTPException

from bff.contract import (
    Channel,
    MappingCompetitor,
    MappingProduct,
    PriceMapping,
    PriceMappingWrite,
    Product,
)
from bff.registry import get_adapter

ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB_PATH = ROOT / "bff" / "data" / "playground.db"
_override_db_path: Path | None = None

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS playground_mappings (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        channel TEXT NOT NULL CHECK (channel IN ('pickup', 'delivery', 'hungerstation')),
        kudu_product_id TEXT NOT NULL,
        kudu_name_snapshot TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playground_mapping_items (
        mapping_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        brand_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        brand_name_snapshot TEXT NOT NULL,
        product_name_snapshot TEXT NOT NULL,
        PRIMARY KEY (mapping_id, brand_id, product_id),
        FOREIGN KEY (mapping_id) REFERENCES playground_mappings(id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_playground_mappings_updated ON playground_mappings(updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_playground_items_mapping ON playground_mapping_items(mapping_id, position)",
)


@dataclass(frozen=True)
class StoredCompetitor:
    brand_id: str
    product_id: str
    brand_name_snapshot: str
    product_name_snapshot: str
    position: int


@dataclass(frozen=True)
class StoredMapping:
    id: str
    name: str
    channel: Channel
    kudu_product_id: str
    kudu_name_snapshot: str
    created_at: str
    updated_at: str
    competitor_items: tuple[StoredCompetitor, ...]


@dataclass(frozen=True)
class ValidatedMapping:
    name: str
    channel: Channel
    kudu_product: Product
    competitor_products: tuple[tuple[str, Product], ...]


def configure_playground_db_path(path: Path | None) -> None:
    """Override the mapping database path for isolated tests."""
    global _override_db_path
    _override_db_path = Path(path) if path is not None else None


def playground_db_path() -> Path:
    if _override_db_path is not None:
        return _override_db_path
    return Path(os.environ.get("PLAYGROUND_DB_PATH", _DEFAULT_DB_PATH))


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    path = playground_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA journal_mode = WAL")
    try:
        for statement in _SCHEMA:
            db.execute(statement)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _stored_mapping(db: sqlite3.Connection, row: sqlite3.Row) -> StoredMapping:
    items = db.execute(
        """
        SELECT * FROM playground_mapping_items
        WHERE mapping_id = ?
        ORDER BY position ASC
        """,
        (row["id"],),
    ).fetchall()
    return StoredMapping(
        id=row["id"],
        name=row["name"],
        channel=row["channel"],
        kudu_product_id=row["kudu_product_id"],
        kudu_name_snapshot=row["kudu_name_snapshot"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        competitor_items=tuple(
            StoredCompetitor(
                brand_id=item["brand_id"],
                product_id=item["product_id"],
                brand_name_snapshot=item["brand_name_snapshot"],
                product_name_snapshot=item["product_name_snapshot"],
                position=item["position"],
            )
            for item in items
        ),
    )


def list_stored_mappings() -> list[StoredMapping]:
    with _connection() as db:
        rows = db.execute(
            "SELECT * FROM playground_mappings ORDER BY updated_at DESC, id ASC"
        ).fetchall()
        return [_stored_mapping(db, row) for row in rows]


def get_stored_mapping(mapping_id: str) -> StoredMapping | None:
    with _connection() as db:
        row = db.execute(
            "SELECT * FROM playground_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
        return _stored_mapping(db, row) if row is not None else None


def create_stored_mapping(validated: ValidatedMapping) -> StoredMapping:
    mapping_id = str(uuid4())
    now = _utc_now()
    kudu_name = _product_name(validated.kudu_product)
    with _connection() as db:
        db.execute(
            """
            INSERT INTO playground_mappings (
                id, name, channel, kudu_product_id, kudu_name_snapshot,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mapping_id,
                validated.name,
                validated.channel,
                validated.kudu_product.id,
                kudu_name,
                now,
                now,
            ),
        )
        _insert_competitors(db, mapping_id, validated.competitor_products)
        row = db.execute(
            "SELECT * FROM playground_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
        assert row is not None
        return _stored_mapping(db, row)


def update_stored_mapping(mapping_id: str, validated: ValidatedMapping) -> StoredMapping | None:
    now = _utc_now()
    with _connection() as db:
        existing = db.execute(
            "SELECT created_at FROM playground_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
        if existing is None:
            return None
        db.execute(
            """
            UPDATE playground_mappings
            SET name = ?, channel = ?, kudu_product_id = ?,
                kudu_name_snapshot = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                validated.name,
                validated.channel,
                validated.kudu_product.id,
                _product_name(validated.kudu_product),
                now,
                mapping_id,
            ),
        )
        db.execute(
            "DELETE FROM playground_mapping_items WHERE mapping_id = ?",
            (mapping_id,),
        )
        _insert_competitors(db, mapping_id, validated.competitor_products)
        row = db.execute(
            "SELECT * FROM playground_mappings WHERE id = ?",
            (mapping_id,),
        ).fetchone()
        assert row is not None
        return _stored_mapping(db, row)


def delete_stored_mapping(mapping_id: str) -> bool:
    with _connection() as db:
        result = db.execute(
            "DELETE FROM playground_mappings WHERE id = ?",
            (mapping_id,),
        )
        return result.rowcount > 0


def _insert_competitors(
    db: sqlite3.Connection,
    mapping_id: str,
    competitors: tuple[tuple[str, Product], ...],
) -> None:
    for position, (brand_name, product) in enumerate(competitors):
        db.execute(
            """
            INSERT INTO playground_mapping_items (
                mapping_id, position, brand_id, product_id,
                brand_name_snapshot, product_name_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                mapping_id,
                position,
                product.brand_id,
                product.id,
                brand_name,
                _product_name(product),
            ),
        )


def _product_name(product: Product) -> str:
    return product.name_en or product.name_ar or product.id


def _effective_price(product: Product) -> float | None:
    return product.special_price if product.special_price is not None else product.regular_price


def _validation_error(message: str, field: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": "invalid_mapping", "field": field, "message": message},
    )


def validate_mapping(payload: PriceMappingWrite) -> ValidatedMapping:
    name = payload.name.strip()
    if not name:
        raise _validation_error("Mapping name cannot be blank.", "name")

    kudu_adapter = get_adapter("kudu")
    if kudu_adapter is None:
        raise _validation_error("KUDU data is not connected.", "kuduProductId")
    kudu_product = kudu_adapter.get_product(payload.kudu_product_id)
    if kudu_product is None or kudu_product.channel != payload.channel:
        raise _validation_error(
            "The selected KUDU item does not exist in this channel.",
            "kuduProductId",
        )
    kudu_price = _effective_price(kudu_product)
    if kudu_price is None or not kudu_product.currency:
        raise _validation_error(
            "The selected KUDU item does not have a comparable price.",
            "kuduProductId",
        )

    seen: set[tuple[str, str]] = set()
    brand_names: dict[str, str] = {}
    competitors: list[tuple[str, Product]] = []
    for index, selection in enumerate(payload.competitor_items):
        brand_id = selection.brand_id.strip()
        product_id = selection.product_id.strip()
        field = f"competitorItems.{index}"
        if brand_id == "kudu":
            raise _validation_error("KUDU cannot be selected as a competitor.", field)
        key = (brand_id, product_id)
        if key in seen:
            raise _validation_error("The same competitor item was selected more than once.", field)
        seen.add(key)

        adapter = get_adapter(brand_id)
        if adapter is None:
            raise _validation_error("The selected competitor is not connected.", field)
        product = adapter.get_product(product_id)
        if product is None or product.brand_id != brand_id or product.channel != payload.channel:
            raise _validation_error(
                "The selected competitor item does not exist in this channel.",
                field,
            )
        price = _effective_price(product)
        if price is None or not product.currency:
            raise _validation_error(
                "The selected competitor item does not have a comparable price.",
                field,
            )
        if product.currency != kudu_product.currency:
            raise _validation_error(
                "The selected item uses a different currency from the KUDU item.",
                field,
            )
        if brand_id not in brand_names:
            brand_names[brand_id] = adapter.get_brand().name
        competitors.append((brand_names[brand_id], product))

    return ValidatedMapping(
        name=name,
        channel=payload.channel,
        kudu_product=kudu_product,
        competitor_products=tuple(competitors),
    )


def _mapping_product(
    *,
    brand_id: str,
    brand_name: str,
    product_id: str,
    fallback_name: str,
    channel: Channel,
) -> MappingProduct:
    adapter = get_adapter(brand_id)
    product = adapter.get_product(product_id) if adapter is not None else None
    if product is None or product.channel != channel:
        return MappingProduct(
            brand_id=brand_id,
            brand_name=brand_name,
            product_id=product_id,
            name_en=fallback_name,
            missing=True,
        )
    return MappingProduct(
        brand_id=brand_id,
        brand_name=adapter.get_brand().name,
        product_id=product.id,
        name_ar=product.name_ar,
        name_en=product.name_en,
        category=product.category,
        image_url=product.image_url,
        effective_price=_effective_price(product),
        currency=product.currency,
        missing=False,
    )


def hydrate_mapping(stored: StoredMapping) -> PriceMapping:
    kudu_item = _mapping_product(
        brand_id="kudu",
        brand_name="KUDU",
        product_id=stored.kudu_product_id,
        fallback_name=stored.kudu_name_snapshot,
        channel=stored.channel,
    )
    competitors: list[MappingCompetitor] = []
    for item in stored.competitor_items:
        current = _mapping_product(
            brand_id=item.brand_id,
            brand_name=item.brand_name_snapshot,
            product_id=item.product_id,
            fallback_name=item.product_name_snapshot,
            channel=stored.channel,
        )
        difference = None
        percentage = None
        position = "unavailable"
        if (
            not kudu_item.missing
            and not current.missing
            and kudu_item.effective_price is not None
            and current.effective_price is not None
            and kudu_item.currency
            and kudu_item.currency == current.currency
        ):
            difference = round(current.effective_price - kudu_item.effective_price, 2)
            if kudu_item.effective_price != 0:
                percentage = round(difference / kudu_item.effective_price * 100, 2)
            position = "higher" if difference > 0 else "lower" if difference < 0 else "equal"
        competitors.append(
            MappingCompetitor(
                **current.model_dump(),
                difference_amount=difference,
                difference_percentage=percentage,
                price_position=position,
            )
        )
    return PriceMapping(
        id=stored.id,
        name=stored.name,
        channel=stored.channel,
        kudu_item=kudu_item,
        competitor_items=competitors,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


def list_mappings() -> list[PriceMapping]:
    return [hydrate_mapping(mapping) for mapping in list_stored_mappings()]


def get_mapping(mapping_id: str) -> PriceMapping | None:
    stored = get_stored_mapping(mapping_id)
    return hydrate_mapping(stored) if stored is not None else None


def create_mapping(payload: PriceMappingWrite) -> PriceMapping:
    return hydrate_mapping(create_stored_mapping(validate_mapping(payload)))


def update_mapping(mapping_id: str, payload: PriceMappingWrite) -> PriceMapping | None:
    stored = update_stored_mapping(mapping_id, validate_mapping(payload))
    return hydrate_mapping(stored) if stored is not None else None


def delete_mapping(mapping_id: str) -> bool:
    return delete_stored_mapping(mapping_id)

