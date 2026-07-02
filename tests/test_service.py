import http.client
import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID

from self_correcting_langgraph_agent.service import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    access_log_record,
    create_server,
    handle_request,
    readiness_payload,
)
from self_correcting_langgraph_agent.service import cli as service_module
from self_correcting_langgraph_agent.service import runtime as service_runtime
from self_correcting_langgraph_agent.service import safety as service_safety
from self_correcting_langgraph_agent.service.trace_store import persist_trace


def test_service_health_endpoint_reports_ok():
    status_code, payload = handle_request("GET", "/health", b"")

    assert status_code == 200
    assert payload == {"status": "ok"}


def test_service_readiness_payload_reports_dependency_checks():
    payload = readiness_payload()

    assert payload == {
        "status": "ready",
        "failed_checks": [],
        "checks": {
            "agent_config": "ok",
            "openapi": "ok",
            "tools": "ok",
        },
    }


def test_service_readiness_payload_checks_configured_trace_dir(tmp_path):
    trace_dir = tmp_path / "traces"

    payload = readiness_payload(ServiceConfig(trace_dir=str(trace_dir)))

    assert payload["status"] == "ready"
    assert payload["checks"]["trace_persistence"] == "ok"
    assert trace_dir.exists()
    assert list(trace_dir.iterdir()) == []


