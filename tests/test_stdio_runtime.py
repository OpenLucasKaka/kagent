import io
import json
import os
import subprocess

from kagent.cli import stdio_runtime


def _jsonl(stdout: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def _runtime_env(tmp_path):
    return {
        **os.environ,
        "KAGENT_SESSION_MEMORY_PATH": str(tmp_path / "session-memory.json"),
    }


def test_stdio_runtime_accepts_run_request_and_streams_jsonl_events(tmp_path):
    request = {
        "type": "run_request",
        "goal": "capture hello",
        "max_iterations": 2,
        "runtime_plan": json.dumps(
            {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "hello from stdio"},
                        "reason": "exercise the stdio protocol",
                    }
                ],
                "final_answer": "stdio done",
            }
        ),
    }

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
        env=_runtime_env(tmp_path),
    )

    events = _jsonl(completed.stdout)
    assert completed.stderr == ""
    assert events[0] == {"type": "runtime_ready"}
    assert [event["type"] for event in events][1:3] == [
        "run_started",
        "run_progress",
    ]
    assert events[-1]["type"] == "run_completed"
    assert events[-1]["status"] == "done"
    assert events[-1]["answer"] == "stdio done"
    assert events[-1]["payload"]["goal"] == "capture hello"


def test_stdio_runtime_reports_malformed_json_as_structured_error(tmp_path):
    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input="{not json}\n",
        capture_output=True,
        text=True,
        check=False,
        env=_runtime_env(tmp_path),
    )

    events = _jsonl(completed.stdout)
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["error_code"] == "invalid_json"


def test_stdio_runtime_reports_invalid_iteration_budget_without_crashing(tmp_path):
    request = {
        "type": "run_request",
        "goal": "invalid budget",
        "max_iterations": 0,
    }

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
        env=_runtime_env(tmp_path),
    )

    events = _jsonl(completed.stdout)
    assert events[0] == {"type": "runtime_ready"}
    assert events[1:] == [
        {
            "type": "run_failed",
            "error_code": "invalid_request",
            "message": "max_iterations must be at least 1",
        }
    ]
    assert "Traceback" not in completed.stdout
    assert completed.stderr == ""


def test_stdio_runtime_reports_missing_provider_as_structured_error(tmp_path):
    env = {
        "KAGENT_LLM_CONFIG_PATH": str(tmp_path / "missing-provider.json"),
        "KAGENT_SESSION_MEMORY_PATH": str(tmp_path / "session-memory.json"),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": "src",
    }
    request = {"type": "run_request", "goal": "needs provider"}

    completed = subprocess.run(
        [".venv/bin/python", "-m", "kagent.cli.stdio_runtime"],
        input=f"{json.dumps(request)}\n",
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )

    events = _jsonl(completed.stdout)
    assert events[0]["type"] == "runtime_ready"
    assert events[1]["type"] == "run_started"
    assert events[-1]["type"] == "run_failed"
    assert events[-1]["error_code"] == "provider_not_configured"
    assert "KAGENT_LLM_BASE_URL" in events[-1]["message"]


def test_stdio_runtime_reports_session_initialization_failure(monkeypatch, tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"turns": []}\n', encoding="utf-8")
    memory_path = tmp_path / "memory-link.json"
    memory_path.symlink_to(target)
    monkeypatch.setenv("KAGENT_SESSION_MEMORY_PATH", str(memory_path))
    stdout = io.StringIO()

    stdio_runtime.run_stdio_runtime(io.StringIO(""), stdout)

    events = _jsonl(stdout.getvalue())
    assert events[-1]["type"] == "runtime_unavailable"
    assert "symlink" in events[-1]["message"]


