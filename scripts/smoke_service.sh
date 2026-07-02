#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
SERVICE_BIN="${SERVICE_BIN:-.venv/bin/self-correcting-agent-serve}"
PORT="$("$PYTHON_BIN" - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"

SERVICE_LOG="${SERVICE_LOG:-/tmp/self-correcting-agent-service-smoke.log}"
AUTH_TOKEN="${SELF_CORRECTING_SMOKE_AUTH_TOKEN:-smoke-token}"
TRACE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/self-correcting-agent-traces.XXXXXX")"
SELF_CORRECTING_SERVICE_AUTH_TOKEN="$AUTH_TOKEN" \
    "$SERVICE_BIN" --host 127.0.0.1 --port "$PORT" --trace-dir "$TRACE_DIR" \
    --max-request-bytes 2048 --max-goal-chars 64 --idempotency-cache-size 8 \
    --protect-diagnostics --trust-forwarded-for \
    --request-timeout-seconds 1 \
    >"$SERVICE_LOG.stdout" 2>"$SERVICE_LOG.stderr" &
server_pid="$!"

dump_service_logs() {
    echo "service smoke failed for pid ${server_pid} on port ${PORT}" >&2
    if kill -0 "$server_pid" 2>/dev/null; then
        echo "service process is still running" >&2
    else
        echo "service process is not running" >&2
    fi
    echo "service stdout ($SERVICE_LOG.stdout):" >&2
    sed -n '1,160p' "$SERVICE_LOG.stdout" >&2 || true
    echo "service stderr ($SERVICE_LOG.stderr):" >&2
    sed -n '1,220p' "$SERVICE_LOG.stderr" >&2 || true
}

cleanup() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    rm -rf "$TRACE_DIR"
}
trap cleanup EXIT INT TERM

if ! "$PYTHON_BIN" - "$PORT" "$SERVICE_LOG.stderr" "$AUTH_TOKEN" <<'PY'
import json
import socket
import sys
import time
import urllib.error
import urllib.request

port = sys.argv[1]
service_stderr_path = sys.argv[2]
auth_token = sys.argv[3]
base_url = f"http://127.0.0.1:{port}"
REQUEST_TIMEOUT_SECONDS = 15


