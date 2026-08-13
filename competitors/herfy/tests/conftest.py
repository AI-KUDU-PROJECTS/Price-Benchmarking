"""
tests/conftest.py
---------------------------------------------------------------------
Shared pytest fixtures. Every test runs against a fresh, temporary SQLite
database (never the real data/herfy_monitor.db) and loads sample API
payloads from tests/fixtures/ - no network access, no live site, per spec
("Create local fixtures so the tests can run without connecting to the
live website"). Identical structure to every other competitor's
conftest.py - only the import path and fixture contents differ (real
captured Herfy product shapes from the live collector smoke test on
branch RUH - Al Mogarazat - Eirad Plaza Mall 1073 / locationId 29696 -
see gen_herfy_fixtures.py provenance note in each fixture file's sibling
test module docstrings).
---------------------------------------------------------------------
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from competitors.herfy.backend import database

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_herfy_monitor.db"


@pytest.fixture()
def conn(db_path: Path):
    database.init_db(db_path)
    with database.get_connection(db_path) as connection:
        yield connection


@pytest.fixture()
def delivery_result() -> dict:
    return load_fixture("sample_channel_delivery.json")


@pytest.fixture()
def pickup_result() -> dict:
    return load_fixture("sample_channel_pickup.json")


@pytest.fixture()
def failed_result() -> dict:
    return load_fixture("sample_channel_failed.json")


@pytest.fixture()
def partial_result() -> dict:
    return load_fixture("sample_channel_partial.json")


@pytest.fixture()
def malformed_result() -> dict:
    return load_fixture("sample_channel_malformed.json")


def clone_with(data: dict, **overrides) -> dict:
    """Deep-copies a fixture dict and applies top-level key overrides -
    used throughout the change-detector tests to derive a "next run" from
    a base fixture without mutating the original."""
    out = copy.deepcopy(data)
    out.update(overrides)
    return out
