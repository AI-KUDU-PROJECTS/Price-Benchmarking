from __future__ import annotations

from pathlib import Path

import pytest

from adapters.kfc.tests.seed import seed_kfc_db


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "kfc_monitor.db"
    seed_kfc_db(path)
    return path