def test_service_ready_endpoint_rejects_unusable_trace_dir(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace directory creation")
    trace_dir = blocking_file / "traces"

    status_code, payload = handle_request(
        "GET",
        "/ready",
        b"",
        config=ServiceConfig(trace_dir=str(trace_dir)),
    )

    assert status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["error_code"] == "readiness_failed"
    assert payload["failed_checks"] == ["trace_persistence"]
    assert payload["checks"]["trace_persistence"] == "failed: trace_persistence_unavailable"
    assert str(blocking_file) not in json.dumps(payload)


def test_service_readiness_payload_is_fast_for_http_probes():
    started_at = time.perf_counter()

    payload = readiness_payload()

    assert payload["status"] == "ready"
    assert time.perf_counter() - started_at < 1.0


def test_service_ready_endpoint_reports_ready():
    status_code, payload = handle_request("GET", "/ready", b"")

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["tools"] == "ok"


def test_service_config_endpoint_reports_redacted_runtime_config():
    status_code, payload = handle_request(
        "GET",
        "/config",
        b"",
        headers={"Authorization": "Bearer secret"},
        config=ServiceConfig(
            host="0.0.0.0",
            port=9000,
            max_request_bytes=2048,
            max_goal_chars=1234,
            auth_token="secret",
            rate_limit_per_minute=12,
            max_concurrent_runs=3,
            idempotency_cache_size=5,
            runtime_allowed_tools_by_subject={"team-a": ("note",)},
            runtime_pending_approval_stale_seconds=1800,
            allow_full_trace_response=True,
            protect_diagnostics=True,
            trace_dir="/tmp/traces",
            run_timeout_seconds=7.5,
            request_timeout_seconds=4.5,
        ),
    )

    assert status_code == 200
    assert payload == {
        "host": "0.0.0.0",
        "port": "9000",
        "max_request_bytes": "2048",
        "max_goal_chars": "1234",
        "auth_required": "true",
        "auth_subject_count": "1",
        "rate_limit_per_minute": "12",
        "max_concurrent_runs": "3",
        "idempotency_cache_size": "5",
        "idempotency_cache_backend": "memory",
        "idempotency_cache_path_configured": "false",
        "runtime_allowed_tools": "default",
        "runtime_allowed_tools_by_subject_count": "1",
        "runtime_max_iterations": "10",
        "runtime_pending_approval_stale_seconds": "1800",
        "allow_full_trace_response": "true",
        "protect_diagnostics": "true",
        "trust_forwarded_for": "false",
        "run_timeout_seconds": "7.5",
        "request_timeout_seconds": "4.5",
        "trace_persistence": "enabled",
        "trace_directory_permissions": "0700",
        "trace_file_permissions": "0600",
        "trace_probe_file_permissions": "0600",
        "llm_provider": "unconfigured",
        "llm_base_url": "",
        "llm_model": "",
        "llm_api_key_configured": "false",
        "llm_timeout_seconds": "30.0",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
        "security_response_headers": "enabled",
        "cache_control_header": "no-store",
        "content_security_policy_header": (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        ),
        "referrer_policy_header": "no-referrer",
        "x_frame_options_header": "DENY",
        "x_content_type_options_header": "nosniff",
    }
    assert "secret" not in json.dumps(payload)


def test_service_version_endpoint_reports_package_version():
    status_code, payload = handle_request("GET", "/version", b"")

    assert status_code == 200
    assert payload == {"version": "0.1.0"}


def test_service_tools_endpoint_reports_registered_tool_metadata():
    status_code, payload = handle_request("GET", "/tools", b"")

    assert status_code == 200
    assert payload["tools"][0]["name"] == "calculate_sum"
    assert payload["tools"][-1]["name"] == "uppercase_text"


def test_service_runtime_tools_endpoint_reports_tool_schemas():
    status_code, payload = handle_request("GET", "/runtime/tools", b"")
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


def test_service_openapi_endpoint_reports_api_contract():
    status_code, payload = handle_request("GET", "/openapi.json", b"")

    assert status_code == 200
    assert payload["openapi"] == "3.1.0"
    assert sorted(payload["paths"]) == [
        "/config",
        "/health",
        "/metrics",
        "/metrics.prom",
        "/openapi.json",
        "/ready",
        "/run",
        "/runtime/approvals",
        "/runtime/approvals/summary",
        "/runtime/policy",
        "/runtime/resume",
        "/runtime/run",
        "/runtime/runs",
        "/runtime/runs/summary",
        "/runtime/runs/{run_id}",
        "/runtime/runs/{run_id}/artifacts",
        "/runtime/runs/{run_id}/artifacts/{artifact_id}",
        "/runtime/runs/{run_id}/cancel",
        "/runtime/runs/{run_id}/timeline",
        "/runtime/tools",
        "/tools",
        "/version",
    ]
    assert payload["paths"]["/health"]["head"]["summary"] == "Report service liveness headers"
    assert payload["paths"]["/run"]["options"]["summary"] == "Report supported HTTP methods"
    assert payload["paths"]["/run"]["post"]["requestBody"]["required"] is True
    assert payload["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"
    assert sorted(payload["paths"]["/run"]["post"]["responses"]) == [
        "200",
        "400",
        "401",
        "403",
        "408",
        "409",
        "413",
        "415",
        "417",
        "429",
        "500",
        "503",
        "504",
    ]


def test_service_metrics_normalizes_runtime_run_status_paths_over_http(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        run = _open_json(
            f"http://{host}:{port}/runtime/run",
            data=json.dumps(
                {
                    "goal": "write launch plan",
                    "plan": {
                        "actions": [
                            {
                                "id": "step-1",
                                "tool": "artifact",
                                "input": {
                                    "title": "Launch plan",
                                    "kind": "plan",
                                    "content": "# Ship\nDo the rollout.",
                                },
                            }
                        ]
                    },
                }
            ).encode("utf-8"),
        )
        artifact_id = run["observations"][0]["output"]["artifact_id"]
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}")
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}/timeline")
        _open_json(f"http://{host}:{port}/runtime/runs/{run['run_id']}/artifacts")
        _open_json(
            f"http://{host}:{port}/runtime/runs/{run['run_id']}/artifacts/{artifact_id}"
        )
        _open_json(
            f"http://{host}:{port}/runtime/runs/{run['run_id']}/cancel",
            data=b"{}",
        )
        _open_json(f"http://{host}:{port}/runtime/approvals")
        _open_json(f"http://{host}:{port}/runtime/approvals/summary")
        _open_json(f"http://{host}:{port}/runtime/policy")
        _open_json(f"http://{host}:{port}/runtime/runs")
        _open_json(f"http://{host}:{port}/runtime/runs/summary")
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["requests_by_path"]["/runtime/run"] == "1"
    assert metrics["requests_by_path"]["/runtime/approvals"] == "1"
    assert metrics["requests_by_path"]["/runtime/approvals/summary"] == "1"
    assert metrics["requests_by_path"]["/runtime/policy"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/summary"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/timeline"] == "1"
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/artifacts"] == "1"
    assert (
        metrics["requests_by_path"]["/runtime/runs/{run_id}/artifacts/{artifact_id}"]
        == "1"
    )
    assert metrics["requests_by_path"]["/runtime/runs/{run_id}/cancel"] == "1"


def test_service_metrics_tracks_requests_by_path_and_status():
    metrics = ServiceMetrics(started_at=10.0)
    metrics.record(method="GET", path="/health", status_code=200, duration_seconds=0.1)
    metrics.record(method="POST", path="/run", status_code=500, duration_seconds=0.2)
    metrics.record(method="POST", path="/run", status_code=200, duration_seconds=0.3)

    assert metrics.snapshot(now=15.0) == {
        "requests_total": "3",
        "responses_by_status": {"200": "2", "500": "1"},
        "requests_by_method": {"GET": "1", "POST": "2"},
        "requests_by_path": {"/health": "1", "/run": "2"},
        "requests_by_auth_subject": {},
        "error_responses_by_code": {},
        "request_duration_seconds_bucket": {
            "0.05": "0",
            "0.1": "1",
            "0.25": "2",
            "0.5": "3",
            "1": "3",
            "2.5": "3",
            "5": "3",
            "10": "3",
            "+Inf": "3",
        },
        "request_duration_seconds_count": "3",
        "request_duration_seconds_sum": "0.6000",
        "average_duration_seconds": "0.2000",
        "max_duration_seconds": "0.3000",
        "agent_runs_total": "0",
        "agent_runs_by_status": {},
        "agent_run_duration_seconds_bucket": {
            "0.05": "0",
            "0.1": "0",
            "0.25": "0",
            "0.5": "0",
            "1": "0",
            "2.5": "0",
            "5": "0",
            "10": "0",
            "+Inf": "0",
        },
        "agent_run_duration_seconds_count": "0",
        "agent_run_duration_seconds_sum": "0.0000",
        "average_agent_run_duration_seconds": "0.0000",
        "max_agent_run_duration_seconds": "0.0000",
        "runtime_runs_total": "0",
        "runtime_runs_by_status": {},
        "runtime_runs_by_auth_subject": {},
        "runtime_runs_by_auth_subject_status": {},
        "runtime_resumes_by_auth_subject": {},
        "runtime_failed_observations_total": "0",
        "runtime_observation_errors_by_code": {},
        "runtime_approval_required_total": "0",
        "runtime_failed_budget_exhaustions_total": "0",
        "runtime_run_duration_seconds_bucket": {
            "0.05": "0",
            "0.1": "0",
            "0.25": "0",
            "0.5": "0",
            "1": "0",
            "2.5": "0",
            "5": "0",
            "10": "0",
            "+Inf": "0",
        },
        "runtime_run_duration_seconds_count": "0",
        "runtime_run_duration_seconds_sum": "0.0000",
        "average_runtime_run_duration_seconds": "0.0000",
        "max_runtime_run_duration_seconds": "0.0000",
        "uptime_seconds": "5.0000",
    }


def test_service_metrics_tracks_requests_by_auth_subject():
    metrics = ServiceMetrics(started_at=10.0)

    metrics.record(method="POST", path="/run", status_code=200, auth_subject="team-a")
    metrics.record(method="POST", path="/run", status_code=500, auth_subject="team-a")
    metrics.record(method="POST", path="/run", status_code=200, auth_subject="ops")
    metrics.record(method="GET", path="/health", status_code=200)

    assert metrics.snapshot(now=12.0)["requests_by_auth_subject"] == {
        "ops": "1",
        "team-a": "2",
    }


def test_service_metrics_tracks_request_duration_histogram_buckets():
    metrics = ServiceMetrics(started_at=10.0)
    metrics.record(method="GET", path="/health", status_code=200, duration_seconds=0.1)
    metrics.record(method="POST", path="/run", status_code=200, duration_seconds=0.6)

    snapshot = metrics.snapshot(now=12.0)

    assert snapshot["request_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "1",
        "0.25": "1",
        "0.5": "1",
        "1": "2",
        "2.5": "2",
        "5": "2",
        "10": "2",
        "+Inf": "2",
    }
    assert snapshot["request_duration_seconds_count"] == "2"
    assert snapshot["request_duration_seconds_sum"] == "0.7000"


def test_service_metrics_tracks_agent_run_duration_histogram_buckets():
    metrics = ServiceMetrics(started_at=10.0)
    metrics.record_agent_run(status="done", duration_seconds=0.2)
    metrics.record_agent_run(status="timeout", duration_seconds=3.0)

    snapshot = metrics.snapshot(now=12.0)

    assert snapshot["agent_run_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "0",
        "0.25": "1",
        "0.5": "1",
        "1": "1",
        "2.5": "1",
        "5": "2",
        "10": "2",
        "+Inf": "2",
    }
    assert snapshot["agent_run_duration_seconds_count"] == "2"
    assert snapshot["agent_run_duration_seconds_sum"] == "3.2000"


def test_service_metrics_tracks_runtime_operational_counters():
    metrics = ServiceMetrics(started_at=10.0)

    metrics.record_runtime_run(
        status="requires_approval",
        failed_observation_count=0,
        approval_required_count=1,
        budget_exhausted=False,
        duration_seconds=0.2,
        auth_subject="team-a",
    )
    metrics.record_runtime_run(
        status="failed",
        failed_observation_count=2,
        approval_required_count=0,
        budget_exhausted=True,
        duration_seconds=3.0,
        auth_subject="team-a",
        resumed_by_auth_subject="default",
        error_code_counts={
            "invalid_tool_input": 1,
            "tool_execution_timeout": 1,
        },
    )
    metrics.record_runtime_run(
        status="done",
        failed_observation_count=0,
        approval_required_count=0,
        budget_exhausted=False,
        duration_seconds=0.4,
        auth_subject="ops",
    )

    snapshot = metrics.snapshot(now=12.0)

    assert snapshot["runtime_runs_total"] == "3"
    assert snapshot["runtime_runs_by_status"] == {
        "done": "1",
        "failed": "1",
        "requires_approval": "1",
    }
    assert snapshot["runtime_runs_by_auth_subject"] == {
        "ops": "1",
        "team-a": "2",
    }
    assert snapshot["runtime_runs_by_auth_subject_status"] == {
        "ops:done": "1",
        "team-a:failed": "1",
        "team-a:requires_approval": "1",
    }
    assert snapshot["runtime_resumes_by_auth_subject"] == {"default": "1"}
    assert snapshot["runtime_failed_observations_total"] == "2"
    assert snapshot["runtime_observation_errors_by_code"] == {
        "invalid_tool_input": "1",
        "tool_execution_timeout": "1",
    }
    assert snapshot["runtime_approval_required_total"] == "1"
    assert snapshot["runtime_failed_budget_exhaustions_total"] == "1"
    assert snapshot["runtime_run_duration_seconds_bucket"] == {
        "0.05": "0",
        "0.1": "0",
        "0.25": "1",
        "0.5": "2",
        "1": "2",
        "2.5": "2",
        "5": "3",
        "10": "3",
        "+Inf": "3",
    }
    assert snapshot["runtime_run_duration_seconds_count"] == "3"
    assert snapshot["runtime_run_duration_seconds_sum"] == "3.6000"
    assert snapshot["average_runtime_run_duration_seconds"] == "1.2000"
    assert snapshot["max_runtime_run_duration_seconds"] == "3.0000"


def test_service_metrics_bounds_http_method_cardinality():
    metrics = ServiceMetrics()

    metrics.record(method="post", path="/run", status_code=200)
    metrics.record(method="PATCH-EXPERIMENTAL-123", path="/run", status_code=405)
    metrics.record(method="TRACE", path="/run", status_code=405)

    snapshot = metrics.snapshot()

    assert snapshot["requests_by_method"] == {"POST": "1", "__unknown__": "2"}


def test_service_metrics_endpoint_reports_runtime_snapshot():
    metrics = ServiceMetrics()
    metrics.record(path="/health", status_code=200)

    status_code, payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert status_code == 200
    assert payload["requests_total"] == "1"
    assert payload["responses_by_status"] == {"200": "1"}


def test_service_metrics_endpoint_reports_agent_run_outcomes():
    metrics = ServiceMetrics()

    run_status, run_payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        metrics=metrics,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert run_status == 200
    assert run_payload["status"] == "done"
    assert metrics_status == 200
    assert metrics_payload["agent_runs_total"] == "1"
    assert metrics_payload["agent_runs_by_status"] == {"done": "1"}
    assert float(metrics_payload["average_agent_run_duration_seconds"]) >= 0
    assert float(metrics_payload["max_agent_run_duration_seconds"]) >= 0


def test_service_metrics_endpoint_reports_agent_failure_and_timeout_outcomes():
    metrics = ServiceMetrics()

    def failing_runner(goal, config):
        raise RuntimeError("boom")

    def slow_runner(goal, config):
        time.sleep(0.2)
        return {"status": "done", "goal": goal, "config": config}

    failed_status, _failed_payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        metrics=metrics,
        agent_runner=failing_runner,
    )
    timeout_status, _timeout_payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(run_timeout_seconds=0.01),
        metrics=metrics,
        agent_runner=slow_runner,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert failed_status == 500
    assert timeout_status == 504
    assert metrics_status == 200
    assert metrics_payload["agent_runs_total"] == "2"
    assert metrics_payload["agent_runs_by_status"] == {"failed": "1", "timeout": "1"}


