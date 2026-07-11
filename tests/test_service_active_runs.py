import json
import threading
import time
from pathlib import Path

from kagent.service import router as service_router
from kagent.service import runtime_cancel as service_runtime_cancel
from kagent.service import runtime_resume as service_runtime_resume
from kagent.service import runtime_run as service_runtime_run
from kagent.service.active_runs import ActiveRunRegistry, ActiveRunSnapshot
from kagent.service.runtime import ServiceConcurrencyLimiter, ServiceConfig
from kagent.service.runtime_lifecycle import persist_cancelled_runtime_trace
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


def test_runtime_timeout_waits_for_worker_cleanup_before_response(tmp_path, monkeypatch):
    worker_started = threading.Event()
    worker_finished = threading.Event()

    def fake_run_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        worker_finished.set()
        return {
            "trace_type": "codex_runtime",
            "run_id": kwargs["run_id"],
            "status": "cancelled",
            "goal": goal,
            "events": [],
            "observations": [],
        }

    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        fake_run_runtime_agent,
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    registry = ActiveRunRegistry()

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"slow run","plan":{"actions":[],"final_answer":"done"}}',
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            run_timeout_seconds=0.01,
        ),
        concurrency_limiter=limiter,
        active_run_registry=registry,
    )

    assert worker_started.is_set()
    assert worker_finished.is_set()
    assert status_code == 504
    assert payload["run_id"]
    assert limiter.snapshot()["active_concurrent_runs"] == "0"
    assert registry.get(payload["run_id"]) is None
    persisted = json.loads(Path(payload["trace_path"]).read_text())
    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "agent_run_timeout"


def test_timed_out_trace_upgrades_worker_cancelled_result(tmp_path):
    run_id = "timed-out-worker-result"
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": run_id,
            "status": "cancelled",
            "goal": "slow run",
            "events": [],
            "observations": [{"status": "ok", "output": {"partial": True}}],
        },
        str(tmp_path),
    )

    persisted = persist_cancelled_runtime_trace(
        run_id=run_id,
        trace_dir=str(tmp_path),
        active_run=ActiveRunSnapshot(
            run_id=run_id,
            owner_auth_subject="",
            state="timed_out",
            started_at="2026-07-11T00:00:00+00:00",
            cancel_reason="runtime run timed out",
            cancelled_at="2026-07-11T00:00:01+00:00",
        ),
        error_code="agent_run_timeout",
        error="agent run timed out",
    )

    assert persisted["status"] == "cancelled"
    assert persisted["error_code"] == "agent_run_timeout"
    assert persisted["error"] == "agent run timed out"
    assert persisted["observations"] == [
        {"status": "ok", "output": {"partial": True}}
    ]


def test_runtime_timeout_tracks_uncooperative_worker_until_it_exits(
    tmp_path,
    monkeypatch,
):
    worker_started = threading.Event()
    worker_finish = threading.Event()

    def fake_run_runtime_agent(goal, **kwargs):
        worker_started.set()
        assert worker_finish.wait(timeout=2)
        return {
            "trace_type": "codex_runtime",
            "run_id": kwargs["run_id"],
            "status": "done",
            "goal": goal,
            "events": [],
            "observations": [],
        }

    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        fake_run_runtime_agent,
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    registry = ActiveRunRegistry()

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"slow run","plan":{"actions":[],"final_answer":"done"}}',
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            run_timeout_seconds=0.01,
        ),
        concurrency_limiter=limiter,
        active_run_registry=registry,
    )

    assert worker_started.is_set()
    assert status_code == 504
    assert limiter.snapshot()["active_concurrent_runs"] == "1"
    assert registry.get(payload["run_id"]).state == "timed_out"

    worker_finish.set()
    _wait_until(lambda: limiter.snapshot()["active_concurrent_runs"] == "0")

    assert registry.get(payload["run_id"]) is None


