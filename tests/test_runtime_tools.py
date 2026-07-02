import json
import time

from self_correcting_langgraph_agent.runtime import tools as runtime_tools
from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime.tools import (
    RuntimeToolSpec,
    default_runtime_tools,
    execute_runtime_tool,
    registered_runtime_tool_metadata,
)


def test_note_tool_returns_structured_observation():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "note",
        {"text": "remember this"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.tool == "note"
    assert observation.action_id == "step-1"
    assert observation.output == {"text": "remember this"}


def test_read_file_tool_reads_text_file_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "docs" / "brief.md"
    target.parent.mkdir()
    target.write_text("# Brief\n\nready\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "read_file",
        {"path": "docs/brief.md"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output["path"] == "docs/brief.md"
    assert observation.output["content"] == "# Brief\n\nready\n"
    assert observation.output["bytes"] == len("# Brief\n\nready\n".encode("utf-8"))
    assert observation.output["truncated"] is False
    assert len(observation.output["sha256"]) == 64


def test_read_file_tool_truncates_large_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "large.txt"
    target.write_text("abcdef", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "read_file",
        {"path": "large.txt", "max_bytes": 3},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output["content"] == "abc"
    assert observation.output["bytes"] == 3
    assert observation.output["truncated"] is True


def test_read_file_tool_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "read_file",
        {"path": "../outside-secret.txt"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "path must stay inside the workspace" in observation.error


def test_list_files_tool_lists_workspace_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "brief.md").write_text("ready\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "list_files",
        {"path": ".", "max_depth": 2},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output["root"] == "."
    assert observation.output["truncated"] is False
    assert observation.output["file_count"] == 3
    assert observation.output["entries"] == [
        {"path": "README.md", "type": "file", "bytes": 6},
        {"path": "docs", "type": "directory", "bytes": 0},
        {"path": "docs/brief.md", "type": "file", "bytes": 6},
    ]


def test_list_files_tool_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "list_files",
        {"path": ".."},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "path must stay inside the workspace" in observation.error


def test_apply_patch_tool_adds_file_inside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: docs/pilot.md\n"
                "+# 试运行计划\n"
                "+\n"
                "+第一版。\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    created = tmp_path / "docs" / "pilot.md"
    assert observation.status == "ok"
    assert created.read_text(encoding="utf-8") == "# 试运行计划\n\n第一版。\n"
    assert observation.output["file_count"] == 1
    assert observation.output["changed_files"][0]["path"] == "docs/pilot.md"
    assert observation.output["changed_files"][0]["operation"] == "add"
    assert observation.output["changed_files"][0]["bytes"] == len(
        "# 试运行计划\n\n第一版。\n".encode("utf-8")
    )
    assert len(observation.output["changed_files"][0]["sha256"]) == 64


def test_apply_patch_tool_accepts_add_file_content_without_plus_prefix(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: example.md\n"
                "# 示例 Markdown 文件\n"
                "\n"
                "这是模型生成的普通 markdown 内容。\n"
                "\n"
                "```python\n"
                "print(\"hello\")\n"
                "```\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert (tmp_path / "example.md").read_text(encoding="utf-8") == (
        "# 示例 Markdown 文件\n\n"
        "这是模型生成的普通 markdown 内容。\n\n"
        "```python\n"
        "print(\"hello\")\n"
        "```\n"
    )


def test_apply_patch_tool_updates_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "notes.md"
    target.write_text("# Notes\n\nold line\nkeep me\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: notes.md\n"
                "@@\n"
                " # Notes\n"
                " \n"
                "-old line\n"
                "+new line\n"
                " keep me\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert target.read_text(encoding="utf-8") == "# Notes\n\nnew line\nkeep me\n"
    assert observation.output["file_count"] == 1
    assert observation.output["changed_files"][0]["path"] == "notes.md"
    assert observation.output["changed_files"][0]["operation"] == "update"


def test_apply_patch_tool_deletes_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "obsolete.md"
    target.write_text("remove me\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Delete File: obsolete.md\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert not target.exists()
    assert observation.output["file_count"] == 1
    assert observation.output["changed_files"][0]["path"] == "obsolete.md"
    assert observation.output["changed_files"][0]["operation"] == "delete"


def test_apply_patch_tool_rejects_update_when_context_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "notes.md"
    target.write_text("keep this\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Update File: notes.md\n"
                "@@\n"
                "-missing line\n"
                "+replacement\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "update context not found" in observation.error
    assert target.read_text(encoding="utf-8") == "keep this\n"


def test_apply_patch_tool_rejects_delete_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "docs"
    target.mkdir()

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Delete File: docs\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "path is a directory" in observation.error
    assert target.is_dir()


def test_apply_patch_tool_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: ../outside.md\n"
                "+nope\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "path must stay inside the workspace" in observation.error
    assert not (tmp_path.parent / "outside.md").exists()


def test_apply_patch_tool_rejects_overwriting_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "README.md"
    existing.write_text("keep me\n", encoding="utf-8")

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n"
                "*** Add File: README.md\n"
                "+replace\n"
                "*** End Patch\n"
            )
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "file already exists" in observation.error
    assert existing.read_text(encoding="utf-8") == "keep me\n"


def test_runtime_tool_times_out_slow_handler():
    def slow_handler(_input_payload):
        time.sleep(0.05)
        return {"text": "late"}

    registry = {
        "slow": RuntimeToolSpec(
            name="slow",
            description="slow tool",
            handler=slow_handler,
            timeout_seconds=0.01,
            output_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "slow",
        {},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "tool_execution_timeout"
    assert observation.error == "tool execution exceeded timeout"
    assert float(observation.duration_seconds) < 0.05


def test_http_request_tool_fetches_text_response_after_approval(monkeypatch):
    class FakeHeaders:
        def get(self, name, default=""):
            if name == "Content-Type":
                return "application/json"
            return default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return json.dumps({"message": "hello-http-tool"}).encode("utf-8")

    class FakeNoRedirectOpener:
        def open(self, _request, *, timeout):
            assert timeout > 0
            return FakeResponse()

    monkeypatch.setattr(
        runtime_tools.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                runtime_tools.socket.AF_INET,
                runtime_tools.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runtime_tools.urllib.error.URLError("unexpected redirect follow")
        ),
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "build_opener",
        lambda *_handlers: FakeNoRedirectOpener(),
    )

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "http_request",
        {"url": "https://example.com/data", "max_bytes": 1024},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output["status_code"] == 200
    assert observation.output["url"] == "https://example.com/data"
    assert observation.output["content_type"] == "application/json"
    assert observation.output["body_text"] == '{"message": "hello-http-tool"}'
    assert observation.output["truncated"] is False


def test_http_request_tool_rejects_private_and_loopback_targets():
    for url in [
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
    ]:
        observation = execute_runtime_tool(
            default_runtime_tools(),
            "http_request",
            {"url": url},
            action_id="step-1",
        )

        assert observation.status == "failed"
        assert observation.error_code == "invalid_tool_input"
        assert "url host is not allowed" in observation.error


def test_http_request_tool_does_not_follow_redirects(monkeypatch):
    class FakeHeaders:
        def get(self, name, default=""):
            if name == "Content-Type":
                return "text/plain"
            return default

    class FakeRedirectResponse:
        status = 302
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return b""

    class FakeNoRedirectOpener:
        def open(self, _request, *, timeout):
            assert timeout > 0
            return FakeRedirectResponse()

    monkeypatch.setattr(
        runtime_tools.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                runtime_tools.socket.AF_INET,
                runtime_tools.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runtime_tools.urllib.error.URLError("unexpected redirect follow")
        ),
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "build_opener",
        lambda *_handlers: FakeNoRedirectOpener(),
    )

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "http_request",
        {"url": "https://example.com/redirect"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output["status_code"] == 302
    assert observation.output["body_text"] == ""


def test_open_url_tool_opens_http_url_with_chrome_applescript_first(monkeypatch):
    calls = []

    class FakeSubprocess:
        CalledProcessError = RuntimeError

        @staticmethod
        def run(args, *, check, capture_output, text):
            calls.append(
                {
                    "args": args,
                    "check": check,
                    "capture_output": capture_output,
                    "text": text,
                }
            )

    monkeypatch.setattr(runtime_tools, "subprocess", FakeSubprocess, raising=False)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "open_url",
        {"url": " https://github.com "},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.tool == "open_url"
    assert observation.output == {
        "url": "https://github.com",
        "opened": True,
        "application": "Google Chrome",
        "command": "osascript Google Chrome",
    }
    assert len(calls) == 1
    assert calls[0]["args"][0] == "osascript"
    assert calls[0]["args"][1] == "-e"
    assert 'URL:"https://github.com"' in calls[0]["args"][2]
    assert "active tab index" in calls[0]["args"][2]
    assert calls[0]["check"] is True
    assert calls[0]["capture_output"] is True
    assert calls[0]["text"] is True


def test_open_url_tool_falls_back_when_chrome_applescript_fails(monkeypatch):
    calls = []

    class FakeCalledProcessError(Exception):
        pass

    class FakeSubprocess:
        CalledProcessError = FakeCalledProcessError

        @staticmethod
        def run(args, *, check, capture_output, text):
            calls.append(args)
            if args[0] == "osascript":
                raise FakeCalledProcessError()

    monkeypatch.setattr(runtime_tools, "subprocess", FakeSubprocess, raising=False)

    observation = execute_runtime_tool(
        default_runtime_tools(),
        "open_url",
        {"url": "https://github.com"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "url": "https://github.com",
        "opened": True,
        "application": "Google Chrome",
        "command": "open -a Google Chrome",
    }
    assert calls[0][0] == "osascript"
    assert calls[1] == ["open", "-a", "Google Chrome", "https://github.com"]


def test_open_url_tool_rejects_non_http_urls():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "open_url",
        {"url": "file:///etc/passwd"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "url must start with http:// or https://" in observation.error


def test_runtime_tool_observation_includes_timing_metadata():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "note",
        {"text": "timed"},
        action_id="step-1",
    ).to_dict()

    assert observation["started_at"].endswith("+00:00")
    assert observation["completed_at"].endswith("+00:00")
    assert float(observation["duration_seconds"]) >= 0
    assert observation["duration_seconds"].count(".") == 1
    assert len(observation["duration_seconds"].split(".")[1]) == 4


def test_runtime_tool_specs_expose_input_schemas_for_planning():
    tools = default_runtime_tools()

    assert tools["apply_patch"].input_schema == {
        "type": "object",
        "required": ["patch"],
        "properties": {
            "patch": {"type": "string", "minLength": 1, "maxLength": 20000}
        },
        "additionalProperties": False,
    }
    assert tools["artifact"].input_schema == {
        "type": "object",
        "required": ["title", "kind", "content"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "kind": {
                "type": "string",
                "enum": ["report", "plan", "decision", "data", "message"],
            },
            "content": {"type": "string", "minLength": 1, "maxLength": 20000},
            "format": {
                "type": "string",
                "enum": ["markdown", "plain_text", "json"],
            },
            "tags": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }
    assert tools["note"].input_schema == {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string", "maxLength": 20000}},
        "additionalProperties": False,
    }
    assert tools["decision_matrix"].input_schema["required"] == [
        "question",
        "criteria",
        "options",
    ]
    assert tools["decision_matrix"].input_schema["properties"]["criteria"]["items"][
        "properties"
    ]["name"] == {"type": "string", "minLength": 1, "maxLength": 200}
    assert tools["decision_matrix"].input_schema["properties"]["criteria"]["items"][
        "properties"
    ]["weight"] == {"type": "number", "minimum": 0}
    assert tools["decision_matrix"].input_schema["properties"]["criteria"][
        "maxItems"
    ] == 20
    assert tools["decision_matrix"].input_schema["properties"]["options"][
        "maxItems"
    ] == 50
    assert tools["open_url"].input_schema == {
        "type": "object",
        "required": ["url"],
        "properties": {"url": {"type": "string", "minLength": 1, "maxLength": 2048}},
        "additionalProperties": False,
    }
    assert tools["transform_text"].input_schema["required"] == ["text", "mode"]
    assert tools["transform_text"].input_schema["properties"]["mode"]["enum"] == [
        "uppercase",
        "lowercase",
        "reverse",
        "trim",
    ]
    assert tools["task_list"].input_schema["required"] == ["items"]
    assert (
        tools["task_list"].input_schema["properties"]["items"]["items"]["properties"][
            "title"
        ]
        == {"type": "string", "minLength": 1, "maxLength": 500}
    )
    assert tools["task_list"].input_schema["properties"]["items"]["maxItems"] == 200


def test_runtime_tool_specs_expose_output_schemas_for_planning_and_clients():
    tools = default_runtime_tools()

    assert tools["apply_patch"].output_schema["required"] == [
        "changed_files",
        "file_count",
    ]
    assert tools["apply_patch"].output_schema["properties"]["changed_files"]["items"][
        "properties"
    ]["operation"]["enum"] == ["add", "update", "delete"]
    assert tools["artifact"].output_schema == {
        "type": "object",
        "required": ["artifact_id", "title", "kind", "format", "content", "tags", "bytes"],
        "properties": {
            "artifact_id": {"type": "string"},
            "title": {"type": "string"},
            "kind": {"type": "string", "enum": ["report", "plan", "decision", "data", "message"]},
            "format": {"type": "string", "enum": ["markdown", "plain_text", "json"]},
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "bytes": {"type": "number", "minimum": 0},
        },
        "additionalProperties": False,
    }
    assert tools["note"].output_schema == {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
        "additionalProperties": False,
    }
    assert tools["open_url"].output_schema == {
        "type": "object",
        "required": ["url", "opened", "application", "command"],
        "properties": {
            "url": {"type": "string"},
            "opened": {"type": "boolean"},
            "application": {"type": "string"},
            "command": {"type": "string"},
        },
        "additionalProperties": False,
    }
    assert tools["transform_text"].output_schema == tools["note"].output_schema
    assert tools["decision_matrix"].output_schema["required"] == [
        "question",
        "criteria",
        "rankings",
        "winner",
    ]
    assert tools["rubric_score"].output_schema["properties"]["score_percent"] == {
        "type": "number",
        "minimum": 0,
        "maximum": 100,
    }
    assert tools["task_list"].output_schema["properties"]["counts"]["properties"] == {
        "pending": {"type": "number", "minimum": 0},
        "in_progress": {"type": "number", "minimum": 0},
        "blocked": {"type": "number", "minimum": 0},
        "done": {"type": "number", "minimum": 0},
    }


def test_runtime_tool_rejects_string_shorter_than_schema_min_length():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"text": input_payload["text"]},
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string", "minLength": 2}},
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "custom",
        {"text": "x"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.text must contain at least 2 character(s)" in observation.error


def test_runtime_tool_rejects_string_longer_than_schema_max_length():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"text": input_payload["text"]},
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string", "maxLength": 3}},
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "custom",
        {"text": "abcd"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.text must contain at most 3 character(s)" in observation.error


def test_runtime_tool_rejects_array_longer_than_schema_max_items():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"items": input_payload["items"]},
            input_schema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {"type": "string"},
                    }
                },
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "custom",
        {"items": ["one", "two", "three"]},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.items must contain at most 2 item(s)" in observation.error


def test_runtime_tool_rejects_number_outside_schema_bounds():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"score": input_payload["score"]},
            input_schema={
                "type": "object",
                "required": ["score"],
                "properties": {
                    "score": {"type": "number", "minimum": 0, "maximum": 5}
                },
                "additionalProperties": False,
            },
        )
    }

    low_observation = execute_runtime_tool(
        registry,
        "custom",
        {"score": -1},
        action_id="step-1",
    )
    high_observation = execute_runtime_tool(
        registry,
        "custom",
        {"score": 6},
        action_id="step-2",
    )

    assert low_observation.status == "failed"
    assert low_observation.error_code == "invalid_tool_input"
    assert "input.score must be at least 0" in low_observation.error
    assert high_observation.status == "failed"
    assert high_observation.error_code == "invalid_tool_input"
    assert "input.score must be at most 5" in high_observation.error


def test_runtime_tool_rejects_non_boolean_for_boolean_schema():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"approved": input_payload["approved"]},
            input_schema={
                "type": "object",
                "required": ["approved"],
                "properties": {"approved": {"type": "boolean"}},
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "custom",
        {"approved": "true"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.approved must be a boolean" in observation.error


def test_runtime_tool_rejects_handler_output_that_violates_output_schema():
    registry = {
        "custom": RuntimeToolSpec(
            name="custom",
            description="custom tool",
            handler=lambda input_payload: {"unexpected": input_payload["text"]},
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
        )
    }

    observation = execute_runtime_tool(
        registry,
        "custom",
        {"text": "hello"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_output"
    assert "output.text is required" in observation.error
    assert observation.output == {}


def test_decision_matrix_tool_rejects_negative_weight_via_schema():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "decision_matrix",
        {
            "question": "Pick launch path",
            "criteria": [{"name": "impact", "weight": -0.1}],
            "options": [
                {"name": "A", "scores": [1]},
                {"name": "B", "scores": [2]},
            ],
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.criteria[0].weight must be at least 0" in observation.error


def test_registered_runtime_tool_metadata_includes_input_schemas():
    metadata = registered_runtime_tool_metadata()
    by_name = {item["name"]: item for item in metadata}

    assert sorted(by_name) == [
        "apply_patch",
        "artifact",
        "decision_matrix",
        "http_request",
        "list_files",
        "note",
        "open_url",
        "read_file",
        "rubric_score",
        "task_list",
        "transform_text",
    ]
    assert by_name["apply_patch"]["approval_required_by_default"] == "false"
    assert "*** Add File:" in metadata[0]["description"]
    assert by_name["apply_patch"]["timeout_seconds"] == "30.0"
    assert by_name["apply_patch"]["input_schema"]["required"] == ["patch"]
    assert by_name["apply_patch"]["output_schema"]["required"] == [
        "changed_files",
        "file_count",
    ]
    assert by_name["artifact"]["approval_required_by_default"] == "false"
    assert by_name["artifact"]["timeout_seconds"] == "30.0"
    assert by_name["artifact"]["input_schema"]["required"] == [
        "title",
        "kind",
        "content",
    ]
    assert by_name["artifact"]["output_schema"]["required"] == [
        "artifact_id",
        "title",
        "kind",
        "format",
        "content",
        "tags",
        "bytes",
    ]
    assert by_name["decision_matrix"]["input_schema"]["required"] == [
        "question",
        "criteria",
        "options",
    ]
    assert by_name["decision_matrix"]["output_schema"]["required"] == [
        "question",
        "criteria",
        "rankings",
        "winner",
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
    assert by_name["note"]["approval_required_by_default"] == "false"
    assert by_name["note"]["input_schema"]["required"] == ["text"]
    assert by_name["note"]["output_schema"]["required"] == ["text"]
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
    assert by_name["task_list"]["input_schema"]["required"] == ["items"]
    assert by_name["task_list"]["output_schema"]["required"] == [
        "items",
        "counts",
        "total",
    ]
    assert by_name["transform_text"]["input_schema"]["properties"]["mode"]["enum"] == [
        "uppercase",
        "lowercase",
        "reverse",
        "trim",
    ]
    assert by_name["transform_text"]["output_schema"]["required"] == ["text"]


def test_transform_text_tool_supports_uppercase_mode():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "transform_text",
        {"text": "Agent Runtime", "mode": "uppercase"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {"text": "AGENT RUNTIME"}


def test_artifact_tool_records_structured_artifact_observation():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "artifact",
        {
            "title": " Launch plan ",
            "kind": "plan",
            "content": "# Ship\nDo the rollout.",
            "format": "markdown",
            "tags": [" release ", "", "ops"],
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "artifact_id": "artifact_edbaf40bdeab",
        "title": "Launch plan",
        "kind": "plan",
        "format": "markdown",
        "content": "# Ship\nDo the rollout.",
        "tags": ["release", "ops"],
        "bytes": 22,
    }


def test_artifact_tool_rejects_blank_content():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "artifact",
        {"title": "Empty", "kind": "report", "content": "   "},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "content" in observation.error


def test_decision_matrix_tool_ranks_options_by_weighted_score():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "decision_matrix",
        {
            "question": "Pick launch path",
            "criteria": [
                {"name": "impact", "weight": 0.7},
                {"name": "confidence", "weight": 0.3},
            ],
            "options": [
                {
                    "name": "Manual rollout",
                    "scores": [3, 4],
                    "rationale": "Simple but slower.",
                },
                {
                    "name": "Automated rollout",
                    "scores": [4, 4],
                    "rationale": "More leverage with same confidence.",
                },
            ],
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "question": "Pick launch path",
        "criteria": [
            {"name": "impact", "weight": 0.7},
            {"name": "confidence", "weight": 0.3},
        ],
        "rankings": [
            {
                "rank": 1,
                "name": "Automated rollout",
                "score": 4.0,
                "scores": [4.0, 4.0],
                "rationale": "More leverage with same confidence.",
            },
            {
                "rank": 2,
                "name": "Manual rollout",
                "score": 3.3,
                "scores": [3.0, 4.0],
                "rationale": "Simple but slower.",
            },
        ],
        "winner": "Automated rollout",
    }


def test_decision_matrix_tool_rejects_non_numeric_weight():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "decision_matrix",
        {
            "question": "Pick launch path",
            "criteria": [{"name": "impact", "weight": "high"}],
            "options": [
                {"name": "A", "scores": [1]},
                {"name": "B", "scores": [2]},
            ],
        },
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "input.criteria[0].weight must be a number" in observation.error


def test_rubric_score_tool_summarizes_passed_criteria():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "rubric_score",
        {
            "criteria": [
                {
                    "name": "Executable",
                    "passed": True,
                    "evidence": "runtime/run returns done",
                },
                {
                    "name": "Documented",
                    "passed": False,
                    "severity": "blocking",
                    "evidence": "missing operator docs",
                },
            ]
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "criteria": [
            {
                "name": "Executable",
                "passed": True,
                "severity": "normal",
                "evidence": "runtime/run returns done",
            },
            {
                "name": "Documented",
                "passed": False,
                "severity": "blocking",
                "evidence": "missing operator docs",
            },
        ],
        "passed": 1,
        "failed": 1,
        "total": 2,
        "score_percent": 50.0,
        "blocking_failures": ["Documented"],
        "failed_criteria": ["Documented"],
    }


def test_task_list_tool_normalizes_items_and_counts_statuses():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "task_list",
        {
            "items": [
                {"title": "Clarify goal", "priority": "high"},
                {"title": "Ship runbook", "status": "done", "owner": "ops"},
            ]
        },
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "items": [
            {
                "title": "Clarify goal",
                "status": "pending",
                "priority": "high",
            },
            {
                "title": "Ship runbook",
                "status": "done",
                "priority": "normal",
                "owner": "ops",
            },
        ],
        "counts": {"pending": 1, "in_progress": 0, "blocked": 0, "done": 1},
        "total": 2,
    }


def test_task_list_tool_rejects_invalid_status():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "task_list",
        {"items": [{"title": "bad", "status": "later"}]},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "status" in observation.error


def test_runtime_tool_rejects_input_properties_not_declared_in_schema():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "note",
        {"text": "ok", "extra": "nope"},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "extra" in observation.error


def test_runtime_tool_rejects_nested_properties_not_declared_in_schema():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "task_list",
        {"items": [{"title": "Plan", "unknown": "nope"}]},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "invalid_tool_input"
    assert "unknown" in observation.error


def test_unknown_runtime_tool_returns_structured_error():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "missing_tool",
        {},
        action_id="step-1",
    )

    assert observation.status == "failed"
    assert observation.error_code == "tool_not_found"


def test_policy_blocks_disallowed_tool_before_execution():
    decision = RuntimePolicy(allowed_tools={"note"}).authorize(
        "http_request",
        {"url": "http://x"},
    )

    assert decision.status == "denied"
    assert decision.reason == "tool_not_allowed"


def test_policy_allows_registered_tool():
    decision = RuntimePolicy(allowed_tools={"note"}).authorize("note", {"text": "ok"})

    assert decision.status == "allowed"
    assert decision.reason == ""


def test_default_policy_allows_task_list_tool():
    decision = RuntimePolicy().authorize("task_list", {"items": [{"title": "Plan"}]})

    assert decision.status == "allowed"


def test_default_policy_allows_open_url_tool():
    decision = RuntimePolicy().authorize("open_url", {"url": "https://github.com"})

    assert decision.status == "allowed"


def test_default_policy_allows_workspace_read_tools():
    policy = RuntimePolicy()

    assert policy.authorize("read_file", {"path": "README.md"}).status == "allowed"
    assert policy.authorize("list_files", {"path": "."}).status == "allowed"


def test_default_policy_allows_artifact_tool():
    decision = RuntimePolicy().authorize(
        "artifact",
        {"title": "Report", "kind": "report", "content": "Ready"},
    )

    assert decision.status == "allowed"


def test_default_policy_allows_decision_matrix_tool():
    decision = RuntimePolicy().authorize(
        "decision_matrix",
        {
            "question": "Pick",
            "criteria": [{"name": "impact", "weight": 1.0}],
            "options": [{"name": "A", "scores": [1]}, {"name": "B", "scores": [2]}],
        },
    )

    assert decision.status == "allowed"


def test_default_policy_allows_rubric_score_tool():
    decision = RuntimePolicy().authorize(
        "rubric_score",
        {"criteria": [{"name": "Ready", "passed": True}]},
    )

    assert decision.status == "allowed"