def test_service_metrics_endpoint_reports_runtime_operational_outcomes():
    metrics = ServiceMetrics()

    approval_status, approval_payload = handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"fetch safely","plan":{"actions":[{"id":"step-1",'
            b'"tool":"http_request","input":{"url":"https://example.com"},'
            b'"reason":"fetch"}]}}'
        ),
        metrics=metrics,
    )
    failed_status, failed_payload = handle_request(
        "POST",
        "/runtime/run",
        (
            b'{"goal":"normalize","max_iterations":1,'
            b'"plan":{"actions":[{"id":"step-1","tool":"transform_text",'
            b'"input":{"text":" hello ","mode":"squash"},"reason":"normalize"}]}}'
        ),
        metrics=metrics,
    )
    metrics_status, metrics_payload = handle_request("GET", "/metrics", b"", metrics=metrics)

    assert approval_status == 200
    assert approval_payload["status"] == "requires_approval"
    assert failed_status == 200
    assert failed_payload["status"] == "failed"
    assert failed_payload["iteration_budget_remaining"] == "0"
    assert metrics_status == 200
    assert metrics_payload["runtime_runs_total"] == "2"
    assert metrics_payload["runtime_runs_by_status"] == {
        "failed": "1",
        "requires_approval": "1",
    }
    assert metrics_payload["runtime_failed_observations_total"] == "1"
    assert metrics_payload["runtime_observation_errors_by_code"] == {
        "invalid_tool_input": "1",
        "tool_not_allowed": "1",
    }
    assert metrics_payload["runtime_approval_required_total"] == "1"
    assert metrics_payload["runtime_failed_budget_exhaustions_total"] == "1"
    assert metrics_payload["runtime_run_duration_seconds_count"] == "2"
    assert float(metrics_payload["runtime_run_duration_seconds_sum"]) > 0
    assert float(metrics_payload["max_runtime_run_duration_seconds"]) > 0


def test_service_metrics_endpoint_reports_current_runtime_approval_queue(tmp_path):
    old_trace_path = persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "old-pending",
            "status": "requires_approval",
            "goal": "old approval",
            "auth_subject": "team-a",
            "pending_approval": {"id": "old-step", "tool": "http_request"},
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "fresh-pending",
            "status": "requires_approval",
            "goal": "fresh approval",
            "auth_subject": "team-a",
            "pending_approval": {"id": "fresh-step", "tool": "note"},
        },
        str(tmp_path),
    )
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "done-run",
            "status": "done",
            "goal": "done",
        },
        str(tmp_path),
    )
    old_timestamp = time.time() - 7200
    os.utime(old_trace_path, (old_timestamp, old_timestamp))

    status_code, metrics_payload = handle_request(
        "GET",
        "/metrics",
        b"",
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            runtime_pending_approval_stale_seconds=3600,
        ),
    )

    assert status_code == 200
    assert metrics_payload["runtime_pending_approvals_current"] == "2"
    assert metrics_payload["runtime_stale_pending_approvals_current"] == "1"
    assert int(metrics_payload["runtime_max_pending_approval_age_seconds"]) >= 3600
    assert metrics_payload["runtime_pending_approval_stale_seconds"] == "3600"


def test_service_metrics_endpoint_reports_concurrency_snapshot():
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)
    release = limiter.try_acquire()

    try:
        status_code, payload = handle_request(
            "GET",
            "/metrics",
            b"",
            concurrency_limiter=limiter,
        )
    finally:
        assert release is not None
        release()

    assert status_code == 200
    assert payload["active_concurrent_runs"] == "1"
    assert payload["max_concurrent_runs"] == "2"


def test_service_metrics_endpoint_reports_rate_limiter_snapshot():
    limiter = ServiceRateLimiter(limit_per_minute=2)
    limiter.allow("client-a")

    status_code, payload = handle_request("GET", "/metrics", b"", rate_limiter=limiter)

    assert status_code == 200
    assert payload["active_rate_limit_windows"] == "1"
    assert payload["rate_limit_per_minute"] == "2"


