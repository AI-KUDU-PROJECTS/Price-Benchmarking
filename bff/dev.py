"""Start the React development server and FastAPI BFF together."""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PYTHON = ROOT / ".venv" / "bin" / "python"
PORT = 5173


def wsl_ip() -> str:
    addresses = subprocess.check_output(["hostname", "-I"], text=True).split()
    for address in addresses:
        if not address.startswith(("127.", "10.255.")):
            return address
    return addresses[0]


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
        error = (result.stderr or result.stdout or "").strip()
        if error:
            print(error)
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
        children.append(
            subprocess.Popen([python, str(ROOT / "manage.py"), "api"], cwd=ROOT, env=env)
        )
    if port_open("127.0.0.1", PORT):
        print(f"Frontend already running on http://127.0.0.1:{PORT}")
    else:
        children.append(subprocess.Popen(["npm", "run", "dev"], cwd=FRONTEND, env=env))

    def shutdown(_signum=None, _frame=None) -> None:
        for process in children:
            if process.poll() is None:
                process.terminate()
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    bff_ready = wait_for_port("127.0.0.1", 8000)
    ui_ready = wait_for_port("127.0.0.1", PORT)
    share_url = share_on_lan()

    print("\nKudu Price Intelligence")
    if not bff_ready:
        print("BFF did not start on http://127.0.0.1:8000")
    if not ui_ready:
        print(f"Frontend did not start on http://127.0.0.1:{PORT}")
    print(f"Local:  http://127.0.0.1:{PORT}")
    print(f"Share:  {share_url or 'unavailable until Windows LAN forwarding is allowed'}")
    print("API:    http://127.0.0.1:8000")
    if children:
        print("Ctrl+C to stop")
    print()

    if not children:
        return 0
    try:
        while not any(process.poll() is not None for process in children):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
