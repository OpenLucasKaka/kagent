#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List

from self_correcting_langgraph_agent.ops.release_evidence import (
    _internal_rollout_missing_fields,
    _observability_acceptance_missing_fields,
    _staging_acceptance_missing_fields,
)

REQUIRED_ARTIFACTS = (
    "scripts/run_checks.sh",
    "scripts/smoke_service.sh",
    "scripts/smoke_internal_runtime.sh",
    "scripts/smoke_real_llm_runtime.sh",
    "scripts/staging_acceptance.sh",
    "scripts/observability_acceptance.sh",
    "scripts/internal_rollout_acceptance.py",
    "deploy/env.example",
    "deploy/kubernetes/self-correcting-agent.yaml",
    "deploy/prometheus/self-correcting-agent-rules.yaml",
    "deploy/prometheus/self-correcting-agent-servicemonitor.yaml",
    "deploy/grafana/self-correcting-agent-dashboard.json",
    "deploy/systemd/self-correcting-agent.service",
    "docs/deployment.md",
    "docs/internal-rollout.md",
    "docs/operations.md",
    "docs/production-readiness.md",
    "examples/internal_runtime_client.py",
)

REQUIRED_OPENAPI_PATHS = (
    "/health",
    "/ready",
    "/runtime/run",
    "/runtime/resume",
    "/runtime/policy",
    "/runtime/approvals",
    "/runtime/approvals/summary",
    "/runtime/runs",
    "/runtime/runs/summary",
    "/runtime/runs/{run_id}",
    "/runtime/runs/{run_id}/timeline",
    "/runtime/runs/{run_id}/artifacts",
    "/runtime/runs/{run_id}/artifacts/{artifact_id}",
    "/openapi.json",
)

REQUIRED_ENV_SERVICE_KEYS = (
    "SELF_CORRECTING_SERVICE_HOST",
    "SELF_CORRECTING_SERVICE_PORT",
    "SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES",
    "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS",
    "SELF_CORRECTING_SERVICE_AUTH_TOKEN",
    "SELF_CORRECTING_SERVICE_AUTH_TOKENS",
    "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE",
    "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS",
    "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE",
    "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH",
    "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE",
    "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS",
    "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR",
    "SELF_CORRECTING_SERVICE_TRACE_DIR",
    "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS",
    "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS",
)

REQUIRED_ENV_RUNTIME_KEYS = (
    "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS",
    "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT",
    "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS",
    "SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS",
    "SELF_CORRECTING_MAX_STEPS",
    "SELF_CORRECTING_MAX_RETRIES",
)

REQUIRED_ENV_PROVIDER_KEYS = (
    "SELF_CORRECTING_LLM_BASE_URL",
    "SELF_CORRECTING_LLM_API_KEY",
    "SELF_CORRECTING_LLM_MODEL",
    "SELF_CORRECTING_LLM_TIMEOUT_SECONDS",
    "SELF_CORRECTING_LLM_MAX_RETRIES",
    "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS",
)

REQUIRED_GRAFANA_METRICS = (
    "up",
    "self_correcting_agent_responses_total",
    "self_correcting_agent_requests_total",
    "self_correcting_agent_runtime_run_duration_seconds_bucket",
    "self_correcting_agent_runtime_approval_required_total",
    "self_correcting_agent_runtime_stale_pending_approvals_current",
    "self_correcting_agent_runtime_runs_by_auth_subject_total",
    "self_correcting_agent_runtime_run_status_by_auth_subject_total",
    "self_correcting_agent_runtime_resumes_by_auth_subject_total",
    "self_correcting_agent_runtime_observation_errors_total",
)

REQUIRED_PROMETHEUS_ALERTS = (
    "SelfCorrectingAgentServiceDown",
    "SelfCorrectingAgentHighErrorRate",
    "SelfCorrectingAgentSlowRuntimeRuns",
    "SelfCorrectingAgentRuntimeSubjectRunFailures",
    "SelfCorrectingAgentRuntimeStalePendingApprovals",
    "SelfCorrectingAgentRuntimeSubjectResumes",
    "SelfCorrectingAgentRuntimeToolExecutionTimeouts",
    "SelfCorrectingAgentTracePersistenceFailures",
    "SelfCorrectingAgentConcurrencySaturated",
    "SelfCorrectingAgentRequestBodyTimeouts",
    "SelfCorrectingAgentMalformedRunRequests",
    "SelfCorrectingAgentOversizedRunRequests",
    "SelfCorrectingAgentUnknownRouteTraffic",
)

REQUIRED_PROMETHEUS_RULE_METRICS = (
    "up",
    "self_correcting_agent_responses_total",
    "self_correcting_agent_requests_total",
    "self_correcting_agent_runtime_run_duration_seconds_bucket",
    "self_correcting_agent_runtime_run_status_by_auth_subject_total",
    "self_correcting_agent_runtime_resumes_by_auth_subject_total",
    "self_correcting_agent_runtime_stale_pending_approvals_current",
    "self_correcting_agent_runtime_observation_errors_total",
    "self_correcting_agent_error_responses_total",
    "self_correcting_agent_idempotency_cache_evictions",
    "tool_execution_timeout",
    "trace_persistence_failed",
    "request_body_timeout",
    "not_found",
)

