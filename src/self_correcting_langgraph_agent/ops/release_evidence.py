from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from self_correcting_langgraph_agent import __version__
from self_correcting_langgraph_agent.ops.release_manifest import verify_release_manifest

PACKAGE_NAME = "self-correcting-langgraph-agent"
SECRET_LIKE_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)
SECRET_KEY_ALLOWLIST = {
    "llm_api_key_configured",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9:_-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._:/+=-]{6,}"),
    re.compile(r"(?i)\bauthorization\s*:\s*[A-Za-z0-9._:/+=-]{6,}"),
)
REQUIRED_PROVIDER_SMOKE_RUN_IDS = (
    "approval_run_id",
    "cli_run_id",
    "http_run_id",
    "resumed_run_id",
)
REQUIRED_PROVIDER_SMOKE_CAPABILITIES = (
    "approval_resume",
    "cli_runtime",
    "http_runtime",
    "metrics",
    "timeline",
    "trace_status",
)
REQUIRED_PROVIDER_SMOKE_SNAPSHOT_FIELDS = (
    "llm_api_key_configured",
    "llm_base_url_host",
    "llm_model",
    "llm_provider",
)
REQUIRED_STAGING_ACCEPTANCE_FIELDS = (
    "auth_subject",
    "base_url_host",
    "runtime_policy_source",
    "runtime_run_id",
)
REQUIRED_STAGING_ACCEPTANCE_VALUES = {
    "health_status": "ok",
    "metrics_trace_persistence": "enabled",
    "ready_status": "ready",
    "runtime_http_request_approval_required": "true",
    "runtime_note_allowed": "true",
    "runtime_run_status": "done",
}
REQUIRED_STAGING_ACCEPTANCE_POSITIVE_INTS = (
    "metrics_runtime_runs_total",
    "runtime_effective_tool_policy_count",
    "runtime_summary_run_count",
    "runtime_timeline_event_count",
)
REQUIRED_OBSERVABILITY_ACCEPTANCE_FIELDS = (
    "base_url_host",
    "metrics_endpoint",
)
REQUIRED_OBSERVABILITY_ACCEPTANCE_VALUES = {
    "grafana_dashboard_status": "passed",
    "metrics_status": "200",
    "prometheus_rules_status": "passed",
    "required_metrics_present": "true",
}
REQUIRED_OBSERVABILITY_ACCEPTANCE_SHA_FIELDS = (
    "grafana_dashboard_sha256",
    "metrics_sha256",
    "prometheus_rules_sha256",
)
REQUIRED_INTERNAL_ROLLOUT_FIELDS = (
    "environment",
    "expected_environment",
    "expected_release_version",
    "release_version",
    "rollout_id",
    "signed_off_at_utc",
)
REQUIRED_INTERNAL_ROLLOUT_TRUE_FIELDS = (
    "environment_matches",
    "required_checks_passed",
    "required_roles_present",
    "version_matches",
)


