"""Shared SQLite adapter for independently collected restaurant modules.

The shared class only maps the common monitoring schema into the BFF
contract. Each restaurant still owns its own collector, database, scheduler,
and backend logic.
"""
from __future__ import annotations

from pathlib import Path

from adapters.kfc.adapter import KfcAdapter


class SharedSQLiteAdapter(KfcAdapter):
    """Parameterized contract adapter for the common monitoring schema."""

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
        super().__init__(
            db_path=db_path,
            branch_id=branch_id,
            location_label=location_label,
        )