REQUIRED_SERVICEMONITOR_SCRAPE_MARKERS = (
    "apiVersion: monitoring.coreos.com/v1",
    "kind: ServiceMonitor",
    "name: self-correcting-agent",
    "app.kubernetes.io/name: self-correcting-agent",
    "port: http",
    "path: /metrics.prom",
    "interval: 30s",
    "scrapeTimeout: 5s",
)

REQUIRED_KUBERNETES_RESOURCES = (
    "Secret",
    "ConfigMap",
    "PersistentVolumeClaim",
    "Deployment",
    "Service",
    "PodDisruptionBudget",
    "NetworkPolicy",
    "CronJob",
)

REQUIRED_KUBERNETES_HARDENING_MARKERS = (
    "automountServiceAccountToken: false",
    "runAsNonRoot: true",
    "readOnlyRootFilesystem: true",
    "allowPrivilegeEscalation: false",
    "seccompProfile:",
    "type: RuntimeDefault",
    "drop:",
    "- ALL",
    "resources:",
    "requests:",
    "limits:",
    "NetworkPolicy",
    "policyTypes:",
    "- Ingress",
    "- Egress",
)

REQUIRED_KUBERNETES_ROLLOUT_MARKERS = (
    "replicas: 2",
    "self-correcting-agent-doctor",
    "--production",
    "readinessProbe:",
    "startupProbe:",
    "livenessProbe:",
    "path: /ready",
    "path: /health",
    "PodDisruptionBudget",
    "minAvailable: 1",
    "terminationGracePeriodSeconds: 45",
    "topologySpreadConstraints:",
    "CronJob",
    "self-correcting-agent-trace-prune",
    "--delete",
)

REQUIRED_SYSTEMD_SERVICE_MARKERS = (
    "ExecStartPre=",
    "self-correcting-agent-doctor --production",
    "ExecStart=",
    "self-correcting-agent-serve",
    "Restart=on-failure",
    "EnvironmentFile=",
    "TimeoutStopSec=45",
)

REQUIRED_SYSTEMD_SANDBOX_MARKERS = (
    "NoNewPrivileges=true",
    "PrivateTmp=true",
    "PrivateDevices=true",
    "ProtectSystem=strict",
    "ProtectHome=true",
    "ProtectKernelTunables=true",
    "ProtectKernelModules=true",
    "ProtectKernelLogs=true",
    "ProtectControlGroups=true",
    "CapabilityBoundingSet=",
    "LockPersonality=true",
    "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
    "RestrictSUIDSGID=true",
    "RestrictRealtime=true",
    "SystemCallArchitectures=native",
)

REQUIRED_SYSTEMD_RESOURCE_MARKERS = (
    "MemoryMax=1G",
    "CPUQuota=100%",
    "TasksMax=64",
)

REQUIRED_SYSTEMD_TRACE_STATE_MARKERS = (
    "StateDirectory=self-correcting-agent",
    "ReadWritePaths=/var/lib/self-correcting-agent",
    "UMask=0077",
    "--trace-dir /var/lib/self-correcting-agent/traces",
)

REQUIRED_INTERNAL_CLIENT_COMMAND_MARKERS = (
    "run_parser = subparsers.add_parser",
    "resume_parser = subparsers.add_parser",
    "approvals_parser = subparsers.add_parser",
    "approval_summary_parser = subparsers.add_parser",
    "policy_parser = subparsers.add_parser",
    "list_parser = subparsers.add_parser",
    "summary_parser = subparsers.add_parser",
    '"run"',
    '"resume"',
    '"approvals"',
    '"approval-summary"',
    '"policy"',
    '"list-runs"',
    '"summary"',
)

REQUIRED_INTERNAL_CLIENT_ROUTE_MARKERS = (
    '"/runtime/run"',
    '"/runtime/resume"',
    '"/runtime/policy"',
    '"/runtime/approvals?',
    '"/runtime/approvals/summary"',
    '"/runtime/runs?',
    '"/runtime/runs/summary"',
)

REQUIRED_INTERNAL_CLIENT_AUTH_MARKERS = (
    "Authorization",
    "Bearer",
    "SELF_CORRECTING_CLIENT_BASE_URL",
    "SELF_CORRECTING_CLIENT_TOKEN",
)

REQUIRED_INTERNAL_CLIENT_AUDIT_MARKERS = (
    "Idempotency-Key",
    "approved_action_ids",
    "auth_subject",
    "resumed_by_auth_subject",
)