def test_stdio_runtime_reuses_and_persists_conversation_memory(monkeypatch, tmp_path):
    memory_path = tmp_path / "session-memory.json"
    monkeypatch.setenv("KAGENT_SESSION_MEMORY_PATH", str(memory_path))
    goals = []

    def fake_run_runtime_agent(goal, **_kwargs):
        goals.append(goal)
        return {
            "status": "done",
            "answer": f"answer-{len(goals)}",
            "goal": goal,
        }

    monkeypatch.setattr(stdio_runtime, "run_runtime_agent", fake_run_runtime_agent)
    requests = [
        {"type": "run_request", "goal": "Call me kaka", "runtime_plan": "{}"},
        {"type": "run_request", "goal": "Who am I?", "runtime_plan": "{}"},
    ]
    stdin = io.StringIO("".join(f"{json.dumps(item)}\n" for item in requests))
    stdout = io.StringIO()

    stdio_runtime.run_stdio_runtime(stdin, stdout)

    assert goals[0] == "Call me kaka"
    assert "User: Call me kaka" in goals[1]
    assert "Assistant: answer-1" in goals[1]
    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved["turns"][-1] == {"user": "Who am I?", "assistant": "answer-2"}
    assert memory_path.stat().st_mode & 0o777 == 0o600


def test_stdio_runtime_resumes_only_the_approved_pending_action(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "KAGENT_SESSION_MEMORY_PATH",
        str(tmp_path / "session-memory.json"),
    )
    calls = []
    pending_action = {
        "id": "open-github",
        "tool": "open_url",
        "input": {"url": "https://github.com"},
        "reason": "open the requested page",
    }

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append((goal, kwargs))
        if len(calls) == 1:
            return {
                "status": "requires_approval",
                "goal": goal,
                "plan": {"actions": [pending_action], "final_answer": "opened"},
                "pending_approval": pending_action,
            }
        return {"status": "done", "answer": "opened", "goal": goal}

    monkeypatch.setattr(stdio_runtime, "run_runtime_agent", fake_run_runtime_agent)
    requests = [
        {"type": "run_request", "goal": "Open GitHub", "runtime_plan": "{}"},
        {
            "type": "approval_response",
            "action_id": "open-github",
            "approved": True,
        },
    ]
    stdin = io.StringIO("".join(f"{json.dumps(item)}\n" for item in requests))
    stdout = io.StringIO()

    stdio_runtime.run_stdio_runtime(stdin, stdout)

    events = _jsonl(stdout.getvalue())
    approval = next(event for event in events if event["type"] == "approval_required")
    assert "tool" not in approval
    assert approval["title"] == "Open a website"
    assert approval["target"] == "https://github.com"
    assert len(calls) == 2
    assert calls[1][1]["approved_action_ids"] == {"open-github"}
    assert events[-1]["type"] == "run_completed"
    assert events[-1]["status"] == "done"


def test_stdio_runtime_rejection_never_executes_pending_action(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "KAGENT_SESSION_MEMORY_PATH",
        str(tmp_path / "session-memory.json"),
    )
    calls = []
    pending_action = {
        "id": "open-github",
        "tool": "open_url",
        "input": {"url": "https://github.com"},
        "reason": "open the requested page",
    }

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append((goal, kwargs))
        return {
            "status": "requires_approval",
            "goal": goal,
            "plan": {"actions": [pending_action]},
            "pending_approval": pending_action,
        }

    monkeypatch.setattr(stdio_runtime, "run_runtime_agent", fake_run_runtime_agent)
    requests = [
        {"type": "run_request", "goal": "Open GitHub", "runtime_plan": "{}"},
        {
            "type": "approval_response",
            "action_id": "open-github",
            "approved": False,
        },
    ]
    stdin = io.StringIO("".join(f"{json.dumps(item)}\n" for item in requests))
    stdout = io.StringIO()

    stdio_runtime.run_stdio_runtime(stdin, stdout)

    events = _jsonl(stdout.getvalue())
    assert len(calls) == 1
    assert events[-1]["type"] == "run_completed"
    assert events[-1]["status"] == "cancelled"
    assert "not performed" in events[-1]["answer"]
