"""Automatic collection runs websites, HungerStation, and Albaik in order."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import bff.auto_pull as auto_pull
from bff.app import app
from bff.pull_all import ALBAIK_APP_TARGETS, HUNGERSTATION_TARGETS, PullManager, PullTarget, TARGETS


def test_parse_times_sorts_dedupes_and_skips_invalid_values() -> None:
    assert auto_pull.parse_times(" 15:30, 7:05,bad,24:00,07:05,,11:00 ") == ["07:05", "11:00", "15:30"]
    assert auto_pull.parse_times("") == []
    assert auto_pull.parse_times(None) == []


def test_scheduled_pull_runs_websites_then_hungerstation_then_albaik(monkeypatch: pytest.MonkeyPatch) -> None:
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
    albaik = PullManager(targets=ALBAIK_APP_TARGETS, runner=runner_for("albaik"), max_workers=1)
    monkeypatch.setattr(auto_pull, "pull_manager", websites)
    monkeypatch.setattr(auto_pull, "hungerstation_pull_manager", hungerstation)
    monkeypatch.setattr(auto_pull, "albaik_app_pull_manager", albaik)

    auto_pull.run_scheduled_pull(include_hungerstation=True, poll_seconds=0.01)

    assert "overlap" not in events
    first_hs = next(index for index, event in enumerate(events) if event.startswith("hs:"))
    assert all(event.startswith("websites:") for event in events[:first_hs])
    first_albaik = next(index for index, event in enumerate(events) if event.startswith("albaik:"))
    assert all(event.startswith("hs:") for event in events[first_hs:first_albaik])
    assert events[first_albaik:] == ["albaik:albaik-pickup", "albaik:albaik-delivery"]
    assert len(events) == len(TARGETS) + len(HUNGERSTATION_TARGETS) + len(ALBAIK_APP_TARGETS)
    assert websites.latest()["trigger"] == "scheduled"
    assert hungerstation.latest()["trigger"] == "scheduled"
    assert albaik.latest()["trigger"] == "scheduled"


@pytest.mark.parametrize("include_albaik_app", [True, False])
def test_scheduled_pull_can_skip_optional_collectors(monkeypatch: pytest.MonkeyPatch, include_albaik_app: bool) -> None:
    websites = PullManager(targets=TARGETS, runner=lambda target, run_id: ("success", "ok"))
    hungerstation = PullManager(targets=HUNGERSTATION_TARGETS, runner=lambda target, run_id: ("success", "ok"))
    albaik = PullManager(targets=ALBAIK_APP_TARGETS, runner=lambda target, run_id: ("success", "ok"), max_workers=1)
    monkeypatch.setattr(auto_pull, "pull_manager", websites)
    monkeypatch.setattr(auto_pull, "hungerstation_pull_manager", hungerstation)
    monkeypatch.setattr(auto_pull, "albaik_app_pull_manager", albaik)

    auto_pull.run_scheduled_pull(include_hungerstation=False, include_albaik_app=include_albaik_app, poll_seconds=0.01)

    assert websites.latest()["status"] == "success"
    assert hungerstation.latest() is None
    if include_albaik_app:
        assert albaik.latest()["status"] == "success"
    else:
        assert albaik.latest() is None


@pytest.mark.parametrize("include_albaik_app", [True, False])
def test_scheduler_starts_from_env_and_reports_next_run(monkeypatch: pytest.MonkeyPatch, include_albaik_app: bool) -> None:
    monkeypatch.setenv("AUTO_PULL_TIMES", "11:00,15:30")
    monkeypatch.setenv("AUTO_PULL_HUNGERSTATION", "false")
    monkeypatch.setenv("AUTO_PULL_ALBAIK_APP", str(include_albaik_app))
    try:
        assert auto_pull.start_from_env() is not None
        assert all(job.kwargs["include_albaik_app"] is include_albaik_app for job in auto_pull._scheduler.get_jobs())
        status = TestClient(app).get("/api/v1/market/pull/schedule").json()
    finally:
        auto_pull.stop()

    assert status["enabled"] is True
    assert status["times"] == ["11:00", "15:30"]
    assert status["includeHungerstation"] is False
    assert status["includeAlbaikApp"] is include_albaik_app
    assert status["timezone"] == "Asia/Riyadh"
    assert status["nextRunAt"].endswith("+03:00")
    assert status["nextRunAt"][11:16] in {"11:00", "15:30"}


def test_scheduler_is_off_without_times(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_PULL_TIMES", "")
    assert auto_pull.start_from_env() is None
    status = TestClient(app).get("/api/v1/market/pull/schedule").json()
    assert status["enabled"] is False
    assert status["nextRunAt"] is None
