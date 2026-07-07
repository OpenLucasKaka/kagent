import importlib
import json
import os
import subprocess
import sys
import threading
from argparse import Namespace
from pathlib import Path


def test_cli_entrypoint_is_delegated_to_cli_main_module():
    from kagent import cli

    cli_main = importlib.import_module("kagent.cli.main")

    assert cli.main is cli_main.main


def test_cli_defaults_goal_runs_to_runtime_mode():
    from kagent.cli.main import _apply_default_cli_mode

    args = Namespace(
        deterministic=False,
        runtime=False,
        runtime_plan="",
        interactive=False,
        goal="write an internal rollout plan",
        list_tools=False,
        list_faults=False,
        graph=False,
        version=False,
        plan=False,
        summary=False,
        max_steps=None,
        max_retries=None,
        inject_wrong_answer=[],
        inject_fault=[],
    )

    _apply_default_cli_mode(args)

    assert args.runtime is True
    assert args.interactive is False
    assert args.deterministic is False


def test_cli_deterministic_flag_keeps_goal_on_legacy_graph():
    from kagent.cli.main import _apply_default_cli_mode

    args = Namespace(
        deterministic=True,
        runtime=False,
        runtime_plan="",
        interactive=False,
        goal="calculate 2 + 3",
        list_tools=False,
        list_faults=False,
        graph=False,
        version=False,
        plan=False,
        summary=False,
        max_steps=None,
        max_retries=None,
        inject_wrong_answer=[],
        inject_fault=[],
    )

    _apply_default_cli_mode(args)

    assert args.runtime is False
    assert args.interactive is False


def test_cli_rejects_deterministic_runtime_plan_mix():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
            "capture hello",
            "--runtime-plan",
            '{"actions":[]}',
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--deterministic cannot be combined with runtime options" in completed.stderr


def test_cli_runs_goal_and_prints_json_trace():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
    assert by_name["open_app"]["approval_required_by_default"] == "true"
    assert by_name["open_app"]["input_schema"]["required"] == ["application"]
    assert by_name["open_app"]["output_schema"]["required"] == [
        "application",
        "opened",
        "command",
    ]
    assert by_name["open_url"]["approval_required_by_default"] == "true"
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
    env["KAGENT_MAX_STEPS"] = "1"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
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
    env["KAGENT_MAX_STEPS"] = "1"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
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
    env["KAGENT_MAX_STEPS"] = "many"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
            "calculate 2 + 3",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "KAGENT_MAX_STEPS must be an integer" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_can_exit_nonzero_when_agent_run_fails():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
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
            "kagent.cli",
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


def test_cli_missing_runtime_provider_config_prints_actionable_error_without_usage(tmp_path):
    env = os.environ.copy()
    env.pop("KAGENT_LLM_BASE_URL", None)
    env.pop("KAGENT_LLM_MODEL", None)
    env.pop("KAGENT_LLM_API_KEY", None)
    env["KAGENT_LLM_CONFIG_PATH"] = str(tmp_path / "missing-provider.json")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "kagent runtime provider is not configured." in completed.stderr
    assert "KAGENT_LLM_BASE_URL" in completed.stderr
    assert "KAGENT_LLM_MODEL" in completed.stderr
    assert "kagent --deterministic 'calculate 2 + 3'" in completed.stderr
    assert "usage:" not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_missing_runtime_provider_config_for_goal_avoids_argparse_usage(tmp_path):
    env = os.environ.copy()
    env.pop("KAGENT_LLM_BASE_URL", None)
    env.pop("KAGENT_LLM_MODEL", None)
    env.pop("KAGENT_LLM_API_KEY", None)
    env["KAGENT_LLM_CONFIG_PATH"] = str(tmp_path / "missing-provider.json")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "draft an internal rollout checklist",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "kagent runtime provider is not configured." in completed.stderr
    assert "usage:" not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_provider_setup_collects_values_and_saves_config(tmp_path):
    from kagent.cli.main import _configure_runtime_provider_interactively
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    prompts = []
    answers = iter(["2", "", ""])
    saved_configs = []

    def input_answer(prompt):
        prompts.append(prompt)
        return next(answers)

    def save_config(config):
        saved_configs.append(config)
        return str(tmp_path / "provider.json")

    config = _configure_runtime_provider_interactively(
        LLMProviderConfig,
        default_model="default-model",
        default_config_path=lambda: str(tmp_path / "provider.json"),
        save_config=save_config,
        input_fn=input_answer,
        secret_input_fn=lambda _prompt: "secret-key",
    )

    assert prompts[0].startswith("Provider")
    assert config.provider == ProviderKind.DEEPSEEK
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.model == "deepseek-chat"
    assert config.api_key == "secret-key"
    assert saved_configs == [config]


def test_cli_provider_setup_allows_custom_openai_compatible_values(tmp_path):
    from kagent.cli.main import _configure_runtime_provider_interactively
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    answers = iter(["4", "https://gateway.example/v1", "gateway-model"])
    saved_configs = []

    def save_config(config):
        saved_configs.append(config)
        return str(tmp_path / "provider.json")

    config = _configure_runtime_provider_interactively(
        LLMProviderConfig,
        default_model="default-model",
        default_config_path=lambda: str(tmp_path / "provider.json"),
        save_config=save_config,
        input_fn=lambda _prompt: next(answers),
        secret_input_fn=lambda _prompt: "secret-key",
    )

    assert config.provider == ProviderKind.OPENAI_COMPATIBLE
    assert config.base_url == "https://gateway.example/v1"
    assert config.model == "gateway-model"
    assert config.api_key == "secret-key"
    assert saved_configs == [config]


def test_cli_configure_flag_rejects_goal_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--configure",
            "draft plan",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--configure cannot be combined with a goal" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_runtime_accepts_non_secret_metadata_and_tags():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
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
            "kagent.cli",
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
    from kagent.cli.main import _persist_runtime_cli_trace

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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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


