from __future__ import annotations

import json
import sqlite3
import time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from math import ceil
from os import environ
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from self_correcting_langgraph_agent.utils.json_output import json_ready

_KNOWN_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "POST"}
_UNKNOWN_METRICS_LABEL = "__unknown__"
_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass(frozen=True)
class ServiceConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    max_request_bytes: int = 65536
    max_goal_chars: int = 4096
    auth_token: str = ""
    auth_tokens: Dict[str, str] = field(default_factory=dict)
    rate_limit_per_minute: int = 0
    max_concurrent_runs: int = 4
    idempotency_cache_size: int = 0
    idempotency_cache_path: str = ""
    runtime_allowed_tools: Tuple[str, ...] = ()
    runtime_allowed_tools_by_subject: Dict[str, Tuple[str, ...]] = field(
        default_factory=dict
    )
    runtime_max_iterations: int = 10
    runtime_pending_approval_stale_seconds: int = 3600
    allow_full_trace_response: bool = False
    protect_diagnostics: bool = False
    trust_forwarded_for: bool = False
    trace_dir: str = ""
    run_timeout_seconds: float = 30.0
    request_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ServiceConfig":
        source = env if env is not None else environ
        return cls(
            host=source.get("SELF_CORRECTING_SERVICE_HOST", cls.host),
            port=_env_int(source, "SELF_CORRECTING_SERVICE_PORT", cls.port),
            max_request_bytes=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES",
                cls.max_request_bytes,
            ),
            max_goal_chars=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS",
                cls.max_goal_chars,
            ),
            auth_token=source.get("SELF_CORRECTING_SERVICE_AUTH_TOKEN", cls.auth_token),
            auth_tokens=_env_auth_tokens(
                source,
                "SELF_CORRECTING_SERVICE_AUTH_TOKENS",
            ),
            rate_limit_per_minute=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE",
                cls.rate_limit_per_minute,
            ),
            max_concurrent_runs=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS",
                cls.max_concurrent_runs,
            ),
            idempotency_cache_size=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE",
                cls.idempotency_cache_size,
            ),
            idempotency_cache_path=source.get(
                "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH",
                cls.idempotency_cache_path,
            ),
            runtime_allowed_tools=_env_csv_tuple(
                source,
                "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS",
            ),
            runtime_allowed_tools_by_subject=_env_subject_csv_tuple_map(
                source,
                "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT",
            ),
            runtime_max_iterations=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS",
                cls.runtime_max_iterations,
            ),
            runtime_pending_approval_stale_seconds=_env_int(
                source,
                "SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS",
                cls.runtime_pending_approval_stale_seconds,
            ),
            allow_full_trace_response=_env_bool(
                source,
                "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE",
                cls.allow_full_trace_response,
            ),
            protect_diagnostics=_env_bool(
                source,
                "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS",
                cls.protect_diagnostics,
            ),
            trust_forwarded_for=_env_bool(
                source,
                "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR",
                cls.trust_forwarded_for,
            ),
            trace_dir=source.get("SELF_CORRECTING_SERVICE_TRACE_DIR", cls.trace_dir),
            run_timeout_seconds=_env_float(
                source,
                "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS",
                cls.run_timeout_seconds,
            ),
            request_timeout_seconds=_env_float(
                source,
                "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS",
                cls.request_timeout_seconds,
            ),
        )

    def __post_init__(self) -> None:
        if self.port < 1 or self.port > 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.max_request_bytes < 1:
            raise ValueError("max_request_bytes must be at least 1")
        if self.max_goal_chars < 1:
            raise ValueError("max_goal_chars must be at least 1")
        if self.rate_limit_per_minute < 0:
            raise ValueError("rate_limit_per_minute must be non-negative")
        if self.max_concurrent_runs < 0:
            raise ValueError("max_concurrent_runs must be non-negative")
        if self.idempotency_cache_size < 0:
            raise ValueError("idempotency_cache_size must be non-negative")
        if self.idempotency_cache_path and self.idempotency_cache_size == 0:
            raise ValueError("idempotency_cache_path requires idempotency_cache_size")
        _validate_runtime_allowed_tools(self.runtime_allowed_tools)
        _validate_runtime_allowed_tools_by_subject(
            self.runtime_allowed_tools_by_subject
        )
        if self.runtime_max_iterations < 1:
            raise ValueError("runtime_max_iterations must be at least 1")
        if self.runtime_pending_approval_stale_seconds < 0:
            raise ValueError(
                "runtime_pending_approval_stale_seconds must be non-negative"
            )
        if self.protect_diagnostics and not self.auth_required:
            raise ValueError("protect_diagnostics requires auth_token")
        _validate_auth_tokens(self.auth_tokens)
        if self.run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds must be positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")

    @property
    def auth_required(self) -> bool:
        return bool(self.auth_token or self.auth_tokens)

    def runtime_allowed_tools_for_subject(
        self,
        auth_subject: str,
    ) -> Optional[Tuple[str, ...]]:
        if auth_subject and auth_subject in self.runtime_allowed_tools_by_subject:
            return self.runtime_allowed_tools_by_subject[auth_subject]
        if self.runtime_allowed_tools:
            return self.runtime_allowed_tools
        return None