REQUIRED_INTERNAL_CLIENT_POLICY_FILTER_MARKERS = (
    "effective_tool_policy",
    "effective_tool_policy_filter",
    "--tool",
    "--approval-required",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate JSON production readiness artifact evidence.",
    )
    parser.add_argument(
        "--provider-smoke-evidence",
        default="",
        help="Optional JSON output captured from scripts/smoke_real_llm_runtime.sh.",
    )
    parser.add_argument(
        "--require-provider-smoke",
        action="store_true",
        help="Fail when provider smoke evidence is missing or did not pass.",
    )
    parser.add_argument(
        "--staging-acceptance-evidence",
        default="",
        help="Optional JSON output captured from scripts/staging_acceptance.sh.",
    )
    parser.add_argument(
        "--require-staging-acceptance",
        action="store_true",
        help="Fail when staging acceptance evidence is missing or did not pass.",
    )
    parser.add_argument(
        "--observability-acceptance-evidence",
        default="",
        help="Optional JSON output captured from scripts/observability_acceptance.sh.",
    )
    parser.add_argument(
        "--require-observability-acceptance",
        action="store_true",
        help="Fail when observability acceptance evidence is missing or did not pass.",
    )
    parser.add_argument(
        "--internal-rollout-evidence",
        default="",
        help="Optional JSON output captured from scripts/internal_rollout_acceptance.py.",
    )
    parser.add_argument(
        "--require-internal-rollout",
        action="store_true",
        help="Fail when internal rollout sign-off evidence is missing or did not pass.",
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    _add_repo_src_to_import_path(repo_root)
    from self_correcting_langgraph_agent.ops.release_evidence import (
        _external_evidence_secret_findings,
    )

    artifacts = {
        relative_path: _artifact_record(repo_root / relative_path)
        for relative_path in REQUIRED_ARTIFACTS
    }
    missing = [
        relative_path
        for relative_path, record in artifacts.items()
        if not record["exists"]
    ]
    configuration = _configuration_record(repo_root)
    openapi_contract = _openapi_contract_record()
    observability = _observability_record(repo_root)
    deployment = _deployment_record(repo_root)
    integration = _integration_record(repo_root)
    provider_smoke = _provider_smoke_record(args.provider_smoke_evidence)
    staging_acceptance = _staging_acceptance_record(
        args.staging_acceptance_evidence
    )
    observability_acceptance = _observability_acceptance_record(
        args.observability_acceptance_evidence
    )
    internal_rollout = _internal_rollout_record(args.internal_rollout_evidence)
    evidence_secret_findings = _external_evidence_secret_findings(
        {
            "provider_smoke": (
                Path(args.provider_smoke_evidence)
                if args.provider_smoke_evidence
                else None
            ),
            "staging_acceptance": (
                Path(args.staging_acceptance_evidence)
                if args.staging_acceptance_evidence
                else None
            ),
            "observability_acceptance": (
                Path(args.observability_acceptance_evidence)
                if args.observability_acceptance_evidence
                else None
            ),
            "internal_rollout": (
                Path(args.internal_rollout_evidence)
                if args.internal_rollout_evidence
                else None
            ),
        }
    )
    failed_checks = []
    if missing:
        failed_checks.append("required_artifacts_missing")
    if configuration["env_example"]["status"] != "passed":
        failed_checks.append(f"env_example_{configuration['env_example']['status']}")
    if openapi_contract["status"] != "passed":
        failed_checks.append(f"openapi_contract_{openapi_contract['status']}")
    if observability["grafana_dashboard"]["status"] != "passed":
        failed_checks.append(
            f"grafana_dashboard_{observability['grafana_dashboard']['status']}"
        )
    if observability["prometheus_alert_rules"]["status"] != "passed":
        failed_checks.append(
            "prometheus_alert_rules_"
            f"{observability['prometheus_alert_rules']['status']}"
        )
    if observability["prometheus_servicemonitor"]["status"] != "passed":
        failed_checks.append(
            "prometheus_servicemonitor_"
            f"{observability['prometheus_servicemonitor']['status']}"
        )
    if deployment["kubernetes_manifest"]["status"] != "passed":
        failed_checks.append(
            f"kubernetes_manifest_{deployment['kubernetes_manifest']['status']}"
        )
    if deployment["systemd_unit"]["status"] != "passed":
        failed_checks.append(f"systemd_unit_{deployment['systemd_unit']['status']}")
    if integration["internal_runtime_client"]["status"] != "passed":
        failed_checks.append(
            "internal_runtime_client_"
            f"{integration['internal_runtime_client']['status']}"
        )
    if args.require_provider_smoke and provider_smoke["status"] != "passed":
        failed_checks.append(f"provider_smoke_{provider_smoke['status']}")
    if (
        args.require_staging_acceptance
        and staging_acceptance["status"] != "passed"
    ):
        failed_checks.append(
            f"staging_acceptance_{staging_acceptance['status']}"
        )
    if (
        args.require_observability_acceptance
        and observability_acceptance["status"] != "passed"
    ):
        failed_checks.append(
            f"observability_acceptance_{observability_acceptance['status']}"
        )
    if args.require_internal_rollout and internal_rollout["status"] != "passed":
        failed_checks.append(f"internal_rollout_{internal_rollout['status']}")
    if evidence_secret_findings:
        failed_checks.append("evidence_secret_detected")
    payload: Dict[str, Any] = {
        "status": "failed" if failed_checks else "passed",
        "summary": {
            "required_artifacts_checked": len(REQUIRED_ARTIFACTS),
            "missing_artifacts": missing,
            "failed_checks": failed_checks,
            "evidence_secret_findings": evidence_secret_findings,
        },
        "configuration": configuration,
        "deployment": deployment,
        "integration": integration,
        "openapi_contract": openapi_contract,
        "observability": observability,
        "provider_smoke": provider_smoke,
        "staging_acceptance": staging_acceptance,
        "observability_acceptance": observability_acceptance,
        "internal_rollout": internal_rollout,
        "artifacts": artifacts,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if failed_checks else 0


def _add_repo_src_to_import_path(repo_root: Path) -> None:
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def _artifact_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "exists": False,
            "bytes": "0",
        }
    content = path.read_bytes()
    return {
        "exists": True,
        "bytes": str(len(content)),
        "sha256": sha256(content).hexdigest(),
    }


def _configuration_record(repo_root: Path) -> Dict[str, Any]:
    return {
        "env_example": _env_example_record(repo_root / "deploy/env.example")
    }


def _env_example_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "service_keys_present": "false",
            "missing_service_keys": list(REQUIRED_ENV_SERVICE_KEYS),
            "runtime_keys_present": "false",
            "missing_runtime_keys": list(REQUIRED_ENV_RUNTIME_KEYS),
            "provider_keys_present": "false",
            "missing_provider_keys": list(REQUIRED_ENV_PROVIDER_KEYS),
        }
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        record = {
            "status": "invalid_text",
            "service_keys_present": "false",
            "missing_service_keys": list(REQUIRED_ENV_SERVICE_KEYS),
            "runtime_keys_present": "false",
            "missing_runtime_keys": list(REQUIRED_ENV_RUNTIME_KEYS),
            "provider_keys_present": "false",
            "missing_provider_keys": list(REQUIRED_ENV_PROVIDER_KEYS),
            "sha256": sha256(content).hexdigest(),
        }
        return record
    keys = _env_template_keys(text)
    missing_service = [key for key in REQUIRED_ENV_SERVICE_KEYS if key not in keys]
    missing_runtime = [key for key in REQUIRED_ENV_RUNTIME_KEYS if key not in keys]
    missing_provider = [key for key in REQUIRED_ENV_PROVIDER_KEYS if key not in keys]
    status = "passed"
    if missing_service:
        status = "missing_service_keys"
    if missing_runtime:
        status = "missing_runtime_keys"
    if missing_provider:
        status = "missing_provider_keys"
    return {
        "status": status,
        "key_count": str(len(keys)),
        "service_keys_present": str(not missing_service).lower(),
        "missing_service_keys": missing_service,
        "runtime_keys_present": str(not missing_runtime).lower(),
        "missing_runtime_keys": missing_runtime,
        "provider_keys_present": str(not missing_provider).lower(),
        "missing_provider_keys": missing_provider,
        "sha256": sha256(content).hexdigest(),
    }


