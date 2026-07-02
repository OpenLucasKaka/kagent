import json
import subprocess


def test_release_evidence_cli_builds_verified_bundle(tmp_path):
    wheel = tmp_path / "self_correcting_langgraph_agent-0.1.0-py3-none-any.whl"
    wheel.write_text("wheel-bytes\n")
    manifest_path = tmp_path / "release-manifest.json"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            str(wheel),
            "--output",
            str(manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "summary": {"failed_checks": [], "missing_artifacts": []},
                "provider_smoke": {"status": "passed"},
            }
        )
        + "\n"
    )
    provider_smoke_path = tmp_path / "provider-smoke.json"
    provider_smoke_path.write_text(
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
            }
        )
        + "\n"
    )
    staging_acceptance_path = tmp_path / "staging-acceptance.json"
    staging_acceptance_path.write_text(
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
    observability_acceptance_path = tmp_path / "observability-acceptance.json"
    observability_acceptance_path.write_text(
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
    internal_rollout_path = tmp_path / "internal-rollout.json"
    internal_rollout_path.write_text(
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
    output_path = tmp_path / "release-evidence.json"

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--release-manifest",
            str(manifest_path),
            "--provider-smoke-evidence",
            str(provider_smoke_path),
            "--staging-acceptance-evidence",
            str(staging_acceptance_path),
            "--observability-acceptance-evidence",
            str(observability_acceptance_path),
            "--internal-rollout-evidence",
            str(internal_rollout_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    saved = json.loads(output_path.read_text())

    assert saved == payload
    assert payload["status"] == "ready"
    assert payload["run_checks"]["status"] == "passed"
    assert payload["readiness_audit"]["status"] == "passed"
    assert payload["release_manifest"]["status"] == "verified"
    assert payload["provider_smoke"]["status"] == "passed"
    assert payload["provider_smoke"]["run_ids"] == {
        "approval_run_id": "approval-run",
        "cli_run_id": "cli-run",
        "http_run_id": "http-run",
        "resumed_run_id": "resume-run",
    }
    assert payload["provider_smoke"]["evidence_schema_version"] == "1"
    assert (
        len(payload["provider_smoke"]["runtime_effective_tool_policy_sha256"])
        == 64
    )
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
    assert payload["staging_acceptance"] == {
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
        "metrics_trace_persistence": "enabled",
        "metrics_runtime_runs_total": "1",
        "missing_fields": [],
    }
    assert payload["observability_acceptance"] == {
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
        "missing_fields": [],
    }
    assert payload["internal_rollout"] == {
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
        "missing_fields": [],
    }
    assert payload["evidence_files"]["readiness_audit"]["sha256"]
    assert payload["evidence_files"]["release_manifest"]["sha256"]
    assert payload["evidence_files"]["provider_smoke"]["sha256"]
    assert payload["evidence_files"]["staging_acceptance"]["sha256"]
    assert payload["evidence_files"]["observability_acceptance"]["sha256"]
    assert payload["evidence_files"]["internal_rollout"]["sha256"]
    assert payload["generated_at_utc"].endswith("Z")


def test_release_evidence_cli_fails_when_required_gate_fails(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(json.dumps({"status": "failed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "1",
            "--readiness-audit",
            str(readiness_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["run_checks"]["status"] == "failed"
    assert payload["readiness_audit"]["status"] == "failed"
    assert "run_checks_failed" in payload["summary"]["failed_checks"]
    assert "readiness_audit_failed" in payload["summary"]["failed_checks"]


def test_release_evidence_cli_can_require_external_evidence(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--require-provider-smoke",
            "--require-staging-acceptance",
            "--require-observability-acceptance",
            "--require-internal-rollout",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["provider_smoke"]["status"] == "not_provided"
    assert payload["staging_acceptance"]["status"] == "not_provided"
    assert payload["observability_acceptance"]["status"] == "not_provided"
    assert payload["internal_rollout"]["status"] == "not_provided"
    assert "provider_smoke_not_provided" in payload["summary"]["failed_checks"]
    assert "staging_acceptance_not_provided" in payload["summary"]["failed_checks"]
    assert (
        "observability_acceptance_not_provided"
        in payload["summary"]["failed_checks"]
    )
    assert "internal_rollout_not_provided" in payload["summary"]["failed_checks"]


def test_release_evidence_cli_blocks_secret_bearing_external_evidence(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    provider_smoke_path = tmp_path / "provider-smoke.json"
    secret_value = "sk-" + "live-provider-token"
    provider_smoke_path.write_text(
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
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--provider-smoke-evidence",
            str(provider_smoke_path),
            "--require-provider-smoke",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
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


def test_release_evidence_cli_rejects_incomplete_provider_smoke_evidence(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    provider_smoke_path = tmp_path / "provider-smoke.json"
    provider_smoke_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--provider-smoke-evidence",
            str(provider_smoke_path),
            "--require-provider-smoke",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
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


def test_release_evidence_cli_rejects_incomplete_staging_acceptance_evidence(
    tmp_path,
):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    staging_acceptance_path = tmp_path / "staging-acceptance.json"
    staging_acceptance_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--staging-acceptance-evidence",
            str(staging_acceptance_path),
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


def test_release_evidence_cli_rejects_incomplete_observability_evidence(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    observability_acceptance_path = tmp_path / "observability-acceptance.json"
    observability_acceptance_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--observability-acceptance-evidence",
            str(observability_acceptance_path),
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


def test_release_evidence_cli_rejects_incomplete_internal_rollout_evidence(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    internal_rollout_path = tmp_path / "internal-rollout.json"
    internal_rollout_path.write_text(json.dumps({"status": "passed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--internal-rollout-evidence",
            str(internal_rollout_path),
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


def test_release_evidence_cli_blocks_failed_staging_acceptance(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    staging_acceptance_path = tmp_path / "staging-acceptance.json"
    staging_acceptance_path.write_text(json.dumps({"status": "failed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--staging-acceptance-evidence",
            str(staging_acceptance_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["staging_acceptance"]["status"] == "failed"
    assert "staging_acceptance_failed" in payload["summary"]["failed_checks"]


def test_release_evidence_cli_blocks_failed_observability_acceptance(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    observability_acceptance_path = tmp_path / "observability-acceptance.json"
    observability_acceptance_path.write_text(json.dumps({"status": "failed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--observability-acceptance-evidence",
            str(observability_acceptance_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["observability_acceptance"]["status"] == "failed"
    assert "observability_acceptance_failed" in payload["summary"]["failed_checks"]


def test_release_evidence_cli_blocks_failed_internal_rollout(tmp_path):
    readiness_path = tmp_path / "readiness-audit.json"
    readiness_path.write_text(
        json.dumps({"status": "passed", "summary": {"failed_checks": []}}) + "\n"
    )
    internal_rollout_path = tmp_path / "internal-rollout.json"
    internal_rollout_path.write_text(json.dumps({"status": "failed"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_evidence",
            "--run-checks-exit-code",
            "0",
            "--readiness-audit",
            str(readiness_path),
            "--internal-rollout-evidence",
            str(internal_rollout_path),
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "blocked"
    assert payload["internal_rollout"]["status"] == "failed"
    assert "internal_rollout_failed" in payload["summary"]["failed_checks"]