def test_service_prometheus_metrics_endpoint_reports_text_exposition(monkeypatch):
    monkeypatch.setenv("SELF_CORRECTING_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("SELF_CORRECTING_LLM_MODEL", "agent-runtime-model")
    monkeypatch.setenv("SELF_CORRECTING_LLM_API_KEY", "super-secret-api-key")
    monkeypatch.setenv("SELF_CORRECTING_LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("SELF_CORRECTING_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS", "0.25")
    metrics = ServiceMetrics()
    metrics.record(
        method="GET",
        path="/health",
        status_code=200,
        duration_seconds=0.125,
        auth_subject="team-a",
    )
    metrics.record(
        method="POST",
        path='/quoted"path\\segment',
        status_code=404,
        duration_seconds=0.0,
        error_code="not_found",
    )
    metrics.record_agent_run(status="done", duration_seconds=0.25)
    metrics.record_runtime_run(
        status="requires_approval",
        failed_observation_count=0,
        approval_required_count=1,
        budget_exhausted=False,
        duration_seconds=0.4,
        auth_subject="team-a",
        resumed_by_auth_subject="default",
    )
    metrics.record_runtime_run(
        status="failed",
        failed_observation_count=2,
        approval_required_count=0,
        budget_exhausted=True,
        duration_seconds=3.5,
        auth_subject="team-a",
        resumed_by_auth_subject="team-a",
        error_code_counts={
            "invalid_tool_input": 1,
            "tool_execution_timeout": 1,
        },
    )
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=2)
    idempotency_cache = ServiceIdempotencyCache(max_entries=5)
    release = limiter.try_acquire()

    try:
        status_code, payload = handle_request(
            "GET",
            "/metrics.prom",
            b"",
            config=ServiceConfig(
                host="0.0.0.0",
                port=9001,
                auth_token="secret",
                max_request_bytes=8192,
                rate_limit_per_minute=11,
                max_concurrent_runs=2,
                idempotency_cache_size=5,
                max_goal_chars=1234,
                allow_full_trace_response=True,
                protect_diagnostics=True,
                trust_forwarded_for=True,
                trace_dir="/var/lib/self-correcting-agent/traces",
                run_timeout_seconds=6.5,
                request_timeout_seconds=4.5,
            ),
            headers={"Authorization": "Bearer secret"},
            metrics=metrics,
            concurrency_limiter=limiter,
            idempotency_cache=idempotency_cache,
        )
    finally:
        assert release is not None
        release()

    assert status_code == 200
    assert isinstance(payload, str)
    assert "# HELP self_correcting_agent_responses_total" in payload
    assert "# TYPE self_correcting_agent_responses_total counter" in payload
    assert "# HELP self_correcting_agent_requests_by_method_total" in payload
    assert "# TYPE self_correcting_agent_requests_by_method_total counter" in payload
    assert "# HELP self_correcting_agent_requests_by_path_total" in payload
    assert "# TYPE self_correcting_agent_requests_by_path_total counter" in payload
    assert "# HELP self_correcting_agent_requests_by_auth_subject_total" in payload
    assert "# TYPE self_correcting_agent_requests_by_auth_subject_total counter" in payload
    assert "# HELP self_correcting_agent_error_responses_total" in payload
    assert "# TYPE self_correcting_agent_error_responses_total counter" in payload
    assert "# HELP self_correcting_agent_request_duration_seconds" in payload
    assert "# TYPE self_correcting_agent_request_duration_seconds histogram" in payload
    assert "# HELP self_correcting_agent_agent_run_duration_seconds" in payload
    assert "# TYPE self_correcting_agent_agent_run_duration_seconds histogram" in payload
    assert "# HELP self_correcting_agent_run_status_total" in payload
    assert "# TYPE self_correcting_agent_run_status_total counter" in payload
    assert "# HELP self_correcting_agent_runtime_runs_total" in payload
    assert "# TYPE self_correcting_agent_runtime_runs_total counter" in payload
    assert "# HELP self_correcting_agent_runtime_run_status_total" in payload
    assert "# TYPE self_correcting_agent_runtime_run_status_total counter" in payload
    assert "# HELP self_correcting_agent_runtime_runs_by_auth_subject_total" in payload
    assert "# TYPE self_correcting_agent_runtime_runs_by_auth_subject_total counter" in payload
    assert "# HELP self_correcting_agent_runtime_run_status_by_auth_subject_total" in payload
    assert (
        "# TYPE self_correcting_agent_runtime_run_status_by_auth_subject_total counter"
        in payload
    )
    assert "# HELP self_correcting_agent_runtime_resumes_by_auth_subject_total" in payload
    assert (
        "# TYPE self_correcting_agent_runtime_resumes_by_auth_subject_total counter"
        in payload
    )
    assert "# HELP self_correcting_agent_runtime_observation_errors_total" in payload
    assert "# TYPE self_correcting_agent_runtime_observation_errors_total counter" in payload
    assert "# HELP self_correcting_agent_runtime_final_answer_guardrails_total" in payload
    assert "# TYPE self_correcting_agent_runtime_final_answer_guardrails_total counter" in payload
    assert (
        "# HELP self_correcting_agent_runtime_final_answer_guardrails_by_reason_total"
        in payload
    )
    assert (
        "# TYPE self_correcting_agent_runtime_final_answer_guardrails_by_reason_total "
        "counter"
        in payload
    )
    assert "# HELP self_correcting_agent_runtime_run_duration_seconds" in payload
    assert "# TYPE self_correcting_agent_runtime_run_duration_seconds histogram" in payload
    assert "# HELP self_correcting_agent_active_concurrent_runs" in payload
    assert "# TYPE self_correcting_agent_active_concurrent_runs gauge" in payload
    assert "# HELP self_correcting_agent_idempotency_cache_hits" in payload
    assert "# TYPE self_correcting_agent_idempotency_cache_hits counter" in payload
    assert "self_correcting_agent_requests_total 2" in payload
    assert 'self_correcting_agent_responses_total{status="200"} 1' in payload
    assert 'self_correcting_agent_error_responses_total{error_code="not_found"} 1' in payload
    assert 'self_correcting_agent_requests_by_method_total{method="GET"} 1' in payload
    assert 'self_correcting_agent_requests_by_method_total{method="POST"} 1' in payload
    assert 'self_correcting_agent_requests_by_path_total{path="/health"} 1' in payload
    assert (
        'self_correcting_agent_requests_by_auth_subject_total{auth_subject="team-a"} 1'
        in payload
    )
    assert (
        'self_correcting_agent_requests_by_path_total{path="/quoted\\"path\\\\segment"} 1'
        in payload
    )
    assert 'self_correcting_agent_request_duration_seconds_bucket{le="0.05"} 1' in payload
    assert 'self_correcting_agent_request_duration_seconds_bucket{le="0.1"} 1' in payload
    assert 'self_correcting_agent_request_duration_seconds_bucket{le="0.25"} 2' in payload
    assert 'self_correcting_agent_request_duration_seconds_bucket{le="+Inf"} 2' in payload
    assert "self_correcting_agent_request_duration_seconds_count 2" in payload
    assert "self_correcting_agent_request_duration_seconds_sum 0.1250" in payload
    assert 'self_correcting_agent_agent_run_duration_seconds_bucket{le="0.25"} 1' in payload
    assert 'self_correcting_agent_agent_run_duration_seconds_bucket{le="+Inf"} 1' in payload
    assert "self_correcting_agent_agent_run_duration_seconds_count 1" in payload
    assert "self_correcting_agent_agent_run_duration_seconds_sum 0.2500" in payload
    assert "self_correcting_agent_active_concurrent_runs 1" in payload
    assert "self_correcting_agent_max_concurrent_runs 2" in payload
    assert "self_correcting_agent_max_request_bytes 8192" in payload
    assert "self_correcting_agent_average_duration_seconds 0.0625" in payload
    assert "self_correcting_agent_max_duration_seconds 0.1250" in payload
    assert "self_correcting_agent_runs_total 1" in payload
    assert 'self_correcting_agent_run_status_total{status="done"} 1' in payload
    assert "self_correcting_agent_runtime_runs_total 2" in payload
    assert (
        'self_correcting_agent_runtime_run_status_total{status="requires_approval"} 1'
        in payload
    )
    assert 'self_correcting_agent_runtime_run_status_total{status="failed"} 1' in payload
    assert (
        'self_correcting_agent_runtime_runs_by_auth_subject_total'
        '{auth_subject="team-a"} 2'
        in payload
    )
    assert (
        'self_correcting_agent_runtime_run_status_by_auth_subject_total'
        '{auth_subject="team-a",status="requires_approval"} 1'
        in payload
    )
    assert (
        'self_correcting_agent_runtime_run_status_by_auth_subject_total'
        '{auth_subject="team-a",status="failed"} 1'
        in payload
    )
    assert (
        'self_correcting_agent_runtime_resumes_by_auth_subject_total'
        '{auth_subject="default"} 1'
        in payload
    )
    assert (
        'self_correcting_agent_runtime_resumes_by_auth_subject_total'
        '{auth_subject="team-a"} 1'
        in payload
    )
    assert "self_correcting_agent_runtime_failed_observations_total 2" in payload
    assert (
        'self_correcting_agent_runtime_observation_errors_total'
        '{error_code="invalid_tool_input"} 1'
        in payload
    )
    assert (
        'self_correcting_agent_runtime_observation_errors_total'
        '{error_code="tool_execution_timeout"} 1'
        in payload
    )
    assert "self_correcting_agent_runtime_approval_required_total 1" in payload
    assert "self_correcting_agent_runtime_final_answer_guardrails_total 0" in payload
    assert "self_correcting_agent_runtime_pending_approvals_current 0" in payload
    assert "self_correcting_agent_runtime_stale_pending_approvals_current 0" in payload
    assert "self_correcting_agent_runtime_max_pending_approval_age_seconds 0" in payload
    assert "self_correcting_agent_runtime_pending_approval_stale_seconds 3600" in payload
    assert "self_correcting_agent_runtime_failed_budget_exhaustions_total 1" in payload
    assert 'self_correcting_agent_runtime_run_duration_seconds_bucket{le="0.5"} 1' in payload
    assert 'self_correcting_agent_runtime_run_duration_seconds_bucket{le="5"} 2' in payload
    assert 'self_correcting_agent_runtime_run_duration_seconds_bucket{le="+Inf"} 2' in payload
    assert "self_correcting_agent_runtime_run_duration_seconds_count 2" in payload
    assert "self_correcting_agent_runtime_run_duration_seconds_sum 3.9000" in payload
    assert "self_correcting_agent_average_agent_run_duration_seconds 0.2500" in payload
    assert "self_correcting_agent_max_agent_run_duration_seconds 0.2500" in payload
    assert "self_correcting_agent_uptime_seconds" in payload
    assert (
        'self_correcting_agent_build_info{auth_required="true",'
        'auth_subject_count="1",allow_full_trace_response="true",'
        'bind_host="0.0.0.0",bind_port="9001",'
        'idempotency_cache_backend="memory",'
        'idempotency_cache_path_configured="false",'
        'idempotency_cache_size="5",runtime_allowed_tools="default",'
        'runtime_allowed_tools_by_subject_count="0",'
        'runtime_max_iterations="10",'
        'max_concurrent_runs="2",'
        'max_goal_chars="1234",max_request_bytes="8192",'
        'protect_diagnostics="true",'
        'rate_limit_per_minute="11",'
        'request_timeout_seconds="4.5",run_timeout_seconds="6.5",'
        'trace_persistence="enabled",trust_forwarded_for="true",version="'
        in payload
    )
    assert 'security_response_headers="enabled"' in payload
    assert 'llm_provider="openai_compatible"' in payload
    assert 'llm_base_url="https://llm.example.test/v1"' in payload
    assert 'llm_model="agent-runtime-model"' in payload
    assert 'llm_api_key_configured="true"' in payload
    assert 'llm_timeout_seconds="12.5"' in payload
    assert 'llm_max_retries="2"' in payload
    assert 'llm_retry_backoff_seconds="0.25"' in payload
    assert "super-secret-api-key" not in payload
    assert 'cache_control_header="no-store"' in payload
    assert (
        'content_security_policy_header="default-src \'none\'; '
        "frame-ancestors 'none'; base-uri 'none'\""
    ) in payload
    assert 'referrer_policy_header="no-referrer"' in payload
    assert 'trace_directory_permissions="0700"' in payload
    assert 'trace_file_permissions="0600"' in payload
    assert 'trace_probe_file_permissions="0600"' in payload
    assert 'x_frame_options_header="DENY"' in payload
    assert 'x_content_type_options_header="nosniff"' in payload
    assert "secret" not in payload
    assert payload.endswith("\n")


def test_service_run_endpoint_returns_agent_summary():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["answer"] == "5"


def test_service_run_endpoint_rejects_full_trace_response_by_default():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
    )

    assert status_code == 403
    assert payload == {
        "status": "failed",
        "error_code": "full_trace_disabled",
        "error": "full_trace responses are disabled",
    }


def test_service_run_endpoint_can_return_full_trace_when_explicitly_enabled():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
        config=ServiceConfig(allow_full_trace_response=True),
    )

    assert status_code == 200
    assert payload["events"][0]["node"] == "planner"


def test_service_run_endpoint_rejects_oversized_request_body():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(max_request_bytes=8),
    )

    assert status_code == 413
    assert payload == {
        "status": "failed",
        "error_code": "request_too_large",
        "error": "request body too large",
    }