def _env_template_keys(text: str) -> List[str]:
    keys = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _separator, _value = stripped.partition("=")
        keys.append(key)
    return keys


def _openapi_contract_record() -> Dict[str, Any]:
    try:
        from self_correcting_langgraph_agent.service.contract import service_openapi
    except Exception as exc:  # pragma: no cover - defensive audit guard
        return {
            "status": "unavailable",
            "error": str(exc),
        }
    try:
        payload = service_openapi()
    except Exception as exc:  # pragma: no cover - defensive audit guard
        return {
            "status": "failed",
            "error": str(exc),
        }
    paths = payload.get("paths")
    if not isinstance(paths, dict):
        return {
            "status": "invalid",
            "error": "paths must be an object",
        }
    operation_ids = _openapi_operation_ids(paths)
    duplicate_operation_ids = sorted(
        operation_id
        for operation_id in set(operation_ids)
        if operation_ids.count(operation_id) > 1
    )
    missing_required_paths = [
        path for path in REQUIRED_OPENAPI_PATHS if path not in paths
    ]
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    status = "passed"
    if duplicate_operation_ids:
        status = "duplicate_operation_ids"
    if missing_required_paths:
        status = "missing_required_paths"
    return {
        "status": status,
        "openapi": str(payload.get("openapi", "")),
        "path_count": str(len(paths)),
        "operation_id_count": str(len(operation_ids)),
        "required_paths_present": str(not missing_required_paths).lower(),
        "missing_required_paths": missing_required_paths,
        "duplicate_operation_ids": duplicate_operation_ids,
        "sha256": sha256(content).hexdigest(),
    }


def _openapi_operation_ids(paths: Dict[str, Any]) -> List[str]:
    operation_ids = []
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and operation.get("operationId"):
                operation_ids.append(str(operation["operationId"]))
    return operation_ids


def _observability_record(repo_root: Path) -> Dict[str, Any]:
    return {
        "grafana_dashboard": _grafana_dashboard_record(
            repo_root / "deploy/grafana/self-correcting-agent-dashboard.json"
        ),
        "prometheus_alert_rules": _prometheus_alert_rules_record(
            repo_root / "deploy/prometheus/self-correcting-agent-rules.yaml"
        ),
        "prometheus_servicemonitor": _prometheus_servicemonitor_record(
            repo_root / "deploy/prometheus/self-correcting-agent-servicemonitor.yaml"
        ),
    }


