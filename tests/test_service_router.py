import json
import os
import time
from pathlib import Path

from self_correcting_langgraph_agent.runtime import tools as runtime_tools
from self_correcting_langgraph_agent.runtime.types import (
    MAX_PLAN_ACTIONS,
    MAX_PLAN_FINAL_ANSWER_CHARS,
)
from self_correcting_langgraph_agent.service import router as service_router
from self_correcting_langgraph_agent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    SqliteServiceIdempotencyCache,
)
from self_correcting_langgraph_agent.service.trace_store import persist_trace


def _mock_public_http_request(monkeypatch, body: bytes = b"ok") -> str:
    class FakeHeaders:
        def get(self, name, default=""):
            if name == "Content-Type":
                return "text/plain"
            return default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return body

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
    return "https://example.com/data"


def test_service_router_handles_health_without_http_handler():
    status_code, payload = service_router.handle_request("GET", "/health", b"")

    assert status_code == 200
    assert payload == {"status": "ok"}


def test_service_router_metrics_snapshot_includes_limiters():
    metrics = ServiceMetrics(started_at=0.0)
    metrics.record(path="/health", status_code=200, duration_seconds=0.1)
    rate_limiter = ServiceRateLimiter(limit_per_minute=3)
    concurrency_limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)

    status_code, payload = service_router.handle_request(
        "GET",
        "/metrics",
        b"",
        metrics=metrics,
        rate_limiter=rate_limiter,
        concurrency_limiter=concurrency_limiter,
    )

    assert status_code == 200
    assert payload["requests_total"] == "1"
    assert payload["rate_limit_per_minute"] == "3"
    assert payload["max_concurrent_runs"] == "2"


def test_service_router_can_protect_diagnostic_endpoints_with_bearer_auth(tmp_path):
    config = ServiceConfig(
        auth_token="secret",
        protect_diagnostics=True,
        trace_dir=str(tmp_path),
    )

    protected_routes = [
        "/config",
        "/tools",
        "/runtime/tools",
        "/runtime/policy",
        "/metrics",
        "/metrics.prom",
        "/openapi.json",
        "/runtime/approvals",
        "/runtime/runs",
    ]

    for route in protected_routes:
        status_code, payload = service_router.handle_request("GET", route, b"", config=config)

        assert status_code == 401
        assert payload == {
            "status": "failed",
            "error_code": "unauthorized",
            "error": "unauthorized",
        }

    for route in protected_routes:
        status_code, payload = service_router.handle_request(
            "GET",
            route,
            b"",
            headers={"Authorization": "Bearer secret"},
            config=config,
        )

        assert status_code == 200
        assert payload


def test_service_router_runtime_policy_reports_admin_audit_view_without_tokens():
    config = ServiceConfig(
        auth_token="admin-token",
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
        runtime_allowed_tools=("note", "task_list"),
        runtime_allowed_tools_by_subject={
            "team-a": ("note",),
            "team-b": ("artifact", "note"),
        },
        protect_diagnostics=True,
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/policy",
        b"",
        headers={"Authorization": "Bearer admin-token"},
        config=config,
    )

    assert status_code == 200
    assert payload["trace_type"] == "codex_runtime"
    assert payload["auth_subject"] == "default"
    assert payload["is_admin"] == "true"
    assert payload["global_allowed_tools"] == ["note", "task_list"]
    assert payload["subject_policy_count"] == "2"
    assert payload["subject_allowed_tools"] == {
        "team-a": ["note"],
        "team-b": ["artifact", "note"],
    }
    assert payload["effective_policy_source"] == "global"
    assert payload["effective_allowed_tools"] == ["note", "task_list"]
    assert len(payload["effective_tool_policy_sha256"]) == 64
    assert payload["effective_tool_policy"] == [
        {"name": "apply_patch", "allowed": "false", "approval_required": "true"},
        {"name": "artifact", "allowed": "false", "approval_required": "true"},
        {
            "name": "decision_matrix",
            "allowed": "false",
            "approval_required": "true",
        },
        {"name": "http_request", "allowed": "false", "approval_required": "true"},
        {"name": "list_files", "allowed": "false", "approval_required": "true"},
        {"name": "note", "allowed": "true", "approval_required": "false"},
        {"name": "open_url", "allowed": "false", "approval_required": "true"},
        {"name": "read_file", "allowed": "false", "approval_required": "true"},
        {"name": "rubric_score", "allowed": "false", "approval_required": "true"},
        {"name": "task_list", "allowed": "true", "approval_required": "false"},
        {
            "name": "transform_text",
            "allowed": "false",
            "approval_required": "true",
        },
    ]
    assert "admin-token" not in json.dumps(payload)
    assert "team-a-token" not in json.dumps(payload)
    assert "team-b-token" not in json.dumps(payload)


def test_service_router_runtime_policy_scopes_subject_audit_view():
    config = ServiceConfig(
        auth_token="admin-token",
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
        runtime_allowed_tools=("note", "task_list"),
        runtime_allowed_tools_by_subject={
            "team-a": ("note",),
            "team-b": ("artifact", "note"),
        },
        protect_diagnostics=True,
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/policy",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    assert status_code == 200
    assert payload["auth_subject"] == "team-a"
    assert payload["is_admin"] == "false"
    assert payload["subject_policy_count"] == "2"
    assert payload["subject_allowed_tools"] == {"team-a": ["note"]}
    assert payload["effective_policy_source"] == "subject"
    assert payload["effective_allowed_tools"] == ["note"]
    assert len(payload["effective_tool_policy_sha256"]) == 64
    assert payload["effective_tool_policy"] == [
        {"name": "apply_patch", "allowed": "false", "approval_required": "true"},
        {"name": "artifact", "allowed": "false", "approval_required": "true"},
        {
            "name": "decision_matrix",
            "allowed": "false",
            "approval_required": "true",
        },
        {"name": "http_request", "allowed": "false", "approval_required": "true"},
        {"name": "list_files", "allowed": "false", "approval_required": "true"},
        {"name": "note", "allowed": "true", "approval_required": "false"},
        {"name": "open_url", "allowed": "false", "approval_required": "true"},
        {"name": "read_file", "allowed": "false", "approval_required": "true"},
        {"name": "rubric_score", "allowed": "false", "approval_required": "true"},
        {"name": "task_list", "allowed": "false", "approval_required": "true"},
        {
            "name": "transform_text",
            "allowed": "false",
            "approval_required": "true",
        },
    ]
    assert payload["effective_tool_policy_sha256"] != ""
    assert "team-b" not in json.dumps(payload)
    assert "team-a-token" not in json.dumps(payload)
    assert "team-b-token" not in json.dumps(payload)


def test_service_router_keeps_probe_and_version_routes_public_when_diagnostics_are_protected():
    config = ServiceConfig(auth_token="secret", protect_diagnostics=True)

    for route in ["/health", "/ready", "/version"]:
        status_code, payload = service_router.handle_request("GET", route, b"", config=config)

        assert status_code == 200
        assert payload


def test_service_router_reuses_run_response_for_matching_idempotency_key():
    calls = []
    cache = ServiceIdempotencyCache(max_entries=8)
    body = b'{"goal": "calculate 2 + 3"}'

    def runner(goal, config):
        calls.append(goal)
        return {
            "run_id": f"run-{len(calls)}",
            "status": "done",
            "answer": "5",
            "events": [],
            "tool_calls": [],
            "verification_results": [],
            "plan": [],
        }

    first_status, first_payload = service_router.handle_request(
        "POST",
        "/run",
        body,
        headers={"Idempotency-Key": "retry-123"},
        config=ServiceConfig(idempotency_cache_size=8),
        idempotency_cache=cache,
        agent_runner=runner,
    )
    second_status, second_payload = service_router.handle_request(
        "POST",
        "/run",
        body,
        headers={"Idempotency-Key": "retry-123"},
        config=ServiceConfig(idempotency_cache_size=8),
        idempotency_cache=cache,
        agent_runner=runner,
    )

    assert first_status == 200
    assert second_status == 200
    assert first_payload == second_payload
    assert calls == ["calculate 2 + 3"]


def test_service_router_scopes_idempotency_cache_by_execution_route():
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(idempotency_cache_size=8)
    headers = {"Idempotency-Key": "retry-123"}
    body = b'{"goal":"capture route scope","plan":{"actions":[],"final_answer":"runtime"}}'

    def runner(goal, config):
        return {
            "run_id": "deterministic-run",
            "status": "done",
            "answer": "deterministic",
            "events": [],
            "tool_calls": [],
            "verification_results": [],
            "plan": [],
        }

    run_status, run_payload = service_router.handle_request(
        "POST",
        "/run",
        body,
        headers=headers,
        config=config,
        idempotency_cache=cache,
        agent_runner=runner,
    )
    runtime_status, runtime_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )

    assert run_status == 200
    assert run_payload["run_id"] == "deterministic-run"
    assert runtime_status == 200
    assert runtime_payload["trace_type"] == "codex_runtime"
    assert runtime_payload["answer"] == "runtime"


def test_service_router_scopes_idempotency_cache_by_internal_auth_subject():
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(
        idempotency_cache_size=8,
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
    )
    body = b'{"goal": "calculate 2 + 3"}'
    headers_a = {
        "Authorization": "Bearer team-a-token",
        "Idempotency-Key": "retry-123",
    }
    headers_b = {
        "Authorization": "Bearer team-b-token",
        "Idempotency-Key": "retry-123",
    }

    first_status, first_payload = service_router.handle_request(
        "POST",
        "/run",
        body,
        headers=headers_a,
        config=config,
        idempotency_cache=cache,
    )
    second_status, second_payload = service_router.handle_request(
        "POST",
        "/run",
        body,
        headers=headers_b,
        config=config,
        idempotency_cache=cache,
    )

    assert first_status == 200
    assert second_status == 200
    assert first_payload["run_id"] != second_payload["run_id"]
    assert cache.snapshot()["idempotency_cache_entries"] == "2"


def test_service_router_runtime_idempotency_cache_isolated_by_internal_auth_subject(
    tmp_path,
):
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        idempotency_cache_size=8,
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
    )
    body = b'{"goal":"capture hello","plan":{"actions":[],"final_answer":"done"}}'
    headers_a = {
        "Authorization": "Bearer team-a-token",
        "Idempotency-Key": "retry-123",
    }
    headers_b = {
        "Authorization": "Bearer team-b-token",
        "Idempotency-Key": "retry-123",
    }

    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        headers=headers_a,
        config=config,
        idempotency_cache=cache,
    )
    second_status, second_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        headers=headers_b,
        config=config,
        idempotency_cache=cache,
    )

    assert first_status == 200
    assert second_status == 200
    assert first_payload["auth_subject"] == "team-a"
    assert second_payload["auth_subject"] == "team-b"
    assert first_payload["run_id"] != second_payload["run_id"]
    assert cache.snapshot()["idempotency_cache_entries"] == "2"


