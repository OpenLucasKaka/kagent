from __future__ import annotations

import json
import sqlite3
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Condition, Lock
from typing import Any, Dict, Optional, Protocol, Tuple
from uuid import uuid4

from kagent.utils.json_output import json_ready

IdempotencyResponse = Tuple[int, Any]
IdempotencyAcquireResult = Tuple[str, Optional[IdempotencyResponse], str]


class IdempotencyCache(Protocol):
    def acquire(
        self,
        key: str,
        body: bytes,
        *,
        lease_seconds: float,
        wait_timeout_seconds: float,
    ) -> IdempotencyAcquireResult: ...

    def complete(
        self,
        key: str,
        body: bytes,
        claim_token: str,
        status_code: int,
        payload: Any,
    ) -> bool: ...

    def release(self, key: str, claim_token: str) -> bool: ...

    def lookup(self, key: str, body: bytes) -> Tuple[str, Optional[IdempotencyResponse]]: ...

    def store(self, key: str, body: bytes, status_code: int, payload: Any) -> None: ...

    def snapshot(self) -> Dict[str, str]: ...


class _IdempotencyMetrics:
    def __init__(self) -> None:
        self._hits = 0
        self._misses = 0
        self._conflicts = 0
        self._stores = 0
        self._evictions = 0
        self._claims = 0
        self._waits = 0
        self._wait_timeouts = 0
        self._takeovers = 0

    def _metrics_snapshot(
        self,
        *,
        entry_count: int,
        max_entries: int,
        backend: str,
    ) -> Dict[str, str]:
        return {
            "idempotency_cache_backend": backend,
            "idempotency_cache_entries": str(entry_count),
            "idempotency_cache_size": str(max_entries),
            "idempotency_cache_hits": str(self._hits),
            "idempotency_cache_misses": str(self._misses),
            "idempotency_cache_conflicts": str(self._conflicts),
            "idempotency_cache_stores": str(self._stores),
            "idempotency_cache_evictions": str(self._evictions),
            "idempotency_cache_claims": str(self._claims),
            "idempotency_cache_waits": str(self._waits),
            "idempotency_cache_wait_timeouts": str(self._wait_timeouts),
            "idempotency_cache_takeovers": str(self._takeovers),
        }


@dataclass
class _MemoryRecord:
    fingerprint: str
    state: str
    status_code: int = 0
    payload: Any = None
    owner_token: str = ""
    lease_expires_at: float = 0.0


