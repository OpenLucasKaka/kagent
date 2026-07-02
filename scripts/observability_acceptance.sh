#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

require_env() {
    name="$1"
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
        echo "$name is required for observability acceptance" >&2
        exit 2
    fi
}

require_env SELF_CORRECTING_OBSERVABILITY_BASE_URL

"$PYTHON_BIN" - <<'PY'
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

base_url = os.environ["SELF_CORRECTING_OBSERVABILITY_BASE_URL"].rstrip("/")
secret = os.environ.get("SELF_CORRECTING_OBSERVABILITY_TOKEN", "")
timeout_seconds = float(
    os.environ.get("SELF_CORRECTING_OBSERVABILITY_TIMEOUT_SECONDS", "30")
)
metrics_path = os.environ.get(
    "SELF_CORRECTING_OBSERVABILITY_METRICS_PATH", "/metrics.prom"
)
prometheus_base_url = os.environ.get("SELF_CORRECTING_PROMETHEUS_BASE_URL", "").rstrip("/")
prometheus_secret = os.environ.get("SELF_CORRECTING_PROMETHEUS_TOKEN", "")
prometheus_query = os.environ.get(
    "SELF_CORRECTING_PROMETHEUS_QUERY", "self_correcting_agent_build_info"
)

parsed = urllib.parse.urlparse(base_url)
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    raise SystemExit("SELF_CORRECTING_OBSERVABILITY_BASE_URL must be an http(s) URL")
if parsed.username or parsed.password:
    raise SystemExit("SELF_CORRECTING_OBSERVABILITY_BASE_URL must not contain credentials")
if not metrics_path.startswith("/"):
    raise SystemExit("SELF_CORRECTING_OBSERVABILITY_METRICS_PATH must start with /")
prometheus_parsed = None
if prometheus_base_url:
    prometheus_parsed = urllib.parse.urlparse(prometheus_base_url)
    if prometheus_parsed.scheme not in {"http", "https"} or not prometheus_parsed.netloc:
        raise SystemExit("SELF_CORRECTING_PROMETHEUS_BASE_URL must be an http(s) URL")
    if prometheus_parsed.username or prometheus_parsed.password:
        raise SystemExit("SELF_CORRECTING_PROMETHEUS_BASE_URL must not contain credentials")

required_metrics = [
    "self_correcting_agent_requests_total",
    "self_correcting_agent_responses_total",
    "self_correcting_agent_request_duration_seconds_bucket",
    "self_correcting_agent_runtime_runs_total",
    "self_correcting_agent_runtime_run_duration_seconds_bucket",
    "self_correcting_agent_runtime_approval_required_total",
    "self_correcting_agent_runtime_stale_pending_approvals_current",
    "self_correcting_agent_runtime_runs_by_auth_subject_total",
    "self_correcting_agent_build_info",
]


def request_text(path):
    headers = {"Accept": "text/plain"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    request = urllib.request.Request(f"{base_url}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def request_prometheus_query():
    if not prometheus_base_url:
        return "not_configured", "0"
    headers = {"Accept": "application/json"}
    if prometheus_secret:
        headers["Authorization"] = f"Bearer {prometheus_secret}"
    query_string = urllib.parse.urlencode({"query": prometheus_query})
    request = urllib.request.Request(
        f"{prometheus_base_url}/api/v1/query?{query_string}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return "failed", "0"
    result = payload.get("data", {}).get("result", [])
    if payload.get("status") != "success" or not isinstance(result, list):
        return "failed", "0"
    if not result:
        return "empty", "0"
    return "passed", str(len(result))


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grafana_status():
    path = Path("deploy/grafana/self-correcting-agent-dashboard.json")
    if not path.is_file():
        return "missing", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "invalid_json", file_sha256(path)
    panels = payload.get("panels")
    if not isinstance(panels, list) or len(panels) < 8:
        return "invalid", file_sha256(path)
    return "passed", file_sha256(path)


def prometheus_rules_status():
    path = Path("deploy/prometheus/self-correcting-agent-rules.yaml")
    if not path.is_file():
        return "missing", ""
    text = path.read_text(encoding="utf-8")
    required_alerts = [
        "SelfCorrectingAgentServiceDown",
        "SelfCorrectingAgentHighErrorRate",
        "SelfCorrectingAgentSlowRuntimeRuns",
        "SelfCorrectingAgentRuntimeSubjectRunFailures",
    ]
    if any(alert not in text for alert in required_alerts):
        return "missing_required_alerts", file_sha256(path)
    return "passed", file_sha256(path)


metrics_status, metrics_text = request_text(metrics_path)
missing_metrics = [metric for metric in required_metrics if metric not in metrics_text]
dashboard_status, dashboard_sha256 = grafana_status()
rules_status, rules_sha256 = prometheus_rules_status()
prometheus_query_status, prometheus_result_count = request_prometheus_query()

status = "passed"
if metrics_status != 200:
    status = "failed"
if missing_metrics:
    status = "failed"
if dashboard_status != "passed" or rules_status != "passed":
    status = "failed"
if prometheus_query_status not in {"passed", "not_configured"}:
    status = "failed"

result = {
    "evidence_schema_version": "1",
    "status": status,
    "base_url_host": parsed.hostname or "",
    "metrics_endpoint": metrics_path,
    "metrics_status": str(metrics_status),
    "required_metrics_present": str(not missing_metrics).lower(),
    "required_metric_count": str(len(required_metrics)),
    "missing_required_metrics": missing_metrics,
    "metrics_sha256": hashlib.sha256(metrics_text.encode("utf-8")).hexdigest(),
    "grafana_dashboard_status": dashboard_status,
    "grafana_dashboard_sha256": dashboard_sha256,
    "prometheus_rules_status": rules_status,
    "prometheus_rules_sha256": rules_sha256,
    "prometheus_query_status": prometheus_query_status,
    "prometheus_query": prometheus_query if prometheus_base_url else "",
    "prometheus_result_count": prometheus_result_count,
    "prometheus_host": (
        prometheus_parsed.hostname
        if prometheus_parsed is not None and prometheus_parsed.hostname
        else ""
    ),
}
print(json.dumps(result, indent=2, sort_keys=True))
if status != "passed":
    sys.exit(1)
PY
