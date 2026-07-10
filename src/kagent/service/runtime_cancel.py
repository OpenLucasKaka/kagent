from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from kagent.service import errors as service_errors
from kagent.service.active_runs import ActiveRunRegistry, ActiveRunSnapshot
from kagent.service.errors import failure_payload
from kagent.service.runtime import ServiceConfig
from kagent.service.runtime_lifecycle import persist_cancelled_runtime_trace
from kagent.service.runtime_status import (
    is_runtime_trace,
    runtime_status_summary,
)
from kagent.service.trace_store import (
    load_trace_by_run_id,
)
from kagent.utils.json_output import json_ready

_TRACE_READ_ERRORS = (OSError, ValueError)
_TERMINAL_RUNTIME_STATUSES = {"cancelled", "done", "failed", "resumed"}
MAX_CANCEL_REASON_CHARS = 500


def execute_runtime_cancel_request(
    run_id: str,
    body: bytes,
    service_config: ServiceConfig,
    auth_subject: str = "",
    *,
    request_auth_is_admin: bool = False,
    active_run_registry: ActiveRunRegistry | None = None,
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
    if active_run_registry is not None:
        active_run = active_run_registry.request_cancel(
            run_id,
            requested_by_auth_subject=auth_subject,
            request_auth_is_admin=request_auth_is_admin,
            reason=reason,
        )
        if active_run is not None:
            if active_run.state != "cancelled":
                return 409, failure_payload(
                    service_errors.INVALID_REQUEST_BODY,
                    "runtime run is already terminal",
                )
            try:
                cancelled_trace = persist_cancelled_runtime_trace(
                    run_id=run_id,
                    trace_dir=service_config.trace_dir,
                    active_run=active_run,
                    cancelled_by_auth_subject=auth_subject,
                )
            except (OSError, ValueError) as exc:
                return 500, failure_payload(
                    service_errors.TRACE_PERSISTENCE_FAILED,
                    f"could not persist trace: {exc}",
                )
            persisted_status = str(cancelled_trace.get("status", ""))
            if persisted_status == "resuming":
                return 409, failure_payload(
                    service_errors.INVALID_REQUEST_BODY,
                    "runtime run approval is being resumed",
                )
            if persisted_status != "cancelled":
                return 409, failure_payload(
                    service_errors.INVALID_REQUEST_BODY,
                    "runtime run is already terminal",
                )
            return 200, json_ready(
                runtime_status_summary(
                    cancelled_trace,
                    service_config.trace_dir,
                    run_id,
                )
            )
        try:
            refreshed_trace = load_trace_by_run_id(run_id, service_config.trace_dir)
        except _TRACE_READ_ERRORS:
            return 500, failure_payload(
                service_errors.TRACE_READ_FAILED,
                "runtime run trace could not be read",
            )
        if refreshed_trace is None or not is_runtime_trace(refreshed_trace):
            return 404, failure_payload(
                service_errors.NOT_FOUND,
                "runtime run trace not found",
            )
        trace = refreshed_trace
        owner_auth_subject = str(trace.get("auth_subject", "")) or auth_subject
        if auth_subject and not request_auth_is_admin and owner_auth_subject != auth_subject:
            return 404, failure_payload(
                service_errors.NOT_FOUND,
                "runtime run trace not found",
            )
    trace_status = str(trace.get("status", ""))
    if trace_status in _TERMINAL_RUNTIME_STATUSES:
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run is already terminal",
        )
    if trace_status == "resuming":
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run approval is being resumed",
        )

    cancelled_at = _utc_timestamp()
    try:
        trace = persist_cancelled_runtime_trace(
            run_id=run_id,
            trace_dir=service_config.trace_dir,
            active_run=ActiveRunSnapshot(
                run_id=run_id,
                owner_auth_subject=owner_auth_subject,
                state="cancelled",
                started_at=str(trace.get("started_at", "")) or cancelled_at,
                cancel_reason=reason,
                cancelled_at=cancelled_at,
            ),
            cancelled_by_auth_subject=auth_subject,
        )
    except (OSError, ValueError) as exc:
        return 500, failure_payload(
            service_errors.TRACE_PERSISTENCE_FAILED,
            f"could not persist trace: {exc}",
        )
    persisted_status = str(trace.get("status", ""))
    if persisted_status == "resuming":
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run approval is being resumed",
        )
    if persisted_status != "cancelled":
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run is already terminal",
        )
    return 200, json_ready(
        runtime_status_summary(trace, service_config.trace_dir, run_id)
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
