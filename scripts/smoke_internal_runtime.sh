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

SERVICE_LOG="${SERVICE_LOG:-/tmp/self-correcting-agent-internal-runtime-smoke.log}"
TRACE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/self-correcting-internal-runtime-traces.XXXXXX")"
ADMIN_TOKEN="${SELF_CORRECTING_INTERNAL_SMOKE_ADMIN_TOKEN:-internal-admin-token}"
TEAM_A_TOKEN="${SELF_CORRECTING_INTERNAL_SMOKE_TEAM_A_TOKEN:-internal-team-a-token}"
TEAM_B_TOKEN="${SELF_CORRECTING_INTERNAL_SMOKE_TEAM_B_TOKEN:-internal-team-b-token}"

SELF_CORRECTING_SERVICE_AUTH_TOKEN="$ADMIN_TOKEN" \
SELF_CORRECTING_SERVICE_AUTH_TOKENS="{\"team-a\":\"$TEAM_A_TOKEN\",\"team-b\":\"$TEAM_B_TOKEN\"}" \
SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT='{"team-a":"note","team-b":"note"}' \
    "$SERVICE_BIN" --host 127.0.0.1 --port "$PORT" --trace-dir "$TRACE_DIR" \
    --protect-diagnostics --runtime-max-iterations 3 \
    >"$SERVICE_LOG.stdout" 2>"$SERVICE_LOG.stderr" &
server_pid="$!"

dump_service_logs() {
    echo "internal runtime smoke failed for pid ${server_pid} on port ${PORT}" >&2
    echo "service stdout ($SERVICE_LOG.stdout):" >&2
    sed -n '1,160p' "$SERVICE_LOG.stdout" >&2 || true
    echo "service stderr ($SERVICE_LOG.stderr):" >&2
    sed -n '1,260p' "$SERVICE_LOG.stderr" >&2 || true
}

cleanup() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    rm -rf "$TRACE_DIR"
}
trap cleanup EXIT INT TERM

if ! "$PYTHON_BIN" - "$PORT" "$SERVICE_LOG.stderr" "$ADMIN_TOKEN" "$TEAM_A_TOKEN" "$TEAM_B_TOKEN" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

port = sys.argv[1]
service_stderr_path = sys.argv[2]
admin_token = sys.argv[3]
team_a_token = sys.argv[4]
team_b_token = sys.argv[5]
base_url = f"http://127.0.0.1:{port}"
REQUEST_TIMEOUT_SECONDS = 15


