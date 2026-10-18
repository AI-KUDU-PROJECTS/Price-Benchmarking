from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from competitors.hungerstation import collector, emulator_lifecycle


def test_session_restarts_waits_and_stops_after_collection(monkeypatch, tmp_path) -> None:
    events = []
    monkeypatch.setattr(emulator_lifecycle, "LOCK_PATH", tmp_path / "emulator.lock")
    monkeypatch.setattr(
        emulator_lifecycle, "_systemctl",
        lambda action, service: events.append((action, service)),
    )
    monkeypatch.setattr(emulator_lifecycle, "_wait_for_boot", lambda device: events.append("booted"))

    with emulator_lifecycle.emulator_session(object(), "android-emulator.service"):
        events.append("collected")

    assert events == [
        ("restart", "android-emulator.service"), "booted", "collected",
        ("stop", "android-emulator.service"),
    ]


def test_session_stops_when_collection_fails(monkeypatch, tmp_path) -> None:
    actions = []
    monkeypatch.setattr(emulator_lifecycle, "LOCK_PATH", tmp_path / "emulator.lock")
    monkeypatch.setattr(emulator_lifecycle, "_systemctl", lambda action, service: actions.append(action))
    monkeypatch.setattr(emulator_lifecycle, "_wait_for_boot", lambda device: None)

    with pytest.raises(RuntimeError, match="collection failed"):
        with emulator_lifecycle.emulator_session(object(), "android-emulator.service"):
            raise RuntimeError("collection failed")
    assert actions == ["restart", "stop"]


def test_session_stops_when_boot_fails(monkeypatch, tmp_path) -> None:
    actions = []
    monkeypatch.setattr(emulator_lifecycle, "LOCK_PATH", tmp_path / "emulator.lock")
    monkeypatch.setattr(emulator_lifecycle, "_systemctl", lambda action, service: actions.append(action))
    monkeypatch.setattr(
        emulator_lifecycle, "_wait_for_boot",
        lambda device: (_ for _ in ()).throw(RuntimeError("boot failed")),
    )

    with pytest.raises(RuntimeError, match="boot failed"):
        with emulator_lifecycle.emulator_session(object(), "android-emulator.service"):
            pass
    assert actions == ["restart", "stop"]


def test_main_uses_one_session_per_restaurant_and_skips_saved_captures(monkeypatch, tmp_path) -> None:
    events = []
    monkeypatch.setattr(collector.config, "EMULATOR_SERVICE", "android-emulator.service")
    monkeypatch.setattr(collector.config, "RESTAURANTS", collector.config.RESTAURANTS[:2])
    monkeypatch.setattr(collector.database, "init_db", lambda path: None)
    monkeypatch.setattr(collector, "find_adb", lambda explicit: Path("/fake/adb"))

    @contextmanager
    def session(device, service):
        events.append("start")
        try:
            yield
        finally:
            events.append("stop")

    monkeypatch.setattr(emulator_lifecycle, "emulator_session", session)
    monkeypatch.setattr(
        collector, "collect_restaurant",
        lambda restaurant, **kwargs: events.append(restaurant.id) or {
            "brand_id": restaurant.id, "name": restaurant.name, "status": "success",
            "run_id": restaurant.id, "product_count": 1,
        },
    )
    monkeypatch.setattr(sys, "argv", ["collector", "--all", "--db", str(tmp_path / "data.db")])
    assert collector.main() == 0
    assert events == ["start", "kfc", "stop", "start", "hardees", "stop"]

    events.clear()
    monkeypatch.setattr(sys, "argv", [
        "collector", "--brand", "kfc", "--from-capture", str(tmp_path / "capture.xml"),
    ])
    assert collector.main() == 0
    assert events == ["kfc"]
