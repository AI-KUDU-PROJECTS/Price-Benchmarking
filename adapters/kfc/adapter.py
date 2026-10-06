"""KFC configuration for the generic SQLite monitoring adapter."""
from __future__ import annotations

from pathlib import Path

from adapters.sqlite_monitor import SQLiteMonitorAdapter, _filter_changes
from competitors.kfc.backend import config


class KfcAdapter(SQLiteMonitorAdapter):
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        branch_id: int | None = None,
        location_label: str | None = None,
    ) -> None:
        super().__init__(
            brand_id="kfc",
            brand_name="KFC",
            db_path=Path(db_path) if db_path else Path(config.DB_PATH),
            branch_id=int(branch_id if branch_id is not None else config.BRANCH_STORE_ID),
            location_label=location_label or f"{config.BRANCH_NAME} – {config.BRANCH_CITY}",
        )


__all__ = ["KfcAdapter", "_filter_changes"]
