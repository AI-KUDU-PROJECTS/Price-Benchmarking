"""Bind the shared SQLite implementation to a brand's default DB path."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from competitors.shared.backend import database as shared_database

MIGRATIONS = shared_database.MIGRATIONS
PRODUCT_SNAPSHOT_COLUMNS = shared_database.PRODUCT_SNAPSHOT_COLUMNS
OFFER_SNAPSHOT_COLUMNS = shared_database.OFFER_SNAPSHOT_COLUMNS
upsert_branch = shared_database.upsert_branch


class DatabaseBinding:
    """Small compatibility layer for existing brand modules and tests."""

    def __init__(self, default_path: Path) -> None:
        self.default_path = default_path

    def init_db(self, db_path: Path | None = None) -> None:
        shared_database.init_db(db_path or self.default_path)

    @contextmanager
    def get_connection(self, db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
        with shared_database.get_connection(db_path or self.default_path) as connection:
            yield connection
