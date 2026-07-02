from pathlib import Path


def test_security_policy_documents_reporting_and_runtime_controls():
    security = Path("SECURITY.md").read_text()

    assert "Supported Versions" in security
    assert "Reporting a Vulnerability" in security
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in security
    assert "at least 16 characters" in security
    assert "auth_token_placeholder" in security
    assert "auth_token_unsafe" in security
    assert "replace-with-a-long-random-token" in security
    assert "WWW-Authenticate" in security
    assert "--require-auth" in security
    assert "`--require-auth` rejects placeholder tokens" in security
    assert "constant-time" in security
    assert "non-ASCII `Authorization`" in security
    assert "single-valued `Authorization`" in security
    assert "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE" in security
    assert "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR" in security
    assert "unsafe `X-Forwarded-For`" in security
    assert "non-IP" in security
    assert "canonical" in security
    assert "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS" in security
    assert "SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES" in security
    assert "Duplicate" in security
    assert "Content-Length" in security
    assert "Transfer-Encoding" in security
    assert "invalid_transfer_encoding" in security
    assert "Expect" in security
    assert "expectation_failed" in security
    assert "Content-Type" in security
    assert "single-valued `application/json`" in security
    assert "Idempotency-Key" in security
    assert "single-valued" in security
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS" in security
    assert "request_body_timeout" in security
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE" in security
    assert "full_trace_response_must_be_disabled" in security
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS" in security
    assert "full_trace_disabled" in security
    assert "X-Content-Type-Options" in security
    assert "Cache-Control" in security
    assert "no-store" in security
    assert "Referrer-Policy" in security
    assert "no-referrer" in security
    assert "Content-Security-Policy" in security
    assert "default-src 'none'" in security
    assert "X-Frame-Options" in security
    assert "DENY" in security
    assert "Server" in security
    assert "Python runtime" in security
    assert "X-Request-ID" in security
    assert "128" in security
    assert "UMask=0077" in security
    assert "0700" in security
    assert "0600" in security
    assert "trace" in security
    assert "same `auth_subject`" in security
    assert "subject-scoped runtime resume" in security
    assert "resumed_by_auth_subject" in security
    assert "operator/admin diagnostic token" in security
    assert "idempotency_cache_persistence" in security
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in security
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in security
    assert "path traversal" in security
