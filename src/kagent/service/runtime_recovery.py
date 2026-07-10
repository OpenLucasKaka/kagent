from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from typing import Any, Dict, Optional
from uuid import uuid4

from kagent.runtime import RUNTIME_TRACE_TYPE
from kagent.service.active_runs import ActiveRunRegistry
from kagent.service.errors import AGENT_RUN_INTERRUPTED
from kagent.service.safety import safe_trace_file_stem
from kagent.service.trace_store import (
    load_trace_by_run_id,
    persist_trace,
    runtime_trace_lock,
)

RUNTIME_INTERRUPTED_ERROR_CODE = AGENT_RUN_INTERRUPTED
_INSTANCE_DIRECTORY = ".runtime-instances"


class RuntimeInstanceLease:
    """Heartbeat lease used to distinguish live workers from orphaned traces."""

    def __init__(
        self,
        trace_dir: str,
        *,
        instance_id: str,
        heartbeat_seconds: float,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self.trace_dir = trace_dir
        self.instance_id = instance_id
        self.heartbeat_seconds = heartbeat_seconds
        self._started_at = _utc_timestamp()
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Optional[Thread] = None
        self._shutdown_watcher_started = False

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._write_heartbeat()
            thread = Thread(
                target=self._heartbeat_loop,
                name=f"kagent-runtime-heartbeat-{self.instance_id[:8]}",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread is not current_thread():
            thread.join(timeout=max(1.0, self.heartbeat_seconds * 2))
        try:
            _lease_path(self.trace_dir, self.instance_id).unlink(missing_ok=True)
        except OSError:
            pass

    def stop_when_idle(self, registry: ActiveRunRegistry) -> None:
        if registry.is_empty():
            self.stop()
            return
        with self._lock:
            if self._shutdown_watcher_started:
                return
            self._shutdown_watcher_started = True

        def wait_for_workers() -> None:
            while not registry.is_empty():
                time.sleep(min(0.1, self.heartbeat_seconds))
            self.stop()

        Thread(
            target=wait_for_workers,
            name=f"kagent-runtime-lease-drain-{self.instance_id[:8]}",
            daemon=True,
        ).start()

    def snapshot(self) -> Dict[str, str]:
        return {
            "runtime_instance_id": self.instance_id,
            "runtime_instance_started_at": self._started_at,
            "runtime_instance_heartbeat_seconds": str(self.heartbeat_seconds),
        }

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_seconds):
            try:
                self._write_heartbeat()
            except OSError:
                continue

    def _write_heartbeat(self) -> None:
        _persist_private_json(
            _lease_path(self.trace_dir, self.instance_id),
            {
                "runtime_instance_id": self.instance_id,
                "started_at": self._started_at,
                "heartbeat_at": _utc_timestamp(),
            },
        )


def reconcile_orphaned_runtime_traces(
    trace_dir: str,
    *,
    current_instance_id: str,
    stale_after_seconds: float,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")
    current_time = now or datetime.now(timezone.utc)
    summary: Dict[str, Any] = {
        "scanned": 0,
        "recovered_running": 0,
        "completed_resumes": 0,
        "reopened_approvals": 0,
        "protected_live": 0,
        "skipped_unowned": 0,
        "skipped_locked": 0,
        "errors": [],
    }
    traces = _runtime_trace_candidates(trace_dir, summary)
    lease_cache: Dict[str, bool] = {}

    for trace in traces:
        if trace.get("status") != "running":
            continue
        owner_id = str(trace.get("runtime_instance_id", ""))
        if not _owner_is_orphaned(
            trace_dir,
            owner_id,
            current_instance_id,
            stale_after_seconds,
            current_time,
            lease_cache,
            summary,
        ):
            continue
        outcome = _reconcile_running_trace(
            trace_dir,
            trace,
            current_instance_id,
            stale_after_seconds,
            current_time,
        )
        _record_outcome(summary, outcome, "recovered_running")

    for trace in traces:
        if trace.get("status") != "resuming":
            continue
        owner_id = str(trace.get("resume_runtime_instance_id", ""))
        if not _owner_is_orphaned(
            trace_dir,
            owner_id,
            current_instance_id,
            stale_after_seconds,
            current_time,
            lease_cache,
            summary,
        ):
            continue
        outcome = _reconcile_resuming_trace(
            trace_dir,
            trace,
            current_instance_id,
            stale_after_seconds,
            current_time,
        )
        if outcome == "completed":
            summary["completed_resumes"] += 1
        elif outcome == "reopened":
            summary["reopened_approvals"] += 1
        elif outcome == "locked":
            summary["skipped_locked"] += 1
        elif outcome.startswith("error:"):
            summary["errors"].append(outcome.removeprefix("error:"))
    return summary


def runtime_instance_is_stale(
    trace_dir: str,
    instance_id: str,
    *,
    stale_after_seconds: float,
    now: Optional[datetime] = None,
) -> bool:
    path = _lease_path(trace_dir, instance_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(payload, dict) or payload.get("runtime_instance_id") != instance_id:
        return True
    heartbeat_at = _parse_timestamp(payload.get("heartbeat_at"))
    if heartbeat_at is None:
        return True
    current_time = now or datetime.now(timezone.utc)
    return (current_time - heartbeat_at).total_seconds() > stale_after_seconds


def _runtime_trace_candidates(trace_dir: str, summary: Dict[str, Any]) -> list[Dict[str, Any]]:
    traces = []
    for path in sorted(Path(trace_dir).glob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            summary["errors"].append(f"{path}: {exc}")
            continue
        if not isinstance(payload, dict) or payload.get("trace_type") != RUNTIME_TRACE_TYPE:
            continue
        summary["scanned"] += 1
        traces.append(payload)
    return traces


def _owner_is_orphaned(
    trace_dir: str,
    owner_id: str,
    current_instance_id: str,
    stale_after_seconds: float,
    now: datetime,
    lease_cache: Dict[str, bool],
    summary: Dict[str, Any],
) -> bool:
    if not owner_id:
        summary["skipped_unowned"] += 1
        return False
    if owner_id == current_instance_id:
        summary["protected_live"] += 1
        return False
    try:
        if owner_id not in lease_cache:
            lease_cache[owner_id] = runtime_instance_is_stale(
                trace_dir,
                owner_id,
                stale_after_seconds=stale_after_seconds,
                now=now,
            )
        stale = lease_cache[owner_id]
    except ValueError as exc:
        summary["errors"].append(f"runtime instance {owner_id!r}: {exc}")
        return False
    if not stale:
        summary["protected_live"] += 1
    return stale


def _reconcile_running_trace(
    trace_dir: str,
    trace: Dict[str, Any],
    current_instance_id: str,
    stale_after_seconds: float,
    now: datetime,
) -> str:
    run_id = str(trace.get("run_id", ""))
    try:
        with _TraceReconcileLock(
            trace_dir,
            run_id,
            instance_id=current_instance_id,
            stale_after_seconds=stale_after_seconds,
            now=now,
        ) as acquired:
            if not acquired:
                return "locked"
            with runtime_trace_lock(run_id, trace_dir):
                current = load_trace_by_run_id(run_id, trace_dir)
                if current is None or current.get("status") != "running":
                    return "unchanged"
                completed_at = now.isoformat()
                current["status"] = "failed"
                current["completed_at"] = completed_at
                current["interrupted_at"] = completed_at
                current["error_code"] = RUNTIME_INTERRUPTED_ERROR_CODE
                current["error"] = "runtime worker owner heartbeat expired"
                current["orphaned_runtime_instance_id"] = current.get(
                    "runtime_instance_id",
                    "",
                )
                current["reconciled_by_runtime_instance_id"] = current_instance_id
                current["reconciled_at"] = completed_at
                current.pop("pending_approval", None)
                _append_recovery_event(current, completed_at)
                _refresh_duration(current, now)
                current["trace_path"] = persist_trace(current, trace_dir)
                return "recovered"
    except (OSError, ValueError) as exc:
        return f"error:{run_id}: {exc}"


def _reconcile_resuming_trace(
    trace_dir: str,
    trace: Dict[str, Any],
    current_instance_id: str,
    stale_after_seconds: float,
    now: datetime,
) -> str:
    run_id = str(trace.get("run_id", ""))
    try:
        with _TraceReconcileLock(
            trace_dir,
            run_id,
            instance_id=current_instance_id,
            stale_after_seconds=stale_after_seconds,
            now=now,
        ) as acquired:
            if not acquired:
                return "locked"
            with runtime_trace_lock(run_id, trace_dir):
                current = load_trace_by_run_id(run_id, trace_dir)
                if current is None or current.get("status") != "resuming":
                    return "unchanged"
                child_run_id = str(current.get("resumed_to_run_id", ""))
                child = (
                    load_trace_by_run_id(child_run_id, trace_dir)
                    if child_run_id
                    else None
                )
                reconciled_at = now.isoformat()
                current["reconciled_at"] = reconciled_at
                current["reconciled_by_runtime_instance_id"] = current_instance_id
                if child is None:
                    current["status"] = "requires_approval"
                    current["resume_recovery"] = "reopened_before_child_initialization"
                    _clear_resume_claim(current, clear_child=True)
                    persist_trace(current, trace_dir)
                    return "reopened"
                current["status"] = "resumed"
                current["completed_at"] = reconciled_at
                current["resumed_at"] = reconciled_at
                current["resume_recovery"] = "approval_consumed_after_owner_loss"
                current.pop("pending_approval", None)
                current.pop("resume_claim_id", None)
                current.pop("resume_claimed_at", None)
                persist_trace(current, trace_dir)
                return "completed"
    except (OSError, ValueError) as exc:
        return f"error:{run_id}: {exc}"


class _TraceReconcileLock:
    def __init__(
        self,
        trace_dir: str,
        run_id: str,
        *,
        instance_id: str,
        stale_after_seconds: float,
        now: datetime,
    ) -> None:
        self.path = Path(trace_dir) / f".{safe_trace_file_stem(run_id)}.reconcile.lock"
        self.instance_id = instance_id
        self.stale_after_seconds = stale_after_seconds
        self.now = now
        self.fd: Optional[int] = None

    def __enter__(self) -> bool:
        if self._create():
            return True
        if not self._reclaim_stale():
            return False
        return self._create()

    def _create(self) -> bool:
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            payload = json.dumps(
                {
                    "runtime_instance_id": self.instance_id,
                    "created_at": self.now.isoformat(),
                },
                sort_keys=True,
            )
            os.write(self.fd, f"{payload}\n".encode("utf-8"))
            os.fsync(self.fd)
        except Exception:
            os.close(self.fd)
            self.fd = None
            self.path.unlink(missing_ok=True)
            raise
        return True

    def _reclaim_stale(self) -> bool:
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            existing_fd = os.open(self.path, flags)
        except FileNotFoundError:
            return True
        try:
            try:
                fcntl.flock(existing_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            stat_result = os.fstat(existing_fd)
            if not self._existing_lock_is_stale(existing_fd, stat_result.st_mtime):
                return False
            try:
                current_stat = os.stat(self.path, follow_symlinks=False)
            except FileNotFoundError:
                return True
            if (
                current_stat.st_dev != stat_result.st_dev
                or current_stat.st_ino != stat_result.st_ino
            ):
                return False
            self.path.unlink()
            return True
        finally:
            os.close(existing_fd)

    def _existing_lock_is_stale(self, existing_fd: int, modified_at: float) -> bool:
        try:
            os.lseek(existing_fd, 0, os.SEEK_SET)
            payload = json.loads(os.read(existing_fd, 4096).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        created_at = _parse_timestamp(payload.get("created_at"))
        lock_time = created_at or datetime.fromtimestamp(modified_at, timezone.utc)
        return (self.now - lock_time).total_seconds() > self.stale_after_seconds

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self.fd is None:
            return
        try:
            stat_result = os.fstat(self.fd)
            try:
                current_stat = os.stat(self.path, follow_symlinks=False)
            except FileNotFoundError:
                current_stat = None
            if (
                current_stat is not None
                and current_stat.st_dev == stat_result.st_dev
                and current_stat.st_ino == stat_result.st_ino
            ):
                self.path.unlink()
        finally:
            os.close(self.fd)
            self.fd = None


def _record_outcome(summary: Dict[str, Any], outcome: str, success_key: str) -> None:
    if outcome == "recovered":
        summary[success_key] += 1
    elif outcome == "locked":
        summary["skipped_locked"] += 1
    elif outcome.startswith("error:"):
        summary["errors"].append(outcome.removeprefix("error:"))


def _clear_resume_claim(trace: Dict[str, Any], *, clear_child: bool) -> None:
    for key in (
        "resume_claim_id",
        "resume_claimed_at",
        "resume_runtime_instance_id",
        "resumed_by_auth_subject",
        "approved_by_auth_subject",
    ):
        trace.pop(key, None)
    if clear_child:
        trace.pop("resumed_to_run_id", None)


def _append_recovery_event(trace: Dict[str, Any], completed_at: str) -> None:
    events = trace.get("events")
    if not isinstance(events, list):
        events = []
        trace["events"] = events
    events.append(
        {
            "node": "runtime",
            "status": "failed",
            "started_at": completed_at,
            "completed_at": completed_at,
            "duration_seconds": "0.0000",
            "error_code": RUNTIME_INTERRUPTED_ERROR_CODE,
            "error": "runtime worker owner heartbeat expired",
        }
    )


def _refresh_duration(trace: Dict[str, Any], now: datetime) -> None:
    started_at = _parse_timestamp(trace.get("started_at"))
    if started_at is not None:
        trace["duration_seconds"] = f"{max(0.0, (now - started_at).total_seconds()):.4f}"


def _lease_path(trace_dir: str, instance_id: str) -> Path:
    return Path(trace_dir) / _INSTANCE_DIRECTORY / f"{safe_trace_file_stem(instance_id)}.json"


def _persist_private_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        fd = os.open(temporary_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