def build_release_evidence(
    *,
    run_checks_exit_code: int,
    readiness_audit_path: Path,
    release_manifest_path: Optional[Path] = None,
    provider_smoke_evidence_path: Optional[Path] = None,
    staging_acceptance_evidence_path: Optional[Path] = None,
    observability_acceptance_evidence_path: Optional[Path] = None,
    internal_rollout_evidence_path: Optional[Path] = None,
    require_provider_smoke: bool = False,
    require_staging_acceptance: bool = False,
    require_observability_acceptance: bool = False,
    require_internal_rollout: bool = False,
) -> Dict[str, Any]:
    readiness_audit = _read_json_file(readiness_audit_path)
    release_manifest = (
        verify_release_manifest(release_manifest_path)
        if release_manifest_path is not None
        else {"status": "not_provided"}
    )
    provider_smoke = (
        _provider_smoke_record(provider_smoke_evidence_path)
        if provider_smoke_evidence_path is not None
        else {"status": "not_provided"}
    )
    staging_acceptance = (
        _staging_acceptance_record(staging_acceptance_evidence_path)
        if staging_acceptance_evidence_path is not None
        else {"status": "not_provided"}
    )
    observability_acceptance = (
        _observability_acceptance_record(observability_acceptance_evidence_path)
        if observability_acceptance_evidence_path is not None
        else {"status": "not_provided"}
    )
    internal_rollout = (
        _internal_rollout_record(internal_rollout_evidence_path)
        if internal_rollout_evidence_path is not None
        else {"status": "not_provided"}
    )
    evidence_secret_findings = _external_evidence_secret_findings(
        {
            "provider_smoke": provider_smoke_evidence_path,
            "staging_acceptance": staging_acceptance_evidence_path,
            "observability_acceptance": observability_acceptance_evidence_path,
            "internal_rollout": internal_rollout_evidence_path,
        }
    )
    failed_checks = _failed_checks(
        run_checks_exit_code=run_checks_exit_code,
        readiness_audit=readiness_audit,
        release_manifest=release_manifest,
        provider_smoke=provider_smoke,
        staging_acceptance=staging_acceptance,
        observability_acceptance=observability_acceptance,
        internal_rollout=internal_rollout,
        evidence_secret_findings=evidence_secret_findings,
        require_provider_smoke=require_provider_smoke,
        require_staging_acceptance=require_staging_acceptance,
        require_observability_acceptance=require_observability_acceptance,
        require_internal_rollout=require_internal_rollout,
    )
    evidence_files = {
        "readiness_audit": _file_record(readiness_audit_path),
    }
    if release_manifest_path is not None:
        evidence_files["release_manifest"] = _file_record(release_manifest_path)
    if provider_smoke_evidence_path is not None:
        evidence_files["provider_smoke"] = _file_record(provider_smoke_evidence_path)
    if staging_acceptance_evidence_path is not None:
        evidence_files["staging_acceptance"] = _file_record(
            staging_acceptance_evidence_path
        )
    if observability_acceptance_evidence_path is not None:
        evidence_files["observability_acceptance"] = _file_record(
            observability_acceptance_evidence_path
        )
    if internal_rollout_evidence_path is not None:
        evidence_files["internal_rollout"] = _file_record(
            internal_rollout_evidence_path
        )

    return {
        "package": PACKAGE_NAME,
        "version": __version__,
        "generated_at_utc": _utc_timestamp(),
        "status": "blocked" if failed_checks else "ready",
        "summary": {
            "failed_checks": failed_checks,
            "evidence_file_count": str(len(evidence_files)),
            "evidence_secret_findings": evidence_secret_findings,
        },
        "run_checks": _run_checks_record(run_checks_exit_code),
        "readiness_audit": _readiness_audit_record(readiness_audit),
        "release_manifest": release_manifest,
        "provider_smoke": provider_smoke,
        "staging_acceptance": staging_acceptance,
        "observability_acceptance": observability_acceptance,
        "internal_rollout": internal_rollout,
        "evidence_files": evidence_files,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate a redacted JSON release evidence bundle."
    )
    parser.add_argument(
        "--run-checks-exit-code",
        required=True,
        type=int,
        help="Exit code from scripts/run_checks.sh.",
    )
    parser.add_argument(
        "--readiness-audit",
        required=True,
        metavar="PATH",
        help="JSON output from scripts/production_readiness_audit.py.",
    )
    parser.add_argument(
        "--release-manifest",
        default="",
        metavar="PATH",
        help="Verified release manifest JSON generated by release_manifest.",
    )
    parser.add_argument(
        "--provider-smoke-evidence",
        default="",
        metavar="PATH",
        help="Redacted JSON output from scripts/smoke_real_llm_runtime.sh.",
    )
    parser.add_argument(
        "--require-provider-smoke",
        action="store_true",
        help="Block release evidence when provider smoke evidence is missing.",
    )
    parser.add_argument(
        "--staging-acceptance-evidence",
        default="",
        metavar="PATH",
        help="Redacted JSON output from scripts/staging_acceptance.sh.",
    )
    parser.add_argument(
        "--require-staging-acceptance",
        action="store_true",
        help="Block release evidence when staging acceptance evidence is missing.",
    )
    parser.add_argument(
        "--observability-acceptance-evidence",
        default="",
        metavar="PATH",
        help="Redacted JSON output from scripts/observability_acceptance.sh.",
    )
    parser.add_argument(
        "--require-observability-acceptance",
        action="store_true",
        help="Block release evidence when observability acceptance evidence is missing.",
    )
    parser.add_argument(
        "--internal-rollout-evidence",
        default="",
        metavar="PATH",
        help="Redacted JSON output from scripts/internal_rollout_acceptance.py.",
    )
    parser.add_argument(
        "--require-internal-rollout",
        action="store_true",
        help="Block release evidence when internal rollout sign-off evidence is missing.",
    )
    parser.add_argument("--output", default="", metavar="PATH", help="Write bundle JSON to PATH.")
    args = parser.parse_args(argv)

    try:
        payload = build_release_evidence(
            run_checks_exit_code=args.run_checks_exit_code,
            readiness_audit_path=Path(args.readiness_audit),
            release_manifest_path=Path(args.release_manifest) if args.release_manifest else None,
            provider_smoke_evidence_path=(
                Path(args.provider_smoke_evidence) if args.provider_smoke_evidence else None
            ),
            staging_acceptance_evidence_path=(
                Path(args.staging_acceptance_evidence)
                if args.staging_acceptance_evidence
                else None
            ),
            observability_acceptance_evidence_path=(
                Path(args.observability_acceptance_evidence)
                if args.observability_acceptance_evidence
                else None
            ),
            internal_rollout_evidence_path=(
                Path(args.internal_rollout_evidence)
                if args.internal_rollout_evidence
                else None
            ),
            require_provider_smoke=args.require_provider_smoke,
            require_staging_acceptance=args.require_staging_acceptance,
            require_observability_acceptance=args.require_observability_acceptance,
            require_internal_rollout=args.require_internal_rollout,
        )
        output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
    except (json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))
    print(output, end="")
    if payload["status"] != "ready":
        raise SystemExit(1)


