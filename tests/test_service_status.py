import os
from pathlib import Path
from stat import S_IMODE

from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.service.status import (
    readiness_payload,
    service_config_snapshot,
)


def test_service_status_reports_readiness_and_redacted_config(tmp_path):
    trace_dir = tmp_path / "traces"
    config = ServiceConfig(
        host="0.0.0.0",
        port=9000,
        max_request_bytes=2048,
        max_goal_chars=123,
        auth_token="secret",
        rate_limit_per_minute=12,
        max_concurrent_runs=3,
        idempotency_cache_size=5,
        runtime_allowed_tools_by_subject={"team-a": ("note",)},
        runtime_max_iterations=9,
        runtime_pending_approval_stale_seconds=1800,
        allow_full_trace_response=True,
        protect_diagnostics=True,
        trust_forwarded_for=True,
        trace_dir=str(trace_dir),
        run_timeout_seconds=7.5,
        request_timeout_seconds=4.5,
    )

    readiness = readiness_payload(config)
    snapshot = service_config_snapshot(config)

    assert readiness["status"] == "ready"
    assert readiness["checks"]["trace_persistence"] == "ok"
    assert snapshot == {
        "host": "0.0.0.0",
        "port": "9000",
        "max_request_bytes": "2048",
        "max_goal_chars": "123",
        "auth_required": "true",
        "auth_subject_count": "1",
        "rate_limit_per_minute": "12",
        "max_concurrent_runs": "3",
        "idempotency_cache_size": "5",
        "idempotency_cache_backend": "memory",
        "idempotency_cache_path_configured": "false",
        "runtime_allowed_tools": "default",
        "runtime_allowed_tools_by_subject_count": "1",
        "runtime_max_iterations": "9",
        "runtime_pending_approval_stale_seconds": "1800",
        "allow_full_trace_response": "true",
        "protect_diagnostics": "true",
        "trust_forwarded_for": "true",
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
    assert "secret" not in str(snapshot)


def test_readiness_trace_probe_uses_owner_only_trace_directory_permissions(tmp_path):
    trace_dir = tmp_path / "traces"

    readiness = readiness_payload(ServiceConfig(trace_dir=str(trace_dir)))

    assert readiness["checks"]["trace_persistence"] == "ok"
    assert S_IMODE(trace_dir.stat().st_mode) == 0o700
    assert list(trace_dir.iterdir()) == []


def test_readiness_checks_sqlite_idempotency_cache_path(tmp_path):
    cache_path = tmp_path / "state" / "idempotency.sqlite3"

    readiness = readiness_payload(
        ServiceConfig(
            idempotency_cache_size=8,
            idempotency_cache_path=str(cache_path),
        )
    )

    assert readiness["status"] == "ready"
    assert readiness["checks"]["idempotency_cache_persistence"] == "ok"
    assert cache_path.exists()
    assert S_IMODE(cache_path.stat().st_mode) == 0o600


def test_readiness_fails_when_sqlite_idempotency_cache_path_is_unusable(tmp_path):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a directory", encoding="utf-8")

    readiness = readiness_payload(
        ServiceConfig(
            idempotency_cache_size=8,
            idempotency_cache_path=str(blocked_parent / "idempotency.sqlite3"),
        )
    )

    assert readiness["status"] == "not_ready"
    assert readiness["checks"]["idempotency_cache_persistence"] == (
        "failed: idempotency_cache_unavailable"
    )
    assert readiness["failed_checks"] == ["idempotency_cache_persistence"]
    assert readiness["error_code"] == "readiness_failed"


def test_readiness_trace_probe_tightens_existing_trace_directory_permissions(tmp_path):
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    trace_dir.chmod(0o755)

    readiness = readiness_payload(ServiceConfig(trace_dir=str(trace_dir)))

    assert readiness["checks"]["trace_persistence"] == "ok"
    assert S_IMODE(trace_dir.stat().st_mode) == 0o700


def test_readiness_trace_probe_uses_owner_only_probe_file_permissions(tmp_path, monkeypatch):
    trace_dir = tmp_path / "traces"
    observed_modes = []
    original_unlink = Path.unlink

    def recording_unlink(self, *args, **kwargs):
        if self.parent == trace_dir and self.name.startswith(".readiness-"):
            observed_modes.append(S_IMODE(self.stat().st_mode))
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", recording_unlink)
    previous_umask = os.umask(0o022)
    try:
        readiness = readiness_payload(ServiceConfig(trace_dir=str(trace_dir)))
    finally:
        os.umask(previous_umask)

    assert readiness["checks"]["trace_persistence"] == "ok"
    assert observed_modes == [0o600]
    assert list(trace_dir.iterdir()) == []