def test_service_run_endpoint_requires_bearer_token_when_configured():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 401
    assert payload == {
        "status": "failed",
        "error_code": "unauthorized",
        "error": "unauthorized",
    }


def test_service_failure_responses_include_machine_readable_error_code():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 401
    assert payload["error"] == "unauthorized"
    assert payload["error_code"] == "unauthorized"


def test_service_common_failure_responses_include_stable_error_codes():
    rate_limiter = ServiceRateLimiter(limit_per_minute=1)
    rate_limiter.allow("local")
    concurrency_limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    release = concurrency_limiter.try_acquire()

    try:
        cases = [
            (
                "request_too_large",
                handle_request(
                    "POST",
                    "/run",
                    b"{}",
                    config=ServiceConfig(max_request_bytes=1),
                ),
            ),
            (
                "unsupported_media_type",
                handle_request(
                    "POST",
                    "/run",
                    b"goal=calculate",
                    headers={"Content-Type": "text/plain"},
                ),
            ),
            (
                "rate_limit_exceeded",
                handle_request(
                    "POST",
                    "/run",
                    json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
                    rate_limiter=rate_limiter,
                ),
            ),
            (
                "too_many_concurrent_runs",
                handle_request(
                    "POST",
                    "/run",
                    json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
                    concurrency_limiter=concurrency_limiter,
                ),
            ),
            ("not_found", handle_request("GET", "/missing", b"")),
        ]
    finally:
        assert release is not None
        release()

    for expected_error_code, (status_code, payload) in cases:
        assert status_code >= 400
        assert payload["status"] == "failed"
        assert payload["error_code"] == expected_error_code
        assert payload["error"]


def test_service_run_endpoint_accepts_configured_bearer_token():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        headers={"Authorization": "Bearer secret"},
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["answer"] == "5"


def test_service_run_endpoint_accepts_named_internal_bearer_token():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        headers={"Authorization": "Bearer team-a-token"},
        config=ServiceConfig(auth_tokens={"team-a": "team-a-token"}),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["answer"] == "5"


def test_service_metrics_over_http_tracks_named_internal_auth_subject():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(auth_tokens={"team-a": "team-a-token"}),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        run_payload = _open_json(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Authorization": "Bearer team-a-token"},
        )
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert run_payload["status"] == "done"
    assert metrics["requests_by_auth_subject"] == {"team-a": "1"}


def test_service_config_loads_named_internal_bearer_tokens_from_env():
    config = ServiceConfig.from_env(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKENS": (
                '{"team-a":"team-a-token","ops":"ops-token"}'
            )
        }
    )

    assert config.auth_required is True
    assert config.auth_tokens == {
        "ops": "ops-token",
        "team-a": "team-a-token",
    }


def test_service_run_endpoint_accepts_lowercase_authorization_header():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        headers={"authorization": "Bearer secret"},
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 200
    assert payload["status"] == "done"


def test_service_run_endpoint_rejects_non_ascii_authorization_without_error():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        headers={"Authorization": "Bearer sécret"},
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 401
    assert payload == {
        "status": "failed",
        "error_code": "unauthorized",
        "error": "unauthorized",
    }


def test_service_rejects_duplicate_authorization_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(auth_token="secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Authorization: Bearer wrong\r\n"
                b"Authorization: Bearer secret\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 401 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "unauthorized",
        "error": "unauthorized",
    }


def test_service_authorization_uses_constant_time_compare(monkeypatch):
    compare_calls = []

    def compare_digest(left, right):
        compare_calls.append((left, right))
        return left == right

    monkeypatch.setattr(service_safety.hmac, "compare_digest", compare_digest)

    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        headers={"Authorization": "Bearer secret"},
        config=ServiceConfig(auth_token="secret"),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert compare_calls == [("Bearer secret", "Bearer secret")]


def test_service_run_endpoint_applies_rate_limit():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 429
    assert second_payload == {
        "status": "failed",
        "error_code": "rate_limit_exceeded",
        "error": "rate limit exceeded",
        "retry_after_seconds": "60",
    }


def test_service_rate_limit_key_prefers_named_internal_auth_subject():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
    config = ServiceConfig(
        auth_tokens={
            "team-a": "team-a-token",
            "team-b": "team-b-token",
        }
    )

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"Authorization": "Bearer team-a-token"},
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
        config=config,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"Authorization": "Bearer team-b-token"},
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
        config=config,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 200
    assert second_payload["status"] == "done"


def test_service_rate_limit_response_reports_dynamic_retry_after_seconds(monkeypatch):
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    assert limiter.allow("127.0.0.1", now=10.0) is True
    monkeypatch.setattr(service_runtime.time, "monotonic", lambda: 15.0)

    status_code, payload = handle_request(
        "POST",
        "/run",
        body,
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert status_code == 429
    assert payload == {
        "status": "failed",
        "error_code": "rate_limit_exceeded",
        "error": "rate limit exceeded",
        "retry_after_seconds": "55",
    }


def test_service_rate_limit_key_ignores_forwarded_for_by_default():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "198.51.100.10"},
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "198.51.100.11"},
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 429
    assert second_payload == {
        "status": "failed",
        "error_code": "rate_limit_exceeded",
        "error": "rate limit exceeded",
        "retry_after_seconds": "60",
    }


def test_service_rate_limit_key_can_trust_lowercase_forwarded_for_header():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "198.51.100.10"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "198.51.100.11"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 200
    assert second_payload["status"] == "done"


def test_service_rate_limit_key_rejects_unsafe_forwarded_for_values():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "a" * 129},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "b" * 129},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 429
    assert second_payload["error_code"] == "rate_limit_exceeded"


def test_service_rate_limit_key_rejects_non_ip_forwarded_for_values():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "not-an-ip-a"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "not-an-ip-b"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 429
    assert second_payload["error_code"] == "rate_limit_exceeded"


def test_service_rate_limit_key_normalizes_forwarded_for_ip_values():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "2001:0db8:0000:0000:0000:0000:0000:0001"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        headers={"x-forwarded-for": "2001:db8::1"},
        config=ServiceConfig(trust_forwarded_for=True),
        remote_addr="127.0.0.1",
        rate_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 429
    assert second_payload["error_code"] == "rate_limit_exceeded"


def test_service_config_reads_environment_defaults():
    config = ServiceConfig.from_env(
        {
            "SELF_CORRECTING_SERVICE_HOST": "0.0.0.0",
            "SELF_CORRECTING_SERVICE_PORT": "9000",
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "secret",
            "SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES": "2048",
            "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS": "1234",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "12",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "3",
            "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE": "5",
            "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH": "/tmp/agent-idempotency.sqlite3",
            "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS": "note,artifact",
            "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT": (
                '{"team-a":"note,transform_text","ops":["artifact","note"]}'
            ),
            "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS": "17",
            "SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS": "1800",
            "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE": "true",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
            "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR": "true",
            "SELF_CORRECTING_SERVICE_TRACE_DIR": "/tmp/agent-traces",
            "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS": "9.5",
            "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS": "4.5",
        }
    )

    assert config.host == "0.0.0.0"
    assert config.port == 9000
    assert config.auth_token == "secret"
    assert config.max_request_bytes == 2048
    assert config.max_goal_chars == 1234
    assert config.rate_limit_per_minute == 12
    assert config.max_concurrent_runs == 3
    assert config.idempotency_cache_size == 5
    assert config.idempotency_cache_path == "/tmp/agent-idempotency.sqlite3"
    assert config.runtime_allowed_tools == ("artifact", "note")
    assert config.runtime_allowed_tools_by_subject == {
        "ops": ("artifact", "note"),
        "team-a": ("note", "transform_text"),
    }
    assert config.runtime_max_iterations == 17
    assert config.runtime_pending_approval_stale_seconds == 1800
    assert config.allow_full_trace_response is True
    assert config.protect_diagnostics is True
    assert config.trust_forwarded_for is True
    assert config.trace_dir == "/tmp/agent-traces"
    assert config.run_timeout_seconds == 9.5
    assert config.request_timeout_seconds == 4.5


def test_service_config_rejects_protected_diagnostics_without_auth_token():
    try:
        ServiceConfig(protect_diagnostics=True)
    except ValueError as exc:
        assert str(exc) == "protect_diagnostics requires auth_token"
    else:
        raise AssertionError("protected diagnostics without auth token was accepted")


def test_service_config_rejects_unknown_runtime_allowed_tools():
    try:
        ServiceConfig(runtime_allowed_tools=("note", "missing_tool"))
    except ValueError as exc:
        assert str(exc) == "runtime_allowed_tools contains unknown tools: missing_tool"
    else:
        raise AssertionError("unknown runtime allowed tool was accepted")