def _failed_checks(
    *,
    run_checks_exit_code: int,
    readiness_audit: Dict[str, Any],
    release_manifest: Dict[str, Any],
    provider_smoke: Dict[str, Any],
    staging_acceptance: Dict[str, Any],
    observability_acceptance: Dict[str, Any],
    internal_rollout: Dict[str, Any],
    evidence_secret_findings: List[Dict[str, str]],
    require_provider_smoke: bool,
    require_staging_acceptance: bool,
    require_observability_acceptance: bool,
    require_internal_rollout: bool,
) -> List[str]:
    failed = []
    if run_checks_exit_code != 0:
        failed.append("run_checks_failed")
    if str(readiness_audit.get("status", "")) != "passed":
        failed.append("readiness_audit_failed")
    if release_manifest["status"] not in {"verified", "not_provided"}:
        failed.append("release_manifest_failed")
    if provider_smoke["status"] not in {"passed", "not_provided"}:
        failed.append("provider_smoke_failed")
    if require_provider_smoke and provider_smoke["status"] != "passed":
        failed.append(f"provider_smoke_{provider_smoke['status']}")
    if staging_acceptance["status"] not in {"passed", "not_provided"}:
        failed.append("staging_acceptance_failed")
    if require_staging_acceptance and staging_acceptance["status"] != "passed":
        failed.append(f"staging_acceptance_{staging_acceptance['status']}")
    if observability_acceptance["status"] not in {"passed", "not_provided"}:
        failed.append("observability_acceptance_failed")
    if (
        require_observability_acceptance
        and observability_acceptance["status"] != "passed"
    ):
        failed.append(
            f"observability_acceptance_{observability_acceptance['status']}"
        )
    if internal_rollout["status"] not in {"passed", "not_provided"}:
        failed.append("internal_rollout_failed")
    if require_internal_rollout and internal_rollout["status"] != "passed":
        failed.append(f"internal_rollout_{internal_rollout['status']}")
    if evidence_secret_findings:
        failed.append("evidence_secret_detected")
    return failed


def _run_checks_record(exit_code: int) -> Dict[str, str]:
    return {
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": str(exit_code),
    }


def _readiness_audit_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary", {})
    return {
        "status": str(payload.get("status", "unknown")),
        "failed_checks": _string_list(summary.get("failed_checks", [])),
        "missing_artifacts": _string_list(summary.get("missing_artifacts", [])),
    }


