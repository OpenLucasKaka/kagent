from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any, Dict, List


def summarize_run(state: Dict[str, Any]) -> Dict[str, Any]:
    node_counts = Counter(event["node"] for event in state.get("events", []))
    status = _json_value(state.get("status"))
    tool_calls = state.get("tool_calls", [])
    failed_verifications = [
        item for item in state.get("verification_results", []) if item["passed"] == "false"
    ]
    reflection_reasons = [
        item["reason"] for item in state.get("reflections", [])
    ]
    reflection_reason_counts = Counter(reflection_reasons)
    faults = [
        item["fault"]
        for item in state.get("execution_attempts", [])
        if item.get("fault")
    ]
    return {
        "status": status,
        "answer": state.get("answer"),
        "run_id": state.get("run_id", ""),
        "started_at": state.get("started_at", ""),
        "completed_at": state.get("completed_at", ""),
        "duration_seconds": state.get("duration_seconds", "0.0000"),
        "planned_steps": str(len(state.get("plan", []))),
        "completed_steps": str(state.get("current_step", 0)),
        "retry_count": str(state.get("retry_count", 0)),
        "failed_verifications": str(len(failed_verifications)),
        "recovered": str(status == "done" and bool(failed_verifications)).lower(),
        "reflection_reasons": reflection_reasons,
        "reflection_reason_counts": {
            reason: str(count)
            for reason, count in sorted(reflection_reason_counts.items())
        },
        "tool_call_count": str(len(tool_calls)),
        "tool_names": _unique_tool_names(tool_calls),
        "node_counts": {
            node: str(count)
            for node, count in sorted(node_counts.items())
        },
        "faults": faults,
        "errors": list(state.get("errors", [])),
    }


def _unique_tool_names(tool_calls: List[Dict[str, str]]) -> List[str]:
    names = []
    for call in tool_calls:
        name = call["tool"]
        if name not in names:
            names.append(name)
    return names


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value