def test_service_config_rejects_unknown_subject_runtime_allowed_tools():
    try:
        ServiceConfig(
            runtime_allowed_tools_by_subject={"team-a": ("note", "missing_tool")}
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "runtime_allowed_tools_by_subject contains unknown tools for team-a: missing_tool"
        )
    else:
        raise AssertionError("unknown subject runtime allowed tool was accepted")


def test_service_config_rejects_non_positive_runtime_iteration_cap():
    try:
        ServiceConfig(runtime_max_iterations=0)
    except ValueError as exc:
        assert str(exc) == "runtime_max_iterations must be at least 1"
    else:
        raise AssertionError("non-positive runtime iteration cap was accepted")


def test_service_config_rejects_invalid_pending_approval_stale_threshold():
    try:
        ServiceConfig(runtime_pending_approval_stale_seconds=-1)
    except ValueError as exc:
        assert str(exc) == (
            "runtime_pending_approval_stale_seconds must be non-negative"
        )
    else:
        raise AssertionError("negative pending approval stale threshold was accepted")


def test_service_module_reports_invalid_environment_config_without_traceback():
    env = os.environ.copy()
    env["SELF_CORRECTING_SERVICE_PORT"] = "not-a-port"

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.service",
            "--help",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "SELF_CORRECTING_SERVICE_PORT must be an integer" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_service_cli_handles_sigterm_with_graceful_exit():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])

    process = subprocess.Popen(
        [
            ".venv/bin/self-correcting-agent-serve",
            "--host",
            "127.0.0.1",
            "--port",
            port,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        serving_line = process.stdout.readline()
        assert json.loads(serving_line)["status"] == "serving"

        process.send_signal(signal.SIGTERM)

        stdout, stderr = process.communicate(timeout=5)
        assert stdout == ""
        assert stderr == ""
        assert process.returncode == 143
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_service_rate_limiter_enforces_fixed_window_limit():
    limiter = ServiceRateLimiter(limit_per_minute=2)

    assert limiter.allow("client-a", now=10.0) is True
    assert limiter.allow("client-a", now=11.0) is True
    assert limiter.allow("client-a", now=12.0) is False
    assert limiter.allow("client-a", now=71.0) is True


def test_service_rate_limiter_can_be_disabled():
    limiter = ServiceRateLimiter(limit_per_minute=0)

    assert limiter.allow("client-a", now=10.0) is True
    assert limiter.allow("client-a", now=10.0) is True


def test_service_rate_limiter_prunes_expired_windows():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    limiter.allow("client-a", now=10.0)
    limiter.allow("client-b", now=20.0)

    limiter.allow("client-c", now=81.0)

    assert limiter.snapshot(now=81.0) == {
        "active_rate_limit_windows": "1",
        "rate_limit_per_minute": "1",
    }


def test_service_rate_limiter_snapshot_prunes_expired_windows_without_new_requests():
    limiter = ServiceRateLimiter(limit_per_minute=1)
    limiter.allow("client-a", now=10.0)
    limiter.allow("client-b", now=20.0)

    assert limiter.snapshot(now=81.0) == {
        "active_rate_limit_windows": "0",
        "rate_limit_per_minute": "1",
    }


def test_service_concurrency_limiter_rejects_when_run_slots_are_full():
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    release = limiter.try_acquire()
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        status_code, payload = handle_request(
            "POST",
            "/run",
            body,
            concurrency_limiter=limiter,
        )
    finally:
        assert release is not None
        release()

    assert status_code == 503
    assert payload == {
        "status": "failed",
        "error_code": "too_many_concurrent_runs",
        "error": "too many concurrent runs",
        "retry_after_seconds": "1",
    }


def test_service_concurrency_limiter_releases_slot_after_run():
    limiter = ServiceConcurrencyLimiter(max_concurrent_runs=1)
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    first_status, first_payload = handle_request(
        "POST",
        "/run",
        body,
        concurrency_limiter=limiter,
    )
    second_status, second_payload = handle_request(
        "POST",
        "/run",
        body,
        concurrency_limiter=limiter,
    )

    assert first_status == 200
    assert first_payload["status"] == "done"
    assert second_status == 200
    assert second_payload["status"] == "done"


def test_service_access_log_record_is_structured():
    record = access_log_record(
        method="POST",
        path="/run",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
    )

    assert record == {
        "event": "http_request",
        "method": "POST",
        "path": "/run",
        "status_code": 200,
        "duration_seconds": "0.1250",
        "request_id": "req-123",
        "remote_addr": "127.0.0.1",
    }


def test_service_access_log_schema_documents_required_and_optional_fields():
    schema = service_module.access_log_schema()

    assert schema["type"] == "object"
    assert schema["required"] == [
        "event",
        "method",
        "path",
        "status_code",
        "duration_seconds",
        "request_id",
        "remote_addr",
    ]
    assert schema["properties"]["event"] == {"type": "string", "const": "http_request"}
    assert schema["properties"]["status_code"] == {"type": "integer"}
    assert schema["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schema["properties"]["error_code"]["type"] == "string"
    assert schema["properties"]["run_id"]["type"] == "string"
    assert schema["properties"]["trace_path"]["type"] == "string"
    assert schema["properties"]["idempotency_key_present"]["type"] == "boolean"
    assert schema["properties"]["request_body_bytes"]["type"] == "integer"
    assert schema["properties"]["auth_subject"]["type"] == "string"
    assert schema["properties"]["runtime_owner_auth_subject"]["type"] == "string"
    assert schema["properties"]["resumed_by_auth_subject"]["type"] == "string"


def test_service_access_log_record_includes_error_code_when_present():
    record = access_log_record(
        method="GET",
        path="/missing",
        status_code=404,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        error_code="not_found",
    )

    assert record["error_code"] == "not_found"


def test_service_access_log_record_includes_run_correlation_fields_when_present():
    record = access_log_record(
        method="POST",
        path="/run",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        run_id="run-123",
        trace_path="/tmp/traces/run-123.json",
    )

    assert record["run_id"] == "run-123"
    assert record["trace_path"] == "/tmp/traces/run-123.json"


def test_service_access_log_record_includes_idempotency_presence_when_present():
    record = access_log_record(
        method="POST",
        path="/run",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        idempotency_key_present=True,
    )

    assert record["idempotency_key_present"] is True


def test_service_access_log_record_includes_request_body_bytes_when_present():
    record = access_log_record(
        method="POST",
        path="/run",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        request_body_bytes=32,
    )

    assert record["request_body_bytes"] == 32


def test_service_access_log_record_includes_auth_subject_when_present():
    record = access_log_record(
        method="POST",
        path="/run",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        auth_subject="team-a",
    )

    assert record["auth_subject"] == "team-a"


def test_service_access_log_record_includes_resume_actor_when_present():
    record = access_log_record(
        method="POST",
        path="/runtime/resume",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        resumed_by_auth_subject="default",
    )

    assert record["resumed_by_auth_subject"] == "default"


def test_service_access_log_record_includes_runtime_owner_when_present():
    record = access_log_record(
        method="POST",
        path="/runtime/resume",
        status_code=200,
        duration_seconds=0.125,
        request_id="req-123",
        remote_addr="127.0.0.1",
        runtime_owner_auth_subject="team-a",
    )

    assert record["runtime_owner_auth_subject"] == "team-a"


def test_service_access_log_write_flushes_stderr(monkeypatch):
    class FakeStderr:
        def __init__(self):
            self.lines = []
            self.flushes = 0

        def write(self, value):
            self.lines.append(value)

        def flush(self):
            self.flushes += 1

    class FakeHandler:
        command = "GET"
        path = "/health"

        def _request_id(self):
            return "req-123"

        def _remote_addr(self):
            return "127.0.0.1"

        def _metrics(self):
            return ServiceMetrics()

    fake_stderr = FakeStderr()
    monkeypatch.setattr(service_module.sys, "stderr", fake_stderr)

    service_module._AgentRequestHandler._write_access_log(
        FakeHandler(),
        200,
        {"status": "ok"},
    )

    assert fake_stderr.lines
    assert fake_stderr.flushes == 1


def test_service_run_endpoint_can_return_full_trace():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
        config=ServiceConfig(allow_full_trace_response=True),
    )

    assert status_code == 200
    assert payload["status"] == "done"
    assert payload["answer"] == "5"
    assert payload["events"][0]["node"] == "planner"
    assert payload["verification_results"][0]["passed"] == "true"


def test_service_run_endpoint_can_persist_full_trace(tmp_path):
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )

    trace_path = Path(payload["trace_path"])
    trace_payload = json.loads(trace_path.read_text())

    assert status_code == 200
    assert trace_path.parent == tmp_path
    assert trace_payload["run_id"] == payload["run_id"]
    assert trace_payload["events"][0]["node"] == "planner"


def test_service_trace_persistence_keeps_run_id_inside_trace_dir(tmp_path):
    trace_dir = tmp_path / "traces"
    outside_path = tmp_path / "outside.json"

    trace_path = Path(
        service_module._persist_trace(
            {"run_id": "../outside", "status": "done"},
            str(trace_dir),
        )
    )

    assert trace_path.parent == trace_dir
    assert trace_path.name != "../outside.json"
    assert json.loads(trace_path.read_text())["run_id"] == "../outside"
    assert not outside_path.exists()


def test_service_run_endpoint_times_out_slow_agent_runner():
    def slow_runner(goal, config):
        time.sleep(0.2)
        return {"status": "done", "goal": goal, "config": config}

    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        config=ServiceConfig(run_timeout_seconds=0.01),
        agent_runner=slow_runner,
    )

    assert status_code == 504
    assert payload == {
        "status": "failed",
        "error_code": "agent_run_timeout",
        "error": "agent run timed out",
    }


