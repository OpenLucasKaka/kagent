#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from self_correcting_langgraph_agent import __version__

DEFAULT_EXPECTED_ENVIRONMENT = "internal-production"

REQUIRED_ROLES = (
    "business_owner",
    "security",
    "sre",
    "tech_lead",
)

REQUIRED_CHECKS = (
    "provider_smoke_attached",
    "staging_acceptance_attached",
    "observability_acceptance_attached",
    "tool_policy_reviewed",
    "team_access_reviewed",
    "trace_retention_reviewed",
    "rollback_rehearsed",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a redacted internal rollout sign-off JSON file.",
    )
    parser.add_argument(
        "--signoff",
        required=True,
        metavar="PATH",
        help="Internal rollout sign-off JSON produced by the rollout owner.",
    )
    parser.add_argument(
        "--expected-version",
        default=__version__,
        help="Release version that the sign-off must approve.",
    )
    parser.add_argument(
        "--expected-environment",
        default=DEFAULT_EXPECTED_ENVIRONMENT,
        help="Deployment environment that the sign-off must approve.",
    )
    args = parser.parse_args()
    payload = build_acceptance(
        Path(args.signoff),
        expected_version=args.expected_version,
        expected_environment=args.expected_environment,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


def build_acceptance(
    path: Path,
    *,
    expected_version: str = __version__,
    expected_environment: str = DEFAULT_EXPECTED_ENVIRONMENT,
) -> Dict[str, Any]:
    if not path.is_file():
        return _failed_payload(
            status="missing",
            missing_required_roles=list(REQUIRED_ROLES),
            failed_required_checks=list(REQUIRED_CHECKS),
            expected_version=expected_version,
            expected_environment=expected_environment,
        )
    content = path.read_bytes()
    try:
        signoff = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failed_payload(
            status="invalid_json",
            sha256=hashlib.sha256(content).hexdigest(),
            missing_required_roles=list(REQUIRED_ROLES),
            failed_required_checks=list(REQUIRED_CHECKS),
            expected_version=expected_version,
            expected_environment=expected_environment,
        )
    if not isinstance(signoff, dict):
        return _failed_payload(
            status="invalid",
            sha256=hashlib.sha256(content).hexdigest(),
            missing_required_roles=list(REQUIRED_ROLES),
            failed_required_checks=list(REQUIRED_CHECKS),
            expected_version=expected_version,
            expected_environment=expected_environment,
        )

    release_version = str(signoff.get("release_version", ""))
    environment = str(signoff.get("environment", ""))
    approver_roles = _approver_roles(signoff.get("approvers"))
    missing_roles = [role for role in REQUIRED_ROLES if role not in approver_roles]
    checks = signoff.get("checks")
    check_values = checks if isinstance(checks, dict) else {}
    failed_checks = [
        check for check in REQUIRED_CHECKS if check_values.get(check) is not True
    ]
    missing_metadata = [
        key
        for key in (
            "rollout_id",
            "release_version",
            "environment",
            "signed_off_at_utc",
        )
        if not str(signoff.get(key, "")).strip()
    ]
    runtime_policy_sha256 = str(
        signoff.get("runtime_effective_tool_policy_sha256", "")
    )
    if not _is_sha256(runtime_policy_sha256):
        missing_metadata.append("runtime_effective_tool_policy_sha256")
    mismatched_metadata = []
    if release_version and release_version != expected_version:
        mismatched_metadata.append("release_version")
    if environment and environment != expected_environment:
        mismatched_metadata.append("environment")
    status = "passed"
    if missing_roles or failed_checks or missing_metadata or mismatched_metadata:
        status = "failed"
    return {
        "evidence_schema_version": "1",
        "status": status,
        "rollout_id": str(signoff.get("rollout_id", "")),
        "release_version": release_version,
        "environment": environment,
        "signed_off_at_utc": str(signoff.get("signed_off_at_utc", "")),
        "runtime_effective_tool_policy_sha256": runtime_policy_sha256,
        "expected_release_version": expected_version,
        "expected_environment": expected_environment,
        "version_matches": str(release_version == expected_version).lower(),
        "environment_matches": str(environment == expected_environment).lower(),
        "required_roles_present": str(not missing_roles).lower(),
        "required_checks_passed": str(not failed_checks).lower(),
        "missing_required_roles": missing_roles,
        "failed_required_checks": failed_checks,
        "missing_metadata": missing_metadata,
        "mismatched_metadata": mismatched_metadata,
        "approver_role_count": str(len(approver_roles)),
        "approver_roles": sorted(approver_roles),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _approver_roles(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    roles = set()
    for item in value:
        if isinstance(item, dict):
            role = str(item.get("role", "")).strip()
            if role:
                roles.add(role)
    return sorted(roles)


def _failed_payload(
    *,
    status: str,
    missing_required_roles: List[str],
    failed_required_checks: List[str],
    expected_version: str,
    expected_environment: str,
    sha256: str = "",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_schema_version": "1",
        "status": status,
        "rollout_id": "",
        "release_version": "",
        "environment": "",
        "signed_off_at_utc": "",
        "expected_release_version": expected_version,
        "expected_environment": expected_environment,
        "version_matches": "false",
        "environment_matches": "false",
        "required_roles_present": "false",
        "required_checks_passed": "false",
        "missing_required_roles": missing_required_roles,
        "failed_required_checks": failed_required_checks,
        "missing_metadata": [
            "rollout_id",
            "release_version",
            "environment",
            "signed_off_at_utc",
            "runtime_effective_tool_policy_sha256",
        ],
        "mismatched_metadata": [],
        "approver_role_count": "0",
        "approver_roles": [],
    }
    if sha256:
        payload["sha256"] = sha256
    return payload


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


if __name__ == "__main__":
    raise SystemExit(main())
