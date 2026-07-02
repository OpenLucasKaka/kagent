from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs

from self_correcting_langgraph_agent.runtime import RUNTIME_TRACE_TYPE
from self_correcting_langgraph_agent.service import errors as service_errors
from self_correcting_langgraph_agent.service.errors import failure_payload
from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.service.safety import safe_trace_file_stem
from self_correcting_langgraph_agent.service.trace_store import load_trace_by_run_id
from self_correcting_langgraph_agent.utils.json_output import json_ready

_TRACE_READ_ERRORS = (OSError, ValueError)
_RUNTIME_STATUS_FILTER_VALUES = {"cancelled", "done", "failed", "requires_approval"}


def execute_runtime_status_request(
    run_id: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime status",
        )
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
    try:
        trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if trace is None or not is_runtime_trace(trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    if not _runtime_trace_visible(trace, request_auth_subject, request_auth_is_admin):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    return 200, json_ready(runtime_status_summary(trace, service_config.trace_dir, run_id))


def execute_runtime_list_request(
    query: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime run listing",
        )
    try:
        limit = _runtime_list_limit(query)
        cursor_key = _runtime_list_cursor_key(query)
        filters = _runtime_list_filters(query)
    except ValueError as exc:
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    trace_dir = Path(service_config.trace_dir)
    summaries = []
    next_cursor = ""
    has_more = False
    for trace_path in sorted(
        trace_dir.glob("*.json"),
        key=_trace_file_sort_key,
        reverse=True,
    ):
        sort_key = _trace_file_sort_key(trace_path)
        if cursor_key is not None and sort_key >= cursor_key:
            continue
        try:
            trace = load_trace_by_run_id(trace_path.stem, service_config.trace_dir)
        except _TRACE_READ_ERRORS:
            continue
        if trace is None or not is_runtime_trace(trace):
            continue
        summary = runtime_status_summary(trace, service_config.trace_dir, trace_path.stem)
        if not _runtime_summary_visible(
            summary,
            request_auth_subject,
            request_auth_is_admin,
        ):
            continue
        if not _runtime_summary_matches_filters(summary, filters):
            continue
        if len(summaries) >= limit:
            has_more = True
            break
        summaries.append(_runtime_list_summary(summary))
        next_cursor = _encode_runtime_list_cursor(sort_key)
    if not has_more:
        next_cursor = ""
    return 200, json_ready(
        {
            "runs": summaries,
            "count": str(len(summaries)),
            "next_cursor": next_cursor,
            "has_more": str(has_more).lower(),
        }
    )


def execute_runtime_summary_request(
    query: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime run summary",
        )
    try:
        filters = _runtime_list_filters(query)
    except ValueError as exc:
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    aggregate = _empty_runtime_summary_aggregate()
    trace_dir = Path(service_config.trace_dir)
    for trace_path in sorted(
        trace_dir.glob("*.json"),
        key=_trace_file_sort_key,
        reverse=True,
    ):
        try:
            trace = load_trace_by_run_id(trace_path.stem, service_config.trace_dir)
        except _TRACE_READ_ERRORS:
            continue
        if trace is None or not is_runtime_trace(trace):
            continue
        summary = runtime_status_summary(trace, service_config.trace_dir, trace_path.stem)
        if not _runtime_summary_visible(
            summary,
            request_auth_subject,
            request_auth_is_admin,
        ):
            continue
        if not _runtime_summary_matches_filters(summary, filters):
            continue
        _add_runtime_summary_to_aggregate(aggregate, summary)
    return 200, json_ready(aggregate)


def execute_runtime_approvals_request(
    query: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime approvals",
        )
    try:
        limit = _runtime_list_limit(query)
        filters = _runtime_list_filters(query)
    except ValueError as exc:
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    approvals = []
    trace_dir = Path(service_config.trace_dir)
    for trace_path in sorted(
        trace_dir.glob("*.json"),
        key=_trace_file_sort_key,
        reverse=True,
    ):
        try:
            trace = load_trace_by_run_id(trace_path.stem, service_config.trace_dir)
        except _TRACE_READ_ERRORS:
            continue
        if trace is None or not is_runtime_trace(trace):
            continue
        summary = runtime_status_summary(trace, service_config.trace_dir, trace_path.stem)
        if not _runtime_summary_visible(
            summary,
            request_auth_subject,
            request_auth_is_admin,
        ):
            continue
        if not _runtime_approval_matches_filters(summary, filters):
            continue
        approvals.append(_runtime_approval_summary(summary))
        if len(approvals) >= limit:
            break
    return 200, json_ready(
        {
            "trace_type": RUNTIME_TRACE_TYPE,
            "count": str(len(approvals)),
            "approvals": approvals,
        }
    )


def execute_runtime_approvals_summary_request(
    query: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime approvals summary",
        )
    try:
        filters = _runtime_list_filters(query)
    except ValueError as exc:
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    aggregate = _empty_runtime_approval_summary()
    trace_dir = Path(service_config.trace_dir)
    for trace_path in sorted(
        trace_dir.glob("*.json"),
        key=_trace_file_sort_key,
        reverse=True,
    ):
        try:
            trace = load_trace_by_run_id(trace_path.stem, service_config.trace_dir)
        except _TRACE_READ_ERRORS:
            continue
        if trace is None or not is_runtime_trace(trace):
            continue
        summary = runtime_status_summary(trace, service_config.trace_dir, trace_path.stem)
        if not _runtime_summary_visible(
            summary,
            request_auth_subject,
            request_auth_is_admin,
        ):
            continue
        if not _runtime_approval_matches_filters(summary, filters):
            continue
        _add_runtime_approval_to_summary(aggregate, summary)
    return 200, json_ready(aggregate)


def execute_runtime_artifact_request(
    run_id: str,
    artifact_id: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime artifact lookup",
        )
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
    if not artifact_id.strip():
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "artifact_id is required",
        )
    try:
        trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if trace is None or not is_runtime_trace(trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    if not _runtime_trace_visible(trace, request_auth_subject, request_auth_is_admin):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime artifact not found")
    artifact = _runtime_trace_artifact(trace, artifact_id)
    if artifact is None:
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime artifact not found")
    return 200, json_ready(
        {
            "trace_type": RUNTIME_TRACE_TYPE,
            "run_id": str(trace.get("run_id", run_id)),
            "trace_path": _runtime_trace_path(trace, service_config.trace_dir, run_id),
            "action_id": artifact["action_id"],
            "tool": artifact["tool"],
            "artifact": artifact["artifact"],
        }
    )


def execute_runtime_artifacts_request(
    run_id: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime artifact listing",
        )
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
    try:
        trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if trace is None or not is_runtime_trace(trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    if not _runtime_trace_visible(trace, request_auth_subject, request_auth_is_admin):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    artifacts = _runtime_trace_artifacts(trace)
    return 200, json_ready(
        {
            "trace_type": RUNTIME_TRACE_TYPE,
            "run_id": str(trace.get("run_id", run_id)),
            "trace_path": _runtime_trace_path(trace, service_config.trace_dir, run_id),
            "count": str(len(artifacts)),
            "artifacts": artifacts,
        }
    )


def execute_runtime_timeline_request(
    run_id: str,
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime timeline",
        )
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
    try:
        trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if trace is None or not is_runtime_trace(trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    if not _runtime_trace_visible(trace, request_auth_subject, request_auth_is_admin):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    events = _runtime_timeline_events(trace.get("events"))
    observations = _runtime_timeline_observations(trace.get("observations"))
    progress_events = _runtime_timeline_progress_events(trace.get("progress_events"))
    return 200, json_ready(
        {
            "trace_type": RUNTIME_TRACE_TYPE,
            "run_id": str(trace.get("run_id", run_id)),
            "trace_path": _runtime_trace_path(trace, service_config.trace_dir, run_id),
            "event_count": str(len(events)),
            "progress_event_count": str(len(progress_events)),
            "observation_count": str(len(observations)),
            "events": events,
            "progress_events": progress_events,
            "observations": observations,
        }
    )


def is_runtime_trace(trace: Dict[str, Any]) -> bool:
    return trace.get("trace_type") == RUNTIME_TRACE_TYPE


def _runtime_trace_visible(
    trace: Dict[str, Any],
    request_auth_subject: str,
    request_auth_is_admin: bool,
) -> bool:
    if request_auth_is_admin or not request_auth_subject:
        return True
    return str(trace.get("auth_subject", "")) == request_auth_subject


def _runtime_summary_visible(
    summary: Dict[str, Any],
    request_auth_subject: str,
    request_auth_is_admin: bool,
) -> bool:
    if request_auth_is_admin or not request_auth_subject:
        return True
    return str(summary.get("auth_subject", "")) == request_auth_subject


def runtime_status_summary(
    trace: Dict[str, Any],
    trace_dir: str,
    requested_run_id: str,
) -> Dict[str, Any]:
    run_id = str(trace.get("run_id", requested_run_id))
    observations = trace.get("observations")
    artifact_ids = _observation_artifact_ids(observations)
    approved_action_ids = _trace_approved_action_ids(trace)
    pending_approval = trace.get("pending_approval")
    latest_failed_observation = _latest_failed_observation(observations)
    summary = {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": str(trace.get("status", "")),
        "goal": str(trace.get("goal", "")),
        "auth_subject": str(trace.get("auth_subject", "")),
        "metadata": _trace_metadata(trace),
        "metadata_keys": _trace_metadata_keys(trace),
        "tags": _trace_tags(trace),
        "trace_path": str(
            trace.get("trace_path")
            or Path(trace_dir) / f"{safe_trace_file_stem(run_id)}.json"
        ),
        "iteration_count": _runtime_iteration_count(trace),
        "max_iterations": str(trace.get("max_iterations", "")),
        "iteration_budget_remaining": _runtime_iteration_budget_remaining(trace),
        "plan_count": str(_list_count(trace.get("plans"))),
        "observation_count": str(_list_count(observations)),
        "event_count": str(_list_count(trace.get("events"))),
        "progress_event_count": str(_list_count(trace.get("progress_events"))),
        "failed_observation_count": str(
            _observation_status_count(observations, "failed")
        ),
        "planner_failure_count": str(
            _failed_observation_tool_count(observations, "planner")
        ),
        "tool_failure_count": str(
            _failed_non_planner_observation_count(observations)
        ),
        "approval_required_count": str(
            _observation_status_count(observations, "requires_approval")
        ),
        "latest_failed_action_id": _observation_field(
            latest_failed_observation,
            "action_id",
        ),
        "latest_failed_tool": _observation_field(latest_failed_observation, "tool"),
        "latest_failed_error_code": _observation_field(
            latest_failed_observation,
            "error_code",
        ),
        "pending_approval_action_id": _pending_approval_field(
            pending_approval,
            "id",
        ),
        "pending_approval_tool": _pending_approval_field(
            pending_approval,
            "tool",
        ),
        "pending_age_seconds": _pending_age_seconds(
            pending_approval,
            trace_dir,
            run_id,
        ),
        "approved_action_count": str(len(approved_action_ids)),
        "approved_action_ids": approved_action_ids,
        "error_code_counts": _observation_error_code_counts(observations),
        "latest_plan_action_count": str(_latest_plan_action_count(trace.get("plan"))),
        "latest_plan_action_ids": _latest_plan_action_ids(trace.get("plan")),
        "dependency_edge_count": str(_plan_dependency_edge_count(trace.get("plan"))),
        "tool_names": _observation_tool_names(observations),
        "artifact_count": str(len(artifact_ids)),
        "artifact_ids": artifact_ids,
        "artifact_kinds": _observation_artifact_kinds(observations),
        "artifact_formats": _observation_artifact_formats(observations),
        "artifact_tags": _observation_artifact_tags(observations),
        "artifact_total_bytes": str(_observation_artifact_total_bytes(observations)),
        "artifact_bytes_by_kind": _observation_artifact_bytes_by_kind(observations),
    }
    for optional_field in [
        "answer",
        "final_answer_guardrail",
        "error_code",
        "error",
        "pending_approval",
        "resumed_from_run_id",
        "resumed_by_auth_subject",
        "cancelled_at",
        "cancelled_by_auth_subject",
        "cancel_reason",
        "started_at",
        "completed_at",
        "duration_seconds",
    ]:
        if optional_field in trace:
            summary[optional_field] = trace[optional_field]
    return summary


def _runtime_list_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    list_summary = dict(summary)
    list_summary.pop("pending_approval", None)
    return list_summary


def _runtime_approval_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    approval = {
        "run_id": str(summary.get("run_id", "")),
        "status": str(summary.get("status", "")),
        "goal": str(summary.get("goal", "")),
        "auth_subject": str(summary.get("auth_subject", "")),
        "trace_path": str(summary.get("trace_path", "")),
        "pending_approval_action_id": str(
            summary.get("pending_approval_action_id", "")
        ),
        "pending_approval_tool": str(summary.get("pending_approval_tool", "")),
    }
    for optional_field in ["started_at", "duration_seconds", "pending_age_seconds"]:
        if optional_field in summary:
            approval[optional_field] = str(summary[optional_field])
    return approval


def _empty_runtime_approval_summary() -> Dict[str, Any]:
    return {
        "trace_type": RUNTIME_TRACE_TYPE,
        "pending_approval_count": "0",
        "stale_pending_count": "0",
        "max_pending_age_seconds": "0",
        "auth_subject_counts": {},
        "tool_counts": {},
    }


def _add_runtime_approval_to_summary(
    aggregate: Dict[str, Any],
    summary: Dict[str, Any],
) -> None:
    aggregate["pending_approval_count"] = str(
        int(aggregate["pending_approval_count"]) + 1
    )
    aggregate["stale_pending_count"] = str(int(aggregate["stale_pending_count"]) + 1)
    aggregate["max_pending_age_seconds"] = str(
        max(
            _parse_non_negative_int(aggregate["max_pending_age_seconds"]),
            _parse_non_negative_int(summary.get("pending_age_seconds")),
        )
    )
    _increment_count(
        aggregate["auth_subject_counts"],
        str(summary.get("auth_subject", "")),
    )
    _increment_count(
        aggregate["tool_counts"],
        str(summary.get("pending_approval_tool", "")),
    )


def _runtime_approval_matches_filters(
    summary: Dict[str, Any],
    filters: Dict[str, Any],
) -> bool:
    if not str(summary.get("pending_approval_action_id", "")).strip() and not str(
        summary.get("pending_approval_tool", "")
    ).strip():
        return False
    if (
        filters.get("tool") is not None
        and summary.get("pending_approval_tool") != filters["tool"]
    ):
        return False
    summary_filters = dict(filters)
    summary_filters["tool"] = None
    return _runtime_summary_matches_filters(summary, summary_filters)


def _empty_runtime_summary_aggregate() -> Dict[str, Any]:
    return {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_count": "0",
        "status_counts": {},
        "auth_subject_counts": {},
        "tool_counts": {},
        "error_code_counts": {},
        "failed_observation_count": "0",
        "approval_required_count": "0",
        "pending_approval_count": "0",
        "final_answer_guardrail_applied_count": "0",
        "final_answer_guardrail_reason_counts": {},
        "artifact_count": "0",
        "artifact_total_bytes": "0",
        "tag_counts": {},
        "metadata_key_counts": {},
    }


def _add_runtime_summary_to_aggregate(
    aggregate: Dict[str, Any],
    summary: Dict[str, Any],
) -> None:
    aggregate["run_count"] = str(int(aggregate["run_count"]) + 1)
    _increment_count(aggregate["status_counts"], str(summary.get("status", "")))
    _increment_count(
        aggregate["auth_subject_counts"],
        str(summary.get("auth_subject", "")),
    )
    for tool_name in summary.get("tool_names", []):
        _increment_count(aggregate["tool_counts"], str(tool_name))
    error_code_counts = summary.get("error_code_counts")
    if isinstance(error_code_counts, dict):
        for error_code, count in error_code_counts.items():
            _increment_count(
                aggregate["error_code_counts"],
                str(error_code),
                _parse_non_negative_int(count),
            )
    aggregate["failed_observation_count"] = str(
        int(aggregate["failed_observation_count"])
        + _parse_non_negative_int(summary.get("failed_observation_count"))
    )
    aggregate["approval_required_count"] = str(
        int(aggregate["approval_required_count"])
        + _parse_non_negative_int(summary.get("approval_required_count"))
    )
    if str(summary.get("pending_approval_action_id", "")).strip() or str(
        summary.get("pending_approval_tool", "")
    ).strip():
        aggregate["pending_approval_count"] = str(
            int(aggregate["pending_approval_count"]) + 1
        )
    guardrail = summary.get("final_answer_guardrail")
    if isinstance(guardrail, dict) and guardrail.get("applied") == "true":
        aggregate["final_answer_guardrail_applied_count"] = str(
            int(aggregate["final_answer_guardrail_applied_count"]) + 1
        )
        _increment_count(
            aggregate["final_answer_guardrail_reason_counts"],
            str(guardrail.get("reason", "")),
        )
    aggregate["artifact_count"] = str(
        int(aggregate["artifact_count"])
        + _parse_non_negative_int(summary.get("artifact_count"))
    )
    aggregate["artifact_total_bytes"] = str(
        int(aggregate["artifact_total_bytes"])
        + _parse_non_negative_int(summary.get("artifact_total_bytes"))
    )
    for tag in summary.get("tags", []):
        _increment_count(aggregate["tag_counts"], str(tag))
    for metadata_key in summary.get("metadata_keys", []):
        _increment_count(aggregate["metadata_key_counts"], str(metadata_key))


def _increment_count(
    counts: Dict[str, str],
    key: str,
    amount: int = 1,
) -> None:
    if not key.strip() or amount <= 0:
        return
    counts[key] = str(int(counts.get(key, "0")) + amount)


def _parse_non_negative_int(value: Any) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _runtime_iteration_count(trace: Dict[str, Any]) -> str:
    value = trace.get("iteration_count")
    if value is not None:
        return str(value)
    return str(_list_count(trace.get("plans")))


def _runtime_iteration_budget_remaining(trace: Dict[str, Any]) -> str:
    value = trace.get("iteration_budget_remaining")
    if value is not None:
        return str(value)
    iteration_count = _parse_int_string(_runtime_iteration_count(trace))
    max_iterations = _parse_int_string(trace.get("max_iterations"))
    if iteration_count is None or max_iterations is None:
        return ""
    return str(max(0, max_iterations - iteration_count))


def _parse_int_string(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _trace_approved_action_ids(trace: Dict[str, Any]) -> list[str]:
    value = trace.get("approved_action_ids")
    if not isinstance(value, list):
        return []
    return sorted(
        {
            action_id
            for action_id in value
            if isinstance(action_id, str) and action_id.strip()
        }
    )


def _trace_metadata(trace: Dict[str, Any]) -> Dict[str, str]:
    value = trace.get("metadata")
    if not isinstance(value, dict):
        return {}
    metadata = {
        str(key): str(metadata_value)
        for key, metadata_value in value.items()
        if str(key).strip()
    }
    return {key: metadata[key] for key in sorted(metadata)}


def _trace_metadata_keys(trace: Dict[str, Any]) -> list[str]:
    return sorted(_trace_metadata(trace))


def _trace_tags(trace: Dict[str, Any]) -> list[str]:
    value = trace.get("tags")
    if not isinstance(value, list):
        return []
    return sorted(
        {
            tag
            for tag in value
            if isinstance(tag, str) and tag.strip()
        }
    )


def _pending_approval_field(value: Any, field: str) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get(field, ""))


def _pending_age_seconds(
    pending_approval: Any,
    trace_dir: str,
    run_id: str,
) -> str:
    if not isinstance(pending_approval, dict):
        return ""
    trace_path = Path(trace_dir) / f"{safe_trace_file_stem(run_id)}.json"
    try:
        age_seconds = int(max(0.0, time.time() - trace_path.stat().st_mtime))
    except OSError:
        return ""
    return str(age_seconds)


def _latest_failed_observation(value: Any) -> Dict[str, Any]:
    if not isinstance(value, list):
        return {}
    for item in reversed(value):
        if isinstance(item, dict) and str(item.get("status", "")) == "failed":
            return item
    return {}


def _observation_field(value: Dict[str, Any], field: str) -> str:
    return str(value.get(field, "")) if value else ""


def _observation_status_count(value: Any, status: str) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict) and str(item.get("status", "")) == status
    )


def _failed_observation_tool_count(value: Any, tool: str) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict)
        and str(item.get("status", "")) == "failed"
        and str(item.get("tool", "")) == tool
    )


