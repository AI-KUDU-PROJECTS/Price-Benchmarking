from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bff.app import app
from bff.hungerstation_status import latest_collection_status
import bff.routes as routes
from competitors.hungerstation import config, database


def batch():
    return {
        "runId": "scheduled-batch", "status": "partial", "trigger": "scheduled",
        "startedAt": "2026-11-03T10:00:00Z", "completedAt": "2026-11-03T10:30:00Z",
        "brands": [
            {"id": brand, "name": name, "status": status,
             "startedAt": "2026-11-03T10:00:00Z", "completedAt": "2026-11-03T10:30:00Z",
             "message": "Data updated." if status == "success" else "AI_ACTION_LIMIT"}
            for brand, name, status in [
                ("kudu", "KUDU", "success"), ("burger-king", "Burger King", "failed"),
                ("albaik", "AlBaik", "failed"),
            ]
        ],
    }


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "hungerstation.db"
    database.init_db(path)
    return path


def save_run(path, brand="burger-king", status="SUCCESS", started="2026-11-03T14:00:00Z",
             finished="2026-11-03T14:10:00Z", count=166, batch_id=None, run_id="individual-run"):
    with database.connection(path) as db:
        db.execute(
            "INSERT INTO runs (run_id,batch_id,brand_id,restaurant_name,status,started_at,finished_at,"
            "product_count,error_message) VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id,batch_id,brand,brand,status,started,finished,count,
             "[NETWORK_ERROR] Connection failed." if status == "FAILED" else None),
        )


def test_later_individual_successes_replace_failed_display_without_editing_history(db_path):
    original = batch()
    unchanged = copy.deepcopy(original)
    save_run(db_path)
    save_run(db_path, brand="albaik", count=74, run_id="albaik-individual")
    result = latest_collection_status(original, db_path)
    assert result["status"] == "success"
    assert result["view"] == "latest_results"
    assert result["batchRunId"] == original["runId"]
    assert result["completedAt"] == "2026-11-03T14:10:00Z"
    assert result["brands"][0] == original["brands"][0]  # Separate KUDU source.
    assert result["brands"][1]["sourceRunId"] == "individual-run"
    assert "166 products" in result["brands"][1]["message"]
    assert "74 products" in result["brands"][2]["message"]
    assert "newer collection" in result["brands"][1]["message"]
    assert original == unchanged
    assert latest_collection_status(original, db_path) == result


def test_newer_failure_is_not_hidden_by_previous_success(db_path):
    save_run(db_path)
    save_run(db_path, status="FAILED", started="2026-11-03T15:00:00Z",
             finished="2026-11-03T15:01:00Z", count=0, run_id="later-failure")
    result = latest_collection_status(batch(), db_path)
    assert result["status"] == "partial"
    assert result["brands"][1]["status"] == "failed"
    assert "NETWORK_ERROR" in result["brands"][1]["message"]
    assert result["brands"][1]["sourceRunId"] == "later-failure"


def test_current_batch_progress_takes_precedence(db_path):
    save_run(db_path)
    current = batch()
    current["status"] = "running"
    current["brands"][1]["status"] = "running"
    assert latest_collection_status(current, db_path) is current


@pytest.mark.parametrize("started,finished", [
    ("2026-11-03T09:00:00Z", "2026-11-03T09:05:00Z"),
    ("2026-11-03T13:00:00+03:00", "2026-11-03T13:05:00+03:00"),
    ("2026-11-03T10:30:00+00:00", "2026-11-03T10:35:00+00:00"),
])
def test_old_or_overlapping_success_cannot_hide_newer_batch_failure(db_path, started, finished):
    save_run(db_path, started=started, finished=finished)
    current = batch()
    assert latest_collection_status(current, db_path) is current


def test_batch_own_database_result_does_not_replace_manager_failure(db_path):
    save_run(db_path, batch_id="scheduled-batch")
    current = batch()
    assert latest_collection_status(current, db_path) is current


def test_individual_run_is_visible_without_previous_batch(db_path):
    save_run(db_path)
    result = latest_collection_status(None, db_path)
    assert result["status"] == "success"
    assert [row["id"] for row in result["brands"]] == ["burger-king"]


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.db"
    current = batch()
    assert latest_collection_status(current, path) is current
    assert not path.exists()


def test_empty_database_does_not_invent_results(db_path):
    assert latest_collection_status(None, db_path) is None


def test_api_reports_latest_individual_result(db_path, monkeypatch):
    save_run(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(routes, "hungerstation_pull_manager", SimpleNamespace(latest=batch))
    response = TestClient(app).get("/api/v1/market/hungerstation/pull")
    assert response.status_code == 200
    result = response.json()["run"]
    assert result["view"] == "latest_results"
    assert result["brands"][1]["status"] == "success"
    assert result["brands"][2]["status"] == "failed"
