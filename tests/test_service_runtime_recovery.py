import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from kagent.service.runtime_recovery import (
    RUNTIME_INTERRUPTED_ERROR_CODE,
    RuntimeInstanceLease,
    reconcile_orphaned_runtime_traces,
    runtime_instance_is_stale,
)
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


def test_runtime_instance_lease_writes_private_fresh_heartbeat(tmp_path):
    lease = RuntimeInstanceLease(
        str(tmp_path),
        instance_id="instance-live",
        heartbeat_seconds=0.05,
    )

    lease.start()
    try:
        lease_path = tmp_path / ".runtime-instances" / "instance-live.json"
        payload = json.loads(lease_path.read_text(encoding="utf-8"))

        assert payload["runtime_instance_id"] == "instance-live"
        assert payload["heartbeat_at"]
        assert stat.S_IMODE(lease_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(lease_path.parent.stat().st_mode) == 0o700
        assert not runtime_instance_is_stale(
            str(tmp_path),
            "instance-live",
            stale_after_seconds=10,
        )
    finally:
        lease.stop()

    assert not lease_path.exists()


def test_reconcile_marks_running_trace_failed_when_owner_lease_is_missing(tmp_path):
    persist_trace(
        _runtime_trace(
            run_id="orphaned-run",
            status="running",
            runtime_instance_id="dead-instance",
        ),
        str(tmp_path),
    )

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
    )

    assert summary["recovered_running"] == 1
    recovered = load_trace_by_run_id("orphaned-run", str(tmp_path))
    assert recovered is not None
    assert recovered["status"] == "failed"
    assert recovered["error_code"] == RUNTIME_INTERRUPTED_ERROR_CODE
    assert recovered["orphaned_runtime_instance_id"] == "dead-instance"
    assert recovered["reconciled_by_runtime_instance_id"] == "replacement-instance"
    assert recovered["completed_at"]
    assert recovered["events"][-1]["error_code"] == RUNTIME_INTERRUPTED_ERROR_CODE


def test_reconcile_protects_running_trace_owned_by_live_instance(tmp_path):
    live_lease = RuntimeInstanceLease(
        str(tmp_path),
        instance_id="live-instance",
        heartbeat_seconds=0.05,
    )
    live_lease.start()
    try:
        persist_trace(
            _runtime_trace(
                run_id="live-run",
                status="running",
                runtime_instance_id="live-instance",
            ),
            str(tmp_path),
        )

        summary = reconcile_orphaned_runtime_traces(
            str(tmp_path),
            current_instance_id="other-instance",
            stale_after_seconds=30,
        )

        assert summary["recovered_running"] == 0
        assert summary["protected_live"] == 1
        protected = load_trace_by_run_id("live-run", str(tmp_path))
        assert protected is not None
        assert protected["status"] == "running"
    finally:
        live_lease.stop()


def test_reconcile_consumes_resuming_approval_when_child_trace_exists(tmp_path):
    persist_trace(
        _resuming_trace("pending-run", child_run_id="resumed-child"),
        str(tmp_path),
    )
    persist_trace(
        {
            **_runtime_trace(
            run_id="resumed-child",
            status="running",
            runtime_instance_id="dead-instance",
            ),
            "resumed_from_run_id": "pending-run",
        },
        str(tmp_path),
    )

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
    )

    assert summary["recovered_running"] == 1
    assert summary["completed_resumes"] == 1
    original = load_trace_by_run_id("pending-run", str(tmp_path))
    child = load_trace_by_run_id("resumed-child", str(tmp_path))
    assert original is not None
    assert child is not None
    assert original["status"] == "resumed"
    assert original["resume_recovery"] == "approval_consumed_after_owner_loss"
    assert "pending_approval" not in original
    assert child["status"] == "failed"
    assert child["error_code"] == "approval_execution_interrupted"
    assert child["events"][-1]["error_code"] == "approval_execution_interrupted"


def test_reconcile_reopens_approval_when_resume_child_was_never_initialized(tmp_path):
    persist_trace(
        _resuming_trace("pending-run", child_run_id="missing-child"),
        str(tmp_path),
    )

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
    )

    assert summary["reopened_approvals"] == 1
    original = load_trace_by_run_id("pending-run", str(tmp_path))
    assert original is not None
    assert original["status"] == "requires_approval"
    assert original["resume_recovery"] == "reopened_before_child_initialization"
    assert original["pending_approval"]["id"] == "step-1"
    assert "resume_claim_id" not in original
    assert "resumed_to_run_id" not in original
    assert "resume_runtime_instance_id" not in original