class ServiceMetrics:
    def __init__(self, *, started_at: Optional[float] = None) -> None:
        self._lock = Lock()
        self._started_at = time.monotonic() if started_at is None else started_at
        self._requests_total = 0
        self._total_duration_seconds = 0.0
        self._max_duration_seconds = 0.0
        self._request_duration_buckets: Dict[str, int] = _empty_duration_buckets()
        self._responses_by_status: Dict[str, int] = {}
        self._requests_by_method: Dict[str, int] = {}
        self._requests_by_path: Dict[str, int] = {}
        self._requests_by_auth_subject: Dict[str, int] = {}
        self._error_responses_by_code: Dict[str, int] = {}
        self._agent_runs_total = 0
        self._agent_run_duration_seconds = 0.0
        self._max_agent_run_duration_seconds = 0.0
        self._agent_run_duration_buckets: Dict[str, int] = _empty_duration_buckets()
        self._agent_runs_by_status: Dict[str, int] = {}
        self._runtime_runs_total = 0
        self._runtime_runs_by_status: Dict[str, int] = {}
        self._runtime_runs_by_auth_subject: Dict[str, int] = {}
        self._runtime_runs_by_auth_subject_status: Dict[str, int] = {}
        self._runtime_resumes_by_auth_subject: Dict[str, int] = {}
        self._runtime_failed_observations_total = 0
        self._runtime_observation_errors_by_code: Dict[str, int] = {}
        self._runtime_approval_required_total = 0
        self._runtime_failed_budget_exhaustions_total = 0
        self._runtime_run_duration_seconds = 0.0
        self._max_runtime_run_duration_seconds = 0.0
        self._runtime_run_duration_buckets: Dict[str, int] = _empty_duration_buckets()

    def record(
        self,
        *,
        path: str,
        status_code: int,
        method: str = "UNKNOWN",
        duration_seconds: float = 0.0,
        error_code: str = "",
        auth_subject: str = "",
    ) -> None:
        with self._lock:
            self._requests_total += 1
            self._total_duration_seconds += duration_seconds
            self._max_duration_seconds = max(self._max_duration_seconds, duration_seconds)
            for bucket, label in _duration_bucket_labels():
                if duration_seconds <= bucket:
                    self._request_duration_buckets[label] += 1
            self._request_duration_buckets["+Inf"] += 1
            status_key = str(status_code)
            method_key = _method_metrics_label(method)
            self._responses_by_status[status_key] = self._responses_by_status.get(status_key, 0) + 1
            self._requests_by_method[method_key] = self._requests_by_method.get(method_key, 0) + 1
            self._requests_by_path[path] = self._requests_by_path.get(path, 0) + 1
            if auth_subject:
                self._requests_by_auth_subject[auth_subject] = (
                    self._requests_by_auth_subject.get(auth_subject, 0) + 1
                )
            if error_code:
                self._error_responses_by_code[error_code] = (
                    self._error_responses_by_code.get(error_code, 0) + 1
                )

    def record_agent_run(self, *, status: str, duration_seconds: float = 0.0) -> None:
        with self._lock:
            self._agent_runs_total += 1
            self._agent_run_duration_seconds += duration_seconds
            self._max_agent_run_duration_seconds = max(
                self._max_agent_run_duration_seconds,
                duration_seconds,
            )
            for bucket, label in _duration_bucket_labels():
                if duration_seconds <= bucket:
                    self._agent_run_duration_buckets[label] += 1
            self._agent_run_duration_buckets["+Inf"] += 1
            self._agent_runs_by_status[status] = self._agent_runs_by_status.get(status, 0) + 1

    def record_runtime_run(
        self,
        *,
        status: str,
        failed_observation_count: int = 0,
        approval_required_count: int = 0,
        budget_exhausted: bool = False,
        duration_seconds: float = 0.0,
        error_code_counts: Optional[Mapping[str, int]] = None,
        auth_subject: str = "",
        resumed_by_auth_subject: str = "",
    ) -> None:
        with self._lock:
            self._runtime_runs_total += 1
            self._runtime_runs_by_status[status] = (
                self._runtime_runs_by_status.get(status, 0) + 1
            )
            if auth_subject:
                self._runtime_runs_by_auth_subject[auth_subject] = (
                    self._runtime_runs_by_auth_subject.get(auth_subject, 0) + 1
                )
                subject_status_key = _combined_metrics_key(auth_subject, status)
                self._runtime_runs_by_auth_subject_status[subject_status_key] = (
                    self._runtime_runs_by_auth_subject_status.get(subject_status_key, 0)
                    + 1
                )
            if resumed_by_auth_subject:
                self._runtime_resumes_by_auth_subject[resumed_by_auth_subject] = (
                    self._runtime_resumes_by_auth_subject.get(
                        resumed_by_auth_subject,
                        0,
                    )
                    + 1
                )
            self._runtime_run_duration_seconds += duration_seconds
            self._max_runtime_run_duration_seconds = max(
                self._max_runtime_run_duration_seconds,
                duration_seconds,
            )
            for bucket, label in _duration_bucket_labels():
                if duration_seconds <= bucket:
                    self._runtime_run_duration_buckets[label] += 1
            self._runtime_run_duration_buckets["+Inf"] += 1
            self._runtime_failed_observations_total += max(0, failed_observation_count)
            for error_code, count in (error_code_counts or {}).items():
                normalized_error_code = str(error_code)
                if not normalized_error_code:
                    continue
                self._runtime_observation_errors_by_code[normalized_error_code] = (
                    self._runtime_observation_errors_by_code.get(
                        normalized_error_code,
                        0,
                    )
                    + max(0, int(count))
                )
            self._runtime_approval_required_total += max(0, approval_required_count)
            if budget_exhausted:
                self._runtime_failed_budget_exhaustions_total += 1

    def snapshot(self, *, now: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            current_time = time.monotonic() if now is None else now
            average_duration = (
                self._total_duration_seconds / self._requests_total
                if self._requests_total
                else 0.0
            )
            average_agent_run_duration = (
                self._agent_run_duration_seconds / self._agent_runs_total
                if self._agent_runs_total
                else 0.0
            )
            average_runtime_run_duration = (
                self._runtime_run_duration_seconds / self._runtime_runs_total
                if self._runtime_runs_total
                else 0.0
            )
            return {
                "requests_total": str(self._requests_total),
                "responses_by_status": _string_counts(self._responses_by_status),
                "requests_by_method": _string_counts(self._requests_by_method),
                "requests_by_path": _string_counts(self._requests_by_path),
                "requests_by_auth_subject": _string_counts(
                    self._requests_by_auth_subject
                ),
                "error_responses_by_code": _string_counts(self._error_responses_by_code),
                "request_duration_seconds_bucket": _string_counts(
                    self._request_duration_buckets
                ),
                "request_duration_seconds_count": str(self._requests_total),
                "request_duration_seconds_sum": f"{self._total_duration_seconds:.4f}",
                "average_duration_seconds": f"{average_duration:.4f}",
                "max_duration_seconds": f"{self._max_duration_seconds:.4f}",
                "agent_runs_total": str(self._agent_runs_total),
                "agent_runs_by_status": _string_counts(self._agent_runs_by_status),
                "agent_run_duration_seconds_bucket": _string_counts(
                    self._agent_run_duration_buckets
                ),
                "agent_run_duration_seconds_count": str(self._agent_runs_total),
                "agent_run_duration_seconds_sum": f"{self._agent_run_duration_seconds:.4f}",
                "average_agent_run_duration_seconds": f"{average_agent_run_duration:.4f}",
                "max_agent_run_duration_seconds": f"{self._max_agent_run_duration_seconds:.4f}",
                "runtime_runs_total": str(self._runtime_runs_total),
                "runtime_runs_by_status": _string_counts(self._runtime_runs_by_status),
                "runtime_runs_by_auth_subject": _string_counts(
                    self._runtime_runs_by_auth_subject
                ),
                "runtime_runs_by_auth_subject_status": _string_counts(
                    self._runtime_runs_by_auth_subject_status
                ),
                "runtime_resumes_by_auth_subject": _string_counts(
                    self._runtime_resumes_by_auth_subject
                ),
                "runtime_failed_observations_total": str(
                    self._runtime_failed_observations_total
                ),
                "runtime_observation_errors_by_code": _string_counts(
                    self._runtime_observation_errors_by_code
                ),
                "runtime_approval_required_total": str(
                    self._runtime_approval_required_total
                ),
                "runtime_failed_budget_exhaustions_total": str(
                    self._runtime_failed_budget_exhaustions_total
                ),
                "runtime_run_duration_seconds_bucket": _string_counts(
                    self._runtime_run_duration_buckets
                ),
                "runtime_run_duration_seconds_count": str(self._runtime_runs_total),
                "runtime_run_duration_seconds_sum": (
                    f"{self._runtime_run_duration_seconds:.4f}"
                ),
                "average_runtime_run_duration_seconds": (
                    f"{average_runtime_run_duration:.4f}"
                ),
                "max_runtime_run_duration_seconds": (
                    f"{self._max_runtime_run_duration_seconds:.4f}"
                ),
                "uptime_seconds": f"{max(0.0, current_time - self._started_at):.4f}",
            }


class ServiceIdempotencyCache:
    def __init__(self, *, max_entries: int) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        self._max_entries = max_entries
        self._lock = Lock()
        self._records: "OrderedDict[str, Tuple[str, int, Any]]" = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._conflicts = 0
        self._stores = 0
        self._evictions = 0

    def lookup(self, key: str, body: bytes) -> Tuple[str, Optional[Tuple[int, Any]]]:
        if self._max_entries == 0:
            return "disabled", None
        fingerprint = _request_body_fingerprint(body)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                self._misses += 1
                return "miss", None
            cached_fingerprint, status_code, payload = record
            self._records.move_to_end(key)
            if cached_fingerprint != fingerprint:
                self._conflicts += 1
                return "conflict", None
            self._hits += 1
            return "hit", (status_code, deepcopy(payload))

    def store(self, key: str, body: bytes, status_code: int, payload: Any) -> None:
        if self._max_entries == 0:
            return
        with self._lock:
            self._records[key] = (_request_body_fingerprint(body), status_code, deepcopy(payload))
            self._records.move_to_end(key)
            self._stores += 1
            while len(self._records) > self._max_entries:
                self._records.popitem(last=False)
                self._evictions += 1

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {
                "idempotency_cache_entries": str(len(self._records)),
                "idempotency_cache_size": str(self._max_entries),
                "idempotency_cache_hits": str(self._hits),
                "idempotency_cache_misses": str(self._misses),
                "idempotency_cache_conflicts": str(self._conflicts),
                "idempotency_cache_stores": str(self._stores),
                "idempotency_cache_evictions": str(self._evictions),
            }


class SqliteServiceIdempotencyCache:
    def __init__(self, *, max_entries: int, database_path: str) -> None:
        if max_entries < 0:
            raise ValueError("max_entries must be non-negative")
        if not database_path:
            raise ValueError("database_path is required")
        self._max_entries = max_entries
        self._database_path = Path(database_path)
        self._lock = Lock()
        self._hits = 0
        self._misses = 0
        self._conflicts = 0
        self._stores = 0
        self._evictions = 0
        self._initialize_database()

    def lookup(self, key: str, body: bytes) -> Tuple[str, Optional[Tuple[int, Any]]]:
        if self._max_entries == 0:
            return "disabled", None
        fingerprint = _request_body_fingerprint(body)
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    (
                        "SELECT fingerprint, status_code, payload_json "
                        "FROM idempotency_cache WHERE cache_key = ?"
                    ),
                    (key,),
                ).fetchone()
                if row is None:
                    self._misses += 1
                    return "miss", None
                cached_fingerprint, status_code, payload_json = row
                if cached_fingerprint != fingerprint:
                    self._conflicts += 1
                    return "conflict", None
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
                        "(cache_key, fingerprint, status_code, payload_json, updated_at_ns) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(cache_key) DO UPDATE SET "
                        "fingerprint = excluded.fingerprint, "
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
                self._evict_over_capacity(connection)

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) FROM idempotency_cache",
                ).fetchone()
                entry_count = int(row[0]) if row is not None else 0
            return {
                "idempotency_cache_backend": "sqlite",
                "idempotency_cache_entries": str(entry_count),
                "idempotency_cache_size": str(self._max_entries),
                "idempotency_cache_hits": str(self._hits),
                "idempotency_cache_misses": str(self._misses),
                "idempotency_cache_conflicts": str(self._conflicts),
                "idempotency_cache_stores": str(self._stores),
                "idempotency_cache_evictions": str(self._evictions),
            }

    def _initialize_database(self) -> None:
        self._database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute(
                (
                    "CREATE TABLE IF NOT EXISTS idempotency_cache ("
                    "cache_key TEXT PRIMARY KEY, "
                    "fingerprint TEXT NOT NULL, "
                    "status_code INTEGER NOT NULL, "
                    "payload_json TEXT NOT NULL, "
                    "updated_at_ns INTEGER NOT NULL"
                    ")"
                )
            )
            connection.execute(
                (
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_idempotency_cache_updated_at "
                    "ON idempotency_cache(updated_at_ns, cache_key)"
                )
            )
        self._database_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._database_path), timeout=5.0)

    def _evict_over_capacity(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT COUNT(*) FROM idempotency_cache").fetchone()
        entry_count = int(row[0]) if row is not None else 0
        overflow = max(0, entry_count - self._max_entries)
        if overflow == 0:
            return
        rows = connection.execute(
            (
                "SELECT cache_key FROM idempotency_cache "
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


class ServiceRateLimiter:
    def __init__(self, *, limit_per_minute: int) -> None:
        if limit_per_minute < 0:
            raise ValueError("limit_per_minute must be non-negative")
        self._limit_per_minute = limit_per_minute
        self._lock = Lock()
        self._windows: Dict[str, Tuple[float, int]] = {}

    def allow(self, key: str, *, now: Optional[float] = None) -> bool:
        if self._limit_per_minute == 0:
            return True
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._prune_expired_windows(current_time)
            window_start, count = self._windows.get(key, (current_time, 0))
            if current_time - window_start >= 60:
                self._windows[key] = (current_time, 1)
                return True
            if count >= self._limit_per_minute:
                return False
            self._windows[key] = (window_start, count + 1)
            return True

    def snapshot(self, *, now: Optional[float] = None) -> Dict[str, str]:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._prune_expired_windows(current_time)
            return {
                "active_rate_limit_windows": str(len(self._windows)),
                "rate_limit_per_minute": str(self._limit_per_minute),
            }

    def retry_after_seconds(self, key: str, *, now: Optional[float] = None) -> int:
        if self._limit_per_minute == 0:
            return 0
        current_time = time.monotonic() if now is None else now
        with self._lock:
            self._prune_expired_windows(current_time)
            window = self._windows.get(key)
            if window is None:
                return 0
            window_start, _count = window
            remaining = 60 - (current_time - window_start)
            return max(1, int(ceil(remaining)))

    def _prune_expired_windows(self, current_time: float) -> None:
        expired_keys = [
            key
            for key, (window_start, _count) in self._windows.items()
            if current_time - window_start >= 60
        ]
        for key in expired_keys:
            del self._windows[key]


class ServiceConcurrencyLimiter:
    def __init__(self, *, max_concurrent_runs: int) -> None:
        if max_concurrent_runs < 0:
            raise ValueError("max_concurrent_runs must be non-negative")
        self._lock = Lock()
        self._max_concurrent_runs = max_concurrent_runs
        self._active_runs = 0
        self._disabled = max_concurrent_runs == 0
        self._semaphore = BoundedSemaphore(max_concurrent_runs or 1)

    def try_acquire(self) -> Optional[Callable[[], None]]:
        if self._disabled:
            return _noop_release
        if not self._semaphore.acquire(blocking=False):
            return None
        with self._lock:
            self._active_runs += 1

        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            with self._lock:
                self._active_runs -= 1
            self._semaphore.release()

        return release

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {
                "active_concurrent_runs": str(self._active_runs),
                "max_concurrent_runs": str(self._max_concurrent_runs),
            }


def access_log_record(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
    request_id: str,
    remote_addr: str,
    error_code: str = "",
    run_id: str = "",
    trace_path: str = "",
    idempotency_key_present: Optional[bool] = None,
    request_body_bytes: Optional[int] = None,
    auth_subject: str = "",
    runtime_owner_auth_subject: str = "",
    resumed_by_auth_subject: str = "",
) -> Dict[str, Any]:
    record = {
        "event": "http_request",
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_seconds": f"{duration_seconds:.4f}",
        "request_id": request_id,
        "remote_addr": remote_addr,
    }
    if error_code:
        record["error_code"] = error_code
    if run_id:
        record["run_id"] = run_id
    if trace_path:
        record["trace_path"] = trace_path
    if idempotency_key_present is not None:
        record["idempotency_key_present"] = idempotency_key_present
    if request_body_bytes is not None:
        record["request_body_bytes"] = request_body_bytes
    if auth_subject:
        record["auth_subject"] = auth_subject
    if runtime_owner_auth_subject:
        record["runtime_owner_auth_subject"] = runtime_owner_auth_subject
    if resumed_by_auth_subject:
        record["resumed_by_auth_subject"] = resumed_by_auth_subject
    return record


def access_log_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "event",
            "method",
            "path",
            "status_code",
            "duration_seconds",
            "request_id",
            "remote_addr",
        ],
        "properties": {
            "event": {"type": "string", "const": "http_request"},
            "method": {"type": "string"},
            "path": {"type": "string"},
            "status_code": {"type": "integer"},
            "duration_seconds": {"type": "string", "pattern": r"^\d+\.\d{4}$"},
            "request_id": {"type": "string"},
            "remote_addr": {"type": "string"},
            "error_code": {"type": "string"},
            "run_id": {"type": "string"},
            "trace_path": {"type": "string"},
            "idempotency_key_present": {"type": "boolean"},
            "request_body_bytes": {"type": "integer"},
            "auth_subject": {"type": "string"},
            "runtime_owner_auth_subject": {"type": "string"},
            "resumed_by_auth_subject": {"type": "string"},
        },
        "additionalProperties": False,
    }


def prometheus_metrics_text(snapshot: Mapping[str, Any]) -> str:
    lines = [
        "# HELP self_correcting_agent_requests_total Total HTTP requests handled.",
        "# TYPE self_correcting_agent_requests_total counter",
        f"self_correcting_agent_requests_total {snapshot.get('requests_total', '0')}",
        "# HELP self_correcting_agent_responses_total HTTP responses by status code.",
        "# TYPE self_correcting_agent_responses_total counter",
    ]
    for status, count in _mapping_value(snapshot, "responses_by_status").items():
        lines.append(
            f'self_correcting_agent_responses_total{{status="{_prometheus_label(status)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_requests_by_method_total HTTP requests by method.",
            "# TYPE self_correcting_agent_requests_by_method_total counter",
        ]
    )
    for method, count in _mapping_value(snapshot, "requests_by_method").items():
        lines.append(
            "self_correcting_agent_requests_by_method_total"
            f'{{method="{_prometheus_label(method)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_requests_by_path_total HTTP requests by route.",
            "# TYPE self_correcting_agent_requests_by_path_total counter",
        ]
    )
    for path, count in _mapping_value(snapshot, "requests_by_path").items():
        lines.append(
            f'self_correcting_agent_requests_by_path_total{{path="{_prometheus_label(path)}"}} '
            f"{count}"
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_requests_by_auth_subject_total "
            "HTTP requests by authenticated internal subject.",
            "# TYPE self_correcting_agent_requests_by_auth_subject_total counter",
        ]
    )
    for auth_subject, count in _mapping_value(snapshot, "requests_by_auth_subject").items():
        lines.append(
            "self_correcting_agent_requests_by_auth_subject_total"
            f'{{auth_subject="{_prometheus_label(auth_subject)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_error_responses_total Errors by stable code.",
            "# TYPE self_correcting_agent_error_responses_total counter",
        ]
    )
    for error_code, count in _mapping_value(snapshot, "error_responses_by_code").items():
        lines.append(
            "self_correcting_agent_error_responses_total"
            f'{{error_code="{_prometheus_label(error_code)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_request_duration_seconds "
            "HTTP request duration in seconds.",
            "# TYPE self_correcting_agent_request_duration_seconds histogram",
        ]
    )
    for bucket, count in _mapping_value(snapshot, "request_duration_seconds_bucket").items():
        lines.append(
            "self_correcting_agent_request_duration_seconds_bucket"
            f'{{le="{_prometheus_label(bucket)}"}} {count}'
        )
    lines.append(
        "self_correcting_agent_request_duration_seconds_count "
        f"{snapshot.get('request_duration_seconds_count', '0')}"
    )
    lines.append(
        "self_correcting_agent_request_duration_seconds_sum "
        f"{snapshot.get('request_duration_seconds_sum', '0.0000')}"
    )
    lines.extend(
        [
            "# HELP self_correcting_agent_runs_total Total agent runs handled by /run.",
            "# TYPE self_correcting_agent_runs_total counter",
            f"self_correcting_agent_runs_total {snapshot.get('agent_runs_total', '0')}",
            "# HELP self_correcting_agent_run_status_total Agent runs by final status.",
            "# TYPE self_correcting_agent_run_status_total counter",
        ]
    )
    for status, count in _mapping_value(snapshot, "agent_runs_by_status").items():
        lines.append(
            f'self_correcting_agent_run_status_total{{status="{_prometheus_label(status)}"}} '
            f"{count}"
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_runs_total "
            "Total Codex-style runtime runs handled.",
            "# TYPE self_correcting_agent_runtime_runs_total counter",
            f"self_correcting_agent_runtime_runs_total "
            f"{snapshot.get('runtime_runs_total', '0')}",
            "# HELP self_correcting_agent_runtime_run_status_total "
            "Codex-style runtime runs by final status.",
            "# TYPE self_correcting_agent_runtime_run_status_total counter",
        ]
    )
    for status, count in _mapping_value(snapshot, "runtime_runs_by_status").items():
        lines.append(
            "self_correcting_agent_runtime_run_status_total"
            f'{{status="{_prometheus_label(status)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_runs_by_auth_subject_total "
            "Codex-style runtime runs by authenticated internal subject.",
            "# TYPE self_correcting_agent_runtime_runs_by_auth_subject_total counter",
        ]
    )
    for auth_subject, count in _mapping_value(
        snapshot,
        "runtime_runs_by_auth_subject",
    ).items():
        lines.append(
            "self_correcting_agent_runtime_runs_by_auth_subject_total"
            f'{{auth_subject="{_prometheus_label(auth_subject)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_run_status_by_auth_subject_total "
            "Codex-style runtime runs by authenticated internal subject and final status.",
            "# TYPE self_correcting_agent_runtime_run_status_by_auth_subject_total counter",
        ]
    )
    for subject_status, count in _mapping_value(
        snapshot,
        "runtime_runs_by_auth_subject_status",
    ).items():
        auth_subject, status = _split_combined_metrics_key(subject_status)
        lines.append(
            "self_correcting_agent_runtime_run_status_by_auth_subject_total"
            f'{{auth_subject="{_prometheus_label(auth_subject)}",'
            f'status="{_prometheus_label(status)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_resumes_by_auth_subject_total "
            "Codex-style runtime resumes by authenticated resume subject.",
            "# TYPE self_correcting_agent_runtime_resumes_by_auth_subject_total counter",
        ]
    )
    for auth_subject, count in _mapping_value(
        snapshot,
        "runtime_resumes_by_auth_subject",
    ).items():
        lines.append(
            "self_correcting_agent_runtime_resumes_by_auth_subject_total"
            f'{{auth_subject="{_prometheus_label(auth_subject)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_failed_observations_total "
            "Failed observations produced by Codex-style runtime runs.",
            "# TYPE self_correcting_agent_runtime_failed_observations_total counter",
            "self_correcting_agent_runtime_failed_observations_total "
            f"{snapshot.get('runtime_failed_observations_total', '0')}",
            "# HELP self_correcting_agent_runtime_observation_errors_total "
            "Runtime observation failures by stable error code.",
            "# TYPE self_correcting_agent_runtime_observation_errors_total counter",
        ]
    )
    for error_code, count in _mapping_value(
        snapshot,
        "runtime_observation_errors_by_code",
    ).items():
        lines.append(
            "self_correcting_agent_runtime_observation_errors_total"
            f'{{error_code="{_prometheus_label(error_code)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_approval_required_total "
            "Approval-required observations produced by Codex-style runtime runs.",
            "# TYPE self_correcting_agent_runtime_approval_required_total counter",
            "self_correcting_agent_runtime_approval_required_total "
            f"{snapshot.get('runtime_approval_required_total', '0')}",
            "# HELP self_correcting_agent_runtime_final_answer_guardrails_total "
            "Final answers corrected by runtime guardrails.",
            "# TYPE self_correcting_agent_runtime_final_answer_guardrails_total counter",
            "self_correcting_agent_runtime_final_answer_guardrails_total "
            f"{snapshot.get('runtime_final_answer_guardrails_total', '0')}",
            "# HELP self_correcting_agent_runtime_final_answer_guardrails_by_reason_total "
            "Final answer guardrail corrections by stable reason.",
            "# TYPE self_correcting_agent_runtime_final_answer_guardrails_by_reason_total counter",
        ]
    )
    for reason, count in _mapping_value(
        snapshot,
        "runtime_final_answer_guardrails_by_reason",
    ).items():
        lines.append(
            "self_correcting_agent_runtime_final_answer_guardrails_by_reason_total"
            f'{{reason="{_prometheus_label(reason)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP self_correcting_agent_runtime_pending_approvals_current "
            "Current persisted pending approval queue size.",
            "# TYPE self_correcting_agent_runtime_pending_approvals_current gauge",
            "self_correcting_agent_runtime_pending_approvals_current "
            f"{snapshot.get('runtime_pending_approvals_current', '0')}",
            "# HELP self_correcting_agent_runtime_stale_pending_approvals_current "
            "Current pending approvals older than the configured stale threshold.",
            "# TYPE self_correcting_agent_runtime_stale_pending_approvals_current gauge",
            "self_correcting_agent_runtime_stale_pending_approvals_current "
            f"{snapshot.get('runtime_stale_pending_approvals_current', '0')}",
            "# HELP self_correcting_agent_runtime_max_pending_approval_age_seconds "
            "Maximum current pending approval age in seconds.",
            "# TYPE self_correcting_agent_runtime_max_pending_approval_age_seconds gauge",
            "self_correcting_agent_runtime_max_pending_approval_age_seconds "
            f"{snapshot.get('runtime_max_pending_approval_age_seconds', '0')}",
            "# HELP self_correcting_agent_runtime_pending_approval_stale_seconds "
            "Configured stale pending approval age threshold in seconds.",
            "# TYPE self_correcting_agent_runtime_pending_approval_stale_seconds gauge",
            "self_correcting_agent_runtime_pending_approval_stale_seconds "
            f"{snapshot.get('runtime_pending_approval_stale_seconds', '3600')}",
            "# HELP self_correcting_agent_runtime_failed_budget_exhaustions_total "
            "Failed Codex-style runtime runs that exhausted their iteration budget.",
            "# TYPE self_correcting_agent_runtime_failed_budget_exhaustions_total counter",
            "self_correcting_agent_runtime_failed_budget_exhaustions_total "
            f"{snapshot.get('runtime_failed_budget_exhaustions_total', '0')}",
            "# HELP self_correcting_agent_runtime_run_duration_seconds "
            "Codex-style runtime run duration in seconds.",
            "# TYPE self_correcting_agent_runtime_run_duration_seconds histogram",
        ]
    )
    for bucket, count in _mapping_value(
        snapshot,
        "runtime_run_duration_seconds_bucket",
    ).items():
        lines.append(
            "self_correcting_agent_runtime_run_duration_seconds_bucket"
            f'{{le="{_prometheus_label(bucket)}"}} {count}'
        )
    lines.extend(
        [
            "self_correcting_agent_runtime_run_duration_seconds_count "
            f"{snapshot.get('runtime_run_duration_seconds_count', '0')}",
            "self_correcting_agent_runtime_run_duration_seconds_sum "
            f"{snapshot.get('runtime_run_duration_seconds_sum', '0.0000')}",
        ]
    )
    lines.extend(
        [
            "# HELP self_correcting_agent_agent_run_duration_seconds "
            "Agent run duration in seconds.",
            "# TYPE self_correcting_agent_agent_run_duration_seconds histogram",
        ]
    )
    for bucket, count in _mapping_value(snapshot, "agent_run_duration_seconds_bucket").items():
        lines.append(
            "self_correcting_agent_agent_run_duration_seconds_bucket"
            f'{{le="{_prometheus_label(bucket)}"}} {count}'
        )
    lines.append(
        "self_correcting_agent_agent_run_duration_seconds_count "
        f"{snapshot.get('agent_run_duration_seconds_count', '0')}"
    )
    lines.append(
        "self_correcting_agent_agent_run_duration_seconds_sum "
        f"{snapshot.get('agent_run_duration_seconds_sum', '0.0000')}"
    )
    if "service_version" in snapshot:
        build_labels = {
            "auth_required": snapshot.get("auth_required", "false"),
            "auth_subject_count": snapshot.get("auth_subject_count", "0"),
            "allow_full_trace_response": snapshot.get("allow_full_trace_response", "false"),
            "bind_host": snapshot.get("bind_host", ""),
            "bind_port": snapshot.get("bind_port", "0"),
            "idempotency_cache_backend": snapshot.get(
                "idempotency_cache_backend",
                "memory",
            ),
            "idempotency_cache_path_configured": snapshot.get(
                "idempotency_cache_path_configured",
                "false",
            ),
            "idempotency_cache_size": snapshot.get("idempotency_cache_size", "0"),
            "runtime_allowed_tools": snapshot.get("runtime_allowed_tools", "default"),
            "runtime_allowed_tools_by_subject_count": snapshot.get(
                "runtime_allowed_tools_by_subject_count",
                "0",
            ),
            "runtime_max_iterations": snapshot.get("runtime_max_iterations", "0"),
            "max_concurrent_runs": snapshot.get("max_concurrent_runs", "0"),
            "max_goal_chars": snapshot.get("max_goal_chars", "0"),
            "max_request_bytes": snapshot.get("max_request_bytes", "0"),
            "protect_diagnostics": snapshot.get("protect_diagnostics", "false"),
            "rate_limit_per_minute": snapshot.get("rate_limit_per_minute", "0"),
            "request_timeout_seconds": snapshot.get("request_timeout_seconds", "0"),
            "run_timeout_seconds": snapshot.get("run_timeout_seconds", "0"),
            "trace_persistence": snapshot.get("trace_persistence", "disabled"),
            "trust_forwarded_for": snapshot.get("trust_forwarded_for", "false"),
            "version": snapshot["service_version"],
            "trace_directory_permissions": snapshot.get(
                "trace_directory_permissions",
                "",
            ),
            "trace_file_permissions": snapshot.get("trace_file_permissions", ""),
            "trace_probe_file_permissions": snapshot.get(
                "trace_probe_file_permissions",
                "",
            ),
            "llm_provider": snapshot.get("llm_provider", "unconfigured"),
            "llm_base_url": snapshot.get("llm_base_url", ""),
            "llm_model": snapshot.get("llm_model", ""),
            "llm_api_key_configured": snapshot.get("llm_api_key_configured", "false"),
            "llm_timeout_seconds": snapshot.get("llm_timeout_seconds", "0"),
            "llm_max_retries": snapshot.get("llm_max_retries", "0"),
            "llm_retry_backoff_seconds": snapshot.get(
                "llm_retry_backoff_seconds",
                "0",
            ),
            "security_response_headers": snapshot.get("security_response_headers", "unknown"),
            "cache_control_header": snapshot.get("cache_control_header", ""),
            "content_security_policy_header": snapshot.get(
                "content_security_policy_header",
                "",
            ),
            "referrer_policy_header": snapshot.get("referrer_policy_header", ""),
            "x_frame_options_header": snapshot.get("x_frame_options_header", ""),
            "x_content_type_options_header": snapshot.get(
                "x_content_type_options_header",
                "",
            ),
        }
        build_label_text = ",".join(
            f'{name}="{_prometheus_label(value)}"'
            for name, value in build_labels.items()
        )
        lines.extend(
            [
                "# HELP self_correcting_agent_build_info Service build and runtime controls.",
                "# TYPE self_correcting_agent_build_info gauge",
                f"self_correcting_agent_build_info{{{build_label_text}}} 1",
            ]
        )
    scalar_metrics = [
        (
            "average_duration_seconds",
            "gauge",
            "Average HTTP request duration in seconds.",
        ),
        ("max_duration_seconds", "gauge", "Maximum observed HTTP request duration in seconds."),
        (
            "average_agent_run_duration_seconds",
            "gauge",
            "Average agent run duration in seconds.",
        ),
        (
            "max_agent_run_duration_seconds",
            "gauge",
            "Maximum observed agent run duration in seconds.",
        ),
        ("uptime_seconds", "gauge", "Service process uptime in seconds."),
        ("active_concurrent_runs", "gauge", "Currently active agent runs."),
        ("max_concurrent_runs", "gauge", "Configured maximum concurrent agent runs."),
        ("max_goal_chars", "gauge", "Configured maximum accepted goal length in characters."),
        (
            "runtime_max_iterations",
            "gauge",
            "Configured maximum Codex-style runtime planner iterations per request.",
        ),
        ("max_request_bytes", "gauge", "Configured maximum accepted request body size in bytes."),
        ("active_rate_limit_windows", "gauge", "Currently tracked rate limit windows."),
        ("rate_limit_per_minute", "gauge", "Configured per-client run rate limit per minute."),
        ("idempotency_cache_entries", "gauge", "Current idempotency cache entry count."),
        ("idempotency_cache_size", "gauge", "Configured idempotency cache entry limit."),
        ("idempotency_cache_hits", "counter", "Total idempotency cache hits."),
        ("idempotency_cache_misses", "counter", "Total idempotency cache misses."),
        ("idempotency_cache_conflicts", "counter", "Total idempotency key conflicts."),
        ("idempotency_cache_stores", "counter", "Total idempotency cache stores."),
        ("idempotency_cache_evictions", "counter", "Total idempotency cache evictions."),
    ]
    for name, metric_type, help_text in scalar_metrics:
        if name in snapshot:
            lines.append(f"# HELP self_correcting_agent_{name} {help_text}")
            lines.append(f"# TYPE self_correcting_agent_{name} {metric_type}")
            lines.append(f"self_correcting_agent_{name} {snapshot[name]}")
    return "\n".join(lines) + "\n"


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value in {None, ""}:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _env_auth_tokens(env: Mapping[str, str], name: str) -> Dict[str, str]:
    value = env.get(name)
    if value in {None, ""}:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    tokens: Dict[str, str] = {}
    for subject, token in payload.items():
        if not isinstance(subject, str) or not isinstance(token, str):
            raise ValueError(f"{name} subjects and tokens must be strings")
        tokens[subject] = token
    return tokens


