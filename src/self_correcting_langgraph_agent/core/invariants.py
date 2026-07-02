from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any, Dict, List


def validate_run_invariants(state: Dict[str, Any]) -> List[str]:
    issues = []
    events = state.get("events", [])
    node_counts = Counter(event["node"] for event in events)
    status = _value(state.get("status"))

    if len(state.get("plan_validations", [])) != len(state.get("plan", [])):
        issues.append("plan_validations count does not match plan")

    if node_counts["executor"] != len(state.get("execution_attempts", [])):
        issues.append("executor event count does not match execution_attempts")

    if node_counts["verifier"] != len(state.get("verification_results", [])):
        issues.append("verifier event count does not match verification_results")

    if node_counts["reflector"] != len(state.get("reflections", [])):
        issues.append("reflector event count does not match reflections")

    if state.get("retry_count", 0) != len(state.get("reflections", [])):
        issues.append("retry_count does not match reflections")

    if state.get("current_step", 0) != len(state.get("step_results", [])):
        issues.append("current_step does not match completed step_results")

    if status == "done" and state.get("current_step", 0) != len(state.get("plan", [])):
        issues.append("done status does not match completed plan")

    failed_verifications = [
        item for item in state.get("verification_results", []) if item["passed"] == "false"
    ]
    if status == "done" and len(failed_verifications) != len(state.get("reflections", [])):
        issues.append("done run failed verification count does not match reflections")

    return issues


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value