def _provider_smoke_record(path: Path) -> Dict[str, Any]:
    payload = _read_json_file(path)
    status = str(payload.get("status", "unknown"))
    missing_fields = (
        _provider_smoke_missing_fields(payload) if status == "passed" else []
    )
    if missing_fields:
        status = "invalid_evidence"
    return {
        "status": status,
        "evidence_schema_version": str(
            payload.get("evidence_schema_version", "")
        ),
        "provider_snapshot": _string_map(payload.get("provider_snapshot", {})),
        "capability_checks": _string_map(payload.get("capability_checks", {})),
        "runtime_effective_tool_policy_sha256": str(
            payload.get("runtime_effective_tool_policy_sha256", "")
        ),
        "run_ids": {
            key: str(payload.get(key, ""))
            for key in (
                "approval_run_id",
                "cli_run_id",
                "http_run_id",
                "resumed_run_id",
            )
            if str(payload.get(key, "")).strip()
        },
        "missing_fields": missing_fields,
    }


def _staging_acceptance_record(path: Path) -> Dict[str, Any]:
    payload = _read_json_file(path)
    status = str(payload.get("status", "unknown"))
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


def _observability_acceptance_record(path: Path) -> Dict[str, Any]:
    payload = _read_json_file(path)
    status = str(payload.get("status", "unknown"))
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
        "base_url_host": str(payload.get("base_url_host", "")),
        "metrics_endpoint": str(payload.get("metrics_endpoint", "")),
        "metrics_status": str(payload.get("metrics_status", "")),
        "required_metrics_present": str(payload.get("required_metrics_present", "")),
        "required_metric_count": str(payload.get("required_metric_count", "")),
        "metrics_sha256": str(payload.get("metrics_sha256", "")),
        "grafana_dashboard_status": str(
            payload.get("grafana_dashboard_status", "")
        ),
        "grafana_dashboard_sha256": str(
            payload.get("grafana_dashboard_sha256", "")
        ),
        "prometheus_rules_status": str(payload.get("prometheus_rules_status", "")),
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


def _internal_rollout_record(path: Path) -> Dict[str, Any]:
    payload = _read_json_file(path)
    status = str(payload.get("status", "unknown"))
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
        "sha256": str(payload.get("sha256", "")),
        "missing_fields": missing_fields,
    }


