from __future__ import annotations

import json
from typing import Any, Dict, List

from kagent.runtime.redaction import redact_runtime_text

RuntimeStep = Dict[str, str]


def derive_runtime_steps(payload: Dict[str, Any]) -> List[RuntimeStep]:
    """Project runtime trace data into a user-facing step view.

    This is intentionally derived from the existing trace payload. It is not
    execution state and must not drive policy, retries, resume, or persistence.
    """
    actions = _trace_actions(payload)
    observations_by_action_id = _observations_by_action_id(payload.get("observations"))
    pending = payload.get("pending_approval")
    pending_action_id = (
        str(pending.get("id", "")).strip() if isinstance(pending, dict) else ""
    )
    steps: List[RuntimeStep] = []
    for index, action in enumerate(actions, start=1):
        action_id = str(action.get("id", "")).strip()
        observation = observations_by_action_id.get(action_id, {})
        state = _step_state(
            observation.get("status"),
            pending=bool(action_id and action_id == pending_action_id),
        )
        title = _step_title(action, observation, state=state)
        detail = _step_detail(action, observation, state=state)
        step: RuntimeStep = {
            "index": str(index),
            "state": state,
            "title": redact_runtime_text(title),
        }
        if detail:
            step["detail"] = redact_runtime_text(detail)
        steps.append(step)
    if steps:
        return steps
    return _planner_failure_steps(payload)


def _trace_actions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = _planned_actions(payload.get("plans"))
    if actions:
        return actions
    return _latest_actions(payload)


def _planned_actions(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: List[Dict[str, Any]] = []
    action_indexes_by_id = {}
    for plan in value:
        if not isinstance(plan, dict):
            continue
        for action in _actions_from_plan(plan):
            action_id = str(action.get("id", "")).strip()
            if action_id and action_id in action_indexes_by_id:
                actions[action_indexes_by_id[action_id]] = action
                continue
            if action_id:
                action_indexes_by_id[action_id] = len(actions)
            actions.append(action)
    return actions


def _latest_actions(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return []
    return _actions_from_plan(plan)


def _actions_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = plan.get("actions")
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict) and str(action.get("tool", "")).strip() != "note"
    ]


def _observations_by_action_id(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    observations: Dict[str, Dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        action_id = str(item.get("action_id", "")).strip()
        if action_id:
            observations[action_id] = item
    return observations


def _step_state(status: Any, *, pending: bool) -> str:
    if pending or str(status).strip() == "requires_approval":
        return "waiting_approval"
    if str(status).strip() in {"ok", "done"}:
        return "done"
    if str(status).strip() == "failed":
        return "failed"
    return "pending"


def _step_title(
    action: Dict[str, Any],
    observation: Dict[str, Any],
    *,
    state: str,
) -> str:
    tool = str(action.get("tool", "")).strip()
    output = observation.get("output")
    if state == "done" and isinstance(output, dict):
        output_title = _title_from_tool_payload(tool, output, completed=True)
        if output_title:
            return output_title
    action_input = action.get("input")
    if isinstance(action_input, dict):
        input_title = _title_from_tool_payload(tool, action_input, completed=False)
        if input_title:
            return input_title
    reason = _one_line(action.get("reason"))
    return reason or "Complete action"


def _step_detail(
    action: Dict[str, Any],
    observation: Dict[str, Any],
    *,
    state: str,
) -> str:
    if state == "failed":
        return _one_line(observation.get("error")) or _one_line(
            observation.get("error_code")
        )
    if state == "waiting_approval":
        return _one_line(action.get("reason"))
    return ""


def _title_from_tool_payload(
    tool: str,
    payload: Dict[str, Any],
    *,
    completed: bool,
) -> str:
    prefix = {
        "apply_patch": "Updated files" if completed else "Update files",
        "artifact": "Created" if completed else "Create",
        "http_request": "Fetched" if completed else "Fetch",
        "list_files": "Listed files" if completed else "List files",
        "open_app": "Opened" if completed else "Open",
        "open_url": "Opened" if completed else "Open",
        "read_file": "Read" if completed else "Read",
        "revert_patch": "Restored files" if completed else "Restore files",
        "workspace_restore": "Restored" if completed else "Restore",
        "shell_command": "Ran command" if completed else "Run command",
    }.get(tool, "")
    if not prefix:
        return ""
    target = _tool_target(tool, payload)
    return " ".join(part for part in [prefix, target] if part)


def _tool_target(tool: str, payload: Dict[str, Any]) -> str:
    if tool in {"open_url", "http_request"}:
        return _short_value(payload.get("url", ""))
    if tool == "open_app":
        return _short_value(payload.get("application", ""))
    if tool == "read_file":
        return _short_value(payload.get("path", ""))
    if tool == "revert_patch":
        return _changed_files_label(payload.get("paths"))
    if tool == "list_files":
        return _short_value(payload.get("root", ""))
    if tool == "shell_command":
        return _short_value(payload.get("command", ""))
    if tool == "artifact":
        return _short_value(payload.get("title", ""))
    if tool == "workspace_restore":
        return _short_value(payload.get("path", ""))
    if tool == "apply_patch":
        return _changed_files_label(payload.get("changed_files"))
    return ""


def _changed_files_label(value: Any) -> str:
    if not isinstance(value, list) or not value:
        return ""
    paths = []
    for item in value[:3]:
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            if path:
                paths.append(path)
        else:
            text = _short_value(item)
            if text:
                paths.append(text)
    if len(value) > 3:
        paths.append(f"+{len(value) - 3} more")
    return ", ".join(paths)


def _planner_failure_steps(payload: Dict[str, Any]) -> List[RuntimeStep]:
    observations = payload.get("observations")
    if not isinstance(observations, list):
        return []
    for observation in reversed(observations):
        if not isinstance(observation, dict):
            continue
        if (
            str(observation.get("tool", "")).strip() == "planner"
            and str(observation.get("status", "")).strip() == "failed"
        ):
            detail = _one_line(observation.get("error")) or _one_line(
                observation.get("error_code")
            )
            step: RuntimeStep = {
                "index": "1",
                "state": "failed",
                "title": "Plan request",
            }
            if detail:
                step["detail"] = redact_runtime_text(detail)
            return [step]
    return []


def _one_line(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _short_value(value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = json.dumps(value)
    elif isinstance(value, (int, float)):
        text = str(value)
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(text.strip().split())
    if len(text) > 96:
        return text[:93] + "..."
    return text
