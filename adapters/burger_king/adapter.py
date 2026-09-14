"""Burger King adapter for the shared marketing BFF contract."""
from __future__ import annotations

from pathlib import Path

from adapters.shared_sqlite import SharedSQLiteAdapter
from competitors.burger_king.backend import config as burger_king_config


class BurgerKingAdapter(SharedSQLiteAdapter):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(
            brand_id="burger-king",
            brand_name="Burger King",
            db_path=Path(db_path) if db_path else Path(burger_king_config.DB_PATH),
            branch_id=int(burger_king_config.BRANCH_STORE_ID),
            location_label=f"{burger_king_config.BRANCH_NAME} – {burger_king_config.BRANCH_CITY}",
        )