def test_service_run_endpoint_wraps_agent_runner_exceptions():
    def failing_runner(goal, config):
        raise RuntimeError("boom")

    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        agent_runner=failing_runner,
    )

    assert status_code == 500
    assert payload == {
        "status": "failed",
        "error_code": "agent_run_failed",
        "error": "agent run failed",
    }


def test_service_run_endpoint_rejects_bad_json():
    status_code, payload = handle_request("POST", "/run", b"{not-json}")

    assert status_code == 400
    assert payload["status"] == "failed"
    assert payload["error"].startswith("invalid JSON")


def test_service_run_endpoint_rejects_non_json_content_type():
    status_code, payload = handle_request(
        "POST",
        "/run",
        b"goal=calculate",
        headers={"Content-Type": "text/plain"},
    )

    assert status_code == 415
    assert payload == {
        "status": "failed",
        "error_code": "unsupported_media_type",
        "error": "content-type must be application/json",
    }


def test_service_run_endpoint_rejects_lowercase_non_json_content_type():
    status_code, payload = handle_request(
        "POST",
        "/run",
        b"goal=calculate",
        headers={"content-type": "text/plain"},
    )

    assert status_code == 415
    assert payload == {
        "status": "failed",
        "error_code": "unsupported_media_type",
        "error": "content-type must be application/json",
    }


def test_service_rejects_duplicate_content_type_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 415 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "unsupported_media_type",
        "error": "content-type must be single-valued application/json",
    }


def test_service_run_endpoint_rejects_invalid_config():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3", "max_steps": 0}).encode("utf-8"),
    )

    assert status_code == 400
    assert payload == {
        "status": "failed",
        "error_code": "invalid_agent_config",
        "error": "max_steps must be at least 1",
    }


def test_service_rejects_unknown_route():
    status_code, payload = handle_request("GET", "/missing", b"")

    assert status_code == 404
    assert payload == {
        "status": "failed",
        "error_code": "not_found",
        "error": "not found",
    }


def test_service_rejects_unsupported_http_method_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            payload = json.loads(exc.read().decode("utf-8"))
            content_type = exc.headers["Content-Type"]
            content_type_options = exc.headers["X-Content-Type-Options"]
            allow_header = exc.headers["Allow"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 405
    assert allow_header == "GET, HEAD, OPTIONS, POST"
    assert content_type == "application/json"
    assert content_type_options == "nosniff"
    assert payload == {
        "status": "failed",
        "error_code": "method_not_allowed",
        "error": "method not allowed",
    }


def test_service_head_health_returns_headers_without_body_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("HEAD", "/health", headers={"X-Request-ID": "head-req"})
        response = connection.getresponse()
        body = response.read()
        status_code = response.status
        content_type = response.getheader("Content-Type")
        request_id = response.getheader("X-Request-ID")
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 200
    assert content_type == "application/json"
    assert request_id == "head-req"
    assert body == b""


def test_service_options_reports_allowed_methods_without_body_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("OPTIONS", "/run")
        response = connection.getresponse()
        body = response.read()
        status_code = response.status
        allow_header = response.getheader("Allow")
        content_length = response.getheader("Content-Length")
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 204
    assert allow_header == "GET, HEAD, OPTIONS, POST"
    assert content_length == "0"
    assert body == b""


def test_service_can_serve_health_and_run_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        health = _open_json(f"http://{host}:{port}/health")
        ready = _open_json(f"http://{host}:{port}/ready")
        run = _open_json(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert health == {"status": "ok"}
    assert ready["status"] == "ready"
    assert run["status"] == "done"
    assert run["answer"] == "5"


def test_service_access_log_includes_run_id_for_run_over_http(capsys):
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        run = _open_json(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    records = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.strip()
    ]
    run_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/run"
    ]

    assert run_records[-1]["run_id"] == run["run_id"]
    assert run_records[-1]["request_body_bytes"] == len(
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
    )


def test_service_access_log_includes_internal_auth_subject_without_token(capsys):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(auth_tokens={"team-a": "team-a-token"}),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=body,
            headers={
                "Authorization": "Bearer team-a-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            run = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    stderr = capsys.readouterr().err
    records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    run_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/run"
    ]

    assert run["status"] == "done"
    assert run_records[-1]["auth_subject"] == "team-a"
    assert "team-a-token" not in stderr


def test_service_access_log_includes_runtime_resume_actor_and_owner_over_http(
    tmp_path,
    capsys,
):
    pending_action = {
        "id": "step-1",
        "tool": "note",
        "input": {"text": "approved note"},
        "reason": "record approved note",
    }
    service_module._persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "pending-team-a",
            "status": "requires_approval",
            "goal": "record approved note",
            "auth_subject": "team-a",
            "plan": {"actions": [pending_action], "final_answer": "recorded"},
            "pending_approval": pending_action,
        },
        str(tmp_path),
    )
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_token="admin-token",
            auth_tokens={"team-a": "team-a-token"},
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps(
        {
            "run_id": "pending-team-a",
            "approved_action_ids": ["step-1"],
        }
    ).encode("utf-8")

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/runtime/resume",
            data=body,
            headers={
                "Authorization": "Bearer admin-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            run = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    stderr = capsys.readouterr().err
    records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    resume_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/runtime/resume"
    ]

    assert run["status"] == "done"
    assert run["auth_subject"] == "team-a"
    assert run["resumed_by_auth_subject"] == "default"
    assert resume_records[-1]["auth_subject"] == "default"
    assert resume_records[-1]["resumed_by_auth_subject"] == "default"
    assert resume_records[-1]["runtime_owner_auth_subject"] == "team-a"
    assert "admin-token" not in stderr
    assert "team-a-token" not in stderr


def test_service_access_log_includes_trace_path_for_persisted_run_over_http(tmp_path, capsys):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        run = _open_json(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    records = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.strip()
    ]
    run_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/run"
    ]

    assert run_records[-1]["run_id"] == run["run_id"]
    assert run_records[-1]["trace_path"] == run["trace_path"]


def test_service_access_log_marks_idempotency_key_presence_without_logging_key(capsys):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(idempotency_cache_size=8),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    idempotency_key = "retry-secret-123"

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    stderr = capsys.readouterr().err
    records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
    run_records = [
        record
        for record in records
        if record["method"] == "POST" and record["path"] == "/run"
    ]

    assert run_records[-1]["idempotency_key_present"] is True
    assert idempotency_key not in stderr


def test_service_can_serve_prometheus_metrics_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        _open_json(f"http://{host}:{port}/health")
        text, content_type = _open_text(f"http://{host}:{port}/metrics.prom")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert content_type.startswith("text/plain")
    assert "self_correcting_agent_requests_total" in text
    assert "self_correcting_agent_active_concurrent_runs" in text


