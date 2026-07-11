import json

from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import run_runtime_agent
from kagent.runtime.presentation import project_runtime_presentation


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
