"""
tests/test_scheduler_lock.py
Covers required test #15: Scheduler locking (spec: "Prevent concurrent
runs. Use a lock file ... so that another run cannot start while one is
already active.").
"""
from __future__ import annotations

import time

import pytest

from competitors.kfc.backend import run_service


def test_lock_prevents_concurrent_acquisition(monkeypatch, tmp_path):
    monkeypatch.setattr(run_service.config, "LOCK_FILE", tmp_path / "collector.lock")

    with run_service.run_lock():
        assert run_service.is_run_active() is True
        with pytest.raises(run_service.RunAlreadyInProgressError):
            with run_service.run_lock():
                pass  # must never get here

    # Lock is released after the `with` block exits.
    assert run_service.is_run_active() is False


def test_lock_is_released_even_if_the_protected_code_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(run_service.config, "LOCK_FILE", tmp_path / "collector.lock")

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with run_service.run_lock():
            raise Boom("simulated failure inside a run")

    assert run_service.is_run_active() is False


def test_stale_lock_is_reclaimed_automatically(monkeypatch, tmp_path):
    lock_file = tmp_path / "collector.lock"
    monkeypatch.setattr(run_service.config, "LOCK_FILE", lock_file)
    monkeypatch.setattr(run_service, "LOCK_STALE_SECONDS", 1)  # shrink the staleness window for the test

    lock_file.write_text("{}")
    old_time = time.time() - 5
    import os
    os.utime(lock_file, (old_time, old_time))

    assert run_service.is_run_active() is False  # older than the (shrunk) staleness window
    with run_service.run_lock():
        assert lock_file.exists()  # reclaimed successfully, not left blocking forever
    assert not lock_file.exists()


def test_fresh_lock_is_not_reclaimed(monkeypatch, tmp_path):
    lock_file = tmp_path / "collector.lock"
    monkeypatch.setattr(run_service.config, "LOCK_FILE", lock_file)
    lock_file.write_text("{}")  # just created - fresh mtime

    assert run_service.is_run_active() is True
    with pytest.raises(run_service.RunAlreadyInProgressError):
        with run_service.run_lock():
            pass