def test_service_echoes_request_id_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/health",
            headers={"X-Request-ID": "req-123"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            request_id = response.headers["X-Request-ID"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert request_id == "req-123"


def test_service_run_response_includes_run_id_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            run_id_header = response.headers["X-Run-ID"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert run_id_header == payload["run_id"]


def test_service_run_response_includes_trace_path_header_over_http(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            trace_path_header = response.headers["X-Trace-Path"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert trace_path_header == payload["trace_path"]
    assert Path(trace_path_header).exists()


def test_service_runtime_run_response_includes_trace_path_header_over_http(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(tmp_path)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/runtime/run",
            data=json.dumps(
                {
                    "goal": "capture hello",
                    "plan": {
                        "actions": [
                            {
                                "id": "step-1",
                                "tool": "note",
                                "input": {"text": "hello"},
                            }
                        ]
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            trace_path_header = response.headers["X-Trace-Path"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert trace_path_header == payload["trace_path"]
    assert Path(trace_path_header).exists()


def test_service_unauthorized_response_includes_www_authenticate_header_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(auth_token="secret"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            authenticate_header = exc.headers["WWW-Authenticate"]
            payload = json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 401
    assert authenticate_header == "Bearer"
    assert payload["error_code"] == "unauthorized"


def test_service_rate_limited_response_includes_retry_after_header_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(rate_limit_per_minute=1),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        for _attempt in range(2):
            request = urllib.request.Request(
                f"http://{host}:{port}/run",
                data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as exc:
                status_code = exc.code
                retry_after = exc.headers["Retry-After"]
                payload = json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 429
    assert retry_after == "60"
    assert payload["error_code"] == "rate_limit_exceeded"
    assert payload["retry_after_seconds"] == retry_after


def test_service_concurrency_rejection_includes_retry_after_header_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(max_concurrent_runs=1),
    )
    release = server.service_concurrency_limiter.try_acquire()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            retry_after = exc.headers["Retry-After"]
            payload = json.loads(exc.read().decode("utf-8"))
    finally:
        assert release is not None
        release()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status_code == 503
    assert retry_after == "1"
    assert payload["error_code"] == "too_many_concurrent_runs"
    assert payload["retry_after_seconds"] == retry_after


def test_service_run_response_omits_unsafe_run_id_header():
    status_code, payload = handle_request(
        "POST",
        "/run",
        json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
        agent_runner=lambda goal, config: {"status": "done", "run_id": "bad\nid"},
    )

    assert status_code == 200
    assert payload["run_id"] == "bad\nid"
    assert not service_module._safe_response_header_value(payload["run_id"])


def test_service_accepts_safe_request_id_header_value():
    assert service_module._request_id_from_headers({"X-Request-ID": "req-123_A"}) == "req-123_A"


def test_service_replaces_unsafe_request_id_header_value():
    request_id = service_module._request_id_from_headers({"X-Request-ID": "bad\nid"})

    assert UUID(request_id)
    assert request_id != "bad\nid"


def test_service_replaces_oversized_request_id_header_value():
    request_id = service_module._request_id_from_headers({"X-Request-ID": "x" * 129})

    assert UUID(request_id)
    assert request_id != "x" * 129


def test_service_sets_content_type_options_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            content_type_options = response.headers["X-Content-Type-Options"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert content_type_options == "nosniff"


def test_service_server_header_does_not_expose_python_runtime_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        request = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            server_header = response.headers["Server"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert server_header == "SelfCorrectingAgentHTTP/0.1"
    assert "Python" not in server_header


def test_service_sets_common_security_headers_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        get_request = urllib.request.Request(f"http://{host}:{port}/health", method="GET")
        with urllib.request.urlopen(get_request, timeout=5) as response:
            get_cache_control = response.headers["Cache-Control"]
            get_referrer_policy = response.headers["Referrer-Policy"]
            get_content_security_policy = response.headers["Content-Security-Policy"]
            get_frame_options = response.headers["X-Frame-Options"]

        connection = http.client.HTTPConnection(host, port, timeout=5)
        connection.request("HEAD", "/health")
        head_response = connection.getresponse()
        head_response.read()
        head_cache_control = head_response.getheader("Cache-Control")
        head_referrer_policy = head_response.getheader("Referrer-Policy")
        head_content_security_policy = head_response.getheader("Content-Security-Policy")
        head_frame_options = head_response.getheader("X-Frame-Options")
        connection.close()

        options_connection = http.client.HTTPConnection(host, port, timeout=5)
        options_connection.request("OPTIONS", "/run")
        options_response = options_connection.getresponse()
        options_response.read()
        options_cache_control = options_response.getheader("Cache-Control")
        options_referrer_policy = options_response.getheader("Referrer-Policy")
        options_content_security_policy = options_response.getheader("Content-Security-Policy")
        options_frame_options = options_response.getheader("X-Frame-Options")
        options_connection.close()

        put_request = urllib.request.Request(
            f"http://{host}:{port}/run",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            urllib.request.urlopen(put_request, timeout=5)
        except urllib.error.HTTPError as exc:
            error_cache_control = exc.headers["Cache-Control"]
            error_referrer_policy = exc.headers["Referrer-Policy"]
            error_content_security_policy = exc.headers["Content-Security-Policy"]
            error_frame_options = exc.headers["X-Frame-Options"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert get_cache_control == "no-store"
    assert head_cache_control == "no-store"
    assert options_cache_control == "no-store"
    assert error_cache_control == "no-store"
    assert get_referrer_policy == "no-referrer"
    assert head_referrer_policy == "no-referrer"
    assert options_referrer_policy == "no-referrer"
    assert error_referrer_policy == "no-referrer"
    assert (
        get_content_security_policy
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert (
        head_content_security_policy
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert (
        options_content_security_policy
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert (
        error_content_security_policy
        == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )
    assert get_frame_options == "DENY"
    assert head_frame_options == "DENY"
    assert options_frame_options == "DENY"
    assert error_frame_options == "DENY"


def test_service_rejects_invalid_content_length_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: not-int\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    status_code = int(status_line.split()[1])
    payload = json.loads(body.decode("utf-8"))

    assert status_code == 400
    assert payload == {
        "status": "failed",
        "error_code": "invalid_content_length",
        "error": "invalid content-length",
    }


def test_service_rejects_negative_content_length_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: -1\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 400 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_content_length",
        "error": "invalid content-length",
    }


def test_service_rejects_duplicate_content_length_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 2\r\n"
                b"Content-Length: 27\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b'{}{"goal": "calculate 2 + 3"}'
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 400 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_content_length",
        "error": "invalid content-length",
    }


def test_service_rejects_transfer_encoding_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Transfer-Encoding: chunked\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 400 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_transfer_encoding",
        "error": "transfer-encoding is unsupported",
    }


def test_service_rejects_expect_header_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Expect: 100-continue\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 417 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "expectation_failed",
        "error": "expect header is unsupported",
    }


def test_service_rejects_duplicate_idempotency_key_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(idempotency_cache_size=8),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Idempotency-Key: retry-a\r\n"
                b"Idempotency-Key: retry-b\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n"
                b"\r\n"
                + body
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 400 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_idempotency_key",
        "error": "idempotency key must be single-valued",
    }


def test_service_rejects_incomplete_request_body_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 32\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b'{"goal": "calculate 2'
            )
            client.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    status_line, body = response.split(b"\r\n", 1)[0], response.split(b"\r\n\r\n", 1)[1]
    assert b" 400 " in status_line
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "incomplete_request_body",
        "error": "request body ended before content-length bytes were read",
    }


def test_service_returns_request_timeout_when_body_read_times_out_over_http():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(request_timeout_seconds=0.2),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.settimeout(2)
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 32\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b'{"goal": "calculate'
            )
            chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    headers_blob, body = response.split(b"\r\n\r\n", 1)
    status_line = headers_blob.split(b"\r\n", 1)[0]
    assert b" 408 " in status_line
    assert b"Retry-After: 1" in headers_blob
    assert json.loads(body.decode("utf-8")) == {
        "status": "failed",
        "error_code": "request_body_timeout",
        "error": "timed out while reading request body",
        "retry_after_seconds": "1",
    }


def test_service_closes_slow_incomplete_requests_after_configured_timeout():
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(request_timeout_seconds=0.2),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        with socket.create_connection((host, port), timeout=5) as client:
            client.settimeout(2)
            client.sendall(
                b"POST /run HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n"
                b"Content-Type: application/json\r\n"
            )
            started_at = time.perf_counter()
            response = client.recv(4096)
            elapsed = time.perf_counter() - started_at
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response == b""
    assert elapsed < 1.5


def test_service_metrics_endpoint_counts_prior_http_requests():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        _open_json(f"http://{host}:{port}/health")
        _open_json(f"http://{host}:{port}/version")
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["requests_total"] == "2"
    assert metrics["requests_by_method"] == {"GET": "2"}
    assert metrics["requests_by_path"] == {"/health": "1", "/version": "1"}
    assert float(metrics["average_duration_seconds"]) > 0
    assert float(metrics["max_duration_seconds"]) > 0
    assert float(metrics["uptime_seconds"]) >= 0


def test_service_metrics_endpoint_counts_error_responses_by_code_over_http():
    server = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        try:
            _open_json(f"http://{host}:{port}/missing-random-123")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["error_responses_by_code"] == {"not_found": "1"}
    assert metrics["requests_by_path"] == {"__unknown__": "1"}


def test_service_metrics_counts_readiness_failures_by_error_code_over_http(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace directory creation")
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(trace_dir=str(blocking_file / "traces")),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        try:
            _open_json(f"http://{host}:{port}/ready")
        except urllib.error.HTTPError as exc:
            assert exc.code == 503
        metrics = _open_json(f"http://{host}:{port}/metrics")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert metrics["error_responses_by_code"] == {"readiness_failed": "1"}
    assert metrics["requests_by_path"] == {"/ready": "1"}


def _open_json(url: str, data=None, headers=None):
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def _open_text(url: str):
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8"), response.headers["Content-Type"]