class ServiceIdempotencyCache(_IdempotencyMetrics):
    def __init__(self, *, max_entries: int) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        super().__init__()
        self._max_entries = max_entries
        self._condition = Condition()
        self._records: "OrderedDict[str, _MemoryRecord]" = OrderedDict()

    def acquire(
        self,
        key: str,
        body: bytes,
        *,
        lease_seconds: float,
        wait_timeout_seconds: float,
    ) -> IdempotencyAcquireResult:
        _validate_acquire_timeouts(lease_seconds, wait_timeout_seconds)
        if self._max_entries == 0:
            return "disabled", None, ""
        fingerprint = _request_body_fingerprint(body)
        claim_token = str(uuid4())
        deadline = time.monotonic() + wait_timeout_seconds
        recorded_wait = False
        with self._condition:
            while True:
                now = time.monotonic()
                record = self._records.get(key)
                if record is None:
                    self._records[key] = _MemoryRecord(
                        fingerprint=fingerprint,
                        state="pending",
                        owner_token=claim_token,
                        lease_expires_at=now + lease_seconds,
                    )
                    self._records.move_to_end(key)
                    self._misses += 1
                    self._claims += 1
                    self._evict_completed_over_capacity()
                    return "claimed", None, claim_token
                self._records.move_to_end(key)
                if record.fingerprint != fingerprint:
                    self._conflicts += 1
                    return "conflict", None, ""
                if record.state == "completed":
                    self._hits += 1
                    return "hit", (record.status_code, deepcopy(record.payload)), ""
                if record.lease_expires_at <= now:
                    record.owner_token = claim_token
                    record.lease_expires_at = now + lease_seconds
                    self._claims += 1
                    self._takeovers += 1
                    return "claimed", None, claim_token
                remaining = deadline - now
                if remaining <= 0:
                    self._wait_timeouts += 1
                    return "in_progress", None, ""
                if not recorded_wait:
                    self._waits += 1
                    recorded_wait = True
                self._condition.wait(
                    timeout=min(remaining, max(0.001, record.lease_expires_at - now))
                )

    def complete(
        self,
        key: str,
        body: bytes,
        claim_token: str,
        status_code: int,
        payload: Any,
    ) -> bool:
        fingerprint = _request_body_fingerprint(body)
        with self._condition:
            record = self._records.get(key)
            if (
                record is None
                or record.state != "pending"
                or record.fingerprint != fingerprint
                or record.owner_token != claim_token
            ):
                return False
            record.state = "completed"
            record.status_code = int(status_code)
            record.payload = deepcopy(payload)
            record.owner_token = ""
            record.lease_expires_at = 0.0
            self._records.move_to_end(key)
            self._stores += 1
            self._evict_completed_over_capacity()
            self._condition.notify_all()
            return True

    def release(self, key: str, claim_token: str) -> bool:
        with self._condition:
            record = self._records.get(key)
            if (
                record is None
                or record.state != "pending"
                or record.owner_token != claim_token
            ):
                return False
            del self._records[key]
            self._condition.notify_all()
            return True

    def lookup(self, key: str, body: bytes) -> Tuple[str, Optional[IdempotencyResponse]]:
        if self._max_entries == 0:
            return "disabled", None
        fingerprint = _request_body_fingerprint(body)
        with self._condition:
            record = self._records.get(key)
            if record is None:
                self._misses += 1
                return "miss", None
            self._records.move_to_end(key)
            if record.fingerprint != fingerprint:
                self._conflicts += 1
                return "conflict", None
            if record.state == "pending":
                return "in_progress", None
            self._hits += 1
            return "hit", (record.status_code, deepcopy(record.payload))

    def store(self, key: str, body: bytes, status_code: int, payload: Any) -> None:
        if self._max_entries == 0:
            return
        with self._condition:
            self._records[key] = _MemoryRecord(
                fingerprint=_request_body_fingerprint(body),
                state="completed",
                status_code=int(status_code),
                payload=deepcopy(payload),
            )
            self._records.move_to_end(key)
            self._stores += 1
            self._evict_completed_over_capacity()
            self._condition.notify_all()

    def snapshot(self) -> Dict[str, str]:
        with self._condition:
            return self._metrics_snapshot(
                entry_count=len(self._records),
                max_entries=self._max_entries,
                backend="memory",
            )

    def _evict_completed_over_capacity(self) -> None:
        while len(self._records) > self._max_entries:
            completed_key = next(
                (
                    cache_key
                    for cache_key, record in self._records.items()
                    if record.state == "completed"
                ),
                None,
            )
            if completed_key is None:
                return
            del self._records[completed_key]
            self._evictions += 1


