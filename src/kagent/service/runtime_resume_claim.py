from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from kagent.service.safety import safe_trace_file_stem
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


class RuntimeResumeClaimConflict(Exception):
    pass


def claim_runtime_resume(
    *,
    trace_dir: str,
    run_id: str,
    pending_action_id: str,
    claim_id: str,
    resumed_run_id: str,
    claimed_by_auth_subject: str = "",
    runtime_instance_id: str = "",
) -> Dict[str, Any]:
    lock_path = _resume_lock_path(trace_dir, run_id)
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeResumeClaimConflict("runtime run approval is already being resumed") from exc
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(claim_id)
            lock_file.flush()
            os.fsync(lock_file.fileno())
        trace = load_trace_by_run_id(run_id, trace_dir)
        if trace is None:
            raise RuntimeResumeClaimConflict("runtime run trace no longer exists")
        pending_approval = trace.get("pending_approval")
        if trace.get("status") != "requires_approval" or not isinstance(
            pending_approval,
            dict,
        ):
            raise RuntimeResumeClaimConflict("runtime run is not waiting for approval")
        if str(pending_approval.get("id", "")) != pending_action_id:
            raise RuntimeResumeClaimConflict("runtime pending approval changed")
        trace["status"] = "resuming"
        trace["resume_claim_id"] = claim_id
        trace["resume_claimed_at"] = _utc_timestamp()
        trace["resumed_to_run_id"] = resumed_run_id
        if runtime_instance_id:
            trace["resume_runtime_instance_id"] = runtime_instance_id
        if claimed_by_auth_subject:
            trace["resumed_by_auth_subject"] = claimed_by_auth_subject
            trace["approved_by_auth_subject"] = claimed_by_auth_subject
        trace["trace_path"] = persist_trace(trace, trace_dir)
        return trace
    finally:
        lock_path.unlink(missing_ok=True)


def release_runtime_resume_claim(
    *,
    trace_dir: str,
    run_id: str,
    claim_id: str,
) -> None:
    trace = load_trace_by_run_id(run_id, trace_dir)
    if trace is None or trace.get("resume_claim_id") != claim_id:
        return
    if trace.get("status") != "resuming":
        return
    trace["status"] = "requires_approval"
    trace.pop("resume_claim_id", None)
    trace.pop("resume_claimed_at", None)
    trace.pop("resumed_to_run_id", None)
    trace.pop("resumed_by_auth_subject", None)
    trace.pop("approved_by_auth_subject", None)
    trace.pop("resume_runtime_instance_id", None)
    persist_trace(trace, trace_dir)


def complete_runtime_resume_claim(
    *,
    trace_dir: str,
    run_id: str,
    claim_id: str,
    resumed_run_id: str,
) -> None:
    trace = load_trace_by_run_id(run_id, trace_dir)
    if trace is None or trace.get("resume_claim_id") != claim_id:
        return
    if trace.get("status") != "resuming":
        return
    completed_at = _utc_timestamp()
    trace["status"] = "resumed"
    trace["completed_at"] = completed_at
    trace["resumed_at"] = completed_at
    trace["resumed_to_run_id"] = resumed_run_id
    trace.pop("pending_approval", None)
    persist_trace(trace, trace_dir)


def _resume_lock_path(trace_dir: str, run_id: str) -> Path:
    return Path(trace_dir) / f".{safe_trace_file_stem(run_id)}.resume.lock"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