def test_concurrent_reconciliation_recovers_orphaned_trace_once(tmp_path):
    persist_trace(
        _runtime_trace(
            run_id="concurrent-orphan",
            status="running",
            runtime_instance_id="dead-instance",
        ),
        str(tmp_path),
    )

    def reconcile(instance_id):
        return reconcile_orphaned_runtime_traces(
            str(tmp_path),
            current_instance_id=instance_id,
            stale_after_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        summaries = list(executor.map(reconcile, ("replacement-a", "replacement-b")))

    assert sum(summary["recovered_running"] for summary in summaries) == 1
    recovered = load_trace_by_run_id("concurrent-orphan", str(tmp_path))
    assert recovered is not None
    assert recovered["status"] == "failed"


def test_reconcile_reclaims_stale_process_lock(tmp_path):
    persist_trace(
        _runtime_trace(
            run_id="stale-lock-run",
            status="running",
            runtime_instance_id="dead-instance",
        ),
        str(tmp_path),
    )
    lock_path = tmp_path / ".stale-lock-run.reconcile.lock"
    lock_path.write_text("", encoding="utf-8")
    stale_timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(lock_path, (stale_timestamp, stale_timestamp))

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert summary["recovered_running"] == 1
    assert summary["skipped_locked"] == 0
    assert not lock_path.exists()


def test_reconcile_preserves_fresh_process_lock(tmp_path):
    persist_trace(
        _runtime_trace(
            run_id="fresh-lock-run",
            status="running",
            runtime_instance_id="dead-instance",
        ),
        str(tmp_path),
    )
    lock_path = tmp_path / ".fresh-lock-run.reconcile.lock"
    lock_path.write_text(
        json.dumps(
            {
                "runtime_instance_id": "starting-instance",
                "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert summary["recovered_running"] == 0
    assert summary["skipped_locked"] == 1
    assert lock_path.exists()


def test_reconcile_reclaims_stale_lock_with_non_object_json(tmp_path):
    persist_trace(
        _runtime_trace(
            run_id="malformed-lock-run",
            status="running",
            runtime_instance_id="dead-instance",
        ),
        str(tmp_path),
    )
    lock_path = tmp_path / ".malformed-lock-run.reconcile.lock"
    lock_path.write_text("[]", encoding="utf-8")
    stale_timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(lock_path, (stale_timestamp, stale_timestamp))

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert summary["recovered_running"] == 1
    assert not lock_path.exists()


def test_reconcile_skips_legacy_running_trace_without_instance_owner(tmp_path):
    persist_trace(
        _runtime_trace(run_id="legacy-running", status="running"),
        str(tmp_path),
    )

    summary = reconcile_orphaned_runtime_traces(
        str(tmp_path),
        current_instance_id="replacement-instance",
        stale_after_seconds=30,
    )

    assert summary["skipped_unowned"] == 1
    legacy = load_trace_by_run_id("legacy-running", str(tmp_path))
    assert legacy is not None
    assert legacy["status"] == "running"


def _runtime_trace(
    *,
    run_id: str,
    status: str,
    runtime_instance_id: str = "",
):
    trace = {
        "trace_type": "codex_runtime",
        "run_id": run_id,
        "status": status,
        "goal": "runtime recovery test",
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        "events": [],
        "observations": [],
        "plans": [],
        "plan": {"actions": []},
    }
    if runtime_instance_id:
        trace["runtime_instance_id"] = runtime_instance_id
    return trace


def _resuming_trace(run_id: str, *, child_run_id: str):
    trace = _runtime_trace(run_id=run_id, status="resuming")
    trace.update(
        {
            "pending_approval": {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "approved"},
            },
            "resume_claim_id": "claim-1",
            "resume_claimed_at": datetime.now(timezone.utc).isoformat(),
            "resume_runtime_instance_id": "dead-instance",
            "resumed_to_run_id": child_run_id,
        }
    )
    return trace