def _grafana_dashboard_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "required_metrics_present": "false",
            "missing_required_metrics": list(REQUIRED_GRAFANA_METRICS),
        }
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_json",
            "required_metrics_present": "false",
            "missing_required_metrics": list(REQUIRED_GRAFANA_METRICS),
            "sha256": sha256(content).hexdigest(),
        }
    panels = payload.get("panels")
    if not isinstance(panels, list):
        return {
            "status": "invalid",
            "title": str(payload.get("title", "")),
            "panel_count": "0",
            "required_metrics_present": "false",
            "missing_required_metrics": list(REQUIRED_GRAFANA_METRICS),
            "sha256": sha256(content).hexdigest(),
        }
    expressions = "\n".join(_grafana_panel_expressions(panels))
    missing_metrics = [
        metric for metric in REQUIRED_GRAFANA_METRICS if metric not in expressions
    ]
    return {
        "status": "passed" if not missing_metrics else "missing_required_metrics",
        "title": str(payload.get("title", "")),
        "panel_count": str(len(panels)),
        "required_metrics_present": str(not missing_metrics).lower(),
        "missing_required_metrics": missing_metrics,
        "sha256": sha256(content).hexdigest(),
    }


def _grafana_panel_expressions(panels: List[Any]) -> List[str]:
    expressions = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        targets = panel.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, dict) and target.get("expr"):
                expressions.append(str(target["expr"]))
    return expressions


def _prometheus_alert_rules_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "alert_count": "0",
            "required_alerts_present": "false",
            "missing_required_alerts": list(REQUIRED_PROMETHEUS_ALERTS),
            "required_metrics_present": "false",
            "missing_required_metrics": list(REQUIRED_PROMETHEUS_RULE_METRICS),
        }
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "invalid_text",
            "alert_count": "0",
            "required_alerts_present": "false",
            "missing_required_alerts": list(REQUIRED_PROMETHEUS_ALERTS),
            "required_metrics_present": "false",
            "missing_required_metrics": list(REQUIRED_PROMETHEUS_RULE_METRICS),
            "sha256": sha256(content).hexdigest(),
        }
    alert_names = _prometheus_alert_names(text)
    missing_alerts = [
        alert for alert in REQUIRED_PROMETHEUS_ALERTS if alert not in alert_names
    ]
    missing_metrics = [
        metric for metric in REQUIRED_PROMETHEUS_RULE_METRICS if metric not in text
    ]
    status = "passed"
    if missing_alerts:
        status = "missing_required_alerts"
    if missing_metrics:
        status = "missing_required_metrics"
    return {
        "status": status,
        "alert_count": str(len(alert_names)),
        "required_alerts_present": str(not missing_alerts).lower(),
        "missing_required_alerts": missing_alerts,
        "required_metrics_present": str(not missing_metrics).lower(),
        "missing_required_metrics": missing_metrics,
        "sha256": sha256(content).hexdigest(),
    }


def _prometheus_alert_names(text: str) -> List[str]:
    names = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- alert:"):
            names.append(stripped.removeprefix("- alert:").strip())
    return names


def _prometheus_servicemonitor_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "scrape_target_present": "false",
            "selector_present": "false",
            "missing_scrape_markers": list(REQUIRED_SERVICEMONITOR_SCRAPE_MARKERS),
        }
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "invalid_text",
            "scrape_target_present": "false",
            "selector_present": "false",
            "missing_scrape_markers": list(REQUIRED_SERVICEMONITOR_SCRAPE_MARKERS),
            "sha256": sha256(content).hexdigest(),
        }
    missing_markers = [
        marker for marker in REQUIRED_SERVICEMONITOR_SCRAPE_MARKERS if marker not in text
    ]
    scrape_target_present = all(
        marker in text
        for marker in (
            "port: http",
            "path: /metrics.prom",
            "interval: 30s",
            "scrapeTimeout: 5s",
        )
    )
    selector_present = all(
        marker in text
        for marker in (
            "selector:",
            "matchLabels:",
            "app.kubernetes.io/name: self-correcting-agent",
        )
    )
    return {
        "status": "passed" if not missing_markers else "missing_scrape_markers",
        "scrape_target_present": str(scrape_target_present).lower(),
        "selector_present": str(selector_present).lower(),
        "missing_scrape_markers": missing_markers,
        "sha256": sha256(content).hexdigest(),
    }


def _deployment_record(repo_root: Path) -> Dict[str, Any]:
    return {
        "kubernetes_manifest": _kubernetes_manifest_record(
            repo_root / "deploy/kubernetes/self-correcting-agent.yaml"
        ),
        "systemd_unit": _systemd_unit_record(
            repo_root / "deploy/systemd/self-correcting-agent.service"
        ),
    }


