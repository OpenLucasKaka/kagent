import json

from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import run_runtime_agent
from kagent.runtime.presentation import (
    project_runtime_presentation,
    project_runtime_start_presentation,
)


def test_projects_user_meaningful_success_results():
    cases = [
        (
            "artifact",
            {
                "artifact_id": "artifact-secret",
                "title": "Release sk-secret123",
                "kind": "report",
                "format": "markdown",
                "content": "Bearer abcdefgh",
                "bytes": 15,
            },
            {
                "title": "Created Release [REDACTED]",
                "detail": "Report · Markdown · 15 bytes",
                "content": "Bearer [REDACTED]",
                "truncated": False,
            },
        ),
        (
            "apply_patch",
            {
                "changed_files": [
                    {"path": "src/one.py", "operation": "update"},
                    {"path": "src/two.py", "operation": "add"},
                ],
                "file_count": 2,
            },
            {
                "title": "Updated files",
                "detail": "2 files: src/one.py, src/two.py",
            },
        ),
        (
            "workspace_diff",
            {
                "kind": "report",
                "path": "release.md",
                "revision_id": "rev-secret",
                "diff": "-token=sk-secret123\n+token=removed",
                "truncated": False,
            },
            {
                "title": "Workspace changes",
                "detail": "report/release.md",
                "content": "-token=[REDACTED]\n+token=removed",
                "truncated": False,
            },
        ),
        (
            "workspace_restore",
            {
                "kind": "reports",
                "path": "release.md",
                "restored_revision_id": "revision-secret",
                "previous_sha256": "a" * 64,
                "sha256": "b" * 64,
                "bytes": 42,
                "updated_at": "2026-01-01T00:00:00Z",
            },
            {
                "title": "Restored workspace asset",
                "detail": "reports/release.md",
            },
        ),
        (
            "open_url",
            {
                "url": "https://example.com/path?token=secret-value",
                "opened": True,
                "application": "Google Chrome",
                "command": "open secret input",
            },
            {
                "title": "Opened URL",
                "detail": "https://example.com/path?token=[REDACTED]",
            },
        ),
        (
            "open_app",
            {"application": "Preview", "opened": True, "command": "open -a"},
            {"title": "Opened application", "detail": "Preview"},
        ),
        (
            "http_request",
            {
                "url": "https://example.com/api?api_key=secret-value",
                "status_code": 200,
                "content_type": "application/json",
                "body_text": "must not be projected",
            },
            {
                "title": "Fetched URL",
                "detail": (
                    "200 · application/json · "
                    "https://example.com/api?api_key=[REDACTED]"
                ),
            },
        ),
        (
            "shell_command",
            {
                "command": "printf secret-input",
                "cwd": ".",
                "exit_code": 0,
                "stdout": "ok\nsk-secret123",
                "stderr": "warning",
                "duration_seconds": 0.125,
                "timed_out": False,
                "truncated": False,
            },
            {
                "title": "Command completed",
                "detail": "Exit 0 · 0.125s",
                "content": "ok\n[REDACTED]\nwarning",
                "truncated": False,
            },
        ),
    ]

    for tool, output, expected in cases:
        presentation = project_runtime_presentation(tool, "ok", output)

        assert presentation == expected
        serialized = json.dumps(presentation)
        assert "artifact-secret" not in serialized
        assert "rev-secret" not in serialized
        assert "secret input" not in serialized
        assert "secret-input" not in serialized
        assert "body_text" not in serialized


def test_projection_returns_empty_for_failures_and_non_presentable_tools():
    assert project_runtime_presentation("artifact", "failed", {"title": "No"}) == {}
    assert project_runtime_presentation("note", "ok", {"text": "internal"}) == {}
    assert project_runtime_presentation("read_file", "ok", {"content": "internal"}) == {}
    assert project_runtime_presentation("list_files", "ok", {"files": ["a"]}) == {}
    assert project_runtime_presentation("unknown", "ok", {"title": "internal"}) == {}


def test_projection_bounds_content_and_combines_existing_truncation():
    presentation = project_runtime_presentation(
        "shell_command",
        "ok",
        {
            "exit_code": 0,
            "stdout": "x" * 5000,
            "stderr": "",
            "duration_seconds": 1,
            "truncated": False,
        },
    )

    assert len(presentation["content"]) == 4000
    assert presentation["truncated"] is True

    artifact = project_runtime_presentation(
        "artifact",
        "ok",
        {
            "title": "Large report",
            "kind": "report",
            "format": "markdown",
            "content": "x" * 4000,
        },
    )
    assert len(artifact["content"]) == 4000
    assert artifact["truncated"] is False


def test_projection_redacts_environment_style_credentials_from_content():
    presentation = project_runtime_presentation(
        "shell_command",
        "ok",
        {
            "exit_code": 0,
            "stdout": (
                "AWS_SECRET_ACCESS_KEY=very-secret-aws-value\n"
                '"GITHUB_TOKEN": "github-secret-value"'
            ),
            "stderr": "",
        },
    )

    assert "very-secret-aws-value" not in presentation["content"]
    assert "github-secret-value" not in presentation["content"]
    assert presentation["content"].count("[REDACTED]") == 2