def _env_csv_tuple(env: Mapping[str, str], name: str) -> Tuple[str, ...]:
    value = env.get(name)
    if value in {None, ""}:
        return ()
    items = {item.strip() for item in str(value).split(",") if item.strip()}
    return tuple(sorted(items))


def _env_subject_csv_tuple_map(
    env: Mapping[str, str],
    name: str,
) -> Dict[str, Tuple[str, ...]]:
    value = env.get(name)
    if value in {None, ""}:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    result: Dict[str, Tuple[str, ...]] = {}
    for subject in sorted(payload):
        tools = payload[subject]
        if not isinstance(subject, str):
            raise ValueError(f"{name} subjects must be strings")
        if isinstance(tools, str):
            result[subject] = tuple(
                sorted({item.strip() for item in tools.split(",") if item.strip()})
            )
        elif isinstance(tools, list) and all(isinstance(item, str) for item in tools):
            result[subject] = tuple(
                sorted({item.strip() for item in tools if item.strip()})
            )
        else:
            raise ValueError(f"{name} values must be strings or arrays of strings")
    return result


def _validate_auth_tokens(auth_tokens: Mapping[str, str]) -> None:
    for subject, token in auth_tokens.items():
        if not subject or not _safe_header_value(subject):
            raise ValueError("auth token subjects must be printable ASCII")
        if not token or not _safe_header_value(f"Bearer {token}"):
            raise ValueError("auth tokens must be printable ASCII")


