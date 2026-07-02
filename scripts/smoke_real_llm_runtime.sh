#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
SERVICE_BIN="${SERVICE_BIN:-.venv/bin/self-correcting-agent-serve}"

require_env() {
    name="$1"
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
        echo "$name is required for real LLM runtime smoke" >&2
        exit 2
    fi
}

require_env SELF_CORRECTING_LLM_BASE_URL
require_env SELF_CORRECTING_LLM_API_KEY
require_env SELF_CORRECTING_LLM_MODEL

export SELF_CORRECTING_LLM_TIMEOUT_SECONDS="${SELF_CORRECTING_LLM_TIMEOUT_SECONDS:-60}"

PORT="$("$PYTHON_BIN" - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"
TRACE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/self-correcting-real-llm-traces.XXXXXX")"
SERVICE_LOG="${SERVICE_LOG:-/tmp/self-correcting-real-llm-service.log}"

"$SERVICE_BIN" --host 127.0.0.1 --port "$PORT" --trace-dir "$TRACE_DIR" \
    --runtime-max-iterations 4 --run-timeout-seconds 120 \
    >"$SERVICE_LOG.stdout" 2>"$SERVICE_LOG.stderr" &
server_pid="$!"

dump_service_logs() {
    echo "real LLM runtime smoke failed for pid ${server_pid} on port ${PORT}" >&2
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

if ! "$PYTHON_BIN" - "$PORT" "$TRACE_DIR" <<'PY'
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

port = sys.argv[1]
trace_dir = sys.argv[2]
base_url = f"http://127.0.0.1:{port}"
REQUEST_TIMEOUT_SECONDS = 150


def get_json(path):
    with urllib.request.urlopen(
        f"{base_url}{path}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    ) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def post_json(path, payload):
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8")), response.headers


def is_transient_llm_failure(payload):
    return (
        isinstance(payload, dict)
        and payload.get("status") == "failed"
        and payload.get("error_code") == "invalid_plan"
        and "llm provider request failed" in str(payload.get("error", ""))
    )


def run_cli_runtime_with_retries():
    last_payload = {}
    for _attempt in range(3):
        completed = subprocess.run(
            [
                ".venv/bin/self-correcting-agent",
                "--runtime",
                "--max-iterations",
                "2",
                "Use the note tool to record the exact text smoke-real-llm-cli, then provide final_answer cli-done.",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        last_payload = json.loads(completed.stdout)
        if not is_transient_llm_failure(last_payload):
            return last_payload
        time.sleep(1)
    return last_payload


def post_runtime_with_retries(payload):
    last_payload = {}
    last_headers = {}
    for _attempt in range(3):
        last_payload, last_headers = post_json("/runtime/run", payload)
        if not is_transient_llm_failure(last_payload):
            return last_payload, last_headers
        time.sleep(1)
    return last_payload, last_headers


def payload_contains(value, needle):
    return needle in json.dumps(value, sort_keys=True)


def provider_snapshot():
    parsed = urllib.parse.urlparse(os.environ["SELF_CORRECTING_LLM_BASE_URL"])
    return {
        "llm_provider": "openai_compatible",
        "llm_base_url_host": parsed.hostname or "",
        "llm_model": os.environ["SELF_CORRECTING_LLM_MODEL"],
        "llm_api_key_configured": str(
            bool(os.environ.get("SELF_CORRECTING_LLM_API_KEY", ""))
        ).lower(),
        "llm_timeout_seconds": os.environ.get(
            "SELF_CORRECTING_LLM_TIMEOUT_SECONDS",
            "",
        ),
        "llm_max_retries": os.environ.get("SELF_CORRECTING_LLM_MAX_RETRIES", "0"),
        "llm_retry_backoff_seconds": os.environ.get(
            "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS",
            "0",
        ),
    }


deadline = time.time() + 20
while True:
    try:
        health, _headers = get_json("/health")
        assert health == {"status": "ok"}
        break
    except Exception:
        if time.time() >= deadline:
            raise
        time.sleep(0.2)

cli_payload = run_cli_runtime_with_retries()
assert cli_payload["status"] == "done", cli_payload
assert cli_payload["answer"] == "cli-done", cli_payload
assert payload_contains(cli_payload["observations"], "smoke-real-llm-cli"), cli_payload

policy_payload, _headers = get_json("/runtime/policy")
assert len(policy_payload["effective_tool_policy_sha256"]) == 64, policy_payload

run_payload, run_headers = post_runtime_with_retries(
    {
        "goal": (
            "Use the note tool to record the exact text smoke-real-llm-http, "
            "then provide final_answer http-done."
        ),
        "max_iterations": 2,
    },
)
assert run_payload["status"] == "done", run_payload
assert run_payload["answer"] == "http-done", run_payload
assert payload_contains(run_payload["observations"], "smoke-real-llm-http"), run_payload
assert run_headers["X-Trace-Path"]
assert run_payload["trace_path"]
run_id = run_payload["run_id"]

status_payload, _headers = get_json(f"/runtime/runs/{run_id}")
assert status_payload["status"] == "done", status_payload
assert status_payload["trace_path"] == run_payload["trace_path"]
timeline_payload, _headers = get_json(f"/runtime/runs/{run_id}/timeline")
assert int(timeline_payload["event_count"]) >= 3, timeline_payload
runs_payload, _headers = get_json("/runtime/runs?status=done&limit=5")
assert run_id in [item["run_id"] for item in runs_payload["runs"]]

pending_payload, _headers = post_runtime_with_retries(
    {
        "goal": "Use http_request to fetch https://example.com, then stop.",
        "max_iterations": 1,
    },
)
assert pending_payload["status"] == "requires_approval", pending_payload
assert pending_payload["pending_approval"]["tool"] == "http_request"
pending_action_id = pending_payload["pending_approval"]["id"]

resumed_payload, _headers = post_json(
    "/runtime/resume",
    {
        "run_id": pending_payload["run_id"],
        "approved_action_ids": [pending_action_id],
        "max_iterations": 1,
    },
)
assert resumed_payload["status"] == "done", resumed_payload
assert resumed_payload["resumed_from_run_id"] == pending_payload["run_id"]
assert resumed_payload["observations"][0]["tool"] == "http_request"
assert resumed_payload["observations"][0]["status"] == "ok"
assert resumed_payload["observations"][0]["output"]["status_code"] == 200

metrics_payload, _headers = get_json("/metrics")
assert int(metrics_payload["runtime_runs_total"]) >= 3, metrics_payload
assert int(metrics_payload["runtime_approval_required_total"]) >= 1, metrics_payload
assert "done" in metrics_payload["runtime_runs_by_status"], metrics_payload
assert "requires_approval" in metrics_payload["runtime_runs_by_status"], metrics_payload

print(
    json.dumps(
        {
            "evidence_schema_version": "1",
            "status": "passed",
            "provider_snapshot": provider_snapshot(),
            "capability_checks": {
                "cli_runtime": "passed",
                "http_runtime": "passed",
                "trace_status": "passed",
                "timeline": "passed",
                "approval_resume": "passed",
                "metrics": "passed",
            },
            "trace_dir": trace_dir,
            "cli_run_id": cli_payload["run_id"],
            "http_run_id": run_id,
            "approval_run_id": pending_payload["run_id"],
            "resumed_run_id": resumed_payload["run_id"],
            "runtime_effective_tool_policy_sha256": policy_payload[
                "effective_tool_policy_sha256"
            ],
            "runtime_runs_total": metrics_payload["runtime_runs_total"],
            "runtime_runs_by_status": metrics_payload["runtime_runs_by_status"],
            "runtime_approval_required_total": metrics_payload[
                "runtime_approval_required_total"
            ],
        },
        indent=2,
        sort_keys=True,
    )
)
PY
then
    dump_service_logs
    exit 1
fi
