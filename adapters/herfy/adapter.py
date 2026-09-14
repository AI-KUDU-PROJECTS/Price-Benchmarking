"""Herfy adapter for the shared marketing BFF contract."""
from __future__ import annotations

from pathlib import Path

from adapters.shared_sqlite import SharedSQLiteAdapter
from competitors.herfy.backend import config as herfy_config


class HerfyAdapter(SharedSQLiteAdapter):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(
            brand_id="herfy",
            brand_name="Herfy",
            db_path=Path(db_path) if db_path else Path(herfy_config.DB_PATH),
            branch_id=int(herfy_config.BRANCH_STORE_ID),
            location_label=f"{herfy_config.BRANCH_NAME} – {herfy_config.BRANCH_CITY}",
        )