def _kubernetes_manifest_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {
            "status": "missing",
            "resource_count": "0",
            "required_resources_present": "false",
            "missing_required_resources": list(REQUIRED_KUBERNETES_RESOURCES),
            "hardening_present": "false",
            "missing_hardening_markers": list(REQUIRED_KUBERNETES_HARDENING_MARKERS),
            "rollout_controls_present": "false",
            "missing_rollout_markers": list(REQUIRED_KUBERNETES_ROLLOUT_MARKERS),
        }
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": "invalid_text",
            "resource_count": "0",
            "required_resources_present": "false",
            "missing_required_resources": list(REQUIRED_KUBERNETES_RESOURCES),
            "hardening_present": "false",
            "missing_hardening_markers": list(REQUIRED_KUBERNETES_HARDENING_MARKERS),
            "rollout_controls_present": "false",
            "missing_rollout_markers": list(REQUIRED_KUBERNETES_ROLLOUT_MARKERS),
            "sha256": sha256(content).hexdigest(),
        }
    resources = _kubernetes_resource_kinds(text)
    missing_resources = [
        resource for resource in REQUIRED_KUBERNETES_RESOURCES if resource not in resources
    ]
    missing_hardening = [
        marker for marker in REQUIRED_KUBERNETES_HARDENING_MARKERS if marker not in text
    ]
    missing_rollout = [
        marker for marker in REQUIRED_KUBERNETES_ROLLOUT_MARKERS if marker not in text
    ]
    status = "passed"
    if missing_resources:
        status = "missing_required_resources"
    if missing_hardening:
        status = "missing_hardening_markers"
    if missing_rollout:
        status = "missing_rollout_markers"
    return {
        "status": status,
        "resource_count": str(len(resources)),
        "required_resources_present": str(not missing_resources).lower(),
        "missing_required_resources": missing_resources,
        "hardening_present": str(not missing_hardening).lower(),
        "missing_hardening_markers": missing_hardening,
        "rollout_controls_present": str(not missing_rollout).lower(),
        "missing_rollout_markers": missing_rollout,
        "sha256": sha256(content).hexdigest(),
    }


def _kubernetes_resource_kinds(text: str) -> List[str]:
    kinds = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("kind:"):
            kinds.append(stripped.removeprefix("kind:").strip())
    return kinds


def _systemd_unit_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return _missing_systemd_unit_record("missing")
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        record = _missing_systemd_unit_record("invalid_text")
        record["sha256"] = sha256(content).hexdigest()
        return record
    missing_service = [
        marker for marker in REQUIRED_SYSTEMD_SERVICE_MARKERS if marker not in text
    ]
    missing_sandbox = [
        marker for marker in REQUIRED_SYSTEMD_SANDBOX_MARKERS if marker not in text
    ]
    missing_resource = [
        marker for marker in REQUIRED_SYSTEMD_RESOURCE_MARKERS if marker not in text
    ]
    missing_trace_state = [
        marker for marker in REQUIRED_SYSTEMD_TRACE_STATE_MARKERS if marker not in text
    ]
    status = "passed"
    if missing_service:
        status = "missing_service_controls"
    if missing_sandbox:
        status = "missing_sandboxing_markers"
    if missing_resource:
        status = "missing_resource_controls"
    if missing_trace_state:
        status = "missing_trace_state_markers"
    return {
        "status": status,
        "service_controls_present": str(not missing_service).lower(),
        "missing_service_markers": missing_service,
        "sandboxing_present": str(not missing_sandbox).lower(),
        "missing_sandboxing_markers": missing_sandbox,
        "resource_controls_present": str(not missing_resource).lower(),
        "missing_resource_markers": missing_resource,
        "trace_state_boundary_present": str(not missing_trace_state).lower(),
        "missing_trace_state_markers": missing_trace_state,
        "sha256": sha256(content).hexdigest(),
    }


def _missing_systemd_unit_record(status: str) -> Dict[str, Any]:
    return {
        "status": status,
        "service_controls_present": "false",
        "missing_service_markers": list(REQUIRED_SYSTEMD_SERVICE_MARKERS),
        "sandboxing_present": "false",
        "missing_sandboxing_markers": list(REQUIRED_SYSTEMD_SANDBOX_MARKERS),
        "resource_controls_present": "false",
        "missing_resource_markers": list(REQUIRED_SYSTEMD_RESOURCE_MARKERS),
        "trace_state_boundary_present": "false",
        "missing_trace_state_markers": list(REQUIRED_SYSTEMD_TRACE_STATE_MARKERS),
    }


def _integration_record(repo_root: Path) -> Dict[str, Any]:
    return {
        "internal_runtime_client": _internal_runtime_client_record(
            repo_root / "examples/internal_runtime_client.py"
        )
    }