def test_cli_runtime_rejects_secret_like_metadata_values_without_traceback():
    api_key = "sk-" + "metadata-redaction-value"

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "score readiness",
            "--runtime",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
            "--metadata",
            f"ticket={api_key}",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "metadata values must not contain secret-like values" in completed.stderr
    assert api_key not in completed.stderr
    assert "Traceback" not in completed.stderr


def test_cli_interactive_runtime_runs_goals_from_stdin_with_inline_plan(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    completed = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            "-m",
            "kagent.cli",
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


def test_cli_defaults_to_interactive_runtime_when_no_goal_is_provided(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")

    completed = subprocess.run(
        [
            str(project_root / ".venv/bin/python"),
            "-m",
            "kagent.cli",
            "--runtime-plan",
            '{"actions":[],"final_answer":"ready"}',
        ],
        input="检查默认交互\nexit\n",
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["status"] == "done"
    assert payload["answer"] == "ready"


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
            "kagent.cli",
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
    from kagent.cli import _run_runtime_interactive

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
    assert "kagent" in captured.err
    assert "[K]" in captured.err
    assert "local agent for your terminal" in captured.err
    assert "ask · approve · automate" in captured.err
    assert "ready for work" not in captured.err
    assert "/help" not in captured.err
    assert "/config" not in captured.err
    assert "/status" not in captured.err


def test_cli_interactive_runtime_reuses_prompt_line_after_empty_enter(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["\n", "\n", "exit\n"]

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
    assert captured.out.count("\x1b[1A\r\x1b[2K") == 2


def test_cli_interactive_runtime_accepts_next_input_while_run_is_active(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    second_input_seen = threading.Event()
    errors = []
    calls = []

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["第一个任务\n", "第二个任务\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            line = self.lines.pop(0) if self.lines else ""
            if line == "第二个任务\n":
                second_input_seen.set()
            return line

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        if len(calls) == 1 and not second_input_seen.wait(timeout=0.2):
            errors.append("second input was not accepted while first run was active")
        return {"status": "done", "answer": f"done {len(calls)}"}

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    assert errors == []
    assert calls[0] == "第一个任务"
    assert calls[1].endswith("Current user message:\n第二个任务")


def test_cli_colored_runtime_prompt_marks_ansi_as_readline_invisible():
    from kagent.cli.ui import runtime_prompt, runtime_prompt_reset

    prompt = runtime_prompt(color=True)

    assert "\001\033[48;5;236m" in prompt
    assert "\033[36m\002› " in prompt
    assert "\033[0m" not in prompt
    assert runtime_prompt_reset(color=True) == "\033[0m"
    assert runtime_prompt(color=False) == "› "
    assert runtime_prompt_reset(color=False) == ""


def test_cli_runtime_user_message_block_is_wide_and_not_arrow_prefixed():
    from kagent.cli.ui import runtime_user_message_block

    block = runtime_user_message_block("测试", color=True, width=12)

    assert block.startswith("\033[48;5;236m")
    assert "›" not in block
    assert "测试" in block
    assert block.endswith("\033[0m")
    visible = (
        block.replace("\033[48;5;236m", "")
        .replace("\033[97m", "")
        .replace("\033[0m", "")
    )
    assert visible.splitlines() == [
        "            ",
        "测试        ",
        "            ",
    ]
    assert runtime_user_message_block("测试", color=False, width=12) == "测试"


def test_cli_runtime_ready_message_feels_like_kagent_product_shell():
    from kagent.cli.ui import runtime_ready_message

    message = runtime_ready_message(color=False)

    assert message.splitlines()[0] == "kagent"
    assert "[K]" in message
    assert "local agent for your terminal" in message
    assert "ask · approve · automate" in message
    assert "/config" not in message
    assert "/help" not in message
    assert "/status" not in message
    assert len(message.splitlines()) <= 4
    assert "K-bot" not in message
    assert "(o_o)" not in message
    assert ("self" + "-correcting") not in message.lower()
    assert "runtime shell" not in message.lower()


def test_cli_runtime_setup_message_keeps_brand_presence():
    from kagent.cli.ui import runtime_setup_message

    message = runtime_setup_message(
        config_path="/Users/kaka/.config/kagent/provider.json",
        color=False,
    )

    assert message.splitlines()[0] == "kagent setup"
    assert "[K]" in message
    assert "Configure your provider once." in message
    assert "K-bot" not in message
    assert "(o_o)" not in message
    assert "/Users/kaka/.config/kagent/provider.json" in message


def test_cli_runtime_help_reads_like_a_command_palette():
    from kagent.cli.ui import runtime_interactive_help

    message = runtime_interactive_help()

    assert message.splitlines()[0] == "kagent command palette"
    assert "Session" in message
    assert "Provider" in message
    assert "Output" in message
    assert "Debug" in message
    assert "/json" in message
    assert "/compact" in message
    assert "show this help" not in message


def test_cli_runtime_command_registry_feeds_help_and_completion():
    from kagent.cli.commands import (
        is_runtime_interactive_command,
        runtime_interactive_command_suggestions,
        runtime_interactive_command_usage,
        runtime_interactive_completion_words,
    )
    from kagent.cli.ui import runtime_interactive_help

    help_text = runtime_interactive_help()
    completion_words = runtime_interactive_completion_words()

    assert is_runtime_interactive_command("/status")
    assert is_runtime_interactive_command("/save-trace /tmp/last.json")
    assert not is_runtime_interactive_command("/stats")
    assert "/status" in runtime_interactive_command_suggestions("/stats")
    assert runtime_interactive_command_usage("/status now") == "/status"
    assert runtime_interactive_command_usage("/export-trace /tmp/run.json") == (
        "/save-trace PATH"
    )
    assert "/status" in help_text
    assert "/reset" in help_text
    assert "/config" in help_text
    assert "/doctor" in help_text
    assert "/save-trace PATH" in help_text
    assert "/status" in completion_words
    assert "/stat" in completion_words
    assert "/doctor" in completion_words
    assert "/diagnostics" in completion_words
    assert "/save-trace" in completion_words
    assert "/export-trace" in completion_words
    assert "/reset-session" in completion_words
    assert "exit" in completion_words


def test_cli_interactive_runtime_blocks_unknown_slash_command_locally(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/stats\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: calls.append(None),
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == []
    assert "Unknown command\n  try /status" in captured.out


def test_cli_interactive_runtime_blocks_invalid_known_slash_command_locally(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/status now\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: calls.append(None),
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == []
    assert "Invalid command\n  usage: /status" in captured.out


def test_cli_runtime_status_formats_empty_shell_state():
    from kagent.cli.ui import format_runtime_interactive_status

    message = format_runtime_interactive_status(
        cwd="/workspace",
        full_json_mode=False,
        session_memory=[],
        last_payload=None,
        trace_dir="",
    )

    assert message == "\n".join(
        [
            "kagent session",
            "  cwd      /workspace",
            "  output   compact",
            "  memory   0 recent turns",
            "  last     -",
            "  trace    off",
        ]
    )


def test_cli_runtime_doctor_redacts_provider_location_and_secret():
    from kagent.cli.ui import format_runtime_interactive_doctor
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    class FakeProvider:
        config = LLMProviderConfig(
            provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
            base_url="https://llm.example.test/v1",
            api_key="sk-secret-value",
            model="qwen3.5-122b-a10b",
        )

    message = format_runtime_interactive_doctor(
        cwd="/workspace",
        provider=FakeProvider(),
        session_memory_path="/state/session-memory.json",
        history_path="/state/history",
        trace_dir="/traces",
        line_editor="prompt_toolkit",
    )

    assert "kagent doctor" in message
    assert "provider     Qwen" in message
    assert "model        qwen3.5-122b-a10b" in message
    assert "base_url     configured" in message
    assert "api_key      configured" in message
    assert "memory       /state/session-memory.json" in message
    assert "history      /state/history" in message
    assert "line_editor  prompt_toolkit" in message
    assert "https://llm.example.test/v1" not in message
    assert "sk-secret-value" not in message


def test_cli_runtime_tools_formats_compact_action_list():
    from kagent.cli.ui import format_runtime_interactive_tools

    message = format_runtime_interactive_tools(
        [
            {
                "name": "apply_patch",
                "description": "Create, update, delete, or move files.",
                "approval_required_by_default": "false",
                "input_schema": {"type": "object"},
            },
            {
                "name": "open_url",
                "description": "Open a URL in the local desktop browser.",
                "approval_required_by_default": "true",
                "input_schema": {"type": "object"},
            },
            {
                "name": "note",
                "description": "Record a short internal note.",
                "approval_required_by_default": "false",
            },
        ]
    )

    assert message == "\n".join(
        [
            "kagent actions",
            "  apply_patch  allowed   Create, update, delete, or move files.",
            "  open_url     approval  Open a URL in the local desktop browser.",
        ]
    )
    assert "input_schema" not in message
    assert "note" not in message


def test_cli_runtime_provider_config_redacts_secret_values():
    from kagent.cli.ui import format_runtime_provider_config
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    class FakeProvider:
        config = LLMProviderConfig(
            provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
            base_url="https://llm.example.test/v1",
            api_key="sk-secret-value",
            model="qwen3.5-122b-a10b",
            timeout_seconds=45,
            max_retries=3,
            retry_backoff_seconds=0.5,
        )

    message = format_runtime_provider_config(FakeProvider())

    assert "kagent provider" in message
    assert "provider   Qwen" in message
    assert "base_url   https://llm.example.test/v1" in message
    assert "model      qwen3.5-122b-a10b" in message
    assert "api_key    configured" in message
    assert "timeout    45s" in message
    assert "retries    3" in message
    assert "sk-secret-value" not in message


def test_cli_prompt_toolkit_reader_wraps_long_lines():
    from kagent.cli.interactive import _PromptToolkitLineReader

    class FakeSession:
        def __init__(self):
            self.calls = []

        def prompt(self, message, **kwargs):
            self.calls.append({"message": message, **kwargs})
            return "帮我制定一个很长很长的周末旅行攻略"

    session = FakeSession()
    reader = _PromptToolkitLineReader(session)

    assert reader.read(color=True) == "帮我制定一个很长很长的周末旅行攻略"
    assert session.calls == [
        {
            "message": [("class:input-bar.prompt", "› ")],
            "wrap_lines": True,
            "multiline": False,
        }
    ]


def test_cli_defaults_history_to_xdg_state(monkeypatch, tmp_path):
    from kagent.cli.memory import default_runtime_history_path

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", "/Users/kaka")

    assert default_runtime_history_path() == str(tmp_path / "kagent" / "history")


def test_cli_history_can_be_disabled_by_env(monkeypatch):
    from kagent.cli.memory import default_runtime_history_path

    monkeypatch.setenv("KAGENT_HISTORY_PATH", "")

    assert default_runtime_history_path() == ""


def test_cli_history_file_is_owner_only_and_redacted(tmp_path):
    from kagent.cli.memory import runtime_prompt_history

    history_path = tmp_path / "state" / "kagent" / "history"
    history = runtime_prompt_history(str(history_path))

    assert history is not None
    history.store_string(
        "remember sk-interactive-secret-value "
        "Authorization: Bearer token-secret-value "
        "https://user:pass@example.com/v1"
    )

    history_text = history_path.read_text(encoding="utf-8")
    assert history_path.parent.stat().st_mode & 0o777 == 0o700
    assert history_path.stat().st_mode & 0o777 == 0o600
    assert "sk-interactive-secret-value" not in history_text
    assert "token-secret-value" not in history_text
    assert "user:pass@example.com" not in history_text
    assert "[REDACTED_API_KEY]" in history_text
    assert "Bearer [REDACTED_TOKEN]" in history_text
    assert "https://[REDACTED_CREDENTIALS]@example.com/v1" in history_text


def test_cli_can_clear_runtime_history_file(tmp_path):
    from kagent.cli.memory import clear_runtime_history

    history_path = tmp_path / "state" / "kagent" / "history"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("old prompt\n", encoding="utf-8")
    history_path.chmod(0o600)

    clear_runtime_history(str(history_path))

    assert history_path.read_text(encoding="utf-8") == ""
    assert history_path.parent.stat().st_mode & 0o777 == 0o700
    assert history_path.stat().st_mode & 0o777 == 0o600


def test_cli_prompt_toolkit_session_uses_persistent_history(
    monkeypatch,
    tmp_path,
):
    from kagent.cli.commands import runtime_interactive_completion_words
    from kagent.cli.interactive import _prompt_toolkit_session_for_tty

    created_sessions = []

    class FakeTTY:
        def isatty(self):
            return True

    class FakePromptSession:
        def __init__(self, **kwargs):
            created_sessions.append(kwargs)

    monkeypatch.setattr(sys, "stdin", sys.__stdin__)
    monkeypatch.setattr(sys.__stdin__, "isatty", lambda: True)
    monkeypatch.setattr("prompt_toolkit.PromptSession", FakePromptSession)
    monkeypatch.setenv("KAGENT_HISTORY_PATH", str(tmp_path / "history"))

    session = _prompt_toolkit_session_for_tty(FakeTTY())

    assert isinstance(session, FakePromptSession)
    assert created_sessions[0]["history"] is not None
    assert created_sessions[0]["complete_while_typing"] is True
    assert created_sessions[0]["completer"] is not None
    assert created_sessions[0]["style"] is not None
    assert "('', 'bg:#303030 #ffffff')" in str(created_sessions[0]["style"].style_rules)
    assert "input-bar.prompt" in str(created_sessions[0]["style"].style_rules)
    assert "#303030" in str(created_sessions[0]["style"].style_rules)
    assert set(created_sessions[0]["completer"].words) == set(
        runtime_interactive_completion_words()
    )
    assert (tmp_path / "history").stat().st_mode & 0o777 == 0o600


def test_cli_interactive_runtime_tty_prints_production_summary(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
    assert "╭─" not in captured.out
    assert "╰─" not in captured.out
    assert "\nDone" in captured.out
    assert "Done · 0.1200s" in captured.out
    assert "0.1200s" in captured.out
    assert "\n\nAnswer\n  已打开 GitHub。" in captured.out
    assert "\n\nResults\n  ✓ Opened https://github.com in Google Chrome" in captured.out
    assert "\n\nActions" not in captured.out
    assert "open_url" not in captured.out
    assert "0.0300s" not in captured.out
    assert "Google Chrome" in captured.out
    assert "opened" not in captured.out
    assert "url=" not in captured.out
    assert "opened=True" not in captured.out
    assert "run-123" not in captured.out
    assert "assistant" not in captured.out
    assert "status" not in captured.out
    assert "tool calls" not in captured.out
    assert "step-1" not in captured.out
    assert "== Run ==" not in captured.out
    assert '"observations"' not in captured.out


def test_cli_compact_summary_wraps_cjk_answer_in_narrow_terminal(monkeypatch):
    from kagent.cli import ui

    monkeypatch.setattr(
        "kagent.cli.ui.shutil.get_terminal_size",
        lambda _fallback: os.terminal_size((40, 24)),
    )

    message = ui.format_runtime_interactive_summary(
        {
            "status": "done",
            "answer": "我是kagent，可以帮你处理本地任务、打开应用、整理文件和执行需要确认的操作。",
            "observations": [
                {
                    "tool": "open_url",
                    "status": "ok",
                    "output": {
                        "url": "https://kagent.local",
                        "application": "Google Chrome",
                    },
                }
            ],
        },
        color=False,
    )

    lines = message.splitlines()
    assert "Answer" in lines
    assert any(line.startswith("  我是kagent") for line in lines)
    assert any(line.startswith("  应用、整理文件") for line in lines)
    assert max(ui._display_width(line) for line in lines) <= 40


def test_cli_compact_summary_hides_failed_observations_when_answer_is_done():
    from kagent.cli.ui import format_runtime_interactive_summary

    message = format_runtime_interactive_summary(
        {
            "status": "done",
            "answer": "你好卡卡，我可以帮你处理本地任务。",
            "observations": [
                {
                    "tool": "read_file",
                    "status": "failed",
                    "error": "The read operation timed out",
                }
            ],
        },
        color=False,
    )

    assert "\n\nAnswer\n  你好卡卡" in message
    assert "\n\nResults" not in message
    assert "Completed action" not in message
    assert "The read operation timed out" not in message


def test_cli_interactive_runtime_tty_prints_live_progress(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
                "type": "planner_failed",
                "duration_seconds": "30.0833",
            }
        )
        event_sink({"type": "planner_started", "iteration": "2"})
        event_sink(
            {
                "type": "planner_completed",
                "action_count": "1",
                "duration_seconds": "0.2000",
            }
        )
        event_sink({"type": "approval_required", "tool": "open_url"})
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
    assert "\r  " in captured.out
    assert "Thinking" in captured.out
    assert "Planned 1 action · 0.2000s" in captured.out
    assert "Working" in captured.out
    assert "Thinking · iter" not in captured.out
    assert "Planner failed" not in captured.out
    assert "Approval required ·" not in captured.out
    assert "✓ Completed · 0.0100s" in captured.out
    assert "\n\nDone" in captured.out
    assert "\n\nAnswer\n  文件已创建。" in captured.out
    assert "\n\nResults\n  ✓ Updated files add hello.md 13B" in captured.out
    assert "\n\nActions" not in captured.out
    assert "apply_patch" not in captured.out
    assert "add hello.md 13B" in captured.out


def test_cli_interactive_runtime_streams_answer_deltas_without_duplicate_summary(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打个招呼\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    def fake_run_runtime_agent(_goal, **kwargs):
        event_sink = kwargs["event_sink"]
        assert kwargs["stream_answers"] is True
        event_sink({"type": "planner_started"})
        event_sink({"type": "answer_started"})
        event_sink({"type": "answer_delta", "delta": "你好"})
        event_sink({"type": "answer_delta", "delta": "，卡卡"})
        event_sink({"type": "answer_completed"})
        return {
            "status": "done",
            "answer": "你好，卡卡",
            "answer_streamed": "true",
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
    assert "Answer\n  你好，卡卡\n" in captured.out
    assert captured.out.count("Answer") == 1
    assert "\nDone" in captured.out


def test_cli_interactive_runtime_tty_can_toggle_json_output(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
    assert "Output mode\n  full JSON traces" in captured.out
    assert '"observations"' in captured.out
    assert "Output mode\n  compact transcript" in captured.out
    assert "Done" in captured.out


def test_cli_interactive_runtime_collapses_repeated_tool_observations(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

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
    assert "Opened https://github.com" in captured.out
    assert "open_url" not in captured.out


def test_cli_interactive_runtime_hides_note_only_activity(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
    from kagent.cli import _run_runtime_interactive

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
    assert "╭─" not in captured.out
    assert "\n\nAnswer\n  文件已创建。" in captured.out
    assert "status" not in captured.out
    assert "\nDone · 1.2500s" in captured.out
    assert "iter 2/3" not in captured.out
    assert "\n\nResults\n  ✓ Updated files hello.md" in captured.out
    assert "\n\nActions" not in captured.out
    assert "apply_patch" not in captured.out
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
    from kagent.cli import _run_runtime_interactive

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
    assert "Memory" in captured.out
    assert "user   我是卡卡" in captured.out
    assert "agent  你好，卡卡。" in captured.out
    assert "Memory\n  cleared" in captured.out
    assert "Memory is empty." in captured.out


def test_cli_interactive_runtime_reset_clears_memory_and_history(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    memory_path = tmp_path / "agent-memory.json"
    history_path = tmp_path / "state" / "kagent" / "history"
    history_path.parent.mkdir(parents=True)
    history_path.write_text("previous prompt\n", encoding="utf-8")
    history_path.chmod(0o600)

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我是卡卡\n", "/reset\n", "/memory\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        return {"status": "done", "answer": "你好，卡卡。"}

    monkeypatch.setenv("KAGENT_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
        session_memory_path=str(memory_path),
    )

    saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert calls == ["我是卡卡"]
    assert saved_memory["turns"] == []
    assert history_path.read_text(encoding="utf-8") == ""
    assert "Reset\n  memory and prompt history cleared" in captured.out
    assert "Memory is empty." in captured.out


def test_cli_interactive_runtime_can_show_session_status(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["我是卡卡\n", "/json\n", "/status\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {
            "status": "done",
            "answer": "你好，卡卡。",
            "run_id": "private-run-id",
        },
        max_iterations=4,
        fail_on_agent_failure=False,
        trace_dir=str(tmp_path / "traces"),
    )

    captured = capsys.readouterr()
    assert "kagent session" in captured.out
    assert f"cwd      {tmp_path}" in captured.out
    assert "output   full JSON" in captured.out
    assert "memory   1 recent turn" in captured.out
    assert "last     done" in captured.out
    assert f"trace    {tmp_path / 'traces'}" in captured.out
    assert "private-run-id" not in captured.out


def test_cli_interactive_runtime_can_show_local_doctor(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/doctor\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    class FakeProvider:
        config = LLMProviderConfig(
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://gateway.example/v1",
            api_key="sk-secret-value",
            model="gateway-model",
        )

    memory_path = tmp_path / "memory.json"
    history_path = tmp_path / "history"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KAGENT_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=FakeProvider(),
        run_runtime_agent=lambda *_args, **_kwargs: {"status": "done"},
        max_iterations=4,
        fail_on_agent_failure=False,
        trace_dir=str(tmp_path / "traces"),
        session_memory_path=str(memory_path),
    )

    captured = capsys.readouterr()
    assert "kagent doctor" in captured.out
    assert f"cwd          {tmp_path}" in captured.out
    assert "provider     OpenAI-compatible" in captured.out
    assert "model        gateway-model" in captured.out
    assert "base_url     configured" in captured.out
    assert "api_key      configured" in captured.out
    assert f"memory       {memory_path}" in captured.out
    assert f"history      {history_path}" in captured.out
    assert f"trace        {tmp_path / 'traces'}" in captured.out
    assert "https://gateway.example/v1" not in captured.out
    assert "sk-secret-value" not in captured.out


def test_cli_interactive_runtime_can_show_registered_tools(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/tools\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(*_args, **_kwargs):
        calls.append("called")
        return {"status": "done"}

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == []
    assert "kagent actions" in captured.out
    assert "apply_patch" in captured.out
    assert "allowed" in captured.out
    assert "open_url" in captured.out
    assert "approval" in captured.out
    assert "input_schema" not in captured.out


def test_cli_interactive_runtime_can_show_provider_config_without_model_call(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive
    from kagent.providers.llm import LLMProviderConfig

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/config\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    class FakeProvider:
        config = LLMProviderConfig(
            base_url="https://llm.example.test/v1",
            api_key="sk-secret-value",
            model="qwen3.5-122b-a10b",
        )

    calls = []
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=FakeProvider(),
        run_runtime_agent=lambda *_args, **_kwargs: calls.append("called"),
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == []
    assert "kagent provider" in captured.out
    assert "qwen3.5-122b-a10b" in captured.out
    assert "sk-secret-value" not in captured.out


def test_cli_interactive_runtime_can_change_working_directory(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    class FakeTTYInput:
        def __init__(self):
            self.lines = [f"/cd {project_dir}\n", "/pwd\n", "创建文件\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append({"goal": goal, "cwd": os.getcwd()})
        return {"status": "done", "answer": "ok"}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == [{"goal": "创建文件", "cwd": str(project_dir)}]
    assert f"Working directory\n  {project_dir}" in captured.out


def test_cli_interactive_runtime_reports_invalid_cd_without_model_call(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    missing_dir = tmp_path / "missing"

    class FakeTTYInput:
        def __init__(self):
            self.lines = [f"/cd {missing_dir}\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: calls.append("called"),
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    captured = capsys.readouterr()
    assert calls == []
    assert f"Directory not found\n  {missing_dir}" in captured.out
    assert "Traceback" not in captured.out


def test_cli_interactive_runtime_carries_session_memory_between_turns(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

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
    assert "Compacted conversation memory from this interactive session" in calls[1]
    assert "User: 我是卡卡" in calls[1]
    assert "Assistant: 你好，卡卡。" in calls[1]
    assert "Current user message:\n我是谁" in calls[1]
    captured = capsys.readouterr()
    assert "你是卡卡。" in captured.out


def test_cli_interactive_runtime_redacts_secrets_before_memory_reuse(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    api_key = "sk-" + "interactive-secret-value"
    bearer_token = "super-secret-runtime-token"

    class FakeTTYInput:
        def __init__(self):
            self.lines = [
                (
                    f"记住 {api_key} 和 "
                    "https://user:pass@example.com/v1\n"
                ),
                "复述一下上一轮\n",
                "exit\n",
            ]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        return {
            "status": "done",
            "answer": f"Authorization: Bearer {bearer_token}",
        }

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    assert api_key not in calls[1]
    assert bearer_token not in calls[1]
    assert "user:pass@example.com" not in calls[1]
    assert "[REDACTED_API_KEY]" in calls[1]
    assert "Bearer [REDACTED_TOKEN]" in calls[1]
    assert "https://[REDACTED_CREDENTIALS]@example.com/v1" in calls[1]
    capsys.readouterr()


def test_cli_interactive_runtime_auto_compacts_long_session_memory(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = [
                "我是卡卡\n",
                "记住我喜欢简洁输出\n",
                "帮我创建试运行计划\n",
                "继续优化 UI\n",
                "接下来处理权限控制\n",
                "帮我打开 github\n",
                "继续整理代码结构\n",
                "需要记住审批要简洁\n",
                "帮我检查上下文压缩\n",
                "我是谁\n",
                "exit\n",
            ]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **_kwargs):
        calls.append(goal)
        return {"status": "done", "answer": f"ok {len(calls)}"}

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )

    final_prompt = calls[-1]
    assert "Compacted conversation memory from this interactive session" in final_prompt
    assert "Summary:" in final_prompt
    assert "Durable facts:" in final_prompt
    assert "User said: 我是卡卡" in final_prompt
    assert "Open items:" in final_prompt
    assert "Request: 帮我创建试运行计划" in final_prompt
    assert "Recent turns:" in final_prompt
    assert "Current user message:\n我是谁" in final_prompt
    assert len(final_prompt) < 4500
    capsys.readouterr()


def test_cli_interactive_runtime_can_force_compact_memory(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    memory_path = tmp_path / "memory.json"

    class FakeTTYInput:
        def __init__(self):
            self.lines = [
                "我是卡卡\n",
                "记住我喜欢简洁输出\n",
                "帮我创建试运行计划\n",
                "继续优化 UI\n",
                "接下来处理权限控制\n",
                "帮我打开 github\n",
                "继续整理代码结构\n",
                "需要记住审批要简洁\n",
                "帮我检查上下文压缩\n",
                "/compact-memory\n",
                "/memory\n",
                "exit\n",
            ]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    monkeypatch.setattr(sys, "stdin", FakeTTYInput())
    monkeypatch.setattr(sys, "__stderr__", sys.stderr)

    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=lambda *_args, **_kwargs: {"status": "done", "answer": "ok"},
        max_iterations=1,
        fail_on_agent_failure=False,
        session_memory_path=str(memory_path),
    )

    saved_memory = json.loads(memory_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert saved_memory["schema_version"] == "2"
    assert saved_memory["compacted_turn_count"] >= 1
    assert saved_memory["summary"]
    assert saved_memory["facts"]
    assert saved_memory["open_items"]
    assert "Memory compacted" in captured.out
    assert "summary" in captured.out
    assert "facts" in captured.out
    assert "open items" in captured.out


def test_cli_interactive_runtime_persists_session_memory_between_shells(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

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
    assert saved_memory["schema_version"] == "2"
    assert saved_memory["summary"] == ""
    assert saved_memory["facts"] == []
    assert saved_memory["open_items"] == []
    assert saved_memory["compacted_turn_count"] == 0
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

    assert "Compacted conversation memory from this interactive session" in calls[0]
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
    from kagent.cli import _run_runtime_interactive

    memory_path = tmp_path / "agent-memory.json"
    memory_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "旧", "assistant": "旧"}]}),
        encoding="utf-8",
    )
    memory_path.chmod(0o600)

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
    assert "Memory\n  cleared" in captured.out


def test_cli_session_memory_rejects_group_or_world_readable_file(tmp_path):
    from kagent.cli.memory import load_runtime_session_memory

    memory_path = tmp_path / "agent-memory.json"
    memory_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "kaka"}]}),
        encoding="utf-8",
    )
    memory_path.chmod(0o644)

    try:
        load_runtime_session_memory(str(memory_path), max_turns=12)
    except ValueError as exc:
        assert "session memory file must be owner-only" in str(exc)
    else:
        raise AssertionError("unsafe session memory file was loaded")


def test_cli_session_memory_rejects_symlink_file(tmp_path):
    from kagent.cli.memory import load_runtime_session_memory

    target_path = tmp_path / "target-memory.json"
    target_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "kaka"}]}),
        encoding="utf-8",
    )
    target_path.chmod(0o600)
    memory_path = tmp_path / "agent-memory.json"
    memory_path.symlink_to(target_path)

    try:
        load_runtime_session_memory(str(memory_path), max_turns=12)
    except ValueError as exc:
        assert "session memory file must not be a symlink" in str(exc)
    else:
        raise AssertionError("symlink session memory file was loaded")


def test_cli_session_memory_rejects_symlink_file_on_save(tmp_path):
    from kagent.cli.memory import save_runtime_session_memory

    target_path = tmp_path / "target-memory.json"
    target_path.write_text(
        json.dumps({"schema_version": "1", "turns": []}),
        encoding="utf-8",
    )
    target_path.chmod(0o600)
    memory_path = tmp_path / "agent-memory.json"
    memory_path.symlink_to(target_path)

    try:
        save_runtime_session_memory(
            str(memory_path),
            [{"user": "kaka", "assistant": "ready"}],
        )
    except ValueError as exc:
        assert "session memory file must not be a symlink" in str(exc)
    else:
        raise AssertionError("session memory was saved through a symlink file")


def test_cli_session_memory_rejects_symlink_parent_on_load(tmp_path):
    from kagent.cli.memory import load_runtime_session_memory

    target_dir = tmp_path / "target-memory-dir"
    target_dir.mkdir()
    target_dir.chmod(0o700)
    memory_path = target_dir / "agent-memory.json"
    memory_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "kaka"}]}),
        encoding="utf-8",
    )
    memory_path.chmod(0o600)
    linked_dir = tmp_path / "linked-memory-dir"
    linked_dir.symlink_to(target_dir)

    try:
        load_runtime_session_memory(str(linked_dir / "agent-memory.json"), max_turns=12)
    except ValueError as exc:
        assert "session memory path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("session memory through symlink parent was loaded")


def test_cli_session_memory_rejects_nested_symlink_parent_on_load(tmp_path):
    from kagent.cli.memory import load_runtime_session_memory

    target_dir = tmp_path / "target-memory-dir"
    nested_dir = target_dir / "nested"
    nested_dir.mkdir(parents=True)
    target_dir.chmod(0o700)
    nested_dir.chmod(0o700)
    memory_path = nested_dir / "agent-memory.json"
    memory_path.write_text(
        json.dumps({"schema_version": "1", "turns": [{"user": "kaka"}]}),
        encoding="utf-8",
    )
    memory_path.chmod(0o600)
    linked_dir = tmp_path / "linked-memory-dir"
    linked_dir.symlink_to(target_dir)

    try:
        load_runtime_session_memory(
            str(linked_dir / "nested" / "agent-memory.json"),
            max_turns=12,
        )
    except ValueError as exc:
        assert "session memory path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("session memory through nested symlink parent was loaded")


def test_cli_session_memory_rejects_symlink_parent_on_save(tmp_path):
    from kagent.cli.memory import save_runtime_session_memory

    target_dir = tmp_path / "target-memory-dir"
    target_dir.mkdir()
    target_dir.chmod(0o700)
    linked_dir = tmp_path / "linked-memory-dir"
    linked_dir.symlink_to(target_dir)

    try:
        save_runtime_session_memory(
            str(linked_dir / "agent-memory.json"),
            [{"user": "kaka", "assistant": "ready"}],
        )
    except ValueError as exc:
        assert "session memory path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("session memory was saved through a symlink parent")


def test_cli_session_memory_rejects_nested_symlink_parent_on_save(tmp_path):
    from kagent.cli.memory import save_runtime_session_memory

    target_dir = tmp_path / "target-memory-dir"
    (target_dir / "nested").mkdir(parents=True)
    target_dir.chmod(0o700)
    (target_dir / "nested").chmod(0o700)
    linked_dir = tmp_path / "linked-memory-dir"
    linked_dir.symlink_to(target_dir)

    try:
        save_runtime_session_memory(
            str(linked_dir / "nested" / "agent-memory.json"),
            [{"user": "kaka", "assistant": "ready"}],
        )
    except ValueError as exc:
        assert "session memory path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("session memory was saved through a nested symlink parent")


def test_cli_session_memory_redacts_secret_like_text_before_persisting(tmp_path):
    from kagent.cli.memory import save_runtime_session_memory

    memory_path = tmp_path / "agent-memory.json"
    api_key = "sk-" + "test-redaction-value"

    save_runtime_session_memory(
        str(memory_path),
        [
            {
                "user": (
                    f"use key {api_key} and "
                    "https://user:pass@example.com/v1"
                ),
                "assistant": "Authorization: Bearer super-secret-token",
            }
        ],
    )

    saved_text = memory_path.read_text(encoding="utf-8")
    saved_memory = json.loads(saved_text)

    assert api_key not in saved_text
    assert "super-secret-token" not in saved_text
    assert "user:pass@example.com" not in saved_text
    assert "[REDACTED_API_KEY]" in saved_memory["turns"][0]["user"]
    assert "https://[REDACTED_CREDENTIALS]@example.com/v1" in saved_memory["turns"][0]["user"]
    assert "Authorization: Bearer [REDACTED_TOKEN]" in saved_memory["turns"][0]["assistant"]


def test_cli_session_memory_tightens_existing_parent_directory(tmp_path):
    from kagent.cli.memory import save_runtime_session_memory

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_dir.chmod(0o755)
    memory_path = memory_dir / "agent-memory.json"

    save_runtime_session_memory(
        str(memory_path),
        [{"user": "kaka", "assistant": "ready"}],
    )

    assert memory_dir.stat().st_mode & 0o777 == 0o700
    assert memory_path.stat().st_mode & 0o777 == 0o600


def test_cli_session_memory_tightens_existing_parent_directory_on_load(tmp_path):
    from kagent.cli.memory import load_runtime_session_memory

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_dir.chmod(0o755)
    memory_path = memory_dir / "agent-memory.json"
    memory_path.write_text(
        json.dumps(
            {"schema_version": "1", "turns": [{"user": "kaka", "assistant": "ready"}]}
        ),
        encoding="utf-8",
    )
    memory_path.chmod(0o600)

    memory = load_runtime_session_memory(str(memory_path), max_turns=12)

    assert memory == [{"user": "kaka", "assistant": "ready"}]
    assert memory_dir.stat().st_mode & 0o777 == 0o700


def test_cli_session_memory_requires_interactive_runtime():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
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


def test_cli_defaults_session_memory_to_xdg_state_for_tty(monkeypatch, tmp_path):
    from kagent.cli.main import _session_memory_path_from_args

    state_home = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    memory_path = _session_memory_path_from_args(
        Namespace(session_memory=""),
        interactive_tty=True,
    )

    assert memory_path == str(state_home / "kagent" / "session-memory.json")


def test_cli_does_not_default_session_memory_for_piped_interactive_runs(
    monkeypatch,
    tmp_path,
):
    from kagent.cli.main import _session_memory_path_from_args

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    assert (
        _session_memory_path_from_args(
            Namespace(session_memory=""),
            interactive_tty=False,
        )
        == ""
    )


def test_cli_session_memory_env_override_can_disable_default_memory(
    monkeypatch,
    tmp_path,
):
    from kagent.cli.main import _session_memory_path_from_args

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("KAGENT_SESSION_MEMORY_PATH", "")

    assert (
        _session_memory_path_from_args(
            Namespace(session_memory=""),
            interactive_tty=True,
        )
        == ""
    )


def test_cli_interactive_runtime_passes_metadata_and_tags_to_each_run(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

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
    from kagent.cli import _run_runtime_interactive

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
    from kagent.cli import _run_runtime_interactive

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
    assert "open_url" not in captured.out
    assert "Opened https://github.com" in captured.out
    assert '"observations"' not in captured.out


def test_cli_interactive_runtime_can_show_last_full_trace_once(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
    from kagent.cli import _run_runtime_interactive
    from kagent.service.trace_store import persist_trace

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


def test_cli_can_save_runtime_trace_snapshot_owner_only(tmp_path):
    from kagent.cli.trace import save_runtime_trace_snapshot_or_raise

    trace_path = tmp_path / "nested" / "last trace.json"

    saved_path = save_runtime_trace_snapshot_or_raise(
        {"run_id": "run-123", "status": "done"},
        str(trace_path),
    )

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    assert saved_path == str(trace_path)
    assert payload == {"run_id": "run-123", "status": "done"}
    assert trace_path.stat().st_mode & 0o777 == 0o600


def test_cli_interactive_runtime_can_save_last_trace_to_file(
    tmp_path,
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    trace_path = tmp_path / "exports" / "last trace.json"

    class FakeTTYInput:
        def __init__(self):
            self.lines = [
                "inspect\n",
                f'/save-trace "{trace_path}"\n',
                "exit\n",
            ]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(_goal, **_kwargs):
        calls.append(None)
        return {
            "status": "done",
            "run_id": "run-123",
            "answer": "ready",
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

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert len(calls) == 1
    assert payload["run_id"] == "run-123"
    assert payload["observations"][0]["tool"] == "note"
    assert trace_path.stat().st_mode & 0o777 == 0o600
    assert "Trace saved" in captured.out
    assert str(trace_path.parent) in captured.out
    assert "trace.json" in captured.out


def test_cli_interactive_runtime_reports_when_no_last_trace_exists(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["/last\n", "/trace\n", "/save-trace /tmp/last.json\n", "exit\n"]

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
    assert captured.out.count("Last run\n  no previous run") == 3


def test_cli_interactive_runtime_can_approve_pending_tool(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

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
                "duration_seconds": "38.3972",
                "iteration_count": "2",
                "max_iterations": "3",
                "pending_approval": {
                    "id": "step-2",
                    "tool": "http_request",
                    "input": {"url": "https://github.com"},
                    "reason": "open requested site",
                },
                "observations": [
                    {
                        "tool": "planner",
                        "status": "failed",
                        "duration_seconds": "30.0833",
                        "error_code": "invalid_plan",
                        "error": "The read operation timed out",
                    },
                    {
                        "action_id": "step-2",
                        "tool": "http_request",
                        "status": "requires_approval",
                        "duration_seconds": "0.0000",
                        "error_code": "tool_not_allowed",
                        "error": "tool execution requires approval",
                    },
                ],
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
    assert "Approval needed" in captured.out
    assert "action  Fetch URL" in captured.out
    assert "target  https://github.com" in captured.out
    assert "reason  open requested site" in captured.out
    assert "Approve this action? [y/N/d]" in captured.out
    assert "Done" in captured.out
    assert "Approval ·" not in captured.out
    assert "Actions" not in captured.out
    assert "planner · 30.0833s" not in captured.out
    assert "invalid_plan" not in captured.out
    assert "tool_not_allowed" not in captured.out
    assert "step-2 http_request" not in captured.out


def test_cli_interactive_runtime_can_show_approval_detail_before_approve(
    monkeypatch,
    capsys,
):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "d\n", "y\n", "exit\n"]

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
                    "tool": "open_url",
                    "input": {"url": "https://github.com"},
                    "reason": "open requested site",
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
    assert calls[1]["approved_action_ids"] == {"step-2"}
    assert "Approval detail" in captured.out
    assert '"id": "step-2"' in captured.out
    assert '"tool": "open_url"' in captured.out
    assert '"url": "https://github.com"' in captured.out
    assert captured.out.count("Approve this action? [y/N/d]") == 2


def test_cli_interactive_runtime_reports_declined_approval(monkeypatch, capsys):
    from kagent.cli import _run_runtime_interactive

    class FakeTTYInput:
        def __init__(self):
            self.lines = ["打开 github\n", "n\n", "exit\n"]

        def isatty(self):
            return True

        def readline(self):
            return self.lines.pop(0) if self.lines else ""

    calls = []

    def fake_run_runtime_agent(goal, **kwargs):
        calls.append({"goal": goal, **kwargs})
        return {
            "status": "requires_approval",
            "pending_approval": {
                "id": "step-2",
                "tool": "open_url",
                "input": {"url": "https://github.com"},
            },
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
    assert len(calls) == 1
    assert "Approval needed" in captured.out
    assert "action  Open URL" in captured.out
    assert "target  https://github.com" in captured.out
    assert "Approval skipped\n  action not approved" in captured.out


def test_cli_writes_output_file_before_failure_exit(tmp_path):
    output_path = tmp_path / "failed-trace.json"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "kagent.cli",
            "--deterministic",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
            "kagent.cli",
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
