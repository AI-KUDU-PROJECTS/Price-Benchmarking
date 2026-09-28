"""Run the connected collectors together without blocking BFF requests."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "bff" / "data" / "pull_logs"
STATE_PATH = LOG_DIR / "latest.json"
HUNGERSTATION_STATE_PATH = LOG_DIR / "hungerstation-latest.json"
TIMEOUT_SECONDS = 45 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class PullTarget:
    id: str
    name: str
    args: tuple[str, ...]


# These are the five connected sources. The four competitor wrappers keep
# their existing collection, database, and per-brand locking behavior.
TARGETS = (
    PullTarget("kudu", "KUDU", ("-m", "kudu.refresh")),
    PullTarget("kfc", "KFC", ("run_kfc_collector.py", "--channel=BOTH", "--no-screenshots")),
    PullTarget("hardees", "Hardee's", ("run_hardees_collector.py", "--channel=BOTH", "--no-screenshots")),
    PullTarget("burger-king", "Burger King", ("run_burger_king_collector.py", "--channel=BOTH", "--no-screenshots")),
    PullTarget("herfy", "Herfy", ("run_herfy_collector.py", "--channel=BOTH", "--no-screenshots")),
)

HUNGERSTATION_TARGETS = (
    PullTarget("kfc", "KFC", ("run_hungerstation_collector.py", "--brand", "kfc")),
    PullTarget("hardees", "Hardee's", ("run_hungerstation_collector.py", "--brand", "hardees")),
    PullTarget("burger-king", "Burger King", ("run_hungerstation_collector.py", "--brand", "burger-king")),
    PullTarget("herfy", "Herfy", ("run_hungerstation_collector.py", "--brand", "herfy")),
    PullTarget("mcdonalds", "McDonald's", ("run_hungerstation_collector.py", "--brand", "mcdonalds")),
    PullTarget("albaik", "AlBaik", ("run_hungerstation_collector.py", "--brand", "albaik")),
)

Runner = Callable[[PullTarget, str], tuple[str, str]]


class PullManager:
    def __init__(self, targets: tuple[PullTarget, ...] = TARGETS, runner: Runner | None = None,
                 state_path: Path | None = None, max_workers: int | None = None) -> None:
        self.targets = targets
        self.runner = runner or self._run_subprocess
        self.state_path = state_path
        self.max_workers = max_workers or len(targets)
        self._lock = threading.Lock()
        self._run: dict | None = None
        if state_path and state_path.exists():
            try:
                loaded = json.loads(state_path.read_text(encoding="utf-8"))
                if (
                    isinstance(loaded, dict)
                    and isinstance(loaded.get("runId"), str)
                    and loaded.get("status") in {"running", "success", "partial", "failed"}
                    and isinstance(loaded.get("brands"), list)
                    and [row.get("id") for row in loaded["brands"] if isinstance(row, dict)]
                    == [target.id for target in self.targets]
                ):
                    self._run = loaded
            except (OSError, ValueError):
                pass
        if self._run and self._run.get("status") == "running":
            # Background threads cannot survive a BFF restart. Never leave
            # the button disabled indefinitely or claim that work finished.
            for row in self._run["brands"]:
                if row.get("status") in {"pending", "running"}:
                    row.update(status="failed", message="Collection interrupted by server restart.", completedAt=_now())
            self._finish_locked()

    def _save_locked(self) -> None:
        if not self.state_path or self._run is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(self._run), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def _finish_locked(self) -> None:
        if self._run is None:
            return
        statuses = [row["status"] for row in self._run["brands"]]
        self._run["status"] = (
            "success" if statuses and all(status == "success" for status in statuses)
            else "partial" if any(status in ("success", "partial") for status in statuses)
            else "failed"
        )
        self._run["completedAt"] = _now()
        self._save_locked()

    def latest(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._run)

    def start(self) -> tuple[dict, bool]:
        with self._lock:
            if self._run and self._run["status"] == "running":
                return copy.deepcopy(self._run), False
            run_id = uuid.uuid4().hex
            self._run = {
                "runId": run_id,
                "status": "running",
                "startedAt": _now(),
                "completedAt": None,
                "brands": [
                    {"id": target.id, "name": target.name, "status": "pending", "startedAt": None,
                     "completedAt": None, "message": None}
                    for target in self.targets
                ],
            }
            self._save_locked()
            snapshot = copy.deepcopy(self._run)
        threading.Thread(target=self._execute, args=(run_id,), daemon=True, name=f"pull-all-{run_id[:8]}").start()
        return snapshot, True

    def _set_brand(self, run_id: str, brand_id: str, **changes: object) -> None:
        with self._lock:
            if self._run and self._run["runId"] == run_id:
                row = next(row for row in self._run["brands"] if row["id"] == brand_id)
                row.update(changes)
                self._save_locked()

    def _execute_one(self, target: PullTarget, run_id: str) -> tuple[str, str]:
        self._set_brand(run_id, target.id, status="running", startedAt=_now())
        return self.runner(target, run_id)

    def _execute(self, run_id: str) -> None:
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._execute_one, target, run_id): target for target in self.targets}
            for future in as_completed(futures):
                target = futures[future]
                try:
                    status, message = future.result()
                except Exception as exc:  # one collector must not block the other results
                    status, message = "failed", f"Collector could not start: {type(exc).__name__}"
                self._set_brand(run_id, target.id, status=status, message=message, completedAt=_now())
        with self._lock:
            if self._run and self._run["runId"] == run_id:
                self._finish_locked()

    @staticmethod
    def _run_subprocess(target: PullTarget, run_id: str) -> tuple[str, str]:
        log_dir = LOG_DIR / run_id
        log_dir.mkdir(parents=True, exist_ok=True)
        # Every source uses read-only fetches. A failed or incomplete pass can
        # be retried once without replacing its last complete snapshot.
        attempts = 2
        best_partial: str | None = None
        last_failure = "Collection failed."
        for attempt in range(attempts):
            log_path = log_dir / (f"{target.id}.log" if attempt == 0 else f"{target.id}.retry.log")
            with log_path.open("w", encoding="utf-8") as output:
                try:
                    result = subprocess.run(
                        [sys.executable, *target.args],
                        cwd=ROOT,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        env={**os.environ, "PULL_RUN_ID": run_id},
                        timeout=TIMEOUT_SECONDS,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    return ("partial", best_partial) if best_partial else ("failed", "Collector timed out; previous data kept.")
            output_text = log_path.read_text(encoding="utf-8", errors="replace")
            if result.returncode == 2 and "Refused to start" in output_text:
                return "already_running", "A separate collection is already running for this brand."
            if target.args and target.args[0] == "run_hungerstation_collector.py":
                match = re.search(
                    rf"HUNGERSTATION_RESULT brand={re.escape(target.id)} status=(SUCCESS|FAILED) products=(\d+)",
                    output_text,
                )
                confirmed = match.group(1).lower() if match else None
                if confirmed == "success":
                    count = int(match.group(2))
                    return "success", f"Collected {count} products from HungerStation."
            elif target.id == "kudu":
                confirmed = "success" if "KUDU catalog updated:" in output_text else None
            else:
                match = re.search(r"\[RUN\] Finished\. Overall status: (SUCCESS|PARTIAL|FAILED)", output_text)
                confirmed = match.group(1).lower() if match else None
            if result.returncode == 0 and confirmed == "success":
                return "success", "Data updated after retry." if attempt else "Data updated."
            if result.returncode == 0 and confirmed == "partial":
                channels = re.findall(r"^  - (PICKUP|DELIVERY): (PARTIAL|FAILED)", output_text, re.MULTILINE)
                names = ", ".join(channel.lower() for channel, _ in channels) or "One channel"
                best_partial = f"{names} incomplete; previous complete data kept."
                last_failure = best_partial
            elif result.returncode == 0 and confirmed is None:
                last_failure = "Collector exited without confirming completion."
            else:
                last_failure = f"Collector failed (exit {result.returncode}); previous complete data kept."
            if attempt + 1 < attempts:
                time.sleep(8)
        return ("partial", best_partial) if best_partial else ("failed", last_failure)


pull_manager = PullManager(state_path=STATE_PATH)
hungerstation_pull_manager = PullManager(
    targets=HUNGERSTATION_TARGETS,
    state_path=HUNGERSTATION_STATE_PATH,
    max_workers=1,
)
