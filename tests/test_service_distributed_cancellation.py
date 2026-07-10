import json
import threading
import time
from pathlib import Path

from kagent.service import router as service_router
from kagent.service import runtime_cancel as service_runtime_cancel
from kagent.service import runtime_resume as service_runtime_resume
from kagent.service import runtime_run as service_runtime_run
from kagent.service.active_runs import ActiveRunRegistry
from kagent.service.runtime import ServiceConfig
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


def test_runtime_run_remote_cancel_reaches_owner_token(tmp_path, monkeypatch):
    worker_started = threading.Event()
    cancellation_observed = threading.Event()

    def cancellable_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        cancellation_observed.set()
        snapshot = token.snapshot()
        return _runtime_result(
            goal,
            kwargs["run_id"],
            status="cancelled",
            cancel_reason=snapshot["reason"],
            cancelled_at=snapshot["cancelled_at"],
        )

    monkeypatch.setattr(service_runtime_run, "run_runtime_agent", cancellable_runtime_agent)
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    owner_registry = ActiveRunRegistry(instance_id="replica-owner")
    remote_registry = ActiveRunRegistry(instance_id="replica-remote")
    responses = []
    thread = _start_runtime_run(config, owner_registry, responses)
    assert worker_started.wait(timeout=1)
    run_id = _wait_for_child_trace(tmp_path).stem

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{run_id}/cancel",
        b'{"reason":"remote operator stop"}',
        config=config,
        active_run_registry=remote_registry,
    )
    thread.join(timeout=2)

    assert cancel_status == 200
    assert cancel_payload["status"] == "cancelled"
    assert cancellation_observed.is_set()
    assert thread.is_alive() is False
    assert responses[0][0] == 200
    assert responses[0][1]["status"] == "cancelled"
    assert responses[0][1]["cancel_reason"] == "remote operator stop"
    persisted = load_trace_by_run_id(run_id, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "remote operator stop"


def test_runtime_run_remote_cancel_cannot_be_overwritten_by_done(
    tmp_path,
    monkeypatch,
):
    worker_started = threading.Event()
    finish_worker = threading.Event()

    def late_done_runtime_agent(goal, **kwargs):
        worker_started.set()
        assert finish_worker.wait(timeout=2)
        return _runtime_result(goal, kwargs["run_id"], status="done")

    monkeypatch.setattr(service_runtime_run, "run_runtime_agent", late_done_runtime_agent)
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    responses = []
    thread = _start_runtime_run(
        config,
        ActiveRunRegistry(instance_id="replica-owner"),
        responses,
    )
    assert worker_started.wait(timeout=1)
    run_id = _wait_for_child_trace(tmp_path).stem

    cancel_status, _ = service_router.handle_request(
        "POST",
        f"/runtime/runs/{run_id}/cancel",
        b'{"reason":"remote cancellation won"}',
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-remote"),
    )
    finish_worker.set()
    thread.join(timeout=2)

    assert cancel_status == 200
    assert thread.is_alive() is False
    assert responses[0][0] == 200
    persisted = load_trace_by_run_id(run_id, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "remote cancellation won"


def test_runtime_run_remote_cancel_after_completion_returns_terminal_conflict(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        lambda goal, **kwargs: _runtime_result(goal, kwargs["run_id"], status="done"),
    )
    config = ServiceConfig(trace_dir=str(tmp_path))
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"finish first","plan":{"actions":[]}}',
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-owner"),
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{payload['run_id']}/cancel",
        b"{}",
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-remote"),
    )

    assert status_code == 200
    assert cancel_status == 409
    assert cancel_payload["error"] == "runtime run is already terminal"
    persisted = load_trace_by_run_id(payload["run_id"], str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "done"


def test_runtime_worker_repairs_cancel_trace_when_cancel_persistence_fails(
    tmp_path,
    monkeypatch,
):
    worker_started = threading.Event()

    def cancellable_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        snapshot = token.snapshot()
        return _runtime_result(
            goal,
            kwargs["run_id"],
            status="cancelled",
            cancel_reason=snapshot["reason"],
            cancelled_at=snapshot["cancelled_at"],
        )

    def failing_cancel_persistence(**_kwargs):
        raise OSError("trace store unavailable")

    monkeypatch.setattr(service_runtime_run, "run_runtime_agent", cancellable_runtime_agent)
    monkeypatch.setattr(
        service_runtime_cancel,
        "persist_cancelled_runtime_trace",
        failing_cancel_persistence,
    )
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    registry = ActiveRunRegistry(instance_id="replica-owner")
    responses = []
    thread = _start_runtime_run(config, registry, responses)
    assert worker_started.wait(timeout=1)
    run_id = _wait_for_child_trace(tmp_path).stem

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{run_id}/cancel",
        b'{"reason":"persist on worker exit"}',
        config=config,
        active_run_registry=registry,
    )
    thread.join(timeout=2)

    assert cancel_status == 500
    assert cancel_payload["error_code"] == "trace_persistence_failed"
    assert thread.is_alive() is False
    assert responses[0][0] == 200
    assert responses[0][1]["status"] == "cancelled"
    persisted = load_trace_by_run_id(run_id, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "persist on worker exit"


def test_runtime_resume_remote_cancel_reaches_owner_token(tmp_path, monkeypatch):
    _persist_pending_approval(tmp_path, run_id="pending-remote-token")
    worker_started = threading.Event()
    cancellation_observed = threading.Event()

    def cancellable_runtime_agent(goal, **kwargs):
        token = kwargs["cancellation_token"]
        worker_started.set()
        while not token.is_cancelled():
            time.sleep(0.005)
        cancellation_observed.set()
        snapshot = token.snapshot()
        return _runtime_result(
            goal,
            kwargs["run_id"],
            status="cancelled",
            cancel_reason=snapshot["reason"],
            cancelled_at=snapshot["cancelled_at"],
        )

    monkeypatch.setattr(service_runtime_resume, "run_runtime_agent", cancellable_runtime_agent)
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    responses = []
    thread = _start_runtime_resume(
        config,
        ActiveRunRegistry(instance_id="replica-owner"),
        "pending-remote-token",
        responses,
    )
    assert worker_started.wait(timeout=1)
    child_path = _wait_for_child_trace(tmp_path, exclude={"pending-remote-token"})

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{child_path.stem}/cancel",
        b'{"reason":"remote resume stop"}',
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-remote"),
    )
    thread.join(timeout=2)

    assert cancel_status == 200
    assert cancel_payload["status"] == "cancelled"
    assert cancellation_observed.is_set()
    assert thread.is_alive() is False
    assert responses[0][0] == 200
    assert responses[0][1]["status"] == "cancelled"
    assert responses[0][1]["cancel_reason"] == "remote resume stop"
    persisted = load_trace_by_run_id(child_path.stem, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "remote resume stop"


def test_runtime_resume_remote_cancel_cannot_be_overwritten_by_failure(
    tmp_path,
    monkeypatch,
):
    _persist_pending_approval(tmp_path, run_id="pending-remote-race")
    worker_started = threading.Event()
    fail_worker = threading.Event()

    def late_failing_runtime_agent(*_args, **_kwargs):
        worker_started.set()
        assert fail_worker.wait(timeout=2)
        raise RuntimeError("worker failed after remote cancellation")

    monkeypatch.setattr(service_runtime_resume, "run_runtime_agent", late_failing_runtime_agent)
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    responses = []
    thread = _start_runtime_resume(
        config,
        ActiveRunRegistry(instance_id="replica-owner"),
        "pending-remote-race",
        responses,
    )
    assert worker_started.wait(timeout=1)
    child_path = _wait_for_child_trace(tmp_path, exclude={"pending-remote-race"})

    cancel_status, _ = service_router.handle_request(
        "POST",
        f"/runtime/runs/{child_path.stem}/cancel",
        b'{"reason":"remote cancellation won"}',
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-remote"),
    )
    fail_worker.set()
    thread.join(timeout=2)

    assert cancel_status == 200
    assert thread.is_alive() is False
    assert responses[0][0] == 500
    persisted = load_trace_by_run_id(child_path.stem, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["cancel_reason"] == "remote cancellation won"


def test_runtime_resume_remote_cancel_after_completion_returns_terminal_conflict(
    tmp_path,
    monkeypatch,
):
    _persist_pending_approval(tmp_path, run_id="pending-completes-first")
    monkeypatch.setattr(
        service_runtime_resume,
        "run_runtime_agent",
        lambda goal, **kwargs: _runtime_result(goal, kwargs["run_id"], status="done"),
    )
    config = ServiceConfig(trace_dir=str(tmp_path))
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"pending-completes-first","approved_action_ids":["step-1"]}',
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-owner"),
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{payload['run_id']}/cancel",
        b"{}",
        config=config,
        active_run_registry=ActiveRunRegistry(instance_id="replica-remote"),
    )

    assert status_code == 200
    assert cancel_status == 409
    assert cancel_payload["error"] == "runtime run is already terminal"
    persisted = load_trace_by_run_id(payload["run_id"], str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "done"


def test_runtime_trace_cancellation_probe_read_failure_is_fail_open(
    tmp_path,
    monkeypatch,
):
    worker_started = threading.Event()
    inspect_token = threading.Event()

    def runtime_agent_with_unreadable_probe(goal, **kwargs):
        worker_started.set()
        assert inspect_token.wait(timeout=2)
        assert kwargs["cancellation_token"].is_cancelled() is False
        return _runtime_result(goal, kwargs["run_id"], status="done")

    monkeypatch.setattr(
        service_runtime_run,
        "run_runtime_agent",
        runtime_agent_with_unreadable_probe,
    )
    config = ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=2)
    responses = []
    thread = _start_runtime_run(
        config,
        ActiveRunRegistry(instance_id="replica-owner"),
        responses,
    )
    assert worker_started.wait(timeout=1)
    trace_path = _wait_for_child_trace(tmp_path)
    trace_path.write_text("{not-json", encoding="utf-8")
    inspect_token.set()
    thread.join(timeout=2)

    assert thread.is_alive() is False
    assert responses[0][0] == 200
    assert responses[0][1]["status"] == "done"
    persisted = load_trace_by_run_id(trace_path.stem, str(tmp_path))
    assert persisted is not None
    assert persisted["status"] == "done"


