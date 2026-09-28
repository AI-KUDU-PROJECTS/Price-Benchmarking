"""Pull-all launches independent collectors together and reports their results."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from bff.app import app
from bff.pull_all import HUNGERSTATION_TARGETS, PullManager, PullTarget, TARGETS
import bff.pull_all as pull_all
import bff.routes as routes


def _wait_for_completion(manager: PullManager) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = manager.latest()
        if run and run["status"] != "running":
            return run
        time.sleep(0.01)
    raise AssertionError("pull-all job did not finish")


def test_all_five_sources_are_configured() -> None:
    assert [target.id for target in TARGETS] == ["kudu", "kfc", "hardees", "burger-king", "herfy"]
    assert TARGETS[0].args == ("-m", "kudu.refresh")
    assert all("--channel=BOTH" in target.args for target in TARGETS[1:])


def test_all_six_hungerstation_restaurants_are_configured() -> None:
    assert [target.id for target in HUNGERSTATION_TARGETS] == [
        "kfc", "hardees", "burger-king", "herfy", "mcdonalds", "albaik",
    ]
    assert all(target.args[:2] == ("run_hungerstation_collector.py", "--brand") for target in HUNGERSTATION_TARGETS)


def test_hungerstation_targets_run_sequentially() -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def runner(target: PullTarget, run_id: str) -> tuple[str, str]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return "success", "Data updated."

    manager = PullManager(targets=HUNGERSTATION_TARGETS, runner=runner, max_workers=1)
    manager.start()
    finished = _wait_for_completion(manager)
    assert finished["status"] == "success"
    assert peak == 1


def test_collectors_start_concurrently_and_duplicate_click_reuses_run() -> None:
    release = threading.Event()
    all_started = threading.Event()
    lock = threading.Lock()
    started_count = 0

    def runner(target: PullTarget, run_id: str) -> tuple[str, str]:
        nonlocal started_count
        with lock:
            started_count += 1
            if started_count == 5:
                all_started.set()
        assert release.wait(timeout=3)
        return "success", "Data updated."

    manager = PullManager(targets=TARGETS, runner=runner)
    first, started = manager.start()
    second, started_again = manager.start()
    assert started is True
    assert started_again is False
    assert first["runId"] == second["runId"]
    assert all_started.wait(timeout=3)
    release.set()
    finished = _wait_for_completion(manager)
    assert finished["status"] == "success"
    assert all(row["status"] == "success" for row in finished["brands"])


def test_endpoint_reports_partial_completion(monkeypatch) -> None:
    targets = (PullTarget("kudu", "KUDU", ()), PullTarget("kfc", "KFC", ()))
    manager = PullManager(
        targets=targets,
        runner=lambda target, run_id: ("failed", "Collector exited with code 1.")
        if target.id == "kfc" else ("success", "Data updated."),
    )
    monkeypatch.setattr(routes, "pull_manager", manager)
    client = TestClient(app)
    started = client.post("/api/v1/market/pull")
    assert started.status_code == 202
    assert started.json()["started"] is True
    finished = _wait_for_completion(manager)
    response = client.get("/api/v1/market/pull")
    assert response.status_code == 200
    assert response.json()["run"]["runId"] == finished["runId"]
    assert finished["status"] == "partial"
    assert {row["id"]: row["status"] for row in finished["brands"]} == {
        "kudu": "success", "kfc": "failed",
    }


def test_americana_collector_retries_failed_run_with_fresh_log(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs["stdout"].name)
        kwargs["stdout"].write("[RUN] Finished. Overall status: FAILED\n" if len(calls) == 1 else "[RUN] Finished. Overall status: SUCCESS\n")
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr(pull_all, "LOG_DIR", tmp_path)
    monkeypatch.setattr(pull_all.subprocess, "run", fake_run)
    monkeypatch.setattr(pull_all.time, "sleep", lambda seconds: None)
    status, message = PullManager._run_subprocess(TARGETS[1], "retry-run")
    assert (status, message) == ("success", "Data updated after retry.")
    assert len(calls) == 2
    assert calls[0].endswith("kfc.log")
    assert calls[1].endswith("kfc.retry.log")


def test_missing_success_marker_is_not_reported_as_success(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs["stdout"].name)
        kwargs["stdout"].write("Started but no completion result\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pull_all, "LOG_DIR", tmp_path)
    monkeypatch.setattr(pull_all.subprocess, "run", fake_run)
    monkeypatch.setattr(pull_all.time, "sleep", lambda seconds: None)
    status, message = PullManager._run_subprocess(TARGETS[0], "missing-marker")
    assert status == "failed"
    assert "without confirming completion" in message
    assert len(calls) == 2


def test_partial_collection_retries_and_can_recover(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs["stdout"].name)
        kwargs["stdout"].write(
            "[RUN] Finished. Overall status: PARTIAL\n  - PICKUP: PARTIAL\n"
            if len(calls) == 1 else "[RUN] Finished. Overall status: SUCCESS\n"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pull_all, "LOG_DIR", tmp_path)
    monkeypatch.setattr(pull_all.subprocess, "run", fake_run)
    monkeypatch.setattr(pull_all.time, "sleep", lambda seconds: None)
    status, message = PullManager._run_subprocess(TARGETS[1], "partial-run")
    assert (status, message) == ("success", "Data updated after retry.")
    assert len(calls) == 2


def test_server_restart_marks_unfinished_run_and_keeps_completed_source(tmp_path) -> None:
    path = tmp_path / "latest.json"
    targets = (PullTarget("kudu", "KUDU", ()), PullTarget("kfc", "KFC", ()))
    path.write_text(json.dumps({
        "runId": "interrupted", "status": "running", "startedAt": "2026-01-01T00:00:00+00:00", "completedAt": None,
        "brands": [
            {"id": "kudu", "name": "KUDU", "status": "success", "message": "Data updated.", "startedAt": None, "completedAt": None},
            {"id": "kfc", "name": "KFC", "status": "running", "message": None, "startedAt": None, "completedAt": None},
        ],
    }))
    manager = PullManager(targets=targets, state_path=path)
    recovered = manager.latest()
    assert recovered["status"] == "partial"
    assert recovered["brands"][0]["status"] == "success"
    assert recovered["brands"][1]["status"] == "failed"
    assert "server restart" in recovered["brands"][1]["message"]
    assert recovered["completedAt"]
    assert json.loads(path.read_text())["status"] == "partial"
