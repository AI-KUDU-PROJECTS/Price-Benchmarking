"""Automatic collection runs websites, then HungerStation, never together."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import bff.auto_pull as auto_pull
from bff.app import app
from bff.pull_all import HUNGERSTATION_TARGETS, PullManager, PullTarget, TARGETS


def test_parse_times_sorts_dedupes_and_skips_invalid_values() -> None:
    assert auto_pull.parse_times(" 15:30, 7:05,bad,24:00,07:05,,11:00 ") == ["07:05", "11:00", "15:30"]
    assert auto_pull.parse_times("") == []
    assert auto_pull.parse_times(None) == []


def test_scheduled_pull_runs_websites_before_hungerstation(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    active: set[str] = set()
    lock = threading.Lock()

    def runner_for(group: str):
        def runner(target: PullTarget, run_id: str) -> tuple[str, str]:
            with lock:
                active.add(group)
                if len(active) > 1:
                    events.append("overlap")
            events.append(f"{group}:{target.id}")
            time.sleep(0.005)
            with lock:
                active.discard(group)
            return "success", "Data updated."
        return runner

    websites = PullManager(targets=TARGETS, runner=runner_for("websites"))
    hungerstation = PullManager(targets=HUNGERSTATION_TARGETS, runner=runner_for("hs"), max_workers=1)
    monkeypatch.setattr(auto_pull, "pull_manager", websites)
    monkeypatch.setattr(auto_pull, "hungerstation_pull_manager", hungerstation)

    auto_pull.run_scheduled_pull(include_hungerstation=True, poll_seconds=0.01)

    assert "overlap" not in events
    first_hs = next(index for index, event in enumerate(events) if event.startswith("hs:"))
    assert all(event.startswith("websites:") for event in events[:first_hs])
    assert len(events) == len(TARGETS) + len(HUNGERSTATION_TARGETS)
    assert websites.latest()["trigger"] == "scheduled"
    assert hungerstation.latest()["trigger"] == "scheduled"


def test_scheduled_pull_can_skip_hungerstation(monkeypatch: pytest.MonkeyPatch) -> None:
    websites = PullManager(targets=TARGETS, runner=lambda target, run_id: ("success", "ok"))
    hungerstation = PullManager(targets=HUNGERSTATION_TARGETS, runner=lambda target, run_id: ("success", "ok"))
    monkeypatch.setattr(auto_pull, "pull_manager", websites)
    monkeypatch.setattr(auto_pull, "hungerstation_pull_manager", hungerstation)

    auto_pull.run_scheduled_pull(include_hungerstation=False, poll_seconds=0.01)

    assert websites.latest()["status"] == "success"
    assert hungerstation.latest() is None


def test_scheduler_starts_from_env_and_reports_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_PULL_TIMES", "11:00,15:30")
    monkeypatch.setenv("AUTO_PULL_HUNGERSTATION", "false")
    try:
        assert auto_pull.start_from_env() is not None
        status = TestClient(app).get("/api/v1/market/pull/schedule").json()
    finally:
        auto_pull.stop()

    assert status["enabled"] is True
    assert status["times"] == ["11:00", "15:30"]
    assert status["includeHungerstation"] is False
    assert status["timezone"] == "Asia/Riyadh"
    assert status["nextRunAt"].endswith("+03:00")
    assert status["nextRunAt"][11:16] in {"11:00", "15:30"}


def test_scheduler_is_off_without_times(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_PULL_TIMES", "")
    assert auto_pull.start_from_env() is None
    status = TestClient(app).get("/api/v1/market/pull/schedule").json()
    assert status["enabled"] is False
    assert status["nextRunAt"] is None