def _start_runtime_run(config, registry, responses):
    thread = threading.Thread(
        target=lambda: responses.append(
            service_router.handle_request(
                "POST",
                "/runtime/run",
                b'{"goal":"distributed cancellation","plan":{"actions":[]}}',
                config=config,
                active_run_registry=registry,
            )
        )
    )
    thread.start()
    return thread


def _start_runtime_resume(config, registry, run_id, responses):
    body = json.dumps(
        {"run_id": run_id, "approved_action_ids": ["step-1"]}
    ).encode("utf-8")
    thread = threading.Thread(
        target=lambda: responses.append(
            service_router.handle_request(
                "POST",
                "/runtime/resume",
                body,
                config=config,
                active_run_registry=registry,
            )
        )
    )
    thread.start()
    return thread


def _persist_pending_approval(trace_dir: Path, *, run_id: str) -> None:
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": run_id,
            "status": "requires_approval",
            "goal": "resume distributed cancellation",
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
        str(trace_dir),
    )


def _runtime_result(goal, run_id, *, status, **extra):
    return {
        "trace_type": "codex_runtime",
        "run_id": run_id,
        "status": status,
        "goal": goal,
        "plan": {"actions": []},
        "plans": [],
        "events": [],
        "observations": [],
        **extra,
    }


def _wait_for_child_trace(trace_dir: Path, *, exclude=frozenset()) -> Path:
    trace_path = None

    def trace_exists():
        nonlocal trace_path
        paths = [path for path in trace_dir.glob("*.json") if path.stem not in exclude]
        if paths:
            trace_path = paths[0]
            return True
        return False

    _wait_until(trace_exists)
    assert trace_path is not None
    return trace_path


def _wait_until(predicate, *, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