def request_json(path, *, token="", payload=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method or ("POST" if payload is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def request_text(path, *, token=""):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def post_runtime(token, plan, *, metadata=None, tags=None):
    payload = {
        "goal": "internal runtime smoke",
        "max_iterations": 1,
        "plan": plan,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    if tags is not None:
        payload["tags"] = tags
    return request_json(
        "/runtime/run",
        token=token,
        payload=payload,
    )


deadline = time.time() + 10
while True:
    try:
        status, health = request_json("/health")
        assert status == 200
        assert health == {"status": "ok"}
        break
    except Exception:
        if time.time() >= deadline:
            raise
        time.sleep(0.2)

unauthorized_status, unauthorized_payload = request_json("/runtime/runs")
assert unauthorized_status == 401, unauthorized_payload
unauthorized_summary_status, unauthorized_summary_payload = request_json(
    "/runtime/runs/summary"
)
assert unauthorized_summary_status == 401, unauthorized_summary_payload

team_a_done_status, team_a_done = post_runtime(
    team_a_token,
    {
        "actions": [
            {
                "id": "note-1",
                "tool": "note",
                "input": {"text": "subject-scoped runtime trace reads"},
                "reason": "record subject smoke",
            }
        ],
        "final_answer": "team-a-done",
    },
    metadata={"workflow": "internal", "ticket": "SMOKE-1"},
    tags=["internal-smoke", "team-a"],
)
assert team_a_done_status == 200, team_a_done
assert team_a_done["status"] == "done", team_a_done
assert team_a_done["auth_subject"] == "team-a", team_a_done
assert team_a_done["metadata"] == {
    "ticket": "SMOKE-1",
    "workflow": "internal",
}, team_a_done
assert team_a_done["tags"] == ["internal-smoke", "team-a"], team_a_done

team_b_detail_status, team_b_detail = request_json(
    f"/runtime/runs/{team_a_done['run_id']}",
    token=team_b_token,
)
assert team_b_detail_status == 404, team_b_detail

team_a_pending_status, team_a_pending = post_runtime(
    team_a_token,
    {
        "actions": [
            {
                "id": "transform-1",
                "tool": "transform_text",
                "input": {"text": "subject-scoped runtime resume", "mode": "uppercase"},
                "reason": "exercise approval boundary",
            }
        ],
        "final_answer": "pending",
    },
)
assert team_a_pending_status == 200, team_a_pending
assert team_a_pending["status"] == "requires_approval", team_a_pending
assert team_a_pending["pending_approval"]["tool"] == "transform_text", team_a_pending

# Template route covered below: /runtime/runs/{run_id}/cancel
team_a_cancel_pending_status, team_a_cancel_pending = post_runtime(
    team_a_token,
    {
        "actions": [
            {
                "id": "cancel-1",
                "tool": "transform_text",
                "input": {"text": "subject-scoped runtime cancel", "mode": "uppercase"},
                "reason": "exercise cancel boundary",
            }
        ],
        "final_answer": "cancel-pending",
    },
)
assert team_a_cancel_pending_status == 200, team_a_cancel_pending
assert team_a_cancel_pending["status"] == "requires_approval", team_a_cancel_pending

team_b_cancel_status, team_b_cancel = request_json(
    f"/runtime/runs/{team_a_cancel_pending['run_id']}/cancel",
    token=team_b_token,
    payload={"reason": "cross-subject cancel must stay hidden"},
)
assert team_b_cancel_status == 404, team_b_cancel

team_a_cancel_status, team_a_cancel = request_json(
    f"/runtime/runs/{team_a_cancel_pending['run_id']}/cancel",
    token=team_a_token,
    payload={"reason": "subject-scoped runtime cancel"},
)
assert team_a_cancel_status == 200, team_a_cancel
assert team_a_cancel["status"] == "cancelled", team_a_cancel
assert team_a_cancel["cancelled_by_auth_subject"] == "team-a", team_a_cancel
assert team_a_cancel["pending_approval_action_id"] == "", team_a_cancel

team_b_resume_status, team_b_resume = request_json(
    "/runtime/resume",
    token=team_b_token,
    payload={
        "run_id": team_a_pending["run_id"],
        "approved_action_ids": ["transform-1"],
        "max_iterations": 1,
    },
)
assert team_b_resume_status == 404, team_b_resume

admin_resume_status, admin_resume = request_json(
    "/runtime/resume",
    token=admin_token,
    payload={
        "run_id": team_a_pending["run_id"],
        "approved_action_ids": ["transform-1"],
        "max_iterations": 1,
    },
)
assert admin_resume_status == 200, admin_resume
assert admin_resume["status"] == "done", admin_resume
assert admin_resume["auth_subject"] == "team-a", admin_resume
assert admin_resume["resumed_by_auth_subject"] == "default", admin_resume
assert admin_resume["resumed_from_run_id"] == team_a_pending["run_id"], admin_resume

team_a_summary_status, team_a_summary = request_json(
    "/runtime/runs/summary?status=done",
    token=team_a_token,
)
assert team_a_summary_status == 200, team_a_summary
assert team_a_summary["run_count"] == "2", team_a_summary
assert team_a_summary["auth_subject_counts"] == {"team-a": "2"}, team_a_summary

team_a_cancelled_summary_status, team_a_cancelled_summary = request_json(
    "/runtime/runs/summary?status=cancelled",
    token=team_a_token,
)
assert team_a_cancelled_summary_status == 200, team_a_cancelled_summary
assert team_a_cancelled_summary["run_count"] == "1", team_a_cancelled_summary
assert team_a_cancelled_summary["status_counts"] == {
    "cancelled": "1"
}, team_a_cancelled_summary

team_a_tag_summary_status, team_a_tag_summary = request_json(
    "/runtime/runs/summary?tag=internal-smoke",
    token=team_a_token,
)
assert team_a_tag_summary_status == 200, team_a_tag_summary
assert team_a_tag_summary["run_count"] == "1", team_a_tag_summary
assert team_a_tag_summary["tag_counts"] == {
    "internal-smoke": "1",
    "team-a": "1",
}, team_a_tag_summary
assert team_a_tag_summary["metadata_key_counts"] == {
    "ticket": "1",
    "workflow": "1",
}, team_a_tag_summary

team_a_metadata_summary_status, team_a_metadata_summary = request_json(
    "/runtime/runs/summary?metadata_key=workflow&metadata_value=internal",
    token=team_a_token,
)
assert team_a_metadata_summary_status == 200, team_a_metadata_summary
assert team_a_metadata_summary["run_count"] == "1", team_a_metadata_summary

team_a_tag_list_status, team_a_tag_list = request_json(
    "/runtime/runs?tag=internal-smoke&limit=10",
    token=team_a_token,
)
assert team_a_tag_list_status == 200, team_a_tag_list
assert team_a_tag_list["count"] == "1", team_a_tag_list
assert team_a_tag_list["runs"][0]["metadata_keys"] == [
    "ticket",
    "workflow",
], team_a_tag_list
assert team_a_tag_list["runs"][0]["tags"] == [
    "internal-smoke",
    "team-a",
], team_a_tag_list

admin_summary_status, admin_summary = request_json(
    "/runtime/runs/summary?has_pending_approval=true",
    token=admin_token,
)
assert admin_summary_status == 200, admin_summary
assert admin_summary["run_count"] == "1", admin_summary
assert admin_summary["pending_approval_count"] == "1", admin_summary

team_a_approvals_status, team_a_approvals = request_json(
    "/runtime/approvals",
    token=team_a_token,
)
assert team_a_approvals_status == 200, team_a_approvals
assert team_a_approvals["count"] == "1", team_a_approvals
assert team_a_approvals["approvals"][0]["run_id"] == team_a_pending["run_id"], team_a_approvals
assert team_a_approvals["approvals"][0]["pending_approval_tool"] == "transform_text", team_a_approvals
assert int(team_a_approvals["approvals"][0]["pending_age_seconds"]) >= 0, team_a_approvals
assert "pending_approval" not in team_a_approvals["approvals"][0], team_a_approvals

team_a_stale_approvals_status, team_a_stale_approvals = request_json(
    "/runtime/approvals?min_pending_age_seconds=0",
    token=team_a_token,
)
assert team_a_stale_approvals_status == 200, team_a_stale_approvals
assert team_a_stale_approvals["count"] == "1", team_a_stale_approvals
assert int(team_a_stale_approvals["approvals"][0]["pending_age_seconds"]) >= 0, team_a_stale_approvals

team_a_approval_summary_status, team_a_approval_summary = request_json(
    "/runtime/approvals/summary?min_pending_age_seconds=0",
    token=team_a_token,
)
assert team_a_approval_summary_status == 200, team_a_approval_summary
assert team_a_approval_summary["pending_approval_count"] == "1", team_a_approval_summary
assert team_a_approval_summary["stale_pending_count"] == "1", team_a_approval_summary
assert int(team_a_approval_summary["max_pending_age_seconds"]) >= 0, team_a_approval_summary
assert team_a_approval_summary["auth_subject_counts"] == {
    "team-a": "1"
}, team_a_approval_summary
assert team_a_approval_summary["tool_counts"] == {
    "transform_text": "1"
}, team_a_approval_summary

team_a_policy_status, team_a_policy = request_json(
    "/runtime/policy",
    token=team_a_token,
)
assert team_a_policy_status == 200, team_a_policy
assert team_a_policy["auth_subject"] == "team-a", team_a_policy
assert team_a_policy["is_admin"] == "false", team_a_policy
assert team_a_policy["effective_policy_source"] == "subject", team_a_policy
assert team_a_policy["effective_allowed_tools"] == ["note"], team_a_policy
assert team_a_policy["subject_allowed_tools"] == {"team-a": ["note"]}, team_a_policy
assert "team-b" not in json.dumps(team_a_policy), team_a_policy

admin_policy_status, admin_policy = request_json(
    "/runtime/policy",
    token=admin_token,
)
assert admin_policy_status == 200, admin_policy
assert admin_policy["auth_subject"] == "default", admin_policy
assert admin_policy["is_admin"] == "true", admin_policy
assert admin_policy["subject_policy_count"] == "2", admin_policy
assert admin_policy["subject_allowed_tools"]["team-a"] == ["note"], admin_policy
assert admin_policy["subject_allowed_tools"]["team-b"] == ["note"], admin_policy

metrics_status, metrics = request_json("/metrics", token=admin_token)
assert metrics_status == 200, metrics
assert metrics["runtime_runs_by_auth_subject"]["team-a"] == "5", metrics
assert metrics["runtime_runs_by_auth_subject_status"]["team-a:done"] == "2", metrics
assert metrics["runtime_runs_by_auth_subject_status"]["team-a:requires_approval"] == "2", metrics
assert metrics["runtime_runs_by_auth_subject_status"]["team-a:cancelled"] == "1", metrics
assert metrics["runtime_resumes_by_auth_subject"]["default"] == "1", metrics
assert metrics["runtime_pending_approvals_current"] == "1", metrics
assert metrics["runtime_stale_pending_approvals_current"] == "0", metrics
assert int(metrics["runtime_max_pending_approval_age_seconds"]) >= 0, metrics
assert metrics["runtime_pending_approval_stale_seconds"] == "3600", metrics

prometheus_status, prometheus_metrics = request_text("/metrics.prom", token=admin_token)
assert prometheus_status == 200, prometheus_metrics
assert "self_correcting_agent_runtime_pending_approvals_current 1" in prometheus_metrics
assert "self_correcting_agent_runtime_stale_pending_approvals_current 0" in prometheus_metrics
assert "self_correcting_agent_runtime_max_pending_approval_age_seconds" in prometheus_metrics
assert "self_correcting_agent_runtime_pending_approval_stale_seconds 3600" in prometheus_metrics

stderr = open(service_stderr_path, encoding="utf-8").read()
records = [json.loads(line) for line in stderr.splitlines() if line.strip()]
resume_records = [
    record
    for record in records
    if record["method"] == "POST" and record["path"] == "/runtime/resume"
]
assert resume_records, stderr
assert resume_records[-1]["auth_subject"] == "default", resume_records[-1]
assert resume_records[-1]["runtime_owner_auth_subject"] == "team-a", resume_records[-1]
assert resume_records[-1]["resumed_by_auth_subject"] == "default", resume_records[-1]
assert admin_token not in stderr
assert team_a_token not in stderr
assert team_b_token not in stderr

print(
    json.dumps(
        {
            "status": "passed",
            "team_a_run_status": team_a_done["status"],
            "team_b_cross_subject_status": str(team_b_detail_status),
            "team_b_cross_subject_resume_status": str(team_b_resume_status),
            "team_b_cross_subject_cancel_status": str(team_b_cancel_status),
            "admin_resume_status": admin_resume["status"],
            "team_a_cancel_status": team_a_cancel["status"],
            "runtime_runs_by_auth_subject": metrics["runtime_runs_by_auth_subject"],
            "runtime_runs_by_auth_subject_status": metrics[
                "runtime_runs_by_auth_subject_status"
            ],
            "runtime_resumes_by_auth_subject": metrics[
                "runtime_resumes_by_auth_subject"
            ],
            "runtime_pending_approvals_current": metrics[
                "runtime_pending_approvals_current"
            ],
            "runtime_stale_pending_approvals_current": metrics[
                "runtime_stale_pending_approvals_current"
            ],
            "runtime_max_pending_approval_age_seconds": metrics[
                "runtime_max_pending_approval_age_seconds"
            ],
            "runtime_pending_approval_stale_seconds": metrics[
                "runtime_pending_approval_stale_seconds"
            ],
            "team_a_summary_run_count": team_a_summary["run_count"],
            "team_a_cancelled_summary_run_count": team_a_cancelled_summary[
                "run_count"
            ],
            "team_a_tag_summary_run_count": team_a_tag_summary["run_count"],
            "team_a_metadata_summary_run_count": team_a_metadata_summary[
                "run_count"
            ],
            "admin_pending_summary_run_count": admin_summary["run_count"],
            "team_a_approval_queue_count": team_a_approvals["count"],
            "team_a_approval_min_age_queue_count": team_a_stale_approvals[
                "count"
            ],
            "team_a_approval_summary_count": team_a_approval_summary[
                "pending_approval_count"
            ],
            "team_a_approval_stale_pending_count": team_a_approval_summary[
                "stale_pending_count"
            ],
            "team_a_approval_max_pending_age_seconds": team_a_approval_summary[
                "max_pending_age_seconds"
            ],
            "team_a_policy_source": team_a_policy["effective_policy_source"],
            "admin_policy_subject_count": admin_policy["subject_policy_count"],
            "team_a_run_id": team_a_done["run_id"],
            "pending_run_id": team_a_pending["run_id"],
            "cancelled_run_id": team_a_cancel["run_id"],
            "admin_resumed_run_id": admin_resume["run_id"],
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