def _internal_runtime_client_record(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return _missing_internal_client_record("missing")
    content = path.read_bytes()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        record = _missing_internal_client_record("invalid_text")
        record["sha256"] = sha256(content).hexdigest()
        return record
    missing_commands = [
        marker for marker in REQUIRED_INTERNAL_CLIENT_COMMAND_MARKERS if marker not in text
    ]
    missing_routes = [
        marker for marker in REQUIRED_INTERNAL_CLIENT_ROUTE_MARKERS if marker not in text
    ]
    missing_auth = [
        marker for marker in REQUIRED_INTERNAL_CLIENT_AUTH_MARKERS if marker not in text
    ]
    missing_audit = [
        marker for marker in REQUIRED_INTERNAL_CLIENT_AUDIT_MARKERS if marker not in text
    ]
    missing_policy_filters = [
        marker
        for marker in REQUIRED_INTERNAL_CLIENT_POLICY_FILTER_MARKERS
        if marker not in text
    ]
    secret_markers = [marker for marker in ("sk-", "ricent" + ".com") if marker in text]
    status = "passed"
    if missing_commands:
        status = "missing_commands"
    if missing_routes:
        status = "missing_runtime_routes"
    if missing_auth:
        status = "missing_auth_markers"
    if missing_audit:
        status = "missing_audit_markers"
    if missing_policy_filters:
        status = "missing_policy_filter_markers"
    if secret_markers:
        status = "contains_secret_markers"
    return {
        "status": status,
        "commands_present": str(not missing_commands).lower(),
        "missing_command_markers": missing_commands,
        "runtime_routes_present": str(not missing_routes).lower(),
        "missing_route_markers": missing_routes,
        "auth_present": str(not missing_auth).lower(),
        "missing_auth_markers": missing_auth,
        "idempotency_present": str("Idempotency-Key" in text).lower(),
        "audit_fields_present": str(not missing_audit).lower(),
        "missing_audit_markers": missing_audit,
        "effective_policy_filtering_present": str(
            not missing_policy_filters
        ).lower(),
        "missing_policy_filter_markers": missing_policy_filters,
        "secret_markers_present": str(bool(secret_markers)).lower(),
        "secret_markers": secret_markers,
        "sha256": sha256(content).hexdigest(),
    }


def _missing_internal_client_record(status: str) -> Dict[str, Any]:
    return {
        "status": status,
        "commands_present": "false",
        "missing_command_markers": list(REQUIRED_INTERNAL_CLIENT_COMMAND_MARKERS),
        "runtime_routes_present": "false",
        "missing_route_markers": list(REQUIRED_INTERNAL_CLIENT_ROUTE_MARKERS),
        "auth_present": "false",
        "missing_auth_markers": list(REQUIRED_INTERNAL_CLIENT_AUTH_MARKERS),
        "idempotency_present": "false",
        "audit_fields_present": "false",
        "missing_audit_markers": list(REQUIRED_INTERNAL_CLIENT_AUDIT_MARKERS),
        "effective_policy_filtering_present": "false",
        "missing_policy_filter_markers": list(
            REQUIRED_INTERNAL_CLIENT_POLICY_FILTER_MARKERS
        ),
        "secret_markers_present": "false",
        "secret_markers": [],
    }


def _provider_smoke_record(evidence_path: str) -> Dict[str, Any]:
    if not evidence_path:
        return {
            "status": "not_provided",
            "required_for_provider_backed_production": True,
        }
    path = Path(evidence_path)
    if not path.is_file():
        return {
            "status": "missing",
            "required_for_provider_backed_production": True,
            "evidence_path": evidence_path,
        }
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_json",
            "required_for_provider_backed_production": True,
            "evidence_path": evidence_path,
            "sha256": sha256(content).hexdigest(),
        }
    status = str(payload.get("status", "missing_status"))
    from self_correcting_langgraph_agent.ops.release_evidence import (
        _provider_smoke_missing_fields,
    )

    missing_fields = (
        _provider_smoke_missing_fields(payload) if status == "passed" else []
    )
    if missing_fields:
        status = "invalid_evidence"
    run_ids = {
        key: str(payload.get(key, ""))
        for key in (
            "approval_run_id",
            "cli_run_id",
            "http_run_id",
            "resumed_run_id",
        )
        if payload.get(key)
    }
    return {
        "status": status,
        "required_for_provider_backed_production": True,
        "evidence_path": evidence_path,
        "bytes": str(len(content)),
        "sha256": sha256(content).hexdigest(),
        "run_ids": run_ids,
        "evidence_schema_version": str(
            payload.get("evidence_schema_version", "")
        ),
        "provider_snapshot": _string_map(payload.get("provider_snapshot", {})),
        "capability_checks": _string_map(payload.get("capability_checks", {})),
        "runtime_effective_tool_policy_sha256": str(
            payload.get("runtime_effective_tool_policy_sha256", "")
        ),
        "missing_fields": missing_fields,
    }


