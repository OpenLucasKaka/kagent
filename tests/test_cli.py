import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_entrypoint_is_delegated_to_cli_main_module():
    from self_correcting_langgraph_agent import cli

    cli_main = importlib.import_module("self_correcting_langgraph_agent.cli.main")

    assert cli.main is cli_main.main


def test_cli_runs_goal_and_prints_json_trace():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "5"
    assert payload["events"][0]["node"] == "planner"


def test_cli_can_demonstrate_self_correction_with_fault_injection():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--inject-wrong-answer",
            "calculate 2 + 3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "5"
    assert payload["retry_count"] == 1
    assert [event["node"] for event in payload["events"]] == [
        "planner",
        "executor",
        "verifier",
        "reflector",
        "executor",
        "verifier",
    ]


def test_cli_accepts_generic_fault_injection():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "uppercase text in 'agent loop'",
            "--inject-fault",
            "uppercase text in 'agent loop'=empty-answer",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "AGENT LOOP"
    assert payload["reflections"][-1]["actual"] == ""


def test_cli_fault_injection_preserves_quoted_text_case_when_matching():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "Uppercase Text in 'Agent Loop'",
            "--inject-fault",
            "Uppercase Text in 'Agent Loop'=empty-answer",
            "--summary",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["retry_count"] == "1"
    assert payload["faults"] == ["empty-answer"]


def test_cli_lists_registered_tools():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--list-tools",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload == {
        "tools": [
            "calculate_sum",
            "count_words",
            "lowercase_text",
            "multiply_numbers",
            "reverse_text",
            "subtract_numbers",
            "trim_text",
            "uppercase_text",
        ]
    }


def test_cli_lists_verbose_tool_metadata():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--list-tools",
            "--verbose",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["tools"][0] == {
        "name": "calculate_sum",
        "command": "calculate N + M",
        "description": "Add two integers.",
        "example": "calculate 2 + 3",
    }
    assert payload["tools"][-1]["name"] == "uppercase_text"


def test_cli_lists_runtime_tool_metadata_when_runtime_mode_is_enabled():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--runtime",
            "--list-tools",
            "--verbose",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    by_name = {item["name"]: item for item in payload["tools"]}

    assert completed.stderr == ""
    assert "read_file" in by_name
    assert "list_files" in by_name
    assert by_name["apply_patch"]["approval_required_by_default"] == "false"
    assert by_name["apply_patch"]["input_schema"]["required"] == ["patch"]
    assert by_name["apply_patch"]["output_schema"]["required"] == [
        "changed_files",
        "file_count",
    ]
    assert by_name["artifact"]["approval_required_by_default"] == "false"
    assert by_name["artifact"]["output_schema"]["required"] == [
        "artifact_id",
        "title",
        "kind",
        "format",
        "content",
        "tags",
        "bytes",
    ]
    assert by_name["http_request"]["approval_required_by_default"] == "true"
    assert by_name["http_request"]["input_schema"]["required"] == ["url"]
    assert by_name["http_request"]["output_schema"]["required"] == [
        "url",
        "status_code",
        "content_type",
        "body_text",
        "bytes",
        "truncated",
    ]
    assert by_name["list_files"]["approval_required_by_default"] == "false"
    assert by_name["list_files"]["output_schema"]["required"] == [
        "root",
        "entries",
        "file_count",
        "truncated",
    ]
    assert by_name["open_url"]["approval_required_by_default"] == "false"
    assert by_name["open_url"]["input_schema"]["required"] == ["url"]
    assert by_name["open_url"]["output_schema"]["required"] == [
        "url",
        "opened",
        "application",
        "command",
    ]
    assert by_name["read_file"]["approval_required_by_default"] == "false"
    assert by_name["read_file"]["input_schema"]["required"] == ["path"]
    assert by_name["read_file"]["output_schema"]["required"] == [
        "path",
        "content",
        "bytes",
        "truncated",
        "sha256",
    ]
    assert by_name["rubric_score"]["input_schema"]["required"] == ["criteria"]
    assert by_name["rubric_score"]["output_schema"]["required"] == [
        "criteria",
        "passed",
        "failed",
        "total",
        "score_percent",
        "blocking_failures",
        "failed_criteria",
    ]


def test_cli_lists_supported_faults():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--list-faults",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload == {"faults": ["empty-answer", "tool-error", "wrong-answer"]}


