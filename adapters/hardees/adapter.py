"""Hardee's adapter for the shared marketing BFF contract."""
from __future__ import annotations

from pathlib import Path

from adapters.sqlite_monitor import SQLiteMonitorAdapter
from competitors.hardees.backend import config as hardees_config


class HardeesAdapter(SQLiteMonitorAdapter):
    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__(
            brand_id="hardees",
            brand_name="Hardee's",
            db_path=Path(db_path) if db_path else Path(hardees_config.DB_PATH),
            branch_id=int(hardees_config.BRANCH_STORE_ID),
            location_label=f"{hardees_config.BRANCH_NAME} – {hardees_config.BRANCH_CITY}",
        )