def test_active_runtime_cancel_bypasses_full_run_concurrency_slot(tmp_path, monkeypatch):
    worker_started = threading.Event()

    def fake_run_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        token_snapshot = token.snapshot()
        return {
            "trace_type": "codex_runtime",
            "run_id": kwargs["run_id"],
            "status": "cancelled",
            "goal": goal,
            "cancelled_at": token_snapshot["cancelled_at"],
            "cancel_reason": token_snapshot["reason"],
            "events": [],
            "observations": [],
        }

    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        fake_run_runtime_agent,
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    registry = ActiveRunRegistry()
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    run_response = []

    thread = threading.Thread(
        target=lambda: run_response.append(
            service_router.handle_request(
                "POST",
                "/runtime/run",
                b'{"goal":"wait for cancel","plan":{"actions":[]}}',
                config=config,
                concurrency_limiter=limiter,
                active_run_registry=registry,
            )
        )
    )
    thread.start()
    assert worker_started.wait(timeout=1)
    trace_path = _wait_for_trace(tmp_path)
    run_id = trace_path.stem

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{run_id}/cancel",
        json.dumps({"reason": "operator requested stop"}).encode("utf-8"),
        config=config,
        concurrency_limiter=limiter,
        active_run_registry=registry,
    )
    thread.join(timeout=2)

    assert cancel_status == 200
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["cancel_reason"] == "operator requested stop"
    assert thread.is_alive() is False
    assert run_response[0][0] == 200
    assert run_response[0][1]["status"] == "cancelled"
    assert limiter.snapshot()["active_concurrent_runs"] == "0"
    persisted = json.loads(trace_path.read_text())
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "operator requested stop"


