from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from self_correcting_langgraph_agent.service import errors as service_errors
from self_correcting_langgraph_agent.service.errors import failure_payload
from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.service.runtime_status import (
    is_runtime_trace,
    runtime_status_summary,
)
from self_correcting_langgraph_agent.service.trace_store import (
    load_trace_by_run_id,
    persist_trace,
)
from self_correcting_langgraph_agent.utils.json_output import json_ready

_TRACE_READ_ERRORS = (OSError, ValueError)
_TERMINAL_RUNTIME_STATUSES = {"cancelled", "done", "failed"}
MAX_CANCEL_REASON_CHARS = 500


def execute_runtime_cancel_request(
    run_id: str,
    body: bytes,
    service_config: ServiceConfig,
    auth_subject: str = "",
    *,
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime cancel",
        )
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 400, failure_payload(service_errors.INVALID_JSON, f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "request body must be a JSON object",
        )
    if set(payload) - {"reason"}:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "cancel request only accepts an optional reason field",
        )
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "reason must be a string",
        )
    reason = reason.strip()
    if len(reason) > MAX_CANCEL_REASON_CHARS:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            f"reason must be at most {MAX_CANCEL_REASON_CHARS} characters",
        )

    try:
        trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if trace is None or not is_runtime_trace(trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    owner_auth_subject = str(trace.get("auth_subject", "")) or auth_subject
    if auth_subject and not request_auth_is_admin and owner_auth_subject != auth_subject:
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    if str(trace.get("status", "")) in _TERMINAL_RUNTIME_STATUSES:
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run is already terminal",
        )

    cancelled_at = _utc_timestamp()
    trace["status"] = "cancelled"
    trace["completed_at"] = cancelled_at
    trace["cancelled_at"] = cancelled_at
    trace["cancelled_by_auth_subject"] = auth_subject
    if reason:
        trace["cancel_reason"] = reason
    trace.pop("pending_approval", None)
    _append_cancel_event(trace, cancelled_at, reason)
    _refresh_duration_seconds(trace)
    try:
        trace["trace_path"] = persist_trace(trace, service_config.trace_dir)
    except OSError as exc:
        return 500, failure_payload(
            service_errors.TRACE_PERSISTENCE_FAILED,
            f"could not persist trace: {exc}",
        )
    return 200, json_ready(
        runtime_status_summary(trace, service_config.trace_dir, run_id)
    )


def _append_cancel_event(
    trace: Dict[str, Any],
    cancelled_at: str,
    reason: str,
) -> None:
    events = trace.get("events")
    if not isinstance(events, list):
        events = []
        trace["events"] = events
    event = {
        "node": "control",
        "status": "cancelled",
        "started_at": cancelled_at,
        "completed_at": cancelled_at,
        "duration_seconds": "0.0000",
    }
    if reason:
        event["reason"] = reason
    events.append(event)


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