def test_cli_can_print_graph_topology_without_goal():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--graph",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload == {
        "nodes": ["planner", "executor", "verifier", "reflector"],
        "edges": [
            "planner -> executor",
            "executor -> verifier",
            "verifier -> reflector",
            "reflector -> executor",
            "verifier -> executor",
            "verifier -> END",
            "planner -> END",
        ],
    }


def test_cli_can_print_package_version_without_goal():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--version",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload == {"version": "0.1.0"}


def test_cli_output_file_also_applies_to_introspection_commands(tmp_path):
    output_path = tmp_path / "version.json"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--version",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stderr == ""
    assert json.loads(output_path.read_text()) == json.loads(completed.stdout)


def test_cli_can_preview_plan_without_execution():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3 then subtract 10 - 4",
            "--plan",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "ready"
    assert payload["plan"] == ["calculate 2 + 3", "subtract 10 - 4"]
    assert payload["plan_validations"][-1]["tool"] == "subtract_numbers"
    assert "events" not in payload


def test_cli_uses_environment_config_defaults_when_flags_are_omitted():
    env = os.environ.copy()
    env["SELF_CORRECTING_MAX_STEPS"] = "1"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 1 + 1 then calculate 2 + 2",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "failed"
    assert payload["config"]["max_steps"] == 1
    assert payload["errors"] == ["planned steps exceed max_steps"]


def test_cli_flags_override_environment_config_defaults():
    env = os.environ.copy()
    env["SELF_CORRECTING_MAX_STEPS"] = "1"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 1 + 1 then calculate 2 + 2",
            "--max-steps",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["config"]["max_steps"] == 2


def test_cli_reports_invalid_environment_config_without_traceback():
    env = os.environ.copy()
    env["SELF_CORRECTING_MAX_STEPS"] = "many"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "SELF_CORRECTING_MAX_STEPS must be an integer" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_can_exit_nonzero_when_agent_run_fails():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 1 + 1 then search the web",
            "--fail-on-agent-failure",
        ],
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert completed.stderr == ""
    assert payload["status"] == "failed"
    assert payload["errors"] == ["unsupported planned step: search the web"]


def test_cli_can_write_json_payload_to_output_file(tmp_path):
    output_path = tmp_path / "trace.json"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--summary",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output_path.read_text())

    assert completed.stderr == ""
    assert stdout_payload == file_payload
    assert file_payload["status"] == "done"


