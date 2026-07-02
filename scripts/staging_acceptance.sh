#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

require_env() {
    name="$1"
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
        echo "$name is required for staging acceptance" >&2
        exit 2
    fi
}

require_env SELF_CORRECTING_STAGING_BASE_URL
require_env SELF_CORRECTING_STAGING_TOKEN

"$PYTHON_BIN" - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

base_url = os.environ["SELF_CORRECTING_STAGING_BASE_URL"].rstrip("/")
secret = os.environ["SELF_CORRECTING_STAGING_TOKEN"]
timeout_seconds = float(os.environ.get("SELF_CORRECTING_STAGING_TIMEOUT_SECONDS", "30"))

parsed = urllib.parse.urlparse(base_url)
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    raise SystemExit("SELF_CORRECTING_STAGING_BASE_URL must be an http(s) URL")
if parsed.username or parsed.password:
    raise SystemExit("SELF_CORRECTING_STAGING_BASE_URL must not contain credentials")


def request_json(path, *, payload=None, method=None, idempotency_key=""):
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {secret}",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"status": "failed", "error": "non-json response"}
        return exc.code, payload


def assert_status(actual, expected, payload, label):
    if actual != expected:
        raise AssertionError(f"{label} returned {actual}: {payload}")


health_status, health = request_json("/health")
assert_status(health_status, 200, health, "health")
assert health == {"status": "ok"}, health

ready_status, ready = request_json("/ready")
assert ready_status in {200, 503}, ready
assert ready.get("status") == "ready", ready

openapi_status, openapi = request_json("/openapi.json")
assert_status(openapi_status, 200, openapi, "openapi")
for path in [
    "/runtime/run",
    "/runtime/policy",
    "/runtime/runs",
    "/runtime/runs/summary",
    "/metrics",
]:
    assert path in openapi["paths"], path

tools_status, tools = request_json("/runtime/tools")
assert_status(tools_status, 200, tools, "runtime tools")
tool_names = [tool["name"] for tool in tools["tools"]]
assert "note" in tool_names, tools

policy_status, policy = request_json("/runtime/policy")
assert_status(policy_status, 200, policy, "runtime policy")
assert "note" in policy["effective_allowed_tools"], policy
effective_tool_policy = {
    item["name"]: item for item in policy.get("effective_tool_policy", [])
}
assert effective_tool_policy, policy
assert effective_tool_policy["note"]["allowed"] == "true", policy
assert (
    effective_tool_policy["http_request"]["approval_required"] == "true"
), policy

run_status, run = request_json(
    "/runtime/run",
    payload={
        "goal": "staging acceptance deterministic runtime check",
        "max_iterations": 1,
        "plan": {
            "actions": [
                {
                    "id": "staging-note",
                    "tool": "note",
                    "input": {"text": "staging-acceptance-runtime"},
                    "reason": "verify deployed runtime execution",
                }
            ],
            "final_answer": "staging-acceptance-done",
        },
    },
    idempotency_key="staging-acceptance-runtime-v1",
)
assert_status(run_status, 200, run, "runtime run")
assert run["status"] == "done", run
assert run["answer"] == "staging-acceptance-done", run
run_id = run["run_id"]

status_status, status_payload = request_json(f"/runtime/runs/{run_id}")
assert_status(status_status, 200, status_payload, "runtime status")
assert status_payload["run_id"] == run_id, status_payload
assert status_payload["status"] == "done", status_payload

timeline_status, timeline = request_json(f"/runtime/runs/{run_id}/timeline")
assert_status(timeline_status, 200, timeline, "runtime timeline")
assert int(timeline["event_count"]) >= 1, timeline

runs_status, runs = request_json("/runtime/runs?limit=5")
assert_status(runs_status, 200, runs, "runtime runs")
assert run_id in [item["run_id"] for item in runs["runs"]], runs

summary_status, summary = request_json("/runtime/runs/summary")
assert_status(summary_status, 200, summary, "runtime summary")
assert int(summary["run_count"]) >= 1, summary

approvals_status, approvals = request_json("/runtime/approvals")
assert_status(approvals_status, 200, approvals, "runtime approvals")

approval_summary_status, approval_summary = request_json("/runtime/approvals/summary")
assert_status(
    approval_summary_status,
    200,
    approval_summary,
    "runtime approval summary",
)

metrics_status, metrics = request_json("/metrics")
assert_status(metrics_status, 200, metrics, "metrics")
assert metrics["trace_persistence"] == "enabled", metrics
assert int(metrics["runtime_runs_total"]) >= 1, metrics

result = {
    "evidence_schema_version": "1",
    "status": "passed",
    "base_url_host": parsed.hostname or "",
    "health_status": health["status"],
    "ready_status": ready["status"],
    "auth_subject": run.get("auth_subject", ""),
    "runtime_policy_source": policy["effective_policy_source"],
    "runtime_effective_tool_policy_count": str(len(effective_tool_policy)),
    "runtime_effective_tool_policy_sha256": policy[
        "effective_tool_policy_sha256"
    ],
    "runtime_note_allowed": effective_tool_policy["note"]["allowed"],
    "runtime_http_request_approval_required": effective_tool_policy[
        "http_request"
    ]["approval_required"],
    "runtime_run_status": run["status"],
    "runtime_run_id": run_id,
    "runtime_timeline_event_count": timeline["event_count"],
    "runtime_summary_run_count": summary["run_count"],
    "approval_queue_count": approvals["count"],
    "approval_summary_count": approval_summary["pending_approval_count"],
    "metrics_trace_persistence": metrics["trace_persistence"],
    "metrics_runtime_runs_total": metrics["runtime_runs_total"],
}
print(json.dumps(result, indent=2, sort_keys=True))
PY