def _staging_acceptance_record(evidence_path: str) -> Dict[str, Any]:
    if not evidence_path:
        return {
            "status": "not_provided",
            "required_for_internal_production": True,
        }
    path = Path(evidence_path)
    if not path.is_file():
        return {
            "status": "missing",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
        }
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_json",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
            "sha256": sha256(content).hexdigest(),
        }
    status = str(payload.get("status", "missing_status"))
    missing_fields = (
        _staging_acceptance_missing_fields(payload) if status == "passed" else []
    )
    if missing_fields:
        status = "invalid_evidence"
    return {
        "evidence_schema_version": str(
            payload.get("evidence_schema_version", "")
        ),
        "status": status,
        "required_for_internal_production": True,
        "evidence_path": evidence_path,
        "bytes": str(len(content)),
        "sha256": sha256(content).hexdigest(),
        "base_url_host": str(payload.get("base_url_host", "")),
        "health_status": str(payload.get("health_status", "")),
        "ready_status": str(payload.get("ready_status", "")),
        "runtime_run_id": str(payload.get("runtime_run_id", "")),
        "auth_subject": str(payload.get("auth_subject", "")),
        "runtime_policy_source": str(payload.get("runtime_policy_source", "")),
        "runtime_effective_tool_policy_count": str(
            payload.get("runtime_effective_tool_policy_count", "")
        ),
        "runtime_effective_tool_policy_sha256": str(
            payload.get("runtime_effective_tool_policy_sha256", "")
        ),
        "runtime_note_allowed": str(payload.get("runtime_note_allowed", "")),
        "runtime_http_request_approval_required": str(
            payload.get("runtime_http_request_approval_required", "")
        ),
        "runtime_run_status": str(payload.get("runtime_run_status", "")),
        "runtime_timeline_event_count": str(
            payload.get("runtime_timeline_event_count", "")
        ),
        "runtime_summary_run_count": str(
            payload.get("runtime_summary_run_count", "")
        ),
        "metrics_trace_persistence": str(
            payload.get("metrics_trace_persistence", "")
        ),
        "metrics_runtime_runs_total": str(
            payload.get("metrics_runtime_runs_total", "")
        ),
        "missing_fields": missing_fields,
    }


def _observability_acceptance_record(evidence_path: str) -> Dict[str, Any]:
    if not evidence_path:
        return {
            "status": "not_provided",
            "required_for_internal_production": True,
        }
    path = Path(evidence_path)
    if not path.is_file():
        return {
            "status": "missing",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
        }
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_json",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
            "sha256": sha256(content).hexdigest(),
        }
    status = str(payload.get("status", "missing_status"))
    missing_fields = (
        _observability_acceptance_missing_fields(payload)
        if status == "passed"
        else []
    )
    if missing_fields:
        status = "invalid_evidence"
    return {
        "evidence_schema_version": str(
            payload.get("evidence_schema_version", "")
        ),
        "status": status,
        "required_for_internal_production": True,
        "evidence_path": evidence_path,
        "bytes": str(len(content)),
        "sha256": sha256(content).hexdigest(),
        "base_url_host": str(payload.get("base_url_host", "")),
        "metrics_endpoint": str(payload.get("metrics_endpoint", "")),
        "metrics_status": str(payload.get("metrics_status", "")),
        "required_metrics_present": str(
            payload.get("required_metrics_present", "")
        ),
        "required_metric_count": str(payload.get("required_metric_count", "")),
        "metrics_sha256": str(payload.get("metrics_sha256", "")),
        "grafana_dashboard_status": str(
            payload.get("grafana_dashboard_status", "")
        ),
        "grafana_dashboard_sha256": str(
            payload.get("grafana_dashboard_sha256", "")
        ),
        "prometheus_rules_status": str(
            payload.get("prometheus_rules_status", "")
        ),
        "prometheus_rules_sha256": str(
            payload.get("prometheus_rules_sha256", "")
        ),
        "prometheus_query_status": str(
            payload.get("prometheus_query_status", "")
        ),
        "prometheus_result_count": str(
            payload.get("prometheus_result_count", "")
        ),
        "missing_fields": missing_fields,
    }


def _internal_rollout_record(evidence_path: str) -> Dict[str, Any]:
    if not evidence_path:
        return {
            "status": "not_provided",
            "required_for_internal_production": True,
        }
    path = Path(evidence_path)
    if not path.is_file():
        return {
            "status": "missing",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
        }
    content = path.read_bytes()
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "status": "invalid_json",
            "required_for_internal_production": True,
            "evidence_path": evidence_path,
            "sha256": sha256(content).hexdigest(),
        }
    status = str(payload.get("status", "missing_status"))
    missing_fields = (
        _internal_rollout_missing_fields(payload) if status == "passed" else []
    )
    if missing_fields:
        status = "invalid_evidence"
    return {
        "evidence_schema_version": str(
            payload.get("evidence_schema_version", "")
        ),
        "status": status,
        "required_for_internal_production": True,
        "evidence_path": evidence_path,
        "bytes": str(len(content)),
        "sha256": sha256(content).hexdigest(),
        "rollout_id": str(payload.get("rollout_id", "")),
        "release_version": str(payload.get("release_version", "")),
        "environment": str(payload.get("environment", "")),
        "signed_off_at_utc": str(payload.get("signed_off_at_utc", "")),
        "runtime_effective_tool_policy_sha256": str(
            payload.get("runtime_effective_tool_policy_sha256", "")
        ),
        "required_roles_present": str(payload.get("required_roles_present", "")),
        "required_checks_passed": str(payload.get("required_checks_passed", "")),
        "approver_role_count": str(payload.get("approver_role_count", "")),
        "expected_release_version": str(
            payload.get("expected_release_version", "")
        ),
        "version_matches": str(payload.get("version_matches", "")),
        "expected_environment": str(payload.get("expected_environment", "")),
        "environment_matches": str(payload.get("environment_matches", "")),
        "evidence_sha256": str(payload.get("sha256", "")),
        "missing_fields": missing_fields,
    }


def _string_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, (str, int, float, bool))
    }


if __name__ == "__main__":
    raise SystemExit(main())
