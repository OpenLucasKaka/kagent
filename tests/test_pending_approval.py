import io
import json
from pathlib import Path

import pytest

import kagent.cli.pending_approval as pending_approval_store
import kagent.cli.stdio_runtime as stdio_runtime_module
from kagent.cli.pending_approval import (
    clear_pending_approval,
    default_pending_approval_path,
    load_pending_approval,
    save_pending_approval,
)
from kagent.cli.stdio_runtime import (
    PendingApproval,
    StdioRuntimeSession,
    run_stdio_runtime,
)


def test_pending_approval_store_is_owner_only_and_atomic(tmp_path):
    path = tmp_path / "state" / "pending.json"
    payload = {
        "action": {"id": "step-1", "tool": "open_url", "input": {}},
        "goal": "open page",
        "runtime_goal": "open page",
        "plan": {"actions": []},
        "phase": "awaiting_approval",
        "allow_live_replan": True,
        "max_iterations": 3,
    }

    save_pending_approval(str(path), payload)

    assert load_pending_approval(str(path)) == payload
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    clear_pending_approval(str(path))
    assert not path.exists()


def test_default_pending_approval_path_uses_kagent_home_after_migration(
    tmp_path,
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        pending_approval_store,
        "migrate_legacy_kagent_state",
        lambda env: calls.append(env),
        raising=False,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {"HOME": str(tmp_path)}

    path = Path(default_pending_approval_path(env, workspace=workspace))

    assert path.parent == tmp_path / ".kagent" / "state" / "pending-approvals"
    assert path.suffix == ".json"
    assert calls == [env]


def test_default_pending_approval_path_explicit_override_skips_migration(
    tmp_path,
    monkeypatch,
):
    explicit = tmp_path / "pending.json"
    monkeypatch.setattr(
        pending_approval_store,
        "migrate_legacy_kagent_state",
        lambda env: (_ for _ in ()).throw(AssertionError("migration called")),
        raising=False,
    )

    assert default_pending_approval_path(
        {"KAGENT_PENDING_APPROVAL_PATH": str(explicit)}
    ) == str(explicit)


def test_pending_approval_store_rejects_symlink_paths(tmp_path):
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        save_pending_approval(
            str(linked_directory / "pending.json"),
            {
                "action": {"id": "step-1", "tool": "open_url", "input": {}},
                "goal": "open page",
                "runtime_goal": "open page",
                "plan": {"actions": []},
                "phase": "awaiting_approval",
            },
        )

    with pytest.raises(ValueError, match="must not contain symlinks"):
        load_pending_approval(str(linked_directory / "pending.json"))


def test_pending_approval_store_rejects_unknown_phase(tmp_path):
    path = tmp_path / "pending.json"

    with pytest.raises(ValueError, match="phase is invalid"):
        save_pending_approval(
            str(path),
            {
                "action": {"id": "step-1", "tool": "open_url", "input": {}},
                "goal": "open page",
                "runtime_goal": "open page",
                "plan": {"actions": []},
                "phase": "unknown",
            },
        )


def test_pending_approval_store_removes_expired_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "pending.json"
    monkeypatch.setattr(pending_approval_store.time, "time", lambda: 1_000.0)
    save_pending_approval(
        str(path),
        {
            "action": {"id": "step-1", "tool": "open_url", "input": {}},
            "goal": "open page",
            "runtime_goal": "open page",
            "plan": {"actions": []},
            "phase": "awaiting_approval",
        },
    )

    monkeypatch.setattr(
        pending_approval_store.time,
        "time",
        lambda: 1_000.0 + (24 * 60 * 60) + 1,
    )

    assert load_pending_approval(str(path)) is None
    assert not path.exists()


def test_stdio_runtime_does_not_replay_interrupted_approved_action(
    tmp_path,
    monkeypatch,
):
    pending_path = tmp_path / "pending-approval.json"
    monkeypatch.setenv("KAGENT_PENDING_APPROVAL_PATH", str(pending_path))
    save_pending_approval(
        str(pending_path),
        {
            "action": {
                "id": "step-1",
                "tool": "open_url",
                "input": {"url": "https://example.com"},
            },
            "goal": "open page",
            "runtime_goal": "open page",
            "plan": {"actions": []},
            "phase": "approved_executing",
        },
    )
    stdout = io.StringIO()

    run_stdio_runtime(io.StringIO(""), stdout)

    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert events[0]["type"] == "runtime_ready"
    assert events[0]["pending_approval"] is False
    assert events[0]["approval_execution_interrupted"] is True
    assert events[1] == {
        "type": "run_failed",
        "error_code": "approval_execution_interrupted",
        "message": (
            "The approved action was interrupted and was not replayed "
            "because its side-effect state is uncertain."
        ),
    }
    assert pending_path.exists()


def test_stdio_runtime_releases_in_memory_approval_after_worker_exception(
    tmp_path,
    monkeypatch,
):
    pending_path = tmp_path / "pending-approval.json"
    stdout = io.StringIO()
    session = StdioRuntimeSession(
        stdout,
        memory_path=str(tmp_path / "memory.json"),
        pending_approval_path=str(pending_path),
    )
    pending = PendingApproval(
        action={"id": "step-1", "tool": "open_url", "input": {}},
        goal="open page",
        runtime_goal="open page",
        plan={"actions": []},
        phase="approved_executing",
    )
    session.pending_approval = pending
    save_pending_approval(
        str(pending_path),
        {
            "action": pending.action,
            "goal": pending.goal,
            "runtime_goal": pending.runtime_goal,
            "plan": pending.plan,
            "phase": pending.phase,
        },
    )

    def raise_worker_error(*args, **kwargs):
        raise RuntimeError("worker crashed")

    monkeypatch.setattr(
        stdio_runtime_module,
        "run_runtime_agent",
        raise_worker_error,
    )

    session._start_active_run("open page", "open page")
    session.wait_until_idle()

    events = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["error_code"] == "approval_execution_interrupted"
    assert session.pending_approval is None
    assert pending_path.exists()


def test_stdio_runtime_recovers_pending_approval_after_process_restart(
    tmp_path,
    monkeypatch,
):
    memory_path = tmp_path / "session-memory.json"
    pending_path = tmp_path / "pending-approval.json"
    monkeypatch.setenv("KAGENT_SESSION_MEMORY_PATH", str(memory_path))
    monkeypatch.setenv("KAGENT_PENDING_APPROVAL_PATH", str(pending_path))
    run_request = {
        "type": "run_request",
        "goal": "fetch example",
        "runtime_plan": json.dumps(
            {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "http_request",
                        "input": {"url": "https://example.com"},
                        "reason": "fetch",
                    }
                ]
            }
        ),
    }
    first_stdout = io.StringIO()

    run_stdio_runtime(
        io.StringIO(json.dumps(run_request) + "\n"),
        first_stdout,
    )

    first_events = [json.loads(line) for line in first_stdout.getvalue().splitlines()]
    assert first_events[-1]["type"] == "approval_required"
    assert pending_path.exists()

    second_stdout = io.StringIO()
    run_stdio_runtime(
        io.StringIO(
            json.dumps(
                {
                    "type": "approval_response",
                    "action_id": "step-1",
                    "approved": False,
                }
            )
            + "\n"
        ),
        second_stdout,
    )

    second_events = [json.loads(line) for line in second_stdout.getvalue().splitlines()]
    assert [event["type"] for event in second_events[:2]] == [
        "runtime_ready",
        "approval_required",
    ]
    assert second_events[-1]["type"] == "run_completed"
    assert second_events[-1]["status"] == "cancelled"
    assert not pending_path.exists()
