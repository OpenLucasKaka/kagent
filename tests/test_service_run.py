import json
from concurrent.futures import TimeoutError as RunTimeoutError
from pathlib import Path

from self_correcting_langgraph_agent.service.run import execute_run_request
from self_correcting_langgraph_agent.service.runtime import ServiceConfig


def test_execute_run_request_returns_summary_and_persists_trace(tmp_path):
    def runner(goal, config):
        return {
            "run_id": "run-123",
            "goal": goal,
            "status": "done",
            "answer": "5",
            "events": [{"node": "planner"}],
            "tool_calls": [{"tool": "calculator"}],
            "verification_results": [],
            "plan": ["calculate"],
            "current_step": 1,
            "retry_count": 0,
            "errors": [],
            "max_steps": config.max_steps,
        }

    status_code, payload = execute_run_request(
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        ServiceConfig(trace_dir=str(tmp_path)),
        agent_runner=runner,
    )

    trace_path = Path(payload["trace_path"])
    trace_payload = json.loads(trace_path.read_text())

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["answer"] == "5"
    assert payload["tool_names"] == ["calculator"]
    assert trace_path.parent == tmp_path
    assert trace_payload["run_id"] == "run-123"


def test_execute_run_request_rejects_full_trace_response_when_disabled():
    calls = []

    def runner(goal, config):
        calls.append(goal)
        return {
            "run_id": "run-123",
            "status": "done",
            "answer": "5",
            "events": [{"node": "planner", "message": "internal reasoning"}],
        }

    status_code, payload = execute_run_request(
        json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
        ServiceConfig(allow_full_trace_response=False),
        agent_runner=runner,
    )

    assert status_code == 403
    assert payload == {
        "status": "failed",
        "error_code": "full_trace_disabled",
        "error": "full_trace responses are disabled",
    }
    assert calls == []


def test_execute_run_request_can_return_full_trace_response_when_enabled():
    def runner(goal, config):
        return {
            "run_id": "run-123",
            "status": "done",
            "answer": "5",
            "events": [{"node": "planner", "message": "internal reasoning"}],
        }

    status_code, payload = execute_run_request(
        json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
        ServiceConfig(allow_full_trace_response=True),
        agent_runner=runner,
    )

    assert status_code == 200
    assert payload["events"] == [{"node": "planner", "message": "internal reasoning"}]


def test_execute_run_request_failure_responses_include_stable_error_codes(monkeypatch):
    def failing_runner(goal, config):
        raise RuntimeError("boom")

    def done_runner(goal, config):
        return {"run_id": "run-123", "status": "done", "events": []}

    def failing_persist_trace(trace, trace_dir):
        raise OSError("disk full")

    monkeypatch.setattr(
        "self_correcting_langgraph_agent.service.run.persist_trace",
        failing_persist_trace,
    )

    cases = [
        (
            "invalid_json",
            execute_run_request(b"{not-json}", ServiceConfig(), agent_runner=done_runner),
        ),
        (
            "invalid_request_body",
            execute_run_request(b"[]", ServiceConfig(), agent_runner=done_runner),
        ),
        (
            "missing_goal",
            execute_run_request(b"{}", ServiceConfig(), agent_runner=done_runner),
        ),
        (
            "invalid_agent_config",
            execute_run_request(
                json.dumps({"goal": "calculate 2 + 3", "max_steps": 0}).encode("utf-8"),
                ServiceConfig(),
                agent_runner=done_runner,
            ),
        ),
        (
            "agent_run_failed",
            execute_run_request(
                json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
                ServiceConfig(),
                agent_runner=failing_runner,
            ),
        ),
        (
            "trace_persistence_failed",
            execute_run_request(
                json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
                ServiceConfig(trace_dir="/tmp/traces"),
                agent_runner=done_runner,
            ),
        ),
    ]

    for expected_error_code, (status_code, payload) in cases:
        assert status_code >= 400
        assert payload["status"] == "failed"
        assert payload["error_code"] == expected_error_code
        assert payload["error"]


def test_execute_run_request_timeout_response_includes_stable_error_code(monkeypatch):
    def timeout_run(call, *, timeout_seconds):
        raise RunTimeoutError

    monkeypatch.setattr(
        "self_correcting_langgraph_agent.service.run.run_with_timeout",
        timeout_run,
    )

    status_code, payload = execute_run_request(
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        ServiceConfig(),
        agent_runner=lambda goal, config: {"status": "done"},
    )

    assert status_code == 504
    assert payload["error_code"] == "agent_run_timeout"


def test_execute_run_request_rejects_non_integer_run_config_values():
    calls = []

    def runner(goal, config):
        calls.append((goal, config))
        return {"run_id": "run-123", "status": "done", "events": []}

    cases = [
        {"goal": "calculate 2 + 3", "max_steps": 2.5},
        {"goal": "calculate 2 + 3", "max_steps": True},
        {"goal": "calculate 2 + 3", "max_steps": "2"},
        {"goal": "calculate 2 + 3", "max_retries": False},
    ]

    for body in cases:
        status_code, payload = execute_run_request(
            json.dumps(body).encode("utf-8"),
            ServiceConfig(),
            agent_runner=runner,
        )

        assert status_code == 400
        assert payload["status"] == "failed"
        assert payload["error_code"] == "invalid_agent_config"
        assert "must be an integer" in payload["error"]

    assert calls == []


def test_execute_run_request_rejects_non_boolean_full_trace_value():
    calls = []

    def runner(goal, config):
        calls.append((goal, config))
        return {"run_id": "run-123", "status": "done", "events": []}

    status_code, payload = execute_run_request(
        json.dumps({"goal": "calculate 2 + 3", "full_trace": "true"}).encode("utf-8"),
        ServiceConfig(),
        agent_runner=runner,
    )

    assert status_code == 400
    assert payload == {
        "status": "failed",
        "error_code": "invalid_request_body",
        "error": "full_trace must be a boolean",
    }
    assert calls == []


def test_execute_run_request_rejects_goal_that_exceeds_configured_limit():
    calls = []

    def runner(goal, config):
        calls.append((goal, config))
        return {"run_id": "run-123", "status": "done", "events": []}

    status_code, payload = execute_run_request(
        json.dumps({"goal": "abcdef"}).encode("utf-8"),
        ServiceConfig(max_goal_chars=5),
        agent_runner=runner,
    )

    assert status_code == 413
    assert payload == {
        "status": "failed",
        "error_code": "goal_too_large",
        "error": "goal exceeds max_goal_chars",
    }
    assert calls == []