def _failed_non_planner_observation_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict)
        and str(item.get("status", "")) == "failed"
        and str(item.get("tool", "")) != "planner"
    )


def _observation_tool_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tool_names = {
        str(item.get("tool", ""))
        for item in value
        if isinstance(item, dict) and str(item.get("tool", "")).strip()
    }
    return sorted(tool_names)


def _observation_error_code_counts(value: Any) -> Dict[str, str]:
    if not isinstance(value, list):
        return {}
    counts: Dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        error_code = str(item.get("error_code", ""))
        if not error_code.strip():
            continue
        counts[error_code] = counts.get(error_code, 0) + 1
    return {error_code: str(counts[error_code]) for error_code in sorted(counts)}


def _latest_plan_actions(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    actions = value.get("actions")
    if not isinstance(actions, list):
        return []
    return [action for action in actions if isinstance(action, dict)]


def _latest_plan_action_count(value: Any) -> int:
    return len(_latest_plan_actions(value))


def _latest_plan_action_ids(value: Any) -> list[str]:
    return [
        str(action.get("id", ""))
        for action in _latest_plan_actions(value)
        if str(action.get("id", "")).strip()
    ]


def _plan_dependency_edge_count(value: Any) -> int:
    edge_count = 0
    for action in _latest_plan_actions(value):
        depends_on = action.get("depends_on")
        if isinstance(depends_on, list):
            edge_count += len(depends_on)
    return edge_count


def _observation_artifact_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    artifact_ids = {
        str(output.get("artifact_id", ""))
        for item in value
        if isinstance(item, dict)
        for output in [item.get("output")]
        if isinstance(output, dict) and str(output.get("artifact_id", "")).strip()
    }
    return sorted(artifact_ids)


def _observation_artifact_kinds(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    artifact_kinds = {
        str(output.get("kind", ""))
        for item in value
        if isinstance(item, dict)
        for output in [item.get("output")]
        if isinstance(output, dict)
        and str(output.get("artifact_id", "")).strip()
        and str(output.get("kind", "")).strip()
    }
    return sorted(artifact_kinds)


def _observation_artifact_formats(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    artifact_formats = {
        str(output.get("format", ""))
        for item in value
        if isinstance(item, dict)
        for output in [item.get("output")]
        if isinstance(output, dict)
        and str(output.get("artifact_id", "")).strip()
        and str(output.get("format", "")).strip()
    }
    return sorted(artifact_formats)


def _observation_artifact_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    artifact_tags = {
        tag.strip()
        for item in value
        if isinstance(item, dict)
        for output in [item.get("output")]
        if isinstance(output, dict)
        and str(output.get("artifact_id", "")).strip()
        for tags in [output.get("tags")]
        if isinstance(tags, list)
        for tag in tags
        if isinstance(tag, str) and tag.strip()
    }
    return sorted(artifact_tags)


def _observation_artifact_total_bytes(value: Any) -> int:
    return sum(byte_count for _, byte_count in _observation_artifact_byte_records(value))


def _observation_artifact_bytes_by_kind(value: Any) -> Dict[str, str]:
    counts: Dict[str, int] = {}
    for kind, byte_count in _observation_artifact_byte_records(value):
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + byte_count
    return {kind: str(counts[kind]) for kind in sorted(counts)}


def _observation_artifact_byte_records(value: Any) -> list[tuple[str, int]]:
    if not isinstance(value, list):
        return []
    records: Dict[str, tuple[str, int]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if not isinstance(output, dict):
            continue
        artifact_id = str(output.get("artifact_id", "")).strip()
        if not artifact_id or artifact_id in records:
            continue
        byte_count = _artifact_byte_count(output.get("bytes"))
        if byte_count is None:
            continue
        records[artifact_id] = (str(output.get("kind", "")).strip(), byte_count)
    return [records[artifact_id] for artifact_id in sorted(records)]


def _artifact_byte_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _runtime_trace_artifact(
    trace: Dict[str, Any],
    artifact_id: str,
) -> Dict[str, Any] | None:
    observations = trace.get("observations")
    if not isinstance(observations, list):
        return None
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        output = observation.get("output")
        if not isinstance(output, dict):
            continue
        if output.get("artifact_id") != artifact_id:
            continue
        return {
            "action_id": str(observation.get("action_id", "")),
            "tool": str(observation.get("tool", "")),
            "artifact": output,
        }
    return None


def _runtime_trace_artifacts(trace: Dict[str, Any]) -> list[Dict[str, Any]]:
    observations = trace.get("observations")
    if not isinstance(observations, list):
        return []
    artifacts = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        output = observation.get("output")
        if not isinstance(output, dict):
            continue
        artifact_id = str(output.get("artifact_id", ""))
        if not artifact_id.strip():
            continue
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "action_id": str(observation.get("action_id", "")),
                "tool": str(observation.get("tool", "")),
                "title": str(output.get("title", "")),
                "kind": str(output.get("kind", "")),
                "format": str(output.get("format", "")),
                "tags": output.get("tags") if isinstance(output.get("tags"), list) else [],
                "bytes": str(output.get("bytes", "")),
            }
        )
    return artifacts


def _runtime_timeline_events(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    fields = [
        "node",
        "status",
        "iteration",
        "action_id",
        "tool",
        "reason",
        "action_count",
        "duration_seconds",
    ]
    events = []
    for item in value:
        if not isinstance(item, dict):
            continue
        event = {
            field: str(item[field])
            for field in fields
            if field in item and str(item[field]).strip()
        }
        depends_on = item.get("depends_on")
        if isinstance(depends_on, list):
            event["depends_on"] = [
                dependency
                for dependency in depends_on
                if isinstance(dependency, str) and dependency.strip()
            ]
        dependency_statuses = item.get("dependency_statuses")
        if isinstance(dependency_statuses, dict):
            event["dependency_statuses"] = {
                str(action_id): str(status)
                for action_id, status in dependency_statuses.items()
                if str(action_id).strip() and str(status).strip()
            }
        if event:
            events.append(event)
    return events


def _runtime_timeline_observations(value: Any) -> list[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    observations = []
    for item in value:
        if not isinstance(item, dict):
            continue
        observation = {
            "action_id": str(item.get("action_id", "")),
            "tool": str(item.get("tool", "")),
            "status": str(item.get("status", "")),
        }
        error_code = str(item.get("error_code", ""))
        if error_code.strip():
            observation["error_code"] = error_code
        output = item.get("output")
        if isinstance(output, dict) and str(output.get("artifact_id", "")).strip():
            observation["artifact_id"] = str(output["artifact_id"])
        observations.append(observation)
    return observations


def _runtime_timeline_progress_events(value: Any) -> list[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    fields = [
        "type",
        "node",
        "status",
        "iteration",
        "action_id",
        "tool",
        "reason",
        "error_code",
        "action_count",
        "iteration_count",
        "duration_seconds",
    ]
    progress_events = []
    for item in value:
        if not isinstance(item, dict):
            continue
        event = {
            field: str(item[field])
            for field in fields
            if field in item and str(item[field]).strip()
        }
        if event:
            progress_events.append(event)
    return progress_events


def _runtime_trace_path(
    trace: Dict[str, Any],
    trace_dir: str,
    requested_run_id: str,
) -> str:
    return str(
        trace.get("trace_path")
        or Path(trace_dir) / f"{safe_trace_file_stem(requested_run_id)}.json"
    )


def _trace_file_sort_key(path: Path) -> tuple[int, str]:
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return (mtime_ns, path.stem)


def _encode_runtime_list_cursor(sort_key: tuple[int, str]) -> str:
    raw_cursor = f"{sort_key[0]}:{sort_key[1]}".encode("utf-8")
    return base64.urlsafe_b64encode(raw_cursor).decode("ascii").rstrip("=")


def _decode_runtime_list_cursor(value: str) -> tuple[int, str]:
    padding = "=" * (-len(value) % 4)
    try:
        raw_cursor = base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("cursor must be a valid runtime list cursor") from exc
    mtime_ns_raw, separator, trace_stem = raw_cursor.partition(":")
    if (
        separator != ":"
        or not mtime_ns_raw.isdigit()
        or not trace_stem
    ):
        raise ValueError("cursor must be a valid runtime list cursor")
    return (int(mtime_ns_raw), trace_stem)


def _runtime_list_limit(query: str) -> int:
    values = parse_qs(query).get("limit", ["50"])
    try:
        limit = int(values[0])
    except ValueError as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if limit < 1 or limit > 100:
        raise ValueError("limit must be an integer between 1 and 100")
    return limit


def _runtime_list_cursor_key(query: str) -> tuple[int, str] | None:
    values = parse_qs(query, keep_blank_values=True)
    cursor = _single_query_value(values, "cursor")
    if cursor is None:
        return None
    if not cursor.strip():
        raise ValueError("cursor must be a non-empty string")
    return _decode_runtime_list_cursor(cursor)


def _runtime_list_filters(query: str) -> Dict[str, Any]:
    values = parse_qs(query, keep_blank_values=True)
    status = _single_query_value(values, "status")
    if status is not None and status not in _RUNTIME_STATUS_FILTER_VALUES:
        raise ValueError(
            "status must be one of: cancelled, done, failed, requires_approval"
        )
    auth_subject = _single_query_value(values, "auth_subject")
    if auth_subject is not None and not auth_subject.strip():
        raise ValueError("auth_subject must be a non-empty string")
    tool = _single_query_value(values, "tool")
    if tool is not None and not tool.strip():
        raise ValueError("tool must be a non-empty string")
    error_code = _single_query_value(values, "error_code")
    if error_code is not None and not error_code.strip():
        raise ValueError("error_code must be a non-empty string")
    latest_failed_error_code = _single_query_value(values, "latest_failed_error_code")
    if latest_failed_error_code is not None and not latest_failed_error_code.strip():
        raise ValueError("latest_failed_error_code must be a non-empty string")
    latest_failed_action_id = _single_query_value(values, "latest_failed_action_id")
    if latest_failed_action_id is not None and not latest_failed_action_id.strip():
        raise ValueError("latest_failed_action_id must be a non-empty string")
    latest_failed_tool = _single_query_value(values, "latest_failed_tool")
    if latest_failed_tool is not None and not latest_failed_tool.strip():
        raise ValueError("latest_failed_tool must be a non-empty string")
    iteration_budget_remaining = _single_query_value(
        values,
        "iteration_budget_remaining",
    )
    if (
        iteration_budget_remaining is not None
        and not iteration_budget_remaining.strip()
    ):
        raise ValueError("iteration_budget_remaining must be a non-negative integer")
    if (
        iteration_budget_remaining is not None
        and not iteration_budget_remaining.isdigit()
    ):
        raise ValueError("iteration_budget_remaining must be a non-negative integer")
    artifact_kind = _single_query_value(values, "artifact_kind")
    if artifact_kind is not None and not artifact_kind.strip():
        raise ValueError("artifact_kind must be a non-empty string")
    artifact_format = _single_query_value(values, "artifact_format")
    if artifact_format is not None and not artifact_format.strip():
        raise ValueError("artifact_format must be a non-empty string")
    artifact_tag = _single_query_value(values, "artifact_tag")
    if artifact_tag is not None and not artifact_tag.strip():
        raise ValueError("artifact_tag must be a non-empty string")
    tag = _single_query_value(values, "tag")
    if tag is not None and not tag.strip():
        raise ValueError("tag must be a non-empty string")
    metadata_key = _single_query_value(values, "metadata_key")
    if metadata_key is not None and not metadata_key.strip():
        raise ValueError("metadata_key must be a non-empty string")
    metadata_value = _single_query_value(values, "metadata_value")
    if metadata_value is not None and not metadata_value.strip():
        raise ValueError("metadata_value must be a non-empty string")
    approved_action_id = _single_query_value(values, "approved_action_id")
    if approved_action_id is not None and not approved_action_id.strip():
        raise ValueError("approved_action_id must be a non-empty string")
    resumed_from_run_id = _single_query_value(values, "resumed_from_run_id")
    if resumed_from_run_id is not None and not resumed_from_run_id.strip():
        raise ValueError("resumed_from_run_id must be a non-empty string")
    resumed_by_auth_subject = _single_query_value(values, "resumed_by_auth_subject")
    if resumed_by_auth_subject is not None and not resumed_by_auth_subject.strip():
        raise ValueError("resumed_by_auth_subject must be a non-empty string")
    pending_approval_tool = _single_query_value(values, "pending_approval_tool")
    if pending_approval_tool is not None and not pending_approval_tool.strip():
        raise ValueError("pending_approval_tool must be a non-empty string")
    pending_approval_action_id = _single_query_value(
        values,
        "pending_approval_action_id",
    )
    if (
        pending_approval_action_id is not None
        and not pending_approval_action_id.strip()
    ):
        raise ValueError("pending_approval_action_id must be a non-empty string")
    final_answer_guardrail_reason = _single_query_value(
        values,
        "final_answer_guardrail_reason",
    )
    if (
        final_answer_guardrail_reason is not None
        and not final_answer_guardrail_reason.strip()
    ):
        raise ValueError("final_answer_guardrail_reason must be a non-empty string")
    min_pending_age_seconds = _single_query_value(values, "min_pending_age_seconds")
    if (
        min_pending_age_seconds is not None
        and not min_pending_age_seconds.strip()
    ):
        raise ValueError("min_pending_age_seconds must be a non-negative integer")
    if (
        min_pending_age_seconds is not None
        and not min_pending_age_seconds.isdigit()
    ):
        raise ValueError("min_pending_age_seconds must be a non-negative integer")
    has_artifacts_value = _single_query_value(values, "has_artifacts")
    has_errors_value = _single_query_value(values, "has_errors")
    has_failures_value = _single_query_value(values, "has_failures")
    has_approvals_value = _single_query_value(values, "has_approvals")
    has_pending_approval_value = _single_query_value(values, "has_pending_approval")
    has_final_answer_guardrail_value = _single_query_value(
        values,
        "has_final_answer_guardrail",
    )
    return {
        "status": status,
        "auth_subject": auth_subject,
        "tool": tool,
        "error_code": error_code,
        "latest_failed_error_code": latest_failed_error_code,
        "latest_failed_action_id": latest_failed_action_id,
        "latest_failed_tool": latest_failed_tool,
        "iteration_budget_remaining": iteration_budget_remaining,
        "artifact_kind": artifact_kind,
        "artifact_format": artifact_format,
        "artifact_tag": artifact_tag,
        "tag": tag,
        "metadata_key": metadata_key,
        "metadata_value": metadata_value,
        "approved_action_id": approved_action_id,
        "resumed_from_run_id": resumed_from_run_id,
        "resumed_by_auth_subject": resumed_by_auth_subject,
        "pending_approval_tool": pending_approval_tool,
        "pending_approval_action_id": pending_approval_action_id,
        "final_answer_guardrail_reason": final_answer_guardrail_reason,
        "min_pending_age_seconds": min_pending_age_seconds,
        "has_artifacts": _parse_optional_boolean(
            has_artifacts_value,
            field_name="has_artifacts",
        ),
        "has_errors": _parse_optional_boolean(
            has_errors_value,
            field_name="has_errors",
        ),
        "has_failures": _parse_optional_boolean(
            has_failures_value,
            field_name="has_failures",
        ),
        "has_approvals": _parse_optional_boolean(
            has_approvals_value,
            field_name="has_approvals",
        ),
        "has_pending_approval": _parse_optional_boolean(
            has_pending_approval_value,
            field_name="has_pending_approval",
        ),
        "has_final_answer_guardrail": _parse_optional_boolean(
            has_final_answer_guardrail_value,
            field_name="has_final_answer_guardrail",
        ),
    }


def _single_query_value(values: Dict[str, list[str]], key: str) -> str | None:
    if key not in values:
        return None
    return values[key][0]


def _parse_optional_boolean(value: str | None, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{field_name} must be true or false")


def _runtime_summary_matches_filters(
    summary: Dict[str, Any],
    filters: Dict[str, Any],
) -> bool:
    status = filters["status"]
    if status is not None and summary.get("status") != status:
        return False
    auth_subject = filters["auth_subject"]
    if auth_subject is not None and summary.get("auth_subject") != auth_subject:
        return False
    tool = filters["tool"]
    if tool is not None and tool not in summary.get("tool_names", []):
        return False
    error_code = filters["error_code"]
    error_code_counts = summary.get("error_code_counts")
    if (
        error_code is not None
        and (
            not isinstance(error_code_counts, dict)
            or error_code not in error_code_counts
        )
    ):
        return False
    latest_failed_error_code = filters["latest_failed_error_code"]
    if (
        latest_failed_error_code is not None
        and summary.get("latest_failed_error_code") != latest_failed_error_code
    ):
        return False
    latest_failed_action_id = filters["latest_failed_action_id"]
    if (
        latest_failed_action_id is not None
        and summary.get("latest_failed_action_id") != latest_failed_action_id
    ):
        return False
    latest_failed_tool = filters["latest_failed_tool"]
    if (
        latest_failed_tool is not None
        and summary.get("latest_failed_tool") != latest_failed_tool
    ):
        return False
    iteration_budget_remaining = filters["iteration_budget_remaining"]
    if (
        iteration_budget_remaining is not None
        and summary.get("iteration_budget_remaining") != iteration_budget_remaining
    ):
        return False
    artifact_kind = filters["artifact_kind"]
    if (
        artifact_kind is not None
        and artifact_kind not in summary.get("artifact_kinds", [])
    ):
        return False
    artifact_format = filters["artifact_format"]
    if (
        artifact_format is not None
        and artifact_format not in summary.get("artifact_formats", [])
    ):
        return False
    artifact_tag = filters["artifact_tag"]
    if (
        artifact_tag is not None
        and artifact_tag not in summary.get("artifact_tags", [])
    ):
        return False
    tag = filters["tag"]
    if tag is not None and tag not in summary.get("tags", []):
        return False
    metadata_key = filters["metadata_key"]
    metadata_value = filters["metadata_value"]
    metadata = summary.get("metadata")
    if metadata_key is not None:
        if not isinstance(metadata, dict) or metadata_key not in metadata:
            return False
        if metadata_value is not None and metadata.get(metadata_key) != metadata_value:
            return False
    elif metadata_value is not None:
        if not isinstance(metadata, dict) or metadata_value not in metadata.values():
            return False
    approved_action_id = filters["approved_action_id"]
    if (
        approved_action_id is not None
        and approved_action_id not in summary.get("approved_action_ids", [])
    ):
        return False
    resumed_from_run_id = filters["resumed_from_run_id"]
    if (
        resumed_from_run_id is not None
        and summary.get("resumed_from_run_id") != resumed_from_run_id
    ):
        return False
    resumed_by_auth_subject = filters["resumed_by_auth_subject"]
    if (
        resumed_by_auth_subject is not None
        and summary.get("resumed_by_auth_subject") != resumed_by_auth_subject
    ):
        return False
    pending_approval_tool = filters["pending_approval_tool"]
    if (
        pending_approval_tool is not None
        and summary.get("pending_approval_tool") != pending_approval_tool
    ):
        return False
    pending_approval_action_id = filters["pending_approval_action_id"]
    if (
        pending_approval_action_id is not None
        and summary.get("pending_approval_action_id") != pending_approval_action_id
    ):
        return False
    final_answer_guardrail_reason = filters["final_answer_guardrail_reason"]
    guardrail = summary.get("final_answer_guardrail")
    if final_answer_guardrail_reason is not None:
        if not isinstance(guardrail, dict):
            return False
        if guardrail.get("reason") != final_answer_guardrail_reason:
            return False
    min_pending_age_seconds = filters["min_pending_age_seconds"]
    if min_pending_age_seconds is not None and _parse_non_negative_int(
        summary.get("pending_age_seconds")
    ) < int(min_pending_age_seconds):
        return False
    has_artifacts = filters["has_artifacts"]
    if (
        has_artifacts is not None
        and (summary.get("artifact_count") != "0") != has_artifacts
    ):
        return False
    has_errors = filters["has_errors"]
    if has_errors is not None and _runtime_summary_has_errors(summary) != has_errors:
        return False
    has_failures = filters["has_failures"]
    if (
        has_failures is not None
        and (summary.get("failed_observation_count") != "0") != has_failures
    ):
        return False
    has_approvals = filters["has_approvals"]
    if (
        has_approvals is not None
        and (summary.get("approved_action_count") != "0") != has_approvals
    ):
        return False
    has_pending_approval = filters["has_pending_approval"]
    if has_pending_approval is not None:
        pending_action_id = str(summary.get("pending_approval_action_id", ""))
        pending_tool = str(summary.get("pending_approval_tool", ""))
        if (bool(pending_action_id or pending_tool)) != has_pending_approval:
            return False
    has_final_answer_guardrail = filters["has_final_answer_guardrail"]
    if has_final_answer_guardrail is not None:
        guardrail_applied = (
            isinstance(guardrail, dict) and guardrail.get("applied") == "true"
        )
        if guardrail_applied != has_final_answer_guardrail:
            return False
    return True


def _runtime_summary_has_errors(summary: Dict[str, Any]) -> bool:
    error_code_counts = summary.get("error_code_counts")
    if isinstance(error_code_counts, dict) and len(error_code_counts) > 0:
        return True
    return bool(str(summary.get("error_code", "")).strip())