def test_runtime_cancel_registry_miss_reloads_completed_trace(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "completed-during-cancel",
            "status": "running",
            "goal": "finish while cancellation is checking the registry",
            "events": [],
            "observations": [],
        },
        str(tmp_path),
    )

    class CompletingRegistry:
        def request_cancel(self, run_id, **_kwargs):
            persist_trace(
                {
                    "trace_type": "codex_runtime",
                    "run_id": run_id,
                    "status": "done",
                    "goal": "finish while cancellation is checking the registry",
                    "events": [],
                    "observations": [],
                },
                str(tmp_path),
            )
            return None

    status_code, payload = service_runtime_cancel.execute_runtime_cancel_request(
        "completed-during-cancel",
        b'{}',
        ServiceConfig(trace_dir=str(tmp_path)),
        active_run_registry=CompletingRegistry(),
    )

    assert status_code == 409
    assert payload["error"] == "runtime run is already terminal"
    persisted = load_trace_by_run_id("completed-during-cancel", str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "done"


def test_concurrent_runtime_resume_claim_executes_pending_action_once(
    tmp_path,
    monkeypatch,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-run",
            "status": "requires_approval",
            "goal": "resume exactly once",
            "pending_approval": {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "approved"},
            },
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "approved"},
                    }
                ],
                "final_answer": "done",
            },
            "events": [],
            "observations": [],
        },
        str(tmp_path),
    )
    claim_barrier = threading.Barrier(2)
    original_claim = service_runtime_resume.claim_runtime_resume
    execution_count = 0
    execution_lock = threading.Lock()

    def synchronized_claim(**kwargs):
        claim_barrier.wait(timeout=2)
        return original_claim(**kwargs)

    def fake_run_runtime_agent(goal, **kwargs):
        nonlocal execution_count
        with execution_lock:
            execution_count += 1
        return {
            "trace_type": "codex_runtime",
            "run_id": kwargs["run_id"],
            "status": "done",
            "goal": goal,
            "plan": {"actions": []},
            "plans": [],
            "events": [],
            "observations": [],
        }

    monkeypatch.setattr(service_runtime_resume, "claim_runtime_resume", synchronized_claim)
    monkeypatch.setattr(
        service_runtime_resume,
        "run_runtime_agent",
        fake_run_runtime_agent,
    )
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)
    registry = ActiveRunRegistry()
    responses = []
    response_lock = threading.Lock()

    def resume() -> None:
        response = service_router.handle_request(
            "POST",
            "/runtime/resume",
            b'{"run_id":"pending-run","approved_action_ids":["step-1"]}',
            config=config,
            concurrency_limiter=limiter,
            active_run_registry=registry,
        )
        with response_lock:
            responses.append(response)

    threads = [threading.Thread(target=resume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(thread.is_alive() is False for thread in threads)
    assert sorted(status for status, _payload in responses) == [200, 409]
    assert execution_count == 1
    success_payload = next(payload for status, payload in responses if status == 200)
    conflict_payload = next(payload for status, payload in responses if status == 409)
    assert conflict_payload["error"] == "runtime run approval is already being resumed"
    assert success_payload["resumed_from_run_id"] == "pending-run"

    original_trace = load_trace_by_run_id("pending-run", str(tmp_path))
    assert original_trace is not None
    assert original_trace["status"] == "resumed"
    assert original_trace["resumed_to_run_id"] == success_payload["run_id"]
    assert "pending_approval" not in original_trace
    resumed_trace = load_trace_by_run_id(success_payload["run_id"], str(tmp_path))
    assert resumed_trace is not None
    assert resumed_trace["status"] == "done"
    assert resumed_trace["resumed_from_run_id"] == "pending-run"
    assert list(tmp_path.glob(".*.resume.lock")) == []

    approvals_status, approvals_payload = service_router.handle_request(
        "GET",
        "/runtime/approvals",
        b"",
        config=config,
    )
    assert approvals_status == 200
    assert approvals_payload["count"] == "0"


def test_resumed_runtime_worker_can_be_cancelled_without_reopening_approval(
    tmp_path,
    monkeypatch,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-run",
            "status": "requires_approval",
            "goal": "cancel resumed worker",
            "pending_approval": {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "approved"},
            },
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "approved"},
                    }
                ],
                "final_answer": "done",
            },
            "events": [],
            "observations": [],
        },
        str(tmp_path),
    )
    worker_started = threading.Event()

    def cancellable_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        snapshot = token.snapshot()
        return {
            "trace_type": "codex_runtime",
            "run_id": kwargs["run_id"],
            "status": "cancelled",
            "goal": goal,
            "cancelled_at": snapshot["cancelled_at"],
            "cancel_reason": snapshot["reason"],
            "plan": {"actions": []},
            "plans": [],
            "events": [],
            "observations": [],
        }

    monkeypatch.setattr(
        service_runtime_resume,
        "run_runtime_agent",
        cancellable_runtime_agent,
    )
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    registry = ActiveRunRegistry()
    resume_response = []
    thread = threading.Thread(
        target=lambda: resume_response.append(
            service_router.handle_request(
                "POST",
                "/runtime/resume",
                b'{"run_id":"pending-run","approved_action_ids":["step-1"]}',
                config=config,
                concurrency_limiter=limiter,
                active_run_registry=registry,
            )
        )
    )
    thread.start()
    assert worker_started.wait(timeout=1)

    resumed_trace_path = None

    def resumed_trace_exists() -> bool:
        nonlocal resumed_trace_path
        paths = [path for path in tmp_path.glob("*.json") if path.stem != "pending-run"]
        if paths:
            resumed_trace_path = paths[0]
            return True
        return False

    _wait_until(resumed_trace_exists)
    assert resumed_trace_path is not None
    resumed_run_id = resumed_trace_path.stem

    original_cancel_status, original_cancel_payload = service_router.handle_request(
        "POST",
        "/runtime/runs/pending-run/cancel",
        b'{}',
        config=config,
        active_run_registry=registry,
    )
    assert original_cancel_status == 409
    assert original_cancel_payload["error"] == "runtime run approval is being resumed"

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{resumed_run_id}/cancel",
        b'{"reason":"operator stop"}',
        config=config,
        active_run_registry=registry,
    )
    thread.join(timeout=2)

    assert cancel_status == 200
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["cancel_reason"] == "operator stop"
    assert thread.is_alive() is False
    assert resume_response[0][0] == 200
    assert resume_response[0][1]["status"] == "cancelled"
    assert limiter.snapshot()["active_concurrent_runs"] == "0"
    original_trace = load_trace_by_run_id("pending-run", str(tmp_path))
    assert original_trace is not None
    assert original_trace["status"] == "resumed"
    assert original_trace["resumed_to_run_id"] == resumed_run_id
    assert "pending_approval" not in original_trace