class SqliteServiceIdempotencyCache(_IdempotencyMetrics):
    _POLL_SECONDS = 0.05

    def __init__(self, *, max_entries: int, database_path: str) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        if not database_path:
            raise ValueError("database_path is required")
        super().__init__()
        self._max_entries = max_entries
        self._database_path = Path(database_path)
        self._lock = Lock()
        self._initialize_database()

    def acquire(
        self,
        key: str,
        body: bytes,
        *,
        lease_seconds: float,
        wait_timeout_seconds: float,
    ) -> IdempotencyAcquireResult:
        _validate_acquire_timeouts(lease_seconds, wait_timeout_seconds)
        if self._max_entries == 0:
            return "disabled", None, ""
        fingerprint = _request_body_fingerprint(body)
        claim_token = str(uuid4())
        lease_ns = max(1, int(lease_seconds * 1_000_000_000))
        deadline = time.monotonic() + wait_timeout_seconds
        recorded_wait = False
        while True:
            status, response, wait_seconds = self._try_acquire(
                key,
                fingerprint,
                claim_token,
                lease_ns,
            )
            if status != "waiting":
                return status, response, claim_token if status == "claimed" else ""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._lock:
                    self._wait_timeouts += 1
                return "in_progress", None, ""
            if not recorded_wait:
                with self._lock:
                    self._waits += 1
                recorded_wait = True
            time.sleep(min(self._POLL_SECONDS, remaining, max(0.001, wait_seconds)))

    def complete(
        self,
        key: str,
        body: bytes,
        claim_token: str,
        status_code: int,
        payload: Any,
    ) -> bool:
        payload_json = json.dumps(json_ready(payload), sort_keys=True)
        fingerprint = _request_body_fingerprint(body)
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    (
                        "UPDATE idempotency_cache SET state = 'completed', "
                        "status_code = ?, payload_json = ?, owner_token = '', "
                        "lease_expires_ns = 0, updated_at_ns = ? "
                        "WHERE cache_key = ? AND fingerprint = ? "
                        "AND state = 'pending' AND owner_token = ?"
                    ),
                    (
                        int(status_code),
                        payload_json,
                        time.time_ns(),
                        key,
                        fingerprint,
                        claim_token,
                    ),
                )
                if cursor.rowcount != 1:
                    return False
                self._stores += 1
                self._evict_completed_over_capacity(connection)
                return True

    def release(self, key: str, claim_token: str) -> bool:
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    (
                        "DELETE FROM idempotency_cache WHERE cache_key = ? "
                        "AND state = 'pending' AND owner_token = ?"
                    ),
                    (key, claim_token),
                )
                return cursor.rowcount == 1

    def lookup(self, key: str, body: bytes) -> Tuple[str, Optional[IdempotencyResponse]]:
        if self._max_entries == 0:
            return "disabled", None
        fingerprint = _request_body_fingerprint(body)
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    (
                        "SELECT fingerprint, state, status_code, payload_json "
                        "FROM idempotency_cache WHERE cache_key = ?"
                    ),
                    (key,),
                ).fetchone()
                if row is None:
                    self._misses += 1
                    return "miss", None
                cached_fingerprint, state, status_code, payload_json = row
                if cached_fingerprint != fingerprint:
                    self._conflicts += 1
                    return "conflict", None
                if state == "pending":
                    return "in_progress", None
                if state != "completed":
                    raise ValueError("idempotency cache record has invalid state")
                connection.execute(
                    "UPDATE idempotency_cache SET updated_at_ns = ? WHERE cache_key = ?",
                    (time.time_ns(), key),
                )
                self._hits += 1
                return "hit", (int(status_code), json.loads(str(payload_json)))

    def store(self, key: str, body: bytes, status_code: int, payload: Any) -> None:
        if self._max_entries == 0:
            return
        payload_json = json.dumps(json_ready(payload), sort_keys=True)
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    (
                        "INSERT INTO idempotency_cache "
                        "(cache_key, fingerprint, state, owner_token, lease_expires_ns, "
                        "status_code, payload_json, updated_at_ns) "
                        "VALUES (?, ?, 'completed', '', 0, ?, ?, ?) "
                        "ON CONFLICT(cache_key) DO UPDATE SET "
                        "fingerprint = excluded.fingerprint, state = 'completed', "
                        "owner_token = '', lease_expires_ns = 0, "
                        "status_code = excluded.status_code, "
                        "payload_json = excluded.payload_json, "
                        "updated_at_ns = excluded.updated_at_ns"
                    ),
                    (
                        key,
                        _request_body_fingerprint(body),
                        int(status_code),
                        payload_json,
                        time.time_ns(),
                    ),
                )
                self._stores += 1
                self._evict_completed_over_capacity(connection)

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) FROM idempotency_cache",
                ).fetchone()
                entry_count = int(row[0]) if row is not None else 0
            return self._metrics_snapshot(
                entry_count=entry_count,
                max_entries=self._max_entries,
                backend="sqlite",
            )

    def _try_acquire(
        self,
        key: str,
        fingerprint: str,
        claim_token: str,
        lease_ns: int,
    ) -> Tuple[str, Optional[IdempotencyResponse], float]:
        now_ns = time.time_ns()
        with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    (
                        "SELECT fingerprint, state, owner_token, lease_expires_ns, "
                        "status_code, payload_json FROM idempotency_cache "
                        "WHERE cache_key = ?"
                    ),
                    (key,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        (
                            "INSERT INTO idempotency_cache "
                            "(cache_key, fingerprint, state, owner_token, lease_expires_ns, "
                            "status_code, payload_json, updated_at_ns) "
                            "VALUES (?, ?, 'pending', ?, ?, 0, 'null', ?)"
                        ),
                        (key, fingerprint, claim_token, now_ns + lease_ns, now_ns),
                    )
                    self._misses += 1
                    self._claims += 1
                    self._evict_completed_over_capacity(connection)
                    return "claimed", None, 0.0
                (
                    cached_fingerprint,
                    state,
                    _owner_token,
                    lease_expires_ns,
                    status_code,
                    payload_json,
                ) = row
                if cached_fingerprint != fingerprint:
                    self._conflicts += 1
                    return "conflict", None, 0.0
                if state == "completed":
                    connection.execute(
                        "UPDATE idempotency_cache SET updated_at_ns = ? WHERE cache_key = ?",
                        (now_ns, key),
                    )
                    self._hits += 1
                    return (
                        "hit",
                        (int(status_code), json.loads(str(payload_json))),
                        0.0,
                    )
                if state != "pending":
                    raise ValueError("idempotency cache record has invalid state")
                if int(lease_expires_ns) <= now_ns:
                    connection.execute(
                        (
                            "UPDATE idempotency_cache SET owner_token = ?, "
                            "lease_expires_ns = ?, updated_at_ns = ? WHERE cache_key = ?"
                        ),
                        (claim_token, now_ns + lease_ns, now_ns, key),
                    )
                    self._claims += 1
                    self._takeovers += 1
                    return "claimed", None, 0.0
                wait_seconds = max(0.001, (int(lease_expires_ns) - now_ns) / 1_000_000_000)
                return "waiting", None, wait_seconds

    def _initialize_database(self) -> None:
        self._database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                (
                    "CREATE TABLE IF NOT EXISTS idempotency_cache ("
                    "cache_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
                    "state TEXT NOT NULL DEFAULT 'completed', "
                    "owner_token TEXT NOT NULL DEFAULT '', "
                    "lease_expires_ns INTEGER NOT NULL DEFAULT 0, "
                    "status_code INTEGER NOT NULL DEFAULT 0, "
                    "payload_json TEXT NOT NULL DEFAULT 'null', "
                    "updated_at_ns INTEGER NOT NULL)"
                )
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(idempotency_cache)")
            }
            migrations = {
                "state": (
                    "ALTER TABLE idempotency_cache ADD COLUMN state TEXT NOT NULL "
                    "DEFAULT 'completed'"
                ),
                "owner_token": (
                    "ALTER TABLE idempotency_cache ADD COLUMN owner_token TEXT NOT NULL "
                    "DEFAULT ''"
                ),
                "lease_expires_ns": (
                    "ALTER TABLE idempotency_cache ADD COLUMN lease_expires_ns "
                    "INTEGER NOT NULL DEFAULT 0"
                ),
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            connection.execute(
                (
                    "CREATE INDEX IF NOT EXISTS idx_idempotency_cache_updated_at "
                    "ON idempotency_cache(updated_at_ns, cache_key)"
                )
            )
        self._database_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._database_path), timeout=5.0)

    def _evict_completed_over_capacity(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT COUNT(*) FROM idempotency_cache").fetchone()
        entry_count = int(row[0]) if row is not None else 0
        overflow = max(0, entry_count - self._max_entries)
        if overflow == 0:
            return
        rows = connection.execute(
            (
                "SELECT cache_key FROM idempotency_cache WHERE state = 'completed' "
                "ORDER BY updated_at_ns ASC, cache_key ASC LIMIT ?"
            ),
            (overflow,),
        ).fetchall()
        for (cache_key,) in rows:
            connection.execute(
                "DELETE FROM idempotency_cache WHERE cache_key = ?",
                (cache_key,),
            )
            self._evictions += 1


def _validate_acquire_timeouts(
    lease_seconds: float,
    wait_timeout_seconds: float,
) -> None:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    if wait_timeout_seconds < 0:
        raise ValueError("wait_timeout_seconds must be non-negative")


def _request_body_fingerprint(body: bytes) -> str:
    return sha256(body).hexdigest()
