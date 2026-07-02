import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from self_correcting_langgraph_agent.service import ServiceConfig, create_server


def test_continuous_iterate_writes_jsonl_metrics(tmp_path):
    log_path = tmp_path / "continuous.log"
    metrics_path = tmp_path / "metrics.jsonl"
    eval_path = tmp_path / "eval.json"
    fake_check = tmp_path / "fake_check.sh"
    fake_check.write_text(
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "cat > \"$SELF_CORRECTING_EVAL_FILE\" <<'JSON'\n"
        "{\"passed\": 6, \"failed\": 0, \"slowest_case\": \"multi_step_success\", "
        "\"recovered_cases\": \"2\", \"recovery_rate\": \"0.33\", "
        "\"category_counts\": {\"tool\": \"3\", \"recovery\": \"2\", \"failure\": \"1\"}}\n"
        "JSON\n"
    )
    fake_check.chmod(0o755)
    env = os.environ.copy()
    env["SELF_CORRECTING_CHECK_COMMAND"] = str(fake_check)
    env["SELF_CORRECTING_EVAL_FILE"] = str(eval_path)

    subprocess.run(
        [
            "scripts/continuous_iterate.sh",
            "1",
            "1",
            str(log_path),
            str(metrics_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    records = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]

    assert len(records) == 1
    assert records[0]["iteration"] == 1
    assert records[0]["checks_exit_code"] == 0
    assert records[0]["status"] == "passed"
    assert int(records[0]["duration_seconds"]) >= 0
    assert records[0]["evaluator_passed"] == 6
    assert records[0]["evaluator_failed"] == 0
    assert records[0]["evaluator_slowest_case"] == "multi_step_success"
    assert records[0]["evaluator_recovered_cases"] == "2"
    assert records[0]["evaluator_recovery_rate"] == "0.33"
    assert records[0]["evaluator_category_counts"] == {
        "failure": "1",
        "recovery": "2",
        "tool": "3",
    }


def test_continuous_iterate_uses_monotonic_clock_for_duration():
    script = Path("scripts/continuous_iterate.sh").read_text()

    assert "time.monotonic_ns()" in script
    assert "subprocess.run(command, shell=True" in script
    assert "max(0, (time.monotonic_ns() - started_nanos) // 1_000_000_000)" in script
    assert "$(((" not in script


def test_continuous_iterate_survives_malformed_evaluator_json(tmp_path):
    log_path = tmp_path / "continuous.log"
    metrics_path = tmp_path / "metrics.jsonl"
    eval_path = tmp_path / "eval.json"
    fake_check = tmp_path / "fake_check.sh"
    fake_check.write_text(
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "printf '{not-json}\\n' > \"$SELF_CORRECTING_EVAL_FILE\"\n"
        "exit 1\n"
    )
    fake_check.chmod(0o755)
    env = os.environ.copy()
    env["SELF_CORRECTING_CHECK_COMMAND"] = str(fake_check)
    env["SELF_CORRECTING_EVAL_FILE"] = str(eval_path)

    completed = subprocess.run(
        [
            "scripts/continuous_iterate.sh",
            "1",
            "1",
            str(log_path),
            str(metrics_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    records = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]

    assert completed.returncode == 0
    assert records[0]["status"] == "failed"
    assert records[0]["evaluator_passed"] is None
    assert records[0]["evaluator_failed"] is None
    assert records[0]["evaluator_slowest_case"] is None
    assert records[0]["evaluator_recovered_cases"] is None
    assert records[0]["evaluator_recovery_rate"] is None
    assert records[0]["evaluator_category_counts"] is None


def test_continuous_iterate_does_not_reuse_stale_evaluator_json(tmp_path):
    log_path = tmp_path / "continuous.log"
    metrics_path = tmp_path / "metrics.jsonl"
    eval_path = tmp_path / "eval.json"
    eval_path.write_text(json.dumps({"passed": 99, "failed": 0}) + "\n")
    fake_check = tmp_path / "fake_check.sh"
    fake_check.write_text("#!/usr/bin/env sh\nset -eu\nexit 1\n")
    fake_check.chmod(0o755)
    env = os.environ.copy()
    env["SELF_CORRECTING_CHECK_COMMAND"] = str(fake_check)
    env["SELF_CORRECTING_EVAL_FILE"] = str(eval_path)

    completed = subprocess.run(
        [
            "scripts/continuous_iterate.sh",
            "1",
            "1",
            str(log_path),
            str(metrics_path),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    records = [
        json.loads(line)
        for line in metrics_path.read_text().splitlines()
        if line.strip()
    ]

    assert completed.returncode == 0
    assert records[0]["status"] == "failed"
    assert records[0]["evaluator_passed"] is None
    assert records[0]["evaluator_failed"] is None


def test_run_checks_metrics_smoke_includes_slowest_case():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "evaluator_slowest_case" in run_checks
    assert "evaluator_recovered_cases" in run_checks
    assert "evaluator_recovery_rate" in run_checks
    assert "evaluator_category_counts" in run_checks
    assert "self_correcting_langgraph_agent.ops.metrics" in run_checks
    assert "--output /tmp/self-correcting-agent-metrics-summary-output.json" in run_checks
    assert "--require-recent-health healthy" in run_checks


def test_run_checks_smoke_exercises_cli_introspection():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "self-correcting-agent --version" in run_checks
    assert "self-correcting-agent-batch" in run_checks
    assert "self-correcting-agent-eval --list-cases" in run_checks
    assert "self-correcting-agent-metrics" in run_checks
    assert "self-correcting-agent-serve --help" in run_checks
    assert "--version" in run_checks
    assert "--plan" in run_checks
    assert "--session-memory /tmp/self-correcting-agent-session-memory.json" in run_checks
    assert "/tmp/self-correcting-agent-session-memory-smoke.json" in run_checks
    assert "unexpected session memory file mode" in run_checks


def test_run_checks_starts_real_service_smoke():
    run_checks = Path("scripts/run_checks.sh").read_text()
    smoke = Path("scripts/smoke_service.sh").read_text()

    assert "scripts/smoke_service.sh" in run_checks
    assert "self-correcting-agent-serve" in smoke
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in smoke
    assert "SELF_CORRECTING_SMOKE_AUTH_TOKEN" in smoke
    assert "Authorization" in smoke
    assert "duplicate_auth_response" in smoke
    assert "WWW-Authenticate" in smoke
    assert "Retry-After" in smoke
    assert "SelfCorrectingAgentHTTP/0.1" in smoke
    assert '"Python" not in response.headers["Server"]' in smoke
    assert "/health" in smoke
    assert "/ready" in smoke
    assert "/config" in smoke
    assert "/run" in smoke
    assert "/metrics" in smoke
    assert "/metrics.prom" in smoke
    assert "text/plain" in smoke
    assert "self_correcting_agent_requests_total" in smoke
    assert "requests_by_method" in smoke
    assert "self_correcting_agent_requests_by_method_total" in smoke
    assert "__unknown__" in smoke
    assert "service_version" in smoke
    assert "bind_host" in smoke
    assert "bind_port" in smoke
    assert "auth_required" in smoke
    assert "allow_full_trace_response" in smoke
    assert "protect_diagnostics" in smoke
    assert "self_correcting_agent_build_info" in smoke
    assert "security_response_headers" in smoke
    assert "content_security_policy_header" in smoke
    assert "x_frame_options_header" in smoke
    assert "max_concurrent_runs" in smoke
    assert "max_request_bytes" in smoke
    assert "self_correcting_agent_max_request_bytes" in smoke
    assert "idempotency_cache_size" in smoke
    assert "idempotency_cache_hits" in smoke
    assert "idempotency_cache_misses" in smoke
    assert "idempotency_cache_conflicts" in smoke
    assert "idempotency_cache_stores" in smoke
    assert "idempotency_cache_evictions" in smoke
    assert "Idempotency-Key" in smoke
    assert "incomplete_request_body" in smoke
    assert "duplicate_length_response" in smoke
    assert "invalid_content_length" in smoke
    assert "transfer_encoding_response" in smoke
    assert "invalid_transfer_encoding" in smoke
    assert "expect_response" in smoke
    assert "expectation_failed" in smoke
    assert "duplicate_content_type_response" in smoke
    assert "content-type must be single-valued application/json" in smoke
    assert "request_body_timeout" in smoke
    assert "invalid_idempotency_key" in smoke
    assert "single-valued" in smoke
    assert "idempotency_key_conflict" in smoke
    assert "max_goal_chars" in smoke
    assert "goal_too_large" in smoke
    assert "full_trace_disabled" in smoke
    assert "full_trace must be a boolean" in smoke
    assert "active_concurrent_runs" in smoke
    assert "active_rate_limit_windows" in smoke
    assert "rate_limit_per_minute" in smoke
    assert "trust_forwarded_for" in smoke
    assert "run_timeout_seconds" in smoke
    assert "request_timeout_seconds" in smoke
    assert "--request-timeout-seconds 1" in smoke
    assert "error_code" in smoke
    assert "invalid_agent_config" in smoke
    assert "max_steps" in smoke
    assert "2.5" in smoke
    assert "run_id" in smoke
    assert "X-Run-ID" in smoke
    assert "X-Trace-Path" in smoke
    assert "X-Request-ID" in smoke
    assert "X-Content-Type-Options" in smoke
    assert "Referrer-Policy" in smoke
    assert "trace_path" in smoke
    assert "idempotency_key_present" in smoke
    assert "request_body_bytes" in smoke
    assert "method_not_allowed" in smoke
    assert "error_responses_by_code" in smoke
    assert "self_correcting_agent_error_responses_total" in smoke
    assert "self_correcting_agent_request_duration_seconds_bucket" in smoke
    assert "self_correcting_agent_request_duration_seconds_count" in smoke
    assert "self_correcting_agent_request_duration_seconds_sum" in smoke
    assert "self_correcting_agent_agent_run_duration_seconds_bucket" in smoke
    assert "self_correcting_agent_agent_run_duration_seconds_count" in smoke
    assert "self_correcting_agent_agent_run_duration_seconds_sum" in smoke
    assert "--trace-dir" in smoke
    assert "trace_persistence" in smoke
    assert "average_duration_seconds" in smoke
    assert "max_duration_seconds" in smoke
    assert "agent_runs_total" in smoke
    assert "agent_runs_by_status" in smoke
    assert "average_agent_run_duration_seconds" in smoke
    assert "self_correcting_agent_runs_total" in smoke
    assert "self_correcting_agent_run_status_total" in smoke
    assert "self_correcting_agent_runtime_pending_approvals_current" in smoke
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in smoke
    assert "self_correcting_agent_runtime_max_pending_approval_age_seconds" in smoke
    assert "self_correcting_agent_runtime_pending_approval_stale_seconds" in smoke
    assert "uptime_seconds" in smoke
    assert "Cache-Control" in smoke
    assert "no-store" in smoke
    assert "no-referrer" in smoke
    assert '"503"' in smoke
    assert '"504"' in smoke
    assert "REQUEST_TIMEOUT_SECONDS = 15" in smoke
    assert "dump_service_logs" in smoke
    assert "$SERVICE_LOG.stdout" in smoke
    assert "$SERVICE_LOG.stderr" in smoke


def test_production_readiness_audit_reports_required_artifacts():
    script_path = Path("scripts/production_readiness_audit.py")
    makefile = Path("Makefile").read_text()
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()

    assert script_path.exists()
    assert os.access(script_path, os.X_OK)
    assert "readiness-audit:" in makefile
    assert "scripts/production_readiness_audit.py" in makefile
    assert "scripts/production_readiness_audit.py" in readme
    assert "scripts/production_readiness_audit.py" in rollout

    completed = subprocess.run(
        [".venv/bin/python", str(script_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["summary"]["required_artifacts_checked"] >= 10
    assert payload["summary"]["missing_artifacts"] == []
    assert payload["openapi_contract"]["status"] == "passed"
    assert payload["openapi_contract"]["openapi"] == "3.1.0"
    assert int(payload["openapi_contract"]["path_count"]) >= 10
    assert int(payload["openapi_contract"]["operation_id_count"]) >= 10
    assert len(payload["openapi_contract"]["sha256"]) == 64
    assert payload["openapi_contract"]["required_paths_present"] == "true"
    assert payload["configuration"]["env_example"]["status"] == "passed"
    assert payload["configuration"]["env_example"]["service_keys_present"] == "true"
    assert payload["configuration"]["env_example"]["runtime_keys_present"] == "true"
    assert payload["configuration"]["env_example"]["provider_keys_present"] == "true"
    assert len(payload["configuration"]["env_example"]["sha256"]) == 64
    assert payload["observability"]["grafana_dashboard"]["status"] == "passed"
    assert payload["observability"]["grafana_dashboard"]["title"] == (
        "Self-Correcting Agent Runtime"
    )
    assert int(payload["observability"]["grafana_dashboard"]["panel_count"]) >= 8
    assert payload["observability"]["grafana_dashboard"][
        "required_metrics_present"
    ] == "true"
    assert len(payload["observability"]["grafana_dashboard"]["sha256"]) == 64
    assert payload["observability"]["prometheus_alert_rules"]["status"] == "passed"
    assert int(payload["observability"]["prometheus_alert_rules"]["alert_count"]) >= 20
    assert payload["observability"]["prometheus_alert_rules"][
        "required_alerts_present"
    ] == "true"
    assert payload["observability"]["prometheus_alert_rules"][
        "required_metrics_present"
    ] == "true"
    assert len(payload["observability"]["prometheus_alert_rules"]["sha256"]) == 64
    assert payload["observability"]["prometheus_servicemonitor"]["status"] == "passed"
    assert payload["observability"]["prometheus_servicemonitor"][
        "scrape_target_present"
    ] == "true"
    assert payload["observability"]["prometheus_servicemonitor"][
        "selector_present"
    ] == "true"
    assert len(payload["observability"]["prometheus_servicemonitor"]["sha256"]) == 64
    assert payload["deployment"]["kubernetes_manifest"]["status"] == "passed"
    assert int(payload["deployment"]["kubernetes_manifest"]["resource_count"]) >= 8
    assert payload["deployment"]["kubernetes_manifest"][
        "required_resources_present"
    ] == "true"
    assert payload["deployment"]["kubernetes_manifest"]["hardening_present"] == "true"
    assert payload["deployment"]["kubernetes_manifest"]["rollout_controls_present"] == "true"
    assert len(payload["deployment"]["kubernetes_manifest"]["sha256"]) == 64
    assert payload["deployment"]["systemd_unit"]["status"] == "passed"
    assert payload["deployment"]["systemd_unit"]["service_controls_present"] == "true"
    assert payload["deployment"]["systemd_unit"]["sandboxing_present"] == "true"
    assert payload["deployment"]["systemd_unit"]["resource_controls_present"] == "true"
    assert payload["deployment"]["systemd_unit"]["trace_state_boundary_present"] == "true"
    assert len(payload["deployment"]["systemd_unit"]["sha256"]) == 64
    assert payload["integration"]["internal_runtime_client"]["status"] == "passed"
    assert payload["integration"]["internal_runtime_client"]["commands_present"] == "true"
    assert payload["integration"]["internal_runtime_client"]["auth_present"] == "true"
    assert payload["integration"]["internal_runtime_client"]["idempotency_present"] == "true"
    assert payload["integration"]["internal_runtime_client"]["runtime_routes_present"] == "true"
    assert (
        payload["integration"]["internal_runtime_client"][
            "effective_policy_filtering_present"
        ]
        == "true"
    )
    assert len(payload["integration"]["internal_runtime_client"]["sha256"]) == 64
    assert "scripts/run_checks.sh" in payload["artifacts"]
    assert "scripts/smoke_internal_runtime.sh" in payload["artifacts"]
    assert "scripts/smoke_real_llm_runtime.sh" in payload["artifacts"]
    assert "scripts/staging_acceptance.sh" in payload["artifacts"]
    assert "deploy/prometheus/self-correcting-agent-rules.yaml" in payload["artifacts"]
    assert "deploy/grafana/self-correcting-agent-dashboard.json" in payload["artifacts"]
    assert "examples/internal_runtime_client.py" in payload["artifacts"]
    assert payload["artifacts"]["scripts/run_checks.sh"]["exists"] is True
    assert payload["artifacts"]["deploy/grafana/self-correcting-agent-dashboard.json"][
        "exists"
    ] is True
    assert "sha256" in payload["artifacts"]["scripts/run_checks.sh"]
    assert payload["provider_smoke"]["status"] == "not_provided"
    assert payload["provider_smoke"]["required_for_provider_backed_production"] is True
    assert payload["staging_acceptance"]["status"] == "not_provided"
    assert payload["staging_acceptance"]["required_for_internal_production"] is True


def test_staging_acceptance_script_is_secret_safe_and_documented():
    script_path = Path("scripts/staging_acceptance.sh")
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()
    readiness = Path("docs/production-readiness.md").read_text()

    assert script_path.exists()
    assert os.access(script_path, os.X_OK)
    assert "scripts/staging_acceptance.sh" in readme
    assert "scripts/staging_acceptance.sh" in rollout
    assert "scripts/staging_acceptance.sh" in readiness

    script = script_path.read_text()
    assert "SELF_CORRECTING_STAGING_BASE_URL" in script
    assert "SELF_CORRECTING_STAGING_TOKEN" in script
    assert "Authorization" in script
    assert "Bearer" in script
    assert "/runtime/policy" in script
    assert "/runtime/run" in script
    assert "/runtime/runs/" in script
    assert "/metrics" in script
    assert "staging_token" not in script
    assert "sk-" not in script


def test_staging_acceptance_script_exercises_production_shaped_service(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            auth_token="admin-token-for-staging",
            auth_tokens={"team-a": "team-a-staging-token"},
            protect_diagnostics=True,
            trace_dir=str(tmp_path),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    env = os.environ.copy()
    env["SELF_CORRECTING_STAGING_BASE_URL"] = f"http://{host}:{port}"
    env["SELF_CORRECTING_STAGING_TOKEN"] = "team-a-staging-token"

    try:
        completed = subprocess.run(
            ["sh", "scripts/staging_acceptance.sh"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    payload = json.loads(completed.stdout)

    assert payload["evidence_schema_version"] == "1"
    assert payload["status"] == "passed"
    assert payload["health_status"] == "ok"
    assert payload["ready_status"] == "ready"
    assert payload["auth_subject"] == "team-a"
    assert payload["runtime_policy_source"] == "default"
    assert int(payload["runtime_effective_tool_policy_count"]) >= 1
    assert len(payload["runtime_effective_tool_policy_sha256"]) == 64
    assert payload["runtime_note_allowed"] == "true"
    assert payload["runtime_http_request_approval_required"] == "true"
    assert payload["runtime_run_status"] == "done"
    assert payload["runtime_summary_run_count"] == "1"
    assert payload["metrics_trace_persistence"] == "enabled"
    assert "team-a-staging-token" not in completed.stdout
    assert "team-a-staging-token" not in completed.stderr


def test_observability_acceptance_script_is_secret_safe_and_documented():
    script_path = Path("scripts/observability_acceptance.sh")
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()
    readiness = Path("docs/production-readiness.md").read_text()
    operations = Path("docs/operations.md").read_text()

    assert script_path.exists()
    assert os.access(script_path, os.X_OK)
    assert "scripts/observability_acceptance.sh" in readme
    assert "scripts/observability_acceptance.sh" in rollout
    assert "scripts/observability_acceptance.sh" in readiness
    assert "scripts/observability_acceptance.sh" in operations

    script = script_path.read_text()
    assert "SELF_CORRECTING_OBSERVABILITY_BASE_URL" in script
    assert "SELF_CORRECTING_OBSERVABILITY_TOKEN" in script
    assert "Authorization" in script
    assert "Bearer" in script
    assert "/metrics.prom" in script
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in script
    assert "deploy/grafana/self-correcting-agent-dashboard.json" in script
    assert "deploy/prometheus/self-correcting-agent-rules.yaml" in script
    assert "observability_token" not in script
    assert "sk-" not in script


def test_observability_acceptance_script_verifies_live_metrics(tmp_path):
    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            auth_token="admin-token-for-observability",
            auth_tokens={"sre": "sre-observability-token"},
            protect_diagnostics=True,
            trace_dir=str(tmp_path),
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    env = os.environ.copy()
    env["SELF_CORRECTING_OBSERVABILITY_BASE_URL"] = f"http://{host}:{port}"
    env["SELF_CORRECTING_OBSERVABILITY_TOKEN"] = "sre-observability-token"

    try:
        completed = subprocess.run(
            ["sh", "scripts/observability_acceptance.sh"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    payload = json.loads(completed.stdout)

    assert payload["evidence_schema_version"] == "1"
    assert payload["status"] == "passed"
    assert payload["metrics_endpoint"] == "/metrics.prom"
    assert payload["metrics_status"] == "200"
    assert payload["required_metrics_present"] == "true"
    assert int(payload["required_metric_count"]) >= 6
    assert payload["grafana_dashboard_status"] == "passed"
    assert payload["prometheus_rules_status"] == "passed"
    assert len(payload["metrics_sha256"]) == 64
    assert "sre-observability-token" not in completed.stdout
    assert "sre-observability-token" not in completed.stderr


def test_observability_acceptance_script_verifies_prometheus_query(tmp_path):
    class PrometheusHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if not self.path.startswith("/api/v1/query?"):
                self.send_response(404)
                self.end_headers()
                return
            payload = {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [
                        {
                            "metric": {"job": "self-correcting-agent"},
                            "value": [123, "1"],
                        }
                    ],
                },
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    service = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            auth_token="admin-token-for-observability",
            auth_tokens={"sre": "sre-observability-token"},
            protect_diagnostics=True,
            trace_dir=str(tmp_path),
        ),
    )
    prometheus = ThreadingHTTPServer(("127.0.0.1", 0), PrometheusHandler)
    service_thread = threading.Thread(target=service.serve_forever, daemon=True)
    prometheus_thread = threading.Thread(
        target=prometheus.serve_forever, daemon=True
    )
    service_thread.start()
    prometheus_thread.start()
    service_host, service_port = service.server_address
    prometheus_host, prometheus_port = prometheus.server_address
    env = os.environ.copy()
    env["SELF_CORRECTING_OBSERVABILITY_BASE_URL"] = (
        f"http://{service_host}:{service_port}"
    )
    env["SELF_CORRECTING_OBSERVABILITY_TOKEN"] = "sre-observability-token"
    env["SELF_CORRECTING_PROMETHEUS_BASE_URL"] = (
        f"http://{prometheus_host}:{prometheus_port}"
    )
    env["SELF_CORRECTING_PROMETHEUS_QUERY"] = "self_correcting_agent_build_info"

    try:
        completed = subprocess.run(
            ["sh", "scripts/observability_acceptance.sh"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        service.shutdown()
        service.server_close()
        prometheus.shutdown()
        prometheus.server_close()
        service_thread.join(timeout=5)
        prometheus_thread.join(timeout=5)

    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["prometheus_query_status"] == "passed"
    assert payload["prometheus_query"] == "self_correcting_agent_build_info"
    assert payload["prometheus_result_count"] == "1"
    assert "sre-observability-token" not in completed.stdout
    assert "sre-observability-token" not in completed.stderr


def test_internal_rollout_acceptance_script_is_secret_safe_and_documented():
    script_path = Path("scripts/internal_rollout_acceptance.py")
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()
    readiness = Path("docs/production-readiness.md").read_text()
    operations = Path("docs/operations.md").read_text()

    assert script_path.exists()
    assert os.access(script_path, os.X_OK)
    assert "scripts/internal_rollout_acceptance.py" in readme
    assert "scripts/internal_rollout_acceptance.py" in rollout
    assert "scripts/internal_rollout_acceptance.py" in readiness
    assert "scripts/internal_rollout_acceptance.py" in operations

    script = script_path.read_text()
    assert "tech_lead" in script
    assert "business_owner" in script
    assert "rollback_rehearsed" in script
    assert "staging_acceptance_attached" in script
    assert "runtime_effective_tool_policy_sha256" in script
    assert "Authorization" not in script
    assert "Bearer" not in script
    assert "sk-" not in script


def test_internal_rollout_acceptance_script_validates_redacted_signoff(tmp_path):
    signoff_path = tmp_path / "rollout-signoff.json"
    signoff_path.write_text(
        json.dumps(
            {
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.1.0",
                "environment": "internal-production",
                "signed_off_at_utc": "2026-06-28T12:00:00Z",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "approvers": [
                    {"role": "tech_lead", "name": "Tech Lead", "email": "tl@example.test"},
                    {"role": "sre", "name": "SRE", "email": "sre@example.test"},
                    {"role": "security", "name": "Security", "email": "sec@example.test"},
                    {
                        "role": "business_owner",
                        "name": "Business Owner",
                        "email": "owner@example.test",
                    },
                ],
                "checks": {
                    "provider_smoke_attached": True,
                    "staging_acceptance_attached": True,
                    "observability_acceptance_attached": True,
                    "tool_policy_reviewed": True,
                    "team_access_reviewed": True,
                    "trace_retention_reviewed": True,
                    "rollback_rehearsed": True,
                },
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/internal_rollout_acceptance.py",
            "--signoff",
            str(signoff_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["evidence_schema_version"] == "1"
    assert payload["status"] == "passed"
    assert payload["rollout_id"] == "rollout-2026-06-28"
    assert payload["release_version"] == "0.1.0"
    assert payload["environment"] == "internal-production"
    assert payload["required_roles_present"] == "true"
    assert payload["required_checks_passed"] == "true"
    assert payload["expected_release_version"] == "0.1.0"
    assert payload["version_matches"] == "true"
    assert payload["expected_environment"] == "internal-production"
    assert payload["environment_matches"] == "true"
    assert len(payload["runtime_effective_tool_policy_sha256"]) == 64
    assert payload["approver_role_count"] == "4"
    assert payload["approver_roles"] == [
        "business_owner",
        "security",
        "sre",
        "tech_lead",
    ]
    assert len(payload["sha256"]) == 64
    assert "tl@example.test" not in completed.stdout
    assert "owner@example.test" not in completed.stdout


def test_internal_rollout_acceptance_script_blocks_incomplete_signoff(tmp_path):
    signoff_path = tmp_path / "rollout-signoff.json"
    signoff_path.write_text(
        json.dumps(
            {
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.1.0",
                "environment": "internal-production",
                "signed_off_at_utc": "2026-06-28T12:00:00Z",
                "approvers": [{"role": "tech_lead", "email": "tl@example.test"}],
                "checks": {"rollback_rehearsed": False},
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/internal_rollout_acceptance.py",
            "--signoff",
            str(signoff_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert "sre" in payload["missing_required_roles"]
    assert "rollback_rehearsed" in payload["failed_required_checks"]
    assert "runtime_effective_tool_policy_sha256" in payload["missing_metadata"]
    assert "tl@example.test" not in completed.stdout


def test_internal_rollout_acceptance_script_blocks_stale_version_or_wrong_environment(
    tmp_path,
):
    signoff_path = tmp_path / "rollout-signoff.json"
    signoff_path.write_text(
        json.dumps(
            {
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.0.9",
                "environment": "qa",
                "signed_off_at_utc": "2026-06-28T12:00:00Z",
                "approvers": [
                    {"role": "tech_lead"},
                    {"role": "sre"},
                    {"role": "security"},
                    {"role": "business_owner"},
                ],
                "checks": {
                    "provider_smoke_attached": True,
                    "staging_acceptance_attached": True,
                    "observability_acceptance_attached": True,
                    "tool_policy_reviewed": True,
                    "team_access_reviewed": True,
                    "trace_retention_reviewed": True,
                    "rollback_rehearsed": True,
                },
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/internal_rollout_acceptance.py",
            "--signoff",
            str(signoff_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["expected_release_version"] == "0.1.0"
    assert payload["version_matches"] == "false"
    assert payload["expected_environment"] == "internal-production"
    assert payload["environment_matches"] == "false"
    assert "release_version" in payload["mismatched_metadata"]
    assert "environment" in payload["mismatched_metadata"]


def test_internal_rollout_acceptance_script_allows_explicit_expected_metadata(
    tmp_path,
):
    signoff_path = tmp_path / "rollout-signoff.json"
    signoff_path.write_text(
        json.dumps(
            {
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.1.0-rc.1",
                "environment": "staging",
                "signed_off_at_utc": "2026-06-28T12:00:00Z",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "approvers": [
                    {"role": "tech_lead"},
                    {"role": "sre"},
                    {"role": "security"},
                    {"role": "business_owner"},
                ],
                "checks": {
                    "provider_smoke_attached": True,
                    "staging_acceptance_attached": True,
                    "observability_acceptance_attached": True,
                    "tool_policy_reviewed": True,
                    "team_access_reviewed": True,
                    "trace_retention_reviewed": True,
                    "rollback_rehearsed": True,
                },
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/internal_rollout_acceptance.py",
            "--signoff",
            str(signoff_path),
            "--expected-version",
            "0.1.0-rc.1",
            "--expected-environment",
            "staging",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["expected_release_version"] == "0.1.0-rc.1"
    assert payload["version_matches"] == "true"
    assert payload["expected_environment"] == "staging"
    assert payload["environment_matches"] == "true"


def test_production_approval_bundle_script_is_secret_safe_and_documented():
    script_path = Path("scripts/production_approval_bundle.sh")
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()
    readiness = Path("docs/production-readiness.md").read_text()
    operations = Path("docs/operations.md").read_text()
    makefile = Path("Makefile").read_text()

    assert script_path.exists()
    assert os.access(script_path, os.X_OK)
    assert "scripts/production_approval_bundle.sh" in readme
    assert "scripts/production_approval_bundle.sh" in rollout
    assert "scripts/production_approval_bundle.sh" in readiness
    assert "scripts/production_approval_bundle.sh" in operations
    assert "production-approval-bundle:" in makefile

    script = script_path.read_text()
    assert "SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE" in script
    assert "SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE" in script
    assert "SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE" in script
    assert "SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE" in script
    assert "SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS" in script
    assert "evidence_missing" in script
    assert "evidence_stale" in script
    assert "evidence_max_age_invalid" in script
    assert "evidence_secret_detected" in script
    assert "release_manifest_missing" in script
    assert "--strict" in script
    assert "unknown_argument" in script
    assert "payload[\"status\"] != \"ready\"" in script
    assert "--require-provider-smoke" in script
    assert "--require-staging-acceptance" in script
    assert "--require-observability-acceptance" in script
    assert "--require-internal-rollout" in script
    assert "Authorization" not in script
    assert "Bearer" not in script
    assert "sk-" not in script


def test_production_approval_bundle_script_rejects_unknown_arguments():
    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strcit"],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stderr)

    assert completed.returncode == 2
    assert payload == {
        "error": "unknown_argument",
        "argument": "--strcit",
        "supported_arguments": ["--strict"],
    }


def test_production_approval_bundle_script_builds_strict_release_evidence(tmp_path):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "provider_snapshot": {
                    "llm_provider": "openai_compatible",
                    "llm_base_url_host": "api.example.test",
                    "llm_model": "agent-runtime-model",
                    "llm_api_key_configured": "true",
                },
                "capability_checks": {
                    "cli_runtime": "passed",
                    "http_runtime": "passed",
                    "trace_status": "passed",
                    "timeline": "passed",
                    "approval_resume": "passed",
                    "metrics": "passed",
                },
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "cli_run_id": "cli-run",
                "http_run_id": "http-run",
                "approval_run_id": "approval-run",
                "resumed_run_id": "resume-run",
            }
        )
        + "\n"
    )
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "base_url_host": "agent.internal",
                "health_status": "ok",
                "ready_status": "ready",
                "runtime_run_id": "staging-run",
                "auth_subject": "team-a",
                "runtime_policy_source": "default",
                "runtime_effective_tool_policy_count": "7",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "runtime_note_allowed": "true",
                "runtime_http_request_approval_required": "true",
                "runtime_run_status": "done",
                "runtime_timeline_event_count": "4",
                "runtime_summary_run_count": "1",
                "approval_queue_count": "0",
                "approval_summary_count": "0",
                "metrics_trace_persistence": "enabled",
                "metrics_runtime_runs_total": "1",
            }
        )
        + "\n"
    )
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "base_url_host": "agent.internal",
                "metrics_endpoint": "/metrics.prom",
                "metrics_status": "200",
                "required_metrics_present": "true",
                "required_metric_count": "8",
                "metrics_sha256": "a" * 64,
                "grafana_dashboard_status": "passed",
                "grafana_dashboard_sha256": "b" * 64,
                "prometheus_rules_status": "passed",
                "prometheus_rules_sha256": "c" * 64,
                "prometheus_query_status": "passed",
                "prometheus_result_count": "1",
            }
        )
        + "\n"
    )
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.1.0",
                "environment": "internal-production",
                "signed_off_at_utc": "2026-06-28T00:00:00+00:00",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "required_roles_present": "true",
                "required_checks_passed": "true",
                "approver_role_count": "4",
                "expected_release_version": "0.1.0",
                "version_matches": "true",
                "expected_environment": "internal-production",
                "environment_matches": "true",
                "sha256": "d" * 64,
            }
        )
        + "\n"
    )
    wheel = tmp_path / "self_correcting_langgraph_agent-0.1.0-py3-none-any.whl"
    wheel.write_text("wheel-bytes\n")
    manifest = tmp_path / "release-manifest.json"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            str(wheel),
            "--output",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    readiness_output = tmp_path / "readiness.json"
    evidence_output = tmp_path / "release-evidence.json"
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_RELEASE_MANIFEST"] = str(manifest)
    env["SELF_CORRECTING_RUN_CHECKS_EXIT_CODE"] = "0"
    env["SELF_CORRECTING_READINESS_AUDIT_OUTPUT"] = str(readiness_output)
    env["SELF_CORRECTING_RELEASE_EVIDENCE_OUTPUT"] = str(evidence_output)

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strict"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stdout)
    readiness = json.loads(readiness_output.read_text())
    evidence = json.loads(evidence_output.read_text())

    assert payload["status"] == "ready"
    assert payload["readiness_audit"] == str(readiness_output)
    assert payload["release_evidence"] == str(evidence_output)
    assert payload["evidence_max_age_seconds"] == "86400"
    assert payload["evidence_files"]["provider_smoke"]["path"] == str(provider_smoke)
    assert payload["evidence_files"]["provider_smoke"]["fresh"] == "true"
    assert int(payload["evidence_files"]["provider_smoke"]["age_seconds"]) >= 0
    assert len(payload["evidence_files"]["provider_smoke"]["sha256"]) == 64
    assert payload["evidence_files"]["staging_acceptance"]["path"] == str(
        staging_acceptance
    )
    assert payload["evidence_files"]["observability_acceptance"]["path"] == str(
        observability_acceptance
    )
    assert payload["evidence_files"]["internal_rollout"]["path"] == str(
        internal_rollout
    )
    assert readiness["status"] == "passed"
    assert evidence["status"] == "ready"
    assert evidence["provider_smoke"]["status"] == "passed"
    assert evidence["staging_acceptance"]["status"] == "passed"
    assert evidence["observability_acceptance"]["status"] == "passed"
    assert evidence["internal_rollout"]["status"] == "passed"


def test_production_approval_bundle_script_reports_all_missing_evidence(tmp_path):
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(
        tmp_path / "missing-provider-smoke.json"
    )
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(
        tmp_path / "missing-staging-acceptance.json"
    )
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        tmp_path / "missing-observability-acceptance.json"
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(
        tmp_path / "missing-internal-rollout.json"
    )

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh"],
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stderr)

    assert completed.returncode == 2
    assert payload == {
        "error": "evidence_missing",
        "missing": [
            {
                "label": "provider_smoke",
                "path": str(tmp_path / "missing-provider-smoke.json"),
            },
            {
                "label": "staging_acceptance",
                "path": str(tmp_path / "missing-staging-acceptance.json"),
            },
            {
                "label": "observability_acceptance",
                "path": str(tmp_path / "missing-observability-acceptance.json"),
            },
            {
                "label": "internal_rollout",
                "path": str(tmp_path / "missing-internal-rollout.json"),
            },
        ],
    }


def test_production_approval_bundle_script_blocks_stale_evidence(tmp_path):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(json.dumps({"status": "passed"}) + "\n")
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(json.dumps({"status": "passed"}) + "\n")
    old_timestamp = 1_000.0
    os.utime(provider_smoke, (old_timestamp, old_timestamp))
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS"] = "60"

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 1
    assert "evidence_stale" in completed.stderr
    assert "provider_smoke" in completed.stderr


def test_production_approval_bundle_script_rejects_invalid_evidence_max_age(
    tmp_path,
):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(json.dumps({"status": "passed"}) + "\n")
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(json.dumps({"status": "passed"}) + "\n")
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS"] = "tomorrow"

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strict"],
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stderr)

    assert completed.returncode == 2
    assert payload == {
        "error": "evidence_max_age_invalid",
        "environment_variable": "SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS",
        "reason": "must_be_integer",
        "value": "tomorrow",
    }
    assert completed.stdout == ""


def test_production_approval_bundle_script_rejects_non_positive_evidence_max_age(
    tmp_path,
):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(json.dumps({"status": "passed"}) + "\n")
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(json.dumps({"status": "passed"}) + "\n")
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS"] = "0"

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strict"],
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stderr)

    assert completed.returncode == 2
    assert payload == {
        "error": "evidence_max_age_invalid",
        "environment_variable": "SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS",
        "reason": "must_be_positive",
        "value": "0",
    }
    assert completed.stdout == ""


def test_production_approval_bundle_script_reports_missing_release_manifest(tmp_path):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(json.dumps({"status": "passed"}) + "\n")
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(json.dumps({"status": "passed"}) + "\n")
    missing_manifest = tmp_path / "missing-release-manifest.json"
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_RELEASE_MANIFEST"] = str(missing_manifest)

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strict"],
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stderr)

    assert completed.returncode == 2
    assert payload == {
        "error": "release_manifest_missing",
        "path": str(missing_manifest),
    }
    assert completed.stdout == ""


def test_production_approval_bundle_script_reports_blocked_release_evidence(
    tmp_path,
):
    provider_smoke = tmp_path / "provider-smoke.json"
    provider_smoke.write_text(json.dumps({"status": "passed"}) + "\n")
    staging_acceptance = tmp_path / "staging-acceptance.json"
    staging_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    observability_acceptance = tmp_path / "observability-acceptance.json"
    observability_acceptance.write_text(json.dumps({"status": "passed"}) + "\n")
    internal_rollout = tmp_path / "internal-rollout.json"
    internal_rollout.write_text(json.dumps({"status": "passed"}) + "\n")
    wheel = tmp_path / "self_correcting_langgraph_agent-0.1.0-py3-none-any.whl"
    wheel.write_text("wheel-bytes\n")
    manifest = tmp_path / "release-manifest.json"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            str(wheel),
            "--output",
            str(manifest),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    readiness_output = tmp_path / "readiness.json"
    evidence_output = tmp_path / "release-evidence.json"
    env = os.environ.copy()
    env["SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE"] = str(provider_smoke)
    env["SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE"] = str(staging_acceptance)
    env["SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE"] = str(
        observability_acceptance
    )
    env["SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE"] = str(internal_rollout)
    env["SELF_CORRECTING_RELEASE_MANIFEST"] = str(manifest)
    env["SELF_CORRECTING_READINESS_AUDIT_OUTPUT"] = str(readiness_output)
    env["SELF_CORRECTING_RELEASE_EVIDENCE_OUTPUT"] = str(evidence_output)

    completed = subprocess.run(
        ["sh", "scripts/production_approval_bundle.sh", "--strict"],
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(completed.stdout)
    release_evidence = json.loads(evidence_output.read_text())

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["release_evidence"] == str(evidence_output)
    assert "readiness_audit_failed" in payload["failed_checks"]
    assert "provider_smoke_invalid_evidence" in payload["failed_checks"]
    assert "staging_acceptance_invalid_evidence" in payload["failed_checks"]
    assert "observability_acceptance_invalid_evidence" in payload["failed_checks"]
    assert "internal_rollout_invalid_evidence" in payload["failed_checks"]
    assert release_evidence["status"] == "blocked"
    assert completed.stderr == ""


def test_production_readiness_audit_accepts_provider_smoke_evidence(tmp_path):
    evidence_path = tmp_path / "provider-smoke.json"
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "provider_snapshot": {
                    "llm_provider": "openai_compatible",
                    "llm_base_url_host": "api.example.test",
                    "llm_model": "agent-runtime-model",
                    "llm_api_key_configured": "true",
                },
                "capability_checks": {
                    "cli_runtime": "passed",
                    "http_runtime": "passed",
                    "trace_status": "passed",
                    "timeline": "passed",
                    "approval_resume": "passed",
                    "metrics": "passed",
                },
                "cli_run_id": "cli-run",
                "http_run_id": "http-run",
                "approval_run_id": "approval-run",
                "resumed_run_id": "resume-run",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "runtime_runs_total": "3",
                "runtime_approval_required_total": "1",
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--provider-smoke-evidence",
            str(evidence_path),
            "--require-provider-smoke",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["provider_smoke"]["status"] == "passed"
    assert payload["provider_smoke"]["evidence_path"] == str(evidence_path)
    assert payload["provider_smoke"]["evidence_schema_version"] == "1"
    assert payload["provider_smoke"]["provider_snapshot"] == {
        "llm_provider": "openai_compatible",
        "llm_base_url_host": "api.example.test",
        "llm_model": "agent-runtime-model",
        "llm_api_key_configured": "true",
    }
    assert payload["provider_smoke"]["capability_checks"] == {
        "approval_resume": "passed",
        "cli_runtime": "passed",
        "http_runtime": "passed",
        "metrics": "passed",
        "timeline": "passed",
        "trace_status": "passed",
    }
    assert len(payload["provider_smoke"]["runtime_effective_tool_policy_sha256"]) == 64
    assert "sha256" in payload["provider_smoke"]
    assert payload["provider_smoke"]["run_ids"] == {
        "approval_run_id": "approval-run",
        "cli_run_id": "cli-run",
        "http_run_id": "http-run",
        "resumed_run_id": "resume-run",
    }


def test_production_readiness_audit_blocks_secret_bearing_evidence(tmp_path):
    evidence_path = tmp_path / "provider-smoke.json"
    secret_value = "sk-" + "provider-smoke-secret"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "cli_run_id": "cli-run",
                "api_key": secret_value,
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--provider-smoke-evidence",
            str(evidence_path),
            "--require-provider-smoke",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert "evidence_secret_detected" in payload["summary"]["failed_checks"]
    assert payload["summary"]["evidence_secret_findings"] == [
        {
            "label": "provider_smoke",
            "path": "$.api_key",
            "reason": "secret_like_key",
        },
        {
            "label": "provider_smoke",
            "path": "$.api_key",
            "reason": "secret_like_value",
        },
    ]
    assert secret_value not in completed.stdout
    assert secret_value not in completed.stderr


def test_production_readiness_audit_rejects_incomplete_provider_smoke_evidence(
    tmp_path,
):
    evidence_path = tmp_path / "provider-smoke.json"
    evidence_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--provider-smoke-evidence",
            str(evidence_path),
            "--require-provider-smoke",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["provider_smoke"]["status"] == "invalid_evidence"
    assert "provider_smoke_invalid_evidence" in payload["summary"]["failed_checks"]
    assert payload["provider_smoke"]["missing_fields"] == [
        "approval_run_id",
        "capability_checks.approval_resume",
        "capability_checks.cli_runtime",
        "capability_checks.http_runtime",
        "capability_checks.metrics",
        "capability_checks.timeline",
        "capability_checks.trace_status",
        "cli_run_id",
        "evidence_schema_version",
        "http_run_id",
        "provider_snapshot.llm_api_key_configured",
        "provider_snapshot.llm_base_url_host",
        "provider_snapshot.llm_model",
        "provider_snapshot.llm_provider",
        "resumed_run_id",
        "runtime_effective_tool_policy_sha256",
    ]


def test_production_readiness_audit_accepts_staging_acceptance_evidence(tmp_path):
    evidence_path = tmp_path / "staging-acceptance.json"
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "base_url_host": "agent.internal",
                "health_status": "ok",
                "ready_status": "ready",
                "runtime_run_id": "staging-run",
                "auth_subject": "team-a",
                "runtime_policy_source": "default",
                "runtime_effective_tool_policy_count": "7",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "runtime_note_allowed": "true",
                "runtime_http_request_approval_required": "true",
                "runtime_run_status": "done",
                "runtime_timeline_event_count": "4",
                "runtime_summary_run_count": "1",
                "approval_queue_count": "0",
                "approval_summary_count": "0",
                "metrics_trace_persistence": "enabled",
                "metrics_runtime_runs_total": "1",
            }
        )
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--staging-acceptance-evidence",
            str(evidence_path),
            "--require-staging-acceptance",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["staging_acceptance"]["status"] == "passed"
    assert payload["staging_acceptance"]["evidence_schema_version"] == "1"
    assert payload["staging_acceptance"]["required_for_internal_production"] is True
    assert payload["staging_acceptance"]["runtime_run_id"] == "staging-run"
    assert payload["staging_acceptance"]["auth_subject"] == "team-a"
    assert payload["staging_acceptance"]["runtime_policy_source"] == "default"
    assert len(payload["staging_acceptance"]["runtime_effective_tool_policy_sha256"]) == 64
    assert payload["staging_acceptance"]["runtime_note_allowed"] == "true"
    assert (
        payload["staging_acceptance"]["runtime_http_request_approval_required"]
        == "true"
    )
    assert len(payload["staging_acceptance"]["sha256"]) == 64


def test_production_readiness_audit_can_require_staging_acceptance_evidence():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--require-staging-acceptance",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["staging_acceptance"]["status"] == "not_provided"
    assert "staging_acceptance_not_provided" in payload["summary"]["failed_checks"]


def test_production_readiness_audit_rejects_incomplete_staging_acceptance_evidence(
    tmp_path,
):
    evidence_path = tmp_path / "staging-acceptance.json"
    evidence_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--staging-acceptance-evidence",
            str(evidence_path),
            "--require-staging-acceptance",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["staging_acceptance"]["status"] == "invalid_evidence"
    assert "staging_acceptance_invalid_evidence" in payload["summary"]["failed_checks"]
    assert payload["staging_acceptance"]["missing_fields"] == [
        "auth_subject",
        "base_url_host",
        "evidence_schema_version",
        "health_status",
        "metrics_runtime_runs_total",
        "metrics_trace_persistence",
        "ready_status",
        "runtime_effective_tool_policy_count",
        "runtime_effective_tool_policy_sha256",
        "runtime_http_request_approval_required",
        "runtime_note_allowed",
        "runtime_policy_source",
        "runtime_run_id",
        "runtime_run_status",
        "runtime_summary_run_count",
        "runtime_timeline_event_count",
    ]


def test_production_readiness_audit_accepts_observability_acceptance_evidence(tmp_path):
    evidence_path = tmp_path / "observability-acceptance.json"
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "base_url_host": "agent.internal",
                "metrics_endpoint": "/metrics.prom",
                "metrics_status": "200",
                "required_metrics_present": "true",
                "required_metric_count": "8",
                "metrics_sha256": "a" * 64,
                "grafana_dashboard_status": "passed",
                "grafana_dashboard_sha256": "b" * 64,
                "prometheus_rules_status": "passed",
                "prometheus_rules_sha256": "c" * 64,
                "prometheus_query_status": "passed",
                "prometheus_result_count": "1",
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--observability-acceptance-evidence",
            str(evidence_path),
            "--require-observability-acceptance",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["observability_acceptance"]["status"] == "passed"
    assert payload["observability_acceptance"]["evidence_schema_version"] == "1"
    assert payload["observability_acceptance"][
        "required_for_internal_production"
    ] is True
    assert payload["observability_acceptance"]["metrics_endpoint"] == "/metrics.prom"
    assert payload["observability_acceptance"]["required_metrics_present"] == "true"
    assert payload["observability_acceptance"]["grafana_dashboard_status"] == "passed"
    assert payload["observability_acceptance"]["prometheus_rules_status"] == "passed"
    assert payload["observability_acceptance"]["prometheus_query_status"] == "passed"
    assert payload["observability_acceptance"]["prometheus_result_count"] == "1"
    assert len(payload["observability_acceptance"]["sha256"]) == 64


def test_production_readiness_audit_can_require_observability_acceptance_evidence():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--require-observability-acceptance",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["observability_acceptance"]["status"] == "not_provided"
    assert (
        "observability_acceptance_not_provided"
        in payload["summary"]["failed_checks"]
    )


def test_production_readiness_audit_rejects_incomplete_observability_evidence(
    tmp_path,
):
    evidence_path = tmp_path / "observability-acceptance.json"
    evidence_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--observability-acceptance-evidence",
            str(evidence_path),
            "--require-observability-acceptance",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["observability_acceptance"]["status"] == "invalid_evidence"
    assert (
        "observability_acceptance_invalid_evidence"
        in payload["summary"]["failed_checks"]
    )
    assert payload["observability_acceptance"]["missing_fields"] == [
        "base_url_host",
        "evidence_schema_version",
        "grafana_dashboard_sha256",
        "grafana_dashboard_status",
        "metrics_endpoint",
        "metrics_sha256",
        "metrics_status",
        "prometheus_query_status",
        "prometheus_rules_sha256",
        "prometheus_rules_status",
        "required_metric_count",
        "required_metrics_present",
    ]


def test_production_readiness_audit_accepts_internal_rollout_evidence(tmp_path):
    evidence_path = tmp_path / "internal-rollout.json"
    evidence_path.write_text(
        json.dumps(
            {
                "evidence_schema_version": "1",
                "status": "passed",
                "rollout_id": "rollout-2026-06-28",
                "release_version": "0.1.0",
                "environment": "internal-production",
                "signed_off_at_utc": "2026-06-28T00:00:00+00:00",
                "runtime_effective_tool_policy_sha256": "a" * 64,
                "required_roles_present": "true",
                "required_checks_passed": "true",
                "approver_role_count": "4",
                "expected_release_version": "0.1.0",
                "version_matches": "true",
                "expected_environment": "internal-production",
                "environment_matches": "true",
                "sha256": "d" * 64,
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--internal-rollout-evidence",
            str(evidence_path),
            "--require-internal-rollout",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["internal_rollout"]["status"] == "passed"
    assert payload["internal_rollout"]["evidence_schema_version"] == "1"
    assert payload["internal_rollout"]["required_for_internal_production"] is True
    assert payload["internal_rollout"]["rollout_id"] == "rollout-2026-06-28"
    assert payload["internal_rollout"]["required_roles_present"] == "true"
    assert payload["internal_rollout"]["required_checks_passed"] == "true"
    assert payload["internal_rollout"]["expected_release_version"] == "0.1.0"
    assert payload["internal_rollout"]["version_matches"] == "true"
    assert payload["internal_rollout"]["expected_environment"] == "internal-production"
    assert payload["internal_rollout"]["environment_matches"] == "true"
    assert len(payload["internal_rollout"]["runtime_effective_tool_policy_sha256"]) == 64
    assert len(payload["internal_rollout"]["sha256"]) == 64


def test_production_readiness_audit_can_require_internal_rollout_evidence():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--require-internal-rollout",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["internal_rollout"]["status"] == "not_provided"
    assert "internal_rollout_not_provided" in payload["summary"]["failed_checks"]


def test_production_readiness_audit_rejects_incomplete_internal_rollout_evidence(
    tmp_path,
):
    evidence_path = tmp_path / "internal-rollout.json"
    evidence_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--internal-rollout-evidence",
            str(evidence_path),
            "--require-internal-rollout",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["internal_rollout"]["status"] == "invalid_evidence"
    assert "internal_rollout_invalid_evidence" in payload["summary"]["failed_checks"]
    assert payload["internal_rollout"]["missing_fields"] == [
        "approver_role_count",
        "environment",
        "environment_matches",
        "evidence_schema_version",
        "expected_environment",
        "expected_release_version",
        "release_version",
        "required_checks_passed",
        "required_roles_present",
        "rollout_id",
        "runtime_effective_tool_policy_sha256",
        "sha256",
        "signed_off_at_utc",
        "version_matches",
    ]


def test_production_readiness_audit_can_require_provider_smoke_evidence():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "scripts/production_readiness_audit.py",
            "--require-provider-smoke",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "failed"
    assert payload["provider_smoke"]["status"] == "not_provided"
    assert "provider_smoke_not_provided" in payload["summary"]["failed_checks"]


def test_run_checks_starts_internal_runtime_smoke():
    run_checks = Path("scripts/run_checks.sh").read_text()
    smoke_path = Path("scripts/smoke_internal_runtime.sh")

    assert smoke_path.exists()
    smoke = smoke_path.read_text()
    assert "scripts/smoke_internal_runtime.sh" in run_checks
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in smoke
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS" in smoke
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in smoke
    assert "protect-diagnostics" in smoke
    assert "/runtime/run" in smoke
    assert "/runtime/resume" in smoke
    assert "/runtime/runs/{run_id}/cancel" in smoke
    assert "/runtime/approvals" in smoke
    assert "/runtime/approvals/summary" in smoke
    assert "/runtime/policy" in smoke
    assert "/runtime/runs" in smoke
    assert "/runtime/runs/summary" in smoke
    assert "metadata" in smoke
    assert "tags" in smoke
    assert "metadata_key=workflow" in smoke
    assert "tag=internal-smoke" in smoke
    assert "subject-scoped runtime trace reads" in smoke
    assert "subject-scoped runtime resume" in smoke
    assert "subject-scoped runtime cancel" in smoke
    assert "team_a_summary_run_count" in smoke
    assert "team_a_cancelled_summary_run_count" in smoke
    assert "team_a_tag_summary_run_count" in smoke
    assert "team_a_metadata_summary_run_count" in smoke
    assert "admin_pending_summary_run_count" in smoke
    assert "min_pending_age_seconds=0" in smoke
    assert "pending_age_seconds" in smoke
    assert "stale_pending_count" in smoke
    assert "max_pending_age_seconds" in smoke
    assert "runtime_pending_approvals_current" in smoke
    assert "runtime_stale_pending_approvals_current" in smoke
    assert "runtime_max_pending_approval_age_seconds" in smoke
    assert "runtime_pending_approval_stale_seconds" in smoke
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in smoke
    assert "runtime_owner_auth_subject" in smoke
    assert "resumed_by_auth_subject" in smoke
    assert "runtime_runs_by_auth_subject" in smoke
    assert "runtime_resumes_by_auth_subject" in smoke
    assert "team_a_policy_source" in smoke
    assert "sk-" not in smoke


def test_internal_runtime_smoke_script_exercises_internal_subjects():
    completed = subprocess.run(
        ["sh", "scripts/smoke_internal_runtime.sh"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["team_a_run_status"] == "done"
    assert payload["team_b_cross_subject_status"] == "404"
    assert payload["team_b_cross_subject_resume_status"] == "404"
    assert payload["team_b_cross_subject_cancel_status"] == "404"
    assert payload["admin_resume_status"] == "done"
    assert payload["team_a_cancel_status"] == "cancelled"
    assert payload["team_a_approval_queue_count"] == "1"
    assert payload["team_a_approval_summary_count"] == "1"
    assert payload["team_a_policy_source"] == "subject"
    assert payload["admin_policy_subject_count"] == "2"
    assert payload["team_a_summary_run_count"] == "2"
    assert payload["team_a_cancelled_summary_run_count"] == "1"
    assert payload["team_a_tag_summary_run_count"] == "1"
    assert payload["team_a_metadata_summary_run_count"] == "1"
    assert payload["admin_pending_summary_run_count"] == "1"
    assert payload["runtime_runs_by_auth_subject"]["team-a"] == "5"
    assert payload["runtime_runs_by_auth_subject_status"]["team-a:cancelled"] == "1"
    assert payload["runtime_resumes_by_auth_subject"]["default"] == "1"


def test_real_llm_runtime_smoke_is_opt_in_and_secret_safe():
    script_path = Path("scripts/smoke_real_llm_runtime.sh")

    assert script_path.exists()
    smoke = script_path.read_text()
    assert "SELF_CORRECTING_LLM_BASE_URL" in smoke
    assert "SELF_CORRECTING_LLM_API_KEY" in smoke
    assert "SELF_CORRECTING_LLM_MODEL" in smoke
    assert "SELF_CORRECTING_LLM_TIMEOUT_SECONDS" in smoke
    assert "self-correcting-agent" in smoke
    assert "--runtime" in smoke
    assert "/runtime/run" in smoke
    assert "/runtime/resume" in smoke
    assert "/runtime/runs/" in smoke
    assert "/runtime/policy" in smoke
    assert "/metrics" in smoke
    assert "requires_approval" in smoke
    assert "pending_approval" in smoke
    assert "runtime_runs_total" in smoke
    assert "runtime_approval_required_total" in smoke
    assert "runtime_effective_tool_policy_sha256" in smoke
    assert "effective_tool_policy_sha256" in smoke
    assert "trace_path" in smoke
    assert "evidence_schema_version" in smoke
    assert "provider_snapshot" in smoke
    assert "llm_base_url_host" in smoke
    assert "capability_checks" in smoke
    assert '"llm_base_url":' not in smoke
    assert "sk-" not in smoke
    assert "scripts/smoke_real_llm_runtime.sh" not in Path(
        "scripts/run_checks.sh"
    ).read_text()


def test_service_smoke_exercises_http_method_discovery():
    smoke = Path("scripts/smoke_service.sh").read_text()

    assert 'method="HEAD"' in smoke
    assert 'method="OPTIONS"' in smoke
    assert 'method="PUT"' in smoke
    assert "Allow" in smoke
    assert "GET, HEAD, OPTIONS, POST" in smoke
    assert '["/health"]["head"]["responses"]["200"]' in smoke
    assert '["/ready"]["head"]["responses"]["200"]' in smoke
    assert '["/ready"]["head"]["responses"]["503"]' in smoke
    assert "headReady" in smoke
    assert '["/metrics.prom"]["get"]["responses"]["200"]' in smoke
    assert '["/run"]["post"]["operationId"]' in smoke
    assert "postRun" in smoke


def test_run_checks_smoke_exercises_cli_output_file():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "--output" in run_checks


def test_run_checks_smoke_exercises_evaluator_category_filter():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "self_correcting_langgraph_agent.eval.evaluator --fail-on-failure" in run_checks
    assert "self_correcting_langgraph_agent.eval.evaluator --list-cases" in run_checks
    assert "self_correcting_langgraph_agent.eval.evaluator --category recovery" in run_checks
    assert (
        "self_correcting_langgraph_agent.eval.evaluator --case subtraction_tool_success"
        in run_checks
    )


def test_run_checks_includes_ruff_lint_gate():
    run_checks = Path("scripts/run_checks.sh").read_text()
    pyproject = Path("pyproject.toml").read_text()

    assert "-m ruff check" in run_checks
    assert "ruff" in pyproject


def test_run_checks_uses_isolated_pycache_for_compileall():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "PYTHONPYCACHEPREFIX=/tmp/self-correcting-agent-pycache" in run_checks
    assert "-m compileall -q src tests" in run_checks


def test_run_checks_builds_release_wheel():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "-m pip wheel" in run_checks
    assert "--no-deps" in run_checks
    assert "--no-build-isolation" in run_checks
    assert "/tmp/self-correcting-agent-wheelhouse" in run_checks
    assert "self_correcting_langgraph_agent-0.1.0-*.whl" in run_checks
    assert "self-correcting-agent-release-manifest" in run_checks
    assert "self-correcting-agent-release-evidence" in run_checks
    assert "/tmp/self-correcting-agent-release-manifest.json" in run_checks
    assert "--verify /tmp/self-correcting-agent-release-manifest.json" in run_checks
    assert "/tmp/self-correcting-agent-release-manifest-invalid.json" in run_checks
    assert "invalid release manifest JSON" in run_checks
    assert "release manifest unexpectedly emitted traceback for invalid JSON" in run_checks
    assert "/tmp/self-correcting-agent-release-manifest-missing-path.json" in run_checks
    assert "artifact path missing" in run_checks
    assert "/tmp/self-correcting-agent-release-manifest-invalid-path.json" in run_checks
    assert "artifact path invalid" in run_checks
    assert "/tmp/self-correcting-agent-release-manifest-directory-path.json" in run_checks
    assert "artifact is not a file" in run_checks
    assert '"sha256"' in run_checks


def test_run_checks_cleans_local_build_metadata_on_exit():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "cleanup_local_build_artifacts" in run_checks
    assert "trap cleanup_local_build_artifacts EXIT" in run_checks
    assert "rm -rf build dist *.egg-info src/*.egg-info" in run_checks


def test_run_checks_builds_isolated_release_wheel():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "/tmp/self-correcting-agent-isolated-wheelhouse" in run_checks
    assert "/tmp/self-correcting-agent-isolated-wheel-build.log" in run_checks


def test_run_checks_installs_built_wheel_in_clean_venv():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "/tmp/self-correcting-agent-wheel-install-venv" in run_checks
    assert "-m venv /tmp/self-correcting-agent-wheel-install-venv" in run_checks
    assert "-m pip install --no-deps /tmp/self-correcting-agent-wheelhouse/" in run_checks
    assert "importlib.metadata" in run_checks
    assert "self-correcting-agent-serve" in run_checks
    assert "self-correcting-agent-doctor" in run_checks
    assert "self-correcting-agent-trace-prune" in run_checks
    assert "self-correcting-agent-trace-replay" in run_checks
    assert '"self-correcting-agent-release-evidence",' in run_checks
    assert '"self-correcting-agent-release-manifest",' in run_checks


def test_run_checks_smokes_trace_prune_dry_run_and_delete():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "/tmp/self-correcting-agent-trace-prune-smoke" in run_checks
    assert "self-correcting-agent-trace-prune" in run_checks
    assert "/tmp/self-correcting-agent-trace-prune-dry-run.json" in run_checks
    assert "/tmp/self-correcting-agent-trace-prune-delete.json" in run_checks
    assert "/tmp/self-correcting-agent-runtime-trace-prune-dry-run.json" in run_checks
    assert "/tmp/self-correcting-agent-runtime-trace-prune-delete.json" in run_checks
    assert "--max-age-days 1" in run_checks
    assert "--runtime-only" in run_checks
    assert "--delete" in run_checks
    assert 'str(deleted["deleted"]) != "1"' in run_checks
    assert 'runtime_dry_run["protected_pending"] != 1' in run_checks
    assert 'runtime_deleted["matched_by_status"] != {"done": "1"}' in run_checks


def test_run_checks_smokes_trace_replay_redacted_summary():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "/tmp/self-correcting-agent-trace-replay.json" in run_checks
    assert "self-correcting-agent-trace-replay" in run_checks
    assert "/tmp/self-correcting-agent-trace-replay-summary.json" in run_checks
    assert '"tool_counts"] != {"apply_patch": "1", "read_file": "1"}' in run_checks
    assert 'summary["progress_event_count"] != "4"' in run_checks
    assert "trace replay leaked read_file content" in run_checks
    assert "trace replay leaked action input patch" in run_checks
    assert "trace replay leaked progress metadata" in run_checks


def test_run_checks_runs_doctor_self_check():
    run_checks = Path("scripts/run_checks.sh").read_text()

    assert "self-correcting-agent-doctor" in run_checks
    assert "/tmp/self-correcting-agent-doctor.json" in run_checks
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE=17" in run_checks
    assert '"idempotency_cache_size": "17"' in run_checks
    assert '"runtime_policy"' in run_checks
    assert '"effective_tool_policy_sha256"' in run_checks
    assert "--require-auth" in run_checks
    assert "/tmp/self-correcting-agent-doctor-require-auth.json" in run_checks
    assert "/tmp/self-correcting-agent-doctor-require-auth-unsafe-token.json" in run_checks
    assert "doctor --require-auth unexpectedly passed with unsafe auth token" in run_checks
    assert "/tmp/self-correcting-agent-doctor-require-auth-placeholder-token.json" in run_checks
    assert "doctor --require-auth unexpectedly passed with placeholder auth token" in run_checks
    assert "--production" in run_checks
    assert "/tmp/self-correcting-agent-doctor-production.json" in run_checks
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN=replace-with-a-long-random-token" in run_checks
    assert "/tmp/self-correcting-agent-doctor-placeholder-token-production.json" in run_checks
    assert "doctor --production unexpectedly passed with placeholder auth token" in run_checks
    assert "auth_token_unsafe" in run_checks
    assert "/tmp/self-correcting-agent-doctor-unsafe-token-production.json" in run_checks
    assert "doctor --production unexpectedly passed with unsafe auth token" in run_checks
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true" in run_checks
    assert "/tmp/self-correcting-agent-doctor-full-trace-production.json" in run_checks
    assert "doctor --production unexpectedly passed with full trace responses enabled" in run_checks
    assert "--require-runtime-provider" in run_checks
    assert "SELF_CORRECTING_LLM_BASE_URL=configured-provider-base" in run_checks
    assert "SELF_CORRECTING_LLM_MODEL=agent-runtime-model" in run_checks
    assert "/tmp/self-correcting-agent-doctor-runtime-provider.json" in run_checks
    assert "/tmp/self-correcting-agent-doctor-runtime-provider-missing.json" in run_checks
    assert "llm_base_url_required" in run_checks
    assert "llm_model_required" in run_checks
    assert "llm_api_key_required" in run_checks
    assert "runtime_iterations_too_low" in run_checks
    assert "SELF_CORRECTING_SERVICE_PORT=not-a-port" in run_checks
    assert "/tmp/self-correcting-agent-doctor-invalid-env.stderr" in run_checks
    assert "Traceback" in run_checks
    assert "doctor unexpectedly emitted traceback for invalid env config" in run_checks
    assert "/tmp/self-correcting-agent-serve-invalid-env.stderr" in run_checks
    assert "serve unexpectedly emitted traceback for invalid env config" in run_checks
