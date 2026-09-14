#!/usr/bin/env python3
"""Start the marketing app so it can be opened locally and on the LAN."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
PYTHON = ROOT / ".venv" / "bin" / "python"
PORT = 5173


def wsl_ip() -> str:
    hostname = subprocess.check_output(["hostname", "-I"], text=True).split()
    for ip in hostname:
        if ip.startswith("127.") or ip.startswith("10.255."):
            continue
        return ip
    return hostname[0]


def windows_path(path: Path) -> str:
    return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()


def share_on_lan() -> str | None:
    script = ROOT / "scripts" / "share_lan.ps1"
    if not script.exists():
        return None
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(script),
                "-WslIp",
                wsl_ip(),
                "-Port",
                str(PORT),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    share_url = None
    for line in (result.stdout or "").splitlines():
        if line.startswith("SHARE_URL="):
            share_url = line.split("=", 1)[1].strip()
        elif line.startswith("SHARE_STATUS=") and "needs-admin" in line:
            print("LAN sharing needs Administrator approval in the Windows prompt.")
    if result.returncode != 0 and not share_url:
        err = (result.stderr or result.stdout or "").strip()
        if err:
            print(err)
    return share_url


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(host, port):
            return True
        time.sleep(0.2)
    return False


def main() -> int:
    python = str(PYTHON if PYTHON.exists() else Path(sys.executable))
    env = os.environ.copy()
    children: list[subprocess.Popen] = []
    if port_open("127.0.0.1", 8000):
        print("BFF already running on http://127.0.0.1:8000")
    else:
        children.append(subprocess.Popen([python, str(ROOT / "run_bff.py")], cwd=ROOT, env=env))
    if port_open("127.0.0.1", PORT):
        print(f"Frontend already running on http://127.0.0.1:{PORT}")
    else:
        children.append(subprocess.Popen(["npm", "run", "dev"], cwd=FRONTEND, env=env))

    def shutdown(_signum=None, _frame=None) -> None:
        for proc in children:
            if proc.poll() is None:
                proc.terminate()
        for proc in children:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    bff_ready = wait_for_port("127.0.0.1", 8000)
    ui_ready = wait_for_port("127.0.0.1", PORT)
    share_url = share_on_lan()

    print()
    print("Kudu Price Intelligence")
    if not bff_ready:
        print("BFF did not start on http://127.0.0.1:8000")
    if not ui_ready:
        print(f"Frontend did not start on http://127.0.0.1:{PORT}")
    print(f"Local:  http://127.0.0.1:{PORT}")
    if share_url:
        print(f"Share:  {share_url}")
    else:
        print("Share:  unavailable until Windows LAN forwarding is allowed")
    print("API:    http://127.0.0.1:8000")
    if children:
        print("Ctrl+C to stop")
    print()

    if not children:
        return 0

    try:
        while True:
            if any(proc.poll() is not None for proc in children):
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
