from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Dict, Optional
from uuid import uuid4

from kagent.runtime.cancellation import RuntimeCancellationToken


class ExecutionSlotLease:
    """Transfers a router-owned concurrency slot to an asynchronous worker."""

    def __init__(self, release: Optional[Callable[[], None]]) -> None:
        self._release = release
        self._lock = Lock()
        self._transferred = False
        self._released = False

    def transfer(self) -> Callable[[], None]:
        with self._lock:
            if self._released:
                raise RuntimeError("execution slot lease is already released")
            if self._transferred:
                raise RuntimeError("execution slot lease is already transferred")
            self._transferred = True
        return self.release_transferred

    def release_if_owned(self) -> None:
        with self._lock:
            if self._transferred or self._released:
                return
            self._released = True
            release = self._release
        if release is not None:
            release()

    def release_transferred(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
            release = self._release
        if release is not None:
            release()


@dataclass(frozen=True)
class ActiveRunSnapshot:
    run_id: str
    owner_auth_subject: str
    state: str
    started_at: str
    cancel_reason: str = ""
    cancelled_at: str = ""


@dataclass
class _ActiveRun:
    run_id: str
    owner_auth_subject: str
    token: RuntimeCancellationToken
    started_at: str
    release: Optional[Callable[[], None]] = None
    state: str = "running"
    cancel_reason: str = ""
    cancelled_at: str = ""


class ActiveRunRegistry:
    """Process-local registry for live runtime workers and cancellation signals."""

    def __init__(self, *, instance_id: str = "") -> None:
        self._lock = Lock()
        self._runs: Dict[str, _ActiveRun] = {}
        self._instance_id = instance_id.strip() or str(uuid4())

    @property
    def instance_id(self) -> str:
        return self._instance_id

    def is_empty(self) -> bool:
        with self._lock:
            return not self._runs

    def register(
        self,
        run_id: str,
        owner_auth_subject: str,
        token: RuntimeCancellationToken,
        *,
        release: Optional[Callable[[], None]] = None,
    ) -> None:
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"runtime run is already active: {run_id}")
            self._runs[run_id] = _ActiveRun(
                run_id=run_id,
                owner_auth_subject=owner_auth_subject,
                token=token,
                started_at=datetime.now(timezone.utc).isoformat(),
                release=release,
            )

    def get(self, run_id: str) -> Optional[ActiveRunSnapshot]:
        with self._lock:
            active_run = self._runs.get(run_id)
            return _snapshot(active_run) if active_run is not None else None

    def request_cancel(
        self,
        run_id: str,
        *,
        requested_by_auth_subject: str = "",
        request_auth_is_admin: bool = False,
        reason: str = "",
    ) -> Optional[ActiveRunSnapshot]:
        with self._lock:
            active_run = self._runs.get(run_id)
            if active_run is None:
                return None
            if (
                requested_by_auth_subject
                and not request_auth_is_admin
                and active_run.owner_auth_subject != requested_by_auth_subject
            ):
                return None
            if active_run.state != "running":
                return _snapshot(active_run)
            active_run.state = "cancelled"
            active_run.cancel_reason = reason.strip()
            active_run.token.cancel(active_run.cancel_reason)
            token_snapshot = active_run.token.snapshot()
            active_run.cancelled_at = token_snapshot["cancelled_at"]
            return _snapshot(active_run)

    def mark_timed_out(self, run_id: str, *, reason: str) -> Optional[ActiveRunSnapshot]:
        with self._lock:
            active_run = self._runs.get(run_id)
            if active_run is None:
                return None
            if active_run.state == "running":
                active_run.state = "timed_out"
                active_run.cancel_reason = reason.strip()
                active_run.token.cancel(active_run.cancel_reason)
                token_snapshot = active_run.token.snapshot()
                active_run.cancelled_at = token_snapshot["cancelled_at"]
            return _snapshot(active_run)

    def result_may_persist(self, run_id: str) -> bool:
        with self._lock:
            active_run = self._runs.get(run_id)
            return active_run is not None and active_run.state == "running"

    def complete(self, run_id: str) -> None:
        with self._lock:
            active_run = self._runs.pop(run_id, None)
        if active_run is not None and active_run.release is not None:
            active_run.release()

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            state_counts: Dict[str, int] = {}
            for active_run in self._runs.values():
                state_counts[active_run.state] = state_counts.get(active_run.state, 0) + 1
            return {
                "active_runtime_runs": str(len(self._runs)),
                "active_runtime_runs_by_state": ",".join(
                    f"{state}:{count}" for state, count in sorted(state_counts.items())
                ),
            }


def _snapshot(active_run: _ActiveRun) -> ActiveRunSnapshot:
    return ActiveRunSnapshot(
        run_id=active_run.run_id,
        owner_auth_subject=active_run.owner_auth_subject,
        state=active_run.state,
        started_at=active_run.started_at,
        cancel_reason=active_run.cancel_reason,
        cancelled_at=active_run.cancelled_at,
    )