def test_cli_can_run_codex_style_runtime_with_inline_plan():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "score readiness",
            "--runtime",
            "--runtime-plan",
            (
                '{"actions":[{"id":"step-1","tool":"rubric_score",'
                '"input":{"criteria":[{"name":"Runnable","passed":true}]},'
                '"reason":"score"}],"final_answer":"ready"}'
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["trace_type"] == "codex_runtime"
    assert payload["status"] == "done"
    assert payload["answer"] == "ready"
    assert payload["observations"][0]["output"]["score_percent"] == 100.0


def test_cli_runtime_accepts_non_secret_metadata_and_tags():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "score readiness",
            "--runtime",
            "--runtime-plan",
            (
                '{"actions":[{"id":"step-1","tool":"note",'
                '"input":{"text":"ready"},"reason":"capture"}],'
                '"final_answer":"ready"}'
            ),
            "--tag",
            "release",
            "--tag",
            "ops",
            "--tag",
            "release",
            "--metadata",
            "workflow=launch",
            "--metadata",
            "ticket=REL-123",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["metadata"] == {"ticket": "REL-123", "workflow": "launch"}
    assert payload["tags"] == ["ops", "release"]


def test_cli_runtime_can_persist_trace_to_trace_dir(tmp_path):
    trace_dir = tmp_path / "runtime-traces"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "score readiness",
            "--runtime",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
            "--trace-dir",
            str(trace_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    trace_path = Path(payload["trace_path"])
    trace_payload = json.loads(trace_path.read_text())

    assert completed.stderr == ""
    assert trace_path.parent == trace_dir
    assert trace_path.name == f"{payload['run_id']}.json"
    assert trace_payload == payload


def test_cli_runtime_trace_persistence_writes_once():
    from self_correcting_langgraph_agent.cli.main import _persist_runtime_cli_trace

    calls = []
    payload = {"run_id": "run-123", "status": "done"}

    def persist_trace(trace, trace_dir):
        calls.append({"trace": dict(trace), "trace_dir": trace_dir})
        return "/tmp/traces/run-123.json"

    _persist_runtime_cli_trace(payload, "/tmp/traces", persist_trace)

    assert payload["trace_path"] == "/tmp/traces/run-123.json"
    assert calls == [
        {
            "trace": {
                "run_id": "run-123",
                "status": "done",
                "trace_path": "/tmp/traces/run-123.json",
            },
            "trace_dir": "/tmp/traces",
        }
    ]


def test_cli_interactive_runtime_can_persist_trace_to_trace_dir(tmp_path):
    trace_dir = tmp_path / "interactive-traces"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--runtime",
            "--interactive",
            "--max-iterations",
            "1",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
            "--trace-dir",
            str(trace_dir),
        ],
        input="score readiness\nexit\n",
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    trace_path = Path(payload["trace_path"])
    trace_payload = json.loads(trace_path.read_text())

    assert completed.stderr == ""
    assert trace_path.parent == trace_dir
    assert trace_payload == payload


def test_cli_interactive_runtime_trace_dir_failure_has_no_traceback(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace dir")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--runtime",
            "--interactive",
            "--max-iterations",
            "1",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
            "--trace-dir",
            str(blocking_file),
        ],
        input="score readiness\nexit\n",
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "could not persist --trace-dir trace" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_runtime_rejects_secret_like_metadata_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "score readiness",
            "--runtime",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
            "--metadata",
            "api_key=secret",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "metadata" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_interactive_runtime_runs_goals_from_stdin_with_inline_plan(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    completed = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--runtime",
            "--interactive",
            "--max-iterations",
            "1",
            "--runtime-plan",
            (
                '{"actions":[{"id":"step-1","tool":"apply_patch",'
                '"input":{"patch":"*** Begin Patch\\n*** Add File: docs/hello.md\\n'
                '+# Hello\\n+\\n+created by agent\\n*** End Patch\\n"},'
                '"reason":"create file"}],"final_answer":"created"}'
            ),
        ],
        input="创建 docs/hello.md\nexit\n",
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "created"
    assert payload["observations"][0]["tool"] == "apply_patch"
    assert (tmp_path / "docs" / "hello.md").read_text(encoding="utf-8") == (
        "# Hello\n\ncreated by agent\n"
    )


def test_cli_interactive_runtime_can_update_file_with_inline_plan(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    target = tmp_path / "plan.md"
    target.write_text("# Plan\n\nstatus: draft\n", encoding="utf-8")

    completed = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            "-m",
            "self_correcting_langgraph_agent.cli",
            "--runtime",
            "--interactive",
            "--max-iterations",
            "1",
            "--runtime-plan",
            (
                '{"actions":[{"id":"step-1","tool":"apply_patch",'
                '"input":{"patch":"*** Begin Patch\\n*** Update File: plan.md\\n'
                '@@\\n # Plan\\n \\n-status: draft\\n+status: ready\\n'
                '*** End Patch\\n"},'
                '"reason":"update file"}],"final_answer":"updated"}'
            ),
        ],
        input="把 plan.md 状态改成 ready\nexit\n",
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "updated"
    assert payload["observations"][0]["tool"] == "apply_patch"
    assert payload["observations"][0]["output"]["changed_files"][0]["operation"] == "update"
    assert target.read_text(encoding="utf-8") == "# Plan\n\nstatus: ready\n"


def test_cli_interactive_runtime_prints_prompt_to_real_stderr(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {"status": "done"},
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "› " in captured.out
    assert "self-correcting agent ready" in captured.err
    assert "/help" in captured.err


def test_cli_interactive_runtime_tty_prints_production_summary(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    def fake_run_runtime_agent(_goal, **_kwargs):
        return {
            "status": "done",
            "run_id": "run-123",
            "duration_seconds": "0.1200",
            "answer": "已打开 GitHub。",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "open_url",
                    "status": "ok",
                    "duration_seconds": "0.0300",
                    "output": {
                        "application": "Google Chrome",
                        "command": "osascript Google Chrome",
                        "opened": True,
                        "url": "https://github.com",
                    },
                }
            ],
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "╭─ ✓ done" in captured.out
    assert "✓ done" in captured.out
    assert "done" in captured.out
    assert "0.1200s" in captured.out
    assert "已打开 GitHub。" in captured.out
    assert "├─ tools" in captured.out
    assert "open_url" in captured.out
    assert "0.0300s" in captured.out
    assert "Google Chrome" in captured.out
    assert "opened" in captured.out
    assert "url=" not in captured.out
    assert "opened=True" not in captured.out
    assert "run-123" not in captured.out
    assert "Tools" not in captured.out
    assert "assistant" not in captured.out
    assert "status" not in captured.out
    assert "tool calls" not in captured.out
    assert "step-1" not in captured.out
    assert "== Run ==" not in captured.out
    assert '"observations"' not in captured.out


def test_cli_interactive_runtime_tty_prints_live_progress(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["创建文件\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    def fake_run_runtime_agent(_goal, **kwargs):
        event_sink = kwargs["event_sink"]
        event_sink({"type": "planner_started", "iteration": "1"})
        event_sink(
            {
                "type": "planner_completed",
                "action_count": "1",
                "duration_seconds": "0.2000",
            }
        )
        event_sink({"type": "tool_started", "tool": "apply_patch"})
        event_sink(
            {
                "type": "tool_completed",
                "tool": "apply_patch",
                "status": "ok",
                "duration_seconds": "0.0100",
            }
        )
        return {
            "status": "done",
            "answer": "文件已创建。",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "apply_patch",
                    "status": "ok",
                    "output": {
                        "changed_files": [
                            {
                                "path": "hello.md",
                                "operation": "add",
                                "bytes": 13,
                                "sha256": "a" * 64,
                            }
                        ],
                        "file_count": 1,
                    },
                }
            ],
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "thinking iter 1..." in captured.out
    assert "planned 1 action(s) 0.2000s" in captured.out
    assert "running apply_patch..." in captured.out
    assert "✓ apply_patch  0.0100s" in captured.out
    assert "文件已创建。" in captured.out
    assert "add hello.md 13B" in captured.out


def test_cli_interactive_runtime_tty_can_toggle_json_output(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/json\n", "inspect\n", "/compact\n", "inspect again\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "observations": [{"action_id": "step-1", "tool": "note", "status": "ok"}],
        },
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "output mode: full JSON" in captured.out
    assert '"observations"' in captured.out
    assert "output mode: compact" in captured.out
    assert "✓ done" in captured.out


def test_cli_interactive_runtime_collapses_repeated_tool_observations(
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我是谁\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    duplicate_observations = [
        {
            "action_id": "step-1",
            "tool": "note",
            "status": "ok",
            "duration_seconds": "0.0003",
            "output": {"text": "用户询问身份。"},
        },
        {
            "action_id": "step-1",
            "tool": "note",
            "status": "ok",
            "duration_seconds": "0.0002",
            "output": {"text": "用户询问身份。"},
        },
        {
            "action_id": "step-1",
            "tool": "note",
            "status": "ok",
            "duration_seconds": "0.0002",
            "output": {"text": "用户询问身份。"},
        },
    ]

    non_note_observations = [
        {
            "action_id": "step-2",
            "tool": "open_url",
            "status": "ok",
            "duration_seconds": "0.0100",
            "output": {"url": "https://github.com", "application": "Google Chrome"},
        }
    ]

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "answer": "你是 kaka。",
            "observations": duplicate_observations + non_note_observations,
        },
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "note" not in captured.out
    assert "用户询问身份" not in captured.out
    assert "open_url" in captured.out


def test_cli_interactive_runtime_hides_note_only_activity(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我试试\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    note_observation = {
        "action_id": "step-1",
        "tool": "note",
        "status": "ok",
        "duration_seconds": "0.0003",
        "output": {"text": "用户说“我试试”，等待进一步指示。"},
    }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "answer": "已记录，等你下一步指令。",
            "observations": [note_observation],
        },
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "已记录，等你下一步指令。" in captured.out
    assert "tool calls" not in captured.out
    assert "用户说" not in captured.out


def test_cli_interactive_runtime_tty_keeps_debug_details_out_of_default_output(
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["创建文件\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    payload = {
        "status": "done",
        "run_id": "private-run-id",
        "duration_seconds": "1.2500",
        "iteration_count": "2",
        "max_iterations": "3",
        "answer": "文件已创建。",
        "events": [{"node": "planner", "status": "ok"}],
        "plans": [{"actions": [{"id": "step-1", "tool": "note"}]}],
        "observations": [
            {
                "action_id": "step-1",
                "tool": "note",
                "status": "ok",
                "output": {"text": "内部规划细节"},
            },
            {
                "action_id": "step-2",
                "tool": "apply_patch",
                "status": "ok",
                "duration_seconds": "0.0200",
                "output": {"changed_files": ["hello.md"], "file_count": 1},
            },
        ],
    }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: payload,
        max_iterations=3,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "╭─ ✓ done" in captured.out
    assert "文件已创建。" in captured.out
    assert "status" not in captured.out
    assert "✓ done" in captured.out
    assert "├─ tools" in captured.out
    assert "apply_patch" in captured.out
    assert "hello.md" in captured.out
    assert "private-run-id" not in captured.out
    assert "step-1" not in captured.out
    assert "step-2" not in captured.out
    assert "内部规划细节" not in captured.out
    assert "events" not in captured.out
    assert "plans" not in captured.out


def test_cli_interactive_runtime_can_show_and_clear_session_memory(
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我是卡卡\n", "/memory\n", "/clear\n", "/memory\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "answer": "你好，卡卡。",
        },
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert "memory" in captured.out
    assert "user   我是卡卡" in captured.out
    assert "agent  你好，卡卡。" in captured.out
    assert "memory cleared" in captured.out
    assert "memory is empty." in captured.out


def test_cli_interactive_runtime_carries_session_memory_between_turns(
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我是卡卡\n", "我是谁\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        return {
            "status": "done",
            "answer": "你好，卡卡。" if len(calls) == 1 else "你是卡卡。",
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    assert calls[0] == "我是卡卡"
    assert "Conversation memory from this interactive session" in calls[1]
    assert "User: 我是卡卡" in calls[1]
    assert "Assistant: 你好，卡卡。" in calls[1]
    assert "Current user message:\n我是谁" in calls[1]
    captured = capsys.readouterr()
    assert "你是卡卡。" in captured.out


def test_cli_interactive_runtime_persists_session_memory_between_shells(
    tmp_path,
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    memory_path = tmp_path / "agent-memory.json"

    class FirstTTYInput:
        def __init__(self):
            self.lines = ["我是卡卡\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FirstTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "answer": "你好，卡卡。",
        },
        max_iterations=1,
        fail_on_agent_failure=False,
        session_memory_path=str(memory_path),
    )

    saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved_memory["schema_version"] == "1"
    assert saved_memory["turns"] == [
        {"user": "我是卡卡", "assistant": "你好，卡卡。"}
    ]
    assert memory_path.stat().st_mode & 0o777 == 0o600

    class SecondTTYInput:
        def __init__(self):
            self.lines = ["我是谁\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        return {"status": "done", "answer": "你是卡卡。"}

    monkeypatch.setattr(sys, "stdin", SecondTTYInput())

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
        session_memory_path=str(memory_path),
    )

    assert "Conversation memory from this interactive session" in calls[0]
    assert "User: 我是卡卡" in calls[0]
    assert "Assistant: 你好，卡卡。" in calls[0]
    assert "Current user message:\n我是谁" in calls[0]
    captured = capsys.readouterr()
    assert "你是卡卡。" in captured.out


def test_cli_interactive_runtime_clear_persists_empty_session_memory(
    tmp_path,
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    memory_path = tmp_path / "agent-memory.json"
    memory_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "旧", "assistant": "旧"}]}),
        encoding="utf-8",
    )

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/clear\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {"status": "done"},
        max_iterations=1,
        fail_on_agent_failure=False,
        session_memory_path=str(memory_path),
    )

    saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
    assert saved_memory["turns"] == []
    captured = capsys.readouterr()
    assert "memory cleared" in captured.out


def test_cli_session_memory_requires_interactive_runtime():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "capture hello",
            "--runtime",
            "--session-memory",
            "/tmp/agent-memory.json",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--session-memory requires --interactive" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_interactive_runtime_passes_metadata_and_tags_to_each_run(
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["inspect\n", "inspect again\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(_goal, **kwargs):
        calls.append(kwargs)
        return {"status": "done", "answer": "ok"}

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
        metadata={"workflow": "launch"},
        tags=["ops"],
    )

    assert [call["metadata"] for call in calls] == [
        {"workflow": "launch"},
        {"workflow": "launch"},
    ]
    assert [call["tags"] for call in calls] == [["ops"], ["ops"]]
    captured = capsys.readouterr()
    assert "ok" in captured.out


def test_cli_interactive_runtime_can_still_print_full_json(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "observations": [{"action_id": "step-1", "tool": "note", "status": "ok"}],
        },
        max_iterations=1,
        fail_on_agent_failure=False,
        full_trace_output=True,
    )

    captured = capsys.readouterr()
    assert '"status": "done"' in captured.out
    assert '"observations"' in captured.out


