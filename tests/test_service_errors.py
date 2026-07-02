from self_correcting_langgraph_agent.service.errors import (
    ERROR_CODES,
    failure_payload,
)


def test_service_error_catalog_lists_stable_error_codes():
    assert ERROR_CODES == (
        "agent_run_failed",
        "agent_run_timeout",
        "expectation_failed",
        "invalid_agent_config",
        "invalid_content_length",
        "invalid_transfer_encoding",
        "incomplete_request_body",
        "invalid_json",
        "invalid_idempotency_key",
        "invalid_request_body",
        "full_trace_disabled",
        "goal_too_large",
        "idempotency_key_conflict",
        "method_not_allowed",
        "missing_goal",
        "not_found",
        "rate_limit_exceeded",
        "readiness_failed",
        "request_body_timeout",
        "request_too_large",
        "too_many_concurrent_runs",
        "trace_persistence_failed",
        "trace_read_failed",
        "unauthorized",
        "unsupported_media_type",
    )


def test_failure_payload_rejects_unknown_error_codes():
    try:
        failure_payload("not_registered", "boom")
    except ValueError as exc:
        assert str(exc) == "unknown service error code: not_registered"
    else:
        raise AssertionError("unknown error code was accepted")
