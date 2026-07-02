from __future__ import annotations

from typing import Dict

AGENT_RUN_FAILED = "agent_run_failed"
AGENT_RUN_TIMEOUT = "agent_run_timeout"
EXPECTATION_FAILED = "expectation_failed"
INVALID_AGENT_CONFIG = "invalid_agent_config"
INVALID_CONTENT_LENGTH = "invalid_content_length"
INVALID_TRANSFER_ENCODING = "invalid_transfer_encoding"
INCOMPLETE_REQUEST_BODY = "incomplete_request_body"
INVALID_JSON = "invalid_json"
INVALID_IDEMPOTENCY_KEY = "invalid_idempotency_key"
INVALID_REQUEST_BODY = "invalid_request_body"
FULL_TRACE_DISABLED = "full_trace_disabled"
GOAL_TOO_LARGE = "goal_too_large"
IDEMPOTENCY_KEY_CONFLICT = "idempotency_key_conflict"
METHOD_NOT_ALLOWED = "method_not_allowed"
MISSING_GOAL = "missing_goal"
NOT_FOUND = "not_found"
RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
READINESS_FAILED = "readiness_failed"
REQUEST_BODY_TIMEOUT = "request_body_timeout"
REQUEST_TOO_LARGE = "request_too_large"
TOO_MANY_CONCURRENT_RUNS = "too_many_concurrent_runs"
TRACE_PERSISTENCE_FAILED = "trace_persistence_failed"
TRACE_READ_FAILED = "trace_read_failed"
UNAUTHORIZED = "unauthorized"
UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"

ERROR_CODES = (
    AGENT_RUN_FAILED,
    AGENT_RUN_TIMEOUT,
    EXPECTATION_FAILED,
    INVALID_AGENT_CONFIG,
    INVALID_CONTENT_LENGTH,
    INVALID_TRANSFER_ENCODING,
    INCOMPLETE_REQUEST_BODY,
    INVALID_JSON,
    INVALID_IDEMPOTENCY_KEY,
    INVALID_REQUEST_BODY,
    FULL_TRACE_DISABLED,
    GOAL_TOO_LARGE,
    IDEMPOTENCY_KEY_CONFLICT,
    METHOD_NOT_ALLOWED,
    MISSING_GOAL,
    NOT_FOUND,
    RATE_LIMIT_EXCEEDED,
    READINESS_FAILED,
    REQUEST_BODY_TIMEOUT,
    REQUEST_TOO_LARGE,
    TOO_MANY_CONCURRENT_RUNS,
    TRACE_PERSISTENCE_FAILED,
    TRACE_READ_FAILED,
    UNAUTHORIZED,
    UNSUPPORTED_MEDIA_TYPE,
)


def failure_payload(error_code: str, message: str) -> Dict[str, str]:
    if error_code not in ERROR_CODES:
        raise ValueError(f"unknown service error code: {error_code}")
    return {
        "status": "failed",
        "error_code": error_code,
        "error": message,
    }