def _validate_runtime_allowed_tools(runtime_allowed_tools: Tuple[str, ...]) -> None:
    if not runtime_allowed_tools:
        return
    from self_correcting_langgraph_agent.runtime.tools import default_runtime_tools

    known_tools = set(default_runtime_tools())
    unknown_tools = sorted(set(runtime_allowed_tools) - known_tools)
    if unknown_tools:
        raise ValueError(
            "runtime_allowed_tools contains unknown tools: "
            + ", ".join(unknown_tools)
        )


def _validate_runtime_allowed_tools_by_subject(
    runtime_allowed_tools_by_subject: Mapping[str, Tuple[str, ...]],
) -> None:
    if not runtime_allowed_tools_by_subject:
        return
    from self_correcting_langgraph_agent.runtime.tools import default_runtime_tools

    known_tools = set(default_runtime_tools())
    for subject, tools in runtime_allowed_tools_by_subject.items():
        if not subject or not _safe_header_value(subject):
            raise ValueError(
                "runtime_allowed_tools_by_subject subjects must be printable ASCII"
            )
        unknown_tools = sorted(set(tools) - known_tools)
        if unknown_tools:
            raise ValueError(
                "runtime_allowed_tools_by_subject contains unknown tools for "
                + subject
                + ": "
                + ", ".join(unknown_tools)
            )


