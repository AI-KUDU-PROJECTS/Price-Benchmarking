"""Bounded, process-local cache for file-backed restaurant reads only.

Authentication still runs on every HTTP request. No sessions or user data are
cached here. DB/WAL and JSON signatures invalidate entries on the next request;
the short TTL also bounds time-dependent freshness and recent-event windows.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


@dataclass
class _Entry:
    version: Hashable
    expires: float
    value: Any


class ReadCache:
    def __init__(self, max_entries: int = 128, ttl: float = 30,
                 clock: Callable[[], float] = monotonic):
        self.max_entries = max_entries
        self.ttl = ttl
        self.clock = clock
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._lock = Lock()
        # Fixed stripes bound lock memory and coalesce simultaneous cold reads.
        self._loads = [Lock() for _ in range(32)]

    def get(self, key: Hashable, version: Callable[[], Hashable | None],
            load: Callable[[], T]) -> T:
        with self._loads[hash(key) % len(self._loads)]:
            before = version()
            with self._lock:
                entry = self._entries.get(key)
                if (before is not None and entry is not None
                        and entry.version == before and self.clock() < entry.expires):
                    self._entries.move_to_end(key)
                    value = entry.value
                else:
                    self._entries.pop(key, None)
                    value = None
                    entry = None
            if entry is not None:
                return deepcopy(value)

            result = load()  # Failures are never cached or replaced by stale data.
            if before is not None and version() == before:
                entry = _Entry(before, self.clock() + self.ttl, deepcopy(result))
                with self._lock:
                    self._entries[key] = entry
                    self._entries.move_to_end(key)
                    while len(self._entries) > self.max_entries:
                        self._entries.popitem(last=False)
            return result


def file_version(paths: tuple[Path, ...]) -> tuple | None:
    result = []
    for path in paths:
        try:
            stat = path.stat()
        except FileNotFoundError:
            result.append(None)
        except OSError:
            return None  # Cannot verify the current version: bypass the cache.
        else:
            # A read-only SQLite connection can create an empty WAL sidecar.
            # No pages means no data change; treat it like an absent WAL.
            result.append(None if path.name.endswith("-wal") and stat.st_size == 0 else
                          (stat.st_dev, stat.st_ino, stat.st_size,
                           stat.st_mtime_ns, stat.st_ctime_ns))
    return tuple(result)


def _source(adapter: Any) -> tuple[tuple, tuple[Path, ...]] | None:
    paths: list[Path] = []
    for attribute in ("db_path", "catalog_path", "hungerstation_path"):
        path = getattr(adapter, attribute, None)
        if path is not None:
            path = Path(path).resolve()
            paths.append(path)
            if attribute == "db_path":
                paths.append(path.with_name(path.name + "-wal"))
    base_key = None
    base = getattr(adapter, "base", None)
    if base is not None:
        source = _source(base)
        if source is None:
            return None
        base_key, base_paths = source
        paths.extend(base_paths)
    if not paths:
        return None  # No reliable invalidation for in-memory/custom adapters.
    identity = (type(adapter).__module__, type(adapter).__qualname__,
                getattr(adapter, "brand_id", None), getattr(adapter, "branch_id", None),
                tuple(str(path) for path in paths), base_key)
    return identity, tuple(paths)


_cache = ReadCache()


def cached_read(adapter: Any, key: tuple, load: Callable[[], T]) -> T:
    source = _source(adapter)
    if source is None:
        return load()
    identity, paths = source
    return _cache.get((identity, key), lambda: file_version(paths), load)


def data_version(adapters: dict[str, Any]) -> str | None:
    """Opaque version covering every DB/WAL/catalog, including overlay sources.

    No TTL here: a committed write or atomic catalog replacement must be seen
    by the very next validation request. Unknown sources disable browser reuse.
    """
    from hashlib import sha256
    import json

    sources = []
    for brand_id, adapter in sorted(adapters.items()):
        source = _source(adapter)
        if source is None:
            return None
        identity, paths = source
        version = file_version(paths)
        if version is None:
            return None
        sources.append((brand_id, identity, version))
    return sha256(json.dumps(("restaurant-data-v1", sources)).encode()).hexdigest()