def test_runtime_agent_adds_presentation_only_to_presentable_tool_completion():
    provider = FakeLLMProvider(
        '{"actions":['
        '{"id":"artifact-action-secret","tool":"artifact",'
        '"input":{"title":"Status report","kind":"report",'
        '"format":"markdown","content":"Ready"},"reason":"create"},'
        '{"id":"note-action-secret","tool":"note",'
        '"input":{"text":"internal note"},"reason":"capture"}'
        '],"final_answer":"done"}'
    )

    result = run_runtime_agent("prepare status", provider=provider)
    completed = [
        event for event in result["progress_events"]
        if event["type"] == "tool_completed"
    ]

    assert completed[0]["presentation"] == {
        "title": "Created Status report",
        "detail": "Report · Markdown · 5 bytes",
        "content": "Ready",
        "truncated": False,
    }
    assert "presentation" not in completed[1]
    presentation_json = json.dumps(completed[0]["presentation"])
    assert "artifact" not in presentation_json.lower()
    assert "artifact-action-secret" not in presentation_json
    assert "input" not in completed[0]["presentation"]


def test_projects_safe_artifact_start_without_exposing_raw_input():
    presentation = project_runtime_start_presentation(
        "artifact",
        {"title": "Release sk-secret123", "content": "Bearer abcdef"},
    )

    assert presentation == {
        "title": "Creating Release [REDACTED]",
        "detail": "Preparing an artifact",
    }
    serialized = json.dumps(presentation)
    assert "Bearer" not in serialized


def test_projects_fixed_safe_start_for_supported_runtime_tools():
    expected = {
        "apply_patch": ("Updating workspace files", "Preparing a reviewed change"),
        "workspace_diff": (
            "Inspecting workspace changes",
            "Preparing a safe comparison",
        ),
        "workspace_restore": (
            "Restoring workspace asset",
            "Preparing a reviewed restore",
        ),
        "open_url": ("Opening requested page", "Preparing a local browser action"),
        "open_app": (
            "Opening requested application",
            "Preparing a local application action",
        ),
        "http_request": ("Fetching requested URL", "Preparing a network request"),
        "shell_command": ("Running approved command", "Preparing a bounded command"),
    }

    for tool, (title, detail) in expected.items():
        presentation = project_runtime_start_presentation(
            tool,
            {"secret": "raw secret input"},
        )

        assert presentation == {"title": title, "detail": detail}
        serialized = json.dumps(presentation)
        assert tool not in serialized
        assert "raw secret input" not in serialized


def test_runtime_agent_adds_safe_start_presentation_only_when_available():
    provider = FakeLLMProvider(
        '{"actions":['
        '{"id":"artifact-action-secret","tool":"artifact",'
        '"input":{"title":"Status report","kind":"report",'
        '"format":"markdown","content":"Bearer secret-value"},'
        '"reason":"create"},'
        '{"id":"note-action-secret","tool":"note",'
        '"input":{"text":"internal note"},"reason":"capture"}'
        '],"final_answer":"done"}'
    )

    result = run_runtime_agent("prepare status", provider=provider)
    started = [
        event
        for event in result["progress_events"]
        if event["type"] == "tool_started"
    ]

    assert started[0]["presentation"] == {
        "title": "Creating Status report",
        "detail": "Preparing an artifact",
    }
    assert "presentation" in started[1]
    assert started[1].get("presentation") is None
    assert "resolved_input" not in started[0]
    serialized = json.dumps(started[0]["presentation"])
    assert "artifact-action-secret" not in serialized
    assert "note-action-secret" not in serialized
    assert "secret-value" not in serialized


def test_direct_action_graph_emits_safe_start_presentation_for_every_tool():
    cases = [
        (
            "artifact",
            {
                "title": "Release sk-secret123",
                "kind": "report",
                "format": "markdown",
                "content": "Bearer secret-value",
            },
            {
                "title": "Creating Release [REDACTED]",
                "detail": "Preparing an artifact",
            },
        ),
        ("note", {"text": "internal secret-value"}, None),
        ("read_file", {"path": "secret-value.txt"}, None),
    ]

    for tool, input_value, expected in cases:
        provider = FakeLLMProvider(
            json.dumps(
                {
                    "actions": [
                        {
                            "id": f"{tool}-action-secret",
                            "tool": tool,
                            "input": input_value,
                            "reason": "run",
                        }
                    ],
                    "final_answer": "done",
                }
            )
        )

        result = run_runtime_agent("prepare status", provider=provider)
        started = [
            event
            for event in result["progress_events"]
            if event["type"] == "tool_started"
        ]

        assert len(started) == 1
        assert "presentation" in started[0]
        assert started[0]["presentation"] == expected
        assert "input" not in started[0]
        serialized = json.dumps(started[0]["presentation"])
        assert f"{tool}-action-secret" not in serialized
        assert "secret-value" not in serialized