def _safe_header_value(value: str) -> bool:
    return bool(value) and all(32 <= ord(character) <= 126 for character in value)


def _string_counts(counts: Mapping[str, int]) -> Dict[str, str]:
    return {key: str(counts[key]) for key in sorted(counts)}


def _combined_metrics_key(left: str, right: str) -> str:
    return f"{left}:{right}"


def _split_combined_metrics_key(value: str) -> Tuple[str, str]:
    left, separator, right = value.partition(":")
    if not separator:
        return value, ""
    return left, right


def _duration_bucket_labels() -> Tuple[Tuple[float, str], ...]:
    return tuple((bucket, f"{bucket:g}") for bucket in _DURATION_BUCKETS)


def _empty_duration_buckets() -> Dict[str, int]:
    buckets = {label: 0 for _bucket, label in _duration_bucket_labels()}
    buckets["+Inf"] = 0
    return buckets


def _method_metrics_label(method: str) -> str:
    method_key = method.upper()
    if method_key in _KNOWN_HTTP_METHODS:
        return method_key
    return _UNKNOWN_METRICS_LABEL


def _mapping_value(snapshot: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = snapshot.get(name)
    return value if isinstance(value, dict) else {}


def _prometheus_label(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _request_body_fingerprint(body: bytes) -> str:
    return sha256(body).hexdigest()


def _noop_release() -> None:
    return None