def get_json(path):
    with urllib.request.urlopen(f"{base_url}{path}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json_auth(path):
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {auth_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(path):
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {auth_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8"), response.headers["Content-Type"]


def post_json(path, payload, extra_headers=None):
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


deadline = time.time() + 10
while True:
    try:
        assert get_json("/health") == {"status": "ok"}
        break
    except Exception:
        if time.time() >= deadline:
            raise
        time.sleep(0.2)

assert get_json("/version")["version"]
ready = get_json("/ready")
assert ready["status"] == "ready"
assert ready["checks"]["trace_persistence"] == "ok"
diagnostic_probe = urllib.request.Request(f"{base_url}/metrics", method="GET")
try:
    urllib.request.urlopen(diagnostic_probe, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 401
    assert exc.headers["WWW-Authenticate"] == "Bearer"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "unauthorized",
        "error": "unauthorized",
    }
else:
    raise AssertionError("unauthorized diagnostic probe unexpectedly succeeded")
config = get_json_auth("/config")
assert config["auth_required"] == "true"
assert config["allow_full_trace_response"] == "false"
assert config["protect_diagnostics"] == "true"
assert int(config["max_concurrent_runs"]) >= 0
assert int(config["idempotency_cache_size"]) == 8
assert int(config["max_request_bytes"]) == 2048
assert int(config["max_goal_chars"]) == 64
assert config["trust_forwarded_for"] == "true"
assert float(config["run_timeout_seconds"]) > 0
assert float(config["request_timeout_seconds"]) > 0
assert config["trace_persistence"] == "enabled"
openapi_payload = get_json_auth("/openapi.json")
openapi_paths = openapi_payload["paths"]
assert openapi_paths["/health"]["head"]["summary"]
assert openapi_paths["/ready"]["head"]["summary"]
assert openapi_paths["/run"]["options"]["summary"]
assert openapi_paths["/health"]["head"]["operationId"] == "headHealth"
assert openapi_paths["/ready"]["head"]["operationId"] == "headReady"
assert openapi_paths["/run"]["post"]["operationId"] == "postRun"
assert openapi_paths["/metrics.prom"]["get"]["operationId"] == "getPrometheusMetrics"
health_headers = openapi_paths["/health"]["get"]["responses"]["200"]["headers"]
head_health = openapi_paths["/health"]["head"]["responses"]["200"]
head_ready = openapi_paths["/ready"]["head"]["responses"]
assert "X-Request-ID" in health_headers
assert health_headers["Cache-Control"]["schema"]["const"] == "no-store"
assert health_headers["X-Content-Type-Options"]["schema"]["const"] == "nosniff"
assert health_headers["Referrer-Policy"]["schema"]["const"] == "no-referrer"
assert "X-Request-ID" in head_health["headers"]
assert head_health["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
assert head_health["headers"]["Referrer-Policy"]["schema"]["const"] == "no-referrer"
assert openapi_paths["/ready"]["head"]["responses"]["200"]["description"] == "Service is ready"
assert openapi_paths["/ready"]["head"]["responses"]["503"]["description"] == "Service is not ready"
assert head_ready["200"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
assert head_ready["503"]["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
assert head_ready["200"]["headers"]["Referrer-Policy"]["schema"]["const"] == "no-referrer"
assert head_ready["503"]["headers"]["Referrer-Policy"]["schema"]["const"] == "no-referrer"
run_contract = openapi_paths["/run"]["post"]
options_contract = openapi_paths["/run"]["options"]
assert "503" in run_contract["responses"]
assert "504" in run_contract["responses"]
assert "403" in run_contract["responses"]
assert "409" in run_contract["responses"]
assert "X-Request-ID" in run_contract["responses"]["200"]["headers"]
assert "X-Run-ID" in run_contract["responses"]["200"]["headers"]
assert "X-Trace-Path" in run_contract["responses"]["200"]["headers"]
assert "Cache-Control" in run_contract["responses"]["400"]["headers"]
assert run_contract["responses"]["400"]["headers"]["Referrer-Policy"]["schema"]["const"] == "no-referrer"
assert run_contract["responses"]["401"]["headers"]["WWW-Authenticate"]["schema"]["const"] == "Bearer"
assert run_contract["responses"]["408"]["headers"]["Retry-After"]["schema"]["const"] == "1"
assert run_contract["responses"]["429"]["headers"]["Retry-After"]["schema"]["pattern"] == r"^[1-9]\d*$"
assert run_contract["responses"]["503"]["headers"]["Retry-After"]["schema"]["const"] == "1"
assert run_contract["requestBody"]["content"]["application/json"]["schema"]["$ref"]
assert run_contract["parameters"][0]["name"] == "Idempotency-Key"
run_request_schema = openapi_payload["components"]["schemas"]["RunRequest"]
assert "disabled by default" in run_request_schema["properties"]["full_trace"]["description"]
assert options_contract["responses"]["204"]["headers"]["Allow"]["schema"]["const"] == (
    "GET, HEAD, OPTIONS, POST"
)
assert openapi_paths["/metrics.prom"]["get"]["responses"]["200"]["content"]["text/plain"]
head_request = urllib.request.Request(f"{base_url}/health", method="HEAD")
with urllib.request.urlopen(head_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
    assert response.status == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Server"] == "SelfCorrectingAgentHTTP/0.1"
    assert "Python" not in response.headers["Server"]
    assert response.read() == b""
head_ready_request = urllib.request.Request(f"{base_url}/ready", method="HEAD")
with urllib.request.urlopen(head_ready_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
    assert response.status == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.read() == b""
options_request = urllib.request.Request(f"{base_url}/run", method="OPTIONS")
with urllib.request.urlopen(options_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
    assert response.status == 204
    assert response.headers["Allow"] == "GET, HEAD, OPTIONS, POST"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.read() == b""
put_request = urllib.request.Request(
    f"{base_url}/run",
    data=b"{}",
    headers={"Content-Type": "application/json"},
    method="PUT",
)
try:
    urllib.request.urlopen(put_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 405
    assert exc.headers["Allow"] == "GET, HEAD, OPTIONS, POST"
    assert exc.headers["Cache-Control"] == "no-store"
    assert exc.headers["Referrer-Policy"] == "no-referrer"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "method_not_allowed",
        "error": "method not allowed",
    }
else:
    raise AssertionError("PUT /run unexpectedly succeeded")
unknown_request = urllib.request.Request(f"{base_url}/missing-random-smoke")
try:
    urllib.request.urlopen(unknown_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 404
    assert exc.headers["Cache-Control"] == "no-store"
    assert exc.headers["Referrer-Policy"] == "no-referrer"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "not_found",
        "error": "not found",
    }
else:
    raise AssertionError("unknown route unexpectedly succeeded")
auth_probe_url = f"{base_url}/run"
auth_probe_request = urllib.request.Request(
    auth_probe_url,
    data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
auth_probe_opener = urllib.request.build_opener()
auth_probe_opener.addheaders = [("Authorization", "Bearer wrong-token")]
try:
    auth_probe_opener.open(auth_probe_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    if exc.code != 401:
        raise
    assert exc.headers["WWW-Authenticate"] == "Bearer"
else:
    raise AssertionError("unauthorized /run probe unexpectedly succeeded")
duplicate_auth_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as sock:
    sock.sendall(
        b"POST /run HTTP/1.1\r\n"
        + f"Host: 127.0.0.1:{port}\r\n".encode("ascii")
        + b"Authorization: Bearer wrong-token\r\n"
        + b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(duplicate_auth_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + duplicate_auth_body
    )
    duplicate_auth_response = sock.recv(4096)
assert duplicate_auth_response.startswith(b"HTTP/1.0 401"), duplicate_auth_response
assert b"WWW-Authenticate: Bearer" in duplicate_auth_response
non_ascii_auth_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as sock:
    sock.sendall(
        b"POST /run HTTP/1.1\r\n"
        + f"Host: 127.0.0.1:{port}\r\n".encode("ascii")
        + b"Authorization: Bearer s\xe9cret\r\n"
        + b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(non_ascii_auth_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + non_ascii_auth_body
    )
    non_ascii_auth_response = sock.recv(4096)
assert non_ascii_auth_response.startswith(b"HTTP/1.0 401"), non_ascii_auth_response
invalid_config_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "calculate 2 + 3", "max_steps": 2.5}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    urllib.request.urlopen(invalid_config_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 400
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_agent_config",
        "error": "max_steps must be an integer",
    }
else:
    raise AssertionError("invalid /run config unexpectedly succeeded")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
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
duplicate_length_response = b"".join(chunks)
duplicate_length_status = duplicate_length_response.split(b"\r\n", 1)[0]
duplicate_length_body = duplicate_length_response.split(b"\r\n\r\n", 1)[1]
assert b" 400 " in duplicate_length_status
assert json.loads(duplicate_length_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "invalid_content_length",
    "error": "invalid content-length",
}
transfer_encoding_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Transfer-Encoding: chunked\r\n"
        + f"Content-Length: {len(transfer_encoding_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n"
        b"\r\n"
        + transfer_encoding_body
    )
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
transfer_encoding_response = b"".join(chunks)
transfer_encoding_status = transfer_encoding_response.split(b"\r\n", 1)[0]
transfer_encoding_body = transfer_encoding_response.split(b"\r\n\r\n", 1)[1]
assert b" 400 " in transfer_encoding_status
assert json.loads(transfer_encoding_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "invalid_transfer_encoding",
    "error": "transfer-encoding is unsupported",
}
expect_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Expect: 100-continue\r\n"
        + f"Content-Length: {len(expect_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n"
        b"\r\n"
        + expect_body
    )
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
expect_response = b"".join(chunks)
expect_status = expect_response.split(b"\r\n", 1)[0]
expect_body = expect_response.split(b"\r\n\r\n", 1)[1]
assert b" 417 " in expect_status
assert json.loads(expect_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "expectation_failed",
    "error": "expect header is unsupported",
}
duplicate_content_type_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(duplicate_content_type_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n"
        b"\r\n"
        + duplicate_content_type_body
    )
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
duplicate_content_type_response = b"".join(chunks)
duplicate_content_type_status = duplicate_content_type_response.split(b"\r\n", 1)[0]
duplicate_content_type_body = duplicate_content_type_response.split(b"\r\n\r\n", 1)[1]
assert b" 415 " in duplicate_content_type_status
assert json.loads(duplicate_content_type_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "unsupported_media_type",
    "error": "content-type must be single-valued application/json",
}
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
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
incomplete_response = b"".join(chunks)
incomplete_status = incomplete_response.split(b"\r\n", 1)[0]
incomplete_body = incomplete_response.split(b"\r\n\r\n", 1)[1]
assert b" 400 " in incomplete_status
assert json.loads(incomplete_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "incomplete_request_body",
    "error": "request body ended before content-length bytes were read",
}
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.settimeout(REQUEST_TIMEOUT_SECONDS)
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 32\r\n"
        b"Connection: close\r\n"
        b"\r\n"
        b'{"goal": "calculate'
    )
    timeout_chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        timeout_chunks.append(chunk)
timeout_response = b"".join(timeout_chunks)
timeout_headers, timeout_body = timeout_response.split(b"\r\n\r\n", 1)
timeout_status = timeout_headers.split(b"\r\n", 1)[0]
assert b" 408 " in timeout_status
assert b"Retry-After: 1" in timeout_headers
assert json.loads(timeout_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "request_body_timeout",
    "error": "timed out while reading request body",
    "retry_after_seconds": "1",
}
oversized_goal_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "x" * 65}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    urllib.request.urlopen(oversized_goal_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 413
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "goal_too_large",
        "error": "goal exceeds max_goal_chars",
    }
else:
    raise AssertionError("oversized /run goal unexpectedly succeeded")
invalid_full_trace_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "calculate 2 + 3", "full_trace": "true"}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    urllib.request.urlopen(invalid_full_trace_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 400
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_request_body",
        "error": "full_trace must be a boolean",
    }
else:
    raise AssertionError("invalid full_trace /run probe unexpectedly succeeded")
full_trace_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "calculate 2 + 3", "full_trace": True}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    urllib.request.urlopen(full_trace_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 403
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "full_trace_disabled",
        "error": "full_trace responses are disabled",
    }
else:
    raise AssertionError("full_trace /run probe unexpectedly succeeded")
invalid_idempotency_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Idempotency-Key": "x" * 129,
    },
    method="POST",
)
try:
    urllib.request.urlopen(invalid_idempotency_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 400
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "invalid_idempotency_key",
        "error": "idempotency key must be 1-128 printable ASCII characters",
    }
else:
    raise AssertionError("invalid idempotency key unexpectedly succeeded")
duplicate_idempotency_body = json.dumps({"goal": "calculate 2 + 3"}).encode("utf-8")
with socket.create_connection(("127.0.0.1", int(port)), timeout=REQUEST_TIMEOUT_SECONDS) as client:
    client.sendall(
        b"POST /run HTTP/1.1\r\n"
        + f"Host: 127.0.0.1:{port}\r\n".encode("ascii")
        + b"Authorization: Bearer "
        + auth_token.encode("ascii")
        + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Idempotency-Key: smoke-duplicate-a\r\n"
        b"Idempotency-Key: smoke-duplicate-b\r\n"
        + f"Content-Length: {len(duplicate_idempotency_body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + duplicate_idempotency_body
    )
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
duplicate_idempotency_response = b"".join(chunks)
duplicate_idempotency_status = duplicate_idempotency_response.split(b"\r\n", 1)[0]
duplicate_idempotency_body = duplicate_idempotency_response.split(b"\r\n\r\n", 1)[1]
assert b" 400 " in duplicate_idempotency_status
assert json.loads(duplicate_idempotency_body.decode("utf-8")) == {
    "status": "failed",
    "error_code": "invalid_idempotency_key",
    "error": "idempotency key must be single-valued",
}
idempotent_first, _idempotent_first_headers = post_json(
    "/run",
    {"goal": "calculate 2 + 3"},
    {"Idempotency-Key": "smoke-retry-1"},
)
idempotent_second, _idempotent_second_headers = post_json(
    "/run",
    {"goal": "calculate 2 + 3"},
    {"Idempotency-Key": "smoke-retry-1"},
)
assert idempotent_first == idempotent_second
conflicting_idempotency_request = urllib.request.Request(
    f"{base_url}/run",
    data=json.dumps({"goal": "calculate 4 + 5"}).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Idempotency-Key": "smoke-retry-1",
    },
    method="POST",
)
try:
    urllib.request.urlopen(conflicting_idempotency_request, timeout=REQUEST_TIMEOUT_SECONDS)
except urllib.error.HTTPError as exc:
    assert exc.code == 409
    assert exc.headers["Cache-Control"] == "no-store"
    assert json.loads(exc.read().decode("utf-8")) == {
        "status": "failed",
        "error_code": "idempotency_key_conflict",
        "error": "idempotency key was already used with a different request body",
    }
else:
    raise AssertionError("conflicting idempotency key unexpectedly succeeded")
run_payload, run_response_headers = post_json("/run", {"goal": "calculate 2 + 3"})
assert run_payload["answer"] == "5"
assert run_payload["run_id"]
assert run_response_headers["X-Run-ID"] == run_payload["run_id"]
assert run_payload["trace_path"]
assert run_response_headers["X-Trace-Path"] == run_payload["trace_path"]
deadline = time.time() + 5
while True:
    access_log_records = [
        json.loads(line)
        for line in open(service_stderr_path, encoding="utf-8")
        if line.strip()
    ]
    run_access_log_records = [
        record
        for record in access_log_records
        if record["method"] == "POST" and record["path"] == "/run"
    ]
    if run_access_log_records:
        break
    if time.time() >= deadline:
        raise AssertionError("missing POST /run access log record")
    time.sleep(0.2)
assert run_access_log_records[-1]["run_id"] == run_payload["run_id"]
assert run_access_log_records[-1]["trace_path"] == run_payload["trace_path"]
assert int(run_access_log_records[-1]["request_body_bytes"]) > 0
idempotency_access_log_records = [
    record
    for record in run_access_log_records
    if record.get("idempotency_key_present") is True
]
assert idempotency_access_log_records
assert "smoke-retry-1" not in open(service_stderr_path, encoding="utf-8").read()
metrics = get_json_auth("/metrics")
assert int(metrics["requests_total"]) >= 3
assert int(metrics["requests_by_method"]["GET"]) >= 1
assert int(metrics["requests_by_method"]["POST"]) >= 1
assert int(metrics["requests_by_path"]["__unknown__"]) >= 1
assert metrics["service_version"]
assert metrics["bind_host"] == "127.0.0.1"
assert int(metrics["bind_port"]) == int(port)
assert metrics["auth_required"] == "true"
assert metrics["protect_diagnostics"] == "true"
assert metrics["trace_persistence"] == "enabled"
assert metrics["trust_forwarded_for"] == "true"
assert float(metrics["request_timeout_seconds"]) > 0
assert int(metrics["max_request_bytes"]) == 2048
assert int(metrics["idempotency_cache_size"]) == 8
assert int(metrics["idempotency_cache_entries"]) >= 1
assert int(metrics["idempotency_cache_hits"]) >= 1
assert int(metrics["idempotency_cache_misses"]) >= 1
assert int(metrics["idempotency_cache_conflicts"]) >= 1
assert int(metrics["idempotency_cache_stores"]) >= 1
assert int(metrics["idempotency_cache_evictions"]) >= 0
assert int(metrics["max_goal_chars"]) == 64
assert int(metrics["error_responses_by_code"]["method_not_allowed"]) >= 1
assert int(metrics["error_responses_by_code"]["invalid_agent_config"]) >= 1
assert int(metrics["error_responses_by_code"]["incomplete_request_body"]) >= 1
assert int(metrics["error_responses_by_code"]["request_body_timeout"]) >= 1
assert int(metrics["error_responses_by_code"]["expectation_failed"]) >= 1
assert int(metrics["error_responses_by_code"]["invalid_idempotency_key"]) >= 1
assert int(metrics["error_responses_by_code"]["invalid_request_body"]) >= 1
assert int(metrics["error_responses_by_code"]["goal_too_large"]) >= 1
assert int(metrics["error_responses_by_code"]["full_trace_disabled"]) >= 1
assert int(metrics["error_responses_by_code"]["idempotency_key_conflict"]) >= 1
assert int(metrics["active_concurrent_runs"]) >= 0
assert int(metrics["max_concurrent_runs"]) >= 0
assert int(metrics["active_rate_limit_windows"]) >= 0
assert int(metrics["rate_limit_per_minute"]) >= 0
assert float(metrics["average_duration_seconds"]) >= 0
assert float(metrics["max_duration_seconds"]) >= 0
assert int(metrics["agent_runs_total"]) >= 1
assert int(metrics["agent_runs_by_status"]["done"]) >= 1
assert float(metrics["average_agent_run_duration_seconds"]) >= 0
assert float(metrics["max_agent_run_duration_seconds"]) >= 0
assert float(metrics["uptime_seconds"]) >= 0
prometheus_metrics, prometheus_content_type = get_text("/metrics.prom")
assert prometheus_content_type.startswith("text/plain")
assert "# HELP self_correcting_agent_requests_total" in prometheus_metrics
assert "# TYPE self_correcting_agent_requests_total counter" in prometheus_metrics
assert "# HELP self_correcting_agent_responses_total" in prometheus_metrics
assert "# TYPE self_correcting_agent_responses_total counter" in prometheus_metrics
assert "# HELP self_correcting_agent_active_concurrent_runs" in prometheus_metrics
assert "# TYPE self_correcting_agent_active_concurrent_runs gauge" in prometheus_metrics
assert "# HELP self_correcting_agent_idempotency_cache_hits" in prometheus_metrics
assert "# TYPE self_correcting_agent_idempotency_cache_hits counter" in prometheus_metrics
assert "self_correcting_agent_requests_total" in prometheus_metrics
assert 'self_correcting_agent_requests_by_method_total{method="GET"}' in prometheus_metrics
assert 'self_correcting_agent_requests_by_method_total{method="POST"}' in prometheus_metrics
assert 'self_correcting_agent_requests_by_path_total{path="__unknown__"}' in prometheus_metrics
assert 'self_correcting_agent_error_responses_total{error_code="method_not_allowed"}' in prometheus_metrics
assert 'self_correcting_agent_error_responses_total{error_code="not_found"}' in prometheus_metrics
assert 'self_correcting_agent_error_responses_total{error_code="full_trace_disabled"}' in prometheus_metrics
assert "self_correcting_agent_request_duration_seconds_bucket" in prometheus_metrics
assert 'self_correcting_agent_request_duration_seconds_bucket{le="+Inf"}' in prometheus_metrics
assert "self_correcting_agent_request_duration_seconds_count" in prometheus_metrics
assert "self_correcting_agent_request_duration_seconds_sum" in prometheus_metrics
assert "self_correcting_agent_agent_run_duration_seconds_bucket" in prometheus_metrics
assert 'self_correcting_agent_agent_run_duration_seconds_bucket{le="+Inf"}' in prometheus_metrics
assert "self_correcting_agent_agent_run_duration_seconds_count" in prometheus_metrics
assert "self_correcting_agent_agent_run_duration_seconds_sum" in prometheus_metrics
assert "self_correcting_agent_runs_total" in prometheus_metrics
assert 'self_correcting_agent_run_status_total{status="done"}' in prometheus_metrics
assert "self_correcting_agent_runtime_pending_approvals_current" in prometheus_metrics
assert "self_correcting_agent_runtime_stale_pending_approvals_current" in prometheus_metrics
assert "self_correcting_agent_runtime_max_pending_approval_age_seconds" in prometheus_metrics
assert "self_correcting_agent_runtime_pending_approval_stale_seconds" in prometheus_metrics
assert "self_correcting_agent_average_agent_run_duration_seconds" in prometheus_metrics
assert "self_correcting_agent_uptime_seconds" in prometheus_metrics
assert "self_correcting_agent_active_concurrent_runs" in prometheus_metrics
assert "self_correcting_agent_active_rate_limit_windows" in prometheus_metrics
assert "self_correcting_agent_build_info" in prometheus_metrics
assert "bind_host" in prometheus_metrics
assert "bind_port" in prometheus_metrics
assert "security_response_headers" in prometheus_metrics
assert "cache_control_header" in prometheus_metrics
assert "content_security_policy_header" in prometheus_metrics
assert "referrer_policy_header" in prometheus_metrics
assert "x_frame_options_header" in prometheus_metrics
assert "x_content_type_options_header" in prometheus_metrics
assert "allow_full_trace_response" in prometheus_metrics
assert "trust_forwarded_for" in prometheus_metrics
assert "max_request_bytes" in prometheus_metrics
assert "self_correcting_agent_max_request_bytes" in prometheus_metrics
assert "protect_diagnostics" in prometheus_metrics
assert "idempotency_cache_size" in prometheus_metrics
assert "idempotency_cache_hits" in prometheus_metrics
assert "idempotency_cache_misses" in prometheus_metrics
assert "idempotency_cache_conflicts" in prometheus_metrics
assert "idempotency_cache_stores" in prometheus_metrics
assert "idempotency_cache_evictions" in prometheus_metrics
assert "request_timeout_seconds" in prometheus_metrics
assert "max_goal_chars" in prometheus_metrics
PY
then
    dump_service_logs
    exit 1
fi