def test_service_router_runs_codex_style_runtime_with_fake_plan_payload():
    body = (
        b'{"goal":"capture hello","plan":{"actions":[{"id":"step-1",'
        b'"tool":"note","input":{"text":"hello"},"reason":"capture"}]}}'
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["plan"]["actions"][0]["tool"] == "note"
    assert payload["observations"][0]["output"] == {"text": "hello"}


def test_service_router_reports_codex_style_runtime_tool_metadata():
    status_code, payload = service_router.handle_request("GET", "/runtime/tools", b"")
    by_name = {item["name"]: item for item in payload["tools"]}

    assert status_code == 200
    assert by_name["apply_patch"]["approval_required_by_default"] == "false"
    assert by_name["apply_patch"]["input_schema"]["required"] == ["patch"]
    assert by_name["apply_patch"]["output_schema"]["required"] == [
        "changed_files",
        "file_count",
    ]
    assert by_name["artifact"]["approval_required_by_default"] == "false"
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
    assert by_name["transform_text"]["output_schema"]["required"] == ["text"]


def test_service_router_runtime_run_can_execute_artifact_tool():
    body = (
        b'{"goal":"write launch plan","plan":{"actions":[{"id":"step-1",'
        b'"tool":"artifact","input":{"title":"Launch plan","kind":"plan",'
        b'"content":"# Ship\\nDo the rollout.","tags":["release"]},'
        b'"reason":"produce artifact"}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["observations"][0]["output"]["artifact_id"] == "artifact_edbaf40bdeab"
    assert payload["observations"][0]["output"]["kind"] == "plan"
    assert payload["observations"][0]["output"]["tags"] == ["release"]


def test_service_router_runtime_status_summarizes_artifacts(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"write launch plan","plan":{"actions":[{"id":"step-1",'
            b'"tool":"artifact","input":{"title":"Launch plan","kind":"plan",'
            b'"content":"# Ship\\nDo the rollout.","tags":["release"]},'
            b'"reason":"produce artifact"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["artifact_count"] == "1"
    assert payload["artifact_ids"] == ["artifact_edbaf40bdeab"]


def test_service_router_runtime_timeline_returns_compact_run_timeline(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"write launch plan","plan":{"actions":[{"id":"step-1",'
            b'"tool":"artifact","input":{"title":"Launch plan","kind":"plan",'
            b'"content":"# Ship\\nDo the rollout.","tags":["release"]},'
            b'"reason":"produce artifact"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/timeline",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["trace_type"] == "codex_runtime"
    assert payload["run_id"] == run_payload["run_id"]
    assert payload["trace_path"] == run_payload["trace_path"]
    assert payload["event_count"] == "3"
    assert payload["progress_event_count"] == "6"
    assert payload["observation_count"] == "1"
    assert [event["node"] for event in payload["events"]] == [
        "planner",
        "policy",
        "executor",
    ]
    assert payload["observations"] == [
        {
            "action_id": "step-1",
            "tool": "artifact",
            "status": "ok",
            "artifact_id": "artifact_edbaf40bdeab",
        }
    ]
    assert [event["type"] for event in payload["progress_events"]] == [
        "planner_started",
        "planner_completed",
        "policy_completed",
        "tool_started",
        "tool_completed",
        "run_completed",
    ]
    assert payload["progress_events"][3]["tool"] == "artifact"
    assert all("input" not in event for event in payload["events"])
    assert all("input" not in event for event in payload["progress_events"])
    assert all("output" not in observation for observation in payload["observations"])


def test_service_router_runtime_timeline_keeps_dependency_metadata(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"capture dependency timeline","plan":{"actions":['
            b'{"id":"step-1","tool":"note","input":{"text":"ready"},'
            b'"reason":"capture"},'
            b'{"id":"step-2","tool":"note","input":{"text":"done"},'
            b'"reason":"persist","depends_on":["step-1"]}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/timeline",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    dependent_policy_event = payload["events"][3]
    dependent_executor_event = payload["events"][4]
    assert dependent_policy_event["depends_on"] == ["step-1"]
    assert dependent_policy_event["dependency_statuses"] == {"step-1": "ok"}
    assert dependent_executor_event["depends_on"] == ["step-1"]
    assert dependent_executor_event["dependency_statuses"] == {"step-1": "ok"}


def test_service_router_runtime_timeline_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/run-123/timeline",
        b"",
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_timeline_hides_non_runtime_trace(tmp_path):
    persist_trace(
        {"run_id": "legacy-run", "status": "done", "goal": "legacy task", "events": []},
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/legacy-run/timeline",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_timeline_reports_unreadable_trace_as_structured_error(
    tmp_path,
):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/broken/timeline",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "trace_read_failed",
        "error": "runtime run trace could not be read",
    }


def test_service_router_runtime_artifacts_lists_persisted_artifact_metadata(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"write launch artifacts","plan":{"actions":['
            b'{"id":"step-1","tool":"artifact","input":{"title":"Launch plan",'
            b'"kind":"plan","content":"# Ship\\nDo the rollout.",'
            b'"tags":["release"]},"reason":"produce plan"},'
            b'{"id":"step-2","tool":"artifact","input":{"title":"Ops note",'
            b'"kind":"message","content":"Watch rollout metrics.",'
            b'"format":"plain_text","tags":["ops"]},"reason":"produce note"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/artifacts",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["trace_type"] == "codex_runtime"
    assert payload["run_id"] == run_payload["run_id"]
    assert payload["trace_path"] == run_payload["trace_path"]
    assert payload["count"] == "2"
    assert payload["artifacts"] == [
        {
            "artifact_id": "artifact_edbaf40bdeab",
            "action_id": "step-1",
            "tool": "artifact",
            "title": "Launch plan",
            "kind": "plan",
            "format": "markdown",
            "tags": ["release"],
            "bytes": "22",
        },
        {
            "artifact_id": "artifact_bc228b091dfd",
            "action_id": "step-2",
            "tool": "artifact",
            "title": "Ops note",
            "kind": "message",
            "format": "plain_text",
            "tags": ["ops"],
            "bytes": "22",
        },
    ]
    assert all("content" not in artifact for artifact in payload["artifacts"])


def test_service_router_runtime_artifacts_returns_empty_manifest(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture runtime","plan":{"actions":[],"final_answer":"runtime"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/artifacts",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["count"] == "0"
    assert payload["artifacts"] == []


def test_service_router_runtime_artifacts_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/run-123/artifacts",
        b"",
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_artifacts_hides_non_runtime_trace(tmp_path):
    persist_trace(
        {
            "run_id": "legacy-run",
            "status": "done",
            "goal": "legacy task",
            "observations": [{"output": {"artifact_id": "artifact-123"}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/legacy-run/artifacts",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_artifacts_reports_unreadable_trace_as_structured_error(
    tmp_path,
):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/broken/artifacts",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "trace_read_failed",
        "error": "runtime run trace could not be read",
    }


def test_service_router_runtime_artifact_returns_one_persisted_artifact(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"write launch plan","plan":{"actions":[{"id":"step-1",'
            b'"tool":"artifact","input":{"title":"Launch plan","kind":"plan",'
            b'"content":"# Ship\\nDo the rollout.","tags":["release"]},'
            b'"reason":"produce artifact"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/artifacts/artifact_edbaf40bdeab",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["trace_type"] == "codex_runtime"
    assert payload["run_id"] == run_payload["run_id"]
    assert payload["trace_path"] == run_payload["trace_path"]
    assert payload["action_id"] == "step-1"
    assert payload["tool"] == "artifact"
    assert payload["artifact"] == {
        "artifact_id": "artifact_edbaf40bdeab",
        "title": "Launch plan",
        "kind": "plan",
        "format": "markdown",
        "content": "# Ship\nDo the rollout.",
        "tags": ["release"],
        "bytes": 22,
    }


def test_service_router_runtime_artifact_reports_missing_artifact(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture runtime","plan":{"actions":[],"final_answer":"runtime"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}/artifacts/missing-artifact",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_artifact_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/run-123/artifacts/artifact-123",
        b"",
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_artifact_hides_non_runtime_trace(tmp_path):
    persist_trace(
        {
            "run_id": "legacy-run",
            "status": "done",
            "goal": "legacy task",
            "observations": [{"output": {"artifact_id": "artifact-123"}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/legacy-run/artifacts/artifact-123",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_artifact_reports_unreadable_trace_as_structured_error(
    tmp_path,
):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/broken/artifacts/artifact-123",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "trace_read_failed",
        "error": "runtime run trace could not be read",
    }


def test_service_router_runtime_run_can_execute_decision_matrix_tool():
    body = (
        b'{"goal":"pick launch path","plan":{"actions":[{"id":"step-1",'
        b'"tool":"decision_matrix","input":{"question":"Pick launch path",'
        b'"criteria":[{"name":"impact","weight":0.7},{"name":"confidence",'
        b'"weight":0.3}],"options":[{"name":"Manual rollout",'
        b'"scores":[3,4]},{"name":"Automated rollout","scores":[4,4]}]},'
        b'"reason":"rank options"}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["observations"][0]["output"]["winner"] == "Automated rollout"
    assert payload["observations"][0]["output"]["rankings"][0]["score"] == 4.0


def test_service_router_runtime_run_can_execute_task_list_tool():
    body = (
        b'{"goal":"plan launch","plan":{"actions":[{"id":"step-1",'
        b'"tool":"task_list","input":{"items":[{"title":"Write runbook",'
        b'"priority":"high"},{"title":"Open dashboard","status":"done"}]},'
        b'"reason":"structure work"}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["observations"][0]["output"]["counts"] == {
        "pending": 1,
        "in_progress": 0,
        "blocked": 0,
        "done": 1,
    }


def test_service_router_runtime_run_can_execute_rubric_score_tool():
    body = json.dumps(
        {
            "goal": "review launch readiness",
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "rubric_score",
                        "input": {
                            "criteria": [
                                {"name": "Runnable", "passed": True},
                                {
                                    "name": "Documented",
                                    "passed": False,
                                    "severity": "blocking",
                                },
                            ]
                        },
                        "reason": "score readiness",
                    }
                ]
            },
        }
    ).encode()

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["observations"][0]["output"]["score_percent"] == 50.0
    assert payload["observations"][0]["output"]["blocking_failures"] == ["Documented"]


def test_service_router_runtime_run_accepts_iteration_limit():
    body = (
        b'{"goal":"capture twice","max_iterations":2,'
        b'"plan":{"actions":[{"id":"step-1","tool":"note",'
        b'"input":{"text":"hello"},"reason":"capture"}]}}'
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert len(payload["plans"]) == 2
    assert len(payload["observations"]) == 2


def test_service_router_runtime_run_accepts_plan_sequence_for_replanning():
    body = (
        b'{"goal":"trim hello","max_iterations":2,'
        b'"plan_sequence":['
        b'{"actions":[{"id":"step-1","tool":"transform_text",'
        b'"input":{"text":" hello ","mode":"strip"},"reason":"normalize"}]},'
        b'{"actions":[{"id":"step-2","tool":"transform_text",'
        b'"input":{"text":" hello ","mode":"trim"},"reason":"retry"}],'
        b'"final_answer":"trimmed"}]}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert len(payload["plans"]) == 2
    assert payload["observations"][0]["status"] == "failed"
    assert payload["observations"][0]["error_code"] == "invalid_tool_input"
    assert payload["observations"][1]["output"] == {"text": "hello"}
    assert payload["answer"] == "trimmed"


def test_service_router_runtime_run_replans_after_invalid_plan_sequence_item():
    body = (
        b'{"goal":"recover bad plan","max_iterations":2,'
        b'"plan_sequence":['
        b'{"actions":"bad"},'
        b'{"actions":[{"id":"step-1","tool":"note",'
        b'"input":{"text":"recovered"},"reason":"recover"}],'
        b'"final_answer":"recovered"}]}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["observations"][0]["tool"] == "planner"
    assert payload["observations"][0]["error_code"] == "invalid_plan"
    assert payload["observations"][1]["output"] == {"text": "recovered"}
    assert payload["answer"] == "recovered"


def test_service_router_runtime_run_rejects_plan_and_plan_sequence_together():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture","plan":{"actions":[]},"plan_sequence":[{"actions":[]}]}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "plan_sequence" in payload["error"]


def test_service_router_runtime_run_rejects_invalid_plan_sequence():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture","plan_sequence":[]}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "plan_sequence" in payload["error"]


def test_service_router_runtime_run_accepts_approved_action_ids(monkeypatch):
    url = _mock_public_http_request(monkeypatch, b"approved fetch")
    body = json.dumps(
        {
            "goal": "fetch approved URL",
            "approved_action_ids": ["step-1"],
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "http_request",
                        "input": {"url": url},
                        "reason": "fetch",
                    }
                ]
            },
        }
    ).encode("utf-8")
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["approved_action_ids"] == ["step-1"]
    assert payload["approved_action_count"] == "1"
    assert payload["events"][1]["status"] == "approved"
    assert payload["observations"][0]["status"] == "ok"
    assert payload["observations"][0]["output"]["status_code"] == 200
    assert payload["observations"][0]["output"]["body_text"] == "approved fetch"


def test_service_router_runtime_run_rejects_invalid_approved_action_ids():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","approved_action_ids":[123],"plan":{"actions":[]}}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "approved_action_ids" in payload["error"]


def test_service_router_runtime_run_rejects_blank_approved_action_ids():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","approved_action_ids":[""],"plan":{"actions":[]}}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "approved_action_ids" in payload["error"]


def test_service_router_runtime_run_rejects_duplicate_approved_action_ids():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"capture hello","approved_action_ids":["step-1","step-1"],'
            b'"plan":{"actions":[]}}'
        ),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "duplicate" in payload["error"]


def test_service_router_runtime_run_reports_duplicate_action_ids_as_invalid_plan():
    body = (
        b'{"goal":"capture","plan":{"actions":['
        b'{"id":"step-1","tool":"note","input":{"text":"one"}},'
        b'{"id":"step-1","tool":"note","input":{"text":"two"}}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert "duplicate action id" in payload["error"]


def test_service_router_runtime_run_reports_whitespace_action_id_as_invalid_plan():
    body = (
        b'{"goal":"capture","plan":{"actions":['
        b'{"id":" step-1 ","tool":"note","input":{"text":"one"}}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert "action id must not contain surrounding whitespace" in payload["error"]


def test_service_router_runtime_run_preserves_action_dependencies():
    body = (
        b'{"goal":"capture then report","plan":{"actions":['
        b'{"id":"step-1","tool":"note","input":{"text":"hello"}},'
        b'{"id":"step-2","tool":"artifact","input":{"title":"Report",'
        b'"kind":"report","content":"ready"},"depends_on":["step-1"]}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["plan"]["actions"][1]["depends_on"] == ["step-1"]
    assert payload["observations"][1]["output"]["title"] == "Report"


def test_service_router_runtime_run_reports_unknown_dependency_as_invalid_plan():
    body = (
        b'{"goal":"bad dependency","plan":{"actions":['
        b'{"id":"step-1","tool":"note","input":{"text":"hello"},'
        b'"depends_on":["missing"]}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert "unknown or later action dependency" in payload["error"]


def test_service_router_runtime_run_reports_unknown_plan_field_as_invalid_plan():
    body = b'{"goal":"bad plan","plan":{"actions":[],"unexpected":true}}'

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert "plan field is not allowed" in payload["error"]


def test_service_router_runtime_run_reports_unknown_action_field_as_invalid_plan():
    body = (
        b'{"goal":"bad action","plan":{"actions":[{"id":"step-1",'
        b'"tool":"note","input":{"text":"hello"},"unexpected":true}]}}'
    )

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert "action field is not allowed" in payload["error"]


def test_service_router_runtime_run_reports_too_many_actions_as_invalid_plan():
    body = json.dumps(
        {
            "goal": "capture",
            "plan": {
                "actions": [
                    {
                        "id": f"step-{index}",
                        "tool": "note",
                        "input": {"text": "hello"},
                    }
                    for index in range(1, MAX_PLAN_ACTIONS + 2)
                ]
            },
        }
    ).encode()

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert f"plan actions must contain at most {MAX_PLAN_ACTIONS}" in payload["error"]


def test_service_router_runtime_run_reports_too_long_final_answer_as_invalid_plan():
    body = json.dumps(
        {
            "goal": "capture",
            "plan": {
                "actions": [],
                "final_answer": "x" * (MAX_PLAN_FINAL_ANSWER_CHARS + 1),
            },
        }
    ).encode()

    status_code, payload = service_router.handle_request("POST", "/runtime/run", body)

    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_plan"
    assert (
        f"final_answer must contain at most {MAX_PLAN_FINAL_ANSWER_CHARS}"
        in payload["error"]
    )


def test_service_router_runtime_resume_continues_persisted_pending_approval(
    tmp_path,
    monkeypatch,
):
    url = _mock_public_http_request(monkeypatch, b"resumed fetch")
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        json.dumps(
            {
                "goal": "fetch site",
                "plan": {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "http_request",
                            "input": {"url": url},
                            "reason": "fetch",
                        }
                    ]
                },
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-1"],
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    resumed_trace_path = Path(resume_payload["trace_path"])
    resumed_trace = json.loads(resumed_trace_path.read_text())

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 200
    assert resume_payload["status"] == "done"
    assert resume_payload["resumed_from_run_id"] == first_payload["run_id"]
    assert resume_payload["approved_action_ids"] == ["step-1"]
    assert resume_payload["approved_action_count"] == "1"
    assert resume_payload["events"][1]["status"] == "approved"
    assert resume_payload["observations"][0]["status"] == "ok"
    assert resume_payload["observations"][0]["output"]["status_code"] == 200
    assert resume_payload["observations"][0]["output"]["body_text"] == "resumed fetch"
    assert resumed_trace["resumed_from_run_id"] == first_payload["run_id"]
    assert resumed_trace["approved_action_ids"] == ["step-1"]
    assert resumed_trace["approved_action_count"] == "1"


def test_service_router_runtime_resume_preserves_metadata_and_tags(
    tmp_path,
    monkeypatch,
):
    url = _mock_public_http_request(monkeypatch, b"resumed fetch")
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        json.dumps(
            {
                "goal": "fetch site",
                "metadata": {"workflow": "launch"},
                "tags": ["release"],
                "plan": {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "http_request",
                            "input": {"url": url},
                            "reason": "fetch",
                        }
                    ]
                },
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-1"],
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    resumed_trace = json.loads(Path(resume_payload["trace_path"]).read_text())

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 200
    assert resume_payload["status"] == "done"
    assert resume_payload["metadata"] == {"workflow": "launch"}
    assert resume_payload["tags"] == ["release"]
    assert resumed_trace["metadata"] == {"workflow": "launch"}
    assert resumed_trace["tags"] == ["release"]


def test_service_router_runtime_resume_hides_cross_subject_pending_run(
    tmp_path,
    monkeypatch,
):
    url = _mock_public_http_request(monkeypatch, b"resumed fetch")
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
    )
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        json.dumps(
            {
                "goal": "fetch site",
                "plan": {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "http_request",
                            "input": {"url": url},
                            "reason": "fetch",
                        }
                    ]
                },
            }
        ).encode("utf-8"),
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-1"],
            }
        ).encode("utf-8"),
        headers={"Authorization": "Bearer team-b-token"},
        config=config,
    )

    assert first_status == 200
    assert first_payload["auth_subject"] == "team-a"
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 404
    assert resume_payload["error_code"] == "not_found"


def test_service_router_runtime_resume_allows_primary_token_for_any_subject_run(
    tmp_path,
    monkeypatch,
):
    url = _mock_public_http_request(monkeypatch, b"resumed fetch")
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_token="primary-admin-token",
        auth_tokens={"team-a": "team-a-token"},
    )
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        json.dumps(
            {
                "goal": "fetch site",
                "plan": {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "http_request",
                            "input": {"url": url},
                            "reason": "fetch",
                        }
                    ]
                },
            }
        ).encode("utf-8"),
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-1"],
            }
        ).encode("utf-8"),
        headers={"Authorization": "Bearer primary-admin-token"},
        config=config,
    )

    assert first_status == 200
    assert first_payload["auth_subject"] == "team-a"
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 200
    assert resume_payload["status"] == "done"
    assert resume_payload["auth_subject"] == "team-a"
    assert resume_payload["resumed_by_auth_subject"] == "default"
    assert resume_payload["resumed_from_run_id"] == first_payload["run_id"]
    resumed_trace = json.loads(Path(resume_payload["trace_path"]).read_text())
    detail_status, detail_payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{resume_payload['run_id']}",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )
    list_status, list_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?auth_subject=team-a&limit=10",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    assert resumed_trace["auth_subject"] == "team-a"
    assert resumed_trace["resumed_by_auth_subject"] == "default"
    assert detail_status == 200
    assert detail_payload["auth_subject"] == "team-a"
    assert detail_payload["resumed_by_auth_subject"] == "default"
    assert list_status == 200
    resumed_items = [
        run for run in list_payload["runs"] if run["run_id"] == resume_payload["run_id"]
    ]
    assert resumed_items[0]["resumed_by_auth_subject"] == "default"


def test_service_router_runtime_resume_rejects_non_pending_approved_action_id(tmp_path):
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-2"],
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 400
    assert resume_payload["error_code"] == "invalid_request_body"
    assert "pending approval action id" in resume_payload["error"]


def test_service_router_runtime_resume_rejects_extra_approved_action_ids(tmp_path):
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    resume_status, resume_payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        json.dumps(
            {
                "run_id": first_payload["run_id"],
                "approved_action_ids": ["step-1", "step-2"],
            }
        ).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert resume_status == 400
    assert resume_payload["error_code"] == "invalid_request_body"
    assert "only the pending approval action id" in resume_payload["error"]


def test_service_router_runtime_resume_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"run-123","approved_action_ids":["step-1"]}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_resume_reports_missing_run(tmp_path):
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"missing","approved_action_ids":["step-1"]}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_resume_rejects_non_runtime_trace(tmp_path):
    persist_trace(
        {
            "run_id": "legacy-run",
            "status": "requires_approval",
            "goal": "legacy task",
            "pending_approval": {"id": "step-1"},
            "plan": {"actions": []},
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"legacy-run","approved_action_ids":["step-1"]}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_resume_reports_unreadable_trace_as_structured_error(tmp_path):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"broken","approved_action_ids":["step-1"]}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "trace_read_failed",
        "error": "runtime run trace could not be read",
    }


def test_service_router_runtime_cancel_marks_pending_run_cancelled(tmp_path):
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_tokens={"team-a": "team-a-token"},
    )
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{first_payload['run_id']}/cancel",
        b"{}",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )
    detail_status, detail_payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{first_payload['run_id']}",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )
    approval_status, approval_payload = service_router.handle_request(
        "GET",
        "/runtime/approvals",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    persisted_trace = json.loads(Path(first_payload["trace_path"]).read_text())

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert cancel_status == 200
    assert cancel_payload["trace_type"] == "codex_runtime"
    assert cancel_payload["run_id"] == first_payload["run_id"]
    assert cancel_payload["status"] == "cancelled"
    assert cancel_payload["cancelled_by_auth_subject"] == "team-a"
    assert cancel_payload["pending_approval_action_id"] == ""
    assert cancel_payload["pending_approval_tool"] == ""
    assert "pending_approval" not in cancel_payload
    assert detail_status == 200
    assert detail_payload["status"] == "cancelled"
    assert detail_payload["cancelled_by_auth_subject"] == "team-a"
    assert approval_status == 200
    assert approval_payload["count"] == "0"
    assert persisted_trace["status"] == "cancelled"
    assert persisted_trace["cancelled_by_auth_subject"] == "team-a"
    assert "pending_approval" not in persisted_trace


def test_service_router_runtime_cancel_hides_cross_subject_run(tmp_path):
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
    )
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{first_payload['run_id']}/cancel",
        b"{}",
        headers={"Authorization": "Bearer team-b-token"},
        config=config,
    )
    persisted_trace = json.loads(Path(first_payload["trace_path"]).read_text())

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert cancel_status == 404
    assert cancel_payload["error_code"] == "not_found"
    assert persisted_trace["status"] == "requires_approval"


def test_service_router_runtime_cancel_rejects_terminal_run(tmp_path):
    config = ServiceConfig(trace_dir=str(tmp_path))
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture","plan":{"actions":[],"final_answer":"done"}}',
        config=config,
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{first_payload['run_id']}/cancel",
        b"{}",
        config=config,
    )
    persisted_trace = json.loads(Path(first_payload["trace_path"]).read_text())

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert cancel_status == 409
    assert cancel_payload["error_code"] == "invalid_request_body"
    assert "already terminal" in cancel_payload["error"]
    assert persisted_trace["status"] == "done"


def test_service_router_runtime_cancel_idempotency_is_scoped_to_run_id(tmp_path):
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(trace_dir=str(tmp_path), idempotency_cache_size=8)
    run_body = (
        b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
        b'"tool":"http_request","input":{"url":"https://example.com"},'
        b'"reason":"fetch"}]}}'
    )
    cancel_headers = {"Idempotency-Key": "cancel-retry"}

    first_run_status, first_run = service_router.handle_request(
        "POST",
        "/runtime/run",
        run_body,
        config=config,
        idempotency_cache=cache,
    )
    second_run_status, second_run = service_router.handle_request(
        "POST",
        "/runtime/run",
        run_body,
        config=config,
        idempotency_cache=cache,
    )
    first_cancel_status, first_cancel = service_router.handle_request(
        "POST",
        f"/runtime/runs/{first_run['run_id']}/cancel",
        b"{}",
        headers=cancel_headers,
        config=config,
        idempotency_cache=cache,
    )
    second_cancel_status, second_cancel = service_router.handle_request(
        "POST",
        f"/runtime/runs/{second_run['run_id']}/cancel",
        b"{}",
        headers=cancel_headers,
        config=config,
        idempotency_cache=cache,
    )
    first_trace = json.loads(Path(first_run["trace_path"]).read_text())
    second_trace = json.loads(Path(second_run["trace_path"]).read_text())

    assert first_run_status == 200
    assert second_run_status == 200
    assert first_run["run_id"] != second_run["run_id"]
    assert first_cancel_status == 200
    assert second_cancel_status == 200
    assert first_cancel["run_id"] == first_run["run_id"]
    assert second_cancel["run_id"] == second_run["run_id"]
    assert first_trace["status"] == "cancelled"
    assert second_trace["status"] == "cancelled"
    assert cache.snapshot()["idempotency_cache_entries"] == "2"


def test_service_router_runtime_cancel_rejects_overlong_reason(tmp_path):
    config = ServiceConfig(trace_dir=str(tmp_path))
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        config=config,
    )

    cancel_status, cancel_payload = service_router.handle_request(
        "POST",
        f"/runtime/runs/{first_payload['run_id']}/cancel",
        json.dumps({"reason": "x" * 501}).encode("utf-8"),
        config=config,
    )
    persisted_trace = json.loads(Path(first_payload["trace_path"]).read_text())

    assert first_status == 200
    assert first_payload["status"] == "requires_approval"
    assert cancel_status == 400
    assert cancel_payload["error_code"] == "invalid_request_body"
    assert cancel_payload["error"] == "reason must be at most 500 characters"
    assert persisted_trace["status"] == "requires_approval"
    assert "cancel_reason" not in persisted_trace


def test_service_router_runtime_status_reports_persisted_run_summary(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["run_id"] == run_payload["run_id"]
    assert payload["trace_type"] == "codex_runtime"
    assert payload["status"] == "requires_approval"
    assert payload["goal"] == "fetch site"
    assert payload["trace_path"] == run_payload["trace_path"]
    assert payload["duration_seconds"] == run_payload["duration_seconds"]
    assert payload["approved_action_count"] == "0"
    assert payload["approved_action_ids"] == []
    assert payload["iteration_count"] == "1"
    assert payload["max_iterations"] == "1"
    assert payload["iteration_budget_remaining"] == "0"
    assert payload["plan_count"] == "1"
    assert payload["observation_count"] == "1"
    assert payload["event_count"] == "2"
    assert payload["failed_observation_count"] == "0"
    assert payload["approval_required_count"] == "1"
    assert payload["pending_approval_action_id"] == "step-1"
    assert payload["pending_approval_tool"] == "http_request"
    assert payload["tool_names"] == ["http_request"]


def test_service_router_runtime_status_reports_final_answer_guardrail(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "identity-guardrail",
            "status": "done",
            "goal": "你是谁",
            "answer": "我是 self-correcting LangGraph agent runtime。",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
            "plans": [{"actions": [], "final_answer": "我是通义千问。"}],
            "observations": [],
            "events": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/identity-guardrail",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["final_answer_guardrail"] == {
        "applied": "true",
        "reason": "runtime_identity_boundary",
        "original_answer_omitted": "true",
    }
    assert "events" not in payload
    assert "observations" not in payload


def test_service_router_runtime_status_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/run-123",
        b"",
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_status_reports_missing_run(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/missing",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_status_hides_non_runtime_trace(tmp_path):
    persist_trace(
        {"run_id": "legacy-run", "status": "done", "goal": "legacy task", "events": []},
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/legacy-run",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 404
    assert payload["error_code"] == "not_found"


def test_service_router_runtime_status_reports_unreadable_trace_as_structured_error(tmp_path):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/broken",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "trace_read_failed",
        "error": "runtime run trace could not be read",
    }


def test_service_router_runtime_runs_list_reports_persisted_summaries(tmp_path):
    first_status, first_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture one","plan":{"actions":[],"final_answer":"one"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    second_status, second_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch site","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    run_ids = {run["run_id"] for run in payload["runs"]}

    assert first_status == 200
    assert second_status == 200
    assert status_code == 200
    assert payload["count"] == "2"
    assert run_ids == {first_payload["run_id"], second_payload["run_id"]}
    assert all("plan_count" in run for run in payload["runs"])
    assert all("latest_plan_action_count" in run for run in payload["runs"])
    assert all("latest_plan_action_ids" in run for run in payload["runs"])
    assert all("observation_count" in run for run in payload["runs"])
    assert all("event_count" in run for run in payload["runs"])
    assert all("duration_seconds" in run for run in payload["runs"])
    assert all("failed_observation_count" in run for run in payload["runs"])
    assert all("planner_failure_count" in run for run in payload["runs"])
    assert all("tool_failure_count" in run for run in payload["runs"])
    assert all("approval_required_count" in run for run in payload["runs"])
    assert all("pending_approval_action_id" in run for run in payload["runs"])
    assert all("pending_approval_tool" in run for run in payload["runs"])
    assert all("approved_action_count" in run for run in payload["runs"])
    assert all("approved_action_ids" in run for run in payload["runs"])
    assert all("error_code_counts" in run for run in payload["runs"])
    assert all("dependency_edge_count" in run for run in payload["runs"])
    assert all("tool_names" in run for run in payload["runs"])
    assert all("artifact_count" in run for run in payload["runs"])
    assert all("artifact_ids" in run for run in payload["runs"])
    assert all("artifact_kinds" in run for run in payload["runs"])
    assert all("artifact_formats" in run for run in payload["runs"])
    assert all("artifact_tags" in run for run in payload["runs"])
    assert all("artifact_total_bytes" in run for run in payload["runs"])
    assert all("artifact_bytes_by_kind" in run for run in payload["runs"])
    assert all("events" not in run for run in payload["runs"])
    assert all("observations" not in run for run in payload["runs"])


def test_service_router_runtime_runs_summary_aggregates_visible_traces(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-failed",
            "status": "failed",
            "goal": "fetch launch brief",
            "auth_subject": "team-a",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [
                {
                    "action_id": "fetch-site",
                    "tool": "http_request",
                    "status": "failed",
                    "error_code": "tool_execution_timeout",
                },
                {
                    "action_id": "write-report",
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-team-a",
                        "title": "Launch brief",
                        "kind": "report",
                        "format": "markdown",
                        "tags": ["release"],
                        "bytes": "120",
                    },
                },
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "ops-pending",
            "status": "requires_approval",
            "goal": "fetch vendor status",
            "auth_subject": "ops",
            "pending_approval": {"id": "ops-fetch", "tool": "http_request"},
            "observations": [
                {
                    "action_id": "ops-fetch",
                    "tool": "http_request",
                    "status": "requires_approval",
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {"run_id": "legacy-run", "status": "failed", "auth_subject": "team-a"},
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/summary",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload == {
        "trace_type": "codex_runtime",
        "run_count": "2",
        "status_counts": {"failed": "1", "requires_approval": "1"},
        "auth_subject_counts": {"ops": "1", "team-a": "1"},
        "tool_counts": {"artifact": "1", "http_request": "2"},
        "error_code_counts": {"tool_execution_timeout": "1"},
        "failed_observation_count": "1",
        "approval_required_count": "1",
        "pending_approval_count": "1",
        "final_answer_guardrail_applied_count": "1",
        "final_answer_guardrail_reason_counts": {
            "runtime_identity_boundary": "1"
        },
        "artifact_count": "1",
        "artifact_total_bytes": "120",
        "tag_counts": {},
        "metadata_key_counts": {},
    }


def test_service_router_runtime_runs_summary_respects_subject_visibility(tmp_path):
    for subject in ["team-a", "ops"]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": f"{subject}-run",
                "status": "done",
                "goal": f"{subject} goal",
                "auth_subject": subject,
                "observations": [
                    {
                        "action_id": "note",
                        "tool": "note",
                        "status": "ok",
                    }
                ],
            },
            str(tmp_path),
        )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/summary",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_token="admin-token",
            auth_tokens={"team-a": "team-a-token"},
        ),
    )

    assert status_code == 200
    assert payload["run_count"] == "1"
    assert payload["auth_subject_counts"] == {"team-a": "1"}
    assert payload["status_counts"] == {"done": "1"}


def test_service_router_runtime_runs_summary_applies_existing_filters(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "failed-http",
            "status": "failed",
            "goal": "fetch status",
            "auth_subject": "team-a",
            "observations": [
                {
                    "action_id": "fetch-site",
                    "tool": "http_request",
                    "status": "failed",
                    "error_code": "tool_execution_timeout",
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "done-note",
            "status": "done",
            "goal": "record note",
            "auth_subject": "team-a",
            "observations": [
                {
                    "action_id": "note",
                    "tool": "note",
                    "status": "ok",
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/summary?status=failed&tool=http_request",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["run_count"] == "1"
    assert payload["status_counts"] == {"failed": "1"}
    assert payload["tool_counts"] == {"http_request": "1"}


def test_service_router_runtime_approvals_lists_pending_actions_without_inputs(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-pending",
            "status": "requires_approval",
            "goal": "fetch launch vendor",
            "auth_subject": "team-a",
            "trace_path": str(tmp_path / "team-a-pending.json"),
            "pending_approval": {
                "id": "fetch-vendor",
                "tool": "http_request",
                "input": {"url": "https://vendor.example/private"},
                "reason": "fetch vendor status",
            },
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "ops-pending",
            "status": "requires_approval",
            "goal": "record ops handoff",
            "auth_subject": "ops",
            "pending_approval": {
                "id": "ops-note",
                "tool": "note",
                "input": {"text": "private ops note"},
            },
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-done",
            "status": "done",
            "goal": "already done",
            "auth_subject": "team-a",
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    approval_ids = {approval["pending_approval_action_id"] for approval in payload["approvals"]}
    serialized = json.dumps(payload)

    assert status_code == 200
    assert payload["trace_type"] == "codex_runtime"
    assert payload["count"] == "2"
    assert approval_ids == {"fetch-vendor", "ops-note"}
    assert all(approval["status"] == "requires_approval" for approval in payload["approvals"])
    assert all("pending_approval" not in approval for approval in payload["approvals"])
    assert "vendor.example/private" not in serialized
    assert "private ops note" not in serialized


def test_service_router_runtime_approvals_respects_subject_visibility(tmp_path):
    for subject in ["team-a", "ops"]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": f"{subject}-pending",
                "status": "requires_approval",
                "goal": f"{subject} approval",
                "auth_subject": subject,
                "pending_approval": {
                    "id": f"{subject}-approval",
                    "tool": "http_request",
                },
            },
            str(tmp_path),
        )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_token="admin-token",
            auth_tokens={"team-a": "team-a-token"},
        ),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert payload["approvals"][0]["run_id"] == "team-a-pending"
    assert payload["approvals"][0]["auth_subject"] == "team-a"


def test_service_router_runtime_approvals_filters_by_tool(tmp_path):
    for action_id, tool in [("fetch-site", "http_request"), ("write-note", "note")]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": f"{tool}-pending",
                "status": "requires_approval",
                "goal": f"{tool} approval",
                "auth_subject": "team-a",
                "pending_approval": {"id": action_id, "tool": tool},
            },
            str(tmp_path),
        )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals?tool=http_request",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert payload["approvals"][0]["pending_approval_tool"] == "http_request"


def test_service_router_runtime_approvals_filters_stale_pending_actions(tmp_path):
    old_pending_path = Path(
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": "old-pending",
                "status": "requires_approval",
                "goal": "old approval",
                "auth_subject": "ops",
                "pending_approval": {"id": "old-fetch", "tool": "http_request"},
            },
            str(tmp_path),
        )
    )
    fresh_pending_path = Path(
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": "fresh-pending",
                "status": "requires_approval",
                "goal": "fresh approval",
                "auth_subject": "ops",
                "pending_approval": {"id": "fresh-fetch", "tool": "http_request"},
            },
            str(tmp_path),
        )
    )
    now = time.time()
    os.utime(old_pending_path, (now - 7_200, now - 7_200))
    os.utime(fresh_pending_path, (now, now))

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals?min_pending_age_seconds=3600",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    summary_status, summary_payload = service_router.handle_request(
        "GET",
        "/runtime/approvals/summary?min_pending_age_seconds=3600",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert payload["approvals"][0]["run_id"] == "old-pending"
    assert int(payload["approvals"][0]["pending_age_seconds"]) >= 3_600
    assert summary_status == 200
    assert summary_payload["pending_approval_count"] == "1"
    assert summary_payload["stale_pending_count"] == "1"
    assert int(summary_payload["max_pending_age_seconds"]) >= 3_600


def test_service_router_runtime_approvals_summary_aggregates_pending_queue(tmp_path):
    for run_id, subject, tool in [
        ("team-a-http", "team-a", "http_request"),
        ("team-a-note", "team-a", "note"),
        ("ops-http", "ops", "http_request"),
    ]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": run_id,
                "status": "requires_approval",
                "goal": f"{subject} {tool}",
                "auth_subject": subject,
                "pending_approval": {"id": f"{run_id}-approval", "tool": tool},
            },
            str(tmp_path),
        )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-done",
            "status": "done",
            "goal": "not pending",
            "auth_subject": "team-a",
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals/summary",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload == {
        "trace_type": "codex_runtime",
        "pending_approval_count": "3",
        "stale_pending_count": "3",
        "max_pending_age_seconds": "0",
        "auth_subject_counts": {"ops": "1", "team-a": "2"},
        "tool_counts": {"http_request": "2", "note": "1"},
    }


