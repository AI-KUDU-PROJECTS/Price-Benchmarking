"""SQLite log of AI calls and what each one cost (shown on the AI page)."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bff.contract import now_riyadh_iso

ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = ROOT / "bff" / "data" / "ai.db"

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS ai_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        purpose TEXT NOT NULL,
        model TEXT NOT NULL,
        input_tokens INTEGER NOT NULL,
        output_tokens INTEGER NOT NULL,
        cache_read_tokens INTEGER NOT NULL,
        cache_write_tokens INTEGER NOT NULL,
        cost_usd REAL
    )
"""


def db_path() -> Path:
    return Path(os.environ.get("AI_DB_PATH", _DEFAULT_DB_PATH))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def record_usage(purpose: str, model: str, usage: dict[str, int], cost_usd: float | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO ai_usage (
                created_at, purpose, model, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, cost_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_riyadh_iso(), purpose, model, usage["input_tokens"], usage["output_tokens"],
                usage["cache_read_tokens"], usage["cache_write_tokens"], cost_usd,
            ),
        )


def summary() -> dict[str, Any]:
    with connect() as conn:
        calls, cost = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(cost_usd), 0) FROM ai_usage"
        ).fetchone()
    return {"calls": calls, "costUsd": round(cost, 4)}
