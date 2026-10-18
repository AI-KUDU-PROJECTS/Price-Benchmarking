"""Own the server's Android emulator for one live restaurant collection."""
from __future__ import annotations

import fcntl
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from competitors.hungerstation.collector import AndroidDevice, CollectionFailure

LOCK_PATH = Path("/tmp/hungerstation-emulator.lock")
BOOT_TIMEOUT_SECONDS = 240


def _systemctl(action: str, service: str) -> None:
    try:
        subprocess.run(
            ["sudo", "-n", "systemctl", action, service],
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        detail = getattr(error, "stderr", "") or str(error)
        raise CollectionFailure(
            f"EMULATOR_{action.upper()}_FAILED",
            f"Android emulator could not {action}: {' '.join(detail.split())[:300]}",
        ) from error


def _wait_for_boot(device: AndroidDevice) -> None:
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            state = device.run("get-state", attempts=1).strip()
            booted = device.run("shell", "getprop", "sys.boot_completed", attempts=1).strip()
            if state == "device" and booted == "1":
                return
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    raise CollectionFailure(
        "EMULATOR_BOOT_TIMEOUT",
        f"Android emulator {device.serial} did not finish booting within {BOOT_TIMEOUT_SECONDS} seconds.",
    )


@contextmanager
def emulator_session(device: AndroidDevice, service: str) -> Iterator[None]:
    """Restart before a collection, then stop, even when collection fails."""
    with LOCK_PATH.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                _systemctl("restart", service)
                _wait_for_boot(device)
                yield
            finally:
                _systemctl("stop", service)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