def test_cli_interactive_runtime_can_show_last_compact_result(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "/last\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    calls = []

    def fake_run_runtime_agent(_goal, **_kwargs):
        calls.append(None)
        return {
            "status": "done",
            "answer": "已打开 GitHub。",
            "duration_seconds": "0.1200",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "open_url",
                    "status": "ok",
                    "output": {"url": "https://github.com"},
                }
            ],
        }

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert len(calls) == 1
    assert captured.out.count("已打开 GitHub。") == 2
    assert captured.out.count("open_url") == 2
    assert '"observations"' not in captured.out


def test_cli_interactive_runtime_can_show_last_full_trace_once(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["inspect\n", "/trace\n", "inspect again\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(_goal, **_kwargs):
        calls.append(None)
        return {
            "status": "done",
            "run_id": f"run-{len(calls)}",
            "answer": f"answer {len(calls)}",
            "observations": [
                {"action_id": "step-1", "tool": "note", "status": "ok"}
            ],
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert len(calls) == 2
    assert '"run_id": "run-1"' in captured.out
    assert '"observations"' in captured.out
    assert "answer 2" in captured.out
    assert '"run_id": "run-2"' not in captured.out


def test_cli_interactive_runtime_trace_dir_updates_last_trace(
    tmp_path,
    monkeypatch,
    capsys,
):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive
    from self_correcting_langgraph_agent.service.trace_store import persist_trace

    trace_dir = tmp_path / "interactive-traces"

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["inspect\n", "/trace\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "run_id": "run-123",
            "answer": "ready",
            "observations": [],
        },
        max_iterations=1,
        fail_on_agent_failure=False,
        trace_dir=str(trace_dir),
        persist_trace=persist_trace,
    )

    trace_path = trace_dir / "run-123.json"
    trace_payload = json.loads(trace_path.read_text())
    captured = capsys.readouterr()

    assert trace_payload["trace_path"] == str(trace_path)
    assert '"trace_path":' in captured.out
    assert str(trace_path) in captured.out


def test_cli_interactive_runtime_reports_when_no_last_trace_exists(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/last\n", "/trace\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {"status": "done"},
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert captured.out.count("No previous runtime run.") == 2


def test_cli_interactive_runtime_can_approve_pending_tool(monkeypatch, capsys):
    from self_correcting_langgraph_agent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "y\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append({"goal": goal, **kwargs})
        if len(calls) == 1:
            return {
                "status": "requires_approval",
                "pending_approval": {
                    "id": "step-2",
                    "tool": "http_request",
                    "input": {"url": "https://github.com"},
                },
            }
        return {
            "status": "done",
            "approved_action_ids": sorted(kwargs.get("approved_action_ids", set())),
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=3,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert len(calls) == 2
    assert calls[1]["goal"] == "打开 github"
    assert calls[1]["approved_action_ids"] == {"step-2"}
    assert "Approve step-2 http_request" in captured.out
    assert "! approval" in captured.out
    assert "✓ done" in captured.out


def test_cli_writes_output_file_before_failure_exit(tmp_path):
    output_path = tmp_path / "failed-trace.json"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 1 + 1 then search the web",
            "--fail-on-agent-failure",
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(output_path.read_text()) == json.loads(completed.stdout)


def test_cli_can_print_run_summary():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "uppercase text in 'agent loop'",
            "--inject-fault",
            "uppercase text in 'agent loop'=empty-answer",
            "--summary",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["retry_count"] == "1"
    assert payload["failed_verifications"] == "1"
    assert payload["faults"] == ["empty-answer"]


def test_cli_reports_invalid_fault_format_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--inject-fault",
            "calculate 2 + 3",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--inject-fault must use STEP=FAULT" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_reports_unknown_fault_name_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--inject-fault",
            "calculate 2 + 3=typo",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "unsupported fault: typo" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_reports_invalid_retry_config_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--max-retries",
            "-1",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--max-retries must be non-negative" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_reports_invalid_step_config_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.cli",
            "calculate 2 + 3",
            "--max-steps",
            "0",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--max-steps must be at least 1" in completed.stderr
    assert "Traceback" not in completed.stderr