def test_runtime_worker_failure_persists_failed_trace_and_releases_slot(
    tmp_path,
    monkeypatch,
):
    def failing_runtime_agent(*_args, **_kwargs):
        raise RuntimeError("worker exploded")

    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        failing_runtime_agent,
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    registry = ActiveRunRegistry()

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"fail safely","plan":{"actions":[]}}',
        config=ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2),
        concurrency_limiter=limiter,
        active_run_registry=registry,
    )

    assert status_code == 500
    assert payload["error_code"] == "agent_run_failed"
    assert payload["run_id"]
    persisted = load_trace_by_run_id(payload["run_id"], str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["error_code"] == "agent_run_failed"
    assert "worker exploded" in persisted["error"]
    assert registry.get(payload["run_id"]) is None
    assert limiter.snapshot()["active_concurrent_runs"] == "0"


def test_runtime_final_trace_persistence_failure_marks_run_failed(
    tmp_path,
    monkeypatch,
):
    real_persist_trace = service_runtime_run.persist_trace

    def fail_completed_trace(trace, trace_dir):
        if trace.get("status") == "done":
            raise OSError("final trace write failed")
        return real_persist_trace(trace, trace_dir)

    monkeypatch.setattr(service_runtime_run, "persist_trace", fail_completed_trace)

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"persist final state","plan":{"actions":[],"final_answer":"done"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
        active_run_registry=ActiveRunRegistry(),
    )

    assert status_code == 500
    assert payload["error_code"] == "agent_run_failed"
    persisted = load_trace_by_run_id(payload["run_id"], str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "failed"
    assert persisted["error_code"] == "agent_run_failed"
    assert "final trace write failed" in persisted["error"]


def test_resumed_final_trace_persistence_failure_marks_child_failed(
    tmp_path,
    monkeypatch,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-persist-failure",
            "status": "requires_approval",
            "goal": "persist resumed final state",
            "pending_approval": {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "approved"},
            },
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "approved"},
                    }
                ],
                "final_answer": "done",
            },
            "events": [],
            "observations": [],
        },
        str(tmp_path),
    )
    real_persist_trace = service_runtime_resume.persist_trace

    def fail_completed_trace(trace, trace_dir):
        if trace.get("status") == "done":
            raise OSError("resumed final trace write failed")
        return real_persist_trace(trace, trace_dir)

    monkeypatch.setattr(service_runtime_resume, "persist_trace", fail_completed_trace)

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"pending-persist-failure","approved_action_ids":["step-1"]}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
        active_run_registry=ActiveRunRegistry(),
    )

    assert status_code == 500
    assert payload["error_code"] == "agent_run_failed"
    child_trace = load_trace_by_run_id(payload["run_id"], str(tmp_path))
    assert child_trace is not None
    assert child_trace["status"] == "failed"
    assert child_trace["error_code"] == "agent_run_failed"
    assert "resumed final trace write failed" in child_trace["error"]
    original_trace = load_trace_by_run_id("pending-persist-failure", str(tmp_path))
    assert original_trace is not None
    assert original_trace["status"] == "resumed"
    assert original_trace["resumed_to_run_id"] == payload["run_id"]


def _wait_for_trace(trace_dir: Path) -> Path:
    trace_path = None

    def trace_exists() -> bool:
        nonlocal trace_path
        paths = list(trace_dir.glob("*.json"))
        if paths:
            trace_path = paths[0]
            return True
        return False

    _wait_until(trace_exists)
    assert trace_path is not None
    return trace_path


def _wait_until(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
