from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from kagent.runtime import RUNTIME_TRACE_TYPE
from kagent.service.active_runs import ActiveRunSnapshot
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


def running_runtime_trace(
    *,
    run_id: str,
    goal: str,
    max_iterations: int,
    auth_subject: str = "",
    resumed_from_run_id: str = "",
    runtime_instance_id: str = "",
) -> Dict[str, Any]:
    started_at = _utc_timestamp()
    trace: Dict[str, Any] = {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": "running",
        "goal": goal,
        "started_at": started_at,
        "max_iterations": str(max_iterations),
        "iteration_count": "0",
        "iteration_budget_remaining": str(max_iterations),
        "events": [],
        "observations": [],
        "plans": [],
        "plan": {"actions": []},
    }
    if auth_subject:
        trace["auth_subject"] = auth_subject
    if resumed_from_run_id:
        trace["resumed_from_run_id"] = resumed_from_run_id
    if runtime_instance_id:
        trace["runtime_instance_id"] = runtime_instance_id
    return trace


def persist_cancelled_runtime_trace(
    *,
    run_id: str,
    trace_dir: str,
    active_run: ActiveRunSnapshot,
    cancelled_by_auth_subject: str = "",
    error_code: str = "run_cancelled",
    error: str = "runtime run cancelled",
) -> Dict[str, Any]:
    trace = load_trace_by_run_id(run_id, trace_dir) or {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": "running",
        "started_at": active_run.started_at,
        "events": [],
    }
    if str(trace.get("status", "")) in {"done", "failed", "resumed"}:
        return trace
    cancelled_at = active_run.cancelled_at or _utc_timestamp()
    trace["status"] = "cancelled"
    trace["completed_at"] = cancelled_at
    trace["cancelled_at"] = cancelled_at
    trace["error_code"] = error_code
    trace["error"] = error
    if cancelled_by_auth_subject:
        trace["cancelled_by_auth_subject"] = cancelled_by_auth_subject
    if active_run.cancel_reason:
        trace["cancel_reason"] = active_run.cancel_reason
    trace.pop("pending_approval", None)
    _append_cancel_event(trace, cancelled_at, active_run.cancel_reason)
    _refresh_duration_seconds(trace)
    trace["trace_path"] = persist_trace(trace, trace_dir)
    return trace


def persist_failed_runtime_trace(
    *,
    run_id: str,
    trace_dir: str,
    error_code: str,
    error: str,
) -> Dict[str, Any]:
    trace = load_trace_by_run_id(run_id, trace_dir) or {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": "running",
        "started_at": _utc_timestamp(),
        "events": [],
    }
    if str(trace.get("status", "")) in {"cancelled", "done", "failed", "resumed"}:
        return trace
    completed_at = _utc_timestamp()
    trace["status"] = "failed"
    trace["completed_at"] = completed_at
    trace["error_code"] = error_code
    trace["error"] = error
    trace.pop("pending_approval", None)
    _append_failure_event(trace, completed_at, error_code, error)
    _refresh_duration_seconds(trace)
    trace["trace_path"] = persist_trace(trace, trace_dir)
    return trace


def _append_cancel_event(trace: Dict[str, Any], cancelled_at: str, reason: str) -> None:
    events = trace.get("events")
    if not isinstance(events, list):
        events = []
        trace["events"] = events
    if any(
        isinstance(event, dict)
        and event.get("node") == "control"
        and event.get("status") == "cancelled"
        for event in events
    ):
        return
    event: Dict[str, Any] = {
        "node": "control",
        "status": "cancelled",
        "started_at": cancelled_at,
        "completed_at": cancelled_at,
        "duration_seconds": "0.0000",
    }
    if reason:
        event["reason"] = reason
    events.append(event)


def _append_failure_event(
    trace: Dict[str, Any],
    completed_at: str,
    error_code: str,
    error: str,
) -> None:
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
            "error_code": error_code,
            "error": error,
        }
    )


def _refresh_duration_seconds(trace: Dict[str, Any]) -> None:
    started_at = trace.get("started_at")
    if not isinstance(started_at, str) or not started_at.strip():
        return
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    trace["duration_seconds"] = f"{max(0.0, time.time() - started.timestamp()):.4f}"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