def test_service_router_runtime_approvals_summary_respects_subject_visibility(tmp_path):
    for subject in ["team-a", "ops"]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": f"{subject}-pending",
                "status": "requires_approval",
                "goal": f"{subject} approval",
                "auth_subject": subject,
                "pending_approval": {
                    "id": f"{subject}-approval",
                    "tool": "http_request",
                },
            },
            str(tmp_path),
        )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals/summary",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_token="admin-token",
            auth_tokens={"team-a": "team-a-token"},
        ),
    )

    assert status_code == 200
    assert payload["pending_approval_count"] == "1"
    assert payload["auth_subject_counts"] == {"team-a": "1"}
    assert payload["tool_counts"] == {"http_request": "1"}


def test_service_router_runtime_approvals_summary_filters_by_tool(tmp_path):
    for action_id, tool in [("fetch-site", "http_request"), ("write-note", "note")]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": f"{tool}-pending",
                "status": "requires_approval",
                "goal": f"{tool} approval",
                "auth_subject": "team-a",
                "pending_approval": {"id": action_id, "tool": tool},
            },
            str(tmp_path),
        )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/approvals/summary?tool=http_request",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["pending_approval_count"] == "1"
    assert payload["tool_counts"] == {"http_request": "1"}


def test_service_router_runtime_status_summarizes_plan_dependencies(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"capture then report","plan":{"actions":['
            b'{"id":"step-1","tool":"note","input":{"text":"hello"}},'
            b'{"id":"step-2","tool":"artifact","input":{"title":"Report",'
            b'"kind":"report","content":"ready"},"depends_on":["step-1"]}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert status_code == 200
    assert payload["dependency_edge_count"] == "1"
    assert payload["latest_plan_action_count"] == "2"
    assert payload["latest_plan_action_ids"] == ["step-1", "step-2"]


def test_service_router_runtime_status_summarizes_failed_observations(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"bad tool input","plan":{"actions":[{"id":"step-1",'
            b'"tool":"transform_text","input":{"text":"hello","mode":"strip"},'
            b'"reason":"normalize"}]}}'
        ),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert run_payload["error_code"] == "invalid_tool_input"
    assert "mode" in run_payload["error"]
    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_tool_input"
    assert "mode" in payload["error"]
    assert payload["failed_observation_count"] == "1"
    assert payload["planner_failure_count"] == "0"
    assert payload["tool_failure_count"] == "1"
    assert payload["approval_required_count"] == "0"
    assert payload["latest_failed_action_id"] == "step-1"
    assert payload["latest_failed_tool"] == "transform_text"
    assert payload["latest_failed_error_code"] == "invalid_tool_input"
    assert payload["error_code_counts"] == {"invalid_tool_input": "1"}
    assert payload["tool_names"] == ["transform_text"]


def test_service_router_runtime_status_summarizes_artifact_bytes(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "artifact-byte-run",
            "status": "done",
            "goal": "produce artifacts",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "done",
                    "output": {
                        "artifact_id": "artifact-report",
                        "kind": "report",
                        "bytes": 120,
                    },
                },
                {
                    "tool": "artifact",
                    "status": "done",
                    "output": {
                        "artifact_id": "artifact-plan",
                        "kind": "plan",
                        "bytes": 30,
                    },
                },
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/artifact-byte-run",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["artifact_total_bytes"] == "150"
    assert payload["artifact_bytes_by_kind"] == {"plan": "30", "report": "120"}


def test_service_router_runtime_status_summarizes_planner_failures(tmp_path):
    run_status, run_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"bad planner","plan":{"actions":"bad"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{run_payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert run_status == 200
    assert run_payload["error_code"] == "invalid_plan"
    assert status_code == 200
    assert payload["status"] == "failed"
    assert payload["failed_observation_count"] == "1"
    assert payload["planner_failure_count"] == "1"
    assert payload["tool_failure_count"] == "0"
    assert payload["tool_names"] == ["planner"]


def test_service_router_runtime_runs_list_skips_unreadable_traces(tmp_path):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "array.json").write_text("[]\n", encoding="utf-8")
    runtime_status, runtime_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture runtime","plan":{"actions":[],"final_answer":"runtime"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert runtime_status == 200
    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == [runtime_payload["run_id"]]


def test_service_router_runtime_runs_list_excludes_non_runtime_traces(tmp_path):
    persist_trace(
        {"run_id": "legacy-run", "status": "done", "goal": "legacy task", "events": []},
        str(tmp_path),
    )
    runtime_status, runtime_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture runtime","plan":{"actions":[],"final_answer":"runtime"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert runtime_status == 200
    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == [runtime_payload["run_id"]]


def test_service_router_runtime_runs_list_applies_limit_after_trace_type_filter(tmp_path):
    runtime_status, runtime_payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture runtime","plan":{"actions":[],"final_answer":"runtime"}}',
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    persist_trace(
        {"run_id": "newer-legacy-run", "status": "done", "goal": "legacy task"},
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=1",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert runtime_status == 200
    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == [runtime_payload["run_id"]]


def test_service_router_runtime_runs_list_is_scoped_to_authenticated_subject(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-run",
            "status": "done",
            "goal": "team a task",
            "auth_subject": "team-a",
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-b-run",
            "status": "done",
            "goal": "team b task",
            "auth_subject": "team-b",
        },
        str(tmp_path),
    )
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_token="admin-token",
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
        protect_diagnostics=True,
    )

    team_status, team_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=10",
        b"",
        headers={"Authorization": "Bearer team-a-token"},
        config=config,
    )
    admin_status, admin_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=10",
        b"",
        headers={"Authorization": "Bearer admin-token"},
        config=config,
    )

    assert team_status == 200
    assert [run["run_id"] for run in team_payload["runs"]] == ["team-a-run"]
    assert admin_status == 200
    assert {run["run_id"] for run in admin_payload["runs"]} == {
        "team-a-run",
        "team-b-run",
    }


def test_service_router_runtime_status_rejects_cross_subject_trace_reads(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-b-run",
            "status": "done",
            "goal": "team b task",
            "auth_subject": "team-b",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "artifact",
                    "status": "done",
                    "output": {
                        "artifact_id": "artifact-team-b",
                        "title": "Team B",
                        "kind": "report",
                        "format": "markdown",
                        "content": "team b private result",
                        "tags": [],
                        "bytes": 21,
                    },
                }
            ],
            "events": [{"type": "run_started", "message": "team b"}],
        },
        str(tmp_path),
    )
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        auth_token="admin-token",
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        },
        protect_diagnostics=True,
    )
    team_a_headers = {"Authorization": "Bearer team-a-token"}
    admin_headers = {"Authorization": "Bearer admin-token"}

    for route in [
        "/runtime/runs/team-b-run",
        "/runtime/runs/team-b-run/timeline",
        "/runtime/runs/team-b-run/artifacts",
        "/runtime/runs/team-b-run/artifacts/artifact-team-b",
    ]:
        status_code, payload = service_router.handle_request(
            "GET",
            route,
            b"",
            headers=team_a_headers,
            config=config,
        )

        assert status_code == 404
        assert payload["error_code"] == "not_found"

    admin_status, admin_payload = service_router.handle_request(
        "GET",
        "/runtime/runs/team-b-run",
        b"",
        headers=admin_headers,
        config=config,
    )

    assert admin_status == 200
    assert admin_payload["run_id"] == "team-b-run"
    assert admin_payload["auth_subject"] == "team-b"