def _file_record(path: Path) -> Dict[str, str]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "file_name": path.name,
        "size_bytes": str(len(data)),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _read_json_file(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OSError(f"{path} must contain a JSON object")
    return payload


def _provider_smoke_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing = []
    if str(payload.get("evidence_schema_version", "")) != "1":
        missing.append("evidence_schema_version")
    for field in REQUIRED_PROVIDER_SMOKE_RUN_IDS:
        if not str(payload.get(field, "")).strip():
            missing.append(field)
    provider_snapshot = payload.get("provider_snapshot", {})
    if not isinstance(provider_snapshot, dict):
        provider_snapshot = {}
    for field in REQUIRED_PROVIDER_SMOKE_SNAPSHOT_FIELDS:
        if not str(provider_snapshot.get(field, "")).strip():
            missing.append(f"provider_snapshot.{field}")
    capability_checks = payload.get("capability_checks", {})
    if not isinstance(capability_checks, dict):
        capability_checks = {}
    for field in REQUIRED_PROVIDER_SMOKE_CAPABILITIES:
        if str(capability_checks.get(field, "")) != "passed":
            missing.append(f"capability_checks.{field}")
    if not _is_sha256(str(payload.get("runtime_effective_tool_policy_sha256", ""))):
        missing.append("runtime_effective_tool_policy_sha256")
    return sorted(missing)


def _staging_acceptance_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing = _schema_version_missing_fields(payload)
    missing.extend(_missing_string_fields(payload, REQUIRED_STAGING_ACCEPTANCE_FIELDS))
    missing.extend(_missing_value_fields(payload, REQUIRED_STAGING_ACCEPTANCE_VALUES))
    missing.extend(
        _missing_positive_int_fields(
            payload,
            REQUIRED_STAGING_ACCEPTANCE_POSITIVE_INTS,
        )
    )
    if not _is_sha256(str(payload.get("runtime_effective_tool_policy_sha256", ""))):
        missing.append("runtime_effective_tool_policy_sha256")
    return sorted(missing)


def _observability_acceptance_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing = _schema_version_missing_fields(payload)
    missing.extend(_missing_string_fields(
        payload,
        REQUIRED_OBSERVABILITY_ACCEPTANCE_FIELDS,
    ))
    missing.extend(
        _missing_value_fields(payload, REQUIRED_OBSERVABILITY_ACCEPTANCE_VALUES)
    )
    missing.extend(
        _missing_positive_int_fields(
            payload,
            ("required_metric_count",),
        )
    )
    for field in REQUIRED_OBSERVABILITY_ACCEPTANCE_SHA_FIELDS:
        if not _is_sha256(str(payload.get(field, ""))):
            missing.append(field)
    prometheus_query_status = str(payload.get("prometheus_query_status", ""))
    if prometheus_query_status not in {"passed", "not_configured"}:
        missing.append("prometheus_query_status")
    elif prometheus_query_status == "passed" and not _is_positive_int(
        payload.get("prometheus_result_count", "")
    ):
        missing.append("prometheus_result_count")
    return sorted(missing)


def _internal_rollout_missing_fields(payload: Dict[str, Any]) -> List[str]:
    missing = _schema_version_missing_fields(payload)
    missing.extend(_missing_string_fields(payload, REQUIRED_INTERNAL_ROLLOUT_FIELDS))
    missing.extend(
        _missing_value_fields(
            payload,
            {field: "true" for field in REQUIRED_INTERNAL_ROLLOUT_TRUE_FIELDS},
        )
    )
    if not _is_positive_int(payload.get("approver_role_count", "")):
        missing.append("approver_role_count")
    if not _is_sha256(str(payload.get("runtime_effective_tool_policy_sha256", ""))):
        missing.append("runtime_effective_tool_policy_sha256")
    if not _is_sha256(str(payload.get("sha256", ""))):
        missing.append("sha256")
    return sorted(missing)


def _missing_string_fields(
    payload: Dict[str, Any],
    fields: tuple[str, ...],
) -> List[str]:
    return [field for field in fields if not str(payload.get(field, "")).strip()]


def _schema_version_missing_fields(payload: Dict[str, Any]) -> List[str]:
    if str(payload.get("evidence_schema_version", "")) != "1":
        return ["evidence_schema_version"]
    return []


def _missing_value_fields(
    payload: Dict[str, Any],
    expected_values: Dict[str, str],
) -> List[str]:
    return [
        field
        for field, expected in expected_values.items()
        if str(payload.get(field, "")) != expected
    ]


def _missing_positive_int_fields(
    payload: Dict[str, Any],
    fields: tuple[str, ...],
) -> List[str]:
    return [field for field in fields if not _is_positive_int(payload.get(field, ""))]


def _is_positive_int(value: Any) -> bool:
    try:
        return int(str(value)) > 0
    except ValueError:
        return False


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _external_evidence_secret_findings(
    paths_by_label: Dict[str, Optional[Path]],
) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for label, path in paths_by_label.items():
        if path is None or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        findings.extend(_secret_findings(label, "$", payload))
    return findings


def _secret_findings(label: str, path: str, value: Any) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{_json_path_key(str(key))}"
            if _is_secret_like_key(str(key), item):
                findings.append(
                    {
                        "label": label,
                        "path": child_path,
                        "reason": "secret_like_key",
                    }
                )
            findings.extend(_secret_findings(label, child_path, item))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_secret_findings(label, f"{path}[{index}]", item))
    elif isinstance(value, str) and _is_secret_like_value(value):
        findings.append(
            {
                "label": label,
                "path": path,
                "reason": "secret_like_value",
            }
        )
    return findings


def _is_secret_like_key(key: str, value: Any) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in SECRET_KEY_ALLOWLIST:
        return False
    if not isinstance(value, str) or not value.strip():
        return False
    return any(token in normalized for token in SECRET_LIKE_KEYS)


def _is_secret_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)


def _json_path_key(key: str) -> str:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return key
    return json.dumps(key)


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _string_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, (str, int, float, bool))
    }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