def test_service_router_runtime_runs_list_filters_by_status(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "failed-run",
            "status": "failed",
            "goal": "failed task",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "done-run",
            "status": "done",
            "goal": "done task",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?status=failed&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["failed-run"]


def test_service_router_runtime_runs_list_filters_by_auth_subject(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-a-run",
            "status": "done",
            "goal": "team a task",
            "auth_subject": "team-a",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "ops-run",
            "status": "done",
            "goal": "ops task",
            "auth_subject": "ops",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?auth_subject=team-a&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert payload["runs"][0]["run_id"] == "team-a-run"
    assert payload["runs"][0]["auth_subject"] == "team-a"


def test_service_router_runtime_runs_list_omits_pending_approval_payload(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-run",
            "status": "requires_approval",
            "goal": "fetch secret",
            "pending_approval": {
                "id": "step-1",
                "tool": "http_request",
                "input": {"url": "https://example.com/private"},
            },
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?status=requires_approval&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert "pending_approval" not in payload["runs"][0]
    assert payload["runs"][0]["pending_approval_action_id"] == "step-1"
    assert payload["runs"][0]["pending_approval_tool"] == "http_request"


def test_service_router_runtime_runs_list_filters_by_tool(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "artifact-run",
            "status": "done",
            "goal": "produce artifact",
            "observations": [{"tool": "artifact", "status": "done", "output": {}}],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "note-run",
            "status": "done",
            "goal": "capture note",
            "observations": [{"tool": "note", "status": "done", "output": {}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?tool=artifact&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["artifact-run"]


def test_service_router_runtime_runs_list_filters_by_error_code(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "tool-input-run",
            "status": "failed",
            "goal": "bad tool input",
            "observations": [
                {
                    "tool": "transform_text",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "planner-run",
            "status": "failed",
            "goal": "bad planner output",
            "observations": [
                {
                    "tool": "planner",
                    "status": "failed",
                    "error_code": "invalid_plan",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?error_code=invalid_tool_input&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["tool-input-run"]
    assert payload["runs"][0]["error_code_counts"] == {"invalid_tool_input": "1"}


def test_service_router_runtime_runs_list_filters_by_latest_failed_error_code(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-invalid-input-run",
            "status": "failed",
            "goal": "bad input",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "transform_text",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-invalid-output-run",
            "status": "failed",
            "goal": "bad output",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "custom_tool",
                    "status": "failed",
                    "error_code": "invalid_tool_output",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_error_code=invalid_tool_input&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert [run["run_id"] for run in payload["runs"]] == [
        "latest-invalid-input-run"
    ]
    assert payload["runs"][0]["latest_failed_error_code"] == "invalid_tool_input"


def test_service_router_runtime_runs_list_filters_by_latest_failed_tool(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-transform-run",
            "status": "failed",
            "goal": "bad transform",
            "observations": [
                {
                    "action_id": "step-1",
                    "tool": "transform_text",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-planner-run",
            "status": "failed",
            "goal": "bad plan",
            "observations": [
                {
                    "action_id": "",
                    "tool": "planner",
                    "status": "failed",
                    "error_code": "invalid_plan",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_tool=planner&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert [run["run_id"] for run in payload["runs"]] == ["latest-planner-run"]
    assert payload["runs"][0]["latest_failed_tool"] == "planner"


def test_service_router_runtime_runs_list_filters_by_latest_failed_action_id(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-fetch-run",
            "status": "failed",
            "goal": "bad fetch",
            "observations": [
                {
                    "action_id": "fetch-site",
                    "tool": "http_request",
                    "status": "failed",
                    "error_code": "tool_not_found",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "latest-transform-run",
            "status": "failed",
            "goal": "bad transform",
            "observations": [
                {
                    "action_id": "normalize-text",
                    "tool": "transform_text",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                    "output": {},
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_action_id=fetch-site&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert [run["run_id"] for run in payload["runs"]] == ["latest-fetch-run"]
    assert payload["runs"][0]["latest_failed_action_id"] == "fetch-site"


def test_service_router_runtime_runs_list_filters_by_artifact_presence(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "artifact-run",
            "status": "done",
            "goal": "produce artifact",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "done",
                    "output": {"artifact_id": "artifact-1"},
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "plain-run",
            "status": "done",
            "goal": "plain run",
            "observations": [{"tool": "note", "status": "done", "output": {}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_artifacts=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["artifact-run"]


def test_service_router_runtime_runs_list_filters_by_error_presence(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "observation-error-run",
            "status": "failed",
            "goal": "bad tool input",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "run-error-run",
            "status": "failed",
            "goal": "trace failed",
            "error_code": "trace_persistence_failed",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "healthy-run",
            "status": "done",
            "goal": "healthy task",
            "observations": [{"tool": "note", "status": "done", "output": {}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_errors=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "2"
    assert {run["run_id"] for run in payload["runs"]} == {
        "observation-error-run",
        "run-error-run",
    }

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_errors=false&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["healthy-run"]


def test_service_router_runtime_runs_list_filters_by_failure_presence(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "failed-observation-run",
            "status": "failed",
            "goal": "bad tool input",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "failed",
                    "error_code": "invalid_tool_input",
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "run-error-only-run",
            "status": "failed",
            "goal": "trace failed",
            "error_code": "trace_persistence_failed",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_failures=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["failed-observation-run"]
    assert payload["runs"][0]["failed_observation_count"] == "1"

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_failures=false&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["run-error-only-run"]


def test_service_router_runtime_runs_list_filters_by_approval_presence(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "approved-run",
            "status": "failed",
            "goal": "approved fetch",
            "approved_action_ids": ["step-1"],
            "approved_action_count": "1",
            "observations": [
                {
                    "tool": "http_request",
                    "status": "failed",
                    "error_code": "tool_not_found",
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "plain-run",
            "status": "done",
            "goal": "plain run",
            "observations": [{"tool": "note", "status": "done", "output": {}}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_approvals=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["approved-run"]
    assert payload["runs"][0]["approved_action_ids"] == ["step-1"]

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_approvals=false&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["plain-run"]


def test_service_router_runtime_runs_list_filters_by_approved_action_id(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "approved-fetch-run",
            "status": "failed",
            "goal": "approved fetch",
            "approved_action_ids": ["fetch-site"],
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "approved-send-run",
            "status": "failed",
            "goal": "approved send",
            "approved_action_ids": ["send-message"],
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?approved_action_id=fetch-site&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["approved-fetch-run"]
    assert payload["runs"][0]["approved_action_ids"] == ["fetch-site"]


def test_service_router_runtime_runs_list_filters_by_resumed_from_run_id(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "resumed-run",
            "status": "failed",
            "goal": "resumed fetch",
            "resumed_from_run_id": "pending-run",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "other-run",
            "status": "done",
            "goal": "other task",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?resumed_from_run_id=pending-run&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["resumed-run"]
    assert payload["runs"][0]["resumed_from_run_id"] == "pending-run"


def test_service_router_runtime_runs_list_filters_by_resumed_by_auth_subject(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "admin-resumed-run",
            "status": "done",
            "goal": "admin resumed",
            "auth_subject": "team-a",
            "resumed_from_run_id": "pending-run",
            "resumed_by_auth_subject": "default",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "team-resumed-run",
            "status": "done",
            "goal": "team resumed",
            "auth_subject": "team-a",
            "resumed_from_run_id": "team-pending-run",
            "resumed_by_auth_subject": "team-a",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?resumed_by_auth_subject=default&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["admin-resumed-run"]
    assert payload["runs"][0]["resumed_by_auth_subject"] == "default"
    assert payload["runs"][0]["auth_subject"] == "team-a"


def test_service_router_runtime_runs_list_filters_by_pending_approval_tool(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "http-approval-run",
            "status": "requires_approval",
            "goal": "fetch site",
            "pending_approval": {"id": "step-1", "tool": "http_request"},
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "note-approval-run",
            "status": "requires_approval",
            "goal": "write note",
            "pending_approval": {"id": "step-2", "tool": "note"},
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?pending_approval_tool=http_request&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["http-approval-run"]
    assert payload["runs"][0]["pending_approval_tool"] == "http_request"


def test_service_router_runtime_runs_list_filters_by_pending_approval_action_id(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "approval-step-1-run",
            "status": "requires_approval",
            "goal": "fetch site",
            "pending_approval": {"id": "step-1", "tool": "http_request"},
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "approval-step-2-run",
            "status": "requires_approval",
            "goal": "send message",
            "pending_approval": {"id": "step-2", "tool": "message"},
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?pending_approval_action_id=step-1&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["approval-step-1-run"]
    assert payload["runs"][0]["pending_approval_action_id"] == "step-1"


def test_service_router_runtime_runs_list_filters_by_pending_approval_presence(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-approval-run",
            "status": "requires_approval",
            "goal": "needs review",
            "pending_approval": {"id": "step-1", "tool": "http_request"},
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "no-approval-run",
            "status": "done",
            "goal": "done",
            "observations": [],
        },
        str(tmp_path),
    )

    pending_status, pending_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_pending_approval=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    clear_status, clear_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_pending_approval=false&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert pending_status == 200
    assert [run["run_id"] for run in pending_payload["runs"]] == [
        "pending-approval-run"
    ]
    assert pending_payload["runs"][0]["pending_approval_action_id"] == "step-1"
    assert clear_status == 200
    assert [run["run_id"] for run in clear_payload["runs"]] == ["no-approval-run"]


def test_service_router_runtime_runs_list_filters_by_final_answer_guardrail_presence(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "identity-corrected-run",
            "status": "done",
            "goal": "你是谁",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "plain-run",
            "status": "done",
            "goal": "普通任务",
            "observations": [],
        },
        str(tmp_path),
    )

    guarded_status, guarded_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_final_answer_guardrail=true&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    plain_status, plain_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_final_answer_guardrail=false&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert guarded_status == 200
    assert [run["run_id"] for run in guarded_payload["runs"]] == [
        "identity-corrected-run"
    ]
    assert guarded_payload["runs"][0]["final_answer_guardrail"] == {
        "applied": "true",
        "reason": "runtime_identity_boundary",
        "original_answer_omitted": "true",
    }
    assert plain_status == 200
    assert [run["run_id"] for run in plain_payload["runs"]] == ["plain-run"]


def test_service_router_runtime_runs_list_filters_by_final_answer_guardrail_reason(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "identity-corrected-run",
            "status": "done",
            "goal": "你是谁",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "deployment-corrected-run",
            "status": "done",
            "goal": "你部署在哪",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_deployment_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?final_answer_guardrail_reason=runtime_identity_boundary&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == [
        "identity-corrected-run"
    ]


def test_service_router_runtime_runs_summary_filters_by_final_answer_guardrail_reason(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "identity-corrected-run",
            "status": "done",
            "goal": "你是谁",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [{"tool": "note", "status": "ok"}],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "deployment-corrected-run",
            "status": "done",
            "goal": "你部署在哪",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_deployment_boundary",
                "original_answer_omitted": "true",
            },
            "observations": [{"tool": "note", "status": "ok"}],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs/summary?final_answer_guardrail_reason=runtime_identity_boundary",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["run_count"] == "1"
    assert payload["final_answer_guardrail_applied_count"] == "1"
    assert payload["final_answer_guardrail_reason_counts"] == {
        "runtime_identity_boundary": "1"
    }


def test_service_router_runtime_runs_list_filters_by_artifact_kind(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "report-run",
            "status": "done",
            "goal": "produce report",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-report",
                        "kind": "report",
                    },
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "plan-run",
            "status": "done",
            "goal": "produce plan",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-plan",
                        "kind": "plan",
                    },
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_kind=report&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["report-run"]
    assert payload["runs"][0]["artifact_kinds"] == ["report"]


def test_service_router_runtime_runs_list_filters_by_artifact_format(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "markdown-run",
            "status": "done",
            "goal": "produce markdown",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-markdown",
                        "kind": "report",
                        "format": "markdown",
                    },
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "json-run",
            "status": "done",
            "goal": "produce json",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-json",
                        "kind": "data",
                        "format": "json",
                    },
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_format=markdown&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["markdown-run"]
    assert payload["runs"][0]["artifact_formats"] == ["markdown"]


def test_service_router_runtime_runs_list_filters_by_artifact_tag(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "release-run",
            "status": "done",
            "goal": "produce release report",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-release",
                        "kind": "report",
                        "format": "markdown",
                        "tags": ["release", "ops"],
                    },
                }
            ],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "finance-run",
            "status": "done",
            "goal": "produce finance report",
            "observations": [
                {
                    "tool": "artifact",
                    "status": "ok",
                    "output": {
                        "artifact_id": "artifact-finance",
                        "kind": "report",
                        "format": "markdown",
                        "tags": ["finance"],
                    },
                }
            ],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_tag=release&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["release-run"]
    assert payload["runs"][0]["artifact_tags"] == ["ops", "release"]


def test_service_router_runtime_runs_list_filters_before_limit(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "failed-run",
            "status": "failed",
            "goal": "failed task",
            "observations": [],
        },
        str(tmp_path),
    )
    time.sleep(0.01)
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "done-run",
            "status": "done",
            "goal": "newer done task",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?status=failed&limit=1",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["failed-run"]


def test_service_router_runtime_runs_list_paginates_with_cursor(tmp_path):
    for run_id in ["oldest-run", "middle-run", "newest-run"]:
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": run_id,
                "status": "done",
                "goal": run_id,
                "observations": [],
            },
            str(tmp_path),
        )
        time.sleep(0.01)

    first_status_code, first_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=2",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert first_status_code == 200
    assert first_payload["count"] == "2"
    assert first_payload["has_more"] == "true"
    assert first_payload["next_cursor"]
    assert [run["run_id"] for run in first_payload["runs"]] == [
        "newest-run",
        "middle-run",
    ]

    second_status_code, second_payload = service_router.handle_request(
        "GET",
        f"/runtime/runs?limit=2&cursor={first_payload['next_cursor']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert second_status_code == 200
    assert second_payload["count"] == "1"
    assert second_payload["has_more"] == "false"
    assert second_payload["next_cursor"] == ""
    assert [run["run_id"] for run in second_payload["runs"]] == ["oldest-run"]


def test_service_router_runtime_runs_list_filters_by_iteration_budget_remaining(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "budget-spent-run",
            "status": "done",
            "goal": "spent",
            "iteration_count": "2",
            "max_iterations": "2",
            "observations": [],
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "budget-open-run",
            "status": "done",
            "goal": "open",
            "iteration_count": "1",
            "max_iterations": "3",
            "observations": [],
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?iteration_budget_remaining=0&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["count"] == "1"
    assert [run["run_id"] for run in payload["runs"]] == ["budget-spent-run"]
    assert payload["runs"][0]["iteration_budget_remaining"] == "0"


def test_service_router_runtime_runs_list_rejects_invalid_status_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?status=running",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "status" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_auth_subject_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?auth_subject=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "auth_subject" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_error_code_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?error_code=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "error_code" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_latest_failed_error_code_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_error_code=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "latest_failed_error_code" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_latest_failed_tool_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_tool=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "latest_failed_tool" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_latest_failed_action_id_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?latest_failed_action_id=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "latest_failed_action_id" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_artifact_kind_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_kind=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "artifact_kind" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_artifact_format_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_format=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "artifact_format" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_artifact_tag_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?artifact_tag=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "artifact_tag" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_artifacts_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_artifacts=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_artifacts" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_errors_filter(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_errors=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_errors" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_failures_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_failures=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_failures" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_approvals_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_approvals=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_approvals" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_pending_approval_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_pending_approval=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_pending_approval" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_has_final_answer_guardrail_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?has_final_answer_guardrail=yes",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "has_final_answer_guardrail" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_final_answer_guardrail_reason_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?final_answer_guardrail_reason=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "final_answer_guardrail_reason" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_approved_action_id_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?approved_action_id=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "approved_action_id" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_resumed_from_run_id_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?resumed_from_run_id=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "resumed_from_run_id" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_resumed_by_auth_subject_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?resumed_by_auth_subject=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "resumed_by_auth_subject" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_pending_approval_tool_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?pending_approval_tool=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "pending_approval_tool" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_pending_approval_action_id_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?pending_approval_action_id=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "pending_approval_action_id" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_iteration_budget_filter(
    tmp_path,
):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?iteration_budget_remaining=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "iteration_budget_remaining" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_cursor(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?cursor=",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "cursor" in payload["error"]


def test_service_router_runtime_runs_list_requires_trace_persistence():
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs",
        b"",
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_agent_config"
    assert "trace_dir" in payload["error"]


def test_service_router_runtime_runs_list_rejects_invalid_limit(tmp_path):
    status_code, payload = service_router.handle_request(
        "GET",
        "/runtime/runs?limit=0",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "limit" in payload["error"]


def test_service_router_runtime_run_persists_trace_when_configured(tmp_path):
    body = (
        b'{"goal":"capture hello","plan":{"actions":[{"id":"step-1",'
        b'"tool":"note","input":{"text":"hello"},"reason":"capture"}]}}'
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    trace_path = Path(payload["trace_path"])
    trace_payload = json.loads(trace_path.read_text())

    assert status_code == 200
    assert trace_path.parent == tmp_path
    assert trace_payload["run_id"] == payload["run_id"]
    assert trace_payload["goal"] == "capture hello"
    assert trace_payload["events"][0]["node"] == "planner"
    assert trace_payload["observations"][0]["output"] == {"text": "hello"}


def test_service_router_runtime_run_persists_metadata_and_tags_for_audit_filters(
    tmp_path,
):
    body = json.dumps(
        {
            "goal": "capture launch note",
            "metadata": {"workflow": "launch", "ticket": "REL-123"},
            "tags": ["release", "ops", "release"],
            "plan": {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "ship"},
                        "reason": "capture",
                    }
                ],
                "final_answer": "captured",
            },
        }
    ).encode("utf-8")

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    trace_payload = json.loads(Path(payload["trace_path"]).read_text())
    detail_status, detail_payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    tag_list_status, tag_list_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?tag=release&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    metadata_list_status, metadata_list_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?metadata_key=workflow&metadata_value=launch&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    summary_status, summary_payload = service_router.handle_request(
        "GET",
        "/runtime/runs/summary?tag=ops",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["metadata"] == {"ticket": "REL-123", "workflow": "launch"}
    assert payload["tags"] == ["ops", "release"]
    assert trace_payload["metadata"] == payload["metadata"]
    assert trace_payload["tags"] == payload["tags"]
    assert detail_status == 200
    assert detail_payload["metadata"] == payload["metadata"]
    assert detail_payload["metadata_keys"] == ["ticket", "workflow"]
    assert detail_payload["tags"] == ["ops", "release"]
    assert tag_list_status == 200
    assert [run["run_id"] for run in tag_list_payload["runs"]] == [payload["run_id"]]
    assert metadata_list_status == 200
    assert [run["run_id"] for run in metadata_list_payload["runs"]] == [
        payload["run_id"]
    ]
    assert summary_status == 200
    assert summary_payload["run_count"] == "1"
    assert summary_payload["tag_counts"] == {"ops": "1", "release": "1"}
    assert summary_payload["metadata_key_counts"] == {
        "ticket": "1",
        "workflow": "1",
    }


def test_service_router_runtime_run_rejects_secret_like_metadata_keys():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        json.dumps(
            {
                "goal": "capture",
                "metadata": {"api_key": "never-persist-this"},
                "plan": {"actions": [], "final_answer": "blocked"},
            }
        ).encode("utf-8"),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "metadata" in payload["error"]
    assert "secret" in payload["error"]


def test_service_router_runtime_runs_list_rejects_blank_metadata_filters(tmp_path):
    for query, field_name in [
        ("tag=", "tag"),
        ("metadata_key=", "metadata_key"),
        ("metadata_value=", "metadata_value"),
    ]:
        status_code, payload = service_router.handle_request(
            "GET",
            f"/runtime/runs?{query}",
            b"",
            config=ServiceConfig(trace_dir=str(tmp_path)),
        )

        assert status_code == 400
        assert payload["error_code"] == "invalid_request_body"
        assert field_name in payload["error"]


def test_service_router_runtime_run_persists_internal_auth_subject(tmp_path):
    body = (
        b'{"goal":"capture hello","plan":{"actions":[{"id":"step-1",'
        b'"tool":"note","input":{"text":"hello"},"reason":"capture"}]}}'
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_tokens={"team-a": "team-a-token"},
        ),
    )
    trace_payload = json.loads(Path(payload["trace_path"]).read_text())
    list_status, list_payload = service_router.handle_request(
        "GET",
        "/runtime/runs?auth_subject=team-a&limit=10",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    detail_status, detail_payload = service_router.handle_request(
        "GET",
        f"/runtime/runs/{payload['run_id']}",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["auth_subject"] == "team-a"
    assert trace_payload["auth_subject"] == "team-a"
    assert list_status == 200
    assert [run["run_id"] for run in list_payload["runs"]] == [payload["run_id"]]
    assert list_payload["runs"][0]["auth_subject"] == "team-a"
    assert detail_status == 200
    assert detail_payload["auth_subject"] == "team-a"


def test_service_router_runtime_run_uses_configured_runtime_allowed_tools():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"transform hello","plan":{"actions":[{"id":"step-1",'
            b'"tool":"transform_text","input":{"text":"hello","mode":"uppercase"},'
            b'"reason":"transform"}]}}'
        ),
        config=ServiceConfig(runtime_allowed_tools=("note",)),
    )

    assert status_code == 200
    assert payload["status"] == "requires_approval"
    assert payload["pending_approval"]["tool"] == "transform_text"
    assert payload["observations"][0]["status"] == "requires_approval"
    assert payload["observations"][0]["error_code"] == "tool_not_allowed"


def test_service_router_runtime_run_uses_subject_runtime_allowed_tools():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"transform hello","plan":{"actions":[{"id":"step-1",'
            b'"tool":"transform_text","input":{"text":"hello","mode":"uppercase"},'
            b'"reason":"transform"}]}}'
        ),
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            auth_tokens={"team-a": "team-a-token"},
            runtime_allowed_tools=("note", "transform_text"),
            runtime_allowed_tools_by_subject={"team-a": ("note",)},
        ),
    )

    assert status_code == 200
    assert payload["auth_subject"] == "team-a"
    assert payload["status"] == "requires_approval"
    assert payload["pending_approval"]["tool"] == "transform_text"
    assert payload["observations"][0]["error_code"] == "tool_not_allowed"


def test_service_router_runtime_run_falls_back_to_global_runtime_allowed_tools():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"transform hello","plan":{"actions":[{"id":"step-1",'
            b'"tool":"transform_text","input":{"text":"hello","mode":"uppercase"},'
            b'"reason":"transform"}]}}'
        ),
        headers={"Authorization": "Bearer team-b-token"},
        config=ServiceConfig(
            auth_tokens={"team-b": "team-b-token"},
            runtime_allowed_tools=("note", "transform_text"),
            runtime_allowed_tools_by_subject={"team-a": ("note",)},
        ),
    )

    assert status_code == 200
    assert payload["auth_subject"] == "team-b"
    assert payload["status"] == "done"
    assert payload["observations"][0]["status"] == "ok"
    assert payload["observations"][0]["output"]["text"] == "HELLO"


def test_service_router_runtime_run_metrics_track_internal_auth_subject(tmp_path):
    metrics = ServiceMetrics()
    body = (
        b'{"goal":"capture hello","plan":{"actions":[{"id":"step-1",'
        b'"tool":"note","input":{"text":"hello"},"reason":"capture"}]}}'
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        body,
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_tokens={"team-a": "team-a-token"},
        ),
        metrics=metrics,
    )

    snapshot = metrics.snapshot()
    assert status_code == 200
    assert payload["status"] == "done"
    assert snapshot["runtime_runs_by_auth_subject"] == {"team-a": "1"}
    assert snapshot["runtime_runs_by_auth_subject_status"] == {"team-a:done": "1"}


def test_service_router_runtime_run_reports_trace_persistence_failure(monkeypatch):
    def failing_persist_trace(trace, trace_dir):
        raise OSError("disk full")

    monkeypatch.setattr(
        "self_correcting_langgraph_agent.service.runtime_run.persist_trace",
        failing_persist_trace,
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","plan":{"actions":[]}}',
        config=ServiceConfig(trace_dir="/tmp/traces"),
    )

    assert status_code == 500
    assert payload["status"] == "failed"
    assert payload["error_code"] == "trace_persistence_failed"
    assert payload["error"]


def test_service_router_runtime_run_times_out_slow_runtime(monkeypatch):
    def slow_runtime_agent(*args, **kwargs):
        time.sleep(0.05)
        return {"trace_type": "codex_runtime", "run_id": "slow", "status": "done"}

    monkeypatch.setattr(
        "self_correcting_langgraph_agent.service.runtime_run.run_runtime_agent",
        slow_runtime_agent,
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"slow runtime","plan":{"actions":[]}}',
        config=ServiceConfig(run_timeout_seconds=0.01),
    )

    assert status_code == 504
    assert payload == {
        "status": "failed",
        "error_code": "agent_run_timeout",
        "error": "agent run timed out",
    }


def test_service_router_runtime_resume_times_out_slow_runtime(tmp_path, monkeypatch):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-run",
            "status": "requires_approval",
            "goal": "slow resume",
            "pending_approval": {"id": "step-1", "tool": "note", "input": {"text": "x"}},
            "plan": {
                "actions": [
                    {"id": "step-1", "tool": "note", "input": {"text": "x"}}
                ]
            },
        },
        str(tmp_path),
    )

    def slow_runtime_agent(*args, **kwargs):
        time.sleep(0.05)
        return {"trace_type": "codex_runtime", "run_id": "slow", "status": "done"}

    monkeypatch.setattr(
        "self_correcting_langgraph_agent.service.runtime_resume.run_runtime_agent",
        slow_runtime_agent,
    )

    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"pending-run","approved_action_ids":["step-1"]}',
        config=ServiceConfig(trace_dir=str(tmp_path), run_timeout_seconds=0.01),
    )

    assert status_code == 504
    assert payload == {
        "status": "failed",
        "error_code": "agent_run_timeout",
        "error": "agent run timed out",
    }


def test_service_router_runtime_run_rejects_invalid_iteration_limit():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","max_iterations":0,"plan":{"actions":[]}}',
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "max_iterations" in payload["error"]


def test_service_router_runtime_run_rejects_iteration_limit_above_configured_cap():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","max_iterations":3,"plan":{"actions":[]}}',
        config=ServiceConfig(runtime_max_iterations=2),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "runtime_max_iterations" in payload["error"]


def test_service_router_runtime_resume_rejects_iteration_limit_above_configured_cap():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/resume",
        b'{"run_id":"run-123","approved_action_ids":[],"max_iterations":3}',
        config=ServiceConfig(trace_dir="/tmp/traces", runtime_max_iterations=2),
    )

    assert status_code == 400
    assert payload["error_code"] == "invalid_request_body"
    assert "runtime_max_iterations" in payload["error"]


def test_service_router_runtime_run_rejects_oversized_goal():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"hello world","plan":{"actions":[]}}',
        config=ServiceConfig(max_goal_chars=5),
    )

    assert status_code == 413
    assert payload["status"] == "failed"
    assert payload["error_code"] == "goal_too_large"


def test_service_router_runtime_run_reuses_run_auth_boundary():
    status_code, payload = service_router.handle_request(
        "POST",
        "/runtime/run",
        b'{"goal":"capture hello","plan":{"actions":[]}}',
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 401
    assert payload["error_code"] == "unauthorized"


def test_service_router_rejects_reused_idempotency_key_with_different_body():
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(idempotency_cache_size=8)
    headers = {"Idempotency-Key": "retry-123"}

    first_status, first_payload = service_router.handle_request(
        "POST",
        "/run",
        b'{"goal": "calculate 2 + 3"}',
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )
    second_status, second_payload = service_router.handle_request(
        "POST",
        "/run",
        b'{"goal": "calculate 4 + 5"}',
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )

    assert first_status == 200
    assert second_status == 409
    assert second_payload == {
        "status": "failed",
        "error_code": "idempotency_key_conflict",
        "error": "idempotency key was already used with a different request body",
    }
    assert first_payload["answer"] == "5"


def test_service_router_reports_idempotency_cache_activity_in_metrics():
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(idempotency_cache_size=8)
    headers = {"Idempotency-Key": "retry-123"}

    service_router.handle_request(
        "POST",
        "/run",
        b'{"goal": "calculate 2 + 3"}',
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )
    service_router.handle_request(
        "POST",
        "/run",
        b'{"goal": "calculate 2 + 3"}',
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )
    service_router.handle_request(
        "POST",
        "/run",
        b'{"goal": "calculate 4 + 5"}',
        headers=headers,
        config=config,
        idempotency_cache=cache,
    )
    status_code, payload = service_router.handle_request(
        "GET",
        "/metrics",
        b"",
        config=config,
        idempotency_cache=cache,
    )

    assert status_code == 200
    assert payload["idempotency_cache_entries"] == "1"
    assert payload["idempotency_cache_size"] == "8"
    assert payload["idempotency_cache_hits"] == "1"
    assert payload["idempotency_cache_misses"] == "1"
    assert payload["idempotency_cache_conflicts"] == "1"
    assert payload["idempotency_cache_stores"] == "1"
    assert payload["idempotency_cache_evictions"] == "0"


def test_idempotency_cache_reports_evictions_when_capacity_is_exceeded():
    cache = ServiceIdempotencyCache(max_entries=1)

    assert cache.lookup("first", b'{"goal": "calculate 1 + 1"}') == ("miss", None)
    cache.store("first", b'{"goal": "calculate 1 + 1"}', 200, {"answer": "2"})
    cache.store("second", b'{"goal": "calculate 2 + 2"}', 200, {"answer": "4"})

    first_status, first_payload = cache.lookup("first", b'{"goal": "calculate 1 + 1"}')
    second_status, second_payload = cache.lookup("second", b'{"goal": "calculate 2 + 2"}')
    snapshot = cache.snapshot()

    assert first_status == "miss"
    assert first_payload is None
    assert second_status == "hit"
    assert second_payload == (200, {"answer": "4"})
    assert snapshot["idempotency_cache_entries"] == "1"
    assert snapshot["idempotency_cache_size"] == "1"
    assert snapshot["idempotency_cache_stores"] == "2"
    assert snapshot["idempotency_cache_evictions"] == "1"


def test_sqlite_idempotency_cache_reuses_responses_across_instances(tmp_path):
    cache_path = tmp_path / "idempotency.sqlite3"
    first_cache = SqliteServiceIdempotencyCache(
        max_entries=8,
        database_path=str(cache_path),
    )
    second_cache = SqliteServiceIdempotencyCache(
        max_entries=8,
        database_path=str(cache_path),
    )

    assert first_cache.lookup("POST /run\x1fteam-a\x1fretry-1", b'{"goal":"a"}') == (
        "miss",
        None,
    )
    first_cache.store(
        "POST /run\x1fteam-a\x1fretry-1",
        b'{"goal":"a"}',
        200,
        {"run_id": "run-1", "answer": "done"},
    )
    hit_status, hit_payload = second_cache.lookup(
        "POST /run\x1fteam-a\x1fretry-1",
        b'{"goal":"a"}',
    )
    conflict_status, conflict_payload = second_cache.lookup(
        "POST /run\x1fteam-a\x1fretry-1",
        b'{"goal":"changed"}',
    )

    assert hit_status == "hit"
    assert hit_payload == (200, {"run_id": "run-1", "answer": "done"})
    assert conflict_status == "conflict"
    assert conflict_payload is None
    assert second_cache.snapshot()["idempotency_cache_entries"] == "1"


def test_sqlite_idempotency_cache_enforces_capacity_across_instances(tmp_path):
    cache_path = tmp_path / "idempotency.sqlite3"
    writer = SqliteServiceIdempotencyCache(
        max_entries=1,
        database_path=str(cache_path),
    )
    reader = SqliteServiceIdempotencyCache(
        max_entries=1,
        database_path=str(cache_path),
    )

    writer.store("first", b'{"goal":"first"}', 200, {"answer": "first"})
    writer.store("second", b'{"goal":"second"}', 200, {"answer": "second"})
    first_status, first_payload = reader.lookup("first", b'{"goal":"first"}')
    second_status, second_payload = reader.lookup("second", b'{"goal":"second"}')
    snapshot = reader.snapshot()

    assert first_status == "miss"
    assert first_payload is None
    assert second_status == "hit"
    assert second_payload == (200, {"answer": "second"})
    assert snapshot["idempotency_cache_entries"] == "1"
    assert snapshot["idempotency_cache_size"] == "1"
    assert snapshot["idempotency_cache_backend"] == "sqlite"


def test_service_router_rejects_unsafe_idempotency_key_before_running_agent():
    calls = []

    def runner(goal, config):
        calls.append(goal)
        return {"run_id": "run-123", "status": "done", "events": []}

    cases = [
        "x" * 129,
        "bad\nkey",
    ]

    for idempotency_key in cases:
        status_code, payload = service_router.handle_request(
            "POST",
            "/run",
            b'{"goal": "calculate 2 + 3"}',
            headers={"Idempotency-Key": idempotency_key},
            config=ServiceConfig(idempotency_cache_size=8),
            idempotency_cache=ServiceIdempotencyCache(max_entries=8),
            agent_runner=runner,
        )

        assert status_code == 400
        assert payload == {
            "status": "failed",
            "error_code": "invalid_idempotency_key",
            "error": "idempotency key must be 1-128 printable ASCII characters",
        }

    assert calls == []


def test_service_router_metrics_snapshot_includes_redacted_runtime_info():
    config = ServiceConfig(
        host="0.0.0.0",
        port=9001,
        auth_token="secret",
        max_request_bytes=8192,
        rate_limit_per_minute=5,
        max_concurrent_runs=7,
        idempotency_cache_size=6,
        max_goal_chars=1234,
        runtime_max_iterations=13,
        allow_full_trace_response=True,
        protect_diagnostics=True,
        trust_forwarded_for=True,
        trace_dir="/var/lib/self-correcting-agent/traces",
        run_timeout_seconds=9.5,
        request_timeout_seconds=4.5,
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/metrics",
        b"",
        headers={"Authorization": "Bearer secret"},
        config=config,
    )

    assert status_code == 200
    assert payload["service_version"]
    assert payload["bind_host"] == "0.0.0.0"
    assert payload["bind_port"] == "9001"
    assert payload["auth_required"] == "true"
    assert payload["auth_subject_count"] == "1"
    assert payload["trace_persistence"] == "enabled"
    assert payload["max_request_bytes"] == "8192"
    assert payload["rate_limit_per_minute"] == "5"
    assert payload["max_concurrent_runs"] == "7"
    assert payload["idempotency_cache_size"] == "6"
    assert payload["max_goal_chars"] == "1234"
    assert payload["runtime_max_iterations"] == "13"
    assert payload["allow_full_trace_response"] == "true"
    assert payload["protect_diagnostics"] == "true"
    assert payload["trust_forwarded_for"] == "true"
    assert payload["run_timeout_seconds"] == "9.5"
    assert payload["request_timeout_seconds"] == "4.5"
    assert payload["trace_directory_permissions"] == "0700"
    assert payload["trace_file_permissions"] == "0600"
    assert payload["trace_probe_file_permissions"] == "0600"
    assert payload["llm_provider"] == "unconfigured"
    assert payload["llm_base_url"] == ""
    assert payload["llm_model"] == ""
    assert payload["llm_api_key_configured"] == "false"
    assert payload["llm_timeout_seconds"] == "30.0"
    assert payload["llm_max_retries"] == "2"
    assert payload["llm_retry_backoff_seconds"] == "0.25"
    assert payload["security_response_headers"] == "enabled"
    assert payload["cache_control_header"] == "no-store"
    assert (
        payload["content_security_policy_header"]
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert payload["referrer_policy_header"] == "no-referrer"
    assert payload["x_frame_options_header"] == "DENY"
    assert payload["x_content_type_options_header"] == "nosniff"
    assert "secret" not in str(payload)


def test_service_router_metrics_snapshot_includes_runtime_guardrail_counts(tmp_path):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "identity-guardrail",
            "status": "done",
            "goal": "你是谁",
            "final_answer_guardrail": {
                "applied": "true",
                "reason": "runtime_identity_boundary",
                "original_answer_omitted": "true",
            },
        },
        str(tmp_path),
    )

    status_code, payload = service_router.handle_request(
        "GET",
        "/metrics",
        b"",
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    assert status_code == 200
    assert payload["runtime_final_answer_guardrails_total"] == "1"
    assert payload["runtime_final_answer_guardrails_by_reason"] == {
        "runtime_identity_boundary": "1"
    }
